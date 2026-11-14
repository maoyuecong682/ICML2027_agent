"""Run the prepared 20-task cohort ONLY after the user's confirmation."""
import argparse
import concurrent.futures
import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path

from run_api import detect_one, key
import run_api

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / 'aligned_inputs_v2'


def load(path):
    return json.loads(path.read_bytes())


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def score(cohort):
    tasks, totals = [], {a: Counter() for a in ['0', '12345', 'TRAIL']}
    for item in cohort['tasks']:
        cases = load(HERE / item['folder'] / 'evaluator_only_cases.json')
        labels = {c['query_id']: c['risk'] for c in cases}
        result = {'task': item['task'], 'positives': sum(labels.values()),
                  'negatives': len(labels) - sum(labels.values()), 'arms': {}}
        for arm in totals:
            folder = OUTPUT / item['folder'] / 'arms' / arm
            predictions = load(folder / 'prediction.json')
            observed = {p['query_id']: p['risk'] for p in predictions['judgments']}
            assert set(labels) == set(observed)
            matrix = Counter()
            for q, true in labels.items():
                matrix['TP' if true and observed[q] else 'FN' if true else 'FP' if observed[q] else 'TN'] += 1
            sources = [load(p) for p in folder.glob('response_*.json')]
            tokens = sum(p['usage']['total_tokens'] for p in sources)
            assert tokens == predictions['usage']['total_tokens']
            stats = {name: matrix[name] for name in ['TP', 'FN', 'FP', 'TN']}
            stats.update(false_negative_rate_percent=100 * matrix['FN'] / result['positives'] if result['positives'] else None,
                         false_positive_rate_percent=100 * matrix['FP'] / result['negatives'] if result['negatives'] else None,
                         total_tokens=tokens, api_attempts=len(sources))
            result['arms'][arm] = stats
            totals[arm].update({k: v for k, v in stats.items() if k not in
                               {'false_negative_rate_percent', 'false_positive_rate_percent'}})
        tasks.append(result)
    means = {}
    for arm, total in totals.items():
        fnr = [t['arms'][arm]['false_negative_rate_percent'] for t in tasks
               if t['arms'][arm]['false_negative_rate_percent'] is not None]
        fpr = [t['arms'][arm]['false_positive_rate_percent'] for t in tasks
               if t['arms'][arm]['false_positive_rate_percent'] is not None]
        means[arm] = {'mean_task_false_negative_rate_percent': statistics.mean(fnr) if fnr else None,
                      'mean_task_false_positive_rate_percent': statistics.mean(fpr) if fpr else None,
                      'valid_tasks_for_false_negative_mean': len(fnr),
                      'valid_tasks_for_false_positive_mean': len(fpr),
                      'mean_detection_tokens_per_task': total['total_tokens'] / len(tasks),
                      'pooled_false_negative_rate_percent': 100 * total['FN'] / (total['TP'] + total['FN'])
                          if total['TP'] + total['FN'] else None,
                      'pooled_false_positive_rate_percent': 100 * total['FP'] / (total['TN'] + total['FP'])
                          if total['TN'] + total['FP'] else None, **dict(total)}
    dump(OUTPUT / 'results20.json', tasks)
    dump(OUTPUT / 'averages20.json', {'tasks': len(tasks), 'arms': means,
        'NA_policy': 'exclude tasks without the corresponding class; retain valid task counts',
        'token_scope': 'actual API prompt+completion usage, averaged over the 20 tasks'})
    print(json.dumps(means, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=5)
    args = parser.parse_args()
    cohort = load(OUTPUT / 'cohort_20.json')
    assert len(cohort['tasks']) == 20
    # Validate the frozen previews before constructing a client or loading a key.
    for item in cohort['tasks']:
        folder = OUTPUT / item['folder']
        assert hashlib.sha256((folder / 'targets.json').read_bytes()).hexdigest() == item['targets_sha256']
        assert hashlib.sha256((folder / 'candidate_message.json').read_bytes()).hexdigest() == item['candidate_sha256']
        assert hashlib.sha256((HERE / item['folder'] / 'evaluator_only_cases.json').read_bytes()).hexdigest() == item['reference_sha256']
        for arm in ['0', '12345', 'TRAIL']:
            assert hashlib.sha256((folder / 'arms' / arm / 'memory.json').read_bytes()).hexdigest() == item['arm_sha256'][arm]
            assert hashlib.sha256((folder / 'arms' / arm / 'request_preview.json').read_bytes()).hexdigest() == item['request_sha256'][arm]
            preview = load(folder / 'arms' / arm / 'request_preview.json')
            request = run_api.make_detection_request(load(folder / 'arms' / arm / 'memory.json'),
                load(folder / 'candidate_message.json'), load(folder / 'targets.json'))
            assert request == preview
    run_api.HERE = OUTPUT
    api_key = key()
    jobs = [(item, arm) for item in cohort['tasks'] for arm in ['0', '12345', 'TRAIL']]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(detect_one, item, arm, api_key) for item, arm in jobs]
        for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
            print('DETECT', f'{i}/60', json.dumps(future.result(), ensure_ascii=False), flush=True)
    score(cohort)


if __name__ == '__main__':
    main()
