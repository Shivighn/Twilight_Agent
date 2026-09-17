const axios = require('axios');
const config = require('../config');
const logger = require('../utils/logger');

/** Sum of `fuel_savings` across every row returned for the given "YYYY-MM". */
async function fetchTotalSavings(yearMonth, session) {
  const url = `${config.mgFuelSavings.apiBaseUrl}/performance-page/mg-fuel-savings/savings`;
  logger.info(`[MgFuelSavings] Fetching savings for ${yearMonth} — GET ${url}?year_month=${yearMonth}`);

  let response;
  try {
    response = await axios.get(url, {
      params: { year_month: yearMonth },
      headers: { Cookie: session.cookieHeader },
      validateStatus: () => true,
    });
  } catch (err) {
    throw new Error(`[MgFuelSavings] Savings fetch failed for ${yearMonth}: ${err.message}`);
  }

  if (response.status !== 200) {
    throw new Error(
      `[MgFuelSavings] Savings fetch failed for ${yearMonth} — HTTP ${response.status} ${JSON.stringify(response.data)}`
    );
  }
  if (!Array.isArray(response.data)) {
    throw new Error(
      `[MgFuelSavings] Unexpected savings response shape for ${yearMonth} — expected an array, got: ${JSON.stringify(response.data)}`
    );
  }

  const total = response.data.reduce((sum, row) => sum + (Number(row.fuel_savings) || 0), 0);
  logger.info(`[MgFuelSavings] Savings for ${yearMonth}: ${response.data.length} row(s), total = ${total}`);
  return total;
}

module.exports = { fetchTotalSavings };
