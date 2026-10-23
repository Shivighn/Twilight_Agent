/**
 * Manual one-off trigger for the Ops Occupancy report (src/opsOccupancy/).
 * Needs a live WhatsApp connection to send for real (run inside
 * `npm run dev` / src/index.js) — same caveat as the other *:run scripts.
 *
 * Usage:
 *   npm run ops-occupancy:run
 */
const { runOnce } = require('../src/opsOccupancy');

(async () => {
  try {
    const result = await runOnce();
    console.log('\n[OpsOccupancy] Run result:', JSON.stringify(result, null, 2));
    process.exit(0);
  } catch (err) {
    console.error('\n[OpsOccupancy] Run FAILED:', err);
    process.exit(1);
  }
})();
