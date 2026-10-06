// Runs the existing scripts/todayOccupancy.py (Redbus occupancy/ASP report)
// as a child process — its own logic/CLI is NOT touched here — then sends
// the CSV it writes to WhatsApp. Reuses the single shared WhatsApp
// connection, same as every other scheduled report in this repo.
//
// "todaysbuses expectancy.txt" is now built fresh every run (see
// expectancyBuilder.js) instead of needing to be hand-prepared — this
// fully automates what used to be a manual FleetZen/admin + Supabase
// lookup step.

const path = require('path');
const fs = require('fs');
const util = require('util');
const execFile = util.promisify(require('child_process').execFile);
const config = require('../config');
const logger = require('../utils/logger');
const { sendToChat, resolveGroupJidByName } = require('../whatsapp/client');
const { istDateString } = require('../terminal44/dateFormat');
const { buildExpectancyList } = require('./expectancyBuilder');

const SCRIPTS_DIR = path.join(__dirname, '..', '..', 'scripts');
const EXPECTANCY_FILE = path.join(SCRIPTS_DIR, 'todaysbuses expectancy.txt'); // exact name scripts/todayOccupancy.py reads — do not change
const RUN_TIMEOUT_MS = 10 * 60 * 1000; // Redbus scraping across ~11 cities/2 days can genuinely take minutes

/**
 * One run: build the expectancy file, run the python script, find the CSV
 * it reports writing, send it. Throws (doesn't swallow) on any failure —
 * same convention as the rest of this repo's scheduled reports.
 */
async function runOnce() {
  const dateStr = istDateString();

  const expectancyList = await buildExpectancyList();
  fs.writeFileSync(EXPECTANCY_FILE, JSON.stringify(expectancyList, null, 2), 'utf8');
  logger.info(`[TodayOccupancy] Wrote ${expectancyList.length} bus(es) to "${path.basename(EXPECTANCY_FILE)}"`);

  logger.info(`[TodayOccupancy] Running ${config.todayOccupancy.pythonBin} todayOccupancy.py (cwd=${SCRIPTS_DIR})`);
  let stdout;
  try {
    const result = await execFile(config.todayOccupancy.pythonBin, ['todayOccupancy.py'], {
      cwd: SCRIPTS_DIR,
      timeout: RUN_TIMEOUT_MS,
      maxBuffer: 10 * 1024 * 1024,
    });
    stdout = result.stdout;
  } catch (err) {
    // Show everything — stdout alone was hiding the actual cause (a Python
    // traceback or a timeout kill both land in stderr/err.message, not
    // stdout, and stdout usually isn't empty by the time something fails).
    const timedOut = err.killed && err.signal ? ` (killed by timeout after ${RUN_TIMEOUT_MS / 1000}s, signal ${err.signal})` : '';
    throw new Error(
      `[TodayOccupancy] todayOccupancy.py failed${timedOut}:\n--- stdout ---\n${err.stdout || '(empty)'}\n--- stderr ---\n${err.stderr || '(empty)'}\n--- error ---\n${err.message}`
    );
  }
  logger.info(`[TodayOccupancy] Script output:\n${stdout}`);

  // The script prints this exact line only on a successful write — parsing
  // it (rather than assuming a fixed filename) handles its own fallback
  // naming (a timestamped name if the usual file was locked) and, more
  // importantly, the "nothing fetched" failure path, where it prints a
  // different message and does NOT write a fresh file at all.
  const match = stdout.match(/YOUR BUSES -> (\S+)/);
  if (!match) {
    throw new Error(
      `[TodayOccupancy] Script did not report writing a CSV (likely rate-limited by Redbus) — not sending. Output:\n${stdout}`
    );
  }
  const csvPath = path.join(SCRIPTS_DIR, match[1]);
  const csvBuffer = fs.readFileSync(csvPath);

  const { whatsappGroupId } = config.todayOccupancy;
  const jid = await resolveGroupJidByName(whatsappGroupId);
  if (!jid) throw new Error(`[TodayOccupancy] Could not find WhatsApp group "${whatsappGroupId}"`);

  const result = await sendToChat(jid, {
    document: csvBuffer,
    fileName: path.basename(csvPath),
    mimetype: 'text/csv',
    caption: `Today's Expected Occupancy & ASP: ${dateStr}`,
  });
  if (!result.success) throw new Error(`[TodayOccupancy] Send failed: ${result.error}`);

  logger.info(`[TodayOccupancy] Sent ${path.basename(csvPath)} for ${dateStr}`);
  return { dateStr, sent: true };
}

module.exports = { runOnce };
