# GridRight

**AI-assisted, utility-moderated settlement platform for distributed solar energy.**

Households with rooftop solar contribute their surplus into a shared community
pool. An AI recommends a fair sell price and how much the pool can absorb; a
human grid operator holds final authority over those recommendations; and
Solana provides a transparent, auditable settlement record. The guiding
principle throughout is **AI recommends, the operator decides** — the AI never
moves money or finalizes a price on its own.

> Full design rationale and decisions live in
> [`gridright_architecture.md`](./gridright_architecture.md). This README is the
> operational + component overview.

---

## Project scope

GridRight is an ongoing solo build focused on correctness and clarity over
speed. It is deliberately scoped to **two account types** — there is no
individual buyer account:

- **Seller** — a household, school, or shop with rooftop solar surplus.
- **Operator** — the utility-side role with authority over pricing, distribution
  decisions, seller onboarding, and payouts.

Electricity sold by a seller flows into a **shared community pool**; the operator
manages distribution and billing to the community in aggregate. Settlement is
**batched per period**, not per trade, because aggregate distribution is simpler
to operate/audit and settles more naturally on-chain as a periodic batch than as
a transaction per kWh.

In scope today: seller onboarding, smart-meter ingestion, surplus forecasting,
AI price/absorption recommendation, a deterministic operator policy layer with
an exception queue, batched settlement cycles with optional auto-pay, on-chain
settlement + a daily Merkle commitment of decisions, and Bubblegum cNFT
contribution badges.

## Business logic

### Roles and the human-in-the-loop boundary

The core rule is that the AI produces a **recommendation**, and a **deterministic
policy layer** (not another AI call) decides whether that recommendation is
auto-approved or must be reviewed by a human operator. Keeping the policy check
deterministic means it can't be gamed by the same reasoning that produced the
recommendation.

### End-to-end flow

```
Solar panels → smart meter + battery
        │
        ▼
AI detects surplus and recommends: a sell price, and how much of the
surplus the community pool can absorb right now (direction: LocalPool / Import / Export)
        │
        ▼
Operator Policy Layer checks the recommendation against a configured band
  ├── Within band  → auto-approved; contribution persisted with a decision_hash
  └── Outside band → flagged into the exception queue; a human approves /
      adjusts / rejects with a required reason
        │
        ▼
Approved contributions accumulate in the community pool
        │
        ▼
Every 30 min a settlement cycle batches decision-settled, unpaid contributions
into per-seller payouts (feed-in tariff + uplift %); small non-escalated lines
may auto-pay, the rest are paid by the operator via Phantom
        │
        ▼
Settlement recorded on Solana; a daily Merkle root commits all decision hashes
        │
        ▼
Cumulative settled kWh crossing a threshold mints a Bubblegum cNFT badge
```

### Pricing and profitability

- **Seller payout** = grid feed-in tariff **+ uplift %** (incentive to feed the
  pool rather than export to the grid at the fixed tariff).
- **Operator margin** = a per-kWh fee or a percentage of community billing.
- Current policy config (see `routers.py`): `band_width_percentage=5`,
  `seller_uplift_percentage=15`, `operator_margin_percentage=5`,
  `feed_in_tariff_reference=0.10`, `pool_capacity_limit_kwh=10000`. These are
  placeholders to replace with real numbers before any real-money use.

### Settlement cadence and missed-deadline handling

Settlement runs on **30-minute cycles**. Unpaid payouts roll forward
(+1 miss each cycle) and **escalate at 3 consecutive misses**. Escalated or
large lines are held for manual operator payment; only small, non-escalated
lines are eligible for opt-in auto-pay.

### Auth model

One Supabase Auth backend with a `role` field (`seller` | `operator`) and two
login entry points sharing it. Gating happens at two layers:

- Frontend route guard (middleware) stops navigation to the wrong dashboard.
- **Backend check on every operator-only endpoint** verifies `role` from the
  Supabase JWT server-side — this is the layer that actually matters, since a
  frontend guard doesn't stop a direct API call to the endpoints that approve
  prices and move money. Auth is declared **per-route** via FastAPI
  dependencies, not globally.

## Architecture

Monorepo with four deployable/buildable pieces:

```
apps/
  web/          Next.js (App Router) frontend — seller + operator dashboards
  api/          FastAPI backend — recommendation, policy, settlement, badges
programs/
  gridright/    Anchor (Rust) Solana program + TS scripts
supabase/
  migrations/   Postgres schema, RLS policies, JWT role claim
```

