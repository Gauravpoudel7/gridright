-- Stamp the app role into auth.users.raw_app_meta_data so it lands in JWT
-- claims.
--
-- The FastAPI backend authorizes per-route from the token's app_metadata.role
-- (see apps/api/app/auth.py) — but sellers only ever had a role in
-- public.profiles, never in auth metadata, so every seller JWT reached the
-- API with no role claim and seller endpoints returned 403 ("Seller role
-- required"). Web-side checks read profiles directly, which is why login and
-- page gating worked while API calls silently failed.
--
-- app_metadata (not user_metadata) is used deliberately: users can edit their
-- own user_metadata via auth.updateUser, so a role there would be forgeable.

-- 1. Backfill every existing user from their profiles row.
update auth.users u
set raw_app_meta_data =
  coalesce(u.raw_app_meta_data, '{}'::jsonb)
  || jsonb_build_object('role', p.role)
from public.profiles p
where p.id = u.id;

-- 2. Future signups: handle_new_user stamps the claim alongside the profile.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id, role, email, display_name, must_change_password)
  values (
    new.id,
    'seller',
    new.email,
    nullif(new.raw_user_meta_data ->> 'display_name', ''),
    coalesce((new.raw_user_meta_data ->> 'must_change_password')::boolean, false)
  )
  on conflict (id) do nothing;

  -- Mirror the role into app_metadata so the JWT carries it. Public signup is
  -- always 'seller'; admin provisioning flips both profiles.role and
  -- app_metadata afterwards.
  update auth.users
  set raw_app_meta_data =
    coalesce(raw_app_meta_data, '{}'::jsonb) || '{"role": "seller"}'::jsonb
  where id = new.id;

  return new;
end;
$$;
