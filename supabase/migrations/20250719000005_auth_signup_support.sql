-- Auth signup support.
--
-- 1. handle_new_user trigger: creates a public.profiles row for every new
--    auth.users row. Role is always 'seller' — public signup cannot create
--    an operator. Operator accounts are provisioned by an admin (seed.sql
--    locally, auth admin API in production) which flips the role afterwards.
-- 2. RLS policies on public.profiles: login and the proxy guard read the
--    caller's own role via the anon-key client, so authenticated users must
--    be able to select their own row. No insert/update policies — the
--    trigger runs as the function owner and admins use the service role.

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id, role, email, display_name)
  values (
    new.id,
    'seller',
    new.email,
    nullif(new.raw_user_meta_data ->> 'display_name', '')
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

drop policy if exists "users read own profile" on public.profiles;
create policy "users read own profile"
  on public.profiles for select
  to authenticated
  using ((select auth.uid()) = id);

-- RLS policies only filter rows; the role also needs the table-level
-- privilege. Without this grant every profile read (login role lookup,
-- proxy guard) fails with 42501 regardless of policy.
grant select on public.profiles to authenticated;
