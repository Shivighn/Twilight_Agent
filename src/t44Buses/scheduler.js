const cron = require('node-cron');
const config = require('../config');
const logger = require('../utils/logger');
const { runOnce } = require('./index');

/** "05:00" -> "0 5 * * *" */
function cronExpressionFor(runTime) {
  const [hh, mm] = runTime.split(':').map((n) => parseInt(n, 10));
  return `${mm} ${hh} * * *`;
}

function startT44BusesScheduler() {
  if (!config.t44Buses.enabled) {
    logger.info('[T44Buses] Disabled (set T44_BUSES_ENABLED=true to enable) — not scheduling');
    return;
  }

  const expr = cronExpressionFor(config.t44Buses.runTime);
  logger.info(
    `[T44Buses] Scheduling daily run at ${config.t44Buses.runTime} (${config.t44Buses.timezone}) — cron "${expr}"`
  );
  cron.schedule(
    expr,
    () => {
      runOnce().catch((err) => logger.error(`[T44Buses] Unhandled run error: ${err.message}`, err));
    },
    { timezone: config.t44Buses.timezone }
  );
}

module.exports = { startT44BusesScheduler };
