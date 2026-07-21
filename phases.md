# GridRight — Fresh Build Implementation Prompts

Reference `gridright_architecture.md` at the start of every phase — tell the agent to read it first each time so it doesn't drift from the design. Run one phase at a time; confirm each passes before moving on. This is an ongoing solo project, not a deadline build — favor correctness over speed.

---

## Phase 0 — Repo scaffold

```
Read gridright_architecture.md in this repo before doing anything else.

Scaffold a new monorepo for GridRight:
- apps/web: Next.js frontend
- apps/api: FastAPI backend
- programs/gridright: Anchor program for Solana settlement
- Supabase project config (migrations folder, local dev setup) / new

Set up: linting, formatting, a basic CI-less test runner (pytest for
backend, whatever the frontend testing setup should be), and a README
that links to gridright_architecture.md as the source of truth.

Do not implement any feature logic yet — this phase is scaffolding only.
Confirm the empty scaffold builds and runs (frontend dev server,
backend dev server, anchor build) before finishing.
```

---

## Phase 1 — Database schema

```
Read gridright_architecture.md. Implement the initial Supabase schema
as a migration:

- profiles: id, role ('seller' | 'operator'), plus whatever auth
  fields Supabase requires.
- community_pool: running totals of contributed kWh and current
  pool capacity/absorption limit.
- contributions: seller_id, kwh_contributed, period_start, period_end,
  ai_recommended_price, final_approved_price, approval_type
  ('auto'|'human'), approval_reason (nullable, required if human),
  payout_amount, status ('pending'|'settled'), tx_signature (nullable).
- operator_policy: configurable band width (e.g. percentage), pool
  capacity limits — whatever the policy check needs, structured so it
  can be edited without a code change.
- Use PLACEHOLDER values for the profitability spread (seller payout =
  feed-in tariff + 15%, operator margin = remaining) and policy band
  (±5%) — flag these clearly as placeholders to replace with real
  numbers per the "Open items" section of the architecture doc.

Write a migration test that inserts a sample contribution end-to-end
and confirms the schema holds together (foreign keys, defaults,
constraints).
```

---

## Phase 2 — AI recommendation + operator policy layer

```
Read gridright_architecture.md, specifically the "Core flow" and
"Why an AI recommendation, not an AI decision" sections.

Implement:
1. An AI recommendation service (Groq, with a fallback rules-based
   estimator if Groq is unavailable) that takes seller surplus + time
   of day + pool state and returns a recommended price and
   recommended pool-absorption amount.
2. A SEPARATE deterministic policy-check service — not another AI
   call — that takes the AI's recommendation and the operator_policy
   config, and returns either "auto-approved" or "needs_review" with
   the specific deviation reason (e.g. "recommended price is 8% above
   reference tariff, band allows 5%").
3. An exception queue: recommendations flagged needs_review go into a
   pending state with the deviation reason attached, awaiting an
   operator decision (approve/adjust/reject) with a required reason
   string logged either way.

Write tests for: a recommendation inside the band auto-approves with
no human step; a recommendation outside the band is correctly flagged
with the right deviation reason; an operator override is recorded with
its reason.
```

---

## Phase 3 — Import/export logic

```
Read gridright_architecture.md. Extend the AI recommendation +
policy-check flow from Phase 2 to also handle import/export:

- If the community pool has a shortfall (more consumption than
  contributed surplus), the AI should recommend importing from the
  main grid, at a recommended price, going through the same
  policy-check flow.
- If there's unmatched surplus the pool can't absorb (over its
  configured capacity), the AI should recommend exporting to the
  main grid, same flow.
- Add a "direction" field (local_pool | import | export) to whatever
  record type this produces, matching the settlement schema from
  Phase 1.

Write tests for both the shortfall and surplus-overflow scenarios,
confirming the right direction and policy-check outcome.
```

---

## Phase 4 — Solana settlement (Anchor program)

```
Read gridright_architecture.md, "Solana settlement record" and
"Settlement cadence" sections.

Implement the Anchor program for batched, per-period settlement:
- On-chain: seller pubkey, kwh_contributed (for the period), final
  approved price, payout amount, timestamp.
- Off-chain (Supabase) but hashed on-chain: full record including
  ai_recommended_price, approval_type, approval_reason.

Deploy to devnet. Write the same style of test scenarios as the prior
build (6 scenarios covering normal settlement, auto vs human
approval, and at least one import/export settlement) and confirm all
pass on devnet.
```

---

## Phase 5 — Auth

```
Read gridright_architecture.md, "Auth" section.

Implement:
- profiles.role field ('seller' | 'operator'), default 'seller'.
- /login and /operator/login pages, same Supabase Auth call, role-
  based redirect after login.
- Frontend middleware gating /operator/** on session + role.
- Backend dependency on every operator-only FastAPI endpoint that
  independently verifies role from the Supabase JWT server-side and
  returns 403 if the caller isn't an operator. Apply this explicitly
  per-route, not via a single global check.

Write tests: seller account hitting an operator-only endpoint -> 403;
operator account -> success; unauthenticated -> 401.
```

---

## Phase 6 — Seller dashboard

```
Read gridright_architecture.md, "Seller dashboard" section.

Build:
- Surplus contributed this period + cumulative, pulled from
  contributions table.
- Amount paid from Solana settlements (tx_signature-linked).
- Total earned to date.
- Contribution metric: cumulative kwh_contributed, displayed
  consistently with whatever the cNFT badge thresholds will use.
- Analysis report: per-period table (kWh contributed, amount earned,
  contribution metric), exportable as CSV. No PDF generation for v1.

Write component/integration tests confirming the dashboard reflects
a seeded set of contributions correctly.
```

---

## Phase 7 — Operator dashboard

```
Read gridright_architecture.md, "Operator dashboard" section.

Build:
- Live feed of AI recommendations, auto-approved ones shown resolved.
- Exception queue with deviation reason shown, approve/adjust/reject
  controls, required reason field on any human decision.
- Import/export panel showing current pool balance and the AI's
  recommendation, same approve/adjust/reject flow.
- Distribution view: aggregate kWh supplied to the community by
  seller.
- Aggregate stats: total spread captured, average seller uplift over
  feed-in tariff — the numbers that back up the profitability claim.

Write tests confirming an operator action (approve/adjust/reject)
correctly updates the underlying contribution record and reason log.
```

---

## Phase 8 — cNFT contribution badges

```
Read gridright_architecture.md. Set up a Bubblegum cNFT tree and
trigger a mint when a seller's cumulative kwh_contributed crosses a
milestone threshold. Use three placeholder thresholds to start (e.g.
100 kWh, 500 kWh, 1000 kWh) — flag these as placeholders to tune
later per the architecture doc's "Open items."

Write a test confirming a seeded seller crossing a threshold triggers
exactly one mint, and doesn't re-mint on subsequent contributions
below the next threshold.
```

---

## Phase 9 — Full regression

```
Run every test suite from Phases 0-8 together. Add end-to-end
scenarios covering: a seller contributing, an auto-approved
settlement, a flagged exception resolved by the operator, an
import scenario, an export scenario, and a cNFT mint trigger — all
settled on devnet. Confirm everything passes before considering this
milestone done.
```