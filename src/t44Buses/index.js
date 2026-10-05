const axios = require('axios');
const config = require('../config');
const logger = require('../utils/logger');
const { sendToChat, resolveGroupJidByName } = require('../whatsapp/client');

const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000;
const HOUR_MS = 60 * 60 * 1000;
const DAY_MS = 24 * HOUR_MS;
const MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/**
 * If run/sent on day D, the window is [D-1 06:00 IST, D 04:00 IST) — same
 * "yesterday's window extends to 4 AM" contract as the existing
 * terminal44 feature. Returns ISO instants for the RPC plus the display
 * date for the reported day (D-1, e.g. "25 Sep").
 */
function windowForToday(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Kolkata',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(now);
  const map = {};
  for (const p of parts) map[p.type] = p.value;

  const todayMidnightIST = Date.UTC(Number(map.year), Number(map.month) - 1, Number(map.day)) - IST_OFFSET_MS;
  const fromUTC = todayMidnightIST - DAY_MS + 6 * HOUR_MS; // yesterday 06:00 IST
  const toUTC = todayMidnightIST + 4 * HOUR_MS; // today 04:00 IST

  const reportedDay = new Date(todayMidnightIST - DAY_MS + IST_OFFSET_MS); // yesterday, IST wall-clock
  const display = `${reportedDay.getUTCDate()} ${MONTH_ABBR[reportedDay.getUTCMonth()]}`;

  return { fromISO: new Date(fromUTC).toISOString(), toISO: new Date(toUTC).toISOString(), display };
}

/** Same window shape as windowForToday(), but anchored directly on a given "YYYY-MM-DD" reported day — for manual ad-hoc testing of a specific date. */
function windowForDate(dateStr) {
  const [y, m, d] = dateStr.split('-').map(Number);
  const dayMidnightIST = Date.UTC(y, m - 1, d) - IST_OFFSET_MS;
  const fromUTC = dayMidnightIST + 6 * HOUR_MS; // that day 06:00 IST
  const toUTC = dayMidnightIST + DAY_MS + 4 * HOUR_MS; // next day 04:00 IST
  const display = `${d} ${MONTH_ABBR[m - 1]}`;
  return { fromISO: new Date(fromUTC).toISOString(), toISO: new Date(toUTC).toISOString(), display };
}

// RFC 4180: quote a field if it contains a comma, quote, or newline.
function csvField(value) {
  const s = value === null || value === undefined ? '' : String(value);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

// "8:15 PM" -> 1215 (minutes since midnight). The RPC only returns
// arrival/departure as pre-formatted 12h text, so bucketing has to parse it
// back — no raw timestamp available.
function parseMinutes(timeStr) {
  const m = /^(\d{1,2}):(\d{2})\s(AM|PM)$/.exec(timeStr || '');
  if (!m) return null;
  let h = Number(m[1]) % 12;
  if (m[3] === 'PM') h += 12;
  return h * 60 + Number(m[2]);
}

// ponytail: 7:30 PM through the end of the window (4 AM) — 7:30-9, 9-10,
// 10-11, 11-12 PM, then everything after midnight lumped into "After 12 AM".
const BUCKETS = [
  { label: '7:30-9 PM', match: (min) => min !== null && min >= 19 * 60 + 30 && min < 21 * 60 },
  { label: '9-10 PM', match: (min) => min !== null && min >= 21 * 60 && min < 22 * 60 },
  { label: '10-11 PM', match: (min) => min !== null && min >= 22 * 60 && min < 23 * 60 },
  { label: '11-12 PM', match: (min) => min !== null && min >= 23 * 60 && min < 24 * 60 },
  { label: 'After 12 AM', match: (min) => min !== null && min < 19 * 60 + 30 },
];

/** "8-9 PM: 8 buses (2 IntrCity, 2 Flix, 4 Zing)" per bucket, joined by blank lines. Buckets by CHECK-IN (arrival) time. */
function buildHourlySummary(rows) {
  const lines = BUCKETS.map(({ label, match }) => {
    const inHour = rows.filter((r) => match(parseMinutes(r.arrival)));
    if (inHour.length === 0) return null; // skip empty time slots
    const counts = {};
    for (const r of inHour) counts[r.operator] = (counts[r.operator] || 0) + 1;
    const breakdown = Object.entries(counts)
      .map(([op, c]) => `${c} ${op}`)
      .join(', ');
    const busWord = inHour.length === 1 ? 'bus' : 'buses';
    return `${label}: ${inHour.length} ${busWord}${breakdown ? ` (${breakdown})` : ''}`;
  }).filter(Boolean);
  return lines.join('\n\n');
}

/**
 * One daily run: RPC the bus-bay report for yesterday's window, build a
 * CSV, send it with the row count in the caption. `windowOverride` (for
 * manual ad-hoc testing only — the real cron always calls with none) is
 * { fromISO, toISO, display }. Throws (doesn't swallow) on failure.
 */
async function runOnce(windowOverride) {
  const { url: supabaseUrl, serviceRoleKey: supabaseServiceRoleKey } = config.supabase;
  const { whatsappGroupId } = config.t44Buses;
  if (!supabaseUrl || !supabaseServiceRoleKey) {
    throw new Error('[T44Buses] SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set');
  }

  const { fromISO, toISO, display } = windowOverride || windowForToday();
  logger.info(`[T44Buses] Fetching bus bay report — from=${fromISO} to=${toISO}`);

  const res = await axios.post(
    `${supabaseUrl}/rest/v1/rpc/t44_bus_bay_report`,
    { p_from: fromISO, p_to: toISO },
    {
      headers: { apikey: supabaseServiceRoleKey, Authorization: `Bearer ${supabaseServiceRoleKey}` },
      validateStatus: () => true,
    }
  );
  if (res.status !== 200) {
    throw new Error(`[T44Buses] RPC failed — HTTP ${res.status} ${JSON.stringify(res.data)}`);
  }
  const rows = res.data;
  logger.info(`[T44Buses] ${rows.length} bus(es) stopped`);

  const headers = ['Date', 'Bus Number', 'Bay', 'Operator', 'Route', 'Service ID', 'Arrival', 'Departure', 'Stopped'];
  const lines = [headers.map(csvField).join(',')];
  for (const r of rows) {
    lines.push(
      [r.date, r.bus_number, r.bay, r.operator, r.route, r.service_id, r.arrival, r.departure, r.stopped]
        .map(csvField)
        .join(',')
    );
  }
  const csv = lines.join('\n');

  if (!whatsappGroupId) throw new Error('[T44Buses] T44_BUSES_WHATSAPP_GROUP_ID not configured');
  const jid = await resolveGroupJidByName(whatsappGroupId);
  if (!jid) throw new Error(`[T44Buses] Could not find WhatsApp group "${whatsappGroupId}"`);

  const fileName = `t44_bus_bay_${new Date().toISOString().slice(0, 10)}.csv`;
  const result = await sendToChat(jid, {
    document: Buffer.from(csv, 'utf8'),
    fileName,
    mimetype: 'text/csv',
    caption: `${display}, ${rows.length} buses stopped at T-44\n\n${buildHourlySummary(rows)}`,
  });
  if (!result.success) throw new Error(`[T44Buses] Send failed: ${result.error}`);

  logger.info('[T44Buses] Sent');
  return { display, rowCount: rows.length };
}

module.exports = { runOnce, windowForToday, windowForDate, buildHourlySummary };
