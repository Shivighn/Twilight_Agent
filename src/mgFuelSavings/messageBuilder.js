const config = require('../config');

const MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

// "15-Sep-26" in Asia/Kolkata, no leading zero on the day — India has no
// DST, so a fixed +5:30 read via Intl is correct and simple. Same approach
// as terminal44/dateFormat.js.
function formatTodayIST(date = new Date()) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Kolkata',
    year: '2-digit',
    month: 'numeric',
    day: 'numeric',
  }).formatToParts(date);
  const map = {};
  for (const p of parts) map[p.type] = p.value;
  return `${map.day}-${MONTH_ABBR[Number(map.month) - 1]}-${map.year}`;
}

// A real Baileys mention needs the bare-digit phone number as both the JID
// and the "@number" text WhatsApp matches it against — same convention as
// fleetIssues/messageBuilder.js. Falls back to inert "@Name" text if a
// contact isn't configured with a real number yet.
function buildTag(raw) {
  const digits = (raw || '').replace(/\D/g, '');
  if (digits) return { text: `@${digits}`, jid: `${digits}@s.whatsapp.net` };
  return { text: raw ? `@${raw}` : '', jid: null };
}

/** Builds { text, mentions } for a name-ordered list of contacts, tag line only. */
function buildTagLine(names) {
  const { contacts } = config.mgFuelSavings;
  const tags = names.map((name) => buildTag(contacts[name]));
  return {
    tagLine: tags.map((t) => t.text).filter(Boolean).join(', '),
    mentions: tags.map((t) => t.jid).filter(Boolean),
  };
}

/**
 * "MG Fuel Savings- 3 anomalies detected, sort it to get correct savings
 *
 * @<likhith>, @<balaji>, @<anil>"
 * Returns { text, mentions } — tags Likhith, Balaji, and Anil with real
 * WhatsApp mentions (pings them even if the group is muted), not inert text.
 */
function buildAnomalyMessage(count) {
  const { tagLine, mentions } = buildTagLine(['likhith', 'balaji', 'anil']);
  const text = `MG Fuel Savings- ${count} anomalies detected, sort it to get correct savings\n\n${tagLine}`;
  return { text, mentions };
}

/**
 * "MG Fuel Savings as of 15-Sep-26: 3,12,779
 *
 * @<anil>, @<uday>, @<siva>"
 * Returns { text, mentions } — tags Anil, Uday, and Siva with real
 * WhatsApp mentions. (Indian lakh/crore grouping on the amount.)
 */
function buildSavingsMessage(totalSavings) {
  const amount = Math.round(totalSavings).toLocaleString('en-IN');
  const { tagLine, mentions } = buildTagLine(['anil', 'uday', 'siva']);
  const text = `MG Fuel Savings as of ${formatTodayIST()}: ${amount}\n\n${tagLine}`;
  return { text, mentions };
}

module.exports = { buildAnomalyMessage, buildSavingsMessage };
