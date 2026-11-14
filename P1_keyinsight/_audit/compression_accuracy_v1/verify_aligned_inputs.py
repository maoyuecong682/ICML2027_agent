"""Audit paired input repair without credentials, model calls or label changes."""
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / 'P0_agentdojo'))
from p0_privacy.input_alignment import VERSION, annotate_observations, parsed_content
from p0_privacy.input_alignment import pointer_value, subject_bindings, validate_bindings


def load(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def content(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def verify():
    output = HERE / 'aligned_inputs_v2'
    manifest = load(output / 'manifest.json')
    cohort = load(output / 'cohort_20.json')
    original_protocol = load(HERE / 'protocol.json')
    assert len(manifest['tasks']) == 50 and len(cohort['tasks']) == 20
    assert len({i['task'] for i in cohort['tasks']}) == 20
    selected = {x['task'] for x in cohort['tasks']}
    assert selected <= {x['task'] for x in manifest['tasks']}
    original_items = {x['task']: x for x in original_protocol['manifest']}
    total_bindings, total_messages, previews = 0, 0, 0
    for item in manifest['tasks']:
        folder = output / item['folder']
        source = ROOT / item['source_folder']
        history = load(folder / 'observations.json')
        candidate = load(folder / 'candidate_message.json')
        original_history = load(source / 'observations.json')
        original_candidate = load(source / 'candidate_message.json')
        assert len(history) == len(original_history)
        for new, old in zip(history + [candidate], original_history + [original_candidate]):
            assert {k: new[k] for k in old} == old
            assert new['state'] in {'before', 'after', 'unknown'}
            assert 'state_basis' in new and 'effect_status' in new
        assert (folder / 'targets.json').read_bytes() == (source / 'targets.json').read_bytes()
        assert sha(folder / 'targets.json') == item['targets_sha256']
        assert sha(folder / 'candidate_message.json') == item['candidate_sha256']
        assert sha(source / 'evaluator_only_cases.json') == item['reference_sha256']
        for name, digest in original_items[item['task']]['input_sha256'].items():
            assert sha(source / name) == digest
        annotated = annotate_observations(item['task'], original_history + [original_candidate])
        bindings = subject_bindings(item['task'], annotated)
        validate_bindings(annotated, bindings)
        expected_history = [b for b in bindings if b['message_id'] != candidate['message_id']]
        assert candidate['subject_bindings'] == [b for b in bindings if b['message_id'] == candidate['message_id']]
        original_scored_inputs = load(source / 'frozen_inputs.json')
        for arm in ['0', '12345', 'TRAIL']:
            assert sha(source / 'arms' / arm / 'memory.json') == original_scored_inputs['arm_memory_sha256'][arm]
            memory = load(folder / 'arms' / arm / 'memory.json')
            assert sha(folder / 'arms' / arm / 'memory.json') == item['arm_sha256'][arm]
            assert memory['input_alignment_version'] == VERSION
            if arm != 'TRAIL':
                records = [n for n in memory['nodes'] if n['type'] in {'actual_disclosure', 'tool_response'}]
                active_messages = {(n['event_id'], n['receiver_id'], 'S' if n['type'] == 'tool_response' else 'R') for n in records}
                expected = [b for b in expected_history if (b['event_id'], b['receiver_id'], b['direction']) in active_messages]
                assert memory['subject_bindings'] == expected
                for n in records:
                    side = 'S' if n['type'] == 'tool_response' else 'R'
                    o = next(x for x in history if x['event_id'] == n['event_id'] and x['direction'] == side)
                    for key in ['state', 'state_basis', 'effect_status', 'observation_order']:
                        assert n[key] == o[key]
                    assert (n['content'] if side == 'S' else n['parameters']) == o['content']
            else:
                parent = load(folder / 'arms/12345/memory.json')
                assert memory['subject_bindings'] == parent['subject_bindings']
                columns = {name: i for i, name in enumerate(memory['record_columns'])}
                for row in memory['records']:
                    eid, side = row[columns['event_id']], row[columns['direction']]
                    o = next(x for x in history if x['event_id'] == eid and x['direction'] == side)
                    for key in ['state', 'state_basis', 'effect_status', 'observation_order']:
                        assert row[columns[key]] == o[key]
            preview = load(folder / 'arms' / arm / 'request_preview.json')
            assert sha(folder / 'arms' / arm / 'request_preview.json') == item['request_sha256'][arm]
            original_request = load(source / 'arms' / arm / 'request.json')
            assert preview['messages'][0] == original_request['messages'][0]
            payload = json.loads(preview['messages'][1]['content'])
            assert set(payload) == {'shared_history', 'candidate_message', 'questions'}
            assert payload['shared_history'] == memory
            assert payload['candidate_message'] == candidate
            assert payload['questions'] == load(source / 'targets.json')
            assert not (folder / 'arms' / arm / 'response_1.json').exists()
            assert not (folder / 'arms' / arm / 'prediction.json').exists()
            previews += 1
        total_bindings += len(bindings)
        total_messages += len(annotated)
    # Reproduce the two concrete failures previously inspected by the user.
    file_case = output / 'tasks/workspace_user_task_25'
    file_memory = load(file_case / 'arms/0/memory.json')
    file_binding = next(b for b in file_memory['subject_bindings']
                        if b['subject'] == 'drive:file:4' and b['direction'] == 'S')
    source = next(o for o in load(file_case / 'observations.json') if o['message_id'] == file_binding['message_id'])
    assert pointer_value(parsed_content(source), file_binding['identifier']['path']) == '4'
    assert pointer_value(parsed_content(source), file_binding['field_paths']['file_metadata'][0]) == 'quarterly-goals-update.docx'
    message_case = output / 'tasks/slack_user_task_10'
    message_memory = load(message_case / 'arms/0/memory.json')
    message_binding = next(b for b in message_memory['subject_bindings']
                           if b['subject'] == 'response:app:slack:slack:e0009/0:message')
    source = next(o for o in load(message_case / 'observations.json') if o['message_id'] == message_binding['message_id'])
    assert pointer_value(parsed_content(source), message_binding['record_path'])['sender'] == 'Alice'
    report = {'tasks_checked': 50, 'messages_annotated': total_messages, 'bindings_grounded': total_bindings,
        'request_previews': previews, 'cohort_tasks': 20, 'cohort_request_previews': 60,
        'new_model_calls': 0, 'questions_references_and_original_content_unchanged': True,
        'original_scored_inputs_unchanged': True, 'three_arm_states_and_mappings_verified': True,
        'no_candidate_return_or_future_message_injected': True,
        'file4_and_slack_message_examples_verified': True,
        'input_only_ready_waiting_for_confirmation': True,
        'cohort_suite_counts': {suite: sum(x['task'].startswith(suite + '/') for x in cohort['tasks'])
                                for suite in ['banking', 'slack', 'travel', 'workspace']},
        'cohort_multi_receiver_tasks': sum(len(x['receivers']) > 1 for x in cohort['tasks'])}
    (output / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    return report


if __name__ == '__main__':
    verify()
