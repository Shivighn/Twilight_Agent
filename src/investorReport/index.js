const axios = require('axios');
const config = require('../config');
const logger = require('../utils/logger');
const { sendToChat, resolveGroupJidByName } = require('../whatsapp/client');

// RFC 4180: quote a field if it contains a comma, quote, or newline.
function csvField(value) {
  const s = value === null || value === undefined ? '' : String(value);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

const MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const DAY_MS = 24 * 60 * 60 * 1000;

/** "14 Sep - 20 Sep" — last week's Monday-Sunday, matching the SQL's date_trunc('week', ...) window. Recomputed every call. */
function lastWeekRangeIST(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Kolkata',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(now);
  const map = {};
  for (const p of parts) map[p.type] = p.value;

  const todayUTC = Date.UTC(Number(map.year), Number(map.month) - 1, Number(map.day));
  const isoWeekday = new Date(todayUTC).getUTCDay() || 7; // Sun=0 -> 7, Mon=1..Sat=6
  const thisMondayUTC = todayUTC - (isoWeekday - 1) * DAY_MS;
  const lastMonday = new Date(thisMondayUTC - 7 * DAY_MS);
  const lastSunday = new Date(thisMondayUTC - 1 * DAY_MS);

  const fmt = (d) => `${d.getUTCDate()} ${MONTH_ABBR[d.getUTCMonth()]}`;
  return `${fmt(lastMonday)} - ${fmt(lastSunday)}`;
}

/** One weekly run: RPC the report, build a CSV, send it to WhatsApp. Throws (doesn't swallow) on any failure — better to skip than post nothing/wrong. */
async function runOnce() {
  const { supabaseUrl, supabaseServiceRoleKey, whatsappGroupId } = config.investorReport;
  if (!supabaseUrl || !supabaseServiceRoleKey) {
    throw new Error('[InvestorReport] INVESTOR_SUPABASE_URL / INVESTOR_SUPABASE_SERVICE_ROLE_KEY not set');
  }

  logger.info('[InvestorReport] Fetching weekly_investor_report()');
  const { data: rows } = await axios.post(
    `${supabaseUrl}/rest/v1/rpc/weekly_investor_report`,
    {},
    { headers: { apikey: supabaseServiceRoleKey, Authorization: `Bearer ${supabaseServiceRoleKey}` } }
  );
  logger.info(`[InvestorReport] ${rows.length} investment(s) this week`);

  const headers = ['Investor Name', 'Pool Name', 'Invested Amount', 'Investment Date'];
  const lines = [headers.map(csvField).join(',')];
  for (const r of rows) {
    lines.push(
      [r.investor_name, r.pool_name, r.invested_amount, r.investment_date].map(csvField).join(',')
    );
  }
  const csv = lines.join('\n');

  if (!whatsappGroupId) {
    throw new Error('[InvestorReport] INVESTOR_REPORT_WHATSAPP_GROUP_ID not configured — skipping send');
  }
  const jid = await resolveGroupJidByName(whatsappGroupId);
  if (!jid) throw new Error(`[InvestorReport] Could not find WhatsApp group "${whatsappGroupId}"`);

  const fileName = `weekly_investor_report_${new Date().toISOString().slice(0, 10)}.csv`;
  const result = await sendToChat(jid, {
    document: Buffer.from(csv, 'utf8'),
    fileName,
    mimetype: 'text/csv',
    caption: `Weekly Investment Report from ${lastWeekRangeIST()}`,
  });
  if (!result.success) throw new Error(`[InvestorReport] Send failed: ${result.error}`);

  logger.info('[InvestorReport] Sent');
  return { rowCount: rows.length };
}

module.exports = { runOnce };
