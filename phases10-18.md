# GridRight — Advanced Roadmap: Smart Meter → AI Forecasting → On-Chain Trust Layer

Continues directly after your most recently completed build (wallet/payout, demo mode, realtime). Renumber against your own phase-tracking doc if it uses different numbers — these are just this document's Phase 1–8.

## How to use this file (Claude Code terminal workflow)

Work **one phase at a time**. For each phase:
1. Implement the tasks.
2. Run **only that phase's Verification tests** (kept deliberately small — see Global Conventions).
3. Write a short **Phase Report**: what was built, files touched, test results, any placeholders/deviations.
4. Do **one self-review pass** against that phase's Definition of Done. Fix anything unchecked *before* moving on — don't carry gaps into the next phase.
5. Stop and wait for a go-ahead before starting the next phase.

## Global conventions (apply to every phase — don't repeat per phase)

- **Don't hardcode.** Any price/unit conversion, threshold, weight, or vendor-specific value goes behind a named constant, env var, or config row — never a bare literal in logic. Follow the existing `PLACEHOLDER`-comment convention already used in the codebase for values that aren't real yet.
- **Check before building.** Before adding a table, hook, endpoint, or provider abstraction, check whether something equivalent already exists in the repo (e.g. `useRealtimeTable`, existing auth deps, existing migration patterns) and extend it instead of duplicating.
- **Reuse established patterns**: migration naming (next sequential timestamp), `DEMO-ONLY: safe to delete` tagging for anything demo-only, `get_current_user`/`get_operator_user` auth deps, `SUPABASE_AUTH_TESTING=1` bypass convention for tests, the hash-on-chain/full-record-off-chain pattern already used by `settle_period`.
- **Keep tests fast and cheap.** Mock external calls (weather API, LLM calls, Solana RPC/wallet signing) rather than hitting real services. Aim for roughly 4–8 focused tests per phase, not exhaustive coverage. Full devnet/E2E/browser verification stays a manual QA step, not part of these automated per-phase tests.
- **Explicit decisions, not silent ones.** Anywhere this doc says "decide and document," leave a code comment stating the choice and why — don't let it fall out implicitly.

---

## Phase 1 — Smart Meter: Demo Simulation

**Goal:** `/demo` gets a simulated meter walkthrough (generation/surplus/grid-export) purely to illustrate the concept — no backend, no DB.

- Add to existing `src/features/demo/`, tagged `DEMO-ONLY`: an in-memory, timer-driven generator producing fake generation/consumption/surplus/grid-export figures on a daylight-shaped curve.
- A tile + small live chart in the demo flow showing these ticking up.
- Zero new tables, zero new endpoints — entirely client-side and disposable.

**Verification:** component renders and updates state on timer tick (mocked timer, no real interval wait); no import from this code appears outside `features/demo/`.

**Definition of Done:** demo shows a self-contained, removable meter walkthrough with no backend/DB touch.

---

## Phase 2 — Smart Meter: Real Per-Seller Ingestion

**Goal:** each seller's dashboard reflects real readings from *their own* registered smart meter — no simulated data in production.

- Migration: `meter_readings` (`seller_id`, `meter_device_id`, `reading_at`, `generation_kwh`, `consumption_kwh`, `surplus_kwh` computed/floored at 0, `grid_export_kwh`), indexed on `(seller_id, reading_at)`.
- Meter registration: a `meter_device_id` + device auth token per seller (extend `profiles` or a small `meter_devices` table); add to seller settings.
- `POST /api/v1/meter-readings`: authenticated by device token (not user session), validates payload/bounds, rejects unregistered/mismatched devices.
- No real hardware here — don't fabricate a background simulator writing to this table; that's Phase 1's job only.
- Dashboard section (reuse `useRealtimeTable`): current generation, current surplus, "fed to grid today" total, short rolling chart. Clear "connect your smart meter" empty state when no device/readings exist yet.

**Verification:** ingestion endpoint accepts a valid signed reading, rejects an unknown/mismatched device token, rejects a malformed payload; dashboard shows the empty state with zero readings and updates on a mocked realtime insert event.

**Definition of Done:** real ingestion path fully separate from Phase 1's demo generator; empty state and live state both correct.

---

## Phase 3 — AI Surplus Forecasting (Seller-Side)

**Goal:** each seller gets an explainable, accuracy-tracked forecast of likely surplus, from weather + their own `meter_readings` history.

