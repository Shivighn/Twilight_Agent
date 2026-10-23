// Runs the existing opsOccupancy.py (repo root, NOT scripts/ — its own
// logic/CLI is untouched) as a child process, then sends BOTH the CSV it
// writes and the slot-count PNG it renders to WhatsApp. Reuses the single
// shared WhatsApp connection, same as every other scheduled report here.
//
// Distinct from todayOccupancy: that one covers every operator Redbus
// returns; this one is scoped to just Flix/IntrCity/Zing (opsOccupancy.py's
// own --ops default).

const path = require('path');
const fs = require('fs');
const util = require('util');
const execFile = util.promisify(require('child_process').execFile);
const config = require('../config');
const logger = require('../utils/logger');
const { sendToChat, resolveGroupJidByName } = require('../whatsapp/client');
const { istDateString } = require('../terminal44/dateFormat');

const REPO_ROOT = path.join(__dirname, '..', '..');
const SCRIPT_PATH = path.join(REPO_ROOT, 'opsOccupancy.py');
const RUN_TIMEOUT_MS = 10 * 60 * 1000; // Redbus scraping across ~11 cities/2 days can genuinely take minutes

/**
 * One run: run the python script, find the CSV + PNG it reports writing,
 * send both. Throws (doesn't swallow) on any failure — same convention as
 * the rest of this repo's scheduled reports.
 */
async function runOnce() {
  const dateStr = istDateString();

  logger.info(`[OpsOccupancy] Running ${config.opsOccupancy.pythonBin} opsOccupancy.py (cwd=${REPO_ROOT})`);
  let stdout;
  try {
    const result = await execFile(config.opsOccupancy.pythonBin, [SCRIPT_PATH], {
      cwd: REPO_ROOT,
      timeout: RUN_TIMEOUT_MS,
      maxBuffer: 10 * 1024 * 1024,
    });
    stdout = result.stdout;
  } catch (err) {
    const timedOut = err.killed && err.signal ? ` (killed by timeout after ${RUN_TIMEOUT_MS / 1000}s, signal ${err.signal})` : '';
    throw new Error(
      `[OpsOccupancy] opsOccupancy.py failed${timedOut}:\n--- stdout ---\n${err.stdout || '(empty)'}\n--- stderr ---\n${err.stderr || '(empty)'}\n--- error ---\n${err.message}`
    );
  }
  logger.info(`[OpsOccupancy] Script output:\n${stdout}`);

  // Printed only on a successful write (see opsOccupancy.py's main()); the
  // "nothing fetched" failure path prints a different message and exits
  // non-zero instead (caught above), so this match is never reached then.
  const match = stdout.match(/Wrote (\S+) and (\S+)/);
  if (!match) {
    throw new Error(
      `[OpsOccupancy] Script did not report writing a report (likely rate-limited by Redbus) — not sending. Output:\n${stdout}`
    );
  }
  const [, csvPath, pngPath] = match;
  const csvBuffer = fs.readFileSync(csvPath);
  const pngBuffer = fs.readFileSync(pngPath);

  const { whatsappGroupId } = config.opsOccupancy;
  const jid = await resolveGroupJidByName(whatsappGroupId);
  if (!jid) throw new Error(`[OpsOccupancy] Could not find WhatsApp group "${whatsappGroupId}"`);
  logger.info(`[OpsOccupancy] Resolved WhatsApp group "${whatsappGroupId}" -> ${jid}`);

  const csvResult = await sendToChat(jid, {
    document: csvBuffer,
    fileName: path.basename(csvPath),
    mimetype: 'text/csv',
    caption: `Ops Occupancy (Flix/IntrCity/Zing): ${dateStr}`,
  });
  if (!csvResult.success) throw new Error(`[OpsOccupancy] CSV send failed: ${csvResult.error}`);

  // Separate message, same convention as terminal44's CSV + snapshot image.
  const pngResult = await sendToChat(jid, { image: pngBuffer });
  if (!pngResult.success) throw new Error(`[OpsOccupancy] Image send failed: ${pngResult.error}`);

  logger.info(`[OpsOccupancy] Sent ${path.basename(csvPath)} and ${path.basename(pngPath)} for ${dateStr}`);
  return { dateStr, sent: true };
}

module.exports = { runOnce };
