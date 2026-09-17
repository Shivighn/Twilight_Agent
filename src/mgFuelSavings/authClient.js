const axios = require('axios');
const config = require('../config');
const logger = require('../utils/logger');

/**
 * The Fleetzen backend (be.fleetzen.co.in) has no API-key mode for this
 * data — the mg-fuel-savings and fuel-sorting-page endpoints require a
 * real logged-in session, exactly like a browser: an HttpOnly session
 * cookie plus a CSRF token. No other automation in this repo talks to this
 * backend this way (fleetIssues/terminal44 both hit different,
 * unauthenticated or Supabase-backed endpoints), so this is a new,
 * self-contained login flow — nothing existing to reuse here.
 *
 * Logs in fresh on every call. This job runs once a day and a whole run
 * (login + 2 fetches) takes seconds, while the session cookie is valid for
 * ~1 hour — so there's no need to persist or refresh a session across runs,
 * that would just be extra state for no benefit.
 *
 * Credentials come ONLY from env vars (MG_FUEL_SAVINGS_EMAIL /
 * MG_FUEL_SAVINGS_PASSWORD) — never hardcoded, same rule as every other
 * secret in this repo.
 */
async function login() {
  const { email, password } = config.mgFuelSavings.credentials;
  if (!email || !password) {
    throw new Error(
      '[MgFuelSavings] MG_FUEL_SAVINGS_EMAIL / MG_FUEL_SAVINGS_PASSWORD not set — cannot log in'
    );
  }

  const url = `${config.mgFuelSavings.apiBaseUrl}/auth/login`;
  logger.info(`[MgFuelSavings] Logging in as ${email} — POST ${url}`);

  let response;
  try {
    response = await axios.post(url, { email, password }, { validateStatus: () => true });
  } catch (err) {
    throw new Error(`[MgFuelSavings] Login request failed: ${err.message}`);
  }

  if (response.status !== 200) {
    throw new Error(`[MgFuelSavings] Login failed — HTTP ${response.status} ${JSON.stringify(response.data)}`);
  }

  const setCookieHeaders = response.headers['set-cookie'] || [];
  if (!setCookieHeaders.length) {
    throw new Error('[MgFuelSavings] Login succeeded (HTTP 200) but no Set-Cookie headers were returned');
  }

  // This axios instance has no browser-style cookie jar — rebuild every
  // Set-Cookie value's name=value pair into one Cookie header to send back
  // on subsequent requests (drops the Set-Cookie-only attributes like
  // Path/Expires/HttpOnly, which are meaningless on an outgoing request).
  const cookieHeader = setCookieHeaders.map((sc) => sc.split(';')[0]).join('; ');

  // The XSRF-TOKEN cookie's value is also returned directly in the body as
  // `csrfToken` — captured here for completeness (spec calls it out
  // explicitly), though every call this feature makes is a GET, which this
  // backend doesn't appear to CSRF-protect (verified against the live API
  // before writing this). Kept available on the session object so a future
  // POST/PUT could add an X-XSRF-TOKEN header without another login.
  const csrfToken = response.data && response.data.csrfToken;

  logger.info('[MgFuelSavings] Login successful — session cookie + CSRF token captured');
  return { cookieHeader, csrfToken };
}

module.exports = { login };
