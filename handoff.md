# GridRight — Handoff Notes (2026-07-20)

Pickup point for a fresh chat. Read this top-to-bottom; everything else you
need (architecture, phases, this handoff) is in the repo root.

---

## 1. What this is

**GridRight** — AI-assisted, utility-moderated settlement platform for
distributed solar energy on Solana.

- **Seller** role: rooftop solar producer. Submits surplus kWh per
  period. Gets paid in SOL (placeholder rate: **1 SOL = 15,000 ¢**).
- **Operator** role: runs the community pool. Approves/adjusts/rejects
  AI recommendations that fall outside the policy band, triggers
  payouts, sees pool stats.
- **AI** is a *recommender only*. The deterministic operator_policy
  decides auto-approve vs needs-review. This split is sacred — do not
  merge them.
- **Anchor program** (on-chain) handles the actual SOL transfer from
  operator wallet → seller wallet via `system_program::transfer` CPI.
  Off-chain (Supabase) holds the full record; only a hash/commitment
  is on-chain.

**Source of truth:** `gridright_architecture.md` at repo root.
**Phase plan:** `phases.md` at repo root (Phase 0 → Phase 9).

---

## 2. Repo layout

```
apps/
  web/         Next.js 16 App Router (React 19, Server Actions, Proxy)
  api/         FastAPI + Pydantic, JWT (HS256/ES256/JWKS)
  (no backend/src, it's app/)
programs/
  gridright/   Anchor 0.32.1, devnet-deployed
supabase/
  migrations/  Numbered SQL files
docs/
  phantom-qa-checklist.md   ← manual browser QA (Phase 10 scope)
handoff.md                  ← this file
README.md, phases.md, gridright_architecture.md
```

Frontend testing: Vitest + @testing-library/react.
Backend testing: pytest.
Anchor testing: `anchor test` (mocha + ts-node).

---

## 3. Where we are

**Done:** Phases 0–9 (full regression green).
**Just finished:** Phase 10 (Phantom wallet + Demo + Realtime, see §5).
**Manual browser QA still pending** — see `docs/phantom-qa-checklist.md`.

**Last verified state** (before this handoff):
- `curl http://localhost:8000/health` → `{"status":"ok"}`
- `curl -o /dev/null -w "%{http_code}" http://localhost:3000` → `200`
- 41 frontend tests, 109 backend tests, 9 Anchor tests on devnet — all passing.

---

## 4. Hard constraints (read before touching anything)

These came from the user and have to be respected across the whole project:

- **Do not break Phases 0–5.** Auth, schema, recommendation/policy logic
  are stable. New work is additive only. If a refactor seems needed, ask first.
- **Demo is genuinely self-contained.** `/demo` must NOT touch the real
  backend, the real Supabase, or the real chain. The proxy matcher must
  never match it. There is a test that asserts this.
- **PLACEHOLDER convention.** Anything that's a stand-in (the 15,000 ¢
  / SOL rate, the 15% spread, the ±5% policy band, badge thresholds
  100/500/1000 kWh) is named `PLACEHOLDER` or kept in a clearly-labeled
  constants file. Don't inline the magic numbers.
- **No breaking existing tests.** Frontend (41), backend (109), Anchor
  (9) all green before any new work.

---

## 5. Phase 10 — what was built (the "just finished" section)

Three deliverables, all in `apps/web/`:

### 5a. Phantom wallet connection (seller + operator)

**Goal:** real SOL payouts from operator → seller via Phantom, on devnet.

Files created / modified:
- `supabase/migrations/20250720000006_add_wallet_address.sql` — adds
  nullable `wallet_address` to `profiles`, RLS for own-wallet update.
- `apps/web/src/components/wallet-providers.tsx` — wraps app in
  `ConnectionProvider` (devnet RPC), `WalletProvider`, `WalletModalProvider`.
- `apps/web/src/components/wallet-connect.tsx` — `WalletMultiButton` +
  `useEffect` to upsert pubkey to `profiles.wallet_address`.
- `apps/web/src/lib/solana-constants.ts` — `SOL_PRICE_CENTS = 15_000`,
  `LAMPORTS_PER_SOL`, `centsToLamports()`.
- `apps/web/src/hooks/use-pay-seller.ts` — builds `pay_seller`
  instruction **manually** (no generated IDL client) with discriminator
  `[193, 245, 214, 255, 208, 113, 43, 124]`, sends via
  `wallet.sendTransaction`, then writes pending → confirmed to Supabase.
