const logger = require('../utils/logger');
const { login } = require('./authClient');
const { getCurrentMonthRangeIST, getTodayISTDateString } = require('./dateRange');
const { fetchTotalSavings } = require('./savingsFetcher');
const { fetchAnomalyCount } = require('./anomalyFetcher');
const { buildAnomalyMessage, buildSavingsMessage } = require('./messageBuilder');
const { sendMgFuelSavingsMessage } = require('./whatsappSender');
const { saveMorningResult, getMorningAnomalyCount } = require('./morningResultStore');

/**
 * Log in and fetch BOTH savings and anomalies for the current
 * (recomputed-every-call) month. Deliberately does NOT swallow errors: if
 * login or either fetch fails, this throws — both are always fetched
 * regardless of which one ends up mattering, because a failure in the
 * anomalies fetch means we don't actually know whether anomalies are >0,
 * so proceeding on the savings number alone would be silently wrong.
 */
async function fetchStatus() {
  const session = await login();
  const { yearMonth, fromISO, toISO } = getCurrentMonthRangeIST();

  const totalSavings = await fetchTotalSavings(yearMonth, session);
  const anomalyCount = await fetchAnomalyCount(fromISO, toISO, session);

  return { yearMonth, totalSavings, anomalyCount };
}

/** Builds the right message for the current status and sends it. Throws (doesn't swallow) on send failure. */
async function sendStatus(periodLabel, { anomalyCount, totalSavings }) {
  const sendAnomalyMessage = anomalyCount > 0;
  const content = sendAnomalyMessage ? buildAnomalyMessage(anomalyCount) : buildSavingsMessage(totalSavings);
  logger.info(
    `[MgFuelSavings] ${periodLabel} decision: anomalyCount=${anomalyCount}, totalSavings=${totalSavings} -> sending ${
      sendAnomalyMessage ? 'anomaly' : 'savings'
    } message`
  );

  const result = await sendMgFuelSavingsMessage(content);
  if (!result.success) {
    throw new Error(`[MgFuelSavings] Failed to send ${periodLabel} message: ${result.error}`);
  }
  return sendAnomalyMessage;
}

/**
 * 10 AM run: always executes. Fetches status, PERSISTS the anomaly count
 * (before attempting to send — the 4 PM gate is about what was detected,
 * not about whether the WhatsApp send happened to succeed), then sends.
 */
async function runMorning() {
  logger.info('[MgFuelSavings] Starting 10 AM run');

  const status = await fetchStatus();
  saveMorningResult(getTodayISTDateString(), status.anomalyCount);
  logger.info(`[MgFuelSavings] 10 AM anomaly count persisted: ${status.anomalyCount}`);

  const sentAnomalyMessage = await sendStatus('10 AM', status);

  logger.info('[MgFuelSavings] 10 AM run complete');
  return { period: 'morning', skipped: false, sentAnomalyMessage, ...status };
}

/**
 * 4 PM run: only actually fetches/sends if the 10 AM run (today, IST)
 * recorded at least 1 anomaly. Reads that result from disk, not memory —
 * correct even if the process restarted between 10 AM and 4 PM. Uses
 * FRESH data for the message itself (re-fetches at send time), only the
 * gate condition comes from the morning's persisted count.
 */
async function runAfternoon() {
  logger.info('[MgFuelSavings] Starting 4 PM run');

  const todayIST = getTodayISTDateString();
  const morningAnomalyCount = getMorningAnomalyCount(todayIST);

  if (morningAnomalyCount === null) {
    logger.warn('[MgFuelSavings] No 10 AM result recorded for today — skipping 4 PM run');
    return { period: 'afternoon', skipped: true, reason: 'no_morning_result' };
  }
  if (morningAnomalyCount === 0) {
    logger.info('[MgFuelSavings] 10 AM found 0 anomalies — skipping 4 PM message');
    return { period: 'afternoon', skipped: true, reason: 'no_anomalies_this_morning' };
  }

  logger.info(`[MgFuelSavings] 10 AM found ${morningAnomalyCount} anomaly(ies) — proceeding with 4 PM run`);
  const status = await fetchStatus();
  const sentAnomalyMessage = await sendStatus('4 PM', status);

  logger.info('[MgFuelSavings] 4 PM run complete');
  return { period: 'afternoon', skipped: false, sentAnomalyMessage, ...status };
}

module.exports = { runMorning, runAfternoon };
