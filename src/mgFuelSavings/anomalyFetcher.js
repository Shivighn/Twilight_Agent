const axios = require('axios');
const config = require('../config');
const logger = require('../utils/logger');

// Business-rule thresholds fixed by spec, not deployment config — not
// meant to be overridden via env.
const MIN_NORMAL_MILEAGE = 2.5;
const MAX_NORMAL_MILEAGE = 4.6;

/**
 * A trip counts as an anomaly ONLY when calculated_mileage is present and
 * outside [2.5, 4.6] — 2.5 <= mileage <= 4.6 is never an anomaly, and no
 * other field (e.g. `reason`) factors in at all, regardless of its value.
 * This is NOT the same as "every row the endpoint returns" — it returns
 * every trip in range, most of which are perfectly normal.
 */
function isAnomaly(row) {
  const mileage = row.calculated_mileage;
  if (mileage === null || mileage === undefined) return false;
  return mileage < MIN_NORMAL_MILEAGE || mileage > MAX_NORMAL_MILEAGE;
}

/** Count of anomalous trips (see isAnomaly) between fromISO and toISO. */
async function fetchAnomalyCount(fromISO, toISO, session) {
  const url = `${config.mgFuelSavings.apiBaseUrl}/fuel-sorting-page/anomalies`;
  logger.info(`[MgFuelSavings] Fetching anomalies — GET ${url}?from=${fromISO}&to=${toISO}`);

  let response;
  try {
    response = await axios.get(url, {
      params: { from: fromISO, to: toISO },
      headers: { Cookie: session.cookieHeader },
      validateStatus: () => true,
    });
  } catch (err) {
    throw new Error(`[MgFuelSavings] Anomalies fetch failed: ${err.message}`);
  }

  if (response.status !== 200) {
    throw new Error(`[MgFuelSavings] Anomalies fetch failed — HTTP ${response.status} ${JSON.stringify(response.data)}`);
  }
  if (!Array.isArray(response.data)) {
    throw new Error(
      `[MgFuelSavings] Unexpected anomalies response shape — expected an array, got: ${JSON.stringify(response.data)}`
    );
  }

  const anomalyCount = response.data.filter(isAnomaly).length;
  logger.info(`[MgFuelSavings] Anomalies: ${response.data.length} trip(s) in range, ${anomalyCount} anomalous`);
  return anomalyCount;
}

module.exports = { fetchAnomalyCount, isAnomaly };
