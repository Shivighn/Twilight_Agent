-- Fleet Issue Auto-Assignment & WhatsApp Escalation Agent
-- See "inspection tagging agent.txt" (repo root) for the full spec.
--
-- Run this against the target Supabase branch (Stage first, then Production)
-- via the SQL editor or `psql`. Safe to re-run (IF NOT EXISTS throughout).

create extension if not exists pgcrypto;

-- One row per issue this agent has ever looked at. Doubles as:
--   1. the idempotency guard (unique on issue_id — an upsert here can never
--      create a duplicate "first" notification even if the daily run fires
--      twice or overlaps itself)
--   2. the status-history record (last_status / last_status_changed_at is
--      enough to implement "reset the escalation timer on status change" —
--      a separate fleet_issue_status_history table is deferred; add one
--      later only if a full audit trail of every status transition is
--      ever needed)
--   3. the WhatsApp delivery state machine (pending/sent/failed +
--      attempt_count) so a failed send is retried, never silently dropped
--      or duplicated
create table if not exists fleet_issue_notifications (
  id uuid primary key default gen_random_uuid(),

  issue_id uuid not null,
  issue_number integer not null,
  vehicle_number text,

  fleet_manager_id text,
  assignment_status text not null default 'assigned', -- 'assigned' | 'unmapped'
  unmapped_reason text,

  first_detected_at timestamptz not null default now(),

  -- Status-change tracking (drives escalation timing — see spec section 6)
  last_status text,
  last_status_changed_at timestamptz,

  -- One-shot notification timestamps. Set once; uday/senior are cleared
  -- back to NULL whenever last_status changes, so a new escalation cycle
  -- can fire again for the new status period.
  fm_notified_at timestamptz,
  uday_notified_at timestamptz,
  senior_escalation_notified_at timestamptz,

  last_notification_type text, -- 'fm' | 'uday_escalation' | 'senior_escalation'
  last_notification_at timestamptz,
  notification_count integer not null default 0,

  -- WhatsApp delivery state for the *most recent* notification attempt.
  -- ('sent' history for earlier notification types is implied by the
  -- corresponding *_notified_at column already being set.)
  notification_state text not null default 'pending', -- 'pending' | 'sent' | 'failed'
  attempt_count integer not null default 0,
  last_attempt_at timestamptz,
  error_message text,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint fleet_issue_notifications_issue_id_key unique (issue_id)
);

create index if not exists fleet_issue_notifications_state_idx
  on fleet_issue_notifications (notification_state)
  where notification_state != 'sent';

-- One row per daily run, for the log summary described in spec section 18.
create table if not exists fleet_issue_agent_runs (
  id uuid primary key default gen_random_uuid(),
  run_id text not null,

  started_at timestamptz not null default now(),
  completed_at timestamptz,

  issues_scanned integer not null default 0,
  new_issues integer not null default 0,
  issues_assigned integer not null default 0,
  unmapped_issues integer not null default 0,

  fm_notifications_sent integer not null default 0,
  uday_escalations_sent integer not null default 0,
  senior_escalations_sent integer not null default 0,
  whatsapp_failures integer not null default 0,

  error_message text,
  created_at timestamptz not null default now()
);
