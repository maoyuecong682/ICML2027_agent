import copy
import json
import unittest

from p0_privacy.background_recovery import BackgroundRecovery
from p0_privacy.public_background import DEFAULT_OUTPUT, digest
from p0_privacy.recovery import SCHEMA, recover


class BackgroundRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.background = json.loads(DEFAULT_OUTPUT.read_bytes())
        self.memory = {'schema': SCHEMA, 'receivers': [{'receiver_id': 'r', 'facts': []}], 'sharing_groups': []}
        self.targets = [{'probe_id': 'opaque', 'receiver_id': 'r', 'field': 'travel_destination'}]

    def rehash(self, background):
        background['content_sha256'] = digest({k: background[k] for k in
            ('tools_by_suite', 'public_records', 'privacy_definitions')})
        return background

    def test_background_is_really_consumed_in_empty_memory(self):
        self.assertIsNone(recover(self.memory, self.targets)[0]['top1_guess'])
        row = BackgroundRecovery(self.background).recover(self.memory, self.targets)[0]
        self.assertIsNotNone(row['top1_guess'])
        self.assertEqual(row['basis'], 'background_guess')
        self.assertEqual(row['evidence'], [])
        self.assertTrue(row['background_evidence'])
        for pointer in row['background_evidence']:
            node = self.background
            for part in pointer.strip('/').split('/'):
                node = node[int(part)] if isinstance(node, list) else node[part]
            self.assertEqual(node, row['top1_guess'])

    def test_removing_records_removes_guess_and_changing_records_changes_guess(self):
        b = copy.deepcopy(self.background)
        b['public_records'] = {k: [] for k in b['public_records']}
        self.assertIsNone(BackgroundRecovery(self.rehash(b)).recover(self.memory, self.targets)[0]['top1_guess'])
        b['public_records']['hotels'] = [{'city': 'City One'}, {'city': 'City Two'}, {'city': 'City Two'}]
        row = BackgroundRecovery(self.rehash(b)).recover(self.memory, self.targets)[0]
        self.assertEqual(row['top1_guess'], 'City Two')
        self.assertEqual(len(row['background_evidence']), 2)

    def test_tool_services_and_ontology_gate_public_candidates(self):
        for kind in ('tools', 'fields'):
            b = copy.deepcopy(self.background)
            if kind == 'tools':
                b['tools_by_suite'] = {}
            else:
                b['privacy_definitions']['fields'].pop('travel_destination')
            self.assertIsNone(BackgroundRecovery(self.rehash(b)).recover(self.memory, self.targets)[0]['top1_guess'])

    def test_memory_evidence_has_priority_and_background_does_not_become_fact(self):
        self.memory['receivers'][0]['facts'] = [{'fact_id': 'f', 'field': 'travel_destination', 'value': 'Private City'}]
        before = copy.deepcopy(self.memory)
        row = BackgroundRecovery(self.background).recover(self.memory, self.targets)[0]
        self.assertEqual(row['top1_guess'], 'Private City')
        self.assertEqual(row['basis'], 'memory_supported')
        self.assertEqual(row['background_evidence'], [])
        self.assertEqual(self.memory, before)

    def test_private_secrets_are_not_invented_and_target_ids_do_not_affect_ranking(self):
        engine = BackgroundRecovery(self.background)
        for field in ('password', 'security_code', 'legal_name', 'password_reset_token'):
            targets = [{**self.targets[0], 'field': field}]
            self.assertIsNone(engine.recover(self.memory, targets)[0]['top1_guess'])
        first = engine.recover(self.memory, self.targets)[0]
        changed = engine.recover(self.memory, [{**self.targets[0], 'probe_id': 'different-task'}])[0]
        self.assertEqual(first['top1_guess'], changed['top1_guess'])
        with self.assertRaises(ValueError):
            engine.recover(self.memory, [{**self.targets[0], 'gold': 'hidden'}])


if __name__ == '__main__':
    unittest.main()
