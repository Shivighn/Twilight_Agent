-- Petpooja Captain Order Automation — schema update
-- Run this against the SAME Supabase project as
-- 2026-10-23_petpooja_captain_orders.sql (dxcmvzlfvwtpsejkmpoy). Safe to
-- re-run defensively (guards with if exists/if not exists where possible),
-- but it IS a one-way migration (column drops/renames) — take a look at
-- the table first if it holds anything you care about.
--
-- Changes:
--   1. Drop chat_name — this table is scoped to exactly one WhatsApp group
--      (config.petpooja_orders_whatsapp_group_name), so the value was the
--      same constant on every row.
--   2. Rename vehicle_number -> bus_number (and all code references).
--   3. parsing_status / petpooja_status -> real Postgres ENUMs, same
--      label set as before.
--   4. Drop provider_mode — written on every row but never read/branched
--      on anywhere in the code; config.petpooja_order_provider is what
--      actually controls behavior.
--   5. attempt_count + max_attempts -> single attempts_made, capped at 5
--      by a check constraint (application logic must never push it past
--      5 either — see petpooja_captain_order_tool.py).
--   6. Drop next_attempt_at (retry-sweep scheduling column; the sweep
--      itself was never built) — keep last_attempt_at.
--   7. sender: no schema change (column already existed) — it was simply
--      never populated; fixed in code (Node gateway now reads the
--      Baileys participant/remoteJid and forwards it through).

-- ── 1. chat_name ─────────────────────────────────────────────────────────
drop index if exists petpooja_captain_orders_chat_time_idx;
alter table petpooja_captain_orders drop column if exists chat_name;
create index if not exists petpooja_captain_orders_received_idx
  on petpooja_captain_orders (received_at desc);

-- ── 2. vehicle_number -> bus_number ──────────────────────────────────────
alter table petpooja_captain_orders rename column vehicle_number to bus_number;

-- ── 3. parsing_status / petpooja_status -> enums ─────────────────────────
do $$ begin
  create type petpooja_parsing_status_enum as enum
    ('pending', 'parsed', 'needs_review', 'parse_failed');
exception when duplicate_object then null;
end $$;

do $$ begin
  create type petpooja_order_status_enum as enum
    ('not_submitted', 'pending', 'creating', 'created', 'failed', 'manual_review');
exception when duplicate_object then null;
end $$;

-- Swap-column approach, not in-place ALTER COLUMN TYPE: Postgres can refuse
-- that in-place cast ("default for column ... cannot be cast automatically")
-- even after DROP DEFAULT — confirmed when this migration was actually run.
-- Adding a new enum column, copying every row's value across with an
-- explicit cast, then dropping the old column and renaming sidesteps it
-- entirely and is the standard safe recipe for this conversion.
alter table petpooja_captain_orders add column parsing_status_new petpooja_parsing_status_enum;
update petpooja_captain_orders set parsing_status_new = parsing_status::petpooja_parsing_status_enum;
drop index if exists petpooja_captain_orders_review_idx;
alter table petpooja_captain_orders drop column parsing_status;
alter table petpooja_captain_orders rename column parsing_status_new to parsing_status;
alter table petpooja_captain_orders alter column parsing_status set default 'pending';
alter table petpooja_captain_orders alter column parsing_status set not null;
create index if not exists petpooja_captain_orders_review_idx
  on petpooja_captain_orders (received_at)
  where parsing_status = 'needs_review';

alter table petpooja_captain_orders add column petpooja_status_new petpooja_order_status_enum;
update petpooja_captain_orders set petpooja_status_new = petpooja_status::petpooja_order_status_enum;
alter table petpooja_captain_orders drop column petpooja_status;
alter table petpooja_captain_orders rename column petpooja_status_new to petpooja_status;
alter table petpooja_captain_orders alter column petpooja_status set default 'not_submitted';
alter table petpooja_captain_orders alter column petpooja_status set not null;

-- ── 4. provider_mode ──────────────────────────────────────────────────────
alter table petpooja_captain_orders drop column if exists provider_mode;

-- ── 5. attempt_count + max_attempts -> attempts_made (capped at 5) ───────
update petpooja_captain_orders set attempt_count = 5 where attempt_count > 5;
alter table petpooja_captain_orders rename column attempt_count to attempts_made;
alter table petpooja_captain_orders drop column if exists max_attempts;
alter table petpooja_captain_orders
  add constraint petpooja_captain_orders_attempts_made_check
  check (attempts_made >= 0 and attempts_made <= 5);

-- ── 6. next_attempt_at ────────────────────────────────────────────────────
drop index if exists petpooja_captain_orders_retry_idx;
alter table petpooja_captain_orders drop column if exists next_attempt_at;
