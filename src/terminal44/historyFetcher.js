const axios = require('axios');
const config = require('../config');
const logger = require('../utils/logger');

// Case-insensitive substring match, not exact equality — tolerates the
// operator name coming back with different spacing/casing ("IntrCity
// SmartBus", "INTRCITY SMARTBUS", etc.) without over-matching an unrelated
// operator.
const OPERATOR_FILTER = 'intrcity';

/**
 * Fetch yesterday's (IST) Terminal 44 history and filter to departed rows
 * for the IntrCity SmartBus operator only.
 *
 * `from`/`to` are BOTH set to the same date deliberately (per the API's own
 * contract) — the endpoint already extends a single day's window to 4:00 AM
 * the next calendar day internally, so a 2-day span would double-count.
 */
async function fetchDepartedHistory(dateStr) {
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
  const filtered = departed.filter((row) => (row.operator_name || '').trim().toLowerCase().includes(OPERATOR_FILTER));
  logger.info(
    `[Terminal44] Fetched ${data.rows.length} row(s) for ${dateStr} (from=${data.from}, to=${data.to}) — ` +
      `${departed.length} departed, ${filtered.length} IntrCity SmartBus`
  );

  return filtered;
}

module.exports = { fetchDepartedHistory };
