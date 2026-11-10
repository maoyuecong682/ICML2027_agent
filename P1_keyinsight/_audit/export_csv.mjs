import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Workbook } from '@oai/artifact-tool';

const auditDir = path.dirname(fileURLToPath(import.meta.url));
const matrix = JSON.parse(await fs.readFile(path.join(auditDir, 'csv_matrix.json'), 'utf8'));
const workbook = Workbook.create();
const sheet = workbook.worksheets.add('消息对照');
const range = sheet.getRange(`A1:K${matrix.length}`);
range.values = matrix;
workbook.recalculate();
const verified = range.values;
if (JSON.stringify(verified) !== JSON.stringify(matrix)) {
  throw new Error('Artifact Tool round-trip changed CSV content');
}
const inspection = await workbook.inspect({
  kind: 'table', range: `消息对照!A1:K${matrix.length}`,
  include: 'values', tableMaxRows: 2, tableMaxCols: 6,
  tableMaxCellChars: 100, maxChars: 1600,
});
await fs.writeFile(path.join(auditDir, 'artifact_inspection.ndjson'), inspection.ndjson, 'utf8');
// CSV carries plain text only. Serialize the verified worksheet values without
// an XLSX side product; quote every field to preserve commas and actual newlines.
const quoted = value => '"' + String(value ?? '').replaceAll('"', '""') + '"';
const csv = '\uFEFF' + verified.map(row => row.map(quoted).join(',')).join('\r\n') + '\r\n';
const output = path.join(auditDir, '..', '联合接收者_新增消息对照.csv');
await fs.writeFile(output, csv, 'utf8');
console.log(JSON.stringify({ output, dataRows: matrix.length - 1, columns: matrix[0].length }));
