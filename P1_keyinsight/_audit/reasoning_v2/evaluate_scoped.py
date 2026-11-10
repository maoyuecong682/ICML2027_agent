"""Explicit-subject questions on the original 50 tasks, graph 0, no network.

Separate output from the frozen CSV and legacy field-wide evaluation.
Questions/gold come only from category definitions and pre-execution data.
"""
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

from p0_privacy.background_recovery import BackgroundRecovery
from p0_privacy.inference import VERSION as RECOVERY_VERSION
from p0_privacy.public_background import DEFAULT_OUTPUT, recovery_context
from p0_privacy.recovery import memory_from_graph
from p0_privacy.recovery_supplement import BATCH, load_jobs
from p0_privacy.scoped_recovery import VERSION, category_fields, questions, score_answers

OUTPUT = HERE / 'scoped_evaluation'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def evaluate(key, job, background):
    # This evaluator reads private data; the recoverer is passed only the
    # physical receiver input constructed below, with no question text/gold.
    private_bytes = job['environment_path'].read_bytes()
    qs = questions(job['task'], json.loads(private_bytes))
    memory = memory_from_graph(job['versions']['0'], shared=True)
    receiver_ids = sorted(receiver['receiver_id'] for receiver in memory['receivers'])
    result = {'questions': qs, 'receivers': receiver_ids, 'conditions': {},
              'category_fields': sorted(category_fields(job['task'])),
              'reference_source_sha256': hashlib.sha256(private_bytes).hexdigest(),
              'status': 'scored' if qs and receiver_ids else 'no_scoped_reference' if not qs else 'no_receivers'}
    covered_fields = {q['field'] for q in qs}
    if covered_fields.intersection({'calendar_start_time', 'calendar_end_time'}):
        covered_fields.add('calendar_schedule')
    result['unscored_category_fields'] = sorted(category_fields(job['task']) - covered_fields)
    if result['status'] != 'scored':
        return result
    engine = BackgroundRecovery(background)
    for condition in ('none', 'local', 'shared'):
        # Exactly one shared view, anchored at a member, honoring the explicit
        # group from memory_from_graph; do not count the same union per member.
        members = receiver_ids if condition != 'shared' else receiver_ids[:1]
        targets = [{'probe_id': key + '::' + rid + '::' + q['question_id'],
                    'receiver_id': rid, 'field': q['field'], 'subject': q['subject']}
                   for rid in members for q in qs]
        context = recovery_context(memory, targets, background, condition)
        predictions = []
        qid_by_probe = {key + '::' + rid + '::' + q['question_id']: q['question_id']
                        for rid in members for q in qs}
        for item in context['receiver_inputs']:
            rows = engine.recover(item['memory'], item['targets'])
            predictions.extend(dict(row, question_id=qid_by_probe[row['probe_id']]) for row in rows)
        dump(OUTPUT / 'calls' / key.replace('/', '_') / (condition + '.json'), {
            'receiver_inputs': context['receiver_inputs'], 'predictions': predictions,
            'public_background_sha256': background['content_sha256'], 'llm_calls': 0})
        result['conditions'][condition] = score_answers(predictions, qs)
    return result


