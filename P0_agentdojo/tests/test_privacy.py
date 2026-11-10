"""Evidence-boundary and graph checks; no model calls and no task execution."""
import copy
import math
import unittest

from p0_privacy.annotation import validate_response
from p0_privacy.build import read_tasks
from p0_privacy.catalog import CATEGORIES
from p0_privacy.graphs import make_graph, min_entropy_gain
from p0_privacy.validate import validate_graph


def fixture():
    disclosure = {"disclosure_id": "task::receiver::e1", "received_request_parameters": {"query": "family reunion"},
                  "source_candidates": [{"source_id": "user:task", "provenance": "user-input",
                                         "text": "When is the family reunion?"}]}
    atom = {"span": "family reunion", "parameter_path": "/query", "field": "query_intent",
            "kind": "direct", "relation": "direct", "necessity": "required", "provenance": "user-input",
            "source_ids": ["user:task"], "op": "identity", "rationale": "Query needed for lookup", "inference_claim": None}
    response = {"disclosures": [{"disclosure_id": disclosure["disclosure_id"], "atoms": [atom],
                                 "parameter_reviews": [{"parameter_path": "/query", "assessment": "sensitive",
                                                        "reason": "query intent"}], "notes": []}]}
    return disclosure, response


class PrivacyTests(unittest.TestCase):
    def test_actual_request_is_the_span_boundary_not_private_sources(self):
        disclosure, response = fixture()
        validate_response(response, [disclosure])
        disclosure["source_candidates"][0]["text"] += " DOB: 1990-05-01"
        response["disclosures"][0]["atoms"][0].update(span="1990-05-01", field="dob")
        with self.assertRaisesRegex(ValueError, "Span not found"):
            validate_response(response, [disclosure])

    def test_wrong_source_type_and_missing_review_are_rejected(self):
        disclosure, response = fixture()
        invalid = copy.deepcopy(response)
        invalid["disclosures"][0]["atoms"][0]["provenance"] = "user-local"
        with self.assertRaisesRegex(ValueError, "Provenance"):
            validate_response(invalid, [disclosure])
        invalid = copy.deepcopy(response)
        invalid["disclosures"][0]["parameter_reviews"] = []
        with self.assertRaisesRegex(ValueError, "Incomplete parameter"):
            validate_response(invalid, [disclosure])

    def test_no_atoms_in_empty_request_and_no_omitted_disclosures(self):
        disclosure, response = fixture()
        disclosure["received_request_parameters"] = {}
        response["disclosures"][0]["parameter_reviews"] = []
        with self.assertRaises(ValueError):
            validate_response(response, [disclosure])
        with self.assertRaisesRegex(ValueError, "exactly once"):
            validate_response({"disclosures": []}, [disclosure])

    def test_sensitive_atom_and_nonsensitive_review_cannot_both_pass(self):
        disclosure, response = fixture()
        response["disclosures"][0]["parameter_reviews"][0]["assessment"] = "no_sensitive_content"
        with self.assertRaisesRegex(ValueError, "Contradictory sensitivity"):
            validate_response(response, [disclosure])

    def test_all_graphs_have_valid_tree_decompositions_and_joint_scopes(self):
        for cid in CATEGORIES:
            validate_graph(make_graph(cid, []))
        packing = make_graph("packing_list", [])
        self.assertTrue(any(len(f["scope"]) > 2 for f in packing["factors"]))
        self.assertIsNone(packing["posterior_audit"]["gain_bits"])
        self.assertFalse(packing["posterior_audit"]["quantitative_ready"])

    def test_all_97_native_tasks_keep_the_execution_evidence_boundary(self):
        tasks = read_tasks()
        self.assertEqual(len(tasks), 97)
        unexecuted = [t for t in tasks if t["execution_status"] == "未执行"]
        self.assertEqual(len(unexecuted), 94)
        self.assertTrue(all(t["disclosures"] is None for t in unexecuted))
        self.assertEqual(sum(len(t["disclosures"] or []) for t in tasks), 6)
        self.assertEqual(sum(not d["received_request_parameters"] for t in tasks for d in t["disclosures"] or []), 3)

    def test_entropy_calculation_requires_real_distributions(self):
        self.assertAlmostEqual(min_entropy_gain({"a": .5, "b": .5}, {"a": 1, "b": 0}), 1)
        self.assertAlmostEqual(min_entropy_gain({"a": .8, "b": .2}, {"a": .8, "b": .2}), 0)
        for prior, posterior in [({"a": 1}, {"b": 1}), ({"a": .2}, {"a": 1}),
                                  ({"a": math.nan}, {"a": 1})]:
            with self.assertRaises(ValueError):
                min_entropy_gain(prior, posterior)


if __name__ == "__main__":
    unittest.main()
