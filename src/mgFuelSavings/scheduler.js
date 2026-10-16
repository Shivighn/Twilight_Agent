const cron = require('node-cron');
const config = require('../config');
const logger = require('../utils/logger');
const { runMorning } = require('./index');

/** "10:00" -> "0 10 * * *" */
function cronExpressionFor(runTime) {
  const [hh, mm] = runTime.split(':').map((n) => parseInt(n, 10));
  return `${mm} ${hh} * * *`;
}

/**
 * Registers ONE daily MG Fuel Savings run, at 4 PM. Explicitly passes
 * `timezone` to node-cron (IANA name, "Asia/Kolkata") rather than relying
 * on the server's local time zone — same reasoning as
 * fleetIssues/scheduler.js and terminal44/scheduler.js.
 *
 * The 10 AM run is paused — not scheduled at all, so it cannot fire under
 * any circumstance. It calls runMorning() (the unconditional fetch+send,
 * same function the old 10 AM slot used), NOT runAfternoon() — that one
 * only sends if a 10 AM run already persisted an anomaly count today (see
 * morningResultStore.js), which would never exist now that 10 AM doesn't
 * run, so it would silently skip forever. runMorning/runAfternoon's own
 * code is untouched; only which one gets scheduled, and when, changed.
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

  const afternoonExpr = cronExpressionFor(config.mgFuelSavings.afternoonRunTime);
  logger.info(
    `[MgFuelSavings] Scheduling daily run at ${config.mgFuelSavings.afternoonRunTime} (${config.mgFuelSavings.timezone}) — cron "${afternoonExpr}" (10 AM run is paused)`
  );
  cron.schedule(
    afternoonExpr,
    () => {
      runMorning().catch((err) => logger.error(`[MgFuelSavings] Unhandled run error: ${err.message}`, err));
    },
    { timezone: config.mgFuelSavings.timezone }
  );
}

module.exports = { startMgFuelSavingsScheduler };
