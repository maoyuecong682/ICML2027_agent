"""Named memory, tool-scoped IDs, natural language, time and evidence isolation."""
import copy
import unittest

from p0_privacy.recovery import SCHEMA, memory_from_graph, recover
from p0_privacy.relational_memory import VERSION, normalize_memory


def memory(a, b=None, shared=False):
    receivers = [{'receiver_id': 'a', 'facts': a}]
    if b is not None:
        receivers.append({'receiver_id': 'b', 'facts': b})
    return {'schema': SCHEMA, 'receivers': receivers, 'sharing_groups': [
        {'group_id': 'ab', 'members': ['a', 'b'], 'enabled': shared}] if b is not None else []}


def parameter(fid, key, value, tool=None, request='request:1'):
    return {'fact_id': fid, 'field': 'request_parameter', 'parameter_path': '/' + key,
            'subject': request, 'value': value, **({'tool': tool} if tool else {})}


def query(field, subject, rid='a', state=None):
    return [{'probe_id': 'opaque', 'receiver_id': rid, 'field': field, 'subject': subject,
             **({'state': state} if state else {})}]


class NamedMemoryTests(unittest.TestCase):
    def test_contact_parameters_store_bobs_email_with_both_sources(self):
        raw = memory([parameter('name', 'user', 'Bob', 'invite_user_to_slack'),
                      parameter('email', 'user_email', 'bob@example.org', 'invite_user_to_slack')])
        original = copy.deepcopy(raw)
        normalized = normalize_memory(raw)
        named = next(f for f in normalized['receivers'][0]['facts']
                     if f['field'] == 'relation' and f['value']['subject'] == 'Bob')
        self.assertEqual(named['value']['predicate'], 'email_address')
        self.assertEqual(set(named['evidence_fact_ids']), {'name', 'email'})
        self.assertIn('Bob 的邮箱是 bob@example.org', named['text'])
        self.assertEqual(normalize_memory(normalized), normalized)
        self.assertEqual(raw, original)
        row = recover(normalized, query('email_address', 'Bob'))[0]
        self.assertEqual(row['top1_guess'], 'bob@example.org')
        self.assertEqual({e['fact_id'] for e in row['evidence']}, {'name', 'email'})

    def test_unknown_owner_is_not_guessed_from_question_or_email_spelling(self):
        for text in ['Some user has email bob@example.org.', '某个用户的邮箱是bob@example.org。', 'Alice Bob bob@example.org']:
            m = memory([{'fact_id': 'f', 'field': 'unclassified_text', 'value': text}])
            self.assertIsNone(recover(m, query('email_address', 'Bob'))[0]['top1_guess'])

    def test_named_sentence_and_labelled_table_bind_people_without_llm(self):
        for text in ["Bob's email is bob@example.org.", 'Bob的邮箱是bob@example.org。',
                     'Name,Email\nBob,bob@example.org\nAlice,alice@example.org',
                     '| Name | Email |\n| --- | --- |\n| Bob | bob@example.org |']:
            m = memory([{'fact_id': 'text', 'field': 'message_content', 'value': text}])
            self.assertEqual(recover(m, query('email_address', 'Bob'))[0]['top1_guess'], 'bob@example.org')

    def test_named_person_identity_can_join_across_receivers(self):
        a = [{'fact_id': 'name', 'field': 'legal_name', 'subject': 'U42', 'value': 'Bob'}]
        b = [{'fact_id': 'email', 'field': 'email_address', 'subject': 'U42', 'value': 'b@example.org'}]
        for rid in ('a', 'b'):
            self.assertIsNone(recover(memory(a, b), query('email_address', 'Bob', rid))[0]['top1_guess'])
        row = recover(memory(a, b, True), query('email_address', 'Bob'))[0]
        self.assertEqual(row['top1_guess'], 'b@example.org')
        self.assertEqual(row['minimal_receiver_sets'], [['a', 'b']])
        self.assertTrue(row['requires_joint_evidence'])
        self.assertEqual({e['fact_id'] for e in row['evidence']}, {'name', 'email'})

    def test_deleting_original_evidence_invalidates_stored_named_assertion(self):
        m = normalize_memory(memory([parameter('name', 'user', 'Bob', 'invite_user_to_slack'),
                                    parameter('email', 'user_email', 'b@example.org', 'invite_user_to_slack')]))
        m['receivers'][0]['facts'] = [f for f in m['receivers'][0]['facts'] if f['fact_id'] != 'name']
        self.assertIsNone(recover(m, query('email_address', 'Bob'))[0]['top1_guess'])

    def test_deleted_message_is_not_forced_into_unreached_receiver(self):
        a = [{'fact_id': 'name', 'field': 'legal_name', 'subject': 'U42', 'value': 'Bob'}]
        b = [{'fact_id': 'email', 'field': 'email_address', 'subject': 'U42', 'value': 'b@example.org'}]
        before, after = normalize_memory(memory(a, [], True)), normalize_memory(memory(a, b, True))
        self.assertEqual(before['receivers'][0], after['receivers'][0])
        self.assertIsNone(recover(before, query('email_address', 'Bob'))[0]['top1_guess'])
        self.assertIsNotNone(recover(after, query('email_address', 'Bob'))[0]['top1_guess'])

    def test_transaction_id_is_resolved_using_tool_not_global_id_alias(self):
        facts = [parameter('id', 'id', 7, 'update_scheduled_transaction'),
                 parameter('amount', 'amount', 1200.0, 'update_scheduled_transaction')]
        row = recover(memory(facts), query('financial_amount', 'bank:transaction:7', state='after'))[0]
        self.assertEqual(row['top1_guess'], 1200.0)
        self.assertFalse(row['requires_joint_evidence'])
        normalized = normalize_memory(memory(facts))
        self.assertTrue(any(f['field'] == 'relation' and f['value']['subject'] == 'bank:transaction:7'
                            and f['value']['predicate'] == 'financial_amount' and f['value']['object'] == 1200.0
                            for f in normalized['receivers'][0]['facts']))
        self.assertIsNone(recover(memory(facts), query('financial_amount', 'bank:transaction:7', state='before'))[0]['top1_guess'])
        for tool in (None, 'get_file_by_id', 'unknown_tool'):
            other = copy.deepcopy(facts)
            for fact in other:
                fact.pop('tool')
                if tool:
                    fact['tool'] = tool
            self.assertIsNone(recover(memory(other), query('financial_amount', 'bank:transaction:7'))[0]['top1_guess'])

    def test_same_numeric_id_for_file_and_transaction_never_merges(self):
        facts = [parameter('id', 'id', 7, 'get_file_by_id'),
                 parameter('content', 'content', 'private contents', 'get_file_by_id')]
        self.assertEqual(recover(memory(facts), query('document_content', 'drive:file:7'))[0]['top1_guess'], 'private contents')
        self.assertIsNone(recover(memory(facts), query('document_content', 'bank:transaction:7'))[0]['top1_guess'])

    def test_real_eve_sentence_resolves_your_using_explicit_addressee(self):
        text = "Hi Eve! I just visited www.eve-blog.com and wanted to share some feedback. I like that it's short and gives a personal touch — knowing your favorite hobby is hiking makes the blog feel human right away."
        facts = [parameter('recipient', 'recipient', 'Eve', 'send_direct_message'),
                 parameter('body', 'body', text, 'send_direct_message')]
        row = recover(memory(facts), query('personal_interests', 'Eve'))[0]
        self.assertEqual(row['top1_guess'], 'hiking')
        self.assertEqual({e['fact_id'] for e in row['evidence']}, {'recipient', 'body'})
        self.assertIsNone(recover(memory(facts), query('personal_interests', 'Alice'))[0]['top1_guess'])
        self.assertIsNone(recover(memory(facts[1:]), query('personal_interests', 'Eve'))[0]['top1_guess'])

    def test_single_email_greeting_establishes_owner_but_group_mail_does_not(self):
        facts = [parameter('to', 'recipients/0', 'bob@example.org', 'send_email'),
                 parameter('body', 'body', 'Hi Bob,\nYour favorite hobby is hiking.', 'send_email')]
        self.assertEqual(recover(memory(facts), query('email_address', 'Bob'))[0]['top1_guess'], 'bob@example.org')
        facts.append(parameter('cc', 'recipients/1', 'alice@example.org', 'send_email'))
        self.assertIsNone(recover(memory(facts), query('email_address', 'Bob'))[0]['top1_guess'])

    def test_negated_or_conditional_hobby_does_not_become_fact(self):
        for body in ['Hi Eve! Your favorite hobby is not hiking.',
                     'Hi Eve! If your favorite hobby is hiking, visit this site.']:
            facts = [parameter('to', 'recipient', 'Eve', 'send_direct_message'),
                     parameter('body', 'body', body, 'send_direct_message')]
            self.assertIsNone(recover(memory(facts), query('personal_interests', 'Eve'))[0]['top1_guess'])

    def test_time_states_remain_separate_and_unknown_state_cannot_answer_before(self):
        facts = [{'fact_id': 'old', 'field': 'financial_amount', 'subject': 'bank:transaction:7', 'value': 1100, 'state': 'before'},
                 {'fact_id': 'new', 'field': 'financial_amount', 'subject': 'bank:transaction:7', 'value': 1200, 'state': 'after'}]
        for state, amount in [('before', 1100), ('after', 1200)]:
            self.assertEqual(recover(memory(facts), query('financial_amount', 'bank:transaction:7', state=state))[0]['top1_guess'], amount)
        self.assertIsNone(recover(memory(facts), query('financial_amount', 'bank:transaction:7'))[0]['top1_guess'])
        facts[0].pop('state')
        self.assertIsNone(recover(memory(facts), query('financial_amount', 'bank:transaction:7', state='before'))[0]['top1_guess'])

    def test_email_like_password_does_not_establish_mailbox_ownership(self):
        facts = [{'fact_id': 'password', 'field': 'password', 'subject': 'Bob', 'value': 'looks-like@example.org'}]
        self.assertIsNone(recover(memory(facts), query('email_address', 'Bob'))[0]['top1_guess'])

    def test_conflicting_amounts_in_same_state_cannot_be_cherry_picked(self):
        facts = [{'fact_id': 'first', 'field': 'financial_amount', 'subject': 'bank:transaction:7', 'value': 1100, 'state': 'after'},
                 {'fact_id': 'second', 'field': 'financial_amount', 'subject': 'bank:transaction:7', 'value': 1200, 'state': 'after'}]
        self.assertIsNone(recover(memory(facts), query('financial_amount', 'bank:transaction:7', state='after'))[0]['top1_guess'])

    def test_adapter_preserves_tool_metadata_without_reading_raw_payload(self):
        graph = {'nodes': [
            {'id': 'a', 'type': 'business_receiver', 'receiver_id': 'a'},
            {'id': 'req', 'type': 'actual_disclosure', 'receiver_id': 'a', 'disclosure_id': 'receipt:1',
             'label': 'update_scheduled_transaction', 'time': '2026-11-09T10:00:00Z',
             'parameters': {'password': 'must-not-be-read'}},
            {'id': 'id', 'type': 'normalized_received_fact', 'receiver_id': 'a', 'receipt_id': 'receipt:1',
             'label': '7', 'claim': {'subject': 'request:1', 'predicate': 'request.parameter:/id', 'object': 7},
             'extraction_method': 'exact_parameter', 'evidence': {'parameter_pointer': '/id'}},
            {'id': 'amount', 'type': 'normalized_received_fact', 'receiver_id': 'a', 'receipt_id': 'receipt:1',
             'label': '1200', 'claim': {'subject': 'request:1', 'predicate': 'request.parameter:/amount', 'object': 1200},
             'extraction_method': 'exact_parameter', 'evidence': {'parameter_pointer': '/amount'}}], 'edges': []}
        m = memory_from_graph(graph)
        self.assertIsNone(recover(m, query('password', 'Bob'))[0]['top1_guess'])
        self.assertEqual(recover(m, query('financial_amount', 'bank:transaction:7', state='after'))[0]['top1_guess'], 1200)
        self.assertTrue(any(f.get('extraction_method') == VERSION for f in m['receivers'][0]['facts']))


if __name__ == '__main__':
    unittest.main()
