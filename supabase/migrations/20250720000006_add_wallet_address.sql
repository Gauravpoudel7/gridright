-- Add wallet_address to profiles for Phantom wallet connection (Phase 9).
-- Nullable — users without a connected wallet are still valid; gating is
-- enforced at the application layer, not the DB constraint.

alter table public.profiles
  add column if not exists wallet_address text;

-- Allow authenticated users to update their own wallet_address.
-- The existing "users read own profile" policy already covers SELECT.
drop policy if exists "users update own wallet" on public.profiles;
create policy "users update own wallet"
  on public.profiles for update
  to authenticated
  using ((select auth.uid()) = id)
  with check ((select auth.uid()) = id);

grant update (wallet_address) on public.profiles to authenticated;
