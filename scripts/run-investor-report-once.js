/**
 * Manual one-off trigger for the weekly investor report
 * (src/investorReport/). Runs the exact same runOnce() the cron job
 * (src/investorReport/scheduler.js) calls — fires it on demand any day,
 * without touching the Monday cron schedule.
 *
 * Needs a live WhatsApp connection to send for real (run inside
 * `npm run dev` / src/index.js) — same caveat as the other *:run scripts.
 *
 * Usage: npm run investor-report:run
 */
const { runOnce } = require('../src/investorReport');

(async () => {
  try {
    const result = await runOnce();
    console.log('\n[InvestorReport] Run result:', JSON.stringify(result, null, 2));
    process.exit(0);
  } catch (err) {
    console.error('\n[InvestorReport] Run FAILED:', err);
    process.exit(1);
  }
})();
