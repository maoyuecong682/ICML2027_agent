"""Resumable 47-task real execution / annotation / Graphiti / Mem0 comparison.

The default privacy-text strategy is real Mem0. Graph arms share that output;
only the five structural switches differ. No synthetic trace substitutes.
"""
import argparse
import asyncio
import copy
import hashlib
import json
import os
import random
import subprocess
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv
from agentdojo.task_suite.load_suites import get_suites
from p0.config import Config
from p0.records import dump, now
from .catalog import CATEGORIES, ONTOLOGY, categories_for
from .simplification import SimplificationConfig, simplify_graph, terminal

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / 'outputs/batch47_20261104'
EXCLUDED = {'workspace/user_task_14', 'workspace/user_task_22', 'workspace/user_task_31'}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def selection(seed=20261104, count=47):
    """One per primary category, then largest-remainder proportional allocation."""
    buckets = defaultdict(list)
    for suite_name, suite in sorted(get_suites('v1.2').items()):
        for task in sorted(suite.user_tasks.values(), key=lambda t: int(t.ID.rsplit('_', 1)[1])):
            key = suite_name + '/' + task.ID
            if key in EXCLUDED:
                continue
            row = {'task_key': key, 'suite': suite_name, 'task_id': task.ID,
                   'prompt': task.PROMPT, 'difficulty': str(task.DIFFICULTY),
                   'category_ids': categories_for(key), 'primary_category_id': categories_for(key)[0]}
            buckets[row['primary_category_id']].append(row)
    population = sum(map(len, buckets.values()))
    if not len(buckets) <= count <= population:
        raise ValueError('Sample size cannot cover every remaining category')
    quotas = {k: 1 for k in buckets}
    capacity = {k: len(v) - 1 for k, v in buckets.items()}
    remaining = count - len(buckets)
    total_capacity = sum(capacity.values())
    ideals = {k: remaining * v / total_capacity for k, v in capacity.items()}
    for k, ideal in ideals.items():
        quotas[k] += int(ideal)
    for k in sorted(buckets, key=lambda k: (-(ideals[k] % 1), k))[:count - sum(quotas.values())]:
        quotas[k] += 1
    rng = random.Random(seed)
    selected = []
    for category in sorted(buckets):
        selected.extend(rng.sample(buckets[category], quotas[category]))
    selected.sort(key=lambda t: (t['suite'], int(t['task_id'].rsplit('_', 1)[1])))
    return {'seed': seed, 'suite_version': 'v1.2', 'population_count': population + len(EXCLUDED),
            'remaining_count': population, 'excluded': sorted(EXCLUDED), 'selected_count': count,
            'selection_before_execution': True, 'selection_uses_outcomes': False,
            'algorithm': 'one per remaining primary category; largest-remainder allocation of remaining capacity; seeded sample',
            'category_population': {k: len(v) for k, v in sorted(buckets.items())},
            'category_quotas': quotas, 'suite_counts': dict(Counter(t['suite'] for t in selected)),
            'tasks': selected}


def prepare(folder, seed=20261104, privacy_text='mem0'):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / '47任务双版本隐私图.json'
    if path.exists():
        bundle = read(path)
        if bundle['selection'] != selection(seed):
            raise ValueError('Resume selection differs from saved selection')
        return bundle
    chosen = selection(seed)
    bundle = {'schema_version': 'p0.batch47.privacy.v1', 'created_at': now(), 'selection': chosen,
              'config': {'privacy_text_compression': privacy_text, 'receiver_merge': 'off',
                         'graph_arms': {'0': {'enabled': False}, '12345': {'enabled': True}},
                         'privacy_definition': 'disclosure_is_leakage_by_experiment_convention',
                         'graphiti': 'mandatory_real_persistent_ingestion',
                         'scope': 'observed_explicit_service_request_parameters; downstream views not silently equated'},
              'tasks': {t['task_key']: {'task': t, 'status': 'pending', 'versions': None} for t in chosen['tasks']}}
    save(folder, bundle)
    return bundle


