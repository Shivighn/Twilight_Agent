const axios = require('axios');
const config = require('../config');
const logger = require('../utils/logger');

// Case-insensitive substring match, not exact equality — tolerates the
// operator name coming back with different spacing/casing ("IntrCity
// SmartBus", "INTRCITY SMARTBUS", etc.) without over-matching an unrelated
// operator.
const OPERATOR_FILTER = 'intrcity';

const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000;
const HOUR_MS = 60 * 60 * 1000;
const DAY_MS = 24 * HOUR_MS;

/**
 * [D 04:00 IST, D+1 04:00 IST) as UTC instants — the report's "business day"
 * boundary. Buses that check out between midnight and 4 AM belong to the
 * PREVIOUS day's window, not this one, matching the T44 bus-bay report's
 * same 4 AM cutoff (src/t44Buses/index.js). Needed because a plain
 * from=D&to=D API call returns D 00:00 through ~D+1 04:00 (its own tail
 * extension), which overlaps with the NEXT day's from=D+1&to=D+1 call for
 * that same 00:00-04:00 slice — without this filter, a bus checking out at
 * say 1 AM would appear in both days' WhatsApp reports.
 */
function windowForDate(dateStr) {
  const [y, m, d] = dateStr.split('-').map(Number);
  const dayMidnightIST = Date.UTC(y, m - 1, d) - IST_OFFSET_MS;
  return { fromUTC: dayMidnightIST + 4 * HOUR_MS, toUTC: dayMidnightIST + DAY_MS + 4 * HOUR_MS };
}

/**
 * Fetch a day's (IST) Terminal 44 history and filter to departed rows for
 * one operator (`operatorFilter`, default IntrCity — the original report).
 *
 * `from`/`to` are BOTH set to the same date deliberately (per the API's own
 * contract) — the endpoint already extends a single day's window to 4:00 AM
 * the next calendar day internally, so a 2-day span would double-count.
 * The [D 04:00, D+1 04:00) filter below then narrows that to our own
 * non-overlapping business-day window (see windowForDate above).
 */
async function fetchDepartedHistory(dateStr, operatorFilter = OPERATOR_FILTER) {
  const url = `${config.terminal44.apiBaseUrl}/terminal44/history`;
  logger.info(`[Terminal44] Fetching history for ${dateStr} — GET ${url}?from=${dateStr}&to=${dateStr}`);

  let response;
  try {
    response = await axios.get(url, { params: { from: dateStr, to: dateStr }, timeout: 30000 });
  } catch (err) {
    const detail = err.response
      ? `HTTP ${err.response.status} ${JSON.stringify(err.response.data)}`
      : err.message;
    throw new Error(`[Terminal44] History fetch failed for ${dateStr}: ${detail}`);
  }

  const { data } = response;
  if (!data || !Array.isArray(data.rows)) {
    throw new Error(
      `[Terminal44] Unexpected response shape for ${dateStr} — expected { from, to, rows: [...] }, got: ${JSON.stringify(data)}`
    );
  }

  const departed = data.rows.filter((row) => row.status === 'departed');
  const matched = departed.filter((row) => (row.operator_name || '').trim().toLowerCase().includes(operatorFilter));

  const { fromUTC, toUTC } = windowForDate(dateStr);
  const filtered = matched.filter((row) => {
    const t = new Date(row.scheduled_departure).getTime();
    return t >= fromUTC && t < toUTC;
  });

  logger.info(
    `[Terminal44] Fetched ${data.rows.length} row(s) for ${dateStr} (from=${data.from}, to=${data.to}) — ` +
      `${departed.length} departed, ${matched.length} matching "${operatorFilter}", ` +
      `${filtered.length} within [04:00, next-day 04:00) window`
  );

  return filtered;
}

module.exports = { fetchDepartedHistory };
