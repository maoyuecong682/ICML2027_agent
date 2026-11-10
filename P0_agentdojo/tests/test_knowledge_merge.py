"""Receiver boundaries, genuine coalition gains, contradictions and ablation."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from p0_privacy.knowledge_merge import (
    DEFAULT_RECORD, DEFAULT_RUN, compare_knowledge, digest, input_from_observed_graph,
    input_from_observed_record, main, merge_knowledge,
)


def claim(subject, predicate, obj, context=None):
    return {"subject": subject, "predicate": predicate, "object": obj,
            "context": {} if context is None else context}


def example():
    return {"task_key": "synthetic/coalition", "task_text": "Synthetic test, not an AgentDojo run",
            "trace_kind": "synthetic", "receivers": [
                {"receiver_id": "A", "view_complete": True}, {"receiver_id": "B", "view_complete": True}],
            "receipts": [], "facts": [], "rules": [], "single_valued_predicates": ["identity", "destination"]}


def add(data, rid, subject, predicate, obj, context=None):
    n = len(data["facts"])
    receipt_id = "receipt:" + str(n)
    data["receipts"].append({"receipt_id": receipt_id, "receiver_id": rid, "status": "received",
                             "trace_kind": data["trace_kind"], "parameters": {"value": obj}})
    data["facts"].append({"fact_id": "source:" + str(n), "receipt_id": receipt_id, "receiver_id": rid,
                          "claim": claim(subject, predicate, obj, context),
                          "evidence": {"parameter_pointer": "/value", "quoted_value": obj}})


def identify_rule():
    return {"rule_id": "link-identity-to-travel", "justification": "Explicit test correspondence rule",
            "premises": [claim("?code", "identity", "?name"), claim("?code", "destination", "?place")],
            "conclusion": claim("?name", "travels_to", "?place")}


def pooled_nodes(output):
    return {n["fact_id"]: n for n in output["coalition_knowledge"]["knowledge"]}


class KnowledgeMergeTests(unittest.TestCase):
    def test_optional_defaults_and_coalition_requires_both_receivers(self):
        data = example()
        add(data, "A", "X17", "identity", "Alice")
        add(data, "B", "X17", "destination", "Hawaii")
        data["rules"] = [identify_rule()]
        before = copy.deepcopy(data)
        off, on = merge_knowledge(data), merge_knowledge(data, enabled=True)
        self.assertEqual(off["status"], "disabled")
        self.assertIsNone(off["coalition_knowledge"])
        self.assertEqual(on["status"], "merged")
        self.assertEqual(off["receiver_knowledge"], on["receiver_knowledge"])
        self.assertEqual(len(on["new_joint_inferences"]), 1)
        node = pooled_nodes(on)[on["new_joint_inferences"][0]]
        self.assertEqual(node["claim"], claim("Alice", "travels_to", "Hawaii"))
        self.assertEqual(node["minimal_receiver_sets"], [["A", "B"]])
        self.assertEqual(len(node["proofs"][0]["premise_fact_ids"]), 2)
        self.assertTrue(all(not r["inferred_fact_ids"] for r in on["receiver_knowledge"].values()))
        self.assertEqual(data, before)

    def test_overlap_is_alignment_not_new_knowledge(self):
        data = example()
        for rid in ("A", "B"):
            add(data, rid, "X17", "identity", "Alice")
        output = merge_knowledge(data, enabled=True)
        self.assertEqual(output["new_joint_inferences"], [])
        self.assertEqual(len(pooled_nodes(output)), 1)
        self.assertEqual(output["alignments"][0]["receivers"], ["A", "B"])
        self.assertEqual(next(iter(pooled_nodes(output).values()))["minimal_receiver_sets"], [["A"], ["B"]])

    def test_alternative_single_receiver_proof_removes_false_joint_gain(self):
        data = example()
        add(data, "A", "X17", "identity", "Alice")
        add(data, "B", "X17", "identity", "Alice")
        add(data, "B", "X17", "destination", "Hawaii")
        data["rules"] = [identify_rule()]
        on, off = merge_knowledge(data, enabled=True), merge_knowledge(data)
        self.assertEqual(on["new_joint_inferences"], [])
        self.assertEqual(len(on["joint_inferences"]), 1)
        node = pooled_nodes(on)[on["joint_inferences"][0]]
        self.assertEqual(node["minimal_receiver_sets"], [["B"]])
        self.assertEqual(on["receiver_knowledge"], off["receiver_knowledge"])

    def test_similar_codes_never_align_without_identity_evidence(self):
        data = example()
        add(data, "A", "X17", "identity", "Alice")
        add(data, "B", "X18", "destination", "Hawaii")
        data["rules"] = [identify_rule()]
        self.assertEqual(merge_knowledge(data, enabled=True)["new_joint_inferences"], [])
        data["entity_equivalences"] = [{"alias": "X18", "canonical": "X17", "justification": "Test ID mapping"}]
        self.assertEqual(len(merge_knowledge(data, enabled=True)["new_joint_inferences"]), 1)

    def test_explicit_predicate_equivalence_aligns_duplicate_claims(self):
        data = example()
        add(data, "A", "X17", "destination", "Hawaii")
        add(data, "B", "X17", "travel_destination", "Hawaii")
        data["predicate_equivalences"] = [{"alias": "travel_destination", "canonical": "destination",
                                            "justification": "Test relation glossary"}]
        self.assertEqual(len(merge_knowledge(data, enabled=True)["alignments"]), 1)

    def test_conflicting_values_survive_and_taint_inferences(self):
        data = example()
        add(data, "A", "X17", "identity", "Alice")
        add(data, "A", "X17", "destination", "Hawaii")
        add(data, "B", "X17", "destination", "Tokyo")
        # Arrival time does not authorize a last-write-wins correction.
        data["receipts"][-1]["time"] = "2099-01-01"
        data["rules"] = [identify_rule()]
        output = merge_knowledge(data, enabled=True)
        conflicts = output["coalition_knowledge"]["conflicts"]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["resolution"], "retain_all_unresolved")
        destinations = [n for n in pooled_nodes(output).values() if n["claim"]["predicate"] == "destination"]
        self.assertEqual({n["claim"]["object"] for n in destinations}, {"Hawaii", "Tokyo"})
        for fid in output["joint_inferences"]:
            self.assertEqual(pooled_nodes(output)[fid]["epistemic_status"], "conflict_related")

    def test_different_temporal_contexts_and_multivalued_lists_do_not_conflict(self):
        data = example()
        add(data, "A", "X17", "destination", "Hawaii", {"period": "2024"})
        add(data, "B", "X17", "destination", "Tokyo", {"period": "2025"})
        add(data, "A", "X17", "packing.item", "Camera")
        add(data, "B", "X17", "packing.item", "Swimwear")
        self.assertEqual(merge_knowledge(data, enabled=True)["coalition_knowledge"]["conflicts"], [])

    def test_multistep_proof_preserves_and_supports(self):
        data = example()
        add(data, "A", "X17", "identity", "Alice")
        add(data, "B", "X17", "destination", "Hawaii")
        data["rules"] = [identify_rule(), {
            "rule_id": "travel-activity", "justification": "Only a test implication, not an absence claim",
            "premises": [claim("?person", "travels_to", "?place")],
            "conclusion": claim("?person", "has_travel_plan", True)}]
        output = merge_knowledge(data, enabled=True)
        self.assertEqual(len(output["new_joint_inferences"]), 2)
        self.assertTrue(all(pooled_nodes(output)[fid]["minimal_receiver_sets"] == [["A", "B"]]
                            for fid in output["new_joint_inferences"]))

    def test_missing_content_is_insufficient_not_zero_gain(self):
        data = example()
        data["receivers"][1]["view_complete"] = False
        output = merge_knowledge(data, enabled=True)
        self.assertEqual(output["status"], "insufficient_information")
        self.assertIsNone(output["coalition_knowledge"])
        self.assertIsNone(output["new_joint_inferences"])

    def test_invalid_evidence_wrong_recipient_permission_and_mixed_traces_rejected(self):
        data = example()
        add(data, "A", "X17", "identity", "Alice")
        changes = [("bad quote", lambda d: d["facts"][0]["evidence"].update(quoted_value="secret")),
                   ("wrong receiver", lambda d: d["facts"][0].update(receiver_id="B")),
                   ("access only", lambda d: d["receipts"][0].update(status="access_granted_not_read_proof")),
                   ("mixed traces", lambda d: d["receipts"][0].update(trace_kind="reference"))]
        for name, change in changes:
            with self.subTest(name=name):
                altered = copy.deepcopy(data)
                change(altered)
                with self.assertRaises(ValueError):
                    merge_knowledge(altered, enabled=True)

    def test_rule_requires_bound_conclusion_and_aliases_cannot_cycle(self):
        data = example()
        data["rules"] = [identify_rule()]
        data["rules"][0]["conclusion"]["subject"] = "?unbound"
        with self.assertRaises(ValueError):
            merge_knowledge(data, enabled=True)
        data["rules"] = []
        data["entity_equivalences"] = [{"alias": "a", "canonical": "b", "justification": "test"},
                                        {"alias": "b", "canonical": "a", "justification": "test"}]
        with self.assertRaises(ValueError):
            merge_knowledge(data, enabled=True)

    def test_actual_task31_skips_single_receiver_preserves_raw_evidence_and_source(self):
        record_before = DEFAULT_RECORD.read_bytes()
        data = input_from_observed_record(DEFAULT_RECORD)
        self.assertEqual(len(data["receivers"]), 1)
        self.assertEqual([r["tool"] for r in data["receipts"]], ["list_files", "create_file"])
        self.assertEqual(data["receipts"][0]["parameters"], {})
        self.assertNotIn("source_candidates", json.dumps(data))
        self.assertEqual(len(data["facts"]), 11)
        text = data["receipts"][1]["parameters"]["content"]
        self.assertIn("June 10th - June 20th, 2024 (Emma Johnson)", text)
        on, off = merge_knowledge(data, enabled=True), merge_knowledge(data)
        self.assertEqual(on["status"], "skipped_single_receiver")
        self.assertEqual(off["status"], "disabled")
        self.assertEqual(on["receiver_knowledge"], off["receiver_knowledge"])
        self.assertEqual(on["new_joint_inferences"], [])
        self.assertIsNone(on["coalition_knowledge"])
        self.assertEqual(DEFAULT_RECORD.read_bytes(), record_before)
        self.assertEqual(on["input_sha256"], digest(data))

    def test_cli_both_arms_in_one_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "experiment.json"
            main(["--receiver-merge", "both", "--output", str(output)])
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(set(report["outputs"]), {"off", "on"})
            self.assertTrue(report["experiment"]["identical_local_baseline_verified"])
            self.assertEqual(report["outputs"]["on"]["input_sha256"], report["outputs"]["off"]["input_sha256"])

    def test_comparison_separates_peer_transfers_and_novel_joint_inference(self):
        data = example()
        add(data, "A", "X17", "identity", "Alice")
        add(data, "B", "X17", "destination", "Hawaii")
        data["rules"] = [identify_rule()]
        result = compare_knowledge(merge_knowledge(data), merge_knowledge(data, enabled=True))
        self.assertEqual(result["new_joint_knowledge_count"], 1)
        for rid, predicate in (("A", "destination"), ("B", "identity")):
            gain = result["per_receiver_gains"][rid]
            self.assertEqual(gain["new_to_receiver_count"], 2)
            self.assertEqual(gain["existing_knowledge_from_peers"][0]["claim"]["predicate"], predicate)
            self.assertEqual(gain["new_jointly_inferred_knowledge"][0]["claim"]["predicate"], "travels_to")
        altered = merge_knowledge(data, enabled=True)
        altered["input_sha256"] = "different-input"
        with self.assertRaises(ValueError):
            compare_knowledge(merge_knowledge(data), altered)
        data["receivers"][1]["view_complete"] = False
        result = compare_knowledge(merge_knowledge(data), merge_knowledge(data, enabled=True))
        self.assertIsNone(result["new_joint_knowledge_count"])
        self.assertIsNone(result["per_receiver_gains"]["A"]["new_to_receiver_count"])

    def test_actual_task14_task22_use_only_received_search_queries(self):
        for number, query in ((14, "family reunion"), (22, "TechServices password reset")):
            with self.subTest(task=number):
                path = DEFAULT_RUN / f"workspace_user_task_{number}" / "graph.json"
                original = path.read_bytes()
                data = input_from_observed_graph(path)
                self.assertEqual(data["task_key"], f"workspace/user_task_{number}")
                self.assertEqual([r["receiver_id"] for r in data["receivers"]], ["app:workspace:email"])
                self.assertEqual([r["parameters"] for r in data["receipts"]], [{"query": query}, {}])
                self.assertEqual(len(data["facts"]), 1)
                self.assertEqual(data["facts"][0]["claim"]["object"], query)
                self.assertNotIn("source_candidates", json.dumps(data))
                result = compare_knowledge(merge_knowledge(data), merge_knowledge(data, enabled=True))
                self.assertEqual(result["status"], "skipped_single_receiver")
                self.assertEqual(result["new_joint_knowledge_count"], 0)
                self.assertEqual(result["new_joint_knowledge"], [])
                self.assertEqual(result["per_receiver_gains"]["app:workspace:email"]["new_to_receiver_count"], 0)
                self.assertEqual(path.read_bytes(), original)

    def test_cli_multiple_actual_tasks_need_no_intermediary_records(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "batch.json"
            main(["--tasks", "workspace/user_task_14", "workspace/user_task_22",
                  "--receiver-merge", "both", "--output", str(output)])
            self.assertEqual(list(Path(directory).iterdir()), [output])
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["task_count"], 2)
            self.assertEqual(set(report["tasks"]), {"workspace/user_task_14", "workspace/user_task_22"})
            for task in report["tasks"].values():
                self.assertEqual(task["outputs"]["off"]["status"], "disabled")
                self.assertEqual(task["outputs"]["on"]["status"], "skipped_single_receiver")
                self.assertTrue(task["comparison"]["same_input_and_local_baseline_verified"])


if __name__ == "__main__":
    unittest.main()
