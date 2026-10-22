const cron = require('node-cron');
const config = require('../config');
const logger = require('../utils/logger');
const { runOnce } = require('./index');

/** "05:30", "1" -> "30 5 * * 1" (every Monday by default; dayOfWeek is configurable so testing on another day doesn't need a code edit — see TRUGO_REPORT_DAY_OF_WEEK). */
function cronExpressionFor(runTime, dayOfWeek) {
  const [hh, mm] = runTime.split(':').map((n) => parseInt(n, 10));
  return `${mm} ${hh} * * ${dayOfWeek}`;
}

function startTrugoReportScheduler() {
  if (!config.trugoReport.enabled) {
    logger.info('[TrugoReport] Disabled (set TRUGO_REPORT_ENABLED=true to enable) — not scheduling');
    return;
  }

  const expr = cronExpressionFor(config.trugoReport.runTime, config.trugoReport.dayOfWeek);
  logger.info(
    `[TrugoReport] Scheduling weekly run at ${config.trugoReport.runTime} (${config.trugoReport.timezone}) — cron "${expr}"`
  );
  cron.schedule(
    expr,
    () => {
      runOnce().catch((err) => logger.error(`[TrugoReport] Unhandled run error: ${err.message}`, err));
    },
    { timezone: config.trugoReport.timezone }
  );
}

module.exports = { startTrugoReportScheduler };
