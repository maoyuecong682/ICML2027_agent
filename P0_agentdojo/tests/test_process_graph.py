"""Task-specific recipient evidence, factor prerequisites, and lossless labels."""
import json
import unittest

from p0_privacy.process_graph import SOURCE, build_task_graph, validate_graph


class TaskPrivacyGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        disclosures = json.loads((SOURCE / "披露信息.json").read_text(encoding="utf-8"))
        categories = json.loads((SOURCE / "类别-信息图.json").read_text(encoding="utf-8"))
        category_map = {g["category_id"]: g for g in categories["graphs"]}
        cls.tasks = {t["task_key"]: t for t in disclosures["tasks"] if t["execution_status"] == "已执行"}
        cls.graphs = {key: build_task_graph(t, category_map, {"ontology": disclosures["ontology"]})
                      for key, t in cls.tasks.items()}

    def test_all_three_graphs_preserve_original_requests_and_annotations(self):
        for key, graph in self.graphs.items():
            self.assertTrue(validate_graph(graph, self.tasks[key])["passed"])
            raw = {d["disclosure_id"]: d["received_request_parameters"] for d in self.tasks[key]["disclosures"]}
            actual = {n["disclosure_id"]: n["parameters"] for n in graph["nodes"] if n["type"] == "actual_disclosure"}
            self.assertEqual(raw, actual)

    def test_indirect_annotation_does_not_activate_a_joint_factor_with_missing_sender(self):
        graph = self.graphs["workspace/user_task_14"]
        self.assertTrue(any(e["kind"] == "indirect_label" for e in graph["edges"]))
        factor = graph["joint_factors"][0]
        self.assertEqual(factor["missing_slots"], ["atom:sender"])
        self.assertIsNone(factor["first_evidence_complete_memory"])
        self.assertEqual(graph["statistics"]["atoms"], 2)
        self.assertEqual(graph["statistics"]["unique_visible_spans"], 1)

    def test_reset_intent_is_not_a_reset_token_in_the_recipient_view(self):
        graph = self.graphs["workspace/user_task_22"]
        self.assertFalse(any(n.get("field") in ("password_reset_token", "security_code") for n in graph["nodes"]))
        self.assertEqual(graph["joint_factors"][0]["missing_slots"], ["atom:email"])
        self.assertTrue(all("token=" not in str(n.get("parameters", {})) for n in graph["nodes"]))

    def test_packing_joint_evidence_first_appears_after_write_and_never_implies_recovery(self):
        graph = self.graphs["workspace/user_task_31"]
        self.assertTrue(all(f["first_evidence_complete_memory"] == "memory:0:2" for f in graph["joint_factors"]))
        self.assertIsNone(graph["assessment"]["privacy_gain_bits"])
        self.assertEqual(graph["assessment"]["secret_recovery_test"], "not_run")
        self.assertEqual(graph["execution_config"]["model"], "deepseek-flash")

    def test_source_reference_does_not_bind_to_the_new_filename_slot(self):
        graph = self.graphs["workspace/user_task_31"]
        reference = next(n for n in graph["nodes"] if n["type"] == "disclosed_atom" and n["label"] == "vacation-plans.docx")
        self.assertFalse(any(b["atom_id"] == reference["id"] and b["template_node"] == "atom:filename"
                             for b in graph["slot_binding_evidence"]))
        source = next(n for n in graph["nodes"] if n["type"] == "audit_provenance_source" and n["provenance"] == "user-local")
        self.assertFalse(source["receiver_visible_as_whole"])


if __name__ == "__main__":
    unittest.main()
