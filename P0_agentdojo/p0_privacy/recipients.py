"""Resolve observed AgentDojo recipients; never infer them from task numbers.

AgentDojo has no general privacy-recipient API. This adapter combines its real
Function.dependencies with a deliberately bounded set of tool semantics.
Unknown semantics remain unresolved; resolution is not a leakage verdict.
"""
import argparse
import copy
import hashlib
import inspect
import json
from pathlib import Path

from agentdojo.task_suite.load_suites import get_suites

from p0.records import dump

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = ROOT / "runs" / "p0_20261028_seed20261028"
SERVICE_IDS = {"cloud_drive": "drive", "inbox": "email", "slack": "slack"}
SERVICE_NAMES = {"cloud_drive": "AgentDojo 模拟云盘应用服务",
                 "inbox": "AgentDojo 模拟邮件应用服务", "slack": "AgentDojo 模拟 Slack 应用服务"}
# Explicit request endpoint, distinct from secondary environment dependencies
# (e.g. calendar notifications or profile reads during a reservation).
ADDITIONAL_ENDPOINTS = {
    'calendar': ('calendar', '日历'), 'user': ('profile', '旅行用户资料'),
    'hotels': ('hotels', '酒店查询'), 'restaurants': ('restaurants', '餐厅查询'),
    'car_rental': ('car_rental', '租车查询'), 'reservation': ('reservation', '预订'),
    'flights': ('flights', '航班查询'), 'bank_account': ('bank', '银行账户'),
    'user_account': ('bank_profile', '银行用户资料'), 'filesystem': ('filesystem', '文件系统'),
    'web': ('web', '网页'),
}
SERVICE_IDS.update({k: v[0] for k, v in ADDITIONAL_ENDPOINTS.items()})
SERVICE_NAMES.update({k: 'AgentDojo 模拟' + v[1] + '服务' for k, v in ADDITIONAL_ENDPOINTS.items()})
PRIMARY_DEPENDENCY = {
    'create_calendar_event': 'calendar', 'cancel_calendar_event': 'calendar',
    'reschedule_calendar_event': 'calendar', 'reserve_hotel': 'reservation',
    'reserve_restaurant': 'reservation', 'reserve_car_rental': 'reservation',
}
# These implementations pass the request arguments to one injected service.
# Target-bearing or ACL-dependent operations require additional semantics below.
REQUEST_TOOLS = {
    "list_files", "get_file_by_id", "search_files", "search_files_by_filename", "create_file",
    "delete_file", "share_file", "append_to_file", "search_emails", "get_unread_emails",
    "get_sent_emails", "get_received_emails", "get_draft_emails", "delete_email",
    "search_contacts_by_name", "search_contacts_by_email", "send_email", "send_direct_message",
}
# The pinned benchmark tool inventory is exhaustively checked by Permissions;
# only these known names can enter the generic single-endpoint adapter.
from p0.policy import READ_TOOLS, WRITE_TOOLS
REQUEST_TOOLS.update(name for suites in (READ_TOOLS, WRITE_TOOLS)
                     for names in suites.values() for name in names)


def resolve_event(suite_name, node, tools):
    """Return the service request receipt and explicit downstream destinations.

The TOOL payload's target is the agent receiving the *response*, not the
recipient of the outgoing request. Only arguments are copied into receipts.
Downstream destinations are separate from service request memory: an email
recipient does not receive the complete send_email request, e.g. its BCC list.
"""
    payload = node["payload"]
    name, arguments = payload["name"], payload["arguments"]
    result = {"event_id": node["id"], "tool": name, "receipts": [], "destinations": [],
              "status": "unresolved", "reason": None, "privacy_leakage_verdict": "not_evaluated"}
    function = tools.get(name)
    if function is None or name not in REQUEST_TOOLS:
        result["reason"] = "Tool semantics are not implemented by this adapter"
        return result
    dependencies = [d.env_dependency for d in function.dependencies.values()]
    dependency = PRIMARY_DEPENDENCY.get(name, dependencies[0] if len(dependencies) == 1 else None)
    if dependency not in dependencies or dependency not in SERVICE_IDS:
        result["reason"] = "Expected one supported AgentDojo service dependency"
        return result
    source = Path(inspect.getsourcefile(function.run)).resolve()
    code = source.read_bytes()
    evidence = {"method": "agentdojo_dependency_and_tool_semantics", "dependency": dependency,
                "implementation": str(source), "implementation_line": inspect.getsourcelines(function.run)[1],
                "implementation_sha256": hashlib.sha256(code).hexdigest(),
                "request_evidence": "TOOL.payload.arguments", "task_number_used": False}
    evidence['secondary_dependencies_not_equated_to_request_receivers'] = [
        d for d in dependencies if d != dependency]
    result["receipts"].append({"receiver_id": f"app:{suite_name}:{SERVICE_IDS[dependency]}",
        "receiver_name": SERVICE_NAMES[dependency], "receiver_kind": "simulated_service",
        "received_request_parameters": copy.deepcopy(arguments), "evidence": evidence,
        "receipt_semantics": "observed_local_service_request_not_real_network_delivery"})
    result["status"] = "resolved"
    # The service receives a request even when execution fails. End recipients
    # must not be marked delivered merely because they appear in arguments.
    success = "error" in payload and payload["error"] is None
    if name == "send_email":
        for field in ("recipients", "cc", "bcc"):
            for address in arguments.get(field) or []:
                result["destinations"].append({"receiver_id": "email:" + address.lower(),
                    "receiver_name": address, "receiver_kind": "email_address", "parameter": field,
                    "status": "simulated_delivery_succeeded" if success else "delivery_not_confirmed",
                    "request_event_id": node["id"]})
    elif name == "send_direct_message":
        user = arguments["recipient"]
        result["destinations"].append({"receiver_id": "slack-user:" + user,
            "receiver_name": user, "receiver_kind": "slack_user", "parameter": "recipient",
            "status": "simulated_delivery_succeeded" if success else "delivery_not_confirmed",
            "request_event_id": node["id"]})
    elif name == "share_file":
        address = arguments["email"]
        result["destinations"].append({"receiver_id": "email:" + address.lower(),
            "receiver_name": address, "receiver_kind": "file_access_grantee", "parameter": "email",
            "status": "access_granted_not_read_proof" if success else "grant_not_confirmed",
            "request_event_id": node["id"]})
    elif name in {"append_to_file", "delete_file"}:
        # Existing ACLs can expose changes to other users. Do not silently assume
        # that the service is the only recipient without a time-correct snapshot.
        result["status"] = "partial"
        result["reason"] = "Existing file ACL visibility requires an event-time state snapshot"
    return result


