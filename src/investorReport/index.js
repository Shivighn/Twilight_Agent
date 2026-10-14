const axios = require('axios');
const config = require('../config');
const logger = require('../utils/logger');
const { sendToChat, resolveGroupJidByName } = require('../whatsapp/client');
const { buildTableImage } = require('../utils/tableImage');

// RFC 4180: quote a field if it contains a comma, quote, or newline.
function csvField(value) {
  const s = value === null || value === undefined ? '' : String(value);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

const MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const DAY_MS = 24 * 60 * 60 * 1000;

/** "2026-09-30" (Postgres date, from the RPC) -> "30 Sep 2026". */
function formatInvestmentDate(isoDate) {
  if (!isoDate) return '';
  const [y, m, d] = isoDate.split('-').map(Number);
  return `${d} ${MONTH_ABBR[m - 1]} ${y}`;
}

// Excel auto-detects a cell that LOOKS like a date and reformats it to its
// own locale short-date display (e.g. "30 Sep 2026" -> "20-09-26") — same
// issue already solved for Service IDs in terminal44/csvBuilder.js. Force
// it to stay literal text with the standard ="..." trick; only for the CSV
// — the snapshot image renders the text directly, so it never needs this.
function excelTextForce(value) {
  if (value === null || value === undefined || value === '') return '';
  return `="${String(value).replace(/"/g, '""')}"`;
}

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

  const headers = ['Investment Date', 'Invested Amount', 'Investor Name', 'Pool Name'];
  const lines = [headers.map(csvField).join(',')];
  for (const r of rows) {
    lines.push(
      [excelTextForce(formatInvestmentDate(r.investment_date)), r.invested_amount, r.investor_name, r.pool_name]
        .map(csvField)
        .join(',')
    );
  }
  const csv = lines.join('\n');

  if (!whatsappGroupId) {
    throw new Error('[InvestorReport] INVESTOR_REPORT_WHATSAPP_GROUP_ID not configured — skipping send');
  }
  const jid = await resolveGroupJidByName(whatsappGroupId);
  if (!jid) throw new Error(`[InvestorReport] Could not find WhatsApp group "${whatsappGroupId}"`);

  // Nothing to attach: say so in words instead of sending a header-only CSV.
  if (rows.length === 0) {
    const empty = await sendToChat(jid, { text: `We had 0 investments from ${lastWeekRangeIST()}` });
    if (!empty.success) throw new Error(`[InvestorReport] Send failed: ${empty.error}`);
    logger.info('[InvestorReport] No investments last week — sent the zero-investments message');
    return { rowCount: 0 };
  }

  const fileName = `weekly_investor_report_${new Date().toISOString().slice(0, 10)}.csv`;
  const result = await sendToChat(jid, {
    document: Buffer.from(csv, 'utf8'),
    fileName,
    mimetype: 'text/csv',
    caption: `Weekly Investment Report from ${lastWeekRangeIST()}`,
  });
  if (!result.success) throw new Error(`[InvestorReport] Send failed: ${result.error}`);
  logger.info('[InvestorReport] CSV sent');

  // Snapshot image so people who won't open the CSV can still see the data
  // at a glance. Sent as a second message, same group — CSV stays as-is.
  const imageBuffer = await buildTableImage(
    headers,
    rows.map((r) => [formatInvestmentDate(r.investment_date), r.invested_amount, r.investor_name, r.pool_name])
  );
  const imageResult = await sendToChat(jid, { image: imageBuffer });
  if (!imageResult.success) throw new Error(`[InvestorReport] Snapshot image send failed: ${imageResult.error}`);
  logger.info('[InvestorReport] Snapshot image sent');

  return { rowCount: rows.length };
}

module.exports = { runOnce };
