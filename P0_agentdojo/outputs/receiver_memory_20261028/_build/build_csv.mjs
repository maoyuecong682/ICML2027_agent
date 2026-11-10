import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Workbook } from '@oai/artifact-tool';

const here = path.dirname(fileURLToPath(import.meta.url));
const workbook = Workbook.create();
if (process.argv.includes('--help-csv')) {
  console.log(workbook.help('CSV export', { search: 'CSV|csv', include: 'index,examples,notes', maxChars: 3000 }).ndjson);
  process.exit(0);
}
const input = JSON.parse(await fs.readFile(path.join(here, 'rows.json'), 'utf8'));
const sheet = workbook.worksheets.add('接收者记忆');
const matrix = [input.headers, ...input.rows];
sheet.getRange(`A1:C${matrix.length}`).values = matrix;
sheet.showGridLines = false;
sheet.getRange(`A1:C${matrix.length}`).format.font = { name: 'Arial', size: 10 };
sheet.getRange(`A1:C${matrix.length}`).format.wrapText = true;
sheet.getRange(`A1:C${matrix.length}`).format.verticalAlignment = 'top';
sheet.getRange(`A1:A${matrix.length}`).format.columnWidth = 64;
sheet.getRange(`B1:B${matrix.length}`).format.columnWidth = 46;
sheet.getRange(`C1:C${matrix.length}`).format.columnWidth = 115;
sheet.getRange('A1:C1').format = { fill: '#243B53', font: { name: 'Arial', size: 10, bold: true, color: '#FFFFFF' } };
sheet.getRange('A1:C1').format.rowHeight = 24;
sheet.getRange('A2:C2').format.autofitRows();
sheet.freezePanes.freezeRows(1);
workbook.recalculate();

const cells = sheet.getRange(`A1:C${matrix.length}`).values;
if (JSON.stringify(cells) !== JSON.stringify(matrix)) throw new Error('Workbook changed source text');
console.log((await workbook.inspect({ kind: 'table', range: '接收者记忆!A1:C3', include: 'values', tableMaxRows: 3, tableMaxCols: 3, tableMaxCellChars: 90, maxChars: 1800 })).ndjson);
const preview = await workbook.render({ sheetName: '接收者记忆', range: 'A1:C2', scale: 1, format: 'png' });
await fs.writeFile(path.join(here, 'preview.png'), new Uint8Array(await preview.arrayBuffer()));
// CSV is the requested output. Serialize exact verified workbook values using
// RFC 4180 quoting, UTF-8 BOM and CRLF; do not create an unsolicited XLSX.
const quote = value => '"' + String(value ?? '').replaceAll('"', '""') + '"';
const csv = '\uFEFF' + cells.map(row => row.map(quote).join(',')).join('\r\n') + '\r\n';
const destination = path.resolve(here, '..', 'task_接收者_接收到的全部记忆.csv');
await fs.writeFile(destination, csv, { encoding: 'utf8', flag: 'wx' });
const parsed = await Workbook.fromCSV(csv.slice(1), { sheetName: '复核' });
const roundtrip = parsed.worksheets.getItem('复核').getRange(`A1:C${matrix.length}`).values;
if (JSON.stringify(roundtrip) !== JSON.stringify(matrix)) throw new Error('CSV roundtrip mismatch');
await fs.writeFile(path.join(here, 'artifact_validation.json'), JSON.stringify({ ...input.summary, columns: input.headers, csv_roundtrip_exact: true, utf8_bom: true, csv_rfc4180_quoted: true }, null, 2));
console.log(JSON.stringify({ output: destination, ...input.summary, csv_roundtrip_exact: true }));
