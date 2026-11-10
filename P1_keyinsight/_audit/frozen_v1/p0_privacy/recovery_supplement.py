"""Run rule-only recovery with public background on all 50 tasks and three views.

No model client, API credentials, or network calls are used in this experiment.
"""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path

from .public_background import DEFAULT_OUTPUT, digest, recovery_context, validate_background
from .recovery import memory_from_graph
from .background_recovery import BackgroundRecovery
from .recovery_evaluation import aggregate as aggregate_existing, references, score, write_report as write_existing_report

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / 'outputs/batch47_20261104'
OUTPUT = BATCH / '50任务补充恢复评估.json'
REPORT = BATCH / '50任务补充恢复评估.md'


def stats(rows):
    return {'correct': sum(r['top1_recovery'] for r in rows), 'probes': len(rows),
            'top1_rate': sum(r['top1_recovery'] for r in rows) / len(rows) if rows else None,
            'rows': rows}


def load_jobs():
    bundle = json.loads((BATCH / '47任务双版本隐私图.json').read_bytes())
    jobs = {}
    for key, entry in bundle['tasks'].items():
        env = BATCH / '_audit/execution' / key.replace('/', '_') / 'environment.before.json'
        jobs[key] = {'cohort': 'batch47', 'task': entry['task'], 'versions': entry['versions'],
                     'environment_path': env, 'conditions': ['none', 'local', 'shared']}
    for arm, name in [('0', '任务隐私图.json'), ('12345', '简化隐私图.json')]:
        graphs = json.loads((ROOT / 'outputs/graphiti_privacy' / name).read_bytes())['graphs']
        for number in (14, 22, 31):
            key = f'workspace/user_task_{number}'
            graph = graphs[key]
            job = jobs.setdefault(key, {'cohort': 'original3', 'task': graph['task'], 'versions': {},
                'environment_path': ROOT / 'runs/p0_20261028_seed20261028' /
                key.replace('/', '_') / 'environment.before.json',
                'conditions': ['none', 'local', 'shared']})
            job['versions'][arm] = graph
    return jobs


def evaluate(key, job, background, audit):
    recoverer = BackgroundRecovery(background)
    env_bytes = job['environment_path'].read_bytes()
    gold, omitted = references(job['task'], json.loads(env_bytes))
    result = {'cohort': job['cohort'], 'status': 'complete',
              'reference_source_sha256': hashlib.sha256(env_bytes).hexdigest(),
              'fields': sorted(gold), 'unscored_fields_no_reference_rule': omitted,
              'conditions': {},
              'source_graph_text_compression': {a: g.get('privacy_text_compression')
                                                for a, g in job['versions'].items()}}
    probe_ids = None
    for arm, graph in job['versions'].items():
        memory = memory_from_graph(graph, shared=True)
        targets = [{'probe_id': key + '::' + r['receiver_id'] + '::' + field,
                    'receiver_id': r['receiver_id'], 'field': field}
                   for r in memory['receivers'] for field in sorted(gold)]
        if probe_ids is None:
            probe_ids = [t['probe_id'] for t in targets]
        if [t['probe_id'] for t in targets] != probe_ids:
            raise ValueError('Two graph arms must have the same probes')
        result['conditions'][arm] = {}
        for condition in job['conditions']:
            context = recovery_context(memory, targets, background, condition)
            predictions = []
            signatures = []
            for receiver_input in context['receiver_inputs']:
                predictions.extend(recoverer.recover(receiver_input['memory'], receiver_input['targets']))
                signatures.append(digest(receiver_input))
            task_audit = audit / key.replace('/', '_')
            task_audit.mkdir(parents=True, exist_ok=True)
            (task_audit / f'{arm}_{condition}.json').write_text(json.dumps({
                'receiver_inputs': context['receiver_inputs'], 'predictions': predictions,
                'public_background_sha256': background['content_sha256'],
                'public_background_used_by_recoverer': True,
                'llm_calls': 0,
            }, ensure_ascii=False, indent=2), encoding='utf-8')
            scored = stats(score(predictions, gold))
            scored['receiver_input_sha256'] = signatures
            result['conditions'][arm][condition] = scored
    return result


def aggregate(tasks):
    output = {}
    for cohort in ('batch47', 'original3'):
        output[cohort] = {}
        for arm in ('0', '12345'):
            output[cohort][arm] = {}
            for condition in ('none', 'local', 'shared'):
                rows = [row for t in tasks.values() if t.get('cohort') == cohort and t.get('status') == 'complete'
                        for row in t['conditions'][arm].get(condition, {}).get('rows', [])]
                if rows:
                    output[cohort][arm][condition] = {k: v for k, v in stats(rows).items() if k != 'rows'}
    return output


