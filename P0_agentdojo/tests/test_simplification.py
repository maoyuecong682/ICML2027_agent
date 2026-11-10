"""Ablation, recipient boundaries and preservation of disclosure evidence."""
import copy
import itertools
import json
import unittest
from pathlib import Path

from p0_privacy.simplification import SimplificationConfig, simplify_graph, terminal


class SimplificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / 'outputs/graphiti_privacy/任务隐私图.json'
        cls.graphs = json.loads(path.read_text(encoding='utf-8'))['graphs']

    def test_all_thirty_two_ablations_preserve_and_slots_and_source(self):
        for graph in self.graphs.values():
            before = copy.deepcopy(graph)
            for switches in itertools.product((False, True), repeat=5):
                with self.subTest(task=graph['task']['task_key'], switches=switches):
                    result = simplify_graph(graph, SimplificationConfig(True, *switches))
                    self.assertTrue(result['simplification']['validation']['passed'])
                    self.assertEqual(graph, before)
                    self.assertTrue(terminal(result))

    def test_master_off_is_exact_identity(self):
        for graph in self.graphs.values():
            self.assertEqual(graph, simplify_graph(graph, SimplificationConfig()))

    def test_list_keeps_members_and_all_supports_with_one_representative(self):
        graph = self.graphs['workspace/user_task_31']
        result = simplify_graph(graph, SimplificationConfig(True, remove_graphiti_relations=False))
        lists = [n for n in result['nodes'] if n['type'] == 'representative_object']
        self.assertEqual(len(lists), 1)
        self.assertEqual(lists[0]['member_count'], 6)
        self.assertIn('Hiking gear', lists[0]['members'])
        factor = next(f for f in result['joint_factors'] if 'atom:packing_items' in f['support'])
        self.assertEqual(factor['support']['atom:packing_items'], [lists[0]['id']])
        relations = [n for n in result['nodes'] if n.get('predicate') == 'LISTS_COLLECTION']
        self.assertEqual(len(relations), 1)

    def test_each_removal_can_be_disabled(self):
        graph = self.graphs['workspace/user_task_31']
        result = simplify_graph(graph, SimplificationConfig(True))
        types = {n['type'] for n in result['nodes']}
        self.assertNotIn('graphiti_episode', types)
        self.assertFalse(any(n.get('empty_parameters') for n in result['nodes']))
        for switches, expected in [((True, False, True, True), 'actual_disclosure'),
                                   ((True, True, True, False), 'graphiti_episode')]:
            variant = simplify_graph(graph, SimplificationConfig(True, *switches))
            if expected == 'actual_disclosure':
                self.assertTrue(any(n.get('empty_parameters') for n in variant['nodes']))
            else:
                self.assertIn(expected, {n['type'] for n in variant['nodes']})

    def test_task_prompt_cannot_introduce_unsent_secret(self):
        graph = copy.deepcopy(self.graphs['workspace/user_task_14'])
        graph['task']['prompt'] += ' UNSENT_SECRET_123'
        result = simplify_graph(graph, SimplificationConfig(True))
        self.assertFalse(any('UNSENT_SECRET_123' in n['label'] for n in result['nodes']))
        self.assertFalse(any(n.get('empty_parameters') for n in result['nodes']))

    def test_same_label_different_receiver_not_merged(self):
        graph = copy.deepcopy(self.graphs['workspace/user_task_14'])
        entity = copy.deepcopy(next(n for n in graph['nodes'] if n['type'] == 'graphiti_entity'))
        entity.update(id='other-recipient-entity', receiver_id='other-recipient')
        graph['nodes'].append(entity)
        result = simplify_graph(graph, SimplificationConfig(True))
        self.assertIn('other-recipient-entity', {n['id'] for n in result['nodes']})

    def test_relation_switch_preserves_entities_and_privacy_dependencies(self):
        graph = self.graphs['workspace/user_task_31']
        keep = simplify_graph(graph, SimplificationConfig(True, remove_graphiti_relations=False))
        remove = simplify_graph(graph, SimplificationConfig(True))
        self.assertTrue(any(n['type'] == 'graphiti_relation_claim' for n in keep['nodes']))
        self.assertFalse(any(n['type'] == 'graphiti_relation_claim' for n in remove['nodes']))
        entity_ids = lambda g: {n['id'] for n in g['nodes'] if n['type'] == 'graphiti_entity'}
        self.assertEqual(entity_ids(keep), entity_ids(remove))
        self.assertEqual(keep['joint_factors'], remove['joint_factors'])
        relevant = {'and_premise', 'documented_association', 'factor_support', 'factor_output'}
        dependencies = lambda g: {(e['source'], e['target'], e['kind']) for e in g['edges']
                                   if e['kind'] in relevant}
        self.assertEqual(dependencies(keep), dependencies(remove))


if __name__ == '__main__':
    unittest.main()
