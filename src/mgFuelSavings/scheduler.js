const cron = require('node-cron');
const config = require('../config');
const logger = require('../utils/logger');
const { runMorning, runAfternoon } = require('./index');

/** "10:00" -> "0 10 * * *" */
function cronExpressionFor(runTime) {
  const [hh, mm] = runTime.split(':').map((n) => parseInt(n, 10));
  return `${mm} ${hh} * * *`;
}

/**
 * Registers TWO daily MG Fuel Savings runs. Explicitly passes `timezone`
 * to node-cron (IANA name, "Asia/Kolkata") rather than relying on the
 * server's local time zone — same reasoning as fleetIssues/scheduler.js
 * and terminal44/scheduler.js.
 *   - 10 AM: always runs.
 *   - 4 PM: always FIRES, but runAfternoon() itself decides whether to
 *     actually fetch/send, based on whether the 10 AM run (persisted to
 *     disk — see morningResultStore.js) found any anomalies.
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

  const morningExpr = cronExpressionFor(config.mgFuelSavings.runTime);
  logger.info(
    `[MgFuelSavings] Scheduling 10 AM run at ${config.mgFuelSavings.runTime} (${config.mgFuelSavings.timezone}) — cron "${morningExpr}"`
  );
  cron.schedule(
    morningExpr,
    () => {
      runMorning().catch((err) => logger.error(`[MgFuelSavings] Unhandled 10 AM run error: ${err.message}`, err));
    },
    { timezone: config.mgFuelSavings.timezone }
  );

  const afternoonExpr = cronExpressionFor(config.mgFuelSavings.afternoonRunTime);
  logger.info(
    `[MgFuelSavings] Scheduling 4 PM run at ${config.mgFuelSavings.afternoonRunTime} (${config.mgFuelSavings.timezone}) — cron "${afternoonExpr}" (only sends if the 10 AM run found anomalies)`
  );
  cron.schedule(
    afternoonExpr,
    () => {
      runAfternoon().catch((err) => logger.error(`[MgFuelSavings] Unhandled 4 PM run error: ${err.message}`, err));
    },
    { timezone: config.mgFuelSavings.timezone }
  );
}

module.exports = { startMgFuelSavingsScheduler };
