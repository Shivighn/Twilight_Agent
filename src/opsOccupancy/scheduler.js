const cron = require('node-cron');
const config = require('../config');
const logger = require('../utils/logger');
const { runOnce } = require('./index');

/** "12:40" -> "40 12 * * *" */
function cronExpressionFor(runTime) {
  const [hh, mm] = runTime.split(':').map((n) => parseInt(n, 10));
  return `${mm} ${hh} * * *`;
}

function startOpsOccupancyScheduler() {
  if (!config.opsOccupancy.enabled) {
    logger.info('[OpsOccupancy] Disabled (set OPS_OCCUPANCY_ENABLED=true to enable) — not scheduling');
    return;
  }

  const expr = cronExpressionFor(config.opsOccupancy.runTime);
  logger.info(
    `[OpsOccupancy] Scheduling daily run at ${config.opsOccupancy.runTime} (${config.opsOccupancy.timezone}) — cron "${expr}"`
  );
  cron.schedule(
    expr,
    () => {
      runOnce().catch((err) => logger.error(`[OpsOccupancy] Unhandled run error: ${err.message}`, err));
    },
    { timezone: config.opsOccupancy.timezone }
  );
}

module.exports = { startOpsOccupancyScheduler };
