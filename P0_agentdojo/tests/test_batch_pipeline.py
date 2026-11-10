"""Offline integration checks; never fabricate a live Mem0/benchmark run."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from agentdojo.task_suite.load_suites import get_suites
from p0_privacy.batch_pipeline import (EXCLUDED, apply_privacy_memory, prepare,
                                      privacy_text_document, selection)
from p0_privacy.recipients import resolve_event
from p0_privacy.simplification import SimplificationConfig, simplify_graph
from privacy_memory_compression import normalize, render_memory, scope
from p0_privacy.annotation import reconcile_review_summaries


class BatchPipelineTests(unittest.TestCase):
    def test_review_aggregation_never_modifies_or_invents_atoms(self):
        original = {'disclosures': [{'disclosure_id': 'd', 'atoms': [
            {'field': 'meeting_topic', 'parameter_path': '/title', 'span': 'Lunch'}],
            'parameter_reviews': [{'parameter_path': '/title', 'assessment': 'no_sensitive_content', 'reason': 'generic title'}]}]}
        derived, audit = reconcile_review_summaries(original)
        self.assertEqual(derived['disclosures'][0]['atoms'], original['disclosures'][0]['atoms'])
        self.assertEqual(original['disclosures'][0]['parameter_reviews'][0]['assessment'], 'no_sensitive_content')
        self.assertEqual(derived['disclosures'][0]['parameter_reviews'][0]['assessment'], 'potentially_sensitive')
        self.assertEqual(len(audit), 1)

    def test_selection_is_fixed_stratified_and_excludes_prior_three(self):
        chosen = selection()
        self.assertEqual(chosen, selection())
        keys = {t['task_key'] for t in chosen['tasks']}
        self.assertEqual(len(keys), 47)
        self.assertFalse(keys & EXCLUDED)
        self.assertEqual(chosen['population_count'], 97)
        self.assertEqual(chosen['remaining_count'], 94)
        self.assertEqual(set(chosen['category_quotas']), set(chosen['category_population']))
        self.assertTrue(all(q >= 1 for q in chosen['category_quotas'].values()))

    def test_preparation_is_resumable_without_fake_graphs(self):
        with tempfile.TemporaryDirectory() as folder:
            first = prepare(Path(folder))
            second = prepare(Path(folder))
            self.assertEqual(first['selection'], second['selection'])
            self.assertEqual(second['config']['privacy_text_compression'], 'mem0')
            self.assertTrue(all(t['versions'] is None for t in second['tasks'].values()))
            self.assertEqual(second['summary']['completed'], 0)
        with tempfile.TemporaryDirectory() as folder:
            ablation = prepare(Path(folder), privacy_text='none')
            self.assertEqual(ablation['config']['privacy_text_compression'], 'none')

    def test_all_registered_tools_have_explicit_request_endpoint(self):
        for name, suite in get_suites('v1.2').items():
            tools = {f.name: f for f in suite.tools}
            for tool in tools:
                node = {'id': 'unit-test', 'payload': {'name': tool, 'error': None,
                        'arguments': {'recipients': [], 'recipient': 'test', 'email': 'test@example.com'}}}
                result = resolve_event(name, node, tools)
                with self.subTest(suite=name, tool=tool):
                    self.assertTrue(result['receipts'])
                    self.assertNotEqual(result['status'], 'unresolved')
                    self.assertEqual(result['receipts'][0]['received_request_parameters'], node['payload']['arguments'])

    def test_both_arms_share_memory_and_keep_evidence(self):
        path = Path(__file__).resolve().parents[1] / 'outputs/graphiti_privacy/任务隐私图.json'
        graph = json.loads(path.read_text(encoding='utf-8'))['graphs']['workspace/user_task_31']
        before = copy.deepcopy(graph)
        disclosures = {}
        for n in graph['nodes']:
            if n['type'] == 'actual_disclosure':
                disclosures[n['disclosure_id']] = {'receiver_id': n['receiver_id'],
                    'event_id': n['event_id'], 'time': n['time'], 'atoms': []}
        for n in graph['nodes']:
            if n['type'] == 'disclosed_atom':
                disclosures[n['disclosure_id']]['atoms'].append(n['annotation'])
        task = {'task_key': graph['task']['task_key'], 'disclosures': list(disclosures.values())}
        document = normalize(privacy_text_document(task))
        # A deterministic memory fixture tests the bridge, not live Mem0 behavior.
        groups = [{'text': b['text'], 'source_ids': [b['id']]} for b in document['blocks']]
        memory = render_memory(groups, document)
        baseline = apply_privacy_memory(graph, memory, {'strategy': 'unit_test_fixture'})
        simplified = simplify_graph(baseline, SimplificationConfig(True))
        self.assertEqual(graph, before)
        self.assertEqual(baseline['privacy_text_compression']['memory'],
                         simplified['privacy_text_compression']['memory'])
        self.assertTrue(baseline['validation']['passed'])
        self.assertTrue(simplified['validation']['passed'])
        bad = copy.deepcopy(memory)
        bad['occurrences'].pop()
        with self.assertRaises(ValueError):
            apply_privacy_memory(graph, bad, {'strategy': 'unit_test_fixture'})


if __name__ == '__main__':
    unittest.main()
