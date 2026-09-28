/**
 * Manual one-off trigger for the Terminal 44 daily history reports
 * (src/terminal44/). Runs the exact same runOnce()/runFlix() the cron jobs
 * (src/terminal44/scheduler.js) call — lets you fire them on demand to
 * check the fetch/CSV/send pipeline without waiting for 2:30 AM IST.
 *
 * Ignores the *_ENABLED flags (those only gate the cron registration, not
 * the run functions themselves). The target WhatsApp group must still be
 * set for the send to actually happen, and this needs to run in a process
 * that already holds a live WhatsApp connection (e.g. via src/index.js) to
 * send anything for real — same caveat as fleet-issues:run.
 *
 * Usage:
 *   npm run terminal44:run                       (IntrCity, yesterday)
 *   npm run terminal44-flix:run                  (Flix, yesterday)
 *   node scripts/run-terminal44-report-once.js [flix] [YYYY-MM-DD]
 *
 * Note each operator's done-marker blocks a second send for the same date —
 * test another date, or delete storage/terminal44/last_sent[_flix].json.
 */
const { runOnce, runFlix } = require('../src/terminal44');

const args = process.argv.slice(2);
const isFlix = args.includes('flix');
const dateOverride = args.find((a) => /^\d{4}-\d{2}-\d{2}$/.test(a));
const run = isFlix ? runFlix : runOnce;

(async () => {
  try {
    const result = await run(dateOverride);
    console.log(`\n[Terminal44] ${isFlix ? 'Flix' : 'IntrCity'} run result:`);
    console.log(JSON.stringify(result, null, 2));
    process.exit(0);
  } catch (err) {
    console.error(`\n[Terminal44] ${isFlix ? 'Flix' : 'IntrCity'} run FAILED:`);
    console.error(err);
    process.exit(1);
  }
})();
