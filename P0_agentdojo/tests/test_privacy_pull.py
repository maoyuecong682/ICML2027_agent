"""Fixed-rule extractor: missing inputs and recipient separation must hold."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("privacy_pull", ROOT / "隐私拉取.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PrivacyPullTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder = ROOT / "outputs" / "ocelot_20261028"
        raw = (folder / "披露信息.json").read_bytes()
        cls.source = json.loads(raw)
        cls.relations = json.loads((folder / "信息之间的关系.json").read_text(encoding="utf-8"))
        cls.sha = MODULE.hash_json_bytes(raw)

    def run_extract(self, relations=None):
        return MODULE.extract(self.source, relations or self.relations, self.sha)

    def test_real_results_do_not_invent_token_or_unknown_tasks(self):
        result = self.run_extract()
        self.assertEqual(result["statistics"]["direct_disclosures"], 7)
        self.assertEqual(result["statistics"]["indirect_findings"], 2)
        reset = next(t for t in result["tasks"] if t["task_id"] == "workspace/user_task_22")
        self.assertEqual([f["field"] for f in reset["direct_disclosures"]], ["query_intent"])
        self.assertEqual(reset["indirect_findings"], [])
        self.assertEqual(sum(t["direct_disclosures"] is None for t in result["tasks"]), 94)

    def test_missing_joint_input_prevents_inference(self):
        rel = copy.deepcopy(self.relations)
        task = next(t for t in rel["tasks"] if t["task_id"] == "workspace/user_task_31")
        task["inference_candidates"][0]["all_of"].append("missing_atom")
        out = next(t for t in self.run_extract(rel)["tasks"] if t["task_id"] == task["task_id"])
        self.assertEqual(out["indirect_findings"], [])
        self.assertEqual(len(out["untriggered_inferences"]), 1)

    def test_recipient_mismatch_prevents_inference(self):
        rel = copy.deepcopy(self.relations)
        task = next(t for t in rel["tasks"] if t["task_id"] == "workspace/user_task_14")
        task["inference_candidates"][0]["receiver_id"] = "other-recipient"
        out = next(t for t in self.run_extract(rel)["tasks"] if t["task_id"] == task["task_id"])
        self.assertEqual(out["indirect_findings"], [])

    def test_invalid_association_quote_prevents_inference(self):
        rel = copy.deepcopy(self.relations)
        task = next(t for t in rel["tasks"] if t["task_id"] == "workspace/user_task_31")
        task["joint_information_groups"][0]["evidence"]["quote"] = "unrelated text"
        out = next(t for t in self.run_extract(rel)["tasks"] if t["task_id"] == task["task_id"])
        self.assertEqual(out["indirect_findings"], [])

    def test_changed_source_hash_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "哈希"):
            MODULE.extract(self.source, self.relations, "different")
