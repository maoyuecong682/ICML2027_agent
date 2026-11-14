"""Score real recorded decisions, verify paired inputs, prepare 50 tiny tables."""
import hashlib
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def load(path):
    return json.loads(path.read_bytes())


def enc(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    protocol = load(HERE / 'protocol.json')
    assert len(protocol['manifest']) == 50
    totals = {a: Counter() for a in ['0', '12345', 'TRAIL']}
    tables, scored = [], []
    common_system = None
    for item in protocol['manifest']:
        folder = HERE / item['folder']
        for name, expected in item['input_sha256'].items():
            assert sha(folder / name) == expected, (item['task'], name)
        cases = load(folder / 'evaluator_only_cases.json')
        gold = {c['query_id']: c['risk'] for c in cases}
        assert sum(gold.values()) == item['positive']
        assert len(gold) - sum(gold.values()) == item['negative']
        source_ids = {f['fact_id'] for r in load(folder / 'original_memory_for_grounding.json')['receivers'] for f in r['facts']}
        for c in cases:
            if c['risk']:
                assert all(set(p['fact_ids']) <= source_ids for p in c['proofs'])
        targets = load(folder / 'targets.json')
        assert all(set(t) <= {'query_id', 'field', 'subject', 'state'} for t in targets)
        assert {t['query_id'] for t in targets} == set(gold)
        frozen = load(folder / 'frozen_inputs.json')
        assert sha(folder / 'targets.json') == frozen['query_sha256']
        assert sha(folder / 'candidate_message.json') == frozen['candidate_sha256']
        observations = load(folder / 'observations.json')
        candidate = load(folder / 'candidate_message.json')
        assert candidate['message_id'] not in {o['message_id'] for o in observations}
        assert all(o['event_id'] <= candidate['event_id'] for o in observations)
        mem0 = load(folder / 'mem0/memory.json')
        assert {o['id'] for o in mem0['occurrences']} == {o['message_id'] for o in observations}
        parent = load(folder / 'arms/12345/memory.json')
        trail = load(folder / 'arms/TRAIL/memory.json')
        assert trail['schema'] == 'TRAIL_relation_preserving_compact_prototype_v2'
        parent_claims = {(n['receiver_id'], enc(n['claim'])) for n in parent['nodes']
                         if n['type'] == 'normalized_received_fact'}
        child_claims = {(trail['receivers'][owner], enc(claim)) for owner, claim in trail['scoped_relations']}
        assert parent_claims == child_claims
        parent_records = {(n['receiver_id'], n['event_id'], 'R') for n in parent['nodes'] if n['type'] == 'actual_disclosure'}
        parent_records |= {(n['receiver_id'], n['event_id'], 'S') for n in parent['nodes'] if n['type'] == 'tool_response'}
        assert parent_records == {(trail['receivers'][r[0]], r[1], r[2]) for r in trail['records']}
        header = ['版本', '有风险的漏过率%', '误判率%', '隐私记忆存储空间（字节）',
                  '检测隐私消耗的DeepSeek token（输入+输出）']
        matrix = [header]
        detail = {'task': item['task'], 'positives': item['positive'], 'negatives': item['negative'], 'arms': {}}
        for arm in ['0', '12345', 'TRAIL']:
            arm_dir = folder / 'arms' / arm
            assert sha(arm_dir / 'memory.json') == frozen['arm_memory_sha256'][arm]
            request, prediction = load(arm_dir / 'request.json'), load(arm_dir / 'prediction.json')
            assert hashlib.sha256(enc(request).encode()).hexdigest() == prediction['request_sha256']
            common_system = common_system or request['messages'][0]
            assert common_system == request['messages'][0]
            assert request['model'] == 'deepseek-flash' and request['temperature'] == 0
            payload = json.loads(request['messages'][1]['content'])
            assert set(payload) == {'shared_history', 'candidate_message', 'questions'}
            assert payload['questions'] == targets and payload['candidate_message'] == candidate
            assert payload['shared_history'] == load(arm_dir / 'memory.json')
            rows = {r['query_id']: r['risk'] for r in prediction['judgments']}
            assert set(rows) == set(gold)
            cm = Counter()
            for qid, truth in gold.items():
                cm['TP' if rows[qid] and truth else 'FP' if rows[qid] else 'FN' if truth else 'TN'] += 1
            assert cm['TP'] + cm['FN'] == item['positive']
            assert cm['TN'] + cm['FP'] == item['negative']
            responses = [load(p) for p in sorted(arm_dir.glob('response_*.json'))]
            actual = json.loads(responses[-1]['choices'][0]['message']['content'])
            assert actual['judgments'] == prediction['judgments']
            usage = {k: sum(r['usage'].get(k, 0) for r in responses)
                     for k in ['prompt_tokens', 'completion_tokens', 'total_tokens']}
            assert usage == prediction['usage']
            assert usage['total_tokens'] == usage['prompt_tokens'] + usage['completion_tokens']
            storage = (arm_dir / 'memory.json').stat().st_size
            assert storage == frozen['arm_memory_bytes'][arm]
            fnr = round(100 * cm['FN'] / item['positive'], 2) if item['positive'] else 'N/A'
            fpr = round(100 * cm['FP'] / item['negative'], 2) if item['negative'] else 'N/A'
            label = {'0': '0（Mem0）', '12345': '0+12345', 'TRAIL': '0+12345+TRAIL（多接收者关联保留）'}[arm]
            matrix.append([label, fnr, fpr, storage, usage['total_tokens']])
            detail['arms'][arm] = {**dict(cm), 'false_negative_rate_percent': fnr,
                'false_positive_rate_percent': fpr, 'storage_bytes': storage, **usage,
                'api_attempts': len(responses)}
            totals[arm].update(cm)
            totals[arm].update(storage_bytes=storage, **usage, api_attempts=len(responses))
        tables.append({'task': item['task'], 'filename': item['task'].replace('/', '_') + '.csv', 'matrix': matrix})
        scored.append(detail)
    assert len(tables) == len({t['filename'] for t in tables}) == 50
    summary = {'tasks': 50, 'selected_real_messages': 50,
        'judgment_items_per_arm': sum(x['queries'] for x in protocol['manifest']),
        'positive_items_per_arm': sum(x['positive'] for x in protocol['manifest']),
        'negative_items_per_arm': sum(x['negative'] for x in protocol['manifest']),
        'tasks_without_positive': sum(x['positive'] == 0 for x in protocol['manifest']),
        'tasks_without_negative': sum(x['negative'] == 0 for x in protocol['manifest']),
        'all_paired_input_checks_passed': True, 'all_TRAlL_parent_claims_and_records_preserved': True,
        'actual_api_usage_verified': True,
        'metric_scope': protocol['risk_definition'], 'totals': {a: dict(c) for a, c in totals.items()},
        'code_sha256': {p.name: sha(p) for p in HERE.glob('*.py')}}
    dump(HERE / 'tables.json', tables)
    dump(HERE / 'scored_results.json', scored)
    dump(HERE / 'summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
