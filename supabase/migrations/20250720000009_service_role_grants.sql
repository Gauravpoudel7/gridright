-- Service-role grants, comprehensive fix.
--
-- The API's backend client authenticates as service_role. Tables created in
-- earlier migrations don't consistently carry privileges for that role under
-- the local CLI's migration runner (we hit 42501 on profiles, meter_devices,
-- and contributions one by one). Grant across the board and set default
-- privileges so future tables don't repeat this.
--
-- RLS still applies to authenticated/anon clients; service_role bypasses RLS
-- by design (backend trust boundary is the API layer).

grant usage on schema public to service_role;
grant select, insert, update, delete on all tables in schema public to service_role;
grant usage, select on all sequences in schema public to service_role;

alter default privileges in schema public
  grant select, insert, update, delete on tables to service_role;
alter default privileges in schema public
  grant usage, select on sequences to service_role;
