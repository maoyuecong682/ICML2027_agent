"""Independent checks of isolation, temporal support and the delivered CSV."""
import csv
import hashlib
import json
import sys
from pathlib import Path

AUDIT = Path(__file__).resolve().parent
ROOT = AUDIT.parent.parent
FROZEN = AUDIT / 'frozen_v1'
sys.path.insert(0, str(FROZEN if FROZEN.exists() else ROOT / 'P0_agentdojo'))


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    protocol = read(AUDIT / 'protocol.json')
    assert protocol['message_exposure'] == 'observed_delivery'
    for item in protocol['code']:
        code_path = FROZEN / Path(item['path']).relative_to('P0_agentdojo') if FROZEN.exists() else ROOT / item['path']
        assert digest(code_path) == item['sha256']
    results = read(AUDIT / 'stage1_results.json')
    source_bundle = read(ROOT / protocol['sources'][0]['path'])
    observed_calls = 0
    counts = []
    from p0_privacy.background_recovery import BackgroundRecovery
    frozen_recoverer = BackgroundRecovery(read(AUDIT / 'public_background.json'))
    for case in protocol['cases']:
        folder = AUDIT / 'cases' / case['case_id']
        source = read(folder / 'source_memory_graph0.json')
        supports = read(folder / 'fact_support_events.json')
        allowed = set(case['allowed_event_ids'])
        prior_events = allowed - {case['selected_event']}
        all_facts = {f['fact_id']: f for r in source['receivers'] for f in r['facts']}
        with_result = results[case['case_id']]['with']
        assert set(results[case['case_id']]) == {'with'}, 'Stage 2 must remain unrun'
        assert not (folder / 'without').exists()
        assert not (folder / 'without_memory.json').exists()
        original_message = next(n for n in source_bundle['tasks'][case['task_key']]['versions']['0']['nodes']
                                if n['type'] == 'actual_disclosure' and n['event_id'] == case['selected_event'])
        assert original_message['parameters'] == case['selected_message']['parameters']
        for i, rid in enumerate(case['receiver_ids'], 1):
            request = read(folder / 'with' / f'receiver_{i}' / 'input.json')
            assert set(request) == {'memory', 'targets', 'public_background'}
            visible = request['memory']['receivers']
            assert [r['receiver_id'] for r in visible] == [rid]
            assert request['memory']['sharing_groups'] == []
            actual = {f['fact_id']: f for f in visible[0]['facts']}
            expected_local = {f['fact_id'] for r in source['receivers'] if r['receiver_id'] == rid
                              for f in r['facts'] if allowed.intersection(supports[f['fact_id']])}
            assert set(actual) == expected_local, 'Non-delivered messages entered local'
            if rid != case['selected_message']['receiver_id']:
                prior = {f['fact_id'] for r in source['receivers'] if r['receiver_id'] == rid
                         for f in r['facts'] if prior_events.intersection(supports[f['fact_id']])}
                assert set(actual) == prior, 'Undelivered m changed receiver memory'
            assert all(actual[fid] == all_facts[fid] for fid in actual)
            assert [t['field'] for t in request['targets']] == case['fields']
            for prediction in with_result['locals'][rid]['rows']:
                assert all(e['fact_id'] in actual for e in prediction['evidence'])
            archived_predictions = read(folder / 'with' / f'receiver_{i}' / 'predictions.json')
            assert frozen_recoverer.recover(request['memory'], request['targets']) == archived_predictions
            observed_calls += 1
        joint_request = read(folder / 'with/joint/input.json')
        joint = {f['fact_id']: f for r in joint_request['memory']['receivers'] for f in r['facts']}
        expected = {fid for fid in all_facts if allowed.intersection(supports[fid])}
        assert set(joint) == expected, 'Future facts or missing prefix facts in joint'
        assert all(joint[fid] == all_facts[fid] for fid in joint)
        assert len(joint) == sum(len(r['facts']) for r in joint_request['memory']['receivers'])
        assert all(g['enabled'] for g in joint_request['memory']['sharing_groups'])
        assert frozen_recoverer.recover(joint_request['memory'], joint_request['targets']) == read(folder / 'with/joint/predictions.json')
        observed_calls += 1
        strict = [row['field'] for row in with_result['joint']['rows'] if row['top1_recovery'] and all(
            not next(r for r in local['rows'] if r['field'] == row['field'])['top1_recovery']
            for local in with_result['locals'].values())]
        assert strict == with_result['strict_synergy_fields']
        counts.append({'task': case['task_key'], 'locals': [v['correct'] for v in with_result['locals'].values()],
                       'joint': with_result['joint']['correct'], 'fields': len(case['fields']), 'strict': strict})
    matrix = read(AUDIT / 'csv_matrix.json')
    csv_path = AUDIT.parent / '联合接收者_新增消息对照.csv'
    with csv_path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.reader(stream))
    assert rows == matrix
    assert len(rows) == len(protocol['cases']) + 1 and all(len(row) == 11 for row in rows)
    assert all(all(value == '' for value in row[6:]) for row in rows[1:])
    assert all(row[0] == case['task_key'] for row, case in zip(rows[1:], protocol['cases']))
    assert all(all(row[i] for i in range(6)) for row in rows[1:])
    assert csv_path.read_bytes().startswith(b'\xef\xbb\xbf')
    check = {'stage': 1, 'case_count': len(protocol['cases']), 'recovery_calls': observed_calls,
             'local_calls': observed_calls - len(protocol['cases']), 'joint_calls': len(protocol['cases']),
             'csv_data_rows': len(rows) - 1, 'csv_columns': 11, 'stage2_columns_blank': True,
             'message_visibility_follows_original_delivery': True, 'unreached_receivers_unchanged': True,
             'local_history_isolated': True,
             'future_events_excluded': True, 'code_hashes_unchanged': True,
             'csv_round_trip_exact': True, 'csv_sha256': digest(csv_path), 'results': counts}
    (AUDIT / 'stage1_validation.json').write_text(json.dumps(check, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(check, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