- Pluggable weather-provider interface (mock provider for dev, real provider behind an env var/API key — never one hardcoded vendor call). Add seller location to `profiles` if missing.
- Scheduled forecast job combining weather + historical generation pattern → predicted surplus curve, next 24–48h.
- Migration: `surplus_forecasts` (`seller_id`, `forecast_for`, `predicted_surplus_kwh`, `confidence`, `factors` jsonb, `generated_at`).
- Store *why*, not just the number — `factors` must be populated (e.g. cloud cover, historical average, trend), not left empty.
- Accuracy tracking: once real `meter_readings` for a forecasted period land, compute and store predicted-vs-actual delta.
- Cache/batch weather lookups by region (geohash or rounded lat/long) — not one external call per seller.

**Verification:** forecast job produces bounded, sane output from mock weather + mock meter history; accuracy computation is correct on a known predicted/actual pair; region cache prevents duplicate calls for two sellers in the same area (mocked provider call-count assertion).

**Definition of Done:** every forecast has stored, non-empty factors; accuracy is computed once actuals exist; weather calls are cached, not per-seller.

---

## Phase 4 — Operator Fleet View + Demand Awareness + Recommendation Feed-In

**Goal:** operator sees an aggregated, explainable fleet outlook (supply *and* demand), and it optionally informs the existing recommendation engine.

- Operator dashboard section: fleet-wide expected surplus (next 24–48h), aggregated from `surplus_forecasts`, with per-seller breakdown and visible confidence (a band, not a single line).
- Short natural-language outlook summary — reuse the existing recommendation layer's LLM call pattern rather than adding a second one.
- Add a lightweight, pluggable demand/peak-hour signal (even a simple time-of-day heuristic to start) alongside the supply forecast, so the combined view is a net position (surplus vs. shortfall), not supply alone.
- Flag sellers whose recent forecast accuracy has drifted notably — useful both as a forecast-quality signal and an early flag for a misbehaving meter.
- **Decide and document explicitly**: (a) fleet forecast/net-position is informational only for now, or (b) it's passed as additional context into the existing recommendation function so pricing/approval shifts with expected supply-demand balance. If (b), pass it as an explicit function input — don't reach into the forecast table from deep inside existing logic. Existing recommendation behavior must degrade gracefully (no-op, not error) when no forecast data exists yet.

**Verification:** aggregation correctly sums/averages a small set of mock per-seller forecasts; accuracy-drift flagging triggers on a known bad-accuracy fixture; if (b) chosen, recommendation function output changes with forecast context present vs. absent, and doesn't error when absent.

**Definition of Done:** fleet view shows real aggregation + confidence + demand signal; the (a)/(b) choice is documented in code; no crash path when forecast data is missing.

---

## Phase 5 — On-Chain Daily Decision Commitment (Merkle Root + Off-Chain Proofs)

**Goal:** every AI-recommendation-vs-operator-decision is tamper-evidently anchored on-chain, without paying to store full records on-chain.

- Add `decision_hash` to the existing contribution/review record (don't create a parallel table for this) — a canonical hash (e.g. SHA-256 of a fixed-field JSON: seller id, AI-recommended price/amount, operator decision, decided-at, model version, record id) computed at the moment a decision is made (auto-approve or operator resolve).
- Daily job: collect that UTC day's `decision_hash` values, sort deterministically (e.g. ascending by hash bytes — order must not depend on insertion order), build a Merkle tree (standard pairwise SHA-256, duplicate last leaf on odd count), get the root.
- New Anchor instruction `commit_daily_root(date, merkle_root, record_count)` writing a `DailyCommitment` account (`authority`, `date`, `merkle_root`, `record_count`, `committed_at`), PDA seeds `[b"daily_commitment", authority.key(), date_bytes]` — authority in the seeds, not hardcoded to one operator.
- Off-chain proof: regenerate the day's tree on demand from stored hashes (don't persist proofs separately — recomputation must be deterministic and cheap) to produce a proof path for any single record.
- Add a verify path (endpoint or dashboard action): given a decision record, regenerate its proof, fetch the on-chain `DailyCommitment` for that date/authority, confirm the proof resolves to the stored root; surface an explorer link to the commit transaction.

**Verification (small, mocked RPC where possible):** hash computation is deterministic for the same input; Merkle root construction is correct against a known small fixture (3–5 leaves, hand-verified expected root); one real devnet round-trip test of `commit_daily_root` + one verify-success and one verify-failure (tampered record) case — keep this the *only* on-chain test in this phase to control cost/time.

