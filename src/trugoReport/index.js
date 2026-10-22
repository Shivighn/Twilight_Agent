// Weekly Trugo bus arrival report — same data source and window-boundary
// convention as src/t44Buses/index.js (the t44_bus_bay_report Supabase RPC,
// 06:00 IST day-start / 04:00 IST next-day-end, non-overlapping), but the
// CSV/caption/snapshot-image format matches src/terminal44/index.js's
// IntrCity/Flix daily reports exactly, per request — just filtered to the
// Trugo operator and spanning the last 7 days instead of 1.
//
// Trugo gets WAY fewer buses than IntrCity/Flix, so this runs weekly
// (Monday 5:30 AM IST) over the past Mon-Sun instead of daily.

const axios = require('axios');
const config = require('../config');
const logger = require('../utils/logger');
const { sendToChat, resolveGroupJidByName } = require('../whatsapp/client');
const { buildTableImage } = require('../utils/tableImage');
const { CSV_HEADERS, formatVehicleNumber, csvField } = require('../terminal44/csvBuilder');
const { isAlreadySent, markSent } = require('./doneMarker');

const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000;
const HOUR_MS = 60 * 60 * 1000;
const DAY_MS = 24 * HOUR_MS;
const MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const OPERATOR_FILTER = 'trugo';

function istMidnightUTC(date) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Kolkata',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(date);
  const map = {};
  for (const p of parts) map[p.type] = p.value;
  return Date.UTC(Number(map.year), Number(map.month) - 1, Number(map.day));
}

/**
 * If run on a Monday, reports the 7 calendar days (Mon-Sun) ending
 * yesterday: window = [that Monday 06:00 IST, today 04:00 IST) — same
 * non-overlapping day-boundary convention as t44Buses/index.js, just 7
 * days wide. Running this at 5:30 AM safely clears the window's own
 * 04:00 IST close.
 */
function windowForLastWeek(now = new Date()) {
  const todayMidnightUTC = istMidnightUTC(now);
  const yesterdayMidnightUTC = todayMidnightUTC - DAY_MS; // end date
  const startMidnightUTC = yesterdayMidnightUTC - 6 * DAY_MS; // 7 days inclusive: start..yesterday

  const fromUTC = startMidnightUTC + 6 * HOUR_MS; // start date 06:00 IST
  const toUTC = todayMidnightUTC + 4 * HOUR_MS; // today 04:00 IST

  const fmt = (ms) => {
    const d = new Date(ms + IST_OFFSET_MS);
    return `${d.getUTCDate()} ${MONTH_ABBR[d.getUTCMonth()]}`;
  };
  const display = `${fmt(startMidnightUTC)} - ${fmt(yesterdayMidnightUTC)}`;
  const weekKey = new Date(startMidnightUTC + IST_OFFSET_MS).toISOString().slice(0, 10); // for the done-marker

  return { fromISO: new Date(fromUTC).toISOString(), toISO: new Date(toUTC).toISOString(), display, weekKey };
}

/** Same window shape, anchored on a given "YYYY-MM-DD" END date (the reported week's last day) — for manual ad-hoc testing. */
function windowForWeekEnding(endDateStr) {
  const [y, m, d] = endDateStr.split('-').map(Number);
  const endMidnightUTC = Date.UTC(y, m - 1, d) - IST_OFFSET_MS;
  const startMidnightUTC = endMidnightUTC - 6 * DAY_MS;
  const fromUTC = startMidnightUTC + 6 * HOUR_MS;
  const toUTC = endMidnightUTC + DAY_MS + 4 * HOUR_MS;

  const fmt = (ms) => {
    const dt = new Date(ms + IST_OFFSET_MS);
    return `${dt.getUTCDate()} ${MONTH_ABBR[dt.getUTCMonth()]}`;
  };
  const display = `${fmt(startMidnightUTC)} - ${fmt(endMidnightUTC)}`;
  const weekKey = new Date(startMidnightUTC + IST_OFFSET_MS).toISOString().slice(0, 10);

  return { fromISO: new Date(fromUTC).toISOString(), toISO: new Date(toUTC).toISOString(), display, weekKey };
}

// excelTextForce is a small, intentionally duplicated copy of the same
// trick used in terminal44/csvBuilder.js and investorReport/index.js —
// not exported from either, cheap enough to repeat rather than wire a
// cross-module export for.
function excelTextForce(value) {
  if (value === null || value === undefined || value === '') return '';
  return `="${String(value).replace(/"/g, '""')}"`;
}

