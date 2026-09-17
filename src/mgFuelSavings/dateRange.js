// Computes the CURRENT calendar month's boundaries in Asia/Kolkata, fresh
// on every call — never hardcode a month. India has no DST, so a fixed
// +5:30 offset (rather than the server's local clock, which is UTC) is
// both correct and simple.
const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000;

function istPartsOf(date) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Kolkata',
    year: 'numeric',
    month: '2-digit',
  }).formatToParts(date);
  const map = {};
  for (const p of parts) map[p.type] = p.value;
  return { year: Number(map.year), month: Number(map.month) };
}

/**
 * { yearMonth: "YYYY-MM", fromISO, toISO } for the current IST calendar
 * month. `fromISO` is the 1st of the month at 00:00:00.000 IST; `toISO` is
 * the last instant of the month (23:59:59.999 IST on the last day) —
 * computed as "start of next month IST minus 1ms" so it's correct
 * regardless of how many days are in the month (28/29/30/31). Both are
 * returned as UTC ISO strings, ready to pass straight to the API.
 */
function getCurrentMonthRangeIST(now = new Date()) {
  const { year, month } = istPartsOf(now);
  const yearMonth = `${year}-${String(month).padStart(2, '0')}`;

  const startOfMonthUTC = Date.UTC(year, month - 1, 1, 0, 0, 0, 0) - IST_OFFSET_MS;
  const startOfNextMonthUTC = Date.UTC(year, month, 1, 0, 0, 0, 0) - IST_OFFSET_MS;

  return {
    yearMonth,
    fromISO: new Date(startOfMonthUTC).toISOString(),
    toISO: new Date(startOfNextMonthUTC - 1).toISOString(),
  };
}

module.exports = { getCurrentMonthRangeIST };
