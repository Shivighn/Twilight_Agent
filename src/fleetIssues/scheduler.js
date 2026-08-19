const cron = require('node-cron');
const config = require('../config');
const logger = require('../utils/logger');
const { runOnce } = require('./index');

/** "10:00" -> "0 10 * * *" */
function cronExpressionFor(runTime) {
  const [hh, mm] = runTime.split(':').map((n) => parseInt(n, 10));
  return `${mm} ${hh} * * *`;
}

/**
 * Registers the daily fleet-issue run. Explicitly passes `timezone` to
 * node-cron (IANA name, e.g. "Asia/Kolkata") rather than relying on the
 * server's local time zone, per spec section 17.
 */
function startFleetIssueScheduler() {
  if (!config.fleetIssues.enabled) {
    logger.info('[FleetIssues] Agent disabled (set FLEET_ISSUE_AGENT_ENABLED=true to enable) — not scheduling');
    return;
  }
  if (!config.fleetIssues.whatsappGroupId) {
    logger.warn(
      '[FleetIssues] WHATSAPP_GROUP_ID not set — scheduler will still run daily, but every WhatsApp send will be skipped and logged until it is configured'
    );
  }

  const expr = cronExpressionFor(config.fleetIssues.runTime);
  logger.info(
    `[FleetIssues] Scheduling daily run at ${config.fleetIssues.runTime} (${config.fleetIssues.timezone}) — cron "${expr}"`
  );

  cron.schedule(
    expr,
    () => {
      runOnce().catch((err) => logger.error(`[FleetIssues] Unhandled run error: ${err.message}`, err));
    },
    { timezone: config.fleetIssues.timezone }
  );
}

module.exports = { startFleetIssueScheduler };
