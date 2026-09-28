const sharp = require('sharp');

const ROW_HEIGHT = 28;
const HEADER_HEIGHT = 32;
const FONT_SIZE = 14;
const CHAR_WIDTH = 9; // a hair wider than 14px monospace so text never clips
const PADDING_X = 10;

function escapeXml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' }[c]));
}

/**
 * Renders a plain table as a PNG "snapshot" of a CSV, for people who won't
 * open the attachment. `headers`: string[]; `rows`: array of arrays, one
 * value per header. Each column is as wide as its longest cell. Returns a Buffer.
 *
 * Needs a font on the host: librsvg draws text via fontconfig, so a server
 * with no fonts installed renders blank text (`apt install fonts-dejavu-core`).
 */
async function buildTableImage(headers, rows) {
  const widths = headers.map((h, i) => {
    const longest = Math.max(String(h).length, ...rows.map((r) => String(r[i] ?? '').length));
    return longest * CHAR_WIDTH + PADDING_X * 2;
  });
  const width = widths.reduce((sum, w) => sum + w, 0);
  const height = HEADER_HEIGHT + rows.length * ROW_HEIGHT;

  const textY = (top, rowHeight) => top + rowHeight / 2 + FONT_SIZE / 3;
  const cellsFor = (values, top, rowHeight, extra) => {
    let x = 0;
    return values
      .map((v, i) => {
        const cell = `<text x="${x + PADDING_X}" y="${textY(top, rowHeight)}" font-family="monospace" font-size="${FONT_SIZE}" ${extra}>${escapeXml(v)}</text>`;
        x += widths[i];
        return cell;
      })
      .join('');
  };

  const header = cellsFor(headers, 0, HEADER_HEIGHT, 'font-weight="bold" fill="white"');
  const body = rows
    .map((row, i) => {
      const top = HEADER_HEIGHT + i * ROW_HEIGHT;
      const bg = i % 2 === 0 ? '#ffffff' : '#f2f2f2';
      return `<rect x="0" y="${top}" width="${width}" height="${ROW_HEIGHT}" fill="${bg}"/>${cellsFor(row, top, ROW_HEIGHT, 'fill="black"')}`;
    })
    .join('');

  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}">
    <rect width="${width}" height="${height}" fill="white"/>
    <rect width="${width}" height="${HEADER_HEIGHT}" fill="#1a73e8"/>
    ${header}
    ${body}
  </svg>`;

  return sharp(Buffer.from(svg)).png().toBuffer();
}

module.exports = { buildTableImage };
