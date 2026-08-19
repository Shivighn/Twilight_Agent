const db = require('./db');
const logger = require('../utils/logger');

function newRunStats(runId) {
  return {
    runId,
    startedAt: new Date().toISOString(),
    issuesScanned: 0,
    newIssues: 0,
    issuesAssigned: 0,
    unmappedIssues: 0,
    fmNotificationsSent: 0,
    udayEscalationsSent: 0,
    seniorEscalationsSent: 0,
    whatsappFailures: 0,
    errorMessage: null,
  };
}

/** Logs the spec's section-18 summary line and persists a run-log row. */
async function finish(stats) {
  const completedAt = new Date().toISOString();
  logger.info(
    `[FleetIssues] Run ${stats.runId} complete — scanned=${stats.issuesScanned} new=${stats.newIssues} ` +
      `assigned=${stats.issuesAssigned} unmapped=${stats.unmappedIssues} ` +
      `fm_sent=${stats.fmNotificationsSent} uday=${stats.udayEscalationsSent} senior=${stats.seniorEscalationsSent} ` +
      `wa_failures=${stats.whatsappFailures}` +
      (stats.errorMessage ? ` error="${stats.errorMessage}"` : '')
  );

  try {
    await db.insert('fleet_issue_agent_runs', {
      run_id: stats.runId,
      started_at: stats.startedAt,
      completed_at: completedAt,
      issues_scanned: stats.issuesScanned,
      new_issues: stats.newIssues,
      issues_assigned: stats.issuesAssigned,
      unmapped_issues: stats.unmappedIssues,
      fm_notifications_sent: stats.fmNotificationsSent,
      uday_escalations_sent: stats.udayEscalationsSent,
      senior_escalations_sent: stats.seniorEscalationsSent,
      whatsapp_failures: stats.whatsappFailures,
      error_message: stats.errorMessage,
    });
  } catch (err) {
    // Never let a logging failure look like a run failure — the run itself
    // already completed by the time we're writing this row.
    logger.error(`[FleetIssues] Failed to write run log row: ${err.message}`);
  }
}

module.exports = { newRunStats, finish };
