/**
 * Manual one-off trigger for the MG Fuel Savings status posts
 * (src/mgFuelSavings/). Runs the exact same runMorning()/runAfternoon()
 * the cron jobs (src/mgFuelSavings/scheduler.js) call — lets you fire
 * either on demand without waiting for 10:00 AM / 4:00 PM IST.
 *
 * Ignores MG_FUEL_SAVINGS_ENABLED (that flag only gates the cron
 * registration, not these functions directly). MG_FUEL_SAVINGS_WHATSAPP_GROUP_ID
 * must still be set for the send to actually happen, and this needs to run
 * in a process that already holds a live WhatsApp connection (e.g. via
 * src/index.js) to send anything for real — same caveat as
 * fleet-issues:run / terminal44:run.
 *
 * Usage:
 *   npm run mg-fuel-savings:run              (10 AM run)
 *   npm run mg-fuel-savings:run:afternoon    (4 PM run — only sends if
 *                                              today's 10 AM run found
 *                                              anomalies)
 *   node scripts/run-mg-fuel-savings-once.js [morning|afternoon]
 */
const { runMorning, runAfternoon } = require('../src/mgFuelSavings');

const period = process.argv[2] === 'afternoon' ? 'afternoon' : 'morning';
const run = period === 'afternoon' ? runAfternoon : runMorning;

(async () => {
  try {
    const result = await run();
    console.log(`\n[MgFuelSavings] ${period} run result:`);
    console.log(JSON.stringify(result, null, 2));
    process.exit(0);
  } catch (err) {
    console.error(`\n[MgFuelSavings] ${period} run FAILED:`);
    console.error(err);
    process.exit(1);
  }
})();
