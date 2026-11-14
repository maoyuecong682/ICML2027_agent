import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Workbook } from '@oai/artifact-tool';

const here = path.dirname(fileURLToPath(import.meta.url));
const tables = JSON.parse(await fs.readFile(path.join(here, 'tables.json'), 'utf8'));
const outputDir = path.resolve(here, '..', '..', '隐私图压缩评估_50任务');
await fs.mkdir(outputDir, { recursive: true });
if (tables.length !== 50) throw new Error('Expected 50 task tables');
const quoted = value => '"' + String(value ?? '').replaceAll('"', '""') + '"';
const verified = [];
for (const item of tables) {
  const workbook = Workbook.create();
  const sheet = workbook.worksheets.add('评估');
  const range = sheet.getRange('A1:E4');
  range.values = item.matrix;
  workbook.recalculate();
  const values = range.values;
  if (JSON.stringify(values) !== JSON.stringify(item.matrix)) {
    throw new Error(`Table values changed for ${item.task}`);
  }
  const inspection = await workbook.inspect({ kind: 'table', range: '评估!A1:E4',
    include: 'values', tableMaxRows: 4, tableMaxCols: 5, maxChars: 2400 });
  const csv = '\uFEFF' + values.map(row => row.map(quoted).join(',')).join('\r\n') + '\r\n';
  await fs.writeFile(path.join(outputDir, item.filename), csv, 'utf8');
  verified.push({ task: item.task, filename: item.filename, rows: 3, metrics: 4,
    inspection: inspection.ndjson });
}
await fs.writeFile(path.join(here, 'artifact_verification.json'), JSON.stringify(verified, null, 2));
console.log(JSON.stringify({ outputDir, tasks: verified.length, shape: '3x4 metrics per CSV' }));
