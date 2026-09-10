# Fleet Issue Tagging Agent — Overview

Daily job that (1) auto-assigns open `issues` rows to the right Fleet
Manager based on the vehicle's recent trips, sends one WhatsApp message per
FM listing their new issues, then (2) on later runs, escalates via WhatsApp
any issue that has sat unchanged too long. Full spec: `inspection tagging
agent.txt` (repo root).

## 1. Files that make up this feature

| File | Role |
|---|---|
| [src/fleetIssues/index.js](src/fleetIssues/index.js) | Orchestrator — `runOnce()`, the whole daily algorithm |
| [src/fleetIssues/scheduler.js](src/fleetIssues/scheduler.js) | Registers `runOnce()` on a daily cron (`AGENT_RUN_TIME`, `AGENT_TIMEZONE`) |
| [src/fleetIssues/issueFetcher.js](src/fleetIssues/issueFetcher.js) | Pulls eligible open issues from `issues` |
| [src/fleetIssues/issueAssigner.js](src/fleetIssues/issueAssigner.js) | Assigns a new issue to an FM, writes the tracking row |
| [src/fleetIssues/fmResolver.js](src/fleetIssues/fmResolver.js) | `vehicle_number` → latest trip → `service_id` → `services_incharge.fleet_manager_id` |
| [src/fleetIssues/escalationManager.js](src/fleetIssues/escalationManager.js) | Decides if/when an already-assigned issue escalates |
| [src/fleetIssues/notificationTracker.js](src/fleetIssues/notificationTracker.js) | Reads/writes `fleet_issue_notifications` (idempotency + state) |
| [src/fleetIssues/messageBuilder.js](src/fleetIssues/messageBuilder.js) | Builds the FM-assignment and escalation WhatsApp text |
| [src/fleetIssues/whatsappSender.js](src/fleetIssues/whatsappSender.js) | Sends via the existing Baileys client (`src/whatsapp/client.js`) — no new connection |
| [src/fleetIssues/runLogger.js](src/fleetIssues/runLogger.js) | Per-run stats, logged + written to `fleet_issue_agent_runs` |
| [src/fleetIssues/db.js](src/fleetIssues/db.js) | Supabase PostgREST client for this feature (GET/POST/PATCH only, no delete) |
| [src/config/index.js](src/config/index.js) | `config.fleetIssues.*` — all env-driven settings, see below |
| [migrations/2026-08-12_fleet_issue_agent.sql](migrations/2026-08-12_fleet_issue_agent.sql) | `fleet_issue_notifications` + `fleet_issue_agent_runs` tables |
| [scripts/run-fleet-issue-agent-once.js](scripts/run-fleet-issue-agent-once.js) | **New** — manual one-off trigger (added for this doc, see below) |

Relevant `.env` keys already set in this repo: `FLEET_ISSUE_AGENT_ENABLED=false`,
`AGENT_TIMEZONE=Asia/Kolkata`, `AGENT_RUN_TIME=10:00`, `TRIP_LOOKBACK_DAYS=10`,
`FM_ESCALATION_DAYS=2`, `SENIOR_ESCALATION_DAYS=5`,
`FLEET_ISSUE_OPEN_STATUSES=Open,In Progress,Reopened`.

> `FLEET_ISSUE_AGENT_ENABLED=false` only stops the **daily cron** from being
> registered (`scheduler.js`). It does **not** block manual runs below —
> `runOnce()` itself doesn't check that flag.

---

## 2. Command 1 — run it manually and check allocation + WhatsApp send

```bash
npm run fleet-issues:run
```

This calls the exact same `runOnce()` the cron uses, once, and prints a
JSON summary (`issuesScanned`, `newIssues`, `issuesAssigned`,
`fmNotificationsSent`, `udayEscalationsSent`, `seniorEscalationsSent`,
`whatsappFailures`, …).

How to confirm it worked:

- **Allocation**: in Supabase, previously-`assignee_id IS NULL` issues now
  have `assignee_id` set, and `fleet_issue_notifications` has a new row per
  issue with `assignment_status='assigned'`.
- **WhatsApp sent**: check the group at `WHATSAPP_GROUP_ID` for a message
  like `Issues assigned to Anudeep:\n\n367 - Driver Complaints...`, and in
  `fleet_issue_notifications` that row's `notification_state='sent'` and
  `fm_notified_at` is set. `logs/gateway.log` also logs the send.
- If `notification_state='failed'`, check `error_message` on that row —
  usually `group_not_configured` or `group_not_found` (bad `WHATSAPP_GROUP_ID`).

---

## 3. Command 2 — simulate "48 hours later, 5 issues still Open"

The agent doesn't track real wall-clock wait time — it compares `now()` to
`fleet_issue_notifications.last_status_changed_at`. So to simulate "48
hours have passed with no status change," backdate that column for your 5
test issues (in Supabase), then re-run the same command:

```sql
update fleet_issue_notifications
set last_status_changed_at = now() - interval '2 days 1 hour'
where issue_id in (/* your 5 issue ids */);
```

```bash
npm run fleet-issues:run
```

**What happens:** `daysUnchanged` (≈2) ≥ `FM_ESCALATION_DAYS` (2) and
`uday_notified_at` is still null, so [escalationManager.js](src/fleetIssues/escalationManager.js)
returns `escalate: 'uday'`. Each of the 5 issues gets its **own** WhatsApp
message (not grouped, unlike the FM-assignment message):

```
⚠️ Issue Escalation

Issue 367 - Driver Complaints: Hand wash broken...
Vehicle: TG13T1986
Status: Open

This issue has remained unchanged for 2 days.

@Uday
```

`fleet_issue_notifications` for each: `uday_notified_at` = now,
`last_notification_type='uday_escalation'`, `notification_count` +1.
`udayEscalationsSent` in the run summary = 5.

---

## 4. Command 3 — same issues, 72 hours later, still nothing changed

⚠️ **With the thresholds currently in `.env`, 72 hours is not a special
point.** `SENIOR_ESCALATION_DAYS=5` (120 hours), not 3 (72 hours) — so
re-running at 72h re-checks the same 5 issues and finds `daysUnchanged`
(≈3) is still under 5, **and** `uday_notified_at` is already set from step
3, so `checkEscalation` returns `escalate: null` for all of them. **No new
message is sent** — the run summary just shows 0 escalations for these
issues.

```bash
npm run fleet-issues:run
```

The next real escalation for these issues fires once `daysUnchanged >= 5`
(day 5 / 120h), and it goes to the **senior** tier:

```
🚨 Issue Escalation

Issue 367 - Driver Complaints: Hand wash broken...
Vehicle: TG13T1986
Status: Open

This issue has remained unchanged for 5 days.

@Uday @Siva @Anil
```

**If you actually want a 3-day/72h senior escalation** (matching your test
plan), set `SENIOR_ESCALATION_DAYS=3` in `.env` before this step — then the
72-hour re-run above sends the 🚨 senior message instead of doing nothing.

Note: any status change on an issue between runs resets the timer —
`last_status_changed_at` is refreshed and both `uday_notified_at` /
`senior_escalation_notified_at` are cleared, so the 2-day/5-day clock
starts over for the new status.
