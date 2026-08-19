const config = require('../config');
const { sendToChat } = require('../whatsapp/client');
const logger = require('../utils/logger');

/**
 * The ONLY place this feature touches WhatsApp — routes through
 * sendToChat() in src/whatsapp/client.js, which reuses the single
 * already-authenticated Baileys socket. No new connection, no new session.
 */
async function sendFleetIssueMessage(text) {
  if (!config.fleetIssues.whatsappGroupId) {
    logger.warn('[FleetIssues] WHATSAPP_GROUP_ID not configured — skipping send');
    return { success: false, error: 'group_not_configured' };
  }
  return sendToChat(config.fleetIssues.whatsappGroupId, { text });
}

module.exports = { sendFleetIssueMessage };
