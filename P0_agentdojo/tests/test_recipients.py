"""Recipient resolution against installed tools and immutable real traces."""
import copy
import json
import unittest

from agentdojo.task_suite.load_suites import get_suites
from p0_privacy.recipients import DEFAULT_RUN, resolve_event, resolve_graph
from p0_privacy.build import read_tasks


class RecipientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.suites = get_suites("v1.2")
        cls.tools = {t.name: t for t in cls.suites["workspace"].tools}
        cls.graph = json.loads((DEFAULT_RUN / "workspace_user_task_31" / "graph.json").read_text(encoding="utf-8"))

    def test_task31_uses_real_requests_and_never_response_contents(self):
        resolved = resolve_graph("workspace/user_task_31", self.graph, self.suites["workspace"])
        self.assertEqual(resolved["resolution_status"], "resolved")
        self.assertEqual(resolved["receiver_ids"], ["app:workspace:drive"])
        self.assertEqual(resolved["destination_ids"], [])
        self.assertEqual([e["tool"] for e in resolved["events"]], ["list_files", "create_file"])
        self.assertEqual(resolved["events"][0]["receipts"][0]["received_request_parameters"], {})
        for event in resolved["events"]:
            receipt = event["receipts"][0]
            original = next(n for n in self.graph["nodes"] if n["id"] == event["event_id"])
            self.assertEqual(receipt["received_request_parameters"], original["payload"]["arguments"])
            self.assertEqual(receipt["evidence"]["dependency"], "cloud_drive")
        altered = copy.deepcopy(self.graph)
        for node in altered["nodes"]:
            if node["type"] == "TOOL":
                node["payload"]["result"] = "SECRET_ONLY_IN_RESPONSE"
                node["payload"]["target"] = "unrelated-response-reader"
        other = resolve_graph("workspace/user_task_99999", altered, self.suites["workspace"])
        self.assertEqual(other["events"], resolved["events"])

    def test_failed_mail_still_reaches_service_but_not_confirmed_addressee(self):
        node = {"id": "test", "payload": {"name": "send_email", "arguments": {
            "recipients": ["a@example.com"], "cc": ["b@example.com"], "bcc": ["c@example.com"],
            "subject": "subject", "body": "body"}, "error": "failed"}}
        result = resolve_event("workspace", node, self.tools)
        self.assertEqual(result["receipts"][0]["receiver_id"], "app:workspace:email")
        self.assertEqual(len(result["destinations"]), 3)
        self.assertTrue(all(d["status"] == "delivery_not_confirmed" for d in result["destinations"]))
        node["payload"]["error"] = None
        self.assertTrue(all(d["status"] == "simulated_delivery_succeeded"
                            for d in resolve_event("workspace", node, self.tools)["destinations"]))

    def test_share_is_permission_not_reading_and_unknown_is_unresolved(self):
        node = {"id": "test", "payload": {"name": "share_file", "arguments": {
            "file_id": "1", "email": "a@example.com", "permission": "r"}, "error": None}}
        result = resolve_event("workspace", node, self.tools)
        self.assertEqual(result["destinations"][0]["status"], "access_granted_not_read_proof")
        node["payload"]["name"] = "unknown_tool"
        self.assertEqual(resolve_event("workspace", node, self.tools)["status"], "unresolved")
        node["payload"]["name"] = "append_to_file"
        self.assertEqual(resolve_event("workspace", node, self.tools)["status"], "partial")
        self.assertEqual(resolve_graph("workspace/empty", {"nodes": []}, self.suites["workspace"])
                         ["resolution_status"], "no_tool_events")

    def test_build_integrates_resolver_for_all_observed_tasks(self):
        tasks = read_tasks()
        observed = [t for t in tasks if t["execution_status"] == "已执行"]
        self.assertEqual(len(observed), 3)
        self.assertTrue(all(t["recipient_resolution"]["resolution_status"] == "resolved" for t in observed))
        self.assertEqual(sum(len(t["disclosures"]) for t in observed), 6)
        task = next(t for t in observed if t["task_key"] == "workspace/user_task_31")
        self.assertEqual([r["receiver_id"] for r in task["receivers"]], ["app:workspace:drive"])
        self.assertTrue(all(d["recipient_resolution"]["task_number_used"] is False for d in task["disclosures"]))


if __name__ == "__main__":
    unittest.main()
