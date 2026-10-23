const axios = require('axios');
const config = require('../config');
const logger = require('../utils/logger');

// Business-rule thresholds fixed by spec, not deployment config — not
// meant to be overridden via env.
const MIN_NORMAL_MILEAGE = 2.5;
const MAX_NORMAL_MILEAGE = 4.8;

/**
 * A trip counts as an anomaly ONLY when calculated_mileage is present and
 * outside [2.5, 4.8] — 2.5 <= mileage <= 4.8 is never an anomaly, and no
 * other field (e.g. `reason`) factors in at all, regardless of its value.
 * This is NOT the same as "every row the endpoint returns" — it returns
 * every trip in range, most of which are perfectly normal.
 */
function isAnomaly(row) {
  const mileage = row.calculated_mileage;
  if (mileage === null || mileage === undefined) return false;
  return mileage < MIN_NORMAL_MILEAGE || mileage > MAX_NORMAL_MILEAGE;
}

/** A trip whose mileage hasn't been calculated yet (seen in the wild as `reason: "PENDING_MILEAGE"`, but mileage being null/undefined is the actual signal checked). */
function isPendingMileage(row) {
  return row.calculated_mileage === null || row.calculated_mileage === undefined;
}

/** { anomalyCount, pendingMileageCount } between fromISO and toISO — one fetch, two counts over the same rows. */
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
  const pendingMileageCount = response.data.filter(isPendingMileage).length;
  logger.info(
    `[MgFuelSavings] Trips: ${response.data.length} in range, ${anomalyCount} anomalous, ${pendingMileageCount} pending mileage`
  );
  return { anomalyCount, pendingMileageCount };
}

module.exports = { fetchAnomalyCount, isAnomaly, isPendingMileage };
