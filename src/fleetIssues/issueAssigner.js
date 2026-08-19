const db = require('./db');
const { resolveFleetManager } = require('./fmResolver');
const { upsertTracking } = require('./notificationTracker');
const logger = require('../utils/logger');

/**
 * Process a single issue with no tracking row yet: resolve its FM, assign
 * it, and record the tracking row. The FM's WhatsApp message itself is sent
 * later by the orchestrator (after grouping every newly-assigned issue by
 * FM) — this function only decides assignment and persists state.
 *
 * Ordering matters for crash safety (spec section 19): `issues.assignee_id`
 * is updated FIRST, the tracking row SECOND. If the process dies in
 * between, the next run sees assignee_id already set (so it won't be
 * overwritten again) but still has no tracking row, so it safely retries
 * just the tracking-row half — no double assignment, no lost issue.
 */
async function assignNewIssue(issue) {
  const resolution = await resolveFleetManager(issue.vehicle_number);
  const now = new Date().toISOString();

  if (!resolution.fleetManagerId) {
    logger.info(`[FleetIssues] Issue ${issue.issue_number}: unmapped — ${resolution.unmappedReason}`);
    await upsertTracking({
      issue_id: issue.id,
      issue_number: issue.issue_number,
      vehicle_number: issue.vehicle_number,
      fleet_manager_id: null,
      assignment_status: 'unmapped',
      unmapped_reason: resolution.unmappedReason,
      first_detected_at: now,
      last_status: issue.status,
      last_status_changed_at: now,
      notification_state: 'sent', // nothing to notify for an unmapped issue
    });
    return { assigned: false, unmappedReason: resolution.unmappedReason };
  }

  if (!issue.assignee_id) {
    await db.update('issues', { id: `eq.${issue.id}` }, { assignee_id: resolution.fleetManagerId });
  } else {
    logger.info(
      `[FleetIssues] Issue ${issue.issue_number} already has assignee_id="${issue.assignee_id}" — leaving it, tracking only.`
    );
  }

  await upsertTracking({
    issue_id: issue.id,
    issue_number: issue.issue_number,
    vehicle_number: issue.vehicle_number,
    fleet_manager_id: resolution.fleetManagerId,
    assignment_status: 'assigned',
    unmapped_reason: null,
    first_detected_at: now,
    last_status: issue.status,
    last_status_changed_at: now,
    notification_state: 'pending', // FM message sent (and this flipped to 'sent') by the orchestrator
  });

  return { assigned: true, fleetManagerId: resolution.fleetManagerId };
}

module.exports = { assignNewIssue };
