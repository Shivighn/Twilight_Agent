-- Petpooja Captain Order Automation
-- See docs/PETPOOJA_CAPTAIN_ORDER_AUTOMATION.md for the full design.
--
-- Run this against the target Supabase project (main FleetZen project,
-- fpmfqdhyfclwtpqhhhtp) via the SQL editor or `psql`. Safe to re-run
-- (`if not exists` throughout).
--
-- NOTE: superseded in part by 2026-10-24_petpooja_captain_orders_schema_update.sql
-- (chat_name/provider_mode/next_attempt_at dropped, vehicle_number renamed
-- to bus_number, attempt_count+max_attempts merged into attempts_made,
-- parsing_status/petpooja_status converted to enums) — this file is kept
-- as-is for history; run both in order on a fresh project.

create extension if not exists pgcrypto;

-- One row per WhatsApp message in the dedicated orders group. Doubles as:
--   1. the inbound message log (raw_text/chat_name/sender/received_at)
--   2. the parsed order (vehicle_number/passenger_count/order_items)
--   3. the idempotency guard (unique on whatsapp_message_id — a redelivered
--      message, or a retry after a crash mid-flow, can never create a
--      second Petpooja order for the same message)
--   4. the outbox/job queue (petpooja_status + attempt bookkeeping below),
--      polled by the background retry sweep described in the design doc
--   5. the Petpooja response/audit log (petpooja_order_id/petpooja_response)
create table if not exists petpooja_captain_orders (
  id uuid primary key default gen_random_uuid(),

  whatsapp_message_id text not null,
  chat_name text not null,
  sender text,
  raw_text text not null,
  received_at timestamptz not null default now(),

  vehicle_number text,
  passenger_count integer,

  -- [{ raw_name, quantity, matched_item_id, matched_item_name,
  --    match_status: 'matched'|'ambiguous'|'unmatched', match_confidence }]
  order_items jsonb not null default '[]',

  -- 'pending' | 'parsed' | 'needs_review' | 'parse_failed'
  parsing_status text not null default 'pending',
  validation_notes text,

  -- 'not_submitted' | 'pending' | 'creating' | 'created' | 'failed' | 'manual_review'
  petpooja_status text not null default 'not_submitted',
  petpooja_order_id text,
  petpooja_response jsonb,
  provider_mode text not null default 'mock',

  attempt_count integer not null default 0,
  max_attempts integer not null default 5,
  next_attempt_at timestamptz,
  last_attempt_at timestamptz,
  last_error text,

  reply_sent text,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint petpooja_captain_orders_message_id_key unique (whatsapp_message_id)
);

create index if not exists petpooja_captain_orders_retry_idx
  on petpooja_captain_orders (next_attempt_at)
  where petpooja_status = 'failed';

create index if not exists petpooja_captain_orders_review_idx
  on petpooja_captain_orders (received_at)
  where parsing_status = 'needs_review';

create index if not exists petpooja_captain_orders_chat_time_idx
  on petpooja_captain_orders (chat_name, received_at desc);
