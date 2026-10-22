/**
 * Manual one-off trigger for the weekly Trugo bus arrival report
 * (src/trugoReport/). Needs a live WhatsApp connection to send for real
 * (run inside `npm run dev` / src/index.js) — same caveat as the other
 * *:run scripts.
 *
 * Usage:
 *   npm run trugo-report:run                         (uses the last Mon-Sun, same as the real cron)
 *   node scripts/run-trugo-report-once.js 2026-10-19  (ad-hoc: test a specific reported week, given its END date)
 */
const { runOnce, windowForWeekEnding } = require('../src/trugoReport');

const dateArg = process.argv[2];
const windowOverride = dateArg ? windowForWeekEnding(dateArg) : undefined;

(async () => {
  try {
    const result = await runOnce(windowOverride);
    console.log('\n[TrugoReport] Run result:', JSON.stringify(result, null, 2));
    process.exit(0);
  } catch (err) {
    console.error('\n[TrugoReport] Run FAILED:', err);
    process.exit(1);
  }
})();