```
                 ┌─────────────────────────────────────────┐
   Smart meter ──┤  FastAPI (apps/api)                       │
   (device token)│   recommender → policy_checker →          │
                 │   exception_queue → settlement_cycle      │
 Seller / Operator────► Next.js (apps/web) ──► /api/v1 ──►    │
   (Supabase JWT)│                                           │
                 │   badge_service, commitments, forecast    │
                 └───────┬───────────────┬───────────────────┘
                         │               │
                   Supabase          Solana devnet
                (Postgres + RLS,   (Anchor program:
                 Auth, Realtime)    settle_period,
                                    pay_seller,
                                    commit_daily_root
                                    + Bubblegum cNFTs)
```

- The frontend talks to Supabase directly for auth/realtime reads and to the
  FastAPI backend (`/api/v1`) for all write/decision paths.
- The backend is the only component that holds the Supabase **service key** and
  the settlement authority; it enforces operator gating and shells out to the
  TS scripts under `programs/gridright/scripts` for on-chain actions.
- Solana stores the financial-critical fields on-chain; the full decision record
  (including AI recommendation + reason) is hashed on-chain and stored in full
  off-chain in Supabase.

## How it works (request lifecycle)

1. **Ingestion** — a smart meter POSTs readings to `/api/v1/meter-readings`
   authenticated by a per-device token (hashed at rest). `surplus_kwh` is
   computed by the DB, never trusted from the wire.
2. **Recommendation** — `/api/v1/recommend` (intentionally public, callable by a
   meter) requires the seller to have a registered wallet, builds `PoolState` +
   an optional `FleetContext` (aggregated net position), and calls the
   recommender. The recommender uses Groq (`GROQ_MODEL`, currently
   `openai/gpt-oss-120b`) with a **rules fallback** when no key/model is
   available, and nudges price within a bounded range from the fleet outlook.
3. **Policy check** — `policy_checker.check` compares the recommendation to the
   configured band. Within band → `queue_add_auto_approved` persists the
   contribution with its `decision_hash`. Outside band → `queue_add` files it
   into the exception queue for `/reviews/{id}/resolve`.
4. **Settlement** — `/api/v1/settlements/run` (every 30 min via scheduler token
   or manual operator) first sweeps unaggregated meter readings into priced
   contributions, batches unpaid decision-settled contributions into per-seller
   payout lines, then runs opt-in auto-pay for small non-escalated lines.
   Operators pay remaining lines client-side via Phantom and record the tx
   signature at `/operator/settlements/items/{id}/paid`.
5. **On-chain commitment** — `/api/v1/commitments/run` (daily) builds a Merkle
   root over the day's decision hashes and commits it immutably
   (`commit_daily_root`, `init` not `init_if_needed`).
   `/contributions/{id}/verify` regenerates a proof and folds it to the
   committed root.
6. **Badges** — after any approve/adjust settlement, `badge_service` checks
   whether the seller's cumulative settled kWh crossed a threshold and mints a
   Bubblegum cNFT (best-effort; a mint failure never fails the operator action).

## Component descriptions

### Backend — `apps/api` (FastAPI, `app/services/`)

| Component | Responsibility |
| --- | --- |
| `recommender.py` | Recommends sell price + pool absorption via Groq, with a deterministic rules fallback and bounded fleet-outlook price nudge. |
| `policy_checker.py` | Deterministic band/capacity check → `auto_approved` or `needs_review`. Never an AI call. |
| `exception_queue.py` | Files out-of-band recommendations for human review; records auto-approvals; resolves reviews with a required reason. |
| `settlement_cycle.py` | 30-min batching of unpaid contributions into per-seller payouts; missed-deadline roll-forward + escalation at 3 misses. |
| `autopay.py` | Opt-in (`AUTOPAY_ENABLED`) auto-payment of small, non-escalated payout lines. |
| `meter.py`, `meter_binding.py`, `meter_aggregation.py` | Device registration/token auth, pairing-code binding, and sweeping raw readings into priced contributions. |
| `forecast.py`, `demand.py`, `weather.py`, `fleet.py` | Surplus forecasting, demand modeling, weather inputs, and the aggregated fleet outlook / net position. |
| `commitments.py`, `merkle.py` | Daily Merkle commitment of decision hashes + off-chain proof verification. |
| `badge_service.py` | Threshold-based, idempotent cNFT badge minting on settled kWh. |
| `operator_dashboard.py`, `seller_dashboard.py` | Read-side aggregation for the two dashboards. |
| `onboarding.py`, `password_gate.py`, `wallet.py`, `wallet_activation.py` | Seller identity application/approval, forced first-login password change, and signed-challenge wallet activation. |
| `auth.py`, `main.py`, `routers.py` | JWT/role dependencies, app + CORS setup, and all `/api/v1` routes. |

