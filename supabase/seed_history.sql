-- OPTIONAL local-only seed: 14 days of hourly meter history for the test
-- seller, so the *learned* AI has data to work with when you test locally.
--
-- Why this is separate from seed.sql: seed.sql only creates summarised
-- contributions, not raw meter_readings — so LearnedDemand and the adaptive
-- forecast have nothing to learn from and silently fall back to the heuristic
-- (correct, but you can't see the new behaviour). Running this file gives the
-- seller a bound meter device plus realistic hourly generation/consumption
-- history that:
--   * LearnedDemand turns into a real per-hour community demand curve
--     (meter_readings.consumption_kwh), replacing the 8/14/22 heuristic, and
--   * the forecast job turns into a per-seller surplus history.
--
-- The rows are marked aggregated = true on purpose: this is HISTORY for the
-- models, not new surplus to price — the settlement/aggregation job must not
-- sweep it into contributions or payouts.
--
-- Run it AFTER `supabase db reset` (which runs migrations + seed.sql):
--   psql "$DATABASE_URL" -f supabase/seed_history.sql
-- or:  supabase db reset && psql "$SUPABASE_DB_URL" -f supabase/seed_history.sql
--
-- Safe to re-run: inserts are guarded / time-relative to now().

-- 1) Give the test seller a location (forecasting only runs for sellers with
--    lat/lng) and a bound meter.
update public.profiles
set latitude = 12.9,
    longitude = 77.6,
    meter_binding_status = 'bound',
    meter_id = 'SEED-METER-001'
where id = '00000000-0000-0000-0000-000000000001';

-- 2) Register the meter device the readings reference (token hash is a dummy;
--    this device never ingests over the network in local testing).
insert into public.meter_devices (seller_id, meter_device_id, device_token_hash)
values (
  '00000000-0000-0000-0000-000000000001',
  'SEED-METER-001',
  encode(digest('seed-local-only', 'sha256'), 'hex')
)
on conflict (meter_device_id) do nothing;

-- 3) 14 days x 24 hours of readings with a realistic daily shape:
--    - consumption: overnight low, a morning bump, and a pronounced EVENING
--      peak (deliberately different from the 8/14/22 heuristic so the learned
--      curve is visibly its own thing).
--    - generation: a midday solar bell (zero at night).
--    - grid_export: whatever generation exceeds same-hour consumption.
insert into public.meter_readings
  (seller_id, meter_device_id, reading_at,
   generation_kwh, consumption_kwh, grid_export_kwh, aggregated)
select
  '00000000-0000-0000-0000-000000000001',
  'SEED-METER-001',
  date_trunc('day', now()) - make_interval(days => d) + make_interval(hours => h),
  gen.generation_kwh,
  con.consumption_kwh,
  greatest(gen.generation_kwh - con.consumption_kwh, 0),
  true
from generate_series(1, 14) as d
cross join generate_series(0, 23) as h
cross join lateral (
  select round((greatest(0, 10 * sin(pi() * (h - 6) / 12.0)))::numeric, 3) as generation_kwh
) as gen
cross join lateral (
  select round((
    case
      when h between 0 and 5  then 5.0    -- overnight baseline
      when h between 6 and 8  then 12.0   -- morning bump
      when h between 9 and 16 then 7.0    -- daytime plateau
      when h between 17 and 21 then 18.0  -- evening peak
      else 8.0                            -- late evening
    end
    -- small deterministic per-day wobble so hours aren't identical every day
    + (((d * 7 + h) % 5) - 2) * 0.4
  )::numeric, 3) as consumption_kwh
) as con;
