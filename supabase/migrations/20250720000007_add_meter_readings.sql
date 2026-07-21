-- Phase 2 (advanced roadmap) — Smart meter: real per-seller ingestion.
--
-- meter_devices: one registered smart meter per seller. The device
-- authenticates ingestion with a bearer token; only the SHA-256 hash is
-- stored (the plaintext token is shown once at registration).
--
-- meter_readings: raw per-reading data. surplus_kwh is a generated column
-- (generation - consumption, floored at 0) so it can never disagree with
-- its inputs.

create table if not exists public.meter_devices (
  id                uuid        primary key default gen_random_uuid(),
  seller_id         uuid        not null references public.profiles(id) on delete cascade,
  meter_device_id   text        not null unique,
  device_token_hash text        not null,
  created_at        timestamptz not null default now(),
  -- One device per seller for now. Decision: multi-meter households are out
  -- of scope until a real need appears; relaxing this later is additive.
  constraint meter_devices_one_per_seller unique (seller_id)
);

alter table public.meter_devices enable row level security;

drop policy if exists "sellers read own meter device" on public.meter_devices;
create policy "sellers read own meter device"
  on public.meter_devices for select
  to authenticated
  using ((select auth.uid()) = seller_id);

grant select on public.meter_devices to authenticated;
-- The API's service-role client manages devices (register/replace/auth-check).
grant select, insert, update, delete on public.meter_devices to service_role;

create table if not exists public.meter_readings (
  id               uuid        primary key default gen_random_uuid(),
  seller_id        uuid        not null references public.profiles(id) on delete cascade,
  meter_device_id  text        not null references public.meter_devices(meter_device_id) on delete cascade,
  reading_at       timestamptz not null,
  generation_kwh   numeric     not null check (generation_kwh >= 0),
  consumption_kwh  numeric     not null check (consumption_kwh >= 0),
  surplus_kwh      numeric     generated always as (greatest(generation_kwh - consumption_kwh, 0)) stored,
  grid_export_kwh  numeric     not null check (grid_export_kwh >= 0),
  created_at       timestamptz not null default now(),
  -- A device can't export more than it generated in the reading window.
  constraint meter_readings_export_bounded check (grid_export_kwh <= generation_kwh)
);

create index if not exists idx_meter_readings_seller_time
  on public.meter_readings (seller_id, reading_at);

alter table public.meter_readings enable row level security;

drop policy if exists "sellers read own meter readings" on public.meter_readings;
create policy "sellers read own meter readings"
  on public.meter_readings for select
  to authenticated
  using ((select auth.uid()) = seller_id);

grant select on public.meter_readings to authenticated;
-- The API's service-role client writes readings and reads recents.
grant select, insert on public.meter_readings to service_role;

-- Realtime: the seller dashboard subscribes to postgres_changes on this
-- table (via the existing useRealtimeTable hook). Add it to the realtime
-- publication if that publication exists (it does under Supabase).
do $$
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    alter publication supabase_realtime add table public.meter_readings;
  end if;
exception when duplicate_object then
  null; -- already in the publication
end $$;
