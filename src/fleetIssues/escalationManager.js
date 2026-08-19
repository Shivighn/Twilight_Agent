const config = require('../config');
const { updateTracking } = require('./notificationTracker');
const logger = require('../utils/logger');

const MS_PER_DAY = 24 * 60 * 60 * 1000;

/**
 * Process an issue that already has a tracking row and has already received
 * its first FM notification: detect a status change (which resets the
 * escalation timer, spec section 6) and decide whether an escalation is due.
 *
 * Returns { escalate: 'uday' | 'senior' | null, daysUnchanged }.
 */
async function checkEscalation(issue, tracking) {
  const now = new Date();

  if (issue.status !== tracking.last_status) {
    logger.info(
      `[FleetIssues] Issue ${issue.issue_number}: status changed "${tracking.last_status}" -> "${issue.status}" — resetting escalation timer`
    );
    await updateTracking(issue.id, {
      last_status: issue.status,
      last_status_changed_at: now.toISOString(),
      uday_notified_at: null,
      senior_escalation_notified_at: null,
    });
    return { escalate: null, daysUnchanged: 0 };
  }

  const daysUnchanged = Math.floor((now - new Date(tracking.last_status_changed_at)) / MS_PER_DAY);

  if (daysUnchanged >= config.fleetIssues.seniorEscalationDays && !tracking.senior_escalation_notified_at) {
    return { escalate: 'senior', daysUnchanged };
  }
  if (daysUnchanged >= config.fleetIssues.fmEscalationDays && !tracking.uday_notified_at) {
    return { escalate: 'uday', daysUnchanged };
  }
  return { escalate: null, daysUnchanged };
}

module.exports = { checkEscalation };
