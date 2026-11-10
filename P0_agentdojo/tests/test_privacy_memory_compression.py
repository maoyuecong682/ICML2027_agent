import copy
import json
from pathlib import Path
import tempfile
import unittest

from privacy_memory_compression import (
    compress_memory, inference_blocks, normalize, render_memory, validate_groups,
)


def block(identifier, text, receiver="drive", field="travel_itinerary", event="e1"):
    return {"id": identifier, "task_id": "workspace/user_task_31", "receiver_id": receiver,
            "field": field, "text": text, "event_id": event}


class PrivacyTextTests(unittest.TestCase):
    def setUp(self):
        self.trip = "Trip: Hawaii, June 10th - June 20th, 2024 (Emma Johnson)"
        self.document = normalize({"schema": "privacy.text.input.v1", "blocks": [
            block("a", self.trip), block("b", self.trip, event="e2")],
            "links": [{"link_id": "binding", "type": "observed_binding", "members": ["a", "b"]}]})

    def test_none_is_exact_per_occurrence_and_does_not_mutate_input(self):
        original = copy.deepcopy(self.document)
        with tempfile.TemporaryDirectory() as directory:
            memory = compress_memory(self.document, output_dir=Path(directory)/"none")
        self.assertEqual(self.document, original)
        self.assertEqual([b["text"] for b in inference_blocks(memory)], [self.trip, self.trip])
        self.assertEqual(len(memory["facts"]), 2)

    def test_duplicate_fact_keeps_both_events_and_binding(self):
        memory = render_memory([{"text": self.trip, "source_ids": ["a", "b"]}], self.document)
        self.assertEqual(len(memory["facts"]), 1)
        self.assertEqual([o["event_id"] for o in memory["occurrences"]], ["e1", "e2"])
        self.assertEqual(memory["links"], self.document["links"])
        self.assertEqual([b["text"] for b in inference_blocks(memory)], [self.trip, self.trip])

    def test_cross_receiver_field_and_kind_merges_rejected(self):
        for key, value in (("receiver_id", "other"), ("task_id", "other"),
                           ("field", "legal_name"), ("kind", "indirect"), ("relation", "implicit")):
            data = copy.deepcopy(self.document)
            data["blocks"][1][key] = value
            with self.assertRaises(ValueError):
                validate_groups([{"text": self.trip, "source_ids": ["a", "b"]}], data["blocks"])

    def test_missing_duplicated_and_fabricated_sources_rejected(self):
        for ids in (["a"], ["a", "a", "b"], ["a", "b", "invented"]):
            with self.assertRaises(ValueError):
                validate_groups([{"text": self.trip, "source_ids": ids}], self.document["blocks"])
        with self.assertRaises(ValueError):
            validate_groups([{"text": "invented summary", "source_ids": ["a", "b"]}], self.document["blocks"])

    def test_no_original_text_backdoor_after_paraphrase_merge(self):
        data = copy.deepcopy(self.document)
        data["blocks"][1]["text"] = "Emma Johnson plans to visit Hawaii June 10th - June 20th, 2024."
        compressed = render_memory([{"text": self.trip, "source_ids": ["a", "b"]}], data)
        self.assertNotIn(data["blocks"][1]["text"], json.dumps(compressed))
        self.assertEqual(len(compressed["occurrences"]), 2)

    def test_raw_adapter_excludes_sources_and_gold(self):
        raw = {"schema": "p6.receiver.raw.v1", "task_id": "t", "reference_answer": "gold",
               "receipts": [{"event_id": "e1", "receiver_id": "r", "source_candidates": ["hidden"],
                             "received_request_parameters": {"content": self.trip}}]}
        data = normalize(raw)
        self.assertEqual(len(data["blocks"]), 1)
        self.assertNotIn("gold", json.dumps(data))
        self.assertNotIn("hidden", json.dumps(data))

    def test_none_needs_no_mem0_or_key_and_existing_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"output"
            compress_memory(self.document, strategy="none", output_dir=path)
            with self.assertRaises(FileExistsError):
                compress_memory(self.document, strategy="none", output_dir=path)
        with self.assertRaises(ValueError):
            compress_memory(self.document, strategy="mem0", output_dir="unused", api_key=None)


if __name__ == "__main__":
    unittest.main()
