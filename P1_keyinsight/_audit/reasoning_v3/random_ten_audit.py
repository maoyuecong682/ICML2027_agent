"""Freeze a uniform sample of ten completed tasks, then compare named relations."""
import hashlib
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / 'P0_agentdojo'))
sys.path.insert(0, str(HERE))

from p0_privacy.background_recovery import BackgroundRecovery
from p0_privacy.inference import VERSION, build_knowledge
from p0_privacy.public_background import DEFAULT_OUTPUT
from p0_privacy.recovery import memory_from_graph
from p0_privacy.recovery_supplement import load_jobs
from rerun_50 import compare_closures


def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export_view(knowledge):
    result = []
    for cid, node in sorted(knowledge['claims'].items()):
        supports = [sorted(s) for s in node['supports']]
        result.append({'claim_id': cid, 'claim': node['claim'], 'proofs': node['proofs'],
                       'evidence_sets': supports,
                       'evidence_receiver_sets': [sorted({knowledge['leaves'][s] for s in support
                                                         if knowledge['leaves'][s] is not None})
                                                  for support in supports],
                       'conflict_related': bool(knowledge['taint'][cid])})
    return result


def requests(facts):
    result = {}
    for fact in facts:
        if fact['field'] != 'request_parameter':
            continue
        event = result.setdefault(fact['event_id'], {'event_id': fact['event_id'],
                                  'tool': fact.get('tool'), 'parameter_paths': {}})
        pointer = fact['parameter_path']
        if pointer in event['parameter_paths']:
            assert event['parameter_paths'][pointer] == fact['value']
        event['parameter_paths'][pointer] = fact['value']
    return list(result.values())


def main():
    jobs = load_jobs()
    population = sorted(jobs)
    assert len(population) == 50
    seed = random.SystemRandom().getrandbits(64)
    selected = random.Random(seed).sample(population, 10)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output = HERE / 'random_ten' / stamp
    assert not output.exists()
    selection = {'population': population, 'population_count': 50, 'sample_count': 10,
                 'sampling': 'random.Random(seed).sample(sorted(population), 10); no receiver or outcome filtering',
                 'seed': seed, 'selected_tasks_in_draw_order': selected,
                 'selection_frozen_before_inference': True, 'created_at_utc': stamp}
    dump(output / 'selection.json', selection)
    background = json.loads(DEFAULT_OUTPUT.read_bytes())
    public_records = BackgroundRecovery(background).public_records
    privacy_fields = set(background['privacy_definitions']['fields']) | {'calendar_start_time', 'calendar_end_time'}
    tasks = {}
    with patch('socket.socket.connect', side_effect=AssertionError('Offline relation audit')):
        for key in selected:
            graph = jobs[key]['versions']['0']
            memory = memory_from_graph(graph, shared=True)
            comparison = compare_closures(memory, public_records, privacy_fields)
            receivers = {r['receiver_id']: r['facts'] for r in memory['receivers']}
            local = {rid: export_view(build_knowledge([(rid, f) for f in facts], public_records))
                     for rid, facts in receivers.items()}
            scopes = set()
            for rid in receivers:
                visible = {rid}
                for group in memory['sharing_groups']:
                    if group['enabled'] and rid in group['members']:
                        visible.update(group['members'])
                scopes.add(tuple(sorted(visible)))
            joint = [{'members': list(scope), 'knowledge': export_view(build_knowledge(
                     [(rid, f) for rid in scope for f in receivers[rid]], public_records))}
                     for scope in sorted(scopes)]
            tasks[key] = {'task_original': jobs[key]['task'], 'comparison': comparison,
                          'received_requests': {rid: requests(facts) for rid, facts in receivers.items()},
                          'local_knowledge': local, 'joint_knowledge': joint,
                          'success_under_current_rules': bool(comparison['new_joint_relations'])}
            dump(output / 'memories' / (key.replace('/', '_') + '.json'), memory)
            print(json.dumps({'task': key, 'receiver_count': len(receivers),
                              'new_joint_relations': len(comparison['new_joint_relations']),
                              'local_claim_counts': comparison['local_claim_counts']}, ensure_ascii=True), flush=True)
    success = [key for key, t in tasks.items() if t['success_under_current_rules']]
    summary = {'sample_count': 10, 'success_tasks': success, 'success_count': len(success),
               'success_rate': len(success) / 10, 'recovery_version': VERSION,
               'multi_receiver_tasks': sum(t['comparison']['receiver_count'] > 1 for t in tasks.values()),
               'graph_arm': '0', 'llm_recoverer_calls': 0, 'network_disabled': True,
               'comparison': 'joint claims minus union of ALL independent local closures; exclude conflicting claims; require multi-receiver evidence',
               'code_sha256': {name: sha(ROOT / 'P0_agentdojo/p0_privacy' / name) for name in
                               ('inference.py', 'relational_memory.py', 'knowledge_merge.py', 'recovery.py')},
               'script_sha256': sha(Path(__file__)),
               'limitation': 'No rule-derived joint result does not prove absence of a natural-language inference path.'}
    dump(output / 'results.json', {'selection': selection, 'summary': summary, 'tasks': tasks})
    dump(output / 'summary.json', summary)
    print(json.dumps({'output': str(output), 'summary': summary}, ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
