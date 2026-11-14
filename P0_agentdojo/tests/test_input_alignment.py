"""Subject pointers, version state, request/result boundaries and source isolation."""
import copy
import unittest

from p0_privacy.input_alignment import annotate_observations, subject_bindings, validate_bindings


def message(eid, side, tool, content, receiver='app:workspace:drive', status='observed'):
    return {'message_id': eid + ':' + side, 'event_id': eid, 'direction': side,
            'receiver_id': receiver, 'tool': tool, 'content': content, 'status': status}


class InputAlignmentTests(unittest.TestCase):
    def test_business_id_uses_record_id_not_array_index_and_preserves_leading_zero(self):
        original = [message('e0004', 'R', 'list_files', {}),
                    message('e0004', 'S', 'list_files',
                            "- id_: '007'\n  filename: first.txt\n  content: one\n"
                            "- id_: '4'\n  filename: second.txt\n  content: two\n")]
        snapshot = copy.deepcopy(original)
        messages = annotate_observations('workspace/user_task_9', original)
        mapped = {b['subject']: b for b in subject_bindings('workspace/user_task_9', messages)}
        self.assertEqual(mapped['drive:file:4']['record_path'], '/1')
        self.assertEqual(mapped['drive:file:4']['identifier'], {'path': '/1/id_', 'value': '4'})
        self.assertEqual(mapped['drive:file:4']['field_paths']['file_metadata'], ['/1/filename'])
        self.assertEqual(mapped['drive:file:007']['record_path'], '/0')
        self.assertNotIn('drive:file:7', mapped)
        self.assertEqual(original, snapshot)

    def test_message_subject_names_exact_return_and_local_record(self):
        receiver = 'app:slack:slack'
        original = [message('e0004', 'R', 'read_channel_messages', {'channel': 'random'}, receiver),
                    message('e0004', 'S', 'read_channel_messages',
                            '- sender: Alice\n  recipient: random\n  body: A message\n', receiver)]
        annotated = annotate_observations('slack/user_task_10', original)
        bindings = subject_bindings('slack/user_task_10', annotated)
        item = next(b for b in bindings if b['subject'] == 'response:app:slack:slack:e0004/0:message')
        self.assertEqual(item['record_path'], '/0')
        self.assertEqual(item['field_paths']['communication_metadata'], ['/0'])
        self.assertEqual(item['message_id'], 'e0004:S')

    def test_state_distinguishes_requested_write_success_and_prior_read(self):
        messages = annotate_observations('workspace/user_task_9', [
            message('e0001', 'R', 'get_file_by_id', {'file_id': '4'}),
            message('e0001', 'S', 'get_file_by_id', "id_: '4'\nfilename: old.txt\ncontent: original"),
            message('e0002', 'R', 'append_to_file', {'file_id': '4', 'content': 'updated'}),
            message('e0002', 'S', 'append_to_file', 'OK'),
            message('e0003', 'R', 'get_file_by_id', {'file_id': '4'}),
            message('e0003', 'S', 'get_file_by_id', "id_: '4'\nfilename: old.txt\ncontent: original updated")])
        self.assertEqual([m['state'] for m in messages], ['before', 'before', 'after', 'after', 'after', 'after'])
        self.assertEqual(messages[2]['effect_status'], 'requested')
        self.assertEqual(messages[3]['effect_status'], 'observed_write_result')
        self.assertEqual(messages[-1]['prior_write_event_id'], 'e0002')
        refs = [b for b in subject_bindings('workspace/user_task_9', messages)
                if b['subject'] == 'drive:file:4']
        self.assertEqual([b['state'] for b in refs], ['before', 'before', 'after', 'after', 'after'])

    def test_a_read_in_another_service_stays_before_after_unrelated_write(self):
        messages = annotate_observations('workspace/user_task_9', [
            message('e0001', 'R', 'send_email', {'recipients': ['a@example.com']}, 'email'),
            message('e0001', 'S', 'send_email', 'OK', 'email'),
            message('e0002', 'R', 'get_file_by_id', {'file_id': '4'}),
            message('e0002', 'S', 'get_file_by_id', "id_: '4'\nfilename: read.txt")])
        self.assertEqual(messages[-1]['state'], 'before')

    def test_error_has_no_successful_record_mapping_or_future_result(self):
        original = [message('e0001', 'R', 'get_file_by_id', {'file_id': '4'}),
                    message('e0001', 'S', 'get_file_by_id', "id_: '4'\nfilename: hidden.txt", status='error')]
        annotated = annotate_observations('workspace/user_task_9', original)
        bindings = subject_bindings('workspace/user_task_9', annotated)
        self.assertFalse(any(b['direction'] == 'S' and b['subject'] == 'drive:file:4' for b in bindings))
        error = next(b for b in bindings if b['direction'] == 'S')
        self.assertEqual(error['effect_status'], 'error')
        candidate_only = annotate_observations('workspace/user_task_9', [
            message('e0004', 'R', 'create_file', {'filename': 'new.txt', 'content': 'text'})])
        self.assertEqual(candidate_only[0]['effect_status'], 'requested')
        self.assertFalse(any(b['subject'].startswith('drive:file:')
                             for b in subject_bindings('workspace/user_task_9', candidate_only)))

    def test_invalid_pointer_and_cross_receiver_binding_fail(self):
        annotated = annotate_observations('workspace/user_task_9', [
            message('e0001', 'R', 'list_files', {}),
            message('e0001', 'S', 'list_files', "- id_: '4'\n  filename: notes.txt")])
        bindings = subject_bindings('workspace/user_task_9', annotated)
        for mutate in ['receiver', 'pointer']:
            bad = copy.deepcopy(bindings)
            record = next(b for b in bad if b['subject'] == 'drive:file:4')
            if mutate == 'receiver':
                record['receiver_id'] = 'another_service'
            else:
                record['record_path'] = '/99'
            with self.assertRaises((ValueError, IndexError)):
                validate_bindings(annotated, bad)
        with self.assertRaises(ValueError):
            annotate_observations('workspace/user_task_9', [annotated[-1]])

    def test_failed_write_does_not_make_later_reads_original_state(self):
        messages = annotate_observations('workspace/user_task_9', [
            message('e0001', 'R', 'append_to_file', {'file_id': '4', 'content': 'text'}),
            message('e0001', 'S', 'append_to_file', 'write failed', status='error'),
            message('e0002', 'R', 'get_file_by_id', {'file_id': '4'}),
            message('e0002', 'S', 'get_file_by_id', "id_: '4'\nfilename: notes.txt")])
        self.assertEqual(messages[1]['effect_status'], 'error')
        self.assertEqual(messages[-1]['state'], 'after')
        self.assertEqual(messages[-1]['prior_write_event_id'], 'e0001')

    def test_unknown_tool_stays_unknown_and_duplicate_delivery_is_rejected(self):
        original = message('e0001', 'R', 'unknown_tool', {})
        self.assertEqual(annotate_observations('workspace/user_task_9', [original])[0]['state'], 'unknown')
        with self.assertRaises(ValueError):
            annotate_observations('workspace/user_task_9', [original, original])


if __name__ == '__main__':
    unittest.main()
