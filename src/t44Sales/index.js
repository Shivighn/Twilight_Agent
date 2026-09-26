const axios = require('axios');
const config = require('../config');
const logger = require('../utils/logger');
const { sendToChat, resolveGroupJidByName } = require('../whatsapp/client');

const MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "2026-09-25" for yesterday, IST. */
function yesterdayIST() {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Kolkata',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date());
  const map = {};
  for (const p of parts) map[p.type] = p.value;
  const todayUTC = Date.UTC(Number(map.year), Number(map.month) - 1, Number(map.day));
  return new Date(todayUTC - 86400000).toISOString().slice(0, 10);
}

/** "2026-09-25" -> "25 Sep" */
function formatDisplay(apiDate) {
  const [, m, d] = apiDate.split('-').map(Number);
  return `${d} ${MONTH_ABBR[m - 1]}`;
}

/**
 * One daily run: fetch T44 total sales from Petpooja, send to WhatsApp.
 * `dateOverride` ("YYYY-MM-DD") is for manual ad-hoc testing of a specific
 * day only — the real daily cron always calls this with no argument, so it
 * always uses yesterday. Throws (doesn't swallow) on failure.
 */
async function runOnce(dateOverride) {
  const { cookie, restaurantIds, whatsappGroupId } = config.t44Sales;
  // ponytail: this cookie is a real browser session (OTP login, no password to
  // automate) — it WILL expire eventually with no way to auto-refresh. When
  // this starts failing, re-paste a fresh PETPOOJA_COOKIE in .env.
  if (!cookie) throw new Error('[T44Sales] PETPOOJA_COOKIE not set');

  const apiDate = dateOverride || yesterdayIST();
  const display = formatDisplay(apiDate);
  logger.info(`[T44Sales] Fetching sales for ${apiDate}`);

  const res = await axios.post(
    'https://billing.petpooja.com/users/load_sales_statistics/',
    new URLSearchParams({ from_date: apiDate, to_date: apiDate, all_restaurants: restaurantIds }).toString(),
    {
      headers: {
        Cookie: cookie,
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-Requested-With': 'XMLHttpRequest',
      },
      validateStatus: () => true,
    }
  );

  if (res.status !== 200) {
    throw new Error(`[T44Sales] Fetch failed — HTTP ${res.status} ${JSON.stringify(res.data)}`);
  }
  const totalSalesRaw = res.data?.Statistics_data?.total_sales;
  if (totalSalesRaw === undefined) {
    throw new Error(`[T44Sales] Unexpected response shape: ${JSON.stringify(res.data)}`);
  }
  const totalSales = totalSalesRaw.replace(/\.\d+$/, ''); // "80,671.00" -> "80,671"
  logger.info(`[T44Sales] Total sales as per Petpooja for ${apiDate}: ${totalSales}`);

  if (!whatsappGroupId) throw new Error('[T44Sales] T44_SALES_WHATSAPP_GROUP_ID not configured');
  const jid = await resolveGroupJidByName(whatsappGroupId);
  if (!jid) throw new Error(`[T44Sales] Could not find WhatsApp group "${whatsappGroupId}"`);

  const text = `T-44 Total Sales of ${display} = ${totalSales}`;
  const result = await sendToChat(jid, { text });
  if (!result.success) throw new Error(`[T44Sales] Send failed: ${result.error}`);

  logger.info('[T44Sales] Sent');
  return { apiDate, totalSales };
}

module.exports = { runOnce };
