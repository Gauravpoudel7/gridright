# GridRight — Seller Onboarding & Meter Binding Flow

## Objective
Implement the seller signup/signin flow with meter binding, wallet activation, and the associated state machine. This supersedes the original single-step "form → operator approves → done" design with a state-tracked pipeline that separates identity approval, meter binding, and wallet activation.

Legal/regulatory documentation compliance (KYC policy, retention rules, consent language) is explicitly out of scope for this phase — focus is the functional state machine and the security patterns (signed proofs, credential handling, auditability) around it.

## 1. Data model changes

`profiles` table (or a new `seller_applications` table if that fits the existing schema better — agent's call):
- `application_status` enum: `submitted | identity_approved | identity_rejected`
- `rejection_reason` (nullable text)
- `meter_binding_status` enum: `unbound | pairing_pending | bound | binding_failed`
- `meter_id` (nullable, only set once binding succeeds — never set at submission time)
- `community_pool_id` FK (nullable until operator assigns it during identity review)
- `wallet_status` enum: `not_connected | active`
- `wallet_address` (nullable until first successful signed connect)
- `must_change_password` boolean, default true, set true whenever operator issues initial credentials

New `wallet_history` table:
- `id`, `profile_id` FK, `old_wallet` (nullable for first connect), `new_wallet`, `changed_at`, `signature_verified` boolean

No new table needed for pairing itself — GridRight just stores the outcome (`meter_id`) once the virtual-smart-meter service confirms the pairing-code exchange.

## 2. State machine

**Application**
`submitted → identity_approved` (operator approves), or `→ identity_rejected` (with reason; applicant can edit and resubmit → back to `submitted`).

**Meter binding** (only reachable after `identity_approved`)
`unbound → pairing_pending` (seller submits pairing code) → `bound` (code exchanged for owner credential via the virtual-smart-meter service, `meter_id` recorded), or `→ binding_failed` (invalid/expired/already-claimed code — seller can retry, operator can reissue a code).
`bound` is terminal and irreversible — no unbind/transfer path.

**Wallet**
`not_connected → active` on first successful signed wallet connect. Stays `active` through any later wallet change — it never reverts to `not_connected`.

**Credential/login**
On `identity_approved`: create the Supabase auth user, generate a temporary password, **email it** to the applicant's Gmail with login instructions, and set `must_change_password = true`.
On first login, if `must_change_password` is true, force the seller through a password-change screen before any other route (dashboard, meter binding, wallet connect) is reachable — enforce this server-side via the existing proxy/role-check pattern, not just a client-side redirect.

## 3. Flows

### 3.1 Identity review
- Applicant submits name, DOB, house-ownership documentation, Gmail, location (free text at this stage).
- Operator reviews in the operator dashboard; on approve, operator also assigns `community_pool_id` from existing pools (auto-resolution from location can be a later enhancement, not required now).
- On approve: create auth user, generate temp password, email it, set `must_change_password = true`, `application_status = identity_approved`.
- On reject: set `identity_rejected` + `rejection_reason`; applicant can resubmit, which resets `application_status = submitted`.

### 3.2 Meter binding
- Only shown once `application_status = identity_approved`.
- Seller enters the meter's **pairing code** (from the physical device/install docs) — not a free-text meter ID.
- Backend calls the virtual-smart-meter service's pairing endpoint to exchange the code for an owner credential.
- Success: store `meter_id`, set `meter_binding_status = bound`. Enforce uniqueness so a `meter_id` already bound elsewhere cannot be bound again — return `binding_failed` with an "already claimed" reason in that case.
- Failure (expired/invalid/already claimed): `binding_failed`, show reason, allow retry with a new code (operator can reissue via the meter service).
- Once `bound`, permanent — no UI path to unbind or rebind a different meter to this profile.

### 3.3 Wallet activation
- Available once `meter_binding_status = bound` and the password has been changed.
- Wallet connect requires a **signed challenge**: backend issues a nonce, the wallet signs it, backend verifies the signature server-side before accepting the address. Never accept a pasted/typed address without signature proof.
- First successful signed connect: `wallet_status = active`, log to `wallet_history` (`old_wallet = null`, `new_wallet`, `signature_verified = true`).
- Later wallet changes: same signed-challenge requirement; log to `wallet_history`. The new wallet takes effect starting the **next** settlement cycle only — any settlement already computed/in-flight against the old wallet is unaffected.

### 3.4 Meter readings before wallet activation
- Readings continue to be ingested and stored via the virtual-smart-meter service regardless of `wallet_status` — do not pause ingestion.
- The recommendation/settlement engine excludes any profile with `wallet_status = not_connected` from settlement runs (readings accumulate, nothing is paid out yet).
- Decide explicitly (and document in the phase report) whether backlog readings from meter-binding to wallet-activation get settled retroactively once the wallet goes active, or only readings from activation forward count — pick one, don't leave it implicit.

## 4. Security requirements
- Temp password: sufficient entropy, never logged in plaintext anywhere (app logs, error tracking).
- Password-change gate enforced server-side — a direct API call while `must_change_password = true` should be rejected for any endpoint except the password-change one itself.
- Wallet signature verification happens server-side only; never trust a client-asserted "signature valid" flag.
- Pairing-code exchange is rate-limited per profile to prevent brute-forcing meter codes.

## 5. Tests to add
- Application transitions: submitted → approved/rejected → resubmit.
- Meter binding: successful bind, expired code, already-claimed meter, retry after failure.
- Uniqueness: two profiles cannot bind the same `meter_id` (DB-level and API-level).
- `must_change_password` gate: temp-password login blocks all routes except password change; clears after change.
- Wallet: signed connect succeeds, invalid/unsigned attempt rejected, wallet change applies only to future settlements (test with a settlement mid-flight at the moment of change).
- Readings-before-activation: readings ingested and stored while `wallet_status = not_connected`, excluded from settlement runs until active.

## 6. Explicit non-goals for this phase
- No legal/regulatory documentation requirements (KYC policy, retention, consent language) — functional flow only.
- No auto-resolution of location → `community_pool` (operator assigns manually for now).
- No meter unbinding/transfer path — intentionally excluded, not an oversight.
- No decision baked in yet for backlog-vs-forward-only settlement on wallet activation (see 3.4) — implementer picks one and flags it in the phase report for review.