def resolve_graph(task_key, graph, suite=None):
    suite_name = task_key.split("/", 1)[0]
    suite = suite or get_suites("v1.2")[suite_name]
    tools = {tool.name: tool for tool in suite.tools}
    events = [resolve_event(suite_name, n, tools) for n in graph["nodes"] if n["type"] == "TOOL"]
    return {"schema_version": "p0.agentdojo.recipients.v1", "task_key": task_key,
        "input_semantics": "actual_TOOL_events_and_registered_AgentDojo_Function_dependencies",
        "boundary": "business_service_requests_and_explicit_downstream_destinations; excludes A/B, user, model, audit",
        "resolution_status": ("no_tool_events" if not events else
                              "resolved" if all(e["status"] == "resolved" for e in events) else "incomplete"),
        "receiver_ids": sorted({r["receiver_id"] for e in events for r in e["receipts"]}),
        "destination_ids": sorted({r["receiver_id"] for e in events for r in e["destinations"]}),
        "events": events, "privacy_leakage_verdict": "not_evaluated"}


def attach_resolved_receivers(task, graph, graph_path, suite=None):
    """Feed resolved service receipts into the existing annotation/memory schema.

Explicit downstream destinations are exported separately. Their content views
need dedicated projections and are not equated to service request parameters.
"""
    from .annotation import source_candidates

    resolution = resolve_graph(task["task_key"], graph, suite)
    digest = hashlib.sha256(graph_path.read_bytes()).hexdigest()
    nodes = {n["id"]: n for n in graph["nodes"]}
    receivers, disclosures = {}, []
    for event in resolution["events"]:
        node = nodes[event["event_id"]]
        for receipt in event["receipts"]:
            rid = receipt["receiver_id"]
            receiver = receivers.setdefault(rid, {"receiver_id": rid, "name": receipt["receiver_name"],
                "memory_space_id": task["task_key"] + "::" + rid, "visibility": "请求参数",
                "receipt_rules": "只记录真实工具请求参数；工具返回值及既有存储不作为新增接收信息",
                "actual_disclosure_ids": [], "background_knowledge": {"status": "not_modeled", "facts": None},
                "recipient_resolution": receipt["evidence"]})
            did = task["task_key"] + "::" + rid + "::" + node["id"]
            receiver["actual_disclosure_ids"].append(did)
            disclosure = {"disclosure_id": did, "event_id": node["id"], "time": node["timestamp"],
                "receiver_id": rid, "receiver_name": receiver["name"], "receiver_visibility": receiver["visibility"],
                "receiver_rules": receiver["receipt_rules"], "tool": event["tool"],
                "received_request_parameters": receipt["received_request_parameters"],
                "evidence": str(graph_path) + "#" + node["id"], "source_graph_sha256": digest,
                "observation_semantics": receipt["receipt_semantics"], "tool_error": node["payload"].get("error"),
                "atoms": None, "parameter_reviews": None, "annotation_notes": None,
                "recipient_resolution": receipt["evidence"]}
            disclosure["source_candidates"] = source_candidates(graph, disclosure)
            disclosures.append(disclosure)
    task.update(receivers=list(receivers.values()), disclosures=disclosures, recipient_resolution=resolution)
    return task


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", default="workspace/user_task_31")
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    path = args.run_dir / args.task.replace("/", "_") / "graph.json"
    graph = json.loads(path.read_text(encoding="utf-8"))
    task = {"task_key": args.task, "prompt": graph["task"]["prompt"]}
    attach_resolved_receivers(task, graph, path)
    task["recipient_resolution"]["source_graph"] = str(path.resolve())
    task["recipient_resolution"]["source_graph_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    dump(args.output, task)
    print(json.dumps({"output": str(args.output), "receivers": [r["receiver_id"] for r in task["receivers"]],
                      "resolution_status": task["recipient_resolution"]["resolution_status"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
