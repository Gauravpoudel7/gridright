-- 30-minute settlement cycles.
--
-- Every 30 minutes a scheduler-triggered run groups all decision-settled,
-- unpaid contributions into a settlement batch with one payout item per
-- seller. The operator pays each item (Phantom transfer) before the batch's
-- due_at.
--
-- Missed-deadline rule (see settlement_cycle.py):
--   * A batch not fully paid when the next run fires is closed as
--     'rolled_over'; its unpaid items carry forward into the new batch and
--     each carried payout's missed_cycles increments. Sellers never lose
--     money — amounts accumulate.
--   * At 3 consecutive missed cycles (~90 min) the item is escalated:
--     flagged for immediate operator action on the dashboard. Intake is
--     never paused.

create table if not exists public.settlement_batches (
  id            uuid        primary key default gen_random_uuid(),
  cycle_start   timestamptz not null,
  due_at        timestamptz not null,
  status        text        not null default 'due'
                  check (status in ('due', 'completed', 'rolled_over')),
  escalated     boolean     not null default false,
  created_at    timestamptz not null default now(),
  completed_at  timestamptz
);

create index if not exists idx_settlement_batches_status
  on public.settlement_batches (status);

alter table public.settlement_batches enable row level security;

create table if not exists public.settlement_items (
  id                 uuid        primary key default gen_random_uuid(),
  batch_id           uuid        not null references public.settlement_batches(id) on delete cascade,
  seller_id          uuid        not null references public.profiles(id) on delete restrict,
  -- Snapshot at batch creation: a wallet change mid-cycle never redirects an
  -- in-flight payout (onboarding spec §3.3 — next cycle only).
  payout_wallet      text        not null,
  total_kwh          numeric     not null check (total_kwh >= 0),
  total_amount       numeric     not null check (total_amount >= 0),
  contribution_count integer     not null check (contribution_count > 0),
  missed_cycles      integer     not null default 0,
  escalated          boolean     not null default false,
  paid               boolean     not null default false,
  tx_signature       text,
  paid_at            timestamptz,
  created_at         timestamptz not null default now(),
  -- One payout line per seller per batch.
  constraint settlement_items_one_per_seller unique (batch_id, seller_id)
);

create index if not exists idx_settlement_items_batch
  on public.settlement_items (batch_id);

alter table public.settlement_items enable row level security;

-- Sellers can see their own payout lines (dashboard "next payout" view).
drop policy if exists "sellers read own settlement items" on public.settlement_items;
create policy "sellers read own settlement items"
  on public.settlement_items for select
  to authenticated
  using ((select auth.uid()) = seller_id);

grant select on public.settlement_items to authenticated;
grant select on public.settlement_batches to authenticated;
-- service_role writes are covered by migration 000009's default privileges.

-- Contributions link to the payout item that covers them; re-pointed when an
-- unpaid item rolls forward into the next batch.
alter table public.contributions
  add column if not exists settlement_item_id uuid
    references public.settlement_items(id) on delete set null;

create index if not exists idx_contributions_settlement_item
  on public.contributions (settlement_item_id);
