"""Tool-return ownership, delivery, errors and usable knowledge; no API calls."""
import copy
import unittest

from p0.tool_memory import execution_memory_from_graph
from p0_privacy.recovery import memory_from_graph, recover
from p0_privacy.response_memory import attach_tool_responses


def event(eid, actor, tool, arguments, content, error=None):
    return {'id': eid, 'type': 'TOOL', 'actor': actor, 'timestamp': '2026-11-14T00:00:00Z',
            'payload': {'name': tool, 'arguments': arguments, 'target': actor,
                        'result': content if error is None else 'HIDDEN_SUCCESS_EMAIL@example.com',
                        'delivered_content': content, 'error': error, 'tool_call_id': eid}}


def fixture(events):
    nodes, memories = [], []
    for rid, evs in events.items():
        nodes.append({'id': 'service:' + rid, 'type': 'business_receiver', 'receiver_id': rid})
        requests = []
        for e in evs:
            p = e['payload']
            did = 'banking/user_task_9::' + rid + '::' + e['id']
            nodes.append({'id': 'request:' + e['id'], 'type': 'actual_disclosure',
                          'event_id': e['id'], 'receiver_id': rid, 'disclosure_id': did,
                          'label': p['name'], 'parameters': p['arguments']})
            requests.append({'event_id': e['id']})
        memories.append({'receiver_id': rid, 'received_requests': requests})
    return {'task': {'task_key': 'banking/user_task_9'}, 'nodes': nodes, 'edges': [],
            'receiver_memory': memories}, {'nodes': [e for es in events.values() for e in es]}


class ResponseMemoryTests(unittest.TestCase):
    def local(self, memory, rid):
        return {**memory, 'receivers': [r for r in memory['receivers'] if r['receiver_id'] == rid],
                'sharing_groups': []}

    def answer(self, memory, rid, field, subject=None, state=None):
        target = {'probe_id': 'p', 'receiver_id': rid, 'field': field}
        if subject: target['subject'] = subject
        if state: target['state'] = state
        return recover(memory, [target])[0]['top1_guess']

    def test_empty_query_stores_return_and_binds_contact_without_cross_service_copy(self):
        events = {
            'profile': [event('e1', 'A', 'get_user_info', {},
                              "{'first_name': 'Emma', 'last_name': 'Johnson', 'email': 'emma@example.com'}")],
            'bank': [event('e2', 'A', 'get_balance', {}, '1810.0')]}
        graph, execution = fixture(events)
        original = copy.deepcopy(graph)
        updated = attach_tool_responses(graph, execution)
        memory = memory_from_graph(updated)
        self.assertEqual(graph, original)
        self.assertEqual(self.answer(self.local(memory, 'profile'), 'profile', 'email_address', 'Emma Johnson'), 'emma@example.com')
        self.assertIsNone(self.answer(self.local(memory, 'bank'), 'bank', 'email_address', 'Emma Johnson'))
        self.assertEqual(self.answer(self.local(memory, 'bank'), 'bank', 'financial_balance', 'bank:self', 'before'), 1810.0)
        self.assertEqual(attach_tool_responses(updated, execution), updated)

    def test_native_returns_only_reach_the_agent_that_actually_received_them(self):
        a = event('e1', 'A', 'read_file', {'file_path': 'a.txt'}, "Alice's email is alice@example.com.")
        b = event('e2', 'B', 'send_money', {}, 'OK')
        graph, execution = fixture({'files': [a], 'bank': [b]})
        execution['nodes'].append({'id': 'm1', 'type': 'MESSAGE', 'actor': 'A', 'payload': {
            'source': 'A', 'target': 'B', 'content': 'The file was read; no email is included in this report.'}})
        agents = {r['agent_id']: r for r in execution_memory_from_graph(execution)['agents']}
        self.assertEqual(agents['A']['tool_observations'][0]['content'], a['payload']['delivered_content'])
        self.assertNotIn('alice@example.com', str(agents['B']))
        self.assertEqual(len(agents['B']['received_agent_messages']), 1)
        memory = memory_from_graph(attach_tool_responses(graph, execution))
        self.assertEqual(self.answer(self.local(memory, 'files'), 'files', 'email_address', 'Alice'), 'alice@example.com')
        self.assertIsNone(self.answer(self.local(memory, 'bank'), 'bank', 'email_address', 'Alice'))

    def test_failed_query_keeps_error_but_cannot_turn_error_or_hidden_result_into_contact(self):
        graph, execution = fixture({'profile': [event('e1', 'A', 'get_user_info', {},
            'ERROR: Contact alice@example.com not found.', 'not found')]})
        updated = attach_tool_responses(graph, execution)
        memory = memory_from_graph(updated)
        self.assertNotIn('HIDDEN_SUCCESS_EMAIL', str(memory))
        self.assertIn('not found', str(memory))
        self.assertIsNone(self.answer(memory, 'profile', 'email_address'))

    def test_record_body_survives_yaml_and_removing_active_response_removes_knowledge(self):
        e = event('e1', 'A', 'get_file_by_id', {'file_id': '7'},
                  "id_: '7'\nfilename: notes.txt\ncontent: Alice's email is alice@example.com.\n")
        graph, execution = fixture({'drive': [e]})
        graph['task']['task_key'] = 'workspace/user_task_9'
        updated = attach_tool_responses(graph, execution)
        memory = memory_from_graph(updated)
        self.assertEqual(self.answer(memory, 'drive', 'document_content', 'drive:file:7', 'before'), "Alice's email is alice@example.com.")
        self.assertEqual(self.answer(memory, 'drive', 'email_address', 'Alice'), 'alice@example.com')
        updated['nodes'] = [n for n in updated['nodes'] if n['type'] != 'tool_response']
        self.assertIsNone(self.answer(memory_from_graph(updated), 'drive', 'email_address', 'Alice'))

    def test_read_after_write_is_not_mislabeled_as_pre_task_value(self):
        graph, execution = fixture({'bank': [event('e1', 'B', 'send_money', {}, 'OK'),
                                             event('e2', 'A', 'get_balance', {}, '70')]})
        memory = memory_from_graph(attach_tool_responses(graph, execution))
        self.assertIsNone(self.answer(memory, 'bank', 'financial_balance', 'bank:self', 'before'))
        self.assertEqual(self.answer(memory, 'bank', 'financial_balance', 'bank:self', 'after'), 70)

    def test_missing_or_mismatched_source_and_wrong_target_are_not_silently_accepted(self):
        graph, execution = fixture({'bank': [event('e1', 'A', 'get_balance', {}, '70')]})
        for mutate in ('missing', 'parameters', 'agent'):
            invalid = copy.deepcopy(execution)
            if mutate == 'missing': invalid['nodes'].clear()
            elif mutate == 'parameters': invalid['nodes'][0]['payload']['arguments'] = {'invented': True}
            else: invalid['nodes'][0]['payload']['target'] = 'B'
            with self.assertRaises(ValueError):
                attach_tool_responses(graph, invalid)


if __name__ == '__main__':
    unittest.main()
