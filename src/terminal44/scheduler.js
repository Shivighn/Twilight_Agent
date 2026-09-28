const cron = require('node-cron');
const config = require('../config');
const logger = require('../utils/logger');
const { runOnce, runFlix } = require('./index');

/** "02:00" -> "0 2 * * *" */
function cronExpressionFor(runTime) {
  const [hh, mm] = runTime.split(':').map((n) => parseInt(n, 10));
  return `${mm} ${hh} * * *`;
}

/**
 * Registers one daily report. Explicitly passes `timezone` to node-cron
 * (IANA name, "Asia/Kolkata") rather than relying on the server's local
 * time zone — same reasoning as fleetIssues/scheduler.js. Each operator's
 * report is gated by its own enable flag, independently of the others.
 */
function scheduleReport({ label, enabled, enabledVar, runTime, groupId, groupVar, run }) {
  if (!enabled) {
    logger.info(`[Terminal44] ${label} report disabled (set ${enabledVar}=true to enable) — not scheduling`);
    return;
  }
  if (!groupId) {
    logger.warn(
      `[Terminal44] ${groupVar} not set — scheduler will still run daily, but every WhatsApp send will be skipped and logged until it is configured`
    );
  }

  const expr = cronExpressionFor(runTime);
  logger.info(
    `[Terminal44] Scheduling daily ${label} run at ${runTime} (${config.terminal44.timezone}) — cron "${expr}"`
  );

  cron.schedule(
    expr,
    () => {
      run().catch((err) => logger.error(`[Terminal44] Unhandled ${label} run error: ${err.message}`, err));
    },
    { timezone: config.terminal44.timezone }
  );
}

function startTerminal44Scheduler() {
  scheduleReport({
    label: 'IntrCity',
    enabled: config.terminal44.enabled,
    enabledVar: 'TERMINAL44_REPORT_ENABLED',
    runTime: config.terminal44.runTime,
    groupId: config.terminal44.whatsappGroupId,
    groupVar: 'TERMINAL44_WHATSAPP_GROUP_ID',
    run: () => runOnce(),
  });
  scheduleReport({
    label: 'Flix',
    enabled: config.terminal44.flix.enabled,
    enabledVar: 'TERMINAL44_FLIX_ENABLED',
    runTime: config.terminal44.flix.runTime,
    groupId: config.terminal44.flix.whatsappGroupId,
    groupVar: 'TERMINAL44_FLIX_WHATSAPP_GROUP_ID',
    run: () => runFlix(),
  });
}

module.exports = { startTerminal44Scheduler };
