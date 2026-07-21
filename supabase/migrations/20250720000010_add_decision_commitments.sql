-- Phase 5 (advanced roadmap) — on-chain daily decision commitment.
--
-- 1. decision_hash lives ON the existing contributions record (per spec: no
--    parallel table for the hash itself). Computed at the moment a decision
--    is made — auto-approve at recommend time, or operator resolve.
--    decided_at + model_version are hash inputs, so they're stored too.
-- 2. daily_commitments is an off-chain MIRROR of the on-chain
--    DailyCommitment account: it records which root was committed for which
--    UTC day, in which transaction — needed for explorer links and for
--    verify without an RPC round-trip on every check. The chain remains the
--    source of truth; this row is bookkeeping.

alter table public.contributions
  add column if not exists decision_hash text,
  add column if not exists decided_at timestamptz,
  add column if not exists model_version text;

-- Daily lookups scan a UTC-day window of decided_at.
create index if not exists idx_contributions_decided_at
  on public.contributions (decided_at);

create table if not exists public.daily_commitments (
  id            uuid        primary key default gen_random_uuid(),
  commit_date   date        not null,
  authority     text        not null,   -- base58 pubkey whose PDA holds the root
  merkle_root   text        not null,   -- hex
  record_count  integer     not null check (record_count > 0),
  tx_signature  text,
  pda           text,
  committed_at  timestamptz not null default now(),
  constraint daily_commitments_unique unique (commit_date, authority)
);

alter table public.daily_commitments enable row level security;

-- Anyone authenticated may read commitments (they're public on-chain anyway).
drop policy if exists "authenticated read commitments" on public.daily_commitments;
create policy "authenticated read commitments"
  on public.daily_commitments for select
  to authenticated
  using (true);

grant select on public.daily_commitments to authenticated;
-- service_role covered by migration 000009's blanket + default grants.
