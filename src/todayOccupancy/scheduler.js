const cron = require('node-cron');
const config = require('../config');
const logger = require('../utils/logger');
const { runOnce } = require('./index');

/** "18:00" -> "0 18 * * *" */
function cronExpressionFor(runTime) {
  const [hh, mm] = runTime.split(':').map((n) => parseInt(n, 10));
  return `${mm} ${hh} * * *`;
}

function startTodayOccupancyScheduler() {
  if (!config.todayOccupancy.enabled) {
    logger.info('[TodayOccupancy] Disabled (set TODAY_OCCUPANCY_ENABLED=true to enable) — not scheduling');
    return;
  }

  const expr = cronExpressionFor(config.todayOccupancy.runTime);
  logger.info(
    `[TodayOccupancy] Scheduling daily run at ${config.todayOccupancy.runTime} (${config.todayOccupancy.timezone}) — cron "${expr}"`
  );
  cron.schedule(
    expr,
    () => {
      runOnce().catch((err) => logger.error(`[TodayOccupancy] Unhandled run error: ${err.message}`, err));
    },
    { timezone: config.todayOccupancy.timezone }
  );
}

module.exports = { startTodayOccupancyScheduler };
