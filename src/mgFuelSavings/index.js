const logger = require('../utils/logger');
const { login } = require('./authClient');
const { getCurrentMonthRangeIST } = require('./dateRange');
const { fetchTotalSavings } = require('./savingsFetcher');
const { fetchAnomalyCount } = require('./anomalyFetcher');
const { buildAnomalyMessage, buildSavingsMessage } = require('./messageBuilder');
const { sendMgFuelSavingsMessage } = require('./whatsappSender');

/**
 * One full daily run: log in, fetch BOTH savings and anomalies for the
 * current (recomputed-every-run) month, then send exactly one message —
 * anomalies take priority if any exist, otherwise the savings total.
 *
 * Deliberately does NOT swallow errors anywhere in this chain: if login or
 * either fetch fails, this throws and NOTHING is sent. Both are always
 * fetched regardless of which one ends up mattering, because a failure in
 * the anomalies fetch means we don't actually know whether anomalies are
 * >0 — posting the savings total in that case would be silently wrong, not
 * just stale. The caller (scheduler.js) is the only place that catches the
 * error, so a failure is loud (logged with full detail) but never crashes
 * the whole gateway process.
 */
async function runOnce() {
  logger.info('[MgFuelSavings] Starting daily run');

  const session = await login();
  const { yearMonth, fromISO, toISO } = getCurrentMonthRangeIST();

  const totalSavings = await fetchTotalSavings(yearMonth, session);
  const anomalyCount = await fetchAnomalyCount(fromISO, toISO, session);

  const sendAnomalyMessage = anomalyCount > 0;
  const text = sendAnomalyMessage ? buildAnomalyMessage(anomalyCount) : buildSavingsMessage(totalSavings);
  logger.info(
    `[MgFuelSavings] Decision: anomalyCount=${anomalyCount}, totalSavings=${totalSavings} -> sending ${
      sendAnomalyMessage ? 'anomaly' : 'savings'
    } message`
  );

  const result = await sendMgFuelSavingsMessage(text);
  if (!result.success) {
    throw new Error(`[MgFuelSavings] Failed to send message: ${result.error}`);
  }

  logger.info('[MgFuelSavings] Run complete');
  return { yearMonth, anomalyCount, totalSavings, sentAnomalyMessage: sendAnomalyMessage };
}

module.exports = { runOnce };
