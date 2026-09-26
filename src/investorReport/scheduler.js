const cron = require('node-cron');
const config = require('../config');
const logger = require('../utils/logger');
const { runOnce } = require('./index');

/** "09:00" -> "0 9 * * 1" (every Monday). */
function cronExpressionFor(runTime) {
  const [hh, mm] = runTime.split(':').map((n) => parseInt(n, 10));
  return `${mm} ${hh} * * 1`;
}

function startInvestorReportScheduler() {
  if (!config.investorReport.enabled) {
    logger.info('[InvestorReport] Disabled (set INVESTOR_REPORT_ENABLED=true to enable) — not scheduling');
    return;
  }

  const expr = cronExpressionFor(config.investorReport.runTime);
  logger.info(
    `[InvestorReport] Scheduling weekly (Monday) run at ${config.investorReport.runTime} (${config.investorReport.timezone}) — cron "${expr}"`
  );
  cron.schedule(
    expr,
    () => {
      runOnce().catch((err) => logger.error(`[InvestorReport] Unhandled run error: ${err.message}`, err));
    },
    { timezone: config.investorReport.timezone }
  );
}

module.exports = { startInvestorReportScheduler };
