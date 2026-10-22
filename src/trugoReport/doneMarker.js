// Same idempotency pattern as src/terminal44/doneMarker.js — keyed by the
// reported week's START date (YYYY-MM-DD), so a gateway restart mid-week
// doesn't re-send the same week's report, but next week's different key
// still goes out normally.

const fs = require('fs');
const path = require('path');
const config = require('../config');
const logger = require('../utils/logger');

function markerPath() {
  return path.join(config.storage.dir, 'trugoReport', 'last_sent.json');
}

function readMarker() {
  try {
    return JSON.parse(fs.readFileSync(markerPath(), 'utf8'));
  } catch (err) {
    if (err.code === 'ENOENT') return null; // never sent before — not an error
    logger.warn(`[TrugoReport] Could not read done-marker (${err.message}) — treating as not-yet-sent`);
    return null;
  }
}

/** Has the report for this `weekKey` (the week's start date, YYYY-MM-DD) already been sent successfully? */
function isAlreadySent(weekKey) {
  const marker = readMarker();
  return !!marker && marker.weekKey === weekKey;
}

/** Record that `weekKey`'s report was sent — call ONLY after a confirmed successful send. */
function markSent(weekKey) {
  const file = markerPath();
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify({ weekKey, sentAt: new Date().toISOString() }, null, 2));
}

module.exports = { isAlreadySent, markSent };
