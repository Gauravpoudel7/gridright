-- Seed test data for local development.
-- Runs automatically on `supabase db reset` (after all migrations).
--
-- Test credentials (local only — never ship this file to a hosted project):
--   seller:   seller@test.com   / password123
--   operator: operator@grid.com / password123
--
-- Users are inserted directly into auth.users with a bcrypt hash, plus the
-- auth.identities row GoTrue requires for email/password sign-in. The
-- on_auth_user_created trigger (migration 0005) creates the profiles rows
-- with role 'seller'; we then flip the operator's role.

insert into auth.users
  (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
   raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
   confirmation_token, recovery_token, email_change, email_change_token_new)
values
  ('00000000-0000-0000-0000-000000000000',
   '00000000-0000-0000-0000-000000000001',
   'authenticated', 'authenticated', 'seller@test.com',
   crypt('password123', gen_salt('bf')), now(),
   '{"provider":"email","providers":["email"]}',
   '{"display_name":"Test Seller"}',
   now(), now(), '', '', '', ''),
  ('00000000-0000-0000-0000-000000000000',
   '00000000-0000-0000-0000-000000000002',
   'authenticated', 'authenticated', 'operator@grid.com',
   crypt('password123', gen_salt('bf')), now(),
   '{"provider":"email","providers":["email"]}',
   '{"display_name":"Test Operator"}',
   now(), now(), '', '', '', '')
on conflict (id) do nothing;

insert into auth.identities
  (id, user_id, provider_id, identity_data, provider, last_sign_in_at,
   created_at, updated_at)
values
  (gen_random_uuid(), '00000000-0000-0000-0000-000000000001',
   '00000000-0000-0000-0000-000000000001',
   '{"sub":"00000000-0000-0000-0000-000000000001","email":"seller@test.com","email_verified":true}',
   'email', now(), now(), now()),
  (gen_random_uuid(), '00000000-0000-0000-0000-000000000002',
   '00000000-0000-0000-0000-000000000002',
   '{"sub":"00000000-0000-0000-0000-000000000002","email":"operator@grid.com","email_verified":true}',
   'email', now(), now(), now())
on conflict (provider_id, provider) do nothing;

-- The trigger created both profiles as 'seller'; promote the operator.
update public.profiles
set role = 'operator'
where id = '00000000-0000-0000-0000-000000000002';

-- The API reads role from the JWT's app_metadata (see app/auth.py), so the
-- operator's role must also live in auth metadata — profiles alone only
-- covers the web proxy's server-side check. Same for the seller.
update auth.users
set raw_app_meta_data = raw_app_meta_data || '{"role":"operator"}'::jsonb
where id = '00000000-0000-0000-0000-000000000002';

update auth.users
set raw_app_meta_data = raw_app_meta_data || '{"role":"seller"}'::jsonb
where id = '00000000-0000-0000-0000-000000000001';

-- Seed seller dashboard data. Prices/payouts use the placeholder policy
-- numbers (tariff 0.10, +15% uplift → 0.115/kWh).
insert into public.contributions
  (seller_id, kwh_contributed, period_start, period_end,
   ai_recommended_price, final_approved_price, approval_type,
   payout_amount, status)
values
  ('00000000-0000-0000-0000-000000000001', 150.0,
   '2026-07-01', '2026-07-15', 0.115, 0.115, 'auto', 17.25, 'settled'),
  ('00000000-0000-0000-0000-000000000001', 200.5,
   '2026-06-16', '2026-06-30', 0.115, 0.115, 'auto', 23.06, 'settled'),
  ('00000000-0000-0000-0000-000000000001', 175.0,
   '2026-07-01', '2026-07-15', 0.145, 0.145, null, 25.38, 'needs_review'),
  ('00000000-0000-0000-0000-000000000001', 80.0,
   '2026-07-01', '2026-07-15', 0.115, 0.115, 'auto', 9.20, 'pending');
