const logger = require('../utils/logger');
const { formatDateDMMMYY, formatTimeAMPM } = require('./dateFormat');

const CSV_HEADERS = ['Date', 'Vehicle Number', 'Service ID', 'Operator', 'Arrival', 'Departure'];

// Canonical Indian plate: 2 letters (state) + 2 digits (district) +
// 2 letters (series) + 4 digits (number) = 10 alnum chars once separators
// are stripped. Only reformat an exact match — anything else (older 1-digit
// district codes, 1-letter series, bad data, etc.) is left as-is rather
// than guessed at.
const PLATE_RE = /^([A-Z]{2})(\d{2})([A-Z]{2})(\d{4})$/;

function formatVehicleNumber(raw) {
  if (!raw) return raw || '';
  const stripped = raw.replace(/[\s-]/g, '').toUpperCase();
  const match = PLATE_RE.exec(stripped);
  if (!match) return raw;
  const [, state, district, series, number] = match;
  return `${state} ${district} ${series} ${number}`;
}

// Minimal CSV field escaping (RFC 4180): quote a field if it contains a
// comma, quote, or newline; double up any embedded quotes.
function csvField(value) {
  const s = value === null || value === undefined ? '' : String(value);
  if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

// Excel (and Google Sheets) auto-detects plain CSV cells that look
// numeric and strips leading zeros — "000"/"001"/"010" would silently
// become "0"/"1"/"10". Service IDs are opaque codes, not numbers, so force
// Excel to keep them as text with the standard ="..." formula trick: Excel
// evaluates it to the literal string, leading zeros intact, no visible "=".
function excelTextForce(value) {
  if (value === null || value === undefined || value === '') return '';
  return `="${String(value).replace(/"/g, '""')}"`;
}

/** Build the CSV string for the given (already departed + IntrCity-filtered) rows. */
function buildCsv(rows) {
  logger.info(`[Terminal44] Building CSV for ${rows.length} row(s)`);

  const lines = [CSV_HEADERS.map(csvField).join(',')];
  for (const row of rows) {
    const fields = [
      formatDateDMMMYY(row.scheduled_arrival),
      formatVehicleNumber(row.bus_number),
      excelTextForce(row.service_name),
      row.operator_name || '',
      formatTimeAMPM(row.scheduled_arrival),
      formatTimeAMPM(row.scheduled_departure),
    ];
    lines.push(fields.map(csvField).join(','));
  }

  const csv = lines.join('\n');
  logger.info(`[Terminal44] CSV built — ${lines.length - 1} data row(s), ${csv.length} bytes`);
  return csv;
}

module.exports = { buildCsv, formatVehicleNumber, csvField };