def save(folder, bundle):
    statuses = Counter(t['status'] for t in bundle['tasks'].values())
    bundle['updated_at'] = now()
    bundle['summary'] = {'selected': len(bundle['tasks']), 'statuses': dict(statuses),
                         'completed': statuses.get('complete', 0),
                         'official_successes': sum(t.get('execution', {}).get('utility') == 1 for t in bundle['tasks'].values())}
    path = folder / '47任务双版本隐私图.json'
    temp = path.with_suffix('.tmp')
    dump(temp, bundle)
    for attempt in range(20):
        try:
            temp.replace(path)
            break
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.2)


def execute_one(folder, key):
    from p0.run import run_one
    bundle = read(folder / '47任务双版本隐私图.json')
    task = bundle['tasks'][key]['task']
    target = folder / '_audit/execution' / key.replace('/', '_')
    if (target / 'graph.json').exists():
        return
    info = {k: task[k] for k in ('suite', 'task_id', 'prompt', 'difficulty')}
    run_one(info, Config(), target, os.environ['DEEPSEEK_API_KEY'])


def worker_execution(folder, task, env_file):
    key = task['task_key']
    path = folder / '_audit/execution' / key.replace('/', '_')
    path.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, '-B', '-X', 'utf8', '-m', 'p0_privacy.batch_pipeline', '--output-dir', str(folder), '--execute-one', key]
    if env_file:
        command += ['--env-file', str(env_file)]
    with (path / 'execution.log').open('a', encoding='utf-8') as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=log, timeout=1800)
    if result.returncode or not (path / 'graph.json').exists():
        raise RuntimeError('Execution worker failed; inspect ' + str(path / 'execution.log'))
    return read(path / 'result.json')


def privacy_text_document(task):
    blocks = []
    for d in task['disclosures']:
        for a in d['atoms']:
            blocks.append({'id': a['atom_id'], 'task_id': task['task_key'], 'receiver_id': d['receiver_id'],
                           'field': a['field'], 'kind': a['kind'], 'relation': a['relation'],
                           'text': a['span'], 'event_id': d['event_id'], 'time': d['time'],
                           'parameter_path': a['parameter_path'], 'span_start': a['span_start'],
                           'span_end': a['span_end'], 'source_ids': a['source_ids']})
    return {'schema': 'privacy.text.input.v1', 'blocks': blocks, 'links': [],
            'origin': 'all observed annotated fragments including non-sensitive context; no source-candidate import'}


def run_mem0(task, audit, strategy):
    document = privacy_text_document(task)
    source = audit / 'mem0_input.json'
    dump(source, document)
    folder = audit / 'privacy_text'
    if (folder / 'memory.json').exists():
        before = read(folder / 'before.json')
        if read(folder / 'report.json')['strategy'] != strategy:
            raise ValueError('Mem0 strategy mismatch')
        if before == document:
            return read(folder / 'memory.json'), read(folder / 'report.json')
        # A strictly revalidated annotation revision is a new input. Preserve
        # the previous store below, then run real Mem0 again, never reuse it.
    if not document['blocks']:
        # Real absence of fragments: no fake Mem0/model run is claimed.
        return {'schema': 'privacy.text.memory.v1', 'facts': [], 'occurrences': [], 'links': []}, {
            'strategy': strategy, 'status': 'not_applicable_no_observed_fragments', 'input_blocks': 0,
            'output_facts': 0, 'new_model_calls': 0}
    if folder.exists():
        # Failed attempts remain audit evidence; retry in a fresh Mem0 store.
        index = 1
        while (audit / f'privacy_text_attempt_{index}').exists():
            index += 1
        folder.rename(audit / f'privacy_text_attempt_{index}')
    python = ROOT / '.venv_mem0/Scripts/python.exe'
    command = [str(python), '-B', '-X', 'utf8', str(ROOT / 'privacy_memory_compression.py'),
               '--input', str(source), '--output', str(folder), '--strategy', strategy]
    with (audit / 'mem0.log').open('a', encoding='utf-8') as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=log, timeout=1800)
    if result.returncode or not (folder / 'memory.json').exists():
        raise RuntimeError('Mem0 failed without baseline fallback; inspect ' + str(audit / 'mem0.log'))
    return read(folder / 'memory.json'), read(folder / 'report.json')


