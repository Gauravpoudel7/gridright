-- Meter readings → contributions bridge.
-- Each settlement run sweeps unaggregated readings, sums grid_export_kwh per
-- seller, and pushes the total through the recommend/policy pipeline to create
-- a contribution. This flag marks readings that have been swept so surplus is
-- never double-counted.

alter table meter_readings
  add column if not exists aggregated boolean not null default false;

create index if not exists idx_meter_readings_unaggregated
  on meter_readings (seller_id)
  where not aggregated;
