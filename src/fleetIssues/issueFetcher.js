const db = require('./db');
const config = require('../config');

/**
 * Fetch issues eligible for this agent to look at: status is one of the
 * configured "open" values (FLEET_ISSUE_OPEN_STATUSES) and it has a vehicle
 * to resolve an FM from. Closed/resolved issues are excluded even if their
 * status string were ever misconfigured into the open list (spec section 4).
 */
async function fetchEligibleIssues() {
  const statusList = config.fleetIssues.openStatuses.map((s) => `"${s}"`).join(',');

  const issues = await db.query('issues', {
    select:
      'id,issue_number,vehicle_number,summary,status,priority_id,reported_at,assignee_id,resolved_at,closed_at',
    filters: { status: `in.(${statusList})` },
  });

  return issues.filter((issue) => issue.vehicle_number && !issue.resolved_at && !issue.closed_at);
}

module.exports = { fetchEligibleIssues };
