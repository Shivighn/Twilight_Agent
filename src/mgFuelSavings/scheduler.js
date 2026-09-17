const cron = require('node-cron');
const config = require('../config');
const logger = require('../utils/logger');
const { runOnce } = require('./index');

/** "11:00" -> "0 11 * * *" */
function cronExpressionFor(runTime) {
  const [hh, mm] = runTime.split(':').map((n) => parseInt(n, 10));
  return `${mm} ${hh} * * *`;
}

/**
 * Registers the daily MG Fuel Savings status post. Explicitly passes
 * `timezone` to node-cron (IANA name, "Asia/Kolkata") rather than relying
 * on the server's local time zone — same reasoning as
 * fleetIssues/scheduler.js and terminal44/scheduler.js.
 */
function startMgFuelSavingsScheduler() {
  if (!config.mgFuelSavings.enabled) {
    logger.info('[MgFuelSavings] Disabled (set MG_FUEL_SAVINGS_ENABLED=true to enable) — not scheduling');
    return;
  }
  if (!config.mgFuelSavings.whatsappGroupId) {
    logger.warn(
      '[MgFuelSavings] MG_FUEL_SAVINGS_WHATSAPP_GROUP_ID not set — scheduler will still run daily, but every WhatsApp send will be skipped and logged until it is configured'
    );
  }

  const expr = cronExpressionFor(config.mgFuelSavings.runTime);
  logger.info(
    `[MgFuelSavings] Scheduling daily run at ${config.mgFuelSavings.runTime} (${config.mgFuelSavings.timezone}) — cron "${expr}"`
  );

  cron.schedule(
    expr,
    () => {
      runOnce().catch((err) => logger.error(`[MgFuelSavings] Unhandled run error: ${err.message}`, err));
    },
    { timezone: config.mgFuelSavings.timezone }
  );
}

module.exports = { startMgFuelSavingsScheduler };
