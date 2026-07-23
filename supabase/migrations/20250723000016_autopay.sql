-- Auto-pay (small payouts settle without a human click).
--
-- paid_method records HOW a settlement item was paid so the operator can
-- audit machine payments separately from their own:
--   'manual' — operator paid via the dashboard (Phantom) and recorded the tx
--   'auto'   — the auto-pay job paid it server-side (non-escalated items
--              below the AUTOPAY_MAX_USD threshold only)
-- Null for unpaid items and for items paid before this migration.

alter table public.settlement_items
  add column if not exists paid_method text
    check (paid_method in ('manual', 'auto'));
