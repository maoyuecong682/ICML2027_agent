"""Privacy graph evidence boundaries and Graphiti projection, without model calls."""
import copy
import json
import unittest

from p0_privacy.knowledge_merge import DEFAULT_RUN, input_from_observed_graph
from p0_privacy.process_graph import SOURCE
from p0_privacy.task_graph import DEFAULT_OUTPUT, project_graph, semantic_evidence, validate_task_graph


class TaskPrivacyGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        disclosure = json.loads((SOURCE / "披露信息.json").read_text(encoding="utf-8"))
        cls.tasks = {t["task_key"]: t for t in disclosure["tasks"]}
        categories = json.loads((SOURCE / "类别-信息图.json").read_text(encoding="utf-8"))
        cls.categories = {g["category_id"]: g for g in categories["graphs"]}
        cls.metadata = {"ontology": disclosure["ontology"], "input_sha256": {}}

    def fixture(self, number):
        data = input_from_observed_graph(DEFAULT_RUN / f"workspace_user_task_{number}" / "graph.json")
        rid = data["receivers"][0]["receiver_id"]
        native = {"config": {"engine": "graphiti-core", "version": "0.31.2"},
                  "groups": {rid: "test-group"}, "nodes": [], "edges": [], "episodes": [],
                  "episode_receipt_map": {}, "readback_verified": True}
        for i, receipt in enumerate(data["receipts"]):
            eid = f"test-episode-{i}"
            native["episode_receipt_map"][eid] = receipt["receipt_id"]
            native["episodes"].append({"uuid": eid, "receiver_id": rid, "valid_at": receipt["time"]})
        return data, native

    def project(self, data, native):
        return project_graph(data, native, self.tasks[data["task_key"]], self.categories, self.metadata, "both")

    def test_all_three_tasks_preserve_direct_and_hypothetical_attributes(self):
        for number in (14, 22, 31):
            with self.subTest(task=number):
                data, native = self.fixture(number)
                graph = self.project(data, native)
                self.assertTrue(graph["validation"]["passed"])
                self.assertFalse(graph["simplification"]["applied"])
                self.assertEqual(graph["recipient_knowledge_merge"]["outputs"]["on"]["status"], "skipped_single_receiver")
                self.assertEqual(len([n for n in graph["nodes"] if n["type"] == "actual_disclosure"]), 2)
                if number == 22:
                    attributes = {n["field"] for n in graph["nodes"] if n["type"] == "sensitive_field"}
                    self.assertNotIn("password_reset_token", attributes)
                if number == 31:
                    plans = [n for n in graph["nodes"] if n["type"] == "composite_privacy_fact"]
                    self.assertEqual(plans[0]["values"]["travel.traveler"], "Emma Johnson")
                    self.assertEqual(plans[0]["values"]["travel.destination"], "Hawaii")
                    self.assertEqual(plans[0]["status"], "explicit_document_association_not_actual_trip_proof")

    def test_model_quotes_require_correct_parameter_and_receiving_episode(self):
        data, native = self.fixture(22)
        rid = data["receivers"][0]["receiver_id"]
        relation = {"receiver_id": rid, "episodes": ["test-episode-0"],
                    "attributes": {"quote": "password reset", "parameter_pointer": "/query"}}
        self.assertEqual(semantic_evidence(relation, native, data)[0]["quote"], "password reset")
        for change in ({"attributes": {"quote": "TOKEN_ONLY_IN_RETURN", "parameter_pointer": "/query"}},
                       {"receiver_id": "different-receiver"}, {"episodes": ["test-episode-1"]}):
            altered = {**relation, **change}
            self.assertEqual(semantic_evidence(altered, native, data), [])

    def test_unsupported_native_relation_is_quarantined_and_never_asserted(self):
        data, native = self.fixture(22)
        native["edges"] = [{"uuid": "bad", "source_node_uuid": "missing", "target_node_uuid": "missing",
                            "receiver_id": data["receivers"][0]["receiver_id"], "episodes": ["test-episode-0"],
                            "attributes": {"quote": "secret-token", "parameter_pointer": "/query"}}]
        graph = self.project(data, native)
        self.assertEqual(len(graph["quarantined_semantic_relations"]), 1)
        self.assertFalse(any(n["type"] == "graphiti_relation_claim" for n in graph["nodes"]))

    def test_and_composition_cannot_survive_a_missing_premise(self):
        data, native = self.fixture(31)
        graph = self.project(data, native)
        index = next(i for i, e in enumerate(graph["edges"]) if e["kind"] == "and_premise")
        graph["edges"].pop(index)
        with self.assertRaises(ValueError):
            validate_task_graph(graph, self.tasks[data["task_key"]])

    def test_existing_annotation_cannot_import_a_new_secret(self):
        data, native = self.fixture(22)
        task = copy.deepcopy(self.tasks[data["task_key"]])
        task["disclosures"][0]["atoms"][0]["span"] = "not actually received"
        with self.assertRaises(ValueError):
            project_graph(data, native, task, self.categories, self.metadata)

    def test_real_graphiti_artifact_has_readback_and_evidence_checks(self):
        path = DEFAULT_OUTPUT / "任务隐私图.json"
        if not path.exists():
            self.skipTest("Run the real Graphiti ingestion before checking its persisted artifact")
        bundle = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(bundle["input_integrity"]["unchanged"])
        self.assertEqual(len(bundle["graphs"]), 3)
        for graph in bundle["graphs"].values():
            native = graph["graphiti_native"]
            self.assertTrue(native["readback_verified"])
            self.assertEqual(len(native["episodes"]), 2)
            self.assertTrue(graph["validation"]["passed"])
            self.assertFalse(graph["simplification"]["applied"])
            self.assertTrue(graph["privacy_projection_storage"]["readback_verified"])
            self.assertEqual(graph["privacy_projection_storage"]["nodes"], len(graph["nodes"]))
            self.assertEqual(graph["privacy_projection_storage"]["edges"], len(graph["edges"]))
            for relation in native["edges"]:
                self.assertIn(relation["receiver_id"], native["groups"])

    def test_unverified_relation_can_never_inherit_another_receivers_quote(self):
        data, native = self.fixture(31)
        rid = data["receivers"][0]["receiver_id"]
        native["nodes"] = [{"uuid": "person", "name": "Emma Johnson", "receiver_id": rid,
                             "group_id": "group-a", "summary": ""},
                            {"uuid": "place", "name": "Hawaii", "receiver_id": "other",
                             "group_id": "group-b", "summary": ""}]
        native["edges"] = [{"uuid": "cross", "source_node_uuid": "person", "target_node_uuid": "place",
                            "receiver_id": rid, "episodes": ["test-episode-1"],
                            "attributes": {"quote": "Hawaii", "parameter_pointer": "/content"}}]
        graph = self.project(data, native)
        self.assertEqual(len(graph["quarantined_semantic_relations"]), 1)
        self.assertFalse(any(n["type"] == "graphiti_relation_claim" for n in graph["nodes"]))


if __name__ == "__main__":
    unittest.main()
