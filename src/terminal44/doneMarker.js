// The idempotency guard for this job — mirrors the check-before-act /
// update-only-after-confirmed-send idiom in fleetIssues/notificationTracker.js
// (there it's a DB row; a single daily report has no per-item state to
// track, so a small persisted marker file is the minimal equivalent).
// Whatever date this file names has already been sent — a retry or a
// second cron fire for the same day must NOT send twice.
//
// Each operator's report keeps its own marker (`name`) so one operator's
// send never suppresses another's. Default name keeps the original
// last_sent.json path, so the IntrCity report is unaffected.

const fs = require('fs');
const path = require('path');
const config = require('../config');
const logger = require('../utils/logger');

function markerPath(name = 'last_sent') {
  return path.join(config.storage.dir, 'terminal44', `${name}.json`);
}

function readMarker(name) {
  try {
    return JSON.parse(fs.readFileSync(markerPath(name), 'utf8'));
  } catch (err) {
    if (err.code === 'ENOENT') return null; // never sent before — not an error
    logger.warn(`[Terminal44] Could not read done-marker (${err.message}) — treating as not-yet-sent`);
    return null;
  }
}

/** Has the report for `dateStr` (YYYY-MM-DD) already been sent successfully? */
function isAlreadySent(dateStr, name) {
  const marker = readMarker(name);
  return !!marker && marker.date === dateStr;
}

/** Record that `dateStr`'s report was sent — call ONLY after a confirmed successful send. */
function markSent(dateStr, name) {
  const file = markerPath(name);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify({ date: dateStr, sentAt: new Date().toISOString() }, null, 2));
}

module.exports = { isAlreadySent, markSent };
