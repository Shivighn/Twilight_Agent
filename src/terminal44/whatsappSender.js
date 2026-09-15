const config = require('../config');
const { sendToChat, resolveGroupJidByName } = require('../whatsapp/client');
const logger = require('../utils/logger');

// A real Baileys JID always ends in one of these — anything else in
// TERMINAL44_WHATSAPP_GROUP_ID is treated as a display name to resolve at
// send time. Same convention as fleetIssues/whatsappSender.js.
function looksLikeJid(value) {
  return /@(g\.us|s\.whatsapp\.net)$/.test(value);
}

// Group JIDs don't change — resolve the configured name once, reuse after.
let cachedGroupJid = null;

async function resolveTargetJid() {
  const configured = config.terminal44.whatsappGroupId;
  if (looksLikeJid(configured)) return configured;
  if (cachedGroupJid) return cachedGroupJid;

  const jid = await resolveGroupJidByName(configured);
  if (jid) {
    cachedGroupJid = jid;
    logger.info(`[Terminal44] Resolved TERMINAL44_WHATSAPP_GROUP_ID "${configured}" -> ${jid}`);
  } else {
    logger.warn(
      `[Terminal44] Could not find a WhatsApp group named "${configured}" — is the bot's account a member of it?`
    );
  }
  return jid;
}

/**
 * Send the CSV as a WhatsApp document. Routes through sendToChat() in
 * src/whatsapp/client.js — the SAME already-authenticated Baileys socket
 * every other feature in this repo uses. No new connection, no new session.
 */

async function sendCsvDocument(buffer, fileName, caption) {
  if (!config.terminal44.whatsappGroupId) {
    const msg = '[Terminal44] TERMINAL44_WHATSAPP_GROUP_ID not configured — skipping send';
    logger.warn(msg);
    return { success: false, error: 'group_not_configured' };
  }

  const jid = await resolveTargetJid();
  if (!jid) return { success: false, error: 'group_not_found' };

  logger.info(`[Terminal44] Sending "${fileName}" (${buffer.length} bytes) to ${jid}`);
  const result = await sendToChat(jid, {
    document: buffer,
    fileName,
    mimetype: 'text/csv',
    caption,
  });

  if (result.success) logger.info(`[Terminal44] Sent "${fileName}" — message id ${result.id}`);
  else logger.error(`[Terminal44] Send failed for "${fileName}": ${result.error}`);

  return result;
}

module.exports = { sendCsvDocument };
