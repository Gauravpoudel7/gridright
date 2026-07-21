-- Add review/exception-queue support to contributions table.
-- A "review" is a contributions row with status = 'needs_review'.

-- 1. Widen the status check to include needs_review and rejected
alter table public.contributions
  drop constraint if exists contributions_status_check;

alter table public.contributions
  add constraint contributions_status_check
    check (status in ('pending', 'needs_review', 'settled', 'rejected'));

-- 2. Allow null approval_type (needs_review rows haven't been decided yet)
alter table public.contributions
  alter column approval_type drop not null;

-- 3. Drop then recreate the human-reason constraint so it handles null approval_type
alter table public.contributions
  drop constraint if exists approval_reason_required_for_human;

alter table public.contributions
  add constraint approval_reason_required_for_human
    check (
      approval_type is null
      or approval_type != 'human'
      or (approval_reason is not null and approval_reason != '')
    );

-- 4. Add review-specific columns
alter table public.contributions
  add column if not exists review_reason text;

alter table public.contributions
  add column if not exists reviewed_at timestamptz;

alter table public.contributions
  add column if not exists adjusted_price numeric
    check (adjusted_price is null or adjusted_price >= 0);
