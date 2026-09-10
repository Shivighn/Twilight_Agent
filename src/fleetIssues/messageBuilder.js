const config = require('../config');

/** Raw fleet_manager_id -> human display name, for message text only. */
function fmDisplayName(fleetManagerId) {
  const { fleetManagers } = config.fleetIssues;
  if (fleetManagerId === fleetManagers.anudeep) return 'Anudeep';
  if (fleetManagerId === fleetManagers.venky) return 'Venky';
  return fleetManagerId || 'Unknown FM';
}

// These category labels are already implied by context (it's a WhatsApp
// message about issues) — stripping them off the front of the summary
// avoids repeating "Inspection Item Failed:" / "Driver Complaints:" on
// every single line.
const REDUNDANT_SUMMARY_PREFIXES = [/^Inspection Item Failed:\s*/i, /^Driver Complaints:\s*/i];

function cleanSummary(summary) {
  if (!summary) return summary;
  for (const prefix of REDUNDANT_SUMMARY_PREFIXES) {
    if (prefix.test(summary)) return summary.replace(prefix, '');
  }
  return summary;
}

function normalizeTitle(text) {
  return (text || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

function bigrams(str) {
  const grams = [];
  for (let i = 0; i < str.length - 1; i++) grams.push(str.slice(i, i + 2));
  return grams;
}

// Sørensen-Dice bigram similarity, 0..1. Catches near-matches a plain
// substring check misses — e.g. "Drivers Available" vs "Drivers
// Availability" share almost every bigram despite neither containing the
// other outright.
function titleSimilarity(a, b) {
  if (!a || !b) return 0;
  if (a === b || a.includes(b) || b.includes(a)) return 1;
  const gramsA = bigrams(a);
  const gramsB = bigrams(b);
  if (!gramsA.length || !gramsB.length) return 0;
  const remaining = new Map();
  for (const g of gramsB) remaining.set(g, (remaining.get(g) || 0) + 1);
  let matches = 0;
  for (const g of gramsA) {
    const count = remaining.get(g) || 0;
    if (count > 0) {
      matches += 1;
      remaining.set(g, count - 1);
    }
  }
  return (2 * matches) / (gramsA.length + gramsB.length);
}

const DUPLICATE_TITLE_THRESHOLD = 0.6;

/**
 * Collapse near-duplicate issue titles per vehicle before they go into the
 * FM-assignment message. The same real-world problem often gets logged
 * with slightly different wording across inspections ("Drivers Available"
 * vs "Drivers Availability", four separate "Stephney" entries for one
 * vehicle, etc.) — this merges those into a single line, keeping whichever
 * title is longer/more descriptive. Comparison is scoped to one vehicle:
 * the same title text on two different vehicles is never merged. Position
 * in the output follows the FIRST occurrence of each cluster.
 */
function dedupeIssuesPerVehicle(issues) {
  const clustersByVehicle = new Map(); // vehicle_number -> [{ normalized, best }]
  const kept = []; // cluster entries, in first-seen order

  for (const issue of issues) {
    const vehicle = issue.vehicle_number || '';
    const normalized = normalizeTitle(cleanSummary(issue.summary));

    if (!clustersByVehicle.has(vehicle)) clustersByVehicle.set(vehicle, []);
    const clusters = clustersByVehicle.get(vehicle);

    // Never merge blank/missing summaries into each other — that would
    // hide genuinely distinct issues that just both lack a title.
    const match = normalized
      ? clusters.find((c) => titleSimilarity(c.normalized, normalized) >= DUPLICATE_TITLE_THRESHOLD)
      : null;

    if (!match) {
      const entry = { normalized, best: issue };
      clusters.push(entry);
      kept.push(entry);
      continue;
    }

    const currentTitle = cleanSummary(match.best.summary) || '';
    const newTitle = cleanSummary(issue.summary) || '';
    if (newTitle.length > currentTitle.length) {
      match.best = issue;
      match.normalized = normalized;
    }
  }

  return kept.map((entry) => entry.best);
}

/**
 * "Issues assigned to Anudeep:\n\nTG13T1986 - Driver complaint...\n...\n\ncc @Uday"
 * (spec section 8). Returns { text, mentions } — Uday is cc'd (real
 * WhatsApp mention) on every FM-assignment message too, not just escalations.
 */
function buildFmAssignmentMessage(fmName, issues) {
  const deduped = dedupeIssuesPerVehicle(issues);
  const lines = deduped.map((i) => `${i.vehicle_number || 'Unknown Vehicle'} - ${cleanSummary(i.summary) || 'No summary'}`);
  const udayTag = buildTag(config.fleetIssues.escalationContacts.uday);

  const text = `Issues assigned to ${fmName}:\n\n${lines.join('\n')}\n\ncc ${udayTag.text}`;
  const mentions = udayTag.jid ? [udayTag.jid] : [];
  return { text, mentions };
}

// A real Baileys mention needs the bare-digit phone number (country code +
// number, no "+", spaces or dashes) as both the JID and the "@number" text
// WhatsApp matches it against. escalationContacts may hold either a phone
// number (real tag, pings the person) or a plain name (falls back to inert
// "@Name" text, kept only so a misconfigured contact doesn't crash a run).
function buildTag(raw) {
  const digits = (raw || '').replace(/\D/g, '');
  if (digits) return { text: `@${digits}`, jid: `${digits}@s.whatsapp.net` };
  return { text: raw ? `@${raw}` : '', jid: null };
}

/**
 * Escalation message (spec sections 9-10) — ONE message per level per run,
 * covering every issue that hit that level this run, grouped by vehicle.
 * `level` is 'uday' or 'senior'. `items` is [{ issue, daysUnchanged }, ...].
 * Returns { text, mentions } — pass both straight through to
 * whatsappSender.sendFleetIssueMessage so the tag is a real, notifying
 * WhatsApp mention rather than inert text.
 */
function buildEscalationMessage(level, items) {
  const { uday, siva, anil } = config.fleetIssues.escalationContacts;
  const icon = level === 'senior' ? '🚨' : '⚠️';

  const tags = (level === 'senior' ? [uday, siva, anil] : [uday]).map(buildTag);
  const tag = tags.map((t) => t.text).filter(Boolean).join(' ');
  const mentions = tags.map((t) => t.jid).filter(Boolean);

  // Group by vehicle, preserving first-seen order.
  const byVehicle = new Map();
  for (const item of items) {
    const key = item.issue.vehicle_number || 'Unknown Vehicle';
    if (!byVehicle.has(key)) byVehicle.set(key, []);
    byVehicle.get(key).push(item);
  }

  // Issues can hit the threshold on different days (backdated tests, or
  // just different report dates) — only claim one shared day count in the
  // header when every issue this run actually shares it.
  const firstDays = items[0].daysUnchanged;
  const sameDaysForAll = items.every((i) => i.daysUnchanged === firstDays);
  const daysPhrase = sameDaysForAll ? `*${firstDays} days*` : 'the escalation threshold';

  const sections = [...byVehicle.entries()].map(([vehicle, vehicleItems]) => {
    const bullets = vehicleItems
      .map(({ issue, daysUnchanged }) => {
        const summary = cleanSummary(issue.summary) || 'No summary';
        const suffix = sameDaysForAll ? '' : ` (${daysUnchanged} days)`;
        return `• Issue ${issue.issue_number} – ${summary}${suffix}`;
      })
      .join('\n');
    return `*${vehicle}*\n\n${bullets}`;
  });

  const statuses = [...new Set(items.map((i) => i.issue.status))];
  const statusLine =
    statuses.length === 1
      ? `All issues are currently *${statuses[0]}*. Please look into these.`
      : `Please look into these issues.`;

  const text =
    `${icon} *Issue Escalation*\n\n` +
    `${tag} — The following issues have remained unchanged for ${daysPhrase}:\n\n` +
    `${sections.join('\n\n')}\n\n` +
    statusLine;

  return { text, mentions };
}

module.exports = { fmDisplayName, buildFmAssignmentMessage, buildEscalationMessage };
