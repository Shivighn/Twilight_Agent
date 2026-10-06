// Builds scripts/"todaysbuses expectancy.txt" automatically, replacing the
// manual FleetZen/admin + terminal_bus_bay_display lookup the user used to
// do by hand every day. Two steps:
//   1. GET the admin app's missed-buses endpoint for the bus numbers to
//      look up — every bus_number in its `rows`, arrived or missed alike
//      (that endpoint tracks recent arrival history generally, not just
//      misses, despite the URL's name).
//   2. RPC a Supabase SQL function (today_expectancy_lookup — same
//      FleetZen project as t44_bus_bay_report, see the SQL this repo's
//      README/setup notes give to create it) with those bus numbers,
//      running the exact join query the user gave, to get each bus's
//      Operator/Service Number/Route/Last Check In.
// Does NOT touch scripts/todayOccupancy.py — this only produces the input
// file it already expects, in the exact shape it already parses.

const axios = require('axios');
const config = require('../config');
const logger = require('../utils/logger');

/** ISO timestamp -> "01 Oct 2026, 08:15 PM" (IST) — the exact format scripts/todayOccupancy.py's tonight() parses via strptime("%d %b %Y, %I:%M %p"). */
function formatLastCheckIn(iso) {
  if (!iso) return '';
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  }).formatToParts(new Date(iso));
  const map = {};
  for (const p of parts) map[p.type] = p.value;
  return `${map.day} ${map.month} ${map.year}, ${map.hour.padStart(2, '0')}:${map.minute} ${map.dayPeriod}`;
}

async function fetchMissedBusNumbers() {
  const { data } = await axios.get(config.todayOccupancy.missedBusesUrl, { timeout: 30000 });
  const rows = data.rows || [];
  const numbers = [...new Set(rows.map((r) => r.bus_number).filter(Boolean))];
  logger.info(`[TodayOccupancy] missed-buses: ${rows.length} row(s), ${numbers.length} distinct bus number(s)`);
  return numbers;
}

async function lookupExpectancy(busNumbers) {
  const { url: supabaseUrl, serviceRoleKey } = config.supabase;
  if (!supabaseUrl || !serviceRoleKey) {
    throw new Error('[TodayOccupancy] SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set');
  }
  const res = await axios.post(
    `${supabaseUrl}/rest/v1/rpc/today_expectancy_lookup`,
    { p_bus_numbers: busNumbers },
    { headers: { apikey: serviceRoleKey, Authorization: `Bearer ${serviceRoleKey}` }, validateStatus: () => true }
  );
  if (res.status !== 200) {
    throw new Error(`[TodayOccupancy] today_expectancy_lookup RPC failed — HTTP ${res.status} ${JSON.stringify(res.data)}`);
  }
  return res.data; // already ORDER BY scheduled_arrival, inside the SQL function itself
}

/** Builds the list in the exact shape scripts/todayOccupancy.py's load_list() reads. */
async function buildExpectancyList() {
  const busNumbers = await fetchMissedBusNumbers();
  if (busNumbers.length === 0) {
    throw new Error('[TodayOccupancy] missed-buses returned 0 bus numbers — nothing to look up');
  }

  const rows = await lookupExpectancy(busNumbers);
  const list = rows
    .filter((r) => r.bus_number) // a bus number with no matching bay-display row at all just won't come back from the LEFT JOINs — this guards the odd null case anyway
    .map((r) => ({
      'Bus Number': r.bus_number,
      Operator: r.operator || '',
      'Service Number': r.service_number || '',
      Route: r.route || '',
      'Last Check In': formatLastCheckIn(r.last_check_in),
    }));
  logger.info(`[TodayOccupancy] Built expectancy list: ${list.length} bus(es) (of ${busNumbers.length} looked up)`);
  return list;
}

module.exports = { buildExpectancyList, formatLastCheckIn };