### Frontend — `apps/web` (Next.js App Router, `src/`)

- `app/dashboard/*` — seller dashboard (surplus, earnings, meter, badges).
- `app/operator/dashboard/*` — operator feed, exception review controls,
  settlement panel, fleet outlook, application review.
- `app/apply`, `app/login`, `app/operator/login`, `app/change-password` — onboarding + auth flows.
- `app/actions/*` — server actions bridging the UI to the FastAPI backend.
- `components/wallet-*`, `lib/supabase/*` — Phantom wallet integration and Supabase clients.
- `features/demo*` — self-contained, isolated demo/simulation experiences.

### Solana program — `programs/gridright` (Anchor/Rust)

- `settle_period` — writes an immutable per-seller, per-period `Settlement` PDA.
- `pay_seller` — transfers the payout (cents→lamports) after verifying the
  recipient matches `Settlement.seller`.
- `commit_daily_root` — immutable daily `DailyCommitment` PDA (one per
  authority+date).
- `scripts/*.ts` — settle/pay/commit/mint-badge/tree-setup helpers the backend shells out to.

### Data — `supabase/migrations`

Postgres schema with RLS, an operator/seller `role` JWT claim, meter readings +
aggregation, surplus forecasts, decision commitments, seller onboarding,
settlement cycles, autopay, and badges.

## Quickstart

### Frontend
```bash
cd apps/web
npm install
npm run dev
```

### Backend
```bash
cd apps/api
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

### Tests
```bash
cd apps/api && pytest                     # backend
cd programs/gridright && anchor test      # Anchor (requires Solana localnet)
cd apps/web && npm test                   # frontend
```

## Free hosting stack

Deployment intentionally uses services that are free **without a card on file**:

| Piece | Service | Free-tier notes |
| --- | --- | --- |
| Frontend | Netlify / Vercel | Root directory `apps/web` |
| Backend | Render (web service) | 750 hrs/mo, 512MB, sleeps after 15 min idle (~30–60s cold start) |
| Database/auth | Supabase Free | Auto-pauses after 7 days without a DB request — the cron pings prevent this |
| Scheduler | cron-job.org | Email-only signup; fires the jobs below |
| Weather | Open-Meteo | Non-commercial license — revisit before real transactions at scale |

Scheduled jobs (cron-job.org → the Render URL, `Authorization: Bearer $SCHEDULER_TOKEN`):

- `GET /health` every 10–14 min — keeps Render awake; touches no DB.
- `POST /api/v1/forecasts/run` hourly — forecast + accuracy job.
- `POST /api/v1/settlements/run` every 30 min — settlement cycle + autopay.
- `POST /api/v1/commitments/run` daily — Merkle commitment.

`SCHEDULER_TOKEN` is a static secret accepted as an alternative to an operator
JWT on the `/run` endpoints only (a live JWT would expire and break the cron).

**Env vars** — Frontend: `NEXT_PUBLIC_SUPABASE_URL`,
`NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_API_URL`,
`NEXT_PUBLIC_SOLANA_RPC`. Backend (Render): `SUPABASE_URL`,
`SUPABASE_SERVICE_KEY`, `SCHEDULER_TOKEN`, `WEATHER_PROVIDER=open-meteo`,
`CORS_ALLOWED_ORIGINS`, `CORS_ALLOWED_ORIGIN_REGEX`, `BADGE_TREE_ADDRESS`,
`COMMIT_AUTHORITY_PUBKEY`, `GROQ_API_KEY` (optional — recommender falls back to
rules without it), `GROQ_MODEL` (optional), `AUTOPAY_ENABLED` (optional). Also
add the production web URL to Supabase Auth's Site URL / redirect allow-list.

## cNFT contribution badges

Milestone badges are Bubblegum compressed NFTs minted on devnet when a seller's
cumulative settled kWh crosses a threshold (placeholders 100 / 500 / 1000 kWh —
see `20250719000004_add_badges.sql`).

```bash
cd programs/gridright
npm run badge:setup-tree   # one-time; prints the tree address
```

Current devnet badge tree: `FRAgmb48t9MgDvWgAC64wvNNgNse9m256Km1dREAF7j7`
(set as `BADGE_TREE_ADDRESS` for the API's minter, which shells out to
`scripts/mint-badge.ts`).

> Note: badges currently mint custodially to the operator wallet — a
> transfer/claim flow to sellers is not yet implemented, and failed mints
> (`seller_badges.mint_status = 'failed'`) have no automatic retry.
