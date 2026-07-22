-- Allow authenticated users to read community pools.
--
-- The operator dashboard's approve form lists pools via the anon-key client
-- with the operator's session; community_pool has had RLS on since the
-- initial schema but never a select policy, so that query silently returned
-- zero rows (empty dropdown). Pools are not sensitive — any signed-in user
-- may list them (sellers will eventually see their own pool name too).

drop policy if exists "authenticated read community pool" on public.community_pool;
create policy "authenticated read community pool"
  on public.community_pool for select
  to authenticated
  using (true);

grant select on public.community_pool to authenticated;
