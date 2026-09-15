// All date/time handling for the Terminal 44 report is anchored to
// Asia/Kolkata explicitly (via Intl's `timeZone`), never the server's local
// clock — the VPS this runs on is UTC, and India has no DST, so a fixed
// +5:30 read via Intl is both correct and simple.

const IST_TZ = 'Asia/Kolkata';
const MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function istPartsOf(date, opts) {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: IST_TZ, ...opts }).formatToParts(date);
  const map = {};
  for (const p of parts) map[p.type] = p.value;
  return map;
}

/** YYYY-MM-DD (IST calendar date) for "now", or for an explicit Date. */
function istDateString(date = new Date()) {
  const { year, month, day } = istPartsOf(date, { year: 'numeric', month: '2-digit', day: '2-digit' });
  return `${year}-${month}-${day}`;
}

/**
 * "Yesterday" as a YYYY-MM-DD string, computed from the IST calendar date —
 * not the server's local date. Pure calendar-day subtraction (no time-of-day
 * involved), so it's safe across month/year boundaries.
 */
function yesterdayISTDateString(now = new Date()) {
  const { year, month, day } = istPartsOf(now, { year: 'numeric', month: '2-digit', day: '2-digit' });
  const asUTC = Date.UTC(Number(year), Number(month) - 1, Number(day));
  const yesterday = new Date(asUTC - 24 * 60 * 60 * 1000);
  const yyyy = yesterday.getUTCFullYear();
  const mm = String(yesterday.getUTCMonth() + 1).padStart(2, '0');
  const dd = String(yesterday.getUTCDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

/** "9-Sep-26" (IST), no leading zero on the day. `iso` is any parseable timestamp. */
function formatDateDMMMYY(iso) {
  const d = new Date(iso);
  const { year, month, day } = istPartsOf(d, { year: '2-digit', month: 'numeric', day: 'numeric' });
  const monthAbbr = MONTH_ABBR[Number(month) - 1];
  return `${day}-${monthAbbr}-${year}`;
}

/** "9:05 AM" (IST), no leading zero on the hour. `iso` is any parseable timestamp. */
function formatTimeAMPM(iso) {
  const d = new Date(iso);
  const { hour, minute, dayPeriod } = istPartsOf(d, {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
    hourCycle: 'h12',
  });
  return `${hour}:${minute} ${dayPeriod}`;
}

module.exports = { istDateString, yesterdayISTDateString, formatDateDMMMYY, formatTimeAMPM };
