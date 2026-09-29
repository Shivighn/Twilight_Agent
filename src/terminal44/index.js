const logger = require('../utils/logger');
const config = require('../config');
const { saveFile } = require('../utils/storage');
const { buildTableImage } = require('../utils/tableImage');
const { yesterdayISTDateString } = require('./dateFormat');
const { fetchDepartedHistory } = require('./historyFetcher');
const { buildCsv, tableRow, CSV_HEADERS } = require('./csvBuilder');
const { isAlreadySent, markSent } = require('./doneMarker');
const { sendCsvDocument, sendImage } = require('./whatsappSender');

// One entry per operator report. Same fetch/CSV/send pipeline; only the
// operator filter, target group, idempotency marker and file name differ.
const INTRCITY = {
  label: 'IntrCity',
  operatorFilter: 'intrcity',
  groupId: config.terminal44.whatsappGroupId,
  markerName: undefined, // original last_sent.json
  filePrefix: 'terminal44_history',
  withImage: true, // snapshot image of the CSV, for a quick glance
};
const FLIX = {
  label: 'Flix',
  operatorFilter: 'flix',
  groupId: config.terminal44.flix.whatsappGroupId,
  markerName: 'last_sent_flix',
  filePrefix: 'terminal44_flix_history',
  withImage: true, // snapshot image of the CSV, for a quick glance
};

/**
 * One full daily run for one operator: fetch a day's (IST) departed
 * Terminal 44 history, build a CSV, and post it to WhatsApp (plus a table
 * snapshot image when `withImage`). `dateOverride` ("YYYY-MM-DD") is for
 * manual testing only — the cron never passes it, so it always reports
 * yesterday. Deliberately does NOT swallow errors anywhere in this chain —
 * every stage either logs success and moves on, or throws with enough
 * detail to debug. The caller (scheduler.js) is the single place that
 * catches it, so a failure is loud (logged with full detail) but never
 * crashes the whole gateway process.
 */
async function runReport(cfg, dateOverride) {
  const { label, operatorFilter, groupId, markerName, filePrefix, withImage } = cfg;
  const dateStr = dateOverride || yesterdayISTDateString();
  logger.info(`[Terminal44] Starting daily ${label} report run for ${dateStr}`);

  if (isAlreadySent(dateStr, markerName)) {
    logger.info(`[Terminal44] ${label} report for ${dateStr} was already sent — skipping (idempotency guard)`);
    return { dateStr, skipped: true };
  }

  const rows = await fetchDepartedHistory(dateStr, operatorFilter);
  const csv = buildCsv(rows);

  const fileName = `${filePrefix}_${dateStr}.csv`;
  const buffer = Buffer.from(csv, 'utf8');

  // Audit trail — same convention as the rest of this repo's storage/
  // usage (petty cash's storage/processed/<date>/*.json).
  const savedPath = saveFile(buffer, fileName, 'terminal44');
  logger.info(`[Terminal44] CSV saved to ${savedPath}`);

  const caption = `${dateStr} - Terminal 44 Bus Arrival Report (${rows.length} departed)`;
  const result = await sendCsvDocument(buffer, fileName, caption, groupId);

  if (!result.success) {
    // Don't mark as sent — leave the idempotency guard open so the next
    // run (retry, or tomorrow's cron if this one never recovers) tries again.
    throw new Error(`[Terminal44] Failed to send ${label} report for ${dateStr}: ${result.error}`);
  }

  // Marked as soon as the CSV is confirmed sent — a failure in the image
  // below must not make a retry re-send the CSV as a duplicate.
  markSent(dateStr, markerName);

  if (withImage && rows.length > 0) {
    const image = await buildTableImage(CSV_HEADERS, rows.map(tableRow));
    const imageResult = await sendImage(image, groupId);
    if (!imageResult.success) {
      throw new Error(`[Terminal44] ${label} snapshot image send failed for ${dateStr}: ${imageResult.error}`);
    }
  }

  logger.info(`[Terminal44] ${label} run complete for ${dateStr} — ${rows.length} departed row(s) sent`);
  return { dateStr, skipped: false, rowCount: rows.length };
}

const runOnce = (dateOverride) => runReport(INTRCITY, dateOverride);
const runFlix = (dateOverride) => runReport(FLIX, dateOverride);

module.exports = { runOnce, runFlix };
