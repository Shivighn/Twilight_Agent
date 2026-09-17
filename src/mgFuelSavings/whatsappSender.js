const config = require('../config');
const { sendToChat, resolveGroupJidByName } = require('../whatsapp/client');
const logger = require('../utils/logger');

// A real Baileys JID always ends in one of these — anything else in
// MG_FUEL_SAVINGS_WHATSAPP_GROUP_ID is treated as a display name to
// resolve at send time. Same convention as fleetIssues/whatsappSender.js
// and terminal44/whatsappSender.js.
function looksLikeJid(value) {
  return /@(g\.us|s\.whatsapp\.net)$/.test(value);
}

// Group JIDs don't change — resolve the configured name once, reuse after.
let cachedGroupJid = null;

async function resolveTargetJid() {
  const configured = config.mgFuelSavings.whatsappGroupId;
  if (looksLikeJid(configured)) return configured;
  if (cachedGroupJid) return cachedGroupJid;

  const jid = await resolveGroupJidByName(configured);
  if (jid) {
    cachedGroupJid = jid;
    logger.info(`[MgFuelSavings] Resolved MG_FUEL_SAVINGS_WHATSAPP_GROUP_ID "${configured}" -> ${jid}`);
  } else {
    logger.warn(
      `[MgFuelSavings] Could not find a WhatsApp group named "${configured}" — is the bot's account a member of it?`
    );
  }
  return jid;
}

/**
 * Send the daily status message. `content` is either a plain string (the
 * savings message) or { text, mentions } (the anomaly message, so its
 * @tags are real, notifying WhatsApp mentions rather than inert text).
 * Routes through sendToChat() in src/whatsapp/client.js — the SAME
 * already-authenticated Baileys socket every other feature in this repo
 * uses. No new connection, no new session.
 */
async function sendMgFuelSavingsMessage(content) {
  if (!config.mgFuelSavings.whatsappGroupId) {
    logger.warn('[MgFuelSavings] MG_FUEL_SAVINGS_WHATSAPP_GROUP_ID not configured — skipping send');
    return { success: false, error: 'group_not_configured' };
  }

  const jid = await resolveTargetJid();
  if (!jid) return { success: false, error: 'group_not_found' };

  const payload = typeof content === 'string' ? { text: content } : content;
  const result = await sendToChat(jid, payload);
  if (result.success) logger.info(`[MgFuelSavings] Sent — message id ${result.id}`);
  else logger.error(`[MgFuelSavings] Send failed: ${result.error}`);
  return result;
}

module.exports = { sendMgFuelSavingsMessage };
