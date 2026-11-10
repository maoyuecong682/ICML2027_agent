"""Export all three privacy processes as one self-contained sequential JSON."""
import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs" / "ocelot_20261028"
TARGET = SOURCE / "三个任务-隐私泄露过程.json"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def atom_record(atom):
    # Keep the original model labels and evidence offsets. Visualization and
    # template matching metadata do not belong to the sequential representation.
    return {k: copy.deepcopy(v) for k, v in atom.items()
            if k not in ("graph_bindings", "graph_binding_status", "provenance_evidence")}


def evaluate_conditions(process, category_map, visible_atoms):
    result = []
    for factor in process["joint_factors"]:
        category = category_map[factor["category_id"]]
        template = next(f for f in category["factors"] if f["id"] == factor["template_factor_id"])
        target = next(s.split(":", 1)[1] for s in template["scope"] if s.startswith("secret:"))
        labels = {n["id"]: n["label"] for n in category["nodes"]}
        inputs = []
        for slot in factor["required_slots"]:
            supporting = [visible_atoms[a] for a in factor["support"][slot] if a in visible_atoms]
            inputs.append({"variable": slot.split(":", 1)[1], "description": labels[slot],
                           "available": bool(supporting),
                           "supporting_atoms": [{"atom_id": a["atom_id"], "span": a["span"],
                                                 "parameter_path": a["parameter_path"]} for a in supporting]})
        missing = [item["variable"] for item in inputs if not item["available"]]
        result.append({"inference_id": factor["category_id"] + ":" + factor["template_factor_id"],
            "category_id": factor["category_id"], "target_field": target,
            "target_description": labels["secret:" + target], "hypothesis": template["description"],
            "origin": "本实验类别规则草案，非 OCELOT 作者规则库", "receiver_id": factor["receiver_id"],
            "required_inputs": inputs, "missing_inputs": missing,
            "status": "missing_evidence_not_activated" if missing else "evidence_available_unverified",
            "status_description": "输入不全，当前联合路径未激活" if missing else "输入线索齐备，推断结论尚未验证",
            "recovery_test": "not_run", "privacy_gain_bits": None})
    return result