def apply_privacy_memory(graph, memory, report):
    """Privacy fragment layer reads Mem0 facts; raw requests remain audit evidence.

    Mem0 does not replace Graphiti's separate semantic extraction or invent
    entity equivalences. Occurrence/time/evidence are retained for every source.
    """
    graph = copy.deepcopy(graph)
    atoms = {n['id']: n for n in graph['nodes'] if n['type'] == 'disclosed_atom'}
    occurrences = {o['id']: o for o in memory['occurrences']}
    if set(atoms) != set(occurrences):
        raise ValueError('Mem0 must cover every annotated occurrence')
    facts = {f['id']: f for f in memory['facts']}
    groups = defaultdict(list)
    for oid, occurrence in occurrences.items():
        fact = facts[occurrence['fact_ref']]
        atom = atoms[oid]
        annotation = atom['annotation']
        if (fact['receiver_id'], fact['field'], fact['kind'], fact['relation']) != (
                atom['receiver_id'], annotation['field'], annotation['kind'], annotation['relation']):
            raise ValueError('Mem0 crossed privacy scope')
        groups[fact['id']].append(oid)
    mapping = {}
    absorbed = {}
    for fid, ids in groups.items():
        canonical = ids[0]
        fact = facts[fid]
        if fact['text'] not in [atoms[oid]['label'] for oid in ids]:
            raise ValueError('Mem0 introduced an unsupported representative')
        for oid in ids:
            mapping[oid] = canonical
        absorbed[canonical] = [copy.deepcopy(atoms[oid]) for oid in ids]
        atoms[canonical]['label'] = fact['text']
        atoms[canonical]['privacy_text_fact_ref'] = fid
        atoms[canonical]['source_occurrences'] = absorbed[canonical]
    graph['nodes'] = [n for n in graph['nodes'] if n['id'] not in mapping or mapping[n['id']] == n['id']]
    edges, seen = [], set()
    for e in graph['edges']:
        value = copy.deepcopy(e)
        value['source'] = mapping.get(e['source'], e['source'])
        value['target'] = mapping.get(e['target'], e['target'])
        signature = (value['source'], value['target'], value['kind'], value.get('template_slot'), value.get('slot'))
        if signature not in seen:
            value['id'] = 'mem0_edge:' + str(len(edges))
            edges.append(value)
            seen.add(signature)
    graph['edges'] = edges
    def references(value):
        if isinstance(value, str):
            return mapping.get(value, value)
        if isinstance(value, list):
            result = [references(v) for v in value]
            return list(dict.fromkeys(result)) if all(isinstance(v, str) for v in result) else result
        if isinstance(value, dict):
            return {k: references(v) for k, v in value.items()}
        return value
    for n in graph['nodes']:
        for key in ('support', 'cumulative_atom_ids', 'indirect_annotation_ids'):
            if key in n:
                n[key] = references(n[key])
    graph['joint_factors'] = references(graph['joint_factors'])
    graph['display_groups'] = references(graph['display_groups'])
    graph['privacy_text_compression'] = {'strategy': report['strategy'], 'report': report,
                                         'memory': copy.deepcopy(memory), 'node_map': mapping,
                                         'scope': 'privacy fragment nodes; independent Graphiti semantics retained',
                                         'same_for_both_graph_arms': True}
    graph['statistics'].update(nodes=len(graph['nodes']), edges=len(edges),
                               node_types=dict(Counter(n['type'] for n in graph['nodes'])))
    graph['assessment']['experiment_definition'] = 'disclosure_is_leakage'
    graph['assessment']['unauthorized_disclosure_verdict'] = 'not_assessed'
    active = {n['id']: n for n in graph['nodes']}
    for edge in graph['edges']:
        a, b = active[edge['source']], active[edge['target']]
        if a.get('receiver_id') and b.get('receiver_id') and a['receiver_id'] != b['receiver_id']:
            raise ValueError('Mem0 introduced a cross-recipient edge')
    for factor in graph['joint_factors']:
        if any(nid not in active for values in factor['support'].values() for nid in values):
            raise ValueError('Mem0 lost factor evidence')
    graph['construction_validation'] = graph.pop('validation', None)
    graph['validation'] = {'passed': True, 'checks': ['Mem0 occurrence coverage',
                          'representative is received text', 'scope isolation',
                          'edge endpoints', 'factor support'], 'semantic_equivalence': 'not_proved'}
    return graph


