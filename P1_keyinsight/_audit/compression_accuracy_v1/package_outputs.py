"""Check CSV round trips and bundle exactly the requested fifty result tables."""
import csv
import hashlib
import json
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUTPUT = ROOT / 'P1_keyinsight/隐私图压缩评估_50任务'
ARCHIVE = OUTPUT.with_suffix('.zip')


def main():
    tables = json.loads((HERE / 'tables.json').read_bytes())
    actual = sorted(OUTPUT.glob('*.csv'))
    assert len(actual) == 50
    assert {p.name for p in actual} == {t['filename'] for t in tables}
    hashes = {}
    for item in tables:
        path = OUTPUT / item['filename']
        assert path.read_bytes().startswith(b'\xef\xbb\xbf')
        with path.open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.reader(stream))
        assert len(rows) == 4 and all(len(r) == 5 for r in rows)
        for saved, source in zip(rows, item['matrix']):
            for a, b in zip(saved, source):
                if isinstance(b, (float, int)):
                    assert float(a) == float(b)
                else:
                    assert a == b
        for row in rows[1:]:
            assert all(v == 'N/A' or 0 <= float(v) <= 100 for v in row[1:3])
            assert int(row[3]) > 0 and int(row[4]) > 0
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    with zipfile.ZipFile(ARCHIVE, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for path in actual:
            z.write(path, arcname=path.name)
    with zipfile.ZipFile(ARCHIVE) as z:
        assert z.testzip() is None and len(z.namelist()) == 50
        assert all(hashlib.sha256(z.read(name)).hexdigest() == hashes[name] for name in z.namelist())
    report = {'csv_files': 50, 'each_table_data_rows': 3, 'each_table_metrics': 4,
              'only_requested_metrics_plus_version_labels': True,
              'CSV_UTF8_BOM_and_exact_round_trip_verified': True,
              'archive_integrity_verified': True, 'file_sha256': hashes}
    (HERE / 'delivery_verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(str(OUTPUT))
    print(str(ARCHIVE))
    print('VERIFIED 50 CSVs, each 3x4 metrics; ZIP contains exactly 50 CSVs')


if __name__ == '__main__':
    main()
