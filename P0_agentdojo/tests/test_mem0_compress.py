import copy
import json
from pathlib import Path
import unittest

from mem0_compress import compact, source_block, validate_snapshot


class CompressionProtectionTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1]/"runs/p0_20261028_seed20261028/workspace_user_task_31/requests.jsonl"
        self.rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]

    def test_both_actors_derive_same_trip_from_their_own_checkpoint(self):
        blocks = [source_block(actor, self.rows[i]["request"]["messages"])
                  for actor, i in (("A", 2), ("B", 3))]
        self.assertEqual(blocks[0]["trip"], blocks[1]["trip"])
        self.assertEqual(blocks[0]["trip"]["traveler"], "Emma Johnson")
        self.assertEqual(len(blocks[0]["packing_list"]), 6)

    def test_missing_trip_field_is_rejected(self):
        before = self.rows[3]["request"]["messages"]
        protected = source_block("B", before)
        after = copy.deepcopy(before)
        changed = copy.deepcopy(protected)
        del changed["trip"]["traveler"]
        after[-1]["content"] = compact({"protected_source": changed})
        with self.assertRaises(AssertionError):
            validate_snapshot(before, after, protected)

    def test_modified_tool_id_is_rejected(self):
        before = self.rows[3]["request"]["messages"]
        protected = source_block("B", before)
        after = copy.deepcopy(before)
        after[-1]["content"] = compact({"protected_source": protected})
        after[-1]["tool_call_id"] = "invalid"
        with self.assertRaises(AssertionError):
            validate_snapshot(before, after, protected)


if __name__ == "__main__":
    unittest.main()
