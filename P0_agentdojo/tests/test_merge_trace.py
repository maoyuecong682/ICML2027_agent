import copy
import hashlib
import json
import unittest

from p0_privacy.merge_trace import BASE, build


class MergeTraceTests(unittest.TestCase):
    def setUp(self):
        raw = (BASE/"披露信息.json").read_bytes()
        self.disclosures = json.loads(raw)
        self.sha = hashlib.sha256(raw).hexdigest()
        self.relations = json.loads((BASE/"信息之间的关系.json").read_bytes())
        self.categories = json.loads((BASE/"类别-信息图.json").read_bytes())

    def run_build(self):
        return build(self.disclosures, self.relations, self.categories, self.sha, "workspace/user_task_31")

    def test_composition_preserves_leaf_inputs_and_is_not_counted_as_secret_recovery(self):
        trace = self.run_build()
        self.assertEqual(len(trace["steps"]), 4)
        self.assertEqual(trace["steps"][1]["leaf_information_ids"], ["I1", "I2", "I3"])
        self.assertEqual(trace["memory_summary"]["confirmed_indirect_secrets"], [])
        self.assertEqual(trace["memory_summary"]["unverified_indirect_candidates"], ["M3", "M4"])
        self.assertTrue(all(s["output_memory"]["privacy_gain_bits"] is None for s in trace["steps"]))

    def test_cross_receiver_input_is_rejected(self):
        task = next(t for t in self.relations["tasks"] if t["task_id"] == "workspace/user_task_31")
        task["information_units"][1]["receiver_id"] = "another_receiver"
        with self.assertRaises(ValueError):
            self.run_build()

    def test_false_binding_quote_is_rejected(self):
        task = next(t for t in self.relations["tasks"] if t["task_id"] == "workspace/user_task_31")
        task["joint_information_groups"][0]["evidence"]["quote"] = "invented trip"
        with self.assertRaises(ValueError):
            self.run_build()


if __name__ == "__main__":
    unittest.main()
