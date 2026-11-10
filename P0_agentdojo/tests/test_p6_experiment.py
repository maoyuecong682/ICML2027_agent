import copy
import json
import unittest

from p0_privacy.p6_experiment import ROOT, compact_receiver, score
from p0_privacy.p6_recovery import recover


class P6Tests(unittest.TestCase):
    def setUp(self):
        self.folder = ROOT/"outputs/p6_20261028/workspace_user_task_31"
        self.raw = json.loads((self.folder/"C0_original/receiver_memory.json").read_bytes())
        self.queries = json.loads((self.folder/"recovery_queries.json").read_bytes())

    def test_compact_preserves_answer_and_supporting_evidence(self):
        self.assertEqual(recover(self.raw, self.queries), recover(compact_receiver(self.raw), self.queries))

    def test_receiver_cannot_borrow_another_receivers_trip(self):
        for receipt in self.raw["receipts"]:
            receipt["receiver_id"] = "someone_else"
        self.assertIsNone(recover(self.raw, self.queries)[0]["top1_guess"])

    def test_annotated_source_and_evaluator_gold_do_not_enter_predictor(self):
        trip = self.raw["receipts"][1]["received_request_parameters"]["content"]
        for receipt in self.raw["receipts"]:
            receipt["received_request_parameters"] = {}
            receipt["source_candidates"] = [{"text": trip}]
        self.raw["reference_answer"] = trip
        self.assertIsNone(recover(self.raw, self.queries)[0]["top1_guess"])

    def test_no_trip_binding_means_no_joint_recovery(self):
        # Three strings merely co-occurring without the declared binding are insufficient.
        self.raw["receipts"][1]["received_request_parameters"]["content"] = (
            "Emma Johnson\nHawaii\nJune 10th - June 20th, 2024")
        self.assertIsNone(recover(self.raw, self.queries)[0]["top1_guess"])

    def test_null_abstention_is_scored_zero(self):
        predictions = [{"probe_id": "x", "top1_guess": None}]
        gold = [{"probe_id": "x", "value": "secret", "group": "test"}]
        self.assertEqual(score(predictions, gold)[0]["top1_recovery"], 0)

    def test_probe_alignment_is_checked(self):
        with self.assertRaises(AssertionError):
            score([{"probe_id": "wrong", "top1_guess": "secret"}],
                  [{"probe_id": "right", "value": "secret", "group": "test"}])

    def test_all_three_tasks_have_independent_positive_evidence_controls(self):
        base = ROOT/"outputs/p6_20261028"
        result = json.loads((base/"P6_实验结果.json").read_bytes())
        for task in result["tasks"]:
            self.assertTrue(task["judgment_equal_C0_C1_C2"])
            self.assertTrue(task["positive_control_evidence_dependency_passed"])
            self.assertTrue(all(c["before_occurrences"] > 0 and c["after_occurrences"] == 0
                                for c in task["deletion_checks"]))


if __name__ == "__main__":
    unittest.main()
