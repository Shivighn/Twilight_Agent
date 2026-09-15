const cron = require('node-cron');
const config = require('../config');
const logger = require('../utils/logger');
const { runOnce } = require('./index');

/** "02:00" -> "0 2 * * *" */
function cronExpressionFor(runTime) {
  const [hh, mm] = runTime.split(':').map((n) => parseInt(n, 10));
  return `${mm} ${hh} * * *`;
}

/**
 * Registers the daily Terminal 44 history report. Explicitly passes
 * `timezone` to node-cron (IANA name, "Asia/Kolkata") rather than relying
 * on the server's local time zone — same reasoning as fleetIssues/scheduler.js.
 */
function startTerminal44Scheduler() {
  if (!config.terminal44.enabled) {
    logger.info('[Terminal44] Report disabled (set TERMINAL44_REPORT_ENABLED=true to enable) — not scheduling');
    return;
  }
  if (!config.terminal44.whatsappGroupId) {
    logger.warn(
      '[Terminal44] TERMINAL44_WHATSAPP_GROUP_ID not set — scheduler will still run daily, but every WhatsApp send will be skipped and logged until it is configured'
    );
  }

  const expr = cronExpressionFor(config.terminal44.runTime);
  logger.info(
    `[Terminal44] Scheduling daily run at ${config.terminal44.runTime} (${config.terminal44.timezone}) — cron "${expr}"`
  );

  cron.schedule(
    expr,
    () => {
      runOnce().catch((err) => logger.error(`[Terminal44] Unhandled run error: ${err.message}`, err));
    },
    { timezone: config.terminal44.timezone }
  );
}

module.exports = { startTerminal44Scheduler };
