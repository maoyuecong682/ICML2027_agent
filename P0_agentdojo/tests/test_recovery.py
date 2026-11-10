import copy
import unittest

from p0_privacy.recovery import SCHEMA, recover, memory_from_graph
from p0_privacy.recovery_evaluation import canonical, references, score


class RecoveryTests(unittest.TestCase):
    def memory(self, facts):
        return {'schema': SCHEMA, 'receivers': [{'receiver_id': 'r', 'facts': facts}], 'sharing_groups': []}

    def target(self, field, rid='r'):
        return [{'probe_id': 'p', 'receiver_id': rid, 'field': field}]

    def test_multiple_categories_use_the_same_input_contract(self):
        for field, path, value in [('financial_amount', '/amount', 20),
                                   ('calendar_schedule', '/start_time', '2024-05-19 12:00'),
                                   ('email_address', '/recipients/0', 'a@example.com'),
                                   ('file_metadata', '/filename', 'private.docx'),
                                   ('channel_membership', '/channel', 'private'),
                                   ('website_visit', '/url', 'www.example.com')]:
            memory = self.memory([{'fact_id': 'f', 'field': 'request_parameter', 'value': value,
                                   'parameter_path': path}])
            self.assertEqual(recover(memory, self.target(field))[0]['top1_guess'], value)

    def test_gold_or_audit_cannot_be_passed_as_memory_or_target(self):
        for bad in ('gold', 'task', 'source_candidates', 'absorbed_records'):
            memory = self.memory([])
            memory[bad] = 'secret'
            with self.assertRaises(ValueError):
                recover(memory, self.target('password'))
        target = self.target('password')
        target[0]['answer'] = 'secret'
        with self.assertRaises(ValueError):
            recover(self.memory([]), target)

    def test_shared_trip_requires_explicit_subject_and_all_premises(self):
        memory = {'schema': SCHEMA, 'receivers': [
            {'receiver_id': 'a', 'facts': [{'fact_id': 'a1', 'field': 'legal_name', 'value': 'Person', 'subject': 'trip:1'}]},
            {'receiver_id': 'b', 'facts': [
                {'fact_id': 'b1', 'field': 'travel_destination', 'value': 'Paris', 'subject': 'trip:1'},
                {'fact_id': 'b2', 'field': 'travel_dates', 'value': '2024-05-19', 'subject': 'trip:1'}]}],
            'sharing_groups': [{'group_id': 'g', 'members': ['a', 'b'], 'enabled': False}]}
        target = self.target('travel_itinerary', 'a')
        self.assertIsNone(recover(memory, target)[0]['top1_guess'])
        memory['sharing_groups'][0]['enabled'] = True
        result = recover(memory, target)[0]
        self.assertEqual(result['top1_guess']['destination'], 'Paris')
        self.assertTrue(result['shared_knowledge_used'])
        self.assertEqual(len(result['evidence']), 3)
        memory['receivers'][1]['facts'][0]['subject'] = 'different-trip'
        self.assertIsNone(recover(memory, target)[0]['top1_guess'])

    def test_conflict_or_cooccurrence_is_not_proof(self):
        facts = [{'fact_id': str(i), 'field': f, 'value': v, 'subject': 'trip'} for i, (f, v) in enumerate([
            ('legal_name', 'Person'), ('travel_destination', 'Paris'), ('travel_destination', 'London'),
            ('travel_dates', '2024-05-19')])]
        self.assertIsNone(recover(self.memory(facts), self.target('travel_itinerary'))[0]['top1_guess'])
        for f in facts:
            f.pop('subject')
        self.assertIsNone(recover(self.memory(facts), self.target('travel_itinerary'))[0]['top1_guess'])

    def test_collection_is_reconstructed_without_losing_members(self):
        expanded = self.memory([{'fact_id': str(i), 'field': 'packing_item', 'value': v, 'subject': 'list:1'}
                                for i, v in enumerate(['Swimwear', 'Camera'])])
        compact = self.memory([{'fact_id': 'collection', 'field': 'packing_items', 'value': ['Swimwear', 'Camera']}])
        self.assertEqual(recover(expanded, self.target('packing_items'))[0]['top1_guess'],
                         recover(compact, self.target('packing_items'))[0]['top1_guess'])

    def test_graph_adapter_never_reads_raw_request_or_absorbed_audit(self):
        graph = {'nodes': [{'id': 'r', 'type': 'business_receiver', 'receiver_id': 'r'},
                          {'id': 'q', 'type': 'actual_disclosure', 'receiver_id': 'r',
                           'parameters': {'password': 'audit-secret'}},
                          {'id': 'e', 'type': 'graphiti_entity', 'receiver_id': 'r', 'label': 'public',
                           'absorbed_records': [{'field': 'password', 'value': 'audit-secret'}]}], 'edges': []}
        memory = memory_from_graph(graph)
        self.assertIsNone(recover(memory, self.target('password'))[0]['top1_guess'])

    def test_references_do_not_use_outgoing_guesses(self):
        task = {'prompt': 'Visit Paris', 'category_ids': ['hotel_search']}
        env = {'user': {'first_name': 'Emma', 'last_name': 'Johnson'}}
        gold, omitted = references(task, env)
        self.assertIn('travel_destination', gold)
        self.assertIn('travel_budget', omitted)
        self.assertEqual(gold['travel_destination'][0]['value'], 'Paris')
        prediction = [{'field': 'travel_destination', 'top1_guess': 'Paris'}]
        self.assertEqual(score(prediction, gold)[0]['top1_recovery'], 1)
        self.assertEqual(score([{'field': 'travel_destination', 'top1_guess': None}], gold)[0]['top1_recovery'], 0)

    def test_canonical_scoring_preserves_case_and_normalizes_numbers(self):
        self.assertEqual(canonical(5.0), canonical('5'))
        self.assertNotEqual(canonical('SecretPassword'), canonical('secretpassword'))
        self.assertNotEqual(canonical('001234', 'security_code'), canonical('1234', 'security_code'))
        self.assertNotEqual(canonical('1234.0', 'password'), canonical('1234', 'password'))
        self.assertEqual(canonical('5.00', 'financial_amount'), canonical(5.0, 'financial_amount'))


if __name__ == '__main__':
    unittest.main()
