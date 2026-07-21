-- Add direction field to contributions for import/export/local_pool tracking
alter table public.contributions
  add column if not exists direction text
    not null default 'local_pool'
    check (direction in ('local_pool', 'import', 'export'));
