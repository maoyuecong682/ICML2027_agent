"""One task/recipient catalogue: observed traces plus local reference workflows.

No model or network calls. Reference workflows run on isolated copies of the
installed benchmark environment; they are never presented as agent executions.
"""
import argparse
import copy
import hashlib
import importlib.metadata
import inspect
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from agentdojo.functions_runtime import FunctionsRuntime
from agentdojo.task_suite.load_suites import get_suites

from p0.records import now
from .recipients import DEFAULT_RUN, ROOT, resolve_graph

DEFAULT_INPUT = ROOT / "outputs/ocelot_20261028/披露信息.json"
DEFAULT_OUTPUT = ROOT / "outputs/任务基本信息与接收者.json"
SERVICES = {
    "cloud_drive": ("drive", "模拟云盘应用服务"),
    "inbox": ("email", "模拟邮件应用服务"),
    "calendar": ("calendar", "模拟日历应用服务"),
    "slack": ("slack", "模拟 Slack 应用服务"),
    "bank_account": ("bank", "模拟银行应用服务"),
    "user_account": ("bank", "模拟银行应用服务"),
    "hotels": ("hotels", "模拟酒店信息查询服务"),
    "restaurants": ("restaurants", "模拟餐厅信息查询服务"),
    "car_rental": ("car_rental", "模拟租车信息查询服务"),
    "flights": ("flights", "模拟航班查询服务"),
    "reservation": ("reservation", "模拟预订应用服务"),
    "web": ("web", "模拟网页请求服务"),
}
LOCAL_SOURCES = {"filesystem", "user"}
TARGET_FIELDS = {"recipient", "recipients", "cc", "bcc", "participants", "event_id",
                 "channel", "user", "user_email", "email", "url", "hotel", "restaurant",
                 "company", "file_id", "id", "permission"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(env):
    return digest(json.dumps(env.model_dump(mode="json"), sort_keys=True,
                             ensure_ascii=False).encode("utf-8"))


def code_ref(function, sources):
    path = Path(inspect.getsourcefile(function)).resolve()
    key = path.as_posix()
    sources[key] = digest(path.read_bytes())
    return {"file": key, "line": inspect.getsourcelines(function)[1]}


class Recipients:
    def __init__(self, owner_emails=()):
        self.items = {}
        self.owner_emails = {str(x).lower() for x in owner_emails}

    def add(self, rid, name, kind, step, role, status, **details):
        item = self.items.setdefault(rid, {"receiver_id": rid, "name": name,
                                         "kind": kind, "evidence": []})
        evidence = {"step": step, "role": role, "status": status, **details}
        if evidence not in item["evidence"]:
            item["evidence"].append(evidence)

    def email(self, address, step, role, status, **details):
        if str(address).lower() not in self.owner_emails:
            self.add("email:" + str(address).lower(), str(address), "email_address",
                     step, role, status, **details)

    def result(self):
        return sorted(self.items.values(), key=lambda x: x["receiver_id"])


def destination_changes(found, name, args, before, after, index):
    """Resolve only outbound operations, never names merely present in read data."""
    if hasattr(after, "inbox"):
        old_ids = set(before.inbox.emails)
        for eid, message in after.inbox.emails.items():
            if eid in old_ids or str(message.status.value) != "sent":
                continue
            for field in ("recipients", "cc", "bcc"):
                for address in getattr(message, field) or []:
                    found.email(address, index, "email_delivery", "reference_simulated_delivery",
                                address_field=field, generated_email_id=str(eid))
    if name == "send_direct_message":
        user = args["recipient"]
        found.add("slack-user:" + user, user, "slack_user", index,
                  "direct_message", "reference_simulated_delivery")
    elif name == "send_channel_message":
        channel = args["channel"]
        found.add("slack-channel:" + channel, "#" + channel, "slack_channel", index,
                  "channel_message", "reference_simulated_post")
        for user, channels in after.slack.user_channels.items():
            if channel in channels and user != "bot":
                found.add("slack-user:" + user, user, "slack_user", index,
                          "channel_member_can_access", "reference_access_not_read_proof", channel=channel)
    elif name == "invite_user_to_slack":
        found.email(args["user_email"], index, "workspace_invitation_target",
                    "reference_target_no_email_delivery_implemented", slack_user=args["user"])
        found.add("slack-user:" + args["user"], args["user"], "slack_user", index,
                  "workspace_access_grantee", "reference_access_not_read_proof")
    elif name == "add_user_to_channel":
        user = args["user"]
        found.add("slack-user:" + user, user, "slack_user", index,
                  "channel_access_grantee", "reference_access_not_read_proof", channel=args["channel"])
    elif name in {"get_webpage", "post_webpage", "download_file"}:
        url = args["url"]
        parsed = urlsplit(url if "://" in url else "//" + url)
        if not parsed.netloc:
            raise ValueError(f"Cannot resolve website: {url}")
        host = parsed.netloc.lower()
        found.add("website:" + host, host, "website", index, "web_request",
                  "reference_simulated_request", url=url)
        if name == "post_webpage":
            found.add("public-web:" + url, "网页公开读者：" + url, "public_audience", index,
                      "published_page_audience", "reference_publication_not_read_proof", url=url)
    elif name in {"share_file", "append_to_file", "delete_file"}:
        file_id = args["file_id"]
        file = (after if name == "share_file" else before).cloud_drive.files[file_id]
        if name == "share_file":
            found.email(args["email"], index, "file_access_grantee",
                        "reference_access_not_read_proof", file_id=file_id, permission=args["permission"])
        else:
            for address, permission in file.shared_with.items():
                found.email(address, index,
                            "existing_file_access_holder" if name == "append_to_file" else "file_deletion_observer",
                            "reference_access_not_read_proof" if name == "append_to_file"
                            else "reference_deletion_visibility_only", file_id=file_id, permission=str(permission))
    elif name == "add_calendar_event_participants":
        for address in args["participants"]:
            found.email(address, index, "calendar_participant",
                        "reference_participant_registered_no_email_delivery", event_id=args["event_id"])
    elif name == "send_money":
        target = args["recipient"]
        found.add("bank-payee:" + target, target, "payment_payee", index,
                  "payment_target", "reference_simulated_transfer")
    elif name in {"schedule_transaction", "update_scheduled_transaction"}:
        if name == "schedule_transaction":
            target = args["recipient"]
        else:
            target = next(t.recipient for t in after.bank_account.scheduled_transactions if t.id == args["id"])
        found.add("scheduled-payee:" + target, target, "scheduled_payee", index,
                  "future_payment_target", "reference_schedule_only_not_received")
    elif name in {"reserve_hotel", "reserve_restaurant", "reserve_car_rental"}:
        field = {"reserve_hotel": "hotel", "reserve_restaurant": "restaurant", "reserve_car_rental": "company"}[name]
        target = args[field]
        found.add("booking-target:" + field + ":" + target, target, "booking_target", index,
                  "booking_target", "reference_reservation_state_only_no_merchant_delivery")


def reference_task(suite, task, sources, initial=None):
    initial = initial if initial is not None else suite.load_and_inject_default_environment({})
    env = task.init_environment(initial.model_copy(deep=True))
    owners = [getattr(getattr(env, name, None), "account_email", "") for name in ("inbox", "calendar", "cloud_drive")]
    found = Recipients(owners)
    source = {"kind": "official_reference_workflow", "ground_truth": code_ref(task.ground_truth, sources),
              "initial_environment_sha256": fingerprint(env)}
    calls = task.ground_truth(env.model_copy(deep=True))
    runtime = FunctionsRuntime(suite.tools)
    steps, local_resources = [], set()
    for index, call in enumerate(calls):
        function = runtime.functions[call.function]
        dependencies = [d.env_dependency for d in function.dependencies.values()]
        if any(d not in SERVICES and d not in LOCAL_SOURCES for d in dependencies):
            raise ValueError(f"Unsupported dependency in {suite.name}/{task.ID}: {dependencies}")
        # Preserve pre-call arguments: calendar tools mutate participants in place.
        args = copy.deepcopy(call.args)
        step = {"step": index, "tool": call.function, "dependencies": dependencies,
                "implementation": code_ref(function.run, sources),
                "target_arguments": {k: v for k, v in args.items() if k in TARGET_FIELDS}}
        before = env.model_copy(deep=True)
        _, error = runtime.run_function(env, call.function, copy.deepcopy(call.args))
        if error is not None:
            raise ValueError(f"Reference call failed in {suite.name}/{task.ID}: {call.function}: {error}")
        step["local_reference_execution"] = "succeeded"
        steps.append(step)
        for dependency in dependencies:
            if dependency in LOCAL_SOURCES:
                local_resources.add(dependency)
                continue
            # The calendar wrapper always receives an inbox dependency, but its
            # email service is only a sink if an email was actually generated.
            if dependency == "inbox" and "calendar" in dependencies:
                if set(before.inbox.emails) == set(env.inbox.emails):
                    continue
            short, label = SERVICES[dependency]
            found.add(f"app:{suite.name}:{short}", label, "simulated_service", index,
                      "generated_email_service" if dependency == "inbox" and "calendar" in dependencies
                      else "service_request", "reference_local_simulation", dependency=dependency)
        destination_changes(found, call.function, args, before, env, index)
    return {"resolution_basis": "official_reference_workflow", "resolution_status": "reference_resolved",
            "receivers": found.result(), "recipient_evidence": {"source": source, "steps": steps,
            "local_sources_not_external_receivers": sorted(local_resources)}}


def observed_task(key, suite, sources):
    path = DEFAULT_RUN / key.replace("/", "_") / "graph.json"
    graph = json.loads(path.read_text(encoding="utf-8"))
    resolution = resolve_graph(key, graph, suite)
    if resolution["resolution_status"] != "resolved":
        raise ValueError(f"Incomplete observed recipient resolution: {key}")
    found, steps = Recipients(), []
    for index, event in enumerate(resolution["events"]):
        for receipt in event["receipts"]:
            found.add(receipt["receiver_id"], receipt["receiver_name"], "simulated_service", index,
                      "service_request", "observed_local_service_request", event_id=event["event_id"])
        for destination in event["destinations"]:
            found.add(destination["receiver_id"], destination["receiver_name"], destination["receiver_kind"],
                      index, "downstream_target", destination["status"], event_id=event["event_id"])
        function = next(t for t in suite.tools if t.name == event["tool"])
        steps.append({"step": index, "event_id": event["event_id"], "tool": event["tool"],
                      "implementation": code_ref(function.run, sources)})
    return {"resolution_basis": "observed_agent_trace", "resolution_status": "observed_resolved",
            "receivers": found.result(), "recipient_evidence": {"source": {
                "kind": "observed_agent_trace", "file": path.relative_to(ROOT).as_posix(),
                "sha256": digest(path.read_bytes())}, "steps": steps}}


def build_catalog(input_path=DEFAULT_INPUT):
    original_bytes = input_path.read_bytes()
    original = json.loads(original_bytes)
    existing = {t["task_key"]: t for t in original["tasks"]}
    suites, sources, tasks = get_suites("v1.2"), {}, []
    native_keys = {f"{name}/{task.ID}" for name, suite in suites.items() for task in suite.user_tasks.values()}
    if set(existing) != native_keys or len(existing) != 97:
        raise ValueError("Task population differs from installed AgentDojo v1.2")
    for name, suite in sorted(suites.items()):
        initial = suite.load_and_inject_default_environment({})
        initial_hash = fingerprint(initial)
        for task in sorted(suite.user_tasks.values(), key=lambda t: int(t.ID.rsplit("_", 1)[1])):
            key = name + "/" + task.ID
            old = existing[key]
            if old["prompt"] != task.PROMPT:
                raise ValueError(f"Task prompt differs from benchmark: {key}")
            item = {"task_key": key, "suite": name, "task_id": task.ID, "prompt": task.PROMPT,
                    "difficulty": task.DIFFICULTY.name, "execution_status": old["execution_status"],
                    "category_ids": old["category_ids"], "primary_category_id": old["primary_category_id"],
                    "official_task_success": old["official_task_success"]}
            if old["execution_status"] == "已执行":
                item.update(observed_task(key, suite, sources))
            else:
                item.update(reference_task(suite, task, sources, initial))
            if not item["receivers"]:
                raise ValueError(f"No receivers resolved: {key}")
            tasks.append(item)
        if fingerprint(initial) != initial_hash:
            raise ValueError(f"Shared initial environment was mutated: {name}")
    kinds = Counter(r["kind"] for t in tasks for r in t["receivers"])
    return {"schema_version": "p0.task_recipient_catalog.v1", "created_at": now(),
            "agentdojo_version": importlib.metadata.version("agentdojo"), "benchmark_version": "v1.2",
            "source": {"merged_task_metadata_from": input_path.relative_to(ROOT).as_posix(),
                       "sha256": digest(original_bytes), "code_sources_sha256": sources},
            "semantics": {
                "scope": "97 个任务合并目录：94 个官方参考流程接收者，3 个已有 agent 轨迹接收者。",
                "reference": "官方 ground_truth 在独立的本地模拟环境中执行；不是模型执行、不是已发生披露、不是所有可能执行路径。",
                "observed": "已有 agent 实际 TOOL 轨迹中的请求接收者；仍为 AgentDojo 本地模拟。",
                "services": "服务边界与 ID 是本实验对工具依赖的映射，不代表外部真实供应商或新增知识。",
                "conditional_targets": "权限获得者、频道可访问成员、未来计划收款方、预订目标、公开读者均由 evidence.status 区分；不代表已阅读或已投递。",
                "excluded": "执行 agent A/B、用户本人、模型服务和审计器沿用原业务边界排除；本地文件系统及用户资料源单列，不当成外部接收者。",
                "privacy": "未做隐私泄露判定；接收者身份不等于获得新知识。邮件收件人不得获得其他 BCC 的可见内容。",
                "runtime": "上线仍须按实际工具参数、当时 ACL/频道成员和执行结果重新解析，不能仅按 task_id 固定接收者。",
                "storage": "将已有任务基本信息和新接收者合并到此单一 JSON；原始披露、运行和哈希引用产物保持原样。"},
            "statistics": {"tasks": len(tasks), "new_reference_tasks": sum(t["resolution_basis"] == "official_reference_workflow" for t in tasks),
                           "existing_observed_tasks": sum(t["resolution_basis"] == "observed_agent_trace" for t in tasks),
                           "tasks_by_suite": dict(Counter(t["suite"] for t in tasks)),
                           "task_receiver_pairs": sum(len(t["receivers"]) for t in tasks),
                           "receiver_kinds": dict(kinds), "unresolved_tasks": 0,
                           "reference_tool_calls": sum(len(t["recipient_evidence"]["steps"]) for t in tasks
                                                       if t["resolution_basis"] == "official_reference_workflow")},
            "tasks": tasks}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    if args.output.resolve() == args.input.resolve():
        parser.error("Keep the hashed historical disclosure input unchanged; use the consolidated catalogue path")
    catalog = build_catalog(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".tmp")
    temporary.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    json.loads(temporary.read_text(encoding="utf-8"))
    temporary.replace(args.output)
    print(json.dumps({"output": str(args.output), **catalog["statistics"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