def export():
    paths = [SOURCE / "披露信息.json", SOURCE / "类别-信息图.json",
             *sorted((SOURCE / "任务隐私过程图").glob("workspace_user_task_*/*.json"))]
    before = {str(p.relative_to(ROOT)).replace("\\", "/"): digest(p) for p in paths}
    disclosures = load(paths[0])
    category_map = {g["category_id"]: g for g in load(paths[1])["graphs"]}
    processes = {p["task"]["task_key"]: p for p in (load(path) for path in paths[2:])}
    tasks = []
    for original in disclosures["tasks"]:
        if original["execution_status"] != "已执行":
            continue
        process = processes[original["task_key"]]
        receivers = copy.deepcopy(original["receivers"])
        request_history = {r["receiver_id"]: [] for r in receivers}
        atom_history = {r["receiver_id"]: {} for r in receivers}
        audit_sources = {}
        original_events = {n["id"]: n for n in load(ROOT / original["disclosures"][0]["evidence"].split("#", 1)[0])["nodes"]}
        task = {"task_id": original["task_key"], "task_name": process["title"], "prompt": original["prompt"],
            "categories": [{"id": cid, "name": category_map[cid]["category_name"],
                            "necessity_rules": copy.deepcopy(category_map[cid]["necessity_rubric"]["rules"])}
                           for cid in original["category_ids"]],
            "execution_status": original["execution_status"], "official_task_success": original["official_task_success"],
            "execution_agents": {"count": 2, "agents": ["A", "B"],
                                 "provider": "DeepSeek", "model": process["execution_config"]["model"]},
            "annotation_model": copy.deepcopy(original["model_annotation"]),
            "receivers": receivers, "audit_sources": [], "steps": [], "final_receiver_memory": [],
            "privacy_assessment": {"inappropriate_leakage": "not_evaluated", "secret_recovery_test": "not_run",
                                   "prior_knowledge": "not_modeled", "privacy_gain_bits": None,
                                   "operator_suggestions_applied": False}}
        for sequence, disclosure in enumerate(sorted(original["disclosures"], key=lambda d: d["time"]), 1):
            rid = disclosure["receiver_id"]
            old_history = copy.deepcopy(request_history[rid])
            request = {"event_id": disclosure["event_id"], "time": disclosure["time"], "tool": disclosure["tool"],
                       "received_parameters": copy.deepcopy(disclosure["received_request_parameters"]),
                       "tool_error": disclosure["tool_error"]}
            request_history[rid].append(request)
            annotations = [atom_record(a) for a in disclosure["atoms"]]
            for atom in annotations:
                atom_history[rid][atom["atom_id"]] = atom
            for source in disclosure["source_candidates"]:
                evidence = source["evidence"]
                reference = {"kind": "original_user_task"} if isinstance(evidence, str) else {
                    "kind": "previous_tool_return", "event_id": evidence["event_id"],
                    "tool": evidence["tool"], "returned_data_pointer": evidence["result_pointer"],
                    "returned_data_encoding": evidence["result_encoding"]}
                audit_sources[source["source_id"]] = {"source_id": source["source_id"],
                    "provenance": source["provenance"], "text": source["text"], "reference": reference,
                    "whole_source_newly_disclosed": False}
            task["steps"].append({"sequence": sequence, "event_id": disclosure["event_id"],
                "time": disclosure["time"], "acting_agent": original_events[disclosure["event_id"]]["actor"],
                "receiver_id": rid, "receiver_name": disclosure["receiver_name"],
                "tool": disclosure["tool"], "received_parameters": copy.deepcopy(disclosure["received_request_parameters"]),
                "tool_error": disclosure["tool_error"], "receipt_semantics": disclosure["observation_semantics"],
                "source_evidence": disclosure["evidence"],
                "memory_before": {"received_request_count": len(old_history), "received_requests": old_history},
                "disclosed_atoms": annotations,
                "parameter_reviews": copy.deepcopy(disclosure["parameter_reviews"]),
                "annotation_notes": copy.deepcopy(disclosure["annotation_notes"]),
                "memory_after": {"received_request_count": len(request_history[rid]),
                                 "received_requests": copy.deepcopy(request_history[rid])},
                "potential_joint_inferences": [f for f in evaluate_conditions(process, category_map, atom_history[rid])
                                              if f["receiver_id"] == rid]})
        task["audit_sources"] = list(audit_sources.values())
        task["final_receiver_memory"] = [{"receiver_id": rid, "received_requests": history}
                                         for rid, history in request_history.items()]
        tasks.append(task)
    package = {"schema_version": "p0.privacy_process.sequential.v1", "title": "三个任务-隐私泄露过程",
        "representation": "按任务与时间顺序组织的独立数据记录", "statistics": {
            "task_count": len(tasks), "request_count": sum(len(t["steps"]) for t in tasks),
            "annotation_count": sum(len(s["disclosed_atoms"]) for t in tasks for s in t["steps"])},
        "scope": copy.deepcopy(disclosures["boundary"]),
        "field_definitions": {
            "steps": "实际工具请求及其接收过程，按时间排序",
            "memory_before/memory_after": "该接收者在本任务中已收到的完整请求历史；不包含未知的既有知识",
            "disclosed_atoms": "原有模型标注，保留 span/field/kind/necessity/provenance/op 与原文位置",
            "audit_sources": "用于追溯的原文资料；不是接收者收到的额外正文",
            "potential_joint_inferences": "按当时累计可见片段检查类别规则的输入条件；不代表秘密已被恢复",
            "op": "模型建议，未实际应用", "privacy_gain_bits": "null 表示尚未测量，不是零泄露"},
        "source_sha256": before, "tasks": tasks}
    validate(package, disclosures)
    assert before == {str(p.relative_to(ROOT)).replace("\\", "/"): digest(p) for p in paths}
    TARGET.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
    json.loads(TARGET.read_text(encoding="utf-8"))
    print(json.dumps({"output": str(TARGET), "statistics": package["statistics"],
                      "validation_passed": True, "source_files_unchanged": True}, ensure_ascii=False))


def validate(package, source):
    original = {t["task_key"]: t for t in source["tasks"] if t["execution_status"] == "已执行"}
    assert {t["task_id"] for t in package["tasks"]} == set(original)
    assert package["statistics"] == {"task_count": 3, "request_count": 6, "annotation_count": 15}
    for task in package["tasks"]:
        raw = {d["event_id"]: d for d in original[task["task_id"]]["disclosures"]}
        source_ids = {s["source_id"] for s in task["audit_sources"]}
        for step in task["steps"]:
            disclosure = raw[step["event_id"]]
            assert step["received_parameters"] == disclosure["received_request_parameters"]
            assert step["disclosed_atoms"] == [atom_record(a) for a in disclosure["atoms"]]
            assert step["memory_after"]["received_requests"][:-1] == step["memory_before"]["received_requests"]
            assert all(set(a["source_ids"]) <= source_ids for a in step["disclosed_atoms"])
            for inference in step["potential_joint_inferences"]:
                assert bool(inference["missing_inputs"]) == (inference["status"] == "missing_evidence_not_activated")
                assert inference["privacy_gain_bits"] is None
        assert task["privacy_assessment"]["privacy_gain_bits"] is None

    def no_diagram_structure(value):
        if isinstance(value, dict):
            assert not (set(value) & {"nodes", "edges", "graph_type", "graph_role", "display_groups"})
            for item in value.values():
                no_diagram_structure(item)
        elif isinstance(value, list):
            for item in value:
                no_diagram_structure(item)
    no_diagram_structure(package)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    export()
