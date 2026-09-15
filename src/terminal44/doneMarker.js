// The idempotency guard for this job — mirrors the check-before-act /
// update-only-after-confirmed-send idiom in fleetIssues/notificationTracker.js
// (there it's a DB row; a single daily report has no per-item state to
// track, so a small persisted marker file is the minimal equivalent).
// Whatever date this file names has already been sent — a retry or a
// second cron fire for the same day must NOT send twice.

const fs = require('fs');
const path = require('path');
const config = require('../config');
const logger = require('../utils/logger');

const MARKER_PATH = path.join(config.storage.dir, 'terminal44', 'last_sent.json');

function readMarker() {
  try {
    return JSON.parse(fs.readFileSync(MARKER_PATH, 'utf8'));
  } catch (err) {
    if (err.code === 'ENOENT') return null; // never sent before — not an error
    logger.warn(`[Terminal44] Could not read done-marker (${err.message}) — treating as not-yet-sent`);
    return null;
  }
}

/** Has the report for `dateStr` (YYYY-MM-DD) already been sent successfully? */
function isAlreadySent(dateStr) {
  const marker = readMarker();
  return !!marker && marker.date === dateStr;
}

/** Record that `dateStr`'s report was sent — call ONLY after a confirmed successful send. */
function markSent(dateStr) {
  fs.mkdirSync(path.dirname(MARKER_PATH), { recursive: true });
  fs.writeFileSync(MARKER_PATH, JSON.stringify({ date: dateStr, sentAt: new Date().toISOString() }, null, 2));
}

module.exports = { isAlreadySent, markSent };
