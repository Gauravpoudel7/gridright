-- Phase 3 (advanced roadmap) — AI surplus forecasting.
--
-- 1. Seller location on profiles: needed to look up weather. Nullable —
--    forecasting simply skips sellers without a location.
-- 2. surplus_forecasts: per-seller predicted surplus for a future timestamp,
--    with mandatory explainability (factors jsonb) and accuracy tracking
--    (actual_surplus_kwh + delta filled in once real meter_readings land).

alter table public.profiles
  add column if not exists latitude  numeric check (latitude  between -90  and 90),
  add column if not exists longitude numeric check (longitude between -180 and 180);

-- The API's service-role client reads profiles (wallet checks, forecast
-- seller discovery). This grant was missing from earlier migrations — the
-- wallet helper masked it by swallowing errors.
grant select on public.profiles to service_role;

create table if not exists public.surplus_forecasts (
  id                    uuid        primary key default gen_random_uuid(),
  seller_id             uuid        not null references public.profiles(id) on delete cascade,
  forecast_for          timestamptz not null,
  predicted_surplus_kwh numeric     not null check (predicted_surplus_kwh >= 0),
  confidence            numeric     not null check (confidence >= 0 and confidence <= 1),
  -- Why the number is what it is (cloud cover, historical average, trend...).
  -- Application code enforces non-empty; the DB enforces presence.
  factors               jsonb       not null,
  generated_at          timestamptz not null default now(),
  -- Accuracy: filled once actual meter readings exist for forecast_for.
  actual_surplus_kwh    numeric,
  accuracy_delta_kwh    numeric,
  accuracy_computed_at  timestamptz,
  constraint surplus_forecasts_factors_not_empty check (factors <> '{}'::jsonb)
);

-- One forecast per seller per target hour per generation run is plenty;
-- lookups are always by seller and target-time range.
create index if not exists idx_surplus_forecasts_seller_time
  on public.surplus_forecasts (seller_id, forecast_for);

alter table public.surplus_forecasts enable row level security;

drop policy if exists "sellers read own forecasts" on public.surplus_forecasts;
create policy "sellers read own forecasts"
  on public.surplus_forecasts for select
  to authenticated
  using ((select auth.uid()) = seller_id);

grant select on public.surplus_forecasts to authenticated;
-- The API's service-role client writes forecasts and accuracy updates.
grant select, insert, update on public.surplus_forecasts to service_role;
