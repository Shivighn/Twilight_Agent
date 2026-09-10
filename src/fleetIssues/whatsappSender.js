const config = require('../config');
const { sendToChat, resolveGroupJidByName } = require('../whatsapp/client');
const logger = require('../utils/logger');

// A real Baileys JID always ends in one of these — anything else in
// WHATSAPP_GROUP_ID is treated as a display name to resolve at send time.
function looksLikeJid(value) {
  return /@(g\.us|s\.whatsapp\.net)$/.test(value);
}

// Group JIDs don't change — resolve the configured name once, reuse after.
let cachedGroupJid = null;

async function resolveTargetJid() {
  const configured = config.fleetIssues.whatsappGroupId;
  if (looksLikeJid(configured)) return configured;
  if (cachedGroupJid) return cachedGroupJid;

  const jid = await resolveGroupJidByName(configured);
  if (jid) {
    cachedGroupJid = jid;
    logger.info(`[FleetIssues] Resolved WHATSAPP_GROUP_ID "${configured}" -> ${jid}`);
  } else {
    logger.warn(
      `[FleetIssues] Could not find a WhatsApp group named "${configured}" — is the bot's account a member of it?`
    );
  }
  return jid;
}

/**
 * The ONLY place this feature touches WhatsApp — routes through
 * sendToChat() in src/whatsapp/client.js, which reuses the single
 * already-authenticated Baileys socket. No new connection, no new session.
 */
// `content` is either a plain string (FM-assignment messages) or
// { text, mentions } (escalation messages, so a real WhatsApp mention/ping
// reaches the tagged contact instead of inert "@name" text).
async function sendFleetIssueMessage(content) {
  if (!config.fleetIssues.whatsappGroupId) {
    logger.warn('[FleetIssues] WHATSAPP_GROUP_ID not configured — skipping send');
    return { success: false, error: 'group_not_configured' };
  }

  const jid = await resolveTargetJid();
  if (!jid) return { success: false, error: 'group_not_found' };

  const payload = typeof content === 'string' ? { text: content } : content;
  return sendToChat(jid, payload);
}

module.exports = { sendFleetIssueMessage };
