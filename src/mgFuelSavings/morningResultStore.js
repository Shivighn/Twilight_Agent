// Persists the 10 AM run's anomaly count so the 4 PM job can decide whether
// to run at all — even across a process restart in between. Mirrors the
// check-before-act idiom in terminal44/doneMarker.js: a small file is the
// minimal durable state for a twice-a-day gate, no DB table needed.

const fs = require('fs');
const path = require('path');
const config = require('../config');
const logger = require('../utils/logger');

const RESULT_PATH = path.join(config.storage.dir, 'mgFuelSavings', 'morning_run_result.json');

function readResult() {
  try {
    return JSON.parse(fs.readFileSync(RESULT_PATH, 'utf8'));
  } catch (err) {
    if (err.code === 'ENOENT') return null; // no 10 AM run recorded yet — not an error
    logger.warn(`[MgFuelSavings] Could not read morning-run result (${err.message}) — treating as none`);
    return null;
  }
}

/**
 * Record the 10 AM run's anomaly count for `dateStr` (YYYY-MM-DD, IST).
 * Called right after the anomalies fetch succeeds — deliberately NOT
 * gated on whether the WhatsApp send itself succeeds, since the 4 PM gate
 * is about what was actually detected, not about delivery.
 */
function saveMorningResult(dateStr, anomalyCount) {
  fs.mkdirSync(path.dirname(RESULT_PATH), { recursive: true });
  fs.writeFileSync(
    RESULT_PATH,
    JSON.stringify({ date: dateStr, anomalyCount, savedAt: new Date().toISOString() }, null, 2)
  );
}

/**
 * The 10 AM anomaly count for `dateStr`, or null if none was recorded —
 * either the morning run hasn't happened yet today, or (crash-safe default)
 * its fetch never completed. A null result means the 4 PM job has nothing
 * to gate on and should skip rather than guess.
 */
function getMorningAnomalyCount(dateStr) {
  const result = readResult();
  if (!result || result.date !== dateStr) return null;
  return result.anomalyCount;
}

module.exports = { saveMorningResult, getMorningAnomalyCount };
