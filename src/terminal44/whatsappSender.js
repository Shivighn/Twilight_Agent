const config = require('../config');
const { sendToChat, resolveGroupJidByName } = require('../whatsapp/client');
const logger = require('../utils/logger');

// A real Baileys JID always ends in one of these — anything else configured
// as a group is treated as a display name to resolve at send time. Same
// convention as fleetIssues/whatsappSender.js.
function looksLikeJid(value) {
  return /@(g\.us|s\.whatsapp\.net)$/.test(value);
}

// Group JIDs don't change — resolve each configured name once, reuse after.
const cachedGroupJids = new Map();

async function resolveTargetJid(configured) {
  if (looksLikeJid(configured)) return configured;
  if (cachedGroupJids.has(configured)) return cachedGroupJids.get(configured);

  const jid = await resolveGroupJidByName(configured);
  if (jid) {
    cachedGroupJids.set(configured, jid);
    logger.info(`[Terminal44] Resolved WhatsApp group "${configured}" -> ${jid}`);
  } else {
    logger.warn(
      `[Terminal44] Could not find a WhatsApp group named "${configured}" — is the bot's account a member of it?`
    );
  }
  return jid;
}

/**
 * Routes through sendToChat() in src/whatsapp/client.js — the SAME
 * already-authenticated Baileys socket every other feature in this repo
 * uses. No new connection, no new session.
 */
async function sendTo(groupId, content, describe) {
  if (!groupId) {
    logger.warn('[Terminal44] WhatsApp group not configured — skipping send');
    return { success: false, error: 'group_not_configured' };
  }

  const jid = await resolveTargetJid(groupId);
  if (!jid) return { success: false, error: 'group_not_found' };

  logger.info(`[Terminal44] Sending ${describe} to ${jid}`);
  const result = await sendToChat(jid, content);

  if (result.success) logger.info(`[Terminal44] Sent ${describe} — message id ${result.id}`);
  else logger.error(`[Terminal44] Send failed for ${describe}: ${result.error}`);

  return result;
}

/** Send the CSV as a WhatsApp document (`groupId` defaults to the IntrCity report's group). */
function sendCsvDocument(buffer, fileName, caption, groupId = config.terminal44.whatsappGroupId) {
  return sendTo(
    groupId,
    { document: buffer, fileName, mimetype: 'text/csv', caption },
    `"${fileName}" (${buffer.length} bytes)`
  );
}

/** Send a PNG as a WhatsApp image. */
function sendImage(buffer, groupId = config.terminal44.whatsappGroupId) {
  return sendTo(groupId, { image: buffer }, `snapshot image (${buffer.length} bytes)`);
}

module.exports = { sendCsvDocument, sendImage };
