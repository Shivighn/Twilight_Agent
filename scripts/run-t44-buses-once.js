/**
 * Manual one-off trigger for the T44 bus-bay report (src/t44Buses/).
 * Needs a live WhatsApp connection to send for real (run inside `npm run
 * dev` / src/index.js) — same caveat as the other *:run scripts.
 *
 * Usage:
 *   npm run t44-buses:run                          (uses yesterday's window, same as the real cron)
 *   node scripts/run-t44-buses-once.js 2026-09-25   (ad-hoc: test a specific reported day)
 */
const { runOnce, windowForDate } = require('../src/t44Buses');

const dateArg = process.argv[2];
const windowOverride = dateArg ? windowForDate(dateArg) : undefined;

(async () => {
  try {
    const result = await runOnce(windowOverride);
    console.log('\n[T44Buses] Run result:', JSON.stringify(result, null, 2));
    process.exit(0);
  } catch (err) {
    console.error('\n[T44Buses] Run FAILED:', err);
    process.exit(1);
  }
})();
