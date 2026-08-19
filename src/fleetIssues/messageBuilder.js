const config = require('../config');

/** Raw fleet_manager_id -> human display name, for message text only. */
function fmDisplayName(fleetManagerId) {
  const { fleetManagers } = config.fleetIssues;
  if (fleetManagerId === fleetManagers.anudeep) return 'Anudeep';
  if (fleetManagerId === fleetManagers.venky) return 'Venky';
  return fleetManagerId || 'Unknown FM';
}

/** "Issues assigned to Anudeep:\n\n7896 - Driver complaint...\n..." (spec section 8). */
function buildFmAssignmentMessage(fmName, issues) {
  const lines = issues.map((i) => `${i.issue_number} - ${i.summary || 'No summary'}`);
  return `Issues assigned to ${fmName}:\n\n${lines.join('\n')}`;
}

/**
 * Escalation message (spec sections 9-10). `level` is 'uday' or 'senior'.
 *
 * NOTE: escalationContacts are plain display names for now, not Baileys
 * mention JIDs (the user asked to defer real @mentions) — the "@Name" here
 * is literal text. To wire in real WhatsApp mentions later: build a
 * `mentions: [jid, ...]` array from config and pass it alongside `text` to
 * whatsappSender.sendFleetIssueMessage (see src/whatsapp/client.js
 * sendToChat, which already forwards any Baileys message-content object).
 */
function buildEscalationMessage({ level, issue, daysUnchanged }) {
  const { uday, siva, anil } = config.fleetIssues.escalationContacts;
  const icon = level === 'senior' ? '🚨' : '⚠️';
  const tag = level === 'senior' ? `@${uday} @${siva} @${anil}` : `@${uday}`;

  return (
    `${icon} Issue Escalation\n\n` +
    `Issue ${issue.issue_number} - ${issue.summary || 'No summary'}\n` +
    `Vehicle: ${issue.vehicle_number}\n` +
    `Status: ${issue.status}\n\n` +
    `This issue has remained unchanged for ${daysUnchanged} days.\n\n` +
    `${tag}`
  );
}

module.exports = { fmDisplayName, buildFmAssignmentMessage, buildEscalationMessage };