def main():
    if RECOVERY_VERSION != 'deterministic-relations-v2':
        raise RuntimeError('Historical v2 output is preserved. Use reasoning_v3/evaluate.py for the active recoverer.')
    preserved = [BATCH / '47任务top1恢复评估.json', BATCH / '47任务双版本隐私图.json',
                 ROOT / 'P1_keyinsight/联合接收者_新增消息对照.csv']
    original_hashes = {str(path.relative_to(ROOT)): sha(path) for path in preserved}
    background = json.loads(DEFAULT_OUTPUT.read_bytes())
    jobs = load_jobs()
    assert len(jobs) == 50
    tasks = {}
    with patch('socket.socket.connect', side_effect=AssertionError('Network disabled during scoped evaluation')):
        for key, job in sorted(jobs.items()):
            tasks[key] = evaluate(key, job, background)
            task = tasks[key]
            print(key, task['status'], len(task['questions']), flush=True)
    assert original_hashes == {str(path.relative_to(ROOT)): sha(path) for path in preserved}
    strict, proof_backed = [], []
    counts = Counter()
    coverage = Counter()
    for key, task in tasks.items():
        counts['questions'] += len(task['questions'])
        if task['status'] != 'scored':
            continue
        counts['scored_tasks'] += 1
        if len(task['receivers']) > 1:
            counts['scored_multi_receiver_tasks'] += 1
        local = task['conditions']['local']
        for q in task['questions']:
            coverage[q['field']] += 1
            candidates = [r for r in local if r['question_id'] == q['question_id']]
            union = next(r for r in task['conditions']['shared'] if r['question_id'] == q['question_id'])
            if union['top1_recovery'] and not any(row['top1_recovery'] for row in candidates):
                entry = {'task': key, 'question': q, 'prediction': union}
                strict.append(entry)
                if union.get('requires_joint_evidence'):
                    proof_backed.append(entry)
    total_multi = sum(len(t['receivers']) > 1 for t in tasks.values())
    aggregate = {}
    for condition in ('none', 'local', 'shared'):
        rows = [row for task in tasks.values() for row in task['conditions'].get(condition, [])]
        aggregate[condition] = {'correct': sum(row['top1_recovery'] for row in rows), 'probes': len(rows)}
    # For comparability, count a question once for local-any vs one union.
    any_local = sum(any(r['top1_recovery'] for r in task['conditions']['local'] if r['question_id'] == q['question_id'])
                    for task in tasks.values() if task['status'] == 'scored' for q in task['questions'])
    strict_tasks = len({entry['task'] for entry in strict})
    summary = {'question_version': VERSION, 'recovery_version': RECOVERY_VERSION,
               'llm_calls': 0, 'network_disabled': True, 'graph_arm': '0',
               'tasks': 50, 'multi_receiver_tasks': total_multi, **dict(counts),
               'question_fields': dict(sorted(coverage.items())), 'aggregate': aggregate,
               'local_any_correct_questions': any_local,
               'joint_correct_questions': aggregate['shared']['correct'],
               'strict_joint_task_count': strict_tasks,
               'strict_joint_task_rate_scored': strict_tasks / counts['scored_tasks'] if counts['scored_tasks'] else None,
               'strict_joint_task_rate_scored_multi_receiver': strict_tasks / counts['scored_multi_receiver_tasks'] if counts['scored_multi_receiver_tasks'] else None,
               'unscored_tasks': {key: task['status'] for key, task in tasks.items() if task['status'] != 'scored'},
               'strict_joint_question_count': len(strict), 'proof_backed_joint_question_count': len(proof_backed),
               'strict_joint_results': strict, 'proof_backed_joint_results': proof_backed,
               'reference_independent_of_outgoing_trace_and_predictions': True,
               'original_artifacts_unchanged_sha256': original_hashes,
               'limitations': [
                   'Questions enumerate supported subjects in pre-execution private data for category-declared fields; unimplemented fields are not scored.',
                   'Tasks without a scoped reference are excluded from rate denominators, never counted as recovery failures.',
                   'The exact person/event/record identifier is part of the question and is assumed known to the receiver.',
                   'Known-before state is explicit in time-varying questions; later updates are not interchangeable with original values.',
                   'The scored graph contains compressed active memory, not all raw tool responses.',
                   'Local probe counts repeat questions per receiver; compare local-any with one shared answer per question.',
                   'Strict outcome alone may reflect top-1 ranking; proof-backed count additionally requires all minimal proofs to span receivers.'],
               'code': {name: sha(P0 / 'p0_privacy' / name) for name in (
                   'inference.py', 'knowledge_merge.py', 'recovery.py', 'background_recovery.py', 'scoped_recovery.py')}}
    dump(OUTPUT / 'results.json', {'summary': summary, 'tasks': tasks})
    dump(OUTPUT / 'summary.json', summary)
    print(json.dumps({k: v for k, v in summary.items() if k not in {
        'strict_joint_results', 'proof_backed_joint_results', 'code', 'original_artifacts_unchanged_sha256', 'limitations'}},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