async def analysis_task(folder, entry, store, categories, strategy):
    from .annotation import annotate_task
    from .build import attach_annotation
    from .recipients import attach_resolved_receivers
    from .knowledge_merge import input_from_record
    from .task_graph import project_graph
    key = entry['task']['task_key']
    audit = folder / '_audit/analysis' / key.replace('/', '_')
    audit.mkdir(parents=True, exist_ok=True)
    path = folder / '_audit/execution' / key.replace('/', '_') / 'graph.json'
    original_bytes = path.read_bytes()
    trace = json.loads(original_bytes)
    task = {**entry['task'], 'execution_status': '已执行', 'annotation_status': 'pending',
            'official_task_success': trace['result']['utility'], 'model_annotation': None,
            'privacy_gain_bits': None, 'privacy_leakage_verdict': 'not_evaluated'}
    attach_resolved_receivers(task, trace, path)
    if not task['disclosures']:
        raise ValueError('No observed service request: no successful privacy-graph construction claimed')
    cat = copy.deepcopy(categories)
    cached_task_path = audit / 'annotated_task.json'
    cached_task = read(cached_task_path) if cached_task_path.exists() else None
    current_receipts = [(d['disclosure_id'], d['received_request_parameters'], d['source_graph_sha256'])
                        for d in task['disclosures']]
    cached_receipts = [(d['disclosure_id'], d['received_request_parameters'], d['source_graph_sha256'])
                       for d in cached_task.get('disclosures', [])] if cached_task else []
    if cached_task and cached_task.get('annotation_status') == 'model_annotated' and current_receipts == cached_receipts:
        task = cached_task
    else:
        try:
            saved = await asyncio.to_thread(annotate_task, task, [cat[c] for c in task['category_ids']],
                                            os.environ.get('DEEPSEEK_API_KEY'), audit / 'annotation')
        except RuntimeError:
            outputs, models = [], []
            for disclosure in task['disclosures']:
                part = {**task, 'disclosures': [disclosure]}
                result = await asyncio.to_thread(annotate_task, part, [cat[c] for c in task['category_ids']],
                    os.environ.get('DEEPSEEK_API_KEY'), audit / 'annotation_by_receipt' / disclosure['event_id'])
                outputs.extend(result['output']['disclosures'])
                models.append(result['model'])
            saved = {'output': {'disclosures': outputs}, 'model': {
                'method': 'strict_per_receipt_annotation_after_failed_task_batch', 'calls': models}}
        attach_annotation(task, saved, cat)
        dump(cached_task_path, task)
    memory, report = await asyncio.to_thread(run_mem0, task, audit, strategy)
    data = input_from_record(task, {'record': str(path), 'record_sha256': hashlib.sha256(original_bytes).hexdigest()})
    native = await store.ingest(data)
    graph = project_graph(data, native, task, cat, {'ontology': ONTOLOGY,
                          'input_sha256': {str(path): hashlib.sha256(original_bytes).hexdigest()}}, 'off')
    graph['privacy_projection_storage'] = await store.persist_projection(graph)
    baseline = apply_privacy_memory(graph, memory, report)
    simplified = simplify_graph(baseline, SimplificationConfig(enabled=True))
    if path.read_bytes() != original_bytes:
        raise ValueError('Execution trace mutated')
    return {'task': entry['task'], 'status': 'complete', 'execution': trace['result'],
            'recipients': task['recipient_resolution'], 'mem0_report': report,
            'comparison': {'same_mem0_memory': True, 'same_graphiti_ingestion': True,
                           '0': {'nodes': len(baseline['nodes']), 'edges': len(baseline['edges'])},
                           '12345': {'nodes': len(simplified['nodes']), 'edges': len(simplified['edges'])},
                           'privacy_gain_bits': None},
            'versions': {'0': baseline, '12345': simplified}}