- `apps/web/src/app/layout.tsx` — wraps children in `<WalletProviders>`.
- `apps/web/src/app/dashboard/seller-dashboard-client.tsx` — wallet
  connect row, realtime-aware history.
- `apps/web/src/app/operator/dashboard/operator-feed-client.tsx` —
  wallet connect row, `PayButton` (gated on operator wallet connected
  AND seller wallet saved), realtime feed.
- `apps/web/src/app/dashboard/page.tsx` — shell.
- `apps/web/src/app/operator/dashboard/page.tsx` — shell.
- `apps/api/app/services/wallet.py` — `get_wallet_address()`,
  `require_wallet()`, `require_wallet_for_seller_id()`. The last two
  bypass enforcement in `SUPABASE_AUTH_TESTING=1` mode (test mode).
- `apps/api/app/routers.py` — wired `require_wallet(_operator)` into
  `resolve_review`, `require_wallet_for_seller_id(req.seller_id)` into
  `recommend_endpoint`.
- `programs/gridright/programs/gridright/src/lib.rs` — added
  `pay_seller` instruction with errors `SellerMismatch`, `ZeroPayout`.
  `PLACEHOLDER SOL_PRICE_CENTS: u64 = 15_000`, `cents_to_lamports()`.
  `PaySeller` accounts: settlement, seller_wallet (mut), operator
  (mut, signer), system_program.

Tests:
- `apps/api/tests/test_wallet_requirement.py` — operator resolve and
  seller recommend with/without wallet.
- `apps/web/src/__tests__/use-realtime-table.test.ts` — channel
  subscribe + payload dispatch.
- `apps/web/src/__tests__/operator-payout-gate.test.tsx` — PayButton
  hidden until operator wallet + seller wallet both present. Uses
  `new PublicKey("11111111111111111111111111111111")` for valid base58
  in mocks.

### 5b. Pre-login demo at `/demo`

**Goal:** isolated, public, no backend/chain calls. Safe to delete
entirely by removing the `src/app/demo/` and `src/features/demo/`
folders.

Files (all prefixed with `// DEMO-ONLY: safe to delete`):
- `apps/web/src/app/demo/page.tsx`
- `apps/web/src/features/demo/mock-data.ts`
- `apps/web/src/features/demo/use-demo-state.ts`
- `apps/web/src/app/page.tsx` — added "Try the Demo" button.

Demo simulates auto-approve vs operator-review flows with mock wallets,
mock pool, fake tx signatures. Pure client-side state machine.

Test guarding isolation:
- `apps/web/src/__tests__/proxy-demo-exclusion.test.ts` — imports
  `config` from `apps/web/src/proxy.ts`, asserts the matcher does not
  cover `/demo`, sanity-checks `/dashboard/:path*` and
  `/operator/dashboard/:path*` are still matched.

### 5c. Realtime everywhere

- `apps/web/src/hooks/use-realtime-table.ts` — `useEffect`-based
  Supabase channel subscription with `postgres_changes` listener,
  cleans up on unmount.
- Live indicator: small pulse dot next to "Pool feed" / dashboard
  headers, driven by channel `SUBSCRIBED` status, greys out on
  disconnect.

### 5d. Cleanup items (also Phase 10)

- `1 SOL = 15,000 ¢` is in one place: `apps/web/src/lib/solana-constants.ts`
  (frontend) and the Rust `PLACEHOLDER SOL_PRICE_CENTS` constant
  (program). They must stay in sync; no third copy.
- `/demo` proxy exclusion test exists.
- `docs/phantom-qa-checklist.md` — 5 scenarios (wrong network, reject
  connection, reject signing, insufficient balance, mid-flow
  disconnect) for a human to run with a real browser + Phantom
  extension.

---

## 6. Operational gotchas (learned the hard way)

