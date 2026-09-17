/**
 * Manual one-off trigger for the MG Fuel Savings daily status post
 * (src/mgFuelSavings/). Runs the exact same runOnce() the cron job
 * (src/mgFuelSavings/scheduler.js) calls — lets you fire it on demand to
 * check the login/fetch/decide/send pipeline without waiting for 11:00 AM IST.
 *
 * Ignores MG_FUEL_SAVINGS_ENABLED (that flag only gates the cron
 * registration, not runOnce() itself). MG_FUEL_SAVINGS_WHATSAPP_GROUP_ID
 * must still be set for the send to actually happen, and this needs to run
 * in a process that already holds a live WhatsApp connection (e.g. via
 * src/index.js) to send anything for real — same caveat as
 * fleet-issues:run / terminal44:run.
 *
 * Usage:
 *   npm run mg-fuel-savings:run
 *   node scripts/run-mg-fuel-savings-once.js
 */
const { runOnce } = require('../src/mgFuelSavings');

(async () => {
  try {
    const result = await runOnce();
    console.log('\n[MgFuelSavings] Run result:');
    console.log(JSON.stringify(result, null, 2));
    process.exit(0);
  } catch (err) {
    console.error('\n[MgFuelSavings] Run FAILED:');
    console.error(err);
    process.exit(1);
  }
})();