def write_drawings(folder, bundle):
    for arm in ('0', '12345'):
        lines = ['# 47任务隐私图：' + arm, '', 'Mem0 为两个版本共同的默认处理阶段。', '']
        for key, entry in bundle['tasks'].items():
            lines += ['## ' + key, '']
            if entry['status'] == 'complete':
                graph = entry['versions'][arm]
                drawing = terminal(graph)
                lines += ['```text', drawing, '```', '']
            else:
                lines += ['状态：' + entry['status'], '']
        (folder / ('47任务隐私图_' + arm + '.md')).write_text('\n'.join(lines), encoding='utf-8')


def prepare_failed(folder, bundle, strategy):
    """Repair failed annotations/Mem0 in separate stores, without touching the
    live coordinator summary or its graph database."""
    from .annotation import annotate_task
    from .build import attach_annotation
    from .graphs import make_graph
    from .recipients import attach_resolved_receivers
    def one(key, entry):
        audit = folder / '_audit/analysis' / key.replace('/', '_')
        path = folder / '_audit/execution' / key.replace('/', '_') / 'graph.json'
        trace = read(path)
        cached = audit / 'annotated_task.json'
        if cached.exists() and (audit / 'privacy_text/report.json').exists():
            old = read(cached)
            if all(d['source_graph_sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
                   for d in old['disclosures']):
                return key
        task = {**entry['task'], 'execution_status': '已执行', 'annotation_status': 'pending',
                'official_task_success': trace['result']['utility'], 'model_annotation': None}
        attach_resolved_receivers(task, trace, path)
        categories = {k: make_graph(k, [key]) for k in task['category_ids']}
        try:
            saved = annotate_task(task, list(categories.values()), os.environ.get('DEEPSEEK_API_KEY'), audit / 'annotation')
        except RuntimeError:
            outputs, models = [], []
            for disclosure in task['disclosures']:
                part = {**task, 'disclosures': [disclosure]}
                result = annotate_task(part, list(categories.values()), os.environ.get('DEEPSEEK_API_KEY'),
                                       audit / 'annotation_by_receipt' / disclosure['event_id'])
                outputs.extend(result['output']['disclosures'])
                models.append(result['model'])
            saved = {'output': {'disclosures': outputs}, 'model': {
                'method': 'strict_per_receipt_annotation_after_failed_task_batch', 'calls': models}}
        attach_annotation(task, saved, categories)
        dump(audit / 'annotated_task.json', task)
        run_mem0(task, audit, strategy)
        return key
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(one, key, entry): key for key, entry in bundle['tasks'].items()
                   if entry['status'] == 'analysis_failed'}
        for future in as_completed(futures):
            try:
                print('PREPARED_RETRY ' + future.result(), flush=True)
            except Exception as exc:
                print('PREPARATION_FAILED ' + futures[future] + ' ' + str(exc), flush=True)


