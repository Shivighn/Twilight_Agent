const cron = require('node-cron');
const config = require('../config');
const logger = require('../utils/logger');
const { runOnce } = require('./index');

/** "09:00" -> "0 9 * * *" */
function cronExpressionFor(runTime) {
  const [hh, mm] = runTime.split(':').map((n) => parseInt(n, 10));
  return `${mm} ${hh} * * *`;
}

function startT44SalesScheduler() {
  if (!config.t44Sales.enabled) {
    logger.info('[T44Sales] Disabled (set T44_SALES_ENABLED=true to enable) — not scheduling');
    return;
  }

  const expr = cronExpressionFor(config.t44Sales.runTime);
  logger.info(
    `[T44Sales] Scheduling daily run at ${config.t44Sales.runTime} (${config.t44Sales.timezone}) — cron "${expr}"`
  );
  cron.schedule(
    expr,
    () => {
      runOnce().catch((err) => logger.error(`[T44Sales] Unhandled run error: ${err.message}`, err));
    },
    { timezone: config.t44Sales.timezone }
  );
}

module.exports = { startT44SalesScheduler };
