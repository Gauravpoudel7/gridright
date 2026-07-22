-- Seller Onboarding & Meter Binding Flow.
--
-- Supersedes the single-step "form → operator approves → done" design with a
-- state-tracked pipeline that separates identity approval, meter binding, and
-- wallet activation. See gridright_seller_onboarding_spec.md.
--
-- State machines encoded here as CHECK constraints; transitions are enforced
-- in the service layer (app/services/onboarding.py, meter_binding.py,
-- wallet_activation.py). The DB guards the terminal invariants the app must
-- never violate: meter_id uniqueness (one meter, one owner) above all.

-- ---------------------------------------------------------------------------
-- 1. seller_applications — identity review, pre-auth-user.
--
-- An applicant has NO auth.users row until an operator approves them, so this
-- can't hang columns off profiles (profiles.id FK-references auth.users).
-- profile_id is backfilled once the auth user is created at approval time.
-- ---------------------------------------------------------------------------
create table if not exists public.seller_applications (
  id                 uuid        primary key default gen_random_uuid(),
  profile_id         uuid        references public.profiles(id) on delete set null,
  full_name          text        not null,
  dob                date        not null,
  ownership_doc_url  text        not null,
  gmail              text        not null,
  location_text      text        not null,
  application_status text        not null default 'submitted'
                       check (application_status in
                         ('submitted', 'identity_approved', 'identity_rejected')),
  rejection_reason   text,
  -- One-time token (hashed, like meter device tokens) that lets an
  -- unauthenticated applicant check status / resubmit after rejection.
  edit_token_hash    text        not null,
  community_pool_id  uuid        references public.community_pool(id) on delete set null,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  -- A rejected application must carry a reason (mirrors the operator-reason
  -- invariant on contributions).
  constraint application_rejection_reason_required check (
    application_status != 'identity_rejected'
    or (rejection_reason is not null and rejection_reason != '')
  )
);

create index if not exists idx_seller_applications_status
  on public.seller_applications (application_status);

alter table public.seller_applications enable row level security;
-- No authenticated policies: applications are managed entirely by the API's
-- service-role client (public submit, operator review). service_role bypasses
-- RLS; anon/authenticated get nothing directly.

-- ---------------------------------------------------------------------------
-- 2. profiles — onboarding state columns.
-- ---------------------------------------------------------------------------
alter table public.profiles
  add column if not exists meter_binding_status text not null default 'unbound'
    check (meter_binding_status in
      ('unbound', 'pairing_pending', 'bound', 'binding_failed')),
  -- Set ONLY once binding succeeds — never at submission time. Unique so a
  -- meter already bound to one profile cannot be claimed by another (spec §3.2,
  -- §5). This is the DB-level half of the uniqueness guarantee; the service
  -- layer returns a friendly "already claimed" before hitting it.
  add column if not exists meter_id text unique,
  add column if not exists community_pool_id uuid
    references public.community_pool(id) on delete set null,
  add column if not exists wallet_status text not null default 'not_connected'
    check (wallet_status in ('not_connected', 'active')),
  -- Set true whenever an operator issues initial credentials; the API gates all
  -- other seller routes until the seller changes it (spec §2, §4).
  add column if not exists must_change_password boolean not null default true;

-- Backfill: existing sellers chose their own password and (if they connected a
-- wallet already) are effectively active. New self-signups are handled by the
-- trigger below; the default of true only applies to operator-provisioned rows.
update public.profiles set must_change_password = false
  where must_change_password is true;
update public.profiles set wallet_status = 'active'
  where wallet_address is not null and wallet_status = 'not_connected';

-- ---------------------------------------------------------------------------
-- 3. wallet_history — audit trail of every signed wallet (re)connect.
-- ---------------------------------------------------------------------------
create table if not exists public.wallet_history (
  id                 uuid        primary key default gen_random_uuid(),
  profile_id         uuid        not null references public.profiles(id) on delete cascade,
  old_wallet         text,       -- null for the first connect
  new_wallet         text        not null,
  signature_verified boolean     not null default false,
  changed_at         timestamptz not null default now()
);

create index if not exists idx_wallet_history_profile
  on public.wallet_history (profile_id, changed_at);

alter table public.wallet_history enable row level security;

drop policy if exists "sellers read own wallet history" on public.wallet_history;
create policy "sellers read own wallet history"
  on public.wallet_history for select
  to authenticated
  using ((select auth.uid()) = profile_id);

grant select on public.wallet_history to authenticated;
-- Writes go through the API's service-role client (blanket grant in 000009).

-- ---------------------------------------------------------------------------
-- 4. wallet_challenges — single-use nonces for signed wallet connect.
--
-- The backend issues a nonce, the wallet signs it, the backend verifies the
-- ed25519 signature server-side before accepting the address (spec §3.3, §4).
-- Never accept a pasted address without a signature over a fresh nonce.
-- ---------------------------------------------------------------------------
create table if not exists public.wallet_challenges (
  id          uuid        primary key default gen_random_uuid(),
  profile_id  uuid        not null references public.profiles(id) on delete cascade,
  nonce       text        not null unique,
  expires_at  timestamptz not null,
  consumed_at timestamptz,
  created_at  timestamptz not null default now()
);

create index if not exists idx_wallet_challenges_profile
  on public.wallet_challenges (profile_id);

alter table public.wallet_challenges enable row level security;
-- Managed entirely by the service-role client; no authenticated policies.

-- ---------------------------------------------------------------------------
-- 4b. meter_pairing_attempts — sliding-window rate limit for pairing-code
--     exchange (spec §4: prevent brute-forcing meter codes). One row per
--     attempt; the service counts rows within the window per profile.
-- ---------------------------------------------------------------------------
create table if not exists public.meter_pairing_attempts (
  id                 uuid        primary key default gen_random_uuid(),
  profile_id         uuid        not null references public.profiles(id) on delete cascade,
  attempted_at_epoch double precision not null,
  created_at         timestamptz not null default now()
);

create index if not exists idx_meter_pairing_attempts_profile_time
  on public.meter_pairing_attempts (profile_id, attempted_at_epoch);

alter table public.meter_pairing_attempts enable row level security;
-- Managed by the service-role client only.

-- ---------------------------------------------------------------------------
-- 5. contributions.payout_wallet — snapshot for next-cycle-only wallet change.
--
-- A wallet change takes effect from the NEXT settlement cycle: any contribution
-- already computed against the old wallet is unaffected (spec §3.3). We snapshot
-- the wallet onto the row at decision/insert time so a later profile update
-- never rewrites in-flight payouts.
-- ---------------------------------------------------------------------------
alter table public.contributions
  add column if not exists payout_wallet text;

-- ---------------------------------------------------------------------------
-- 6. handle_new_user — self-signups pick their own password, so they must NOT
--    be forced through the password-change gate. Operator-provisioned sellers
--    get must_change_password=true set explicitly by the approval path.
-- ---------------------------------------------------------------------------
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
    -- Operator-created accounts carry a flag in metadata; everyone else
    -- (public signup) chose their own password → no forced change.
    coalesce((new.raw_user_meta_data ->> 'must_change_password')::boolean, false)
  )
  on conflict (id) do nothing;
  return new;
end;
$$;
