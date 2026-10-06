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
    // Same report, filtered to the Flix operator instead of IntrCity, sent
    // to its own group with a snapshot image of the CSV. Own enable flag so
    // it can be switched on/off independently. Off by default.
    flix: {
      enabled: (process.env.TERMINAL44_FLIX_ENABLED || 'false').toLowerCase() === 'true',
      runTime: process.env.TERMINAL44_FLIX_RUN_TIME || '02:35', // HH:mm, interpreted in `timezone`
      whatsappGroupId: process.env.TERMINAL44_FLIX_WHATSAPP_GROUP_ID || 'Agent Test',
    },
  },
  // MG Fuel Savings daily status post. Off by default, same safety rule as
  // fleetIssues/terminal44 above.
  mgFuelSavings: {
    enabled: (process.env.MG_FUEL_SAVINGS_ENABLED || 'false').toLowerCase() === 'true',
    timezone: 'Asia/Kolkata',
    runTime: process.env.MG_FUEL_SAVINGS_RUN_TIME || '10:00', // HH:mm, interpreted in `timezone`
    // Only actually sends if the 10 AM run found >=1 anomaly (see
    // mgFuelSavings/index.js runAfternoon / morningResultStore.js).
    afternoonRunTime: process.env.MG_FUEL_SAVINGS_AFTERNOON_RUN_TIME || '16:00',
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
      siva: process.env.SIVA_WHATSAPP_ID || 'Siva',
      balaji: process.env.BALAJI_WHATSAPP_ID || 'Balaji',
      likhith: process.env.LIKHITH_WHATSAPP_ID || 'Likhith',
    },
  },
  // Weekly investor-investments report — calls a wrapping SQL function
  // (public.weekly_investor_report(), applied directly in the
  // InvestorProject Supabase — see migration "weekly_investor_report_fn")
  // that runs the exact query as given, via RPC. Different Supabase
  // project from `supabase` above, hence its own URL/key.
  investorReport: {
    enabled: (process.env.INVESTOR_REPORT_ENABLED || 'false').toLowerCase() === 'true',
    timezone: 'Asia/Kolkata',
    runTime: process.env.INVESTOR_REPORT_RUN_TIME || '14:00', // HH:mm Monday, interpreted in `timezone`
    supabaseUrl: process.env.INVESTOR_SUPABASE_URL || '',
    supabaseServiceRoleKey: process.env.INVESTOR_SUPABASE_SERVICE_ROLE_KEY || '',
    whatsappGroupId: process.env.INVESTOR_REPORT_WHATSAPP_GROUP_ID || 'Agent Test',
  },
  // T44 daily sales post — Petpooja billing dashboard has no API-key auth
  // for this account, so this reuses a real logged-in browser session
  // cookie (OTP login, no password available) pasted into PETPOOJA_COOKIE.
  // No way to auto-refresh it — re-paste when it expires.
  t44Sales: {
    enabled: (process.env.T44_SALES_ENABLED || 'false').toLowerCase() === 'true',
    timezone: 'Asia/Kolkata',
    runTime: process.env.T44_SALES_RUN_TIME || '09:00', // HH:mm, interpreted in `timezone`
    cookie: process.env.PETPOOJA_COOKIE || '',
    restaurantIds: process.env.PETPOOJA_RESTAURANT_IDS || '457540,462523',
    whatsappGroupId: process.env.T44_SALES_WHATSAPP_GROUP_ID || 'Agent Test',
  },
  // T44 bus-bay report — calls a wrapping SQL function
  // (public.t44_bus_bay_report(p_from, p_to)) via RPC on the SAME FleetZen
  // Supabase project as `supabase` above (that's where terminal_* live) —
  // reuses supabase.url/serviceRoleKey directly, no separate credentials.
  t44Buses: {
    enabled: (process.env.T44_BUSES_ENABLED || 'false').toLowerCase() === 'true',
    timezone: 'Asia/Kolkata',
    runTime: process.env.T44_BUSES_RUN_TIME || '05:00', // HH:mm, interpreted in `timezone`
    whatsappGroupId: process.env.T44_BUSES_WHATSAPP_GROUP_ID || 'Agent Test',
  },
  // Daily occupancy/ASP report — builds scripts/"todaysbuses expectancy.txt"
  // automatically (missedBusesUrl for the bus numbers, then a Supabase RPC
  // for each one's Operator/Service Number/Route/Last Check In — see
  // src/todayOccupancy/expectancyBuilder.js), then runs the existing
  // scripts/todayOccupancy.py as a child process (its own logic is
  // untouched) and sends the CSV it writes.
  todayOccupancy: {
    enabled: (process.env.TODAY_OCCUPANCY_ENABLED || 'false').toLowerCase() === 'true',
    timezone: 'Asia/Kolkata',
    runTime: process.env.TODAY_OCCUPANCY_RUN_TIME || '18:00', // HH:mm, interpreted in `timezone`
    pythonBin: process.env.TODAY_OCCUPANCY_PYTHON_BIN || 'python3',
    whatsappGroupId: process.env.TODAY_OCCUPANCY_WHATSAPP_GROUP_ID || 'Agent Test',
    // The admin app's endpoint for which bus numbers to look up. "localhost"
    // only works if that admin app runs on the SAME machine as this
    // gateway process — true today (local testing); re-check this once
    // the job moves to the VPS, where that admin app may not be reachable
    // at this address (or may not be running there at all).
    missedBusesUrl: process.env.TODAY_OCCUPANCY_MISSED_BUSES_URL || 'http://localhost:3000/terminal44/missed-buses?days=4',
  },
};

module.exports = config;