**Definition of Done:** decision records are hashed at decision time; daily root commits on devnet; a specific record's proof verifiably resolves to its day's committed root, and a tampered record's proof does not.

---

## Phase 6 — Reputation Signals + Dispute/Appeal Flow

**Goal:** turn Phase 3's forecast accuracy and Phase 5's tamper-evident decisions into visible trust signals, and give sellers a real path to contest a decision.

- Seller reputation: surface existing forecast-accuracy history on the seller's profile/operator view (already computed in Phase 3 — this phase just makes it visible and configurable, e.g. which time window it's averaged over).
- Operator consistency: derive an override-rate metric from decision records (approved-as-is vs. adjusted vs. rejected, and direction of adjustment) — any weighting used to summarize this into a single score must be a named, configurable constant, not a hardcoded formula.
- Migration: `disputes` (`contribution_id`/`review_id`, `seller_id`, `reason`, `status` open/resolved, `resolution`, `evidence_verified` bool, `created_at`, `resolved_at`).
- Seller-facing "Flag for review" action requiring a non-empty reason (mirrors the existing exception-queue reason convention).
- Dispute detail view pulls the Phase 5 verify result for the underlying decision record, so resolution is grounded in verified evidence, not just re-litigated off-chain claims.
- Resolution flow: operator resolves with a decision + reason (note in a comment if a separate appeals-authority role would make sense later — don't build a new role unless one already exists in the schema).

**Verification:** override-consistency metric computed correctly on a small known set of decisions; dispute creation rejects an empty reason; dispute detail correctly surfaces a mocked verify-true and verify-false result.

**Definition of Done:** both reputation signals are visible and driven by real stored data (not placeholders); a seller can file and see the status of a dispute backed by Phase 5 evidence.

---

## Phase 7 — Tokenized Renewable Energy Certificates (RECs)

**Goal:** verified real grid-export (Phase 2 data) mints a tradeable/holdable SPL token per kWh, separate from the cash payout.

- Check first whether any token/cNFT minting infra already exists in the *current* rearchitected repo (note: earlier hackathon-era Bubblegum cNFT setup was from a prior repo and may not carry over) — extend rather than duplicate if something's already there.
- Define the REC unit consistently with the existing `amount_wh` convention already used elsewhere — don't invent a second unit system.
- Mint tied to confirmed settlement: amount = actual `grid_export_kwh` from Phase 2 meter data for that settlement period (not the forecast, not the AI recommendation — reward verified actual export only).
- Mint authority should be a program-controlled PDA, not a personal/operator keypair, so it isn't centrally hardcoded to one wallet.
- Sellers view/hold RECs in the wallet already connected from the payout work.

**Verification:** mint amount matches the settlement's actual `grid_export_kwh` in a fixture case; mint is rejected/no-ops if there's no confirmed settlement backing it (can't mint on unverified data).

**Definition of Done:** RECs mint only against real, settled, verified export; mint authority isn't a personal keypair.

---

## Phase 8 — Community Governance-Lite

**Goal:** active pool participants get a lightweight voice in policy parameters (the existing `operator_policy` fields) — governance-lite, not a full DAO.

- Voting eligibility: sellers with at least one confirmed contribution (don't hardcode a different eligibility rule without noting it).
- Votable parameter set should be configurable (a list, not one hardcoded field) — start with whichever `operator_policy` fields make sense (e.g. `band_width_percentage`, `seller_uplift_percentage`) but don't wire the mechanism to only ever support those two.
- Start with off-chain vote records tied to a wallet-signed message (proves identity cheaply without a full on-chain voting program) — same off-chain-data/on-chain-trust-anchor spirit as Phase 5; note on-chain voting as a future upgrade path rather than building it now.
- Quorum/threshold values live in config (new `governance_config` row or reuse `operator_policy`), not hardcoded numbers.
- Operator explicitly retains override/emergency authority — document this choice the same way as other explicit decisions in this doc.

**Verification:** a vote from an ineligible wallet (no confirmed contribution) is rejected; quorum/threshold check correctly passes/fails against small known vote-count fixtures; an operator override after a passed vote is possible and logged.

**Definition of Done:** eligibility and votable-parameter set are enforced and configurable, not hardcoded; operator override path exists and is documented.