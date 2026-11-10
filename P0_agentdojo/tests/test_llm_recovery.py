import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from p0_privacy.llm_recovery import make_request, predict, validate_predictions
from p0_privacy.recovery import SCHEMA


class LLMRecoveryTests(unittest.TestCase):
    def view(self, empty=False):
        return {'receiver_id': 'r', 'memory': {'schema': SCHEMA, 'receivers': [
            {'receiver_id': 'r', 'facts': [] if empty else [
                {'fact_id': 'f', 'field': 'legal_name', 'value': 'Private Person'}]}],
            'sharing_groups': []}, 'targets': [
                {'probe_id': 'task-secret-index', 'receiver_id': 'r', 'field': 'legal_name'}]}

    def prediction(self, basis='background_guess', evidence=None):
        return {'predictions': [{'query_id': 'q0', 'top1_guess': 'Guessed Name',
                                'basis': basis, 'evidence_fact_ids': evidence or []}]}

    def test_request_has_no_probe_identifier_or_reference(self):
        request = make_request(self.view(True), {'public_records': {'hotels': []}})
        payload = json.loads(request['messages'][1]['content'])
        self.assertNotIn('task-secret-index', str(request))
        self.assertNotIn('Private Person', str(request))
        self.assertEqual(set(payload), {'public_background', 'memory', 'queries'})
        self.assertEqual(payload['queries'][0]['query_id'], 'q0')

    def test_evidence_cannot_be_invented_in_empty_memory(self):
        with self.assertRaises(ValueError):
            validate_predictions(self.prediction('memory_supported', ['f']), self.view(True))
        validate_predictions(self.prediction(), self.view(True))

    def test_missing_or_duplicate_targets_are_rejected(self):
        data = self.prediction()
        data['predictions'].append(copy.deepcopy(data['predictions'][0]))
        with self.assertRaises(ValueError):
            validate_predictions(data, self.view())
        data = self.prediction()
        data['predictions'][0]['query_id'] = 'q1'
        with self.assertRaises(ValueError):
            validate_predictions(data, self.view())

    def test_identical_requests_cache_and_remap_probe_ids(self):
        data = self.prediction()
        response = SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',
            message=SimpleNamespace(content=json.dumps(data)))],
            model_dump_json=lambda **kwargs: json.dumps({'choices': data}))
        calls = []
        def create(**kwargs):
            calls.append(kwargs)
            return response
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with tempfile.TemporaryDirectory() as folder:
            first = predict(client, self.view(True), {}, Path(folder))
            changed = self.view(True)
            changed['targets'][0]['probe_id'] = 'another-task-id'
            second = predict(client, changed, {}, Path(folder))
            self.assertEqual(len(calls), 1)
            self.assertEqual(first[0]['top1_guess'], second[0]['top1_guess'])
            self.assertEqual(second[0]['probe_id'], 'another-task-id')
            self.assertEqual(first[0]['request_sha256'], second[0]['request_sha256'])


if __name__ == '__main__':
    unittest.main()
