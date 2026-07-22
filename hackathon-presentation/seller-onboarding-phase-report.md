# Seller Onboarding & Meter Binding — Phase Report

## Summary

Full-stack implementation of the GridRight seller onboarding flow, covering DB migration, FastAPI services/routers/tests, and Next.js pages/components/server actions.

**Test results (final run, post-verification pass):** 188 passed, 7 skipped, 0 failed.

---

## What was built

### 1. DB migration (`supabase/migrations/20250722000011_seller_onboarding.sql`)

- New tables: `seller_applications`, `wallet_history`, `wallet_challenges`, `meter_pairing_attempts`
- New columns on `profiles`: `meter_binding_status`, `meter_id` (unique), `community_pool_id`, `wallet_status`, `must_change_password`
- New column on `contributions`: `payout_wallet`
- Updated `handle_new_user` trigger

### 2. API services (`apps/api/app/services/`)

| File | Responsibility |
|---|---|
| `onboarding.py` | Application submit/approve/reject/resubmit; `ApplicationStore` ABC + `SupabaseApplicationStore`; `Emailer` ABC + `SMTPEmailer` (prod) / `ConsoleEmailer` (explicit dev opt-in only) |
| `meter_binding.py` | Pairing-code exchange with virtual-smart-meter service; `PairingClient` ABC + `HTTPPairingClient`/`SimulatedPairingClient`; rate-limit + state machine (`unbound→pairing_pending→bound/binding_failed`) |
| `wallet_activation.py` | ed25519 challenge/verify via `solders`; `issue_challenge`, `verify_and_connect`, `wallet_history` logging |
| `password_gate.py` | `must_change_password` flag; `PasswordGateStore` ABC + `SupabasePasswordGateStore`; `change_password` |

### 3. API routers (`apps/api/app/routers.py`)

New endpoints added:

```
POST   /api/v1/applications                              (public submit)
GET    /api/v1/applications/{id}/status                  (edit-token gated)
PUT    /api/v1/applications/{id}                         (edit-token gated resubmit)
GET    /api/v1/operator/applications
POST   /api/v1/operator/applications/{id}/approve
POST   /api/v1/operator/applications/{id}/reject
POST   /api/v1/sellers/me/meter-binding
GET    /api/v1/sellers/me/meter-binding
POST   /api/v1/sellers/me/wallet/challenge
POST   /api/v1/sellers/me/wallet/verify
POST   /api/v1/sellers/me/change-password
```

`get_password_changed_seller` dependency gates all seller routes except `/change-password`.

### 4. Settlement exclusion (`apps/api/app/services/wallet.py`, `exception_queue.py`)

- `get_active_wallet` returns wallet only when `wallet_status='active'`
- `payout_wallet` snapshotted on `contributions` at insert time — wallet changes never rewrite existing rows
- Readings between meter-binding and wallet-activation are stored but **never settled retroactively** (forward-only, spec §3.4/§6)

### 5. Web — server actions (`apps/web/src/app/actions/`)

| File | Actions |
|---|---|
| `onboarding.ts` | `submitApplicationAction`, `checkApplicationStatusAction`, `resubmitApplicationAction`, `approveApplicationAction`, `rejectApplicationAction` |
| `password.ts` | `changePasswordAction` |
| `meter-binding.ts` | `submitPairingCodeAction` |
| `wallet-activation.ts` | `requestWalletChallengeAction`, `verifyWalletSignatureAction` |

### 6. Web — pages (`apps/web/src/app/`)

| Route | Description |
|---|---|
| `/apply` | Public seller application form + status checker / resubmit |
| `/change-password` | Forced password change for operator-provisioned sellers |

### 7. Web — components (`apps/web/src/components/`)

| File | Description |
|---|---|
| `meter-binding-section.tsx` | Pairing-code form; status badge; permanent once bound |
| `wallet-activate.tsx` | Challenge → `signMessage` → verify flow; replaces trust-the-browser pattern |

### 8. Web — operator dashboard (`apps/web/src/app/operator/dashboard/`)

- `applications-review.tsx` — approve (with pool assignment) / reject (with reason) panel
- `page.tsx` — fetches pending applications + community pools; renders Identity Review section above the exception queue

### 9. Middleware (`apps/web/src/proxy.ts`)

