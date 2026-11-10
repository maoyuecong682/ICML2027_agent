"""Separate v2 regression: original 50 tasks, no model/network, no overwrites."""
import copy
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
P0 = ROOT / 'P0_agentdojo'
sys.path.insert(0, str(P0))

from p0_privacy.inference import VERSION
from p0_privacy.public_background import DEFAULT_OUTPUT
from p0_privacy.recovery import SCHEMA, recover
from p0_privacy.recovery_supplement import BATCH, evaluate, load_jobs


def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def demo():
    prior = {'schema': SCHEMA, 'receivers': [
        {'receiver_id': 'A', 'facts': [{'fact_id': 'prior:A', 'field': 'message_content', 'value': '小张负责 X17。'}]},
        {'receiver_id': 'B', 'facts': []}],
        'sharing_groups': [{'group_id': 'AB', 'members': ['A', 'B'], 'enabled': True}]}
    after = copy.deepcopy(prior)
    message = {'fact_id': 'new:B', 'field': 'message_content', 'value': 'X17 是并购项目。'}
    after['receivers'][1]['facts'].append(message)
    result = {'source': 'synthetic_capability_check_NOT_AgentDojo', 'actual_message_recipient': 'B',
              'message': message, 'before': {}, 'after': {}}
    for name, memory in [('before', prior), ('after', after)]:
        for rid in ('A', 'B', 'joint'):
            visible = copy.deepcopy(memory)
            if rid != 'joint':
                visible['receivers'] = [r for r in visible['receivers'] if r['receiver_id'] == rid]
                visible['sharing_groups'] = []
            target = [{'probe_id': 'p0', 'receiver_id': 'A' if rid == 'joint' else rid,
                       'field': 'project_participation', 'subject': '小张'}]
            result[name][rid] = {'input': {'memory': visible, 'targets': target},
                                 'prediction': recover(visible, target)[0]}
    assert result['before']['A']['input'] == result['after']['A']['input']
    assert all(v['prediction']['top1_guess'] is None for v in result['before'].values())
    assert all(result['after'][rid]['prediction']['top1_guess'] is None for rid in ('A', 'B'))
    proved = result['after']['joint']['prediction']
    assert proved['top1_guess'] == {'person': '小张', 'project': 'X17', 'project_type': '并购'}
    assert proved['minimal_receiver_sets'] == [['A', 'B']]
    dump(HERE / 'message_ablation_demo.json', result)


def main():
    if VERSION != 'deterministic-relations-v2':
        raise RuntimeError('Historical v2 output is preserved. Use reasoning_v3/evaluate.py for the active recoverer.')
    old_path = BATCH / '47任务top1恢复评估.json'
    old_bytes = old_path.read_bytes()
    old = json.loads(old_bytes)
    background = json.loads(DEFAULT_OUTPUT.read_bytes())
    jobs = load_jobs()
    assert len(jobs) == 50
    tasks, strict, changed, successful_rules = {}, [], [], []
    aggregate = {condition: {'correct': 0, 'probes': 0} for condition in ('none', 'local', 'shared')}
    with patch('socket.socket.connect', side_effect=AssertionError('Network disabled during v2 validation')):
        demo()
        for key, original in sorted(jobs.items()):
            job = {**original, 'versions': {'0': original['versions']['0']}}
            task = evaluate(key, job, background, HERE / 'calls')
            tasks[key] = task
            conditions = task['conditions']['0']
            for condition, stats in conditions.items():
                for metric in ('correct', 'probes'):
                    aggregate[condition][metric] += stats[metric]
            local, joint = conditions['local']['rows'], conditions['shared']['rows']
            for field in task['fields']:
                local_rows = [r for r in local if r['field'] == field]
                joint_row = next(r for r in joint if r['field'] == field)
                if joint_row['top1_recovery'] and not any(r['top1_recovery'] for r in local_rows):
                    strict.append({'task': key, 'field': field, 'prediction': joint_row})
                if joint_row['top1_recovery'] and joint_row['method'] == 'deterministic_rule_inference':
                    successful_rules.append({'task': key, 'field': field, 'prediction': joint_row})
            for condition in ('local', 'shared'):
                baseline = {r['probe_id']: r for r in old['tasks'][key]['recovery']['conditions']['0'][condition]['rows']}
                for row in conditions[condition]['rows']:
                    previous = baseline[row['probe_id']]
                    if row['top1_guess'] != previous['top1_guess']:
                        changed.append({'task': key, 'condition': condition, 'field': row['field'],
                                        'receiver_id': row['receiver_id'],
                                        'before': previous['top1_guess'], 'after': row['top1_guess'],
                                        'old_score': previous['top1_recovery'], 'new_score': row['top1_recovery'],
                                        'method': row['method']})
            print(key, 'local', conditions['local']['correct'], 'shared', conditions['shared']['correct'], flush=True)
    assert old_path.read_bytes() == old_bytes
    for values in aggregate.values():
        values['rate'] = values['correct'] / values['probes'] if values['probes'] else None
    summary = {'version': VERSION, 'llm_calls': 0, 'network_disabled': True,
               'tasks': 50, 'graph_arm': '0', 'target_and_reference_definitions_unchanged': True,
               'old_report_unchanged_sha256': sha(old_path), 'old_aggregate': old['aggregate']['0'],
               'new_aggregate': aggregate, 'strict_joint_task_count': len({r['task'] for r in strict}),
               'strict_joint_task_rate': len({r['task'] for r in strict}) / 50,
               'strict_joint_fields': strict, 'successful_rule_task_fields': successful_rules,
               'prediction_changes': changed,
               'code': {name: sha(P0 / 'p0_privacy' / name) for name in
                        ('inference.py', 'knowledge_merge.py', 'recovery.py', 'background_recovery.py')}}
    dump(HERE / '50task_results.json', {'summary': summary, 'tasks': tasks})
    dump(HERE / 'summary.json', summary)
    print(json.dumps({k: v for k, v in summary.items() if k not in {
        'strict_joint_fields', 'successful_rule_task_fields', 'prediction_changes', 'code', 'old_aggregate'}},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
