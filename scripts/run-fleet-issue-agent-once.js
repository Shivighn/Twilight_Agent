/**
 * Manual one-off trigger for the Fleet Issue Auto-Assignment + Escalation
 * agent (src/fleetIssues/). Runs the exact same runOnce() the daily cron
 * job (src/fleetIssues/scheduler.js) calls — this just lets you fire it
 * on demand instead of waiting for AGENT_RUN_TIME, so you can check
 * assignment + WhatsApp sending without deploying/waiting.
 *
 * Ignores FLEET_ISSUE_AGENT_ENABLED (that flag only gates the cron
 * registration, not runOnce() itself) — so this works even while the
 * scheduler is off. WHATSAPP_GROUP_ID must still be set for messages to
 * actually send; if it isn't, sends are skipped and logged as such.
 *
 * Usage:
 *   npm run fleet-issues:run
 *   node scripts/run-fleet-issue-agent-once.js
 */
const { runOnce } = require('../src/fleetIssues');

(async () => {
  const stats = await runOnce();
  console.log('\n[FleetIssues] Run summary:');
  console.log(JSON.stringify(stats, null, 2));
  process.exit(stats.errorMessage ? 1 : 0);
})();
