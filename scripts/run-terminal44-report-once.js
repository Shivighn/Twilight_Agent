/**
 * Manual one-off trigger for the Terminal 44 daily history report
 * (src/terminal44/). Runs the exact same runOnce() the cron job
 * (src/terminal44/scheduler.js) calls — lets you fire it on demand to
 * check the fetch/CSV/send pipeline without waiting for 2:00 AM IST.
 *
 * Ignores TERMINAL44_REPORT_ENABLED (that flag only gates the cron
 * registration, not runOnce() itself). TERMINAL44_WHATSAPP_GROUP_ID must
 * still be set for the send to actually happen, and this needs to run in
 * a process that already holds a live WhatsApp connection (e.g. via
 * src/index.js) to send anything for real — same caveat as
 * fleet-issues:run.
 *
 * Usage:
 *   npm run terminal44:run
 *   node scripts/run-terminal44-report-once.js
 */
const { runOnce } = require('../src/terminal44');

(async () => {
  try {
    const result = await runOnce();
    console.log('\n[Terminal44] Run result:');
    console.log(JSON.stringify(result, null, 2));
    process.exit(0);
  } catch (err) {
    console.error('\n[Terminal44] Run FAILED:');
    console.error(err);
    process.exit(1);
  }
})();
