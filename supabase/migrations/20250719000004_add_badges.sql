-- Phase 8 — cNFT contribution badges
--
-- badge_thresholds: milestone thresholds that trigger a cNFT mint when a
-- seller's cumulative settled kwh_contributed crosses them.
-- PLACEHOLDER values (100 / 500 / 1000 kWh) — replace with real numbers
-- per "Open items" #4 in gridright_architecture.md.
--
-- seller_badges: one row per (seller, threshold) mint. The unique
-- constraint is the idempotency guarantee — a threshold can never be
-- minted twice for the same seller, even under concurrent settlement.

create table if not exists public.badge_thresholds (
  id            uuid        primary key default gen_random_uuid(),
  threshold_kwh numeric     not null unique check (threshold_kwh > 0),
  label         text        not null,
  is_active     boolean     not null default true,
  created_at    timestamptz not null default now()
);

alter table public.badge_thresholds enable row level security;

-- PLACEHOLDER thresholds — tune later per architecture doc "Open items"
insert into public.badge_thresholds (threshold_kwh, label) values
  (100,  'Community Contributor — 100 kWh'),
  (500,  'Community Supporter — 500 kWh'),
  (1000, 'Community Champion — 1000 kWh');

create table if not exists public.seller_badges (
  id             uuid        primary key default gen_random_uuid(),
  seller_id      uuid        not null references public.profiles(id) on delete restrict,
  threshold_kwh  numeric     not null references public.badge_thresholds(threshold_kwh),
  label          text        not null,
  -- cumulative settled kWh at mint time, for the audit trail
  kwh_at_mint    numeric     not null check (kwh_at_mint >= 0),
  -- cNFT mint details (nullable until the on-chain mint confirms)
  asset_id       text,
  tx_signature   text,
  mint_status    text        not null default 'pending'
                             check (mint_status in ('pending', 'minted', 'failed')),
  created_at     timestamptz not null default now(),
  -- exactly one badge per seller per threshold — the re-mint guard
  constraint seller_badges_one_per_threshold unique (seller_id, threshold_kwh)
);

create index idx_seller_badges_seller_id on public.seller_badges(seller_id);

alter table public.seller_badges enable row level security;
