require('dotenv').config();

function requireEnv(key) {
  const val = process.env[key];
  if (!val) throw new Error(`Missing required env var: ${key}`);
  return val;
}

const config = {
  whatsapp: {
    monitoredChats: requireEnv('WA_MONITORED_CHATS')
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean),
  },
  agentService: {
    url: process.env.AGENT_SERVICE_URL || 'http://localhost:8000',
    timeoutMs: parseInt(process.env.AGENT_SERVICE_TIMEOUT_MS || '120000', 10),
  },
  storage: {
    dir: process.env.STORAGE_DIR || './storage',
    retentionDays: parseInt(process.env.STORAGE_RETENTION_DAYS || '3', 10),
  },
  logging: {
    level: process.env.LOG_LEVEL || 'info',
    dir: process.env.LOG_DIR || './logs',
  },
  // Not required via requireEnv(): missing/blank here must not crash the
  // whole gateway (WhatsApp inbound + petty-cash pipeline) — only the
  // fleet-issue feature depends on it, and it checks for itself at run time.
  supabase: {
    url: process.env.SUPABASE_URL || '',
    serviceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY || '',
  },
  // Fleet Issue Auto-Assignment & WhatsApp Escalation Agent — see
  // "inspection tagging agent.txt" (repo root) for the spec this implements.
  // Off by default: a bad/incomplete config here must never start sending
  // real WhatsApp messages until someone deliberately turns it on.
  fleetIssues: {
    enabled: (process.env.FLEET_ISSUE_AGENT_ENABLED || 'false').toLowerCase() === 'true',
    timezone: process.env.AGENT_TIMEZONE || 'Asia/Kolkata',
    runTime: process.env.AGENT_RUN_TIME || '10:00', // HH:mm, interpreted in `timezone`
    tripLookbackDays: parseInt(process.env.TRIP_LOOKBACK_DAYS || '10', 10),
    fmEscalationDays: parseInt(process.env.FM_ESCALATION_DAYS || '2', 10),
    seniorEscalationDays: parseInt(process.env.SENIOR_ESCALATION_DAYS || '5', 10),
    // Which issues.status values are eligible for processing at all.
    openStatuses: (process.env.FLEET_ISSUE_OPEN_STATUSES || 'Open,In_Progress,Reopened')
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean),
    fleetManagers: {
      anudeep: process.env.ANUDEEP_FM_ID || '',
      venky: process.env.VENKY_FM_ID || '',
    },
    // Plain display names for now — NOT Baileys mention JIDs. Swap these for
    // real WhatsApp IDs later and wire them into messageBuilder.js's
    // `mentions` array; until then messages just print the name as text.
    escalationContacts: {
      uday: process.env.UDAY_WHATSAPP_ID || 'Uday',
      siva: process.env.SIVA_WHATSAPP_ID || 'Siva',
      anil: process.env.ANIL_WHATSAPP_ID || 'Anil',
    },
    // Target chat JID for FM-assignment + escalation messages. Blank = agent
    // logs a warning and skips sending (never guesses a chat to post into).
    whatsappGroupId: process.env.WHATSAPP_GROUP_ID || '',
  },
  // Terminal 44 daily history report — posts yesterday's departed-vehicle
  // history (Terminal 44 API) as a CSV to WhatsApp every night.
  // Off by default, same safety rule as fleetIssues above: a bad/incomplete
  // config here must never start sending real WhatsApp messages until
  // someone deliberately turns it on.
  terminal44: {
    enabled: (process.env.TERMINAL44_REPORT_ENABLED || 'false').toLowerCase() === 'true',
    timezone: 'Asia/Kolkata',
    runTime: process.env.TERMINAL44_RUN_TIME || '02:00', // HH:mm, interpreted in `timezone`
    apiBaseUrl: process.env.TERMINAL44_API_BASE_URL || 'https://be.fleetzen.co.in',
    // Target WhatsApp group for the CSV document. Blank = agent logs a
    // warning and skips sending (never guesses a chat to post into).
    whatsappGroupId: process.env.TERMINAL44_WHATSAPP_GROUP_ID || 'Agent Test',
  },
  // MG Fuel Savings daily status post. Off by default, same safety rule as
  // fleetIssues/terminal44 above.
  mgFuelSavings: {
    enabled: (process.env.MG_FUEL_SAVINGS_ENABLED || 'false').toLowerCase() === 'true',
    timezone: 'Asia/Kolkata',
    runTime: process.env.MG_FUEL_SAVINGS_RUN_TIME || '11:00', // HH:mm, interpreted in `timezone`
    apiBaseUrl: process.env.MG_FUEL_SAVINGS_API_BASE_URL || 'https://be.fleetzen.co.in',
    // Dedicated automation account for be.fleetzen.co.in — never hardcoded;
    // real values live only in .env (gitignored).
    credentials: {
      email: process.env.MG_FUEL_SAVINGS_EMAIL || '',
      password: process.env.MG_FUEL_SAVINGS_PASSWORD || '',
    },
    // Target WhatsApp group for the daily status message. Blank = agent
    // logs a warning and skips sending (never guesses a chat to post into).
    whatsappGroupId: process.env.MG_FUEL_SAVINGS_WHATSAPP_GROUP_ID || 'Agent Test',
    // Real phone numbers (country code + number, no "+", spaces or dashes)
    // — messageBuilder.js turns these into real WhatsApp @mentions on both
    // messages. Anil/Uday reuse the same contacts already configured for
    // fleetIssues (ANIL_WHATSAPP_ID / UDAY_WHATSAPP_ID) — same people, no
    // need for duplicate vars.
    contacts: {
      anil: process.env.ANIL_WHATSAPP_ID || 'Anil',
      uday: process.env.UDAY_WHATSAPP_ID || 'Uday',
      balaji: process.env.BALAJI_WHATSAPP_ID || 'Balaji',
      likhith: process.env.LIKHITH_WHATSAPP_ID || 'Likhith',
    },
  },
};

module.exports = config;