- Fetches `must_change_password` alongside `role` in a single Supabase query
- Redirects `/dashboard/*` → `/change-password` when flag is set
- Added `/change-password` to the matcher (no loop — the page itself is never redirected)

---

## Architecture decisions

- **Applicants have no auth row until approval** — `seller_applications` is a separate table; the edit token is the only credential before approval.
- **Virtual-smart-meter pairing** uses a swappable `PairingClient` ABC; `SimulatedPairingClient` encodes outcome in the code prefix for dev/test.
- **Wallet signature verification is server-side** via `solders` (ed25519); the client never asserts validity.
- **Settlement is forward-only** — readings before `wallet_status=active` are stored but never settled retroactively. This is enforced in `get_active_wallet` and documented in the service layer.
- **`payout_wallet` is snapshotted at contribution time** — changing a wallet never rewrites settled rows.
- **Password-change gate is dual-enforced** — FastAPI dependency rejects API calls; Next.js middleware redirects the UI. Neither alone is sufficient.

---

## Verification pass (four review items)

1. **Meter-binding immutability (server-side)** — PASS. `submit_pairing_code` rejects with 409 when `meter_binding_status = bound`, before the rate-limit check and before any pairing exchange. Tests: `test_bound_is_terminal`, `test_rebind_after_bound_does_not_reach_pairing_service` (spy client proves the exchange is never invoked on the rejected rebind; `meter_id` and status unchanged).
2. **Rate limiting** — PASS (enforcing, not log-only). `count_recent_attempts` over a 10-minute sliding window gates the exchange at 5 attempts/profile with a 429. Tests: `test_rate_limit_blocks_burst` (lockout + window slide), `test_rate_limit_short_circuits_before_pairing_service` (spy client proves the pairing service is not reached while locked out).
3. **The 7 skipped tests** — all genuinely infra-dependent, none are onboarding-spec tests: 6× `test_e2e_devnet.py` (need `RUN_DEVNET_E2E=1` + live Solana devnet + funded keypair) and 1× `test_migration.py::test_migration_end_to_end` (needs `DATABASE_URL` to a real Postgres). The requested scenarios all run and pass: meter-uniqueness (`test_meter_uniqueness_across_profiles` + `test_meter_uniqueness_db_level`), wallet-change-mid-settlement (`test_wallet_change_does_not_touch_in_flight_contribution`), password gate (`test_password_gate.py`, 4 tests).
4. **Temp password handling** — FIXED. The plaintext password reaches only the email body; log lines carry the recipient/application id, never the password (asserted by `test_smtp_emailer_send_never_logs_password`, `test_console_emailer_never_logs_password`). Gap found and closed: `SMTPEmailer` previously degraded to a silent no-op when `SMTP_HOST` was unset, so a misconfigured prod deploy would approve sellers whose credentials went nowhere. Now transport selection fails loudly: SMTP when `SMTP_HOST` is set; `ConsoleEmailer` only behind explicit `GRIDRIGHT_ALLOW_CONSOLE_EMAIL=1`; otherwise `RuntimeError` — raised in `approve_application` BEFORE the auth user is created (`test_approve_fails_loud_before_side_effects_when_email_unconfigured`).

**Deploy note:** production (Render) must set `SMTP_HOST/PORT/USER/PASS/FROM`; local dev sets `GRIDRIGHT_ALLOW_CONSOLE_EMAIL=1`. With neither, operator approval returns 500 by design.

---

## How to verify end-to-end

1. **API tests:** `cd apps/api && python -m pytest tests/ -q` → 180 passed, 7 skipped
2. **Apply flow:** visit `/apply`, submit a form, copy the application ID + edit token
3. **Operator review:** log in as operator, go to `/operator/dashboard`, approve the application (assign a pool) — seller receives email with temp password
4. **Password change:** seller logs in, is redirected to `/change-password`, sets new password → lands on `/dashboard`
5. **Meter binding:** on `/dashboard`, enter a pairing code (prefix `OK` for simulated success) → status becomes `bound`
6. **Wallet activation:** connect a Solana wallet, click "Verify & activate" → backend issues challenge, wallet signs, backend verifies ed25519 → `wallet_status=active`
7. **Settlement gate:** submit a reading before wallet activation → stored but not settled; submit after → settled normally