1. **Local Supabase is the source of truth for dev.**
   `apps/web/.env.local` points to `http://127.0.0.1:54321`. The
   hosted Supabase URL+key in there previously did NOT match each
   other (URL was project A, key was project B, both 401'd). The
   file has a comment block explaining how to switch to hosted.

2. **Supabase starts separately.** If the API returns
   `connect ECONNREFUSED 127.0.0.1:8000`, that's the FastAPI backend
   being down — not Supabase. Restart:
   ```bash
   cd apps/api
   SUPABASE_URL=... SUPABASE_SERVICE_KEY=... uvicorn app.main:app --reload
   ```
   (The actual env values are in `apps/api/.env` or your shell env.)

3. **Anchor build artifacts go stale.** If an Anchor test fails with
   `InstructionFallbackNotFound`, the `.so` in
   `programs/gridright/target/deploy/` may be older than your source.
   Copy fresh: `cp programs/gridright/target/deploy/gridright.so
   target/deploy/gridright.so` (or just `anchor build && anchor
   deploy --provider.cluster devnet`).

4. **Discriminator is not guessed.** `use-pay-seller.ts` reads it
   from `target/idl/gridright.json`. For `pay_seller`:
   `[193, 245, 214, 255, 208, 113, 43, 124]`. If you add a new
   instruction, regenerate the IDL and re-read.

5. **React 19 + wallet adapter.** The wallet adapter used to try to
   downgrade `react-dom` to 16.x. Locked in root `package.json`:
   ```json
   "overrides": {
     "react": "19.2.4",
     "react-dom": "19.2.4"
   }
   ```
   Don't remove the overrides.

6. **Test mode.** `SUPABASE_AUTH_TESTING=1` bypasses the wallet gate
   on the backend. Keep it set in CI. Don't accidentally ship a
   release with it on.

7. **Devnet program ID:** `88HxyoRrb9NzqWfk34SCoqHZcMFxmmHg6XVNpcVPxoFL`.
   Devnet badge tree: `FRAgmb48t9MgDvWgAC64wvNNgNse9m256Km1dREAF7j7`.

---

## 7. What's open / next

**Manual QA (human, not me):**
- `docs/phantom-qa-checklist.md` — needs a real browser with Phantom
  extension. Five failure cases must all leave `contributions.status`
  unchanged and produce no partial transfers.

**UI design direction (just discussed, not implemented):**
The user asked what UI would look good, simple, business-attractive.
I proposed:
- **Style:** Linear/Stripe/Vercel — restrained palette, generous
  whitespace, Inter or Geist, 1px borders no shadows, no gradients.
- **Palette:** off-white background, slate text, one accent
  (deep green `#0F766E` or Solana purple `#9945FF`).
- **Layout:** shared top bar (wallet pill + avatar), sidebar nav,
  card-grid main. Seller = "My Home" with Next Credit / Production
  chart / Pending settlements. Operator = split-view Pool Console
  (queue left, detail right).
- **Signatures:** transaction pulse on payout rows, tabular kWh/$ in
  tables, Live dot for realtime, inline confirmation (no modals),
  one-CTA empty states.
- **Stack:** no new deps — shadcn/Radix primitives + Tailwind.

User was about to choose where to start (sketch components vs
flesh out one dashboard). That decision is undecided.

**Anything else you discover:** surface it before changing, not after.

---

## 8. To start work in a new chat

1. Read this file.
2. Read `gridright_architecture.md`.
3. Read `phases.md` for the phase you're in.
4. Confirm health before coding:
   ```bash
   curl -s http://localhost:8000/health       # → {"status":"ok"}
   curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000   # → 200
   ```
5. Run the test suite you expect to keep green:
   ```bash
   cd apps/web && npx vitest run
   cd apps/api && pytest
   cd programs/gridright && anchor test --skip-build  # or anchor test
   ```
6. If `web` returns 500 or 404, check `apps/web/.env.local` (gotcha #1).
   If `api` returns ECONNREFUSED, restart it (gotcha #2).
7. Now you can start. Reference code as `file_path:line_number` —
   it's clickable. Match surrounding style: comment density, naming,
   idioms.

---

## 9. Memory I added to the system (so future-me knows)

`C:\Users\gaura\.claude\projects\C--Users-gaura-OneDrive-Desktop-gridright\memory\gridright-project.md`
— one-liner: community solar/energy pool app, monorepo (FastAPI +
Next.js + Anchor + Supabase), seller/operator roles, AI recommender
(not decision-maker), Solana settlement, Bubblegum cNFT badges.

If you add a fact that helps future sessions and isn't already in
the repo, write a memory file. Update this index after.

---

**End of handoff.** If you re-read this in 3 months and nothing
makes sense, blame context rot, not me — but the architecture doc
and the test suite are the actual ground truth.