def write_report(result):
    lines = ['# 50任务补充恢复评估', '',
        '50个任务均运行无记忆/local/shared三组，两版图均评估；47任务local/shared同步刷新以保持恢复器一致。',
        '全部使用固定规则加公共背景候选，无LLM、无API调用。无记忆时接收者事实为空，但允许公共背景猜测。',
        '候选由工具服务定义、隐私字段定义和公开记录生成，按公开属性出现次数降序、值的固定顺序打破平局。',
        '这不是用户群体统计先验；公开商户或航班资料不证明用户与这些对象存在联系。',
        '每次调用只提供一个接收者可见的事实，不提供任务原文、私有环境、参考答案或其他接收者隐藏记忆。',
        '单接收者local/shared可见信息相同，使用同一套确定性规则。',
        '指标为接收者×字段微平均；一个首选答案命中参考集合记1。它不是披露概率。', '',
        '三组均使用相同的记忆优先、无记忆候选时转公共背景的规则；无候选则弃答。',
        '原3任务复用其已有图；这些旧图没有批量47任务的Mem0压缩元数据，不将两批图称为同一配置。', '',
        '| 数据组 | 图版本 | 条件 | 正确/目标数 | Top-1 |', '|---|---|---|---:|---:|']
    for cohort, arms in result['aggregate'].items():
        for arm, conditions in arms.items():
            for condition, s in conditions.items():
                lines.append(f"| {cohort} | {arm} | {condition} | {s['correct']}/{s['probes']} | {s['top1_rate']:.2%} |")
    lines += ['', '| 任务 | 图版本 | 无记忆 | local | shared |', '|---|---|---:|---:|---:|']
    for key, task in result['tasks'].items():
        if task['status'] != 'complete':
            lines.append(f"| {key} | — | {task['status']} | — | — |")
            continue
        for arm, conditions in task['conditions'].items():
            cells = []
            for c in ('none', 'local', 'shared'):
                s = conditions.get(c)
                cells.append(f"{s['correct']}/{s['probes']} ({s['top1_rate']:.2%})"
                             if s and s['top1_rate'] is not None else '未运行')
            lines.append('| ' + key + ' | ' + arm + ' | ' + ' | '.join(cells) + ' |')
    lines += ['', '未建立参考规则的字段不计入分母；执行失败单列，不按0分充数。',
              '输入和规则预测保存在_audit/rule_background_recovery，参考答案不进入恢复器。',
              '先前LLM实验已作废并归档，不进入本报告统计。']
    REPORT.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def merge_into_existing47(supplement):
    """Keep the existing top-level schema, task wrapper and original table columns."""
    if supplement['predictor'] != 'deterministic_rules_with_public_background_no_llm' or supplement['llm_calls'] != 0:
        raise ValueError('Only verified rule-only results may be merged')
    path = BATCH / '47任务top1恢复评估.json'
    result = json.loads(path.read_bytes())
    original_keys = set(result)
    archive = BATCH / '_audit/rule_background_recovery'
    for source in (path, path.with_suffix('.md')):
        backup = archive / ('pre_merge_' + source.name)
        if not backup.exists():
            backup.write_bytes(source.read_bytes())
    for key, task in supplement['tasks'].items():
        if task['status'] != 'complete':
            raise ValueError('Incomplete supplement')
        entry = result['tasks'].setdefault(key, {
            'status': 'evaluated', 'graph_sha256': task['input_sha256'],
            'recovery': {'status': 'complete',
                'target_definition': 'one valid value per category-declared privacy field',
                'reference_independent_of_predictions_and_outgoing_parameters': True,
                'reference_source_sha256': task['reference_source_sha256'],
                'fields': task['fields'], 'unscored_fields_no_reference_rule': task['unscored_fields_no_reference_rule'],
                'conditions': {'0': {}, '12345': {}}}})
        if entry['recovery']['reference_source_sha256'] != task['reference_source_sha256']:
            raise ValueError('Reference source changed')
        for arm, conditions in task['conditions'].items():
            for name, condition in conditions.items():
                fields = task['fields']
                field_hits = [max((r['top1_recovery'] for r in condition['rows'] if r['field'] == field), default=0)
                              for field in fields]
                entry['recovery']['conditions'][arm][name] = {
                    **condition,
                    'task_field_any_receiver_top1': sum(field_hits) / len(field_hits) if field_hits else None,
                    'sharing': 'explicit_hypothetical_all_services' if name == 'shared' else 'none'}
    result['predictor'] = 'deterministic rules + frozen public-record frequency fallback; no LLM; memory-first in all three conditions'
    result['aggregate'] = aggregate_existing(result['tasks'])
    result['coverage'] = {'selected_tasks': len(result['tasks']),
        'evaluated_tasks': sum(t['status'] == 'evaluated' for t in result['tasks'].values()),
        'awaiting_graph': sum(t['status'] == 'awaiting_graph' for t in result['tasks'].values())}
    result['paired_candidate_changes'] = []
    for key in sorted(result['tasks']):
        conditions = result['tasks'][key]['recovery']['conditions']
        for name in ('none', 'local', 'shared'):
            for left, right in zip(conditions['0'][name]['rows'], conditions['12345'][name]['rows']):
                if left['probe_id'] != right['probe_id']:
                    raise ValueError('Probe mismatch')
                if left['top1_guess'] != right['top1_guess']:
                    result['paired_candidate_changes'].append({'task': key, 'sharing': name,
                        'probe_id': left['probe_id'], '0_guess': left['top1_guess'], '12345_guess': right['top1_guess'],
                        '0_score': left['top1_recovery'], '12345_score': right['top1_recovery'],
                        '0_evidence': left['evidence'], '12345_evidence': right['evidence']})
    result['protocol_sha256'] = supplement['protocol_sha256']
    assert set(result) == original_keys
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    write_existing_report(BATCH, result)
    # The graph bundle still contains exactly the selected 47 tasks. Mirror only
    # their evaluations; the three old graphs are not added to that selection.
    bundle_path = BATCH / '47任务双版本隐私图.json'
    bundle = json.loads(bundle_path.read_bytes())
    subset = {k: result['tasks'][k] for k in bundle['tasks']}
    for key in bundle['tasks']:
        bundle['tasks'][key]['recovery_evaluation'] = result['tasks'][key]['recovery']
    bundle['top1_evaluation'] = {k: v for k, v in result.items() if k != 'tasks'}
    bundle['top1_evaluation']['aggregate'] = aggregate_existing(subset)
    bundle['top1_evaluation']['coverage'] = {'selected_tasks': len(subset), 'evaluated_tasks': len(subset), 'awaiting_graph': 0}
    bundle['top1_evaluation']['paired_candidate_changes'] = [x for x in result['paired_candidate_changes'] if x['task'] in subset]
    bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--merge', action='store_true', help='Merge into original 47-task evaluation schema')
    args = parser.parse_args(argv)
    background_bytes = DEFAULT_OUTPUT.read_bytes()
    background = json.loads(background_bytes)
    validate_background(background)
    jobs = load_jobs()
    audit = BATCH / '_audit/rule_background_recovery'
    audit.mkdir(parents=True, exist_ok=True)
    frozen = audit / 'public_background.json'
    if frozen.exists() and frozen.read_bytes() != background_bytes:
        raise ValueError('Background changed after experiment freeze')
    frozen.write_bytes(background_bytes)
    protocol = hashlib.sha256(Path(__file__).read_bytes() +
        Path(__file__).with_name('recovery_evaluation.py').read_bytes() +
        Path(__file__).with_name('recovery.py').read_bytes() +
        Path(__file__).with_name('background_recovery.py').read_bytes() +
        Path(__file__).with_name('public_background.py').read_bytes() + background_bytes).hexdigest()
    result = json.loads(OUTPUT.read_bytes()) if OUTPUT.exists() else None
    if result and result.get('predictor') != 'deterministic_rules_with_public_background_no_llm':
        archive = BATCH / '_audit' / ('rule_recovery' if result.get('llm_calls') == 0 else 'llm_recovery')
        archive.mkdir(parents=True, exist_ok=True)
        (archive / 'superseded_without_background_results.json').write_bytes(OUTPUT.read_bytes())
        if REPORT.exists():
            (archive / 'superseded_without_background_report.md').write_bytes(REPORT.read_bytes())
        result = None
    result = result or {'schema': 'privacy.recovery.supplement.v1', 'tasks': {}}
    result.update(protocol_sha256=protocol, predictor='deterministic_rules_with_public_background_no_llm', model=None,
                  llm_calls=0, public_background_used_by_recoverer=True,
                  public_background_sha256=background['content_sha256'],
                  metric='receiver-field micro top1; one value matches independent reference set',
                  comparison_warning='same memory-first + public-background fallback in all three conditions; inventory frequency is not a population prior')
    signatures = {k: digest({'protocol': protocol, 'graphs': j['versions'],
                            'environment_sha256': hashlib.sha256(j['environment_path'].read_bytes()).hexdigest(),
                            'task': j['task'], 'conditions': j['conditions']}) for k, j in jobs.items()}

    def save():
        result['aggregate'] = aggregate(result['tasks'])
        result['coverage'] = {'requested_tasks': len(jobs),
            'completed_tasks': sum(t.get('status') == 'complete' for t in result['tasks'].values()),
            'failed_tasks': sum(t.get('status') == 'failed' for t in result['tasks'].values())}
        temp = OUTPUT.with_suffix('.tmp')
        temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(OUTPUT)
        write_report(result)

    pending = {k: j for k, j in jobs.items() if result['tasks'].get(k, {}).get('input_sha256') != signatures[k]
               or result['tasks'].get(k, {}).get('status') != 'complete'}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(evaluate, k, j, background, audit): k for k, j in pending.items()}
        for future in concurrent.futures.as_completed(futures):
            key = futures[future]
            try:
                evaluated = future.result()
                result['tasks'][key] = {**evaluated, 'input_sha256': signatures[key]}
                print('RECOVERY_COMPLETE ' + key, flush=True)
            except Exception as exc:
                result['tasks'][key] = {'status': 'failed', 'cohort': jobs[key]['cohort'],
                                        'error_type': type(exc).__name__}
                print('RECOVERY_FAILED ' + key + ' ' + type(exc).__name__, flush=True)
            save()
    save()
    print(json.dumps({'coverage': result['coverage'], 'aggregate': result['aggregate']}), flush=True)
    if result['coverage']['completed_tasks'] != len(jobs):
        raise SystemExit(1)
    if args.merge:
        merge_into_existing47(result)


if __name__ == '__main__':
    main()
