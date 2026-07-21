# GridRight — Architecture

GridRight is an AI-assisted, utility-moderated settlement platform for distributed solar energy. Sellers with surplus solar contribute it to a shared community pool; an AI recommends pricing and distribution decisions; a grid operator holds real authority over those recommendations; and Solana provides transparent, auditable settlement.

This is an ongoing solo build — not a hackathon project, no external pitch or pilot planned yet. Prioritize correctness and clarity over speed.

---

## Roles

There are exactly two account types. There is no individual buyer account — electricity sold by a seller goes into a shared community pool, and the operator manages distribution and billing to the community in aggregate.

- **Seller** — a household, school, shop, or similar with rooftop solar surplus.
- **Operator** — the utility-side role with authority over pricing and distribution decisions.

---

## Core flow

```
Solar Panels
     │
     ▼
Smart Meter + Battery
     │
     ▼
AI detects surplus
     │
     ▼
AI recommends: sell price for the seller, and how much of the surplus
the community pool can absorb right now
     │
     ▼
Operator Policy Layer checks the recommendation against a configured band
 ├── Within band  → auto-approved
 └── Outside band → flagged, human reviews and approves/adjusts/rejects
     with a required reason
     │
     ▼
Seller's contribution is added to the community pool; operator settles
seller payout against pooled community consumption for the period
     │
     ▼
Settlement recorded on Solana
     │
     ▼
Transparent record: seller, kWh contributed, AI-recommended price,
final approved price, approval type + reason, timestamp
```

### Why an AI recommendation, not an AI decision

The AI never has final authority. If the AI both recommended and approved, there'd be no independent check on price — the exact failure mode the operator layer exists to prevent. The operator's policy check is a deterministic rules layer (bands, feeder/pool capacity limits), not another AI call, so it can't be gamed by the same reasoning that produced the recommendation.

### Why a community pool, not individual buyers

Aggregate distribution is simpler for a utility to operate and audit than tracking many individual buyer-seller pairs, and it settles more naturally on-chain as a periodic batch rather than a transaction per kWh trade. It also matches how utilities already think about grid balancing — in aggregate, not pairwise.

---

## Profitability model

Needs real numbers before implementation — placeholders below, replace before building:

- Seller payout = standard grid feed-in tariff **+ X%** (incentive to contribute to the pool instead of exporting to the grid at the fixed tariff).
- Operator keeps a flat per-kWh fee **or** a percentage margin from community billing — this funds operator/platform sustainability.
- Every payout traces back to this rule; there is no other source of "profitability" claimed anywhere in the dashboards.

---

## Settlement cadence

Batched, not per-trade: seller contributions accumulate against the community pool through a billing period (e.g. daily or weekly), and payout settlement happens once per period against aggregate pool consumption. This is cheaper on-chain and matches the community-pool model — there's no per-buyer transaction to settle individually.

---

## Dashboards

### Seller dashboard
- Surplus contributed to the community pool (this period and cumulative).
- Amount paid by the operator from Solana settlements, per the payout rule above.
- Total earned to date.
- Community contribution metric: **kWh delivered to the community pool** (single number, used consistently everywhere this appears, including cNFT milestone badges).
- Generated analysis report: per-period summary (kWh contributed, amount earned, contribution metric) — v1 scope is a simple exportable table/CSV, not full PDF generation.

### Operator dashboard
- AI's recommended import/export decisions: when the pool has a shortfall, recommend importing from the main grid; when there's unmatched surplus the pool can't absorb, recommend exporting to the grid. Same band/exception logic as pricing.
- Pricing management: current seller payout rate, policy band configuration.
- Distribution view: how much electricity is being supplied to the community by each seller, aggregated.
- Exception queue: AI recommendations outside the configured band, with approve/adjust/reject controls and a required reason field, logged for audit.
- Aggregate stats proving the profitability claim: total spread captured, average seller uplift over feed-in tariff.

---

## Auth

One Supabase Auth backend, `role` field on the profile (`seller` | `operator`). Two login entry points (`/login`, `/operator/login`), same underlying auth, role-based redirect after login.

Gating happens at two layers:
- Frontend route guard (middleware) — stops navigation to the wrong dashboard.
- Backend API check on every operator-only endpoint, verifying `role` from the Supabase JWT server-side. This is the layer that actually matters — a frontend-only guard doesn't stop a direct API call, and these are the endpoints that approve prices and move money.

---

## Solana settlement record

Each settlement (batched per period, per seller) records:

- Seller
- kWh contributed this period
- AI-recommended price
- Final approved price
- Approval type (`auto` | `human`) and reason (required if `human`)
- Payout amount
- Timestamp

If full on-chain storage of every field is too costly, store the critical financial fields on-chain (seller, kWh, final price, payout, timestamp) and hash the full record — including AI recommendation and reason — on-chain, with the full JSON stored off-chain in Supabase.

---

## Stack (carried over from prior build)

- Next.js frontend, FastAPI backend, Supabase (data, realtime, auth)
- Groq for AI recommendations, with fallback rules
- Solana devnet, Anchor program for settlement
- Bubblegum cNFT tree for seller contribution milestone badges

---

## Open items to resolve before implementation starts

1. Pick real numbers for the profitability spread (seller uplift %, operator margin).
2. Pick real numbers for the operator policy band width.
3. Decide billing period length for settlement (daily vs weekly vs other).
4. Decide the 2-3 contribution thresholds that trigger a cNFT badge mint.
5. Badge cNFTs currently mint custodially to the operator wallet (sellers have no Solana wallet); a transfer-to-seller/claim flow is unimplemented — any seller-facing badge UI must not imply the seller holds the cNFT until that exists.
6. Failed badge mints (`seller_badges.mint_status = 'failed'`) have no automatic retry — recovery is a manual operator action (delete the failed row, then re-run the badge check for that seller). Build a retry path before badges matter operationally.