# Phase 5 — On-Chain Daily Decision Commitment (report)

## What was built
The full Phase 5 pipeline: every AI-recommendation-vs-final-decision gets a
canonical SHA-256 hash at the moment the decision is made, all hashes for
one UTC day fold into a Merkle root, that root is committed to a Solana
PDA once per (authority, date), and any single record can be verified
off-chain against the committed root.

Per the spec: hash-on-chain (32-byte root), full records off-chain
(Supabase), proofs regenerated on demand and never persisted.

## Files touched

### Created
- `supabase/migrations/20250720000010_add_decision_commitments.sql`
  (already applied to local Supabase) — adds `decision_hash text,
  decided_at timestamptz, model_version text` to `contributions`; creates
  `idx_contributions_decided_at` for the daily window scan; creates
  `daily_commitments` mirror table (commit_date, authority, merkle_root,
  record_count, tx_signature, pda, committed_at) with RLS authenticated-read
  and a unique `(commit_date, authority)` constraint.
- `apps/api/app/services/decisions.py` — `DECISION_HASH_VERSION = "v1"`,
  `canonical_decision_payload(...)` (fixed field set, floats stringified
  to `:.6f` / `:.4f` for price/kwh so cross-runtime float reprs don't
  shift the hash), `decision_hash(...)` = SHA-256 hex of canonical JSON
  with sorted keys and compact separators.
- `apps/api/app/services/merkle.py` — `sort_leaves`, `merkle_root`
  (pairwise SHA-256, duplicate last on odd count, raises on empty),
  `merkle_proof` (sibling path with `sibling_is_left` flag for fold
  direction), `verify_proof`. `MerkleProof` dataclass.
- `apps/api/app/services/commitments.py` — store-ABC pattern:
  `CommitmentStore` (Supabase impl) + `AnchorCommitClient` (TS-script
  impl, npx.cmd-safe via `shutil.which`). `run_daily_commitment(day)`
  collects `decided_at`-windowed hashes, sorts, builds root, shells out
  to `commit-daily-root.ts`, mirrors the receipt. `verify_contribution
  (record_id, hex, day)` regenerates the proof and checks it folds to
  the committed root; returns the on-chain tx signature + devnet
  explorer URL.
- `programs/gridright/scripts/commit-daily-root.ts` — shells in the
  exact same pattern as `settle-period.ts`: args via `--name value`,
  RPC `SOLANA_RPC_URL` default devnet, wallet `SOLANA_WALLET` default
  `~/.config/solana/id.json`, IDL from `target/idl/gridright.json`,
  prints one JSON line. Validates `--date` matches `YYYY-MM-DD`, that
  `--root` is 64 hex chars, and that `--count` is a positive integer.
- `apps/api/tests/test_commitments.py` — 10 mocked Phase 5 tests.

### Modified
- `programs/gridright/programs/gridright/src/lib.rs` — added
  `DailyCommitment` account (`authority, date: String, merkle_root:
  [u8;32], record_count: u32, committed_at: i64, bump`); added
  `commit_daily_root` instruction (date, merkle_root, record_count)
  with PDA `[b"daily_commitment", authority.key(), date.as_bytes()]`
  and **`init` (not `init_if_needed`)** so re-commits fail — the
  on-chain audit trail is immutable. Two new errors:
  `InvalidDate` (must be 10 chars), `EmptyCommitment` (count > 0).
- `programs/gridright/tests/gridright.ts` — test 10, the **single
  on-chain commitment test** mandated by the spec: commit round-trip
  (date, root, count persisted on the PDA), verify-success (committed
  bytes match what was sent), verify-failure-tampered (a flipped bit
  on the root differs from the on-chain committed value).
- `programs/gridright/target/deploy/gridright.so` — rebuilt + redeployed
  to devnet (program id `88HxyoRrb9NzqWfk34SCoqHZcMFxmmHg6XVNpcVPxoFL`,
  on-chain IDL account `3wccaA6Mo1xzZeuu7xB6UzXzyNT1KY7fkwnqpNy7Jjv3`
  upgraded to the new 1392-byte IDL). All 10 Anchor tests pass against
  devnet.
- `apps/api/app/services/exception_queue.py` — `ReviewStore` ABC gained
  `add_auto_approved` (the decision moment for an auto-approved
  recommendation) and a `model_version` param on `add_pending_review`.
  `SupabaseReviewStore.add_auto_approved` generates a client-side
  uuid4 so the `decision_hash` (which includes `record_id`) can be
  computed in the same insert. `resolve_review` now fetches
  `ai_recommended_price, model_version` and writes `decided_at +
  decision_hash` on the update. Module-level `add()` gained
  `model_version`; new module-level `add_auto_approved()`.
- `apps/api/app/routers.py` — `recommend_endpoint` now passes
  `model_version=recommendation.model_used` into `queue_add`, and in
  the auto-approved branch (defensive try/except) calls the new
  `queue_add_auto_approved` so the contribution + hash are persisted.
  Two new endpoints: `POST /commitments/run` (operator, runs the
  daily commit job for today) and `GET /contributions/{id}/verify`
  (operator, off-chain proof verification + explorer link).
- `apps/api/tests/test_exception_queue.py` — `DictReviewStore` gained
  `add_auto_approved` and now mirrors `decided_at` + `decision_hash`
  in `resolve_review`. Required: conftest installs this as the
  default store, so an unimplemented abstract method would have
  broken all 130 prior tests.
- `apps/api/tests/test_operator_dashboard.py` — `RecordingReviewStore`
  gained `add_auto_approved` and accepts `model_version` (same
  reason).
- `programs/gridright/.mocharc.json` — small mocha config (`node-option:
  import=tsx`) so the test suite can be run directly with
  `npx mocha` against devnet (the project's `anchor test` wrapper
  shells to `/bin/bash`, which isn't available on this Windows box;
  this was the simplest path that re-uses the existing `target/`
  IDL/types).
- `programs/gridright/target/idl/gridright.json` and `target/types/gridright.ts`
  regenerated by the build (new `commit_daily_root` instruction,
  `DailyCommitment` account, discriminator bytes).

## Definition of Done — self-review

| Requirement | Status |
|---|---|
| decision_hash lives on the existing `contributions` row (no parallel table) | ✅ migration 20250720000010 |
| Hash = SHA-256 of canonical fixed-field JSON, computed at the decision moment | ✅ `decisions.py`, `add_auto_approved` and `resolve_review` |
| decision_hash versioned so old hashes stay re-derivable | ✅ `DECISION_HASH_VERSION = "v1"`, in payload as `v` |
| All decision types covered: auto, approve, adjust, reject | ✅ `add_auto_approved` (`decision="auto"`), `resolve_review` (`decision=action.value`) |
| Daily job: collect by `decided_at` window, sort, Merkle root, on-chain commit | ✅ `run_daily_commitment` |
| Merkle root is insertion-order-independent | ✅ tested in `test_merkle_root_order_independent` |
| DailyCommitment PDA `[b"daily_commitment", authority, date_bytes]` | ✅ `CommitDailyRoot` accounts struct |
| On-chain account is **immutable** (re-commit fails) | ✅ `init`, not `init_if_needed`; date validation; record_count > 0 |
| Off-chain proof regenerated on demand (never persisted) | ✅ `merkle_proof` + `verify_contribution`; nothing stored on the contribution row |
| Verify endpoint with explorer link | ✅ `GET /contributions/{id}/verify` returns `explorer_url` |
| 4–8 focused mocked Phase 5 tests | ✅ 10 tests in `test_commitments.py` (hash + 4 Merkle fixture tests + 4 mocked commit/verify tests) |
| ONE on-chain test: commit round-trip + verify-success + verify-failure | ✅ test 10 in `programs/gridright/tests/gridright.ts` |
| No hardcoded values (PLACEHOLDER / env / config) | ✅ new env reads only; no literals added |
| No regression in existing tests | ✅ 140 backend + 56 frontend + 10 Anchor, all green |

## Test results

- Backend: `140 passed, 1 skipped` (was 130 — +10 new Phase 5 tests)
- Frontend: `56 passed` (unchanged — Phase 5 is server-side)
- Anchor: `10 passing` against devnet (was 9 — +1 new on-chain commitment test)

## Placeholders / deviations
- **CLI mocharc** (`programs/gridright/.mocharc.json`): I added a small
  mocha config so the test suite runs with `npx mocha` against devnet.
  The project's `anchor test` script shells to `/bin/bash`, which
  isn't available on this Windows host. The mocharc just sets
  `node-option: import=tsx` and the spec; no behavioral change to the
  program under test. This is a workspace-level tooling detail, not a
  spec deviation.
- **`record_count > 0` requirement** isn't in the spec text, but the
  spec calls an empty-day commit a no-op (the job skips it). The on-chain
  `init` would still succeed for an empty leaf set, so the instruction
  rejects it with `EmptyCommitment` to keep the on-chain invariant
  (every PDA covers at least one record) honest. The off-chain job
  already skips empty days before calling the on-chain instruction.

## Stopping for go-ahead
Phase 5 is complete. Ready for Phase 6 on your signal.