/**
 * RPC row ({date, bus_number, bay, operator, route, service_id, arrival,
 * departure, stopped}, all already display-formatted server-side) ->
 * CSV_HEADERS-order row. Plain values, no CSV escaping, no Excel tricks —
 * shared by the CSV and the snapshot image, same convention as
 * terminal44/csvBuilder.js's own tableRow(). excelTextForce is applied
 * separately, only when building the CSV string below — the image
 * renders this as literal picture text, so the ="..." wrapper would show
 * up visibly (and wrongly) in the snapshot otherwise.
 */
function tableRow(row) {
  return [
    row.date,
    formatVehicleNumber(row.bus_number),
    row.service_id === null || row.service_id === undefined ? '' : String(row.service_id),
    row.operator || '',
    row.arrival,
    row.departure,
  ];
}

async function fetchTrugoRows(fromISO, toISO) {
  const { url: supabaseUrl, serviceRoleKey } = config.supabase;
  if (!supabaseUrl || !serviceRoleKey) {
    throw new Error('[TrugoReport] SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set');
  }
  const res = await axios.post(
    `${supabaseUrl}/rest/v1/rpc/t44_bus_bay_report`,
    { p_from: fromISO, p_to: toISO },
    { headers: { apikey: serviceRoleKey, Authorization: `Bearer ${serviceRoleKey}` }, validateStatus: () => true }
  );
  if (res.status !== 200) {
    throw new Error(`[TrugoReport] RPC failed — HTTP ${res.status} ${JSON.stringify(res.data)}`);
  }
  const rows = res.data.filter((r) => (r.operator || '').trim().toLowerCase().includes(OPERATOR_FILTER));
  logger.info(`[TrugoReport] ${res.data.length} bus(es) in window — ${rows.length} matching "${OPERATOR_FILTER}"`);
  return rows;
}

/**
 * One weekly run: RPC the past week's Trugo departures, build a CSV, send
 * it. `windowOverride` ({fromISO, toISO, display, weekKey}) is for manual
 * ad-hoc testing only — the real cron always calls with none. Deliberately
 * does NOT swallow errors — same convention as every other scheduled
 * report in this repo.
 */
async function runOnce(windowOverride) {
  const { fromISO, toISO, display, weekKey } = windowOverride || windowForLastWeek();
  logger.info(`[TrugoReport] Starting weekly run for ${display} (from=${fromISO} to=${toISO})`);

  if (isAlreadySent(weekKey)) {
    logger.info(`[TrugoReport] Report for week starting ${weekKey} was already sent — skipping (idempotency guard)`);
    return { weekKey, skipped: true };
  }

  const rows = await fetchTrugoRows(fromISO, toISO);

  const lines = [CSV_HEADERS.map(csvField).join(',')];
  for (const row of rows) {
    const fields = tableRow(row);
    fields[2] = excelTextForce(fields[2]); // Service ID: keep as literal text in Excel (leading zeros, "....." placeholders, etc.)
    lines.push(fields.map(csvField).join(','));
  }
  const csv = lines.join('\n');
  const buffer = Buffer.from(csv, 'utf8');
  const fileName = `terminal44_trugo_history_${weekKey}.csv`;

  const { whatsappGroupId } = config.trugoReport;
  if (!whatsappGroupId) throw new Error('[TrugoReport] TRUGO_REPORT_WHATSAPP_GROUP_ID not configured');
  const jid = await resolveGroupJidByName(whatsappGroupId);
  if (!jid) throw new Error(`[TrugoReport] Could not find WhatsApp group "${whatsappGroupId}"`);

  const caption = `${display} - Terminal 44 Trugo Bus Arrival Report (${rows.length} departed)`;
  const result = await sendToChat(jid, { document: buffer, fileName, mimetype: 'text/csv', caption });
  if (!result.success) {
    throw new Error(`[TrugoReport] Failed to send report for ${display}: ${result.error}`);
  }

  // Marked as soon as the CSV is confirmed sent — a failure in the image
  // below must not make a retry re-send the CSV as a duplicate.
  markSent(weekKey);

  if (rows.length > 0) {
    const image = await buildTableImage(CSV_HEADERS, rows.map(tableRow));
    const imageResult = await sendToChat(jid, { image });
    if (!imageResult.success) {
      throw new Error(`[TrugoReport] Snapshot image send failed for ${display}: ${imageResult.error}`);
    }
  }

  logger.info(`[TrugoReport] Run complete for ${display} — ${rows.length} departed row(s) sent`);
  return { weekKey, skipped: false, rowCount: rows.length };
}

module.exports = { runOnce, windowForLastWeek, windowForWeekEnding };
