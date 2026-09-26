/**
 * Manual one-off trigger for the T44 daily sales post (src/t44Sales/).
 * Needs a live WhatsApp connection to send for real (run inside `npm run
 * dev` / src/index.js) — same caveat as the other *:run scripts.
 *
 * Usage:
 *   npm run t44-sales:run                  (uses yesterday, same as the real cron)
 *   node scripts/run-t44-sales-once.js 2026-09-24   (ad-hoc: test a specific date)
 */
const { runOnce } = require('../src/t44Sales');

(async () => {
  try {
    const result = await runOnce(process.argv[2]);
    console.log('\n[T44Sales] Run result:', JSON.stringify(result, null, 2));
    process.exit(0);
  } catch (err) {
    console.error('\n[T44Sales] Run FAILED:', err);
    process.exit(1);
  }
})();
