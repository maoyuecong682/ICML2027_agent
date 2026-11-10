import copy
import unittest

from p0_privacy.public_background import (
    build_background, project_public_records, recovery_context, validate_background,
)
from p0_privacy.recovery import SCHEMA, recover


class PublicBackgroundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.background = build_background()

    def inputs(self):
        memory = {'schema': SCHEMA, 'receivers': [
            {'receiver_id': 'a', 'facts': [{'fact_id': 'a1', 'field': 'legal_name', 'value': 'Private A'}]},
            {'receiver_id': 'b', 'facts': [{'fact_id': 'b1', 'field': 'legal_name', 'value': 'Private B'}]},
            {'receiver_id': 'c', 'facts': [{'fact_id': 'c1', 'field': 'legal_name', 'value': 'Private C'}]},
        ], 'sharing_groups': [
            {'group_id': 'ab', 'members': ['a', 'b'], 'enabled': True},
            {'group_id': 'bc', 'members': ['b', 'c'], 'enabled': True},
        ]}
        targets = [{'probe_id': 'p', 'receiver_id': 'a', 'field': 'legal_name'}]
        return memory, targets

    def test_default_public_data_and_tools_are_complete_and_repeatable(self):
        b = self.background
        self.assertEqual(b['statistics']['tools_by_suite'],
                         {'banking': 11, 'slack': 11, 'travel': 28, 'workspace': 24})
        self.assertEqual(b['statistics']['public_records_by_type'],
                         {'hotels': 10, 'restaurants': 13, 'car_rental': 10, 'flights': 3})
        self.assertEqual(b['content_sha256'], build_background()['content_sha256'])
        self.assertNotIn('TASK_CATEGORIES', b['privacy_definitions'])
        for tools in b['tools_by_suite'].values():
            for tool in tools:
                self.assertIsNotNone(tool['service']['service_type'])
                self.assertIn('properties', tool['parameters'])

    def test_projection_excludes_private_domains_and_uses_independent_copies(self):
        env = {'hotels': {'hotel_list': [{'name': 'Public hotel'}]},
               'restaurants': {'restaurant_list': []}, 'flights': {'flight_list': []},
               'car_rental': {'company_list': []},
               'user': {'password': 'PRIVATE_SENTINEL'},
               'reservation': {'hotel': 'PRIVATE_SENTINEL'},
               'gold': 'PRIVATE_SENTINEL'}
        result = project_public_records(env)
        self.assertNotIn('PRIVATE_SENTINEL', str(result))
        result['hotels'][0]['name'] = 'Changed'
        self.assertEqual(env['hotels']['hotel_list'][0]['name'], 'Public hotel')

    def test_three_conditions_keep_background_and_targets_identical(self):
        memory, targets = self.inputs()
        original = copy.deepcopy(memory)
        contexts = {c: recovery_context(memory, targets, self.background, c)
                    for c in ('none', 'local', 'shared')}
        for context in contexts.values():
            self.assertEqual(context['public_background_sha256'], self.background['content_sha256'])
            self.assertEqual(context['receiver_inputs'][0]['targets'], targets)
        self.assertEqual(memory, original)
        no_memory = contexts['none']['receiver_inputs'][0]['memory']
        self.assertTrue(all(not r['facts'] for r in no_memory['receivers']))
        self.assertIsNone(recover(no_memory, targets)[0]['top1_guess'])

    def test_local_is_physically_isolated_and_shared_is_not_transitive(self):
        memory, targets = self.inputs()
        local = recovery_context(memory, targets, self.background, 'local')['receiver_inputs'][0]
        shared = recovery_context(memory, targets, self.background, 'shared')['receiver_inputs'][0]
        self.assertEqual([r['receiver_id'] for r in local['memory']['receivers']], ['a'])
        self.assertNotIn('Private B', str(local))
        self.assertEqual([r['receiver_id'] for r in shared['memory']['receivers']], ['a', 'b'])
        self.assertNotIn('Private C', str(shared))
        self.assertEqual([g['group_id'] for g in shared['memory']['sharing_groups']], ['ab'])

    def test_tampering_or_wrong_condition_is_rejected(self):
        corrupted = copy.deepcopy(self.background)
        corrupted['public_records']['hotels'][0]['name'] = 'Tampered'
        with self.assertRaises(ValueError):
            validate_background(corrupted)
        memory, targets = self.inputs()
        with self.assertRaises(ValueError):
            recovery_context(memory, targets, self.background, 'unknown')


if __name__ == '__main__':
    unittest.main()
