const logger = require('../utils/logger');
const { saveFile } = require('../utils/storage');
const { yesterdayISTDateString } = require('./dateFormat');
const { fetchDepartedHistory } = require('./historyFetcher');
const { buildCsv } = require('./csvBuilder');
const { isAlreadySent, markSent } = require('./doneMarker');
const { sendCsvDocument } = require('./whatsappSender');

/**
 * One full daily run: fetch yesterday's (IST) departed Terminal 44 history,
 * build a CSV, and post it to WhatsApp. Deliberately does NOT swallow
 * errors anywhere in this chain — every stage either logs success and
 * moves on, or throws with enough detail to debug, and nothing here catches
 * that throw. The caller (scheduler.js) is the single place that catches it,
 * so a failure is loud (logged with full detail) but never crashes the
 * whole gateway process.
 */
async function runOnce() {
  const dateStr = yesterdayISTDateString();
  logger.info(`[Terminal44] Starting daily report run for ${dateStr}`);

  if (isAlreadySent(dateStr)) {
    logger.info(`[Terminal44] Report for ${dateStr} was already sent — skipping (idempotency guard)`);
    return { dateStr, skipped: true };
  }

  const rows = await fetchDepartedHistory(dateStr);
  const csv = buildCsv(rows);

  const fileName = `terminal44_history_${dateStr}.csv`;
  const buffer = Buffer.from(csv, 'utf8');

  // Audit trail — same convention as the rest of this repo's storage/
  // usage (petty cash's storage/processed/<date>/*.json).
  const savedPath = saveFile(buffer, fileName, 'terminal44');
  logger.info(`[Terminal44] CSV saved to ${savedPath}`);

  // const caption = `Terminal 44 Bus Arrival Report — ${dateStr} (${rows.length} departed)`;
  const caption = `${dateStr} - Terminal 44 Bus Arrival Report (${rows.length} departed)`;
  const result = await sendCsvDocument(buffer, fileName, caption);

  if (!result.success) {
    // Don't mark as sent — leave the idempotency guard open so the next
    // run (retry, or tomorrow's cron if this one never recovers) tries again.
    throw new Error(`[Terminal44] Failed to send report for ${dateStr}: ${result.error}`);
  }

  markSent(dateStr);
  logger.info(`[Terminal44] Run complete for ${dateStr} — ${rows.length} departed row(s) sent`);
  return { dateStr, skipped: false, rowCount: rows.length };
}

module.exports = { runOnce };