async def run_analysis(folder, bundle, strategy):
    from .graphs import make_graph
    from .graphiti_backend import GraphitiConfig, GraphitiStore
    categories = {key: make_graph(key, [t['task']['task_key'] for t in bundle['tasks'].values()
                                      if key in t['task']['category_ids']]) for key in CATEGORIES}
    store = GraphitiStore(GraphitiConfig.from_env(), folder / '_audit/graphiti')
    try:
        await store.initialize()
        for key, entry in list(bundle['tasks'].items()):
            if entry['status'] == 'complete':
                continue
            trace = folder / '_audit/execution' / key.replace('/', '_') / 'graph.json'
            if not trace.exists():
                continue
            print('ANALYSIS_START ' + key, flush=True)
            try:
                bundle['tasks'][key] = await analysis_task(folder, entry, store, categories, strategy)
                print('ANALYSIS_DONE ' + key, flush=True)
            except Exception as exc:
                import traceback
                entry.update(status='analysis_failed', error={'type': type(exc).__name__, 'message': str(exc)})
                (folder / '_audit' / (key.replace('/', '_') + '_analysis_error.txt')).write_text(traceback.format_exc(), encoding='utf-8')
                print('ANALYSIS_FAILED ' + key + ' ' + type(exc).__name__, flush=True)
            save(folder, bundle)
            write_drawings(folder, bundle)
    finally:
        await store.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--seed', type=int, default=20261104)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--execute-one')
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--privacy-text', choices=('mem0', 'none'), default='mem0')
    parser.add_argument('--analysis-only', action='store_true')
    parser.add_argument('--prepare-failed', action='store_true')
    args = parser.parse_args(argv)
    load_dotenv(args.env_file or ROOT / '.env', override=False)
    folder = args.output_dir.resolve()
    if args.execute_one:
        execute_one(folder, args.execute_one)
        return
    bundle = prepare(folder, args.seed, args.privacy_text)
    if bundle['config']['privacy_text_compression'] != args.privacy_text:
        raise ValueError('Do not change Mem0 condition in an existing experiment directory')
    bundle['config']['privacy_text_compression'] = args.privacy_text
    print(json.dumps({'selection': bundle['selection']['suite_counts'], 'summary': bundle['summary']}, ensure_ascii=False), flush=True)
    if args.prepare_only:
        save(folder, bundle)
        write_drawings(folder, bundle)
        return
    if not os.environ.get('DEEPSEEK_API_KEY', '').strip():
        bundle['runtime_status'] = 'awaiting_DEEPSEEK_API_KEY_no_model_calls_or_task_executions'
        save(folder, bundle)
        write_drawings(folder, bundle)
        print('CREDENTIAL_MISSING: prepared selection and resumable pipeline; no fake graphs generated', flush=True)
        return
    if args.prepare_failed:
        prepare_failed(folder, bundle, args.privacy_text)
        return
    bundle['runtime_status'] = 'running'
    # Recover completed workers even if the coordinator was interrupted while
    # saving its summary (e.g. transient Windows file-sharing locks).
    for key, entry in bundle['tasks'].items():
        result_path = folder / '_audit/execution' / key.replace('/', '_') / 'result.json'
        if entry['status'] != 'complete' and result_path.exists():
            entry.update(status='executed', execution=read(result_path))
    save(folder, bundle)
    if not args.analysis_only:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(worker_execution, folder, e['task'], args.env_file): key
                       for key, e in bundle['tasks'].items() if e['status'] != 'complete'}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    result = future.result()
                    bundle['tasks'][key].update(status='executed', execution=result)
                    print('EXECUTED ' + key + ' utility=' + str(result['utility']), flush=True)
                except Exception as exc:
                    bundle['tasks'][key].update(status='execution_failed', error={'type': type(exc).__name__, 'message': str(exc)})
                    print('EXECUTION_FAILED ' + key, flush=True)
                save(folder, bundle)
    asyncio.run(run_analysis(folder, bundle, args.privacy_text))
    bundle['runtime_status'] = 'complete' if bundle['summary']['completed'] == 47 else 'incomplete_with_recorded_failures'
    save(folder, bundle)
    write_drawings(folder, bundle)
    print(json.dumps(bundle['summary'], ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
