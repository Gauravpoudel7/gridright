-- GridRight Initial Schema
-- Phase 1 — Database schema
--
-- Placeholders (to replace with real numbers per "Open items" in architecture doc):
--   - seller_uplift_percentage      → 15 (PLACEHOLDER)
--   - operator_margin_percentage    →  5 (PLACEHOLDER)
--   - band_width_percentage         →  5 (PLACEHOLDER)
--   - pool_capacity_limit_kwh       → 10000 (PLACEHOLDER)
--   - feed_in_tariff_reference      → 0.10 (PLACEHOLDER, $/kWh)

-- 1. Profiles — linked to Supabase Auth
create table if not exists public.profiles (
  id          uuid        primary key references auth.users on delete cascade,
  role        text        not null check (role in ('seller', 'operator')) default 'seller',
  email       text        not null,
  display_name text,
  created_at  timestamptz not null default now()
);

alter table public.profiles enable row level security;

-- 2. Community pool — aggregate running totals
create table if not exists public.community_pool (
  id                    uuid        primary key default gen_random_uuid(),
  total_kwh_contributed numeric     not null default 0 check (total_kwh_contributed >= 0),
  current_absorption_kwh numeric    not null default 0 check (current_absorption_kwh >= 0),
  absorption_limit_kwh  numeric     not null check (absorption_limit_kwh > 0),
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);

alter table public.community_pool enable row level security;

-- 3. Contributions — per-period seller records
create table if not exists public.contributions (
  id                    uuid        primary key default gen_random_uuid(),
  seller_id             uuid        not null references public.profiles(id) on delete restrict,
  kwh_contributed       numeric     not null check (kwh_contributed > 0),
  period_start          timestamptz not null,
  period_end            timestamptz not null,
  ai_recommended_price  numeric     not null check (ai_recommended_price >= 0),
  final_approved_price  numeric     not null check (final_approved_price >= 0),
  approval_type         text        not null check (approval_type in ('auto', 'human')),
  approval_reason       text,
  payout_amount         numeric     not null check (payout_amount >= 0),
  status                text        not null default 'pending' check (status in ('pending', 'settled')),
  tx_signature          text,
  created_at            timestamptz not null default now(),
  constraint contributions_period_check check (period_end > period_start),
  constraint approval_reason_required_for_human check (
    approval_type != 'human' or (approval_reason is not null and approval_reason != '')
  )
);

create index idx_contributions_seller_id on public.contributions(seller_id);
create index idx_contributions_status on public.contributions(status);
create index idx_contributions_period on public.contributions(period_start, period_end);

alter table public.contributions enable row level security;

-- 4. Operator policy — configurable without code changes
create table if not exists public.operator_policy (
  id                        uuid        primary key default gen_random_uuid(),
  band_width_percentage     numeric     not null check (band_width_percentage >= 0),
  pool_capacity_limit_kwh   numeric     not null check (pool_capacity_limit_kwh > 0),
  seller_uplift_percentage  numeric     not null check (seller_uplift_percentage >= 0),
  operator_margin_percentage numeric    not null check (operator_margin_percentage >= 0),
  feed_in_tariff_reference  numeric     not null check (feed_in_tariff_reference >= 0),
  is_active                 boolean     not null default true,
  created_at                timestamptz not null default now(),
  updated_at                timestamptz not null default now()
);

alter table public.operator_policy enable row level security;

-- Seed the default policy row with PLACEHOLDER values
insert into public.operator_policy
  (band_width_percentage, pool_capacity_limit_kwh, seller_uplift_percentage,
   operator_margin_percentage, feed_in_tariff_reference)
values
  (5, 10000, 15, 5, 0.10);
