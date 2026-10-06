/**
 * Manual one-off trigger for the Today's Occupancy/ASP report
 * (src/todayOccupancy/). Needs a live WhatsApp connection to send for
 * real (run inside `npm run dev` / src/index.js) — same caveat as the
 * other *:run scripts. Also needs scripts/"todaysbuses expectancy.txt"
 * to already exist and be modified TODAY (IST) — see
 * src/todayOccupancy/index.js and scripts/todayOccupancy.py's docstring.
 *
 * Usage:
 *   npm run today-occupancy:run
 */
const { runOnce } = require('../src/todayOccupancy');

(async () => {
  try {
    const result = await runOnce();
    console.log('\n[TodayOccupancy] Run result:', JSON.stringify(result, null, 2));
    process.exit(0);
  } catch (err) {
    console.error('\n[TodayOccupancy] Run FAILED:', err);
    process.exit(1);
  }
})();
