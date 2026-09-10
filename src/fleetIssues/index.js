const logger = require('../utils/logger');
const { fetchEligibleIssues } = require('./issueFetcher');
const { assignNewIssue } = require('./issueAssigner');
const { checkEscalation } = require('./escalationManager');
const { getByIssueId, updateTracking } = require('./notificationTracker');
const { fmDisplayName, buildFmAssignmentMessage, buildEscalationMessage } = require('./messageBuilder');
const { sendFleetIssueMessage } = require('./whatsappSender');
const runLogger = require('./runLogger');

/**
 * One full daily run (spec section 11's algorithm). Safe to call more than
 * once for the same day/issue set — see notificationTracker.js and the
 * ordering notes in issueAssigner.js for why.
 */
async function runOnce() {
  const runId = `run_${Date.now()}`;
  const stats = runLogger.newRunStats(runId);
  logger.info(`[FleetIssues] Starting run ${runId}`);

  try {
    const issues = await fetchEligibleIssues();
    stats.issuesScanned = issues.length;

    // fleetManagerId -> [{ issue, priorCount }] — one grouped WhatsApp
    // message per FM, covering both brand-new assignments and any earlier
    // assignment whose FM message never actually got sent (retry).
    const toNotifyByFm = new Map();
    const queueForFm = (fleetManagerId, issue, priorCount) => {
      if (!toNotifyByFm.has(fleetManagerId)) toNotifyByFm.set(fleetManagerId, []);
      toNotifyByFm.get(fleetManagerId).push({ issue, priorCount });
    };

    // 'uday' | 'senior' -> [{ issue, daysUnchanged, priorCount }] — one
    // grouped WhatsApp message per escalation level per run (not one per
    // issue), covering every issue/vehicle that hit that level this run.
    const toEscalateByLevel = new Map();
    const queueEscalation = (level, issue, daysUnchanged, priorCount) => {
      if (!toEscalateByLevel.has(level)) toEscalateByLevel.set(level, []);
      toEscalateByLevel.get(level).push({ issue, daysUnchanged, priorCount });
    };

    for (const issue of issues) {
      const tracking = await getByIssueId(issue.id);

      if (!tracking) {
        stats.newIssues += 1;
        const result = await assignNewIssue(issue);
        if (result.assigned) {
          stats.issuesAssigned += 1;
          queueForFm(result.fleetManagerId, issue, 0);
        } else {
          stats.unmappedIssues += 1;
        }
        continue;
      }

      // Retry an FM notification that was never confirmed sent (previous
      // run crashed, or WhatsApp failed) before considering escalation.
      if (tracking.assignment_status === 'assigned' && !tracking.fm_notified_at) {
        queueForFm(tracking.fleet_manager_id, issue, tracking.notification_count || 0);
        continue;
      }

      if (tracking.assignment_status !== 'assigned') continue; // unmapped — nothing more to do here

      const { escalate, daysUnchanged } = await checkEscalation(issue, tracking);
      if (!escalate) continue;

      queueEscalation(escalate, issue, daysUnchanged, tracking.notification_count || 0);
    }

    for (const [fleetManagerId, items] of toNotifyByFm) {
      const { text, mentions } = buildFmAssignmentMessage(
        fmDisplayName(fleetManagerId),
        items.map((i) => i.issue)
      );
      const result = await sendFleetIssueMessage({ text, mentions });
      const now = new Date().toISOString();

      for (const { issue, priorCount } of items) {
        if (result.success) {
          await updateTracking(issue.id, {
            fm_notified_at: now,
            last_notification_type: 'fm',
            last_notification_at: now,
            notification_state: 'sent',
            last_attempt_at: now,
            error_message: null,
            notification_count: priorCount + 1,
          });
          stats.fmNotificationsSent += 1;
        } else {
          await updateTracking(issue.id, {
            notification_state: 'failed',
            last_attempt_at: now,
            error_message: result.error || 'unknown error',
          });
          stats.whatsappFailures += 1;
        }
      }
    }

    for (const [level, escItems] of toEscalateByLevel) {
      const { text, mentions } = buildEscalationMessage(level, escItems);
      const result = await sendFleetIssueMessage({ text, mentions });
      const now = new Date().toISOString();

      for (const { issue, priorCount } of escItems) {
        if (result.success) {
          const patch = {
            last_notification_type: `${level}_escalation`,
            last_notification_at: now,
            notification_state: 'sent',
            last_attempt_at: now,
            error_message: null,
            notification_count: priorCount + 1,
          };
          patch[level === 'senior' ? 'senior_escalation_notified_at' : 'uday_notified_at'] = now;
          await updateTracking(issue.id, patch);
          if (level === 'senior') stats.seniorEscalationsSent += 1;
          else stats.udayEscalationsSent += 1;
        } else {
          await updateTracking(issue.id, {
            notification_state: 'failed',
            last_attempt_at: now,
            error_message: result.error || 'unknown error',
          });
          stats.whatsappFailures += 1;
        }
      }
    }
  } catch (err) {
    stats.errorMessage = err.message;
    logger.error(`[FleetIssues] Run ${runId} crashed: ${err.message}`, err);
  }

  await runLogger.finish(stats);
  return stats;
}

module.exports = { runOnce };
