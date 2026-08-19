const db = require('./db');

const TABLE = 'fleet_issue_notifications';

/**
 * The idempotency guard for the whole agent: one row per issue, unique on
 * issue_id (see migrations/2026-08-12_fleet_issue_agent.sql). Running the
 * daily job twice — or two overlapping runs — can never produce a duplicate
 * "first-time" notification, because both would upsert the same row.
 */

async function getByIssueId(issueId) {
  const rows = await db.query(TABLE, { filters: { issue_id: `eq.${issueId}` }, limit: 1 });
  return rows[0] || null;
}

/** Create (or fully replace) the tracking row for an issue seen for the first time. */
async function upsertTracking(row) {
  return db.upsert(TABLE, { ...row, updated_at: new Date().toISOString() }, 'issue_id');
}

/** Patch fields on an existing tracking row (status change, notification/delivery state). */
async function updateTracking(issueId, patch) {
  return db.update(TABLE, { issue_id: `eq.${issueId}` }, { ...patch, updated_at: new Date().toISOString() });
}

module.exports = { getByIssueId, upsertTracking, updateTracking };
