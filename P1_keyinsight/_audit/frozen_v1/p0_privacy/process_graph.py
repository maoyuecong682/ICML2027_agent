"""Instantiate task-specific disclosure graphs from existing, immutable evidence.

No task execution, model calls, label editing, or numeric privacy claims.
"""
import copy
import hashlib
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from p0.records import dump, now

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs" / "ocelot_20261028"
OUTPUT = SOURCE / "任务隐私过程图"
SEMANTICS = {
    "received": "已记录的工具请求进入本实验定义的业务接收者；本地模拟，不是互联网投递证明",
    "memory_update": "同一接收者按时间保留请求历史；不代表测得知识增益",
    "contains_atom": "接收请求中逐字存在的已标注片段；相同片段的不同标签不能累加为多个泄露量",
    "retains_atom": "接收者在该时刻的累计记忆包含此片段",
    "provenance": "审计资料来源，不代表该来源全文也向业务接收者发送",
    "direct_label": "原有模型认为片段直接编码此字段；语义判断尚未人工复核",
    "indirect_label": "原有模型提出的潜在推断；不代表接收者已恢复秘密",
    "factor_support": "实际可见片段可绑定类别因子的一个输入槽位；全部槽位有证据仍不证明推断成功",
    "factor_output": "类别规则提出的推断目标；没有概率校准或秘密恢复实验",
}
TITLES = {
    "email_read": "查询家庭聚会时间", "credential_lookup": "查找密码重置链接",
    "packing_list": "创建夏威夷打包清单",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_pointer(value, pointer):
    for part in pointer.lstrip("/").split("/") if pointer else []:
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def bind_slots(category, disclosure, atoms):
    """Explicit semantic bridges; ambiguous original field matches stay unbound.

    Crucially, a cited source filename in /content is NOT the new /filename.
    Non-sensitive list items may supply evidence to a contextual hypothesis.
    """
    slots = defaultdict(list)
    rules = []
    for atom in atoms:
        name = None
        path, field = atom["parameter_path"], atom["field"]
        if category["category_id"] == "packing_list":
            mapping = {"legal_name": "traveler_name", "travel_destination": "destination", "travel_dates": "dates"}
            if path == "/content" and field in mapping and atom["kind"] == "direct":
                name = mapping[field]
            elif path == "/filename":
                name = "filename"
            elif path == "/content" and field == "none":
                normalized = disclosure["received_request_parameters"]["content"].replace("\\n", "\n")
                if any(line.strip() == "- " + atom["span"] for line in normalized.splitlines()):
                    name = "packing_items"
        elif category["category_id"] in ("email_read", "credential_lookup"):
            if path == "/query" and field == "query_intent":
                name = "query"
            elif path == "/sender":
                name = "sender"
            elif category["category_id"] == "credential_lookup" and path == "/query" and field == "none":
                # This is only a proposed role for a non-sensitive qualifier.
                # It cannot make a subscription factor ready without identity.
                name = "service"
        if name:
            slot = "atom:" + name
            if slot in {n["id"] for n in category["nodes"]}:
                slots[slot].append(atom["atom_id"])
                rules.append({"atom_id": atom["atom_id"], "template_node": slot,
                              "method": "explicit_parameter_and_annotation_role",
                              "status": "candidate_binding_not_expert_validated"})
    return dict(slots), rules


def build_task_graph(task, categories, source_meta):
    graph = {"schema_version": "p0.ocelot.task_privacy_process.v1", "created_at": now(),
        "task": {k: copy.deepcopy(task[k]) for k in ("task_key", "prompt", "category_ids", "official_task_success")},
        "title": TITLES.get(task["primary_category_id"], task["primary_category_id"]),
        "graph_type": "directed_typed_evidence_graph_with_joint_factor_scopes",
        "graph_role": "实际接收过程、累计记忆、原有片段标注与类别推断因子的任务级关联",
        "sources": source_meta, "nodes": [], "edges": [], "joint_factors": [],
        "timeline": [], "receiver_memory": [], "execution_trace": [],
        "boundary": {"execution_agents": ["A", "B"], "agents_are_leakage_sinks": False,
                     "user_is_leakage_sink": False, "model_provider_is_leakage_sink": False,
                     "receipt": "AgentDojo 本地模拟应用请求投影", "collusion": False,
                     "background_knowledge": "not_modeled"},
        "edge_semantics": SEMANTICS,
        "assessment": {"leakage_verdict": "not_evaluated", "privacy_gain_bits": None,
                       "posterior": None, "calibration": "not_done", "secret_recovery_test": "not_run",
                       "annotation_model": copy.deepcopy(task["model_annotation"]),
                       "operators_applied": False,
                       "note": "可见敏感片段与不当泄露分别判断；服务可能已有原始资料，不能断言新增了知识"},
        "display_groups": [],
    }
    nodes, edges = graph["nodes"], graph["edges"]
    node_map = {}

    def node(nid, kind, label, **attributes):
        if nid not in node_map:
            item = {"id": nid, "type": kind, "label": label, **attributes}
            nodes.append(item)
            node_map[nid] = item
        return node_map[nid]

    def edge(a, b, kind, **attributes):
        item = {"id": f"edge:{len(edges)}", "source": a, "target": b, "kind": kind,
                "semantics": SEMANTICS[kind], **attributes}
        edges.append(item)
        return item

    disclosures = sorted(task["disclosures"], key=lambda d: d["time"])
    original_path = ROOT / disclosures[0]["evidence"].split("#", 1)[0]
    original = json.loads(original_path.read_text(encoding="utf-8"))
    graph["execution_config"] = copy.deepcopy(original["config"])
    for original_node in original["nodes"]:
        graph["execution_trace"].append({"event_id": original_node["id"], "type": original_node["type"],
            "actor": original_node["actor"], "label": original_node["label"], "time": original_node["timestamp"],
            "evidence": str(original_path.relative_to(ROOT)).replace("\\", "/") + "#" + original_node["id"],
            "counts_as_business_disclosure": original_node["type"] == "TOOL"})
    by_receiver = defaultdict(list)
    for disclosure in disclosures:
        by_receiver[disclosure["receiver_id"]].append(disclosure)
    for receiver_index, receiver in enumerate(task["receivers"]):
        rid = receiver["receiver_id"]
        receiver_node = node(f"receiver:{receiver_index}", "business_receiver", receiver["name"],
            receiver_id=rid, visibility=receiver["visibility"], receipt_rules=receiver["receipt_rules"],
            background_knowledge=receiver["background_knowledge"])
        state_prefix = f"memory:{receiver_index}:"
        last_state = node(state_prefix + "0", "receiver_memory_state", "M0 · 本任务尚无接收记录",
                          receiver_id=rid, step=0, cumulative_disclosure_ids=[], cumulative_atom_ids=[],
                          initial_knowledge=None, initial_knowledge_status="unknown_not_empty_assumption")
        prior_disclosures, prior_atoms = [], []
        for step, disclosure in enumerate(by_receiver[rid], 1):
            original_event = next(n for n in original["nodes"] if n["id"] == disclosure["event_id"])
            if original_event["payload"]["arguments"] != disclosure["received_request_parameters"]:
                raise ValueError("Source trace and disclosure parameters differ")
            request = node("request:" + disclosure["event_id"], "actual_disclosure", disclosure["tool"],
                disclosure_id=disclosure["disclosure_id"], event_id=disclosure["event_id"],
                actor=original_event["actor"], time=disclosure["time"], receiver_id=rid,
                parameters=copy.deepcopy(disclosure["received_request_parameters"]),
                evidence=disclosure["evidence"], source_graph_sha256=disclosure["source_graph_sha256"],
                empty_parameters=not bool(disclosure["received_request_parameters"]),
                source_candidates=copy.deepcopy(disclosure["source_candidates"]),
                parameter_reviews=copy.deepcopy(disclosure["parameter_reviews"]),
                annotation_notes=copy.deepcopy(disclosure["annotation_notes"]))
            edge(request["id"], receiver_node["id"], "received", evidence=disclosure["evidence"])
            prior_disclosures.append(disclosure["disclosure_id"])
            prior_atoms.extend(a["atom_id"] for a in disclosure["atoms"])
            current_state = node(state_prefix + str(step), "receiver_memory_state", f"M{step} · 累计 {step} 次请求",
                receiver_id=rid, step=step, time=disclosure["time"],
                cumulative_disclosure_ids=list(prior_disclosures), cumulative_atom_ids=list(prior_atoms),
                initial_knowledge=None, initial_knowledge_status="unknown_not_empty_assumption")
            edge(last_state["id"], current_state["id"], "memory_update", new_disclosure_id=disclosure["disclosure_id"])
            edge(request["id"], current_state["id"], "memory_update", actual_new_request=True)
            graph["timeline"].append({"step": step, "receiver_id": rid, "request_node": request["id"],
                                      "before_memory": last_state["id"], "after_memory": current_state["id"],
                                      "time": disclosure["time"]})
            for atom in disclosure["atoms"]:
                atom_node = node(atom["atom_id"], "disclosed_atom", atom["span"],
                    receiver_id=rid, disclosure_id=disclosure["disclosure_id"],
                    visible_since_memory=current_state["id"], annotation=copy.deepcopy(atom))
                text = str(resolve_pointer(disclosure["received_request_parameters"], atom["parameter_path"]))
                if text[atom["span_start"]:atom["span_end"]] != atom["span"]:
                    raise ValueError("Annotated span not present at original offsets")
                edge(request["id"], atom_node["id"], "contains_atom", parameter_path=atom["parameter_path"],
                     span_start=atom["span_start"], span_end=atom["span_end"])
                for sid in atom["source_ids"]:
                    source = next(s for s in disclosure["source_candidates"] if s["source_id"] == sid)
                    source_node = node("source:" + sid, "audit_provenance_source", sid,
                        provenance=source["provenance"], text=source["text"], evidence=source["evidence"],
                        receiver_visible_as_whole=False)
                    edge(source_node["id"], atom_node["id"], "provenance",
                         match="exact_substring" if atom["span"] in source["text"] else "model_attribution_unverified")
                if atom["field"] != "none":
                    label = source_meta["ontology"].get(atom["field"], atom["field"])
                    field_node = node(f"field:{receiver_index}:" + atom["field"], "sensitive_field", label,
                        receiver_id=rid, field=atom["field"], direct_values=[], indirect_annotation_ids=[],
                        privacy_gain_bits=None, recovery_status="not_tested")
                    if atom["kind"] == "direct" and atom["span"] not in field_node["direct_values"]:
                        field_node["direct_values"].append(atom["span"])
                    if atom["kind"] == "indirect":
                        field_node["indirect_annotation_ids"].append(atom["atom_id"])
                    edge(atom_node["id"], field_node["id"],
                         "direct_label" if atom["kind"] == "direct" else "indirect_label",
                         evidence_kind="existing_model_annotation", annotation_model="deepseek-flash",
                         claim=atom.get("inference_claim"))
            last_state = current_state
        for atom_id in prior_atoms:
            edge(last_state["id"], atom_id, "retains_atom")
        graph["receiver_memory"].append({"receiver_id": rid, "receiver_node": receiver_node["id"],
            "memory_space_id": receiver["memory_space_id"], "final_state": last_state["id"],
            "received_requests": [{"disclosure_id": d["disclosure_id"], "event_id": d["event_id"],
                                   "tool": d["tool"], "time": d["time"],
                                   "parameters": copy.deepcopy(d["received_request_parameters"])} for d in by_receiver[rid]]})
        for category_id in task["category_ids"]:
            category = categories[category_id]
            slot_bindings = defaultdict(list)
            for disclosure in by_receiver[rid]:
                slots, rules = bind_slots(category, disclosure, disclosure["atoms"])
                for slot, atom_ids in slots.items():
                    slot_bindings[slot].extend(atom_ids)
                graph.setdefault("slot_binding_evidence", []).extend({"category_id": category_id, **r} for r in rules)
            for factor in category["factors"]:
                if factor["relation"] != "joint_inference_hypothesis":
                    continue
                slots = [s for s in factor["scope"] if s.startswith("atom:")]
                missing = [s for s in slots if not slot_bindings.get(s)]
                support = {s: list(dict.fromkeys(slot_bindings.get(s, []))) for s in slots}
                secret = next(s.split(":", 1)[1] for s in factor["scope"] if s.startswith("secret:"))
                factor_id = f"factor:{receiver_index}:{category_id}:{factor['id']}"
                status = "evidence_available_unverified" if not missing else "missing_evidence_not_activated"
                supported_atom_ids = {a for atoms in support.values() for a in atoms}
                complete_states = [n for n in nodes if n["type"] == "receiver_memory_state"
                                   and n["receiver_id"] == rid and not missing
                                   and supported_atom_ids <= set(n["cumulative_atom_ids"])]
                first_complete = min(complete_states, key=lambda n: n["step"])["id"] if complete_states else None
                target = node(f"field:{receiver_index}:" + secret, "sensitive_field", source_meta["ontology"][secret],
                    receiver_id=rid, field=secret, direct_values=[], indirect_annotation_ids=[],
                    privacy_gain_bits=None, recovery_status="not_tested")
                factor_node = node(factor_id, "category_inference_factor", factor["description"],
                    receiver_id=rid, category_id=category_id, template_factor_id=factor["id"],
                    template_scope=copy.deepcopy(factor["scope"]), support=support, missing_slots=missing,
                    status=status, probability_table=None, privacy_gain_bits=None,
                    evaluated_at_memory=last_state["id"], first_evidence_complete_memory=first_complete,
                    prerequisite_semantics="所有列出槽位均须有证据；不因存在一条支持边就宣称联合推断成立")
                for slot, atom_ids in support.items():
                    for atom_id in atom_ids:
                        edge(atom_id, factor_id, "factor_support", template_slot=slot,
                             evidence_kind="deterministic_candidate_binding")
                edge(factor_id, target["id"], "factor_output", status=status, probability=None)
                graph["joint_factors"].append({"factor_node": factor_id, "output_node": target["id"],
                    "receiver_id": rid, "category_id": category_id, "template_factor_id": factor["id"],
                    "scope": factor["scope"], "required_slots": slots, "support": support,
                    "missing_slots": missing, "status": status, "evaluated_at_memory": last_state["id"],
                    "first_evidence_complete_memory": first_complete})
    # Render grouping is explicit and lossless: none of the original 15 labels
    # are silently removed merely to make the PNG simpler.
    groups = defaultdict(list)
    for n in nodes:
        if n["type"] == "disclosed_atom":
            a = n["annotation"]
            key = (n["receiver_id"], a["field"], a["necessity"], a["op"])
            groups[key].append(n["id"])
    for i, (key, atom_ids) in enumerate(groups.items()):
        graph["display_groups"].append({"id": f"view-group:{i}", "atom_ids": atom_ids,
                                        "receiver_id": key[0], "field": key[1], "necessity": key[2], "op": key[3]})
    graph["statistics"] = {"requests": len(disclosures), "receivers": len(by_receiver),
        "atoms": sum(len(d["atoms"]) for d in disclosures),
        "unique_visible_spans": len({(d["disclosure_id"], a["parameter_path"], a["span_start"], a["span_end"])
                                     for d in disclosures for a in d["atoms"]}),
        "nodes": len(nodes), "edges": len(edges),
        "factor_status": dict(Counter(f["status"] for f in graph["joint_factors"]))}
    return graph


def validate_graph(graph, task):
    by_id = {n["id"]: n for n in graph["nodes"]}
    assert len(by_id) == len(graph["nodes"])
    assert all(e["source"] in by_id and e["target"] in by_id for e in graph["edges"])
    atoms = [n for n in graph["nodes"] if n["type"] == "disclosed_atom"]
    original_atoms = {a["atom_id"]: a for d in task["disclosures"] for a in d["atoms"]}
    assert {n["id"] for n in atoms} == set(original_atoms)
    assert all(n["annotation"] == original_atoms[n["id"]] for n in atoms)
    assert sorted(a for group in graph["display_groups"] for a in group["atom_ids"]) == sorted(original_atoms)
    for e in graph["edges"]:
        if e["kind"] == "received":
            assert by_id[e["source"]]["type"] == "actual_disclosure"
            assert by_id[e["target"]]["type"] == "business_receiver"
    for timeline in graph["timeline"]:
        before, after = by_id[timeline["before_memory"]], by_id[timeline["after_memory"]]
        assert after["step"] == before["step"] + 1
        assert set(before["cumulative_atom_ids"]) <= set(after["cumulative_atom_ids"])
        assert set(before["cumulative_disclosure_ids"]) < set(after["cumulative_disclosure_ids"])
    for factor in graph["joint_factors"]:
        assert all(by_id[a]["receiver_id"] == factor["receiver_id"] for aa in factor["support"].values() for a in aa)
        assert bool(factor["missing_slots"]) == (factor["status"] == "missing_evidence_not_activated")
        if factor["missing_slots"]:
            assert factor["first_evidence_complete_memory"] is None
        else:
            state = by_id[factor["first_evidence_complete_memory"]]
            assert {a for aa in factor["support"].values() for a in aa} <= set(state["cumulative_atom_ids"])
    assert graph["assessment"]["privacy_gain_bits"] is None
    assert graph["assessment"]["leakage_verdict"] == "not_evaluated"
    return {"passed": True, "task": task["task_key"], "statistics": graph["statistics"],
        "checks": ["original request equality", "all model annotations preserved verbatim", "all node/edge references valid",
                   "cumulative memory monotonic", "receiver isolation", "factor prerequisites explicit",
                   "display grouping preserves every atom", "no invented gain or recovery verdict"]}


def main():
    inputs = [SOURCE / "类别-信息图.json", SOURCE / "类别-信息图.zip", SOURCE / "披露信息.json"]
    graph_data, disclosure_data = [json.loads(p.read_text(encoding="utf-8")) for p in (inputs[0], inputs[2])]
    with zipfile.ZipFile(inputs[1]) as archive:
        if hashlib.sha256(archive.read("类别-信息图.json")).hexdigest() != sha(inputs[0]):
            raise ValueError("Graph JSON differs from ZIP source")
    tasks = [t for t in disclosure_data["tasks"] if t["execution_status"] == "已执行"]
    assert len(tasks) == 3
    originals = [ROOT / d["evidence"].split("#", 1)[0] for t in tasks for d in t["disclosures"]]
    inputs = list(dict.fromkeys(inputs + originals))
    before = {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in inputs}
    categories = {g["category_id"]: g for g in graph_data["graphs"]}
    metadata = {"input_sha256": before, "ontology": disclosure_data["ontology"],
                "method": "instantiation_from_existing_evidence_no_new_model_call",
                "new_api_calls": 0, "new_task_executions": 0}
    from .process_render import render
    entries, validations = [], []
    for task in tasks:
        graph = build_task_graph(task, categories, metadata)
        validation = validate_graph(graph, task)
        folder = OUTPUT / task["task_key"].replace("/", "_")
        path = folder / "隐私信息泄露过程图.json"
        dump(path, graph)
        render(path)
        validations.append(validation)
        entries.append({"task": task["task_key"], "title": graph["title"],
                        "json": str(path.relative_to(OUTPUT)).replace("\\", "/"),
                        "png": str(path.with_suffix(".png").relative_to(OUTPUT)).replace("\\", "/"),
                        "statistics": graph["statistics"]})
    after = {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in inputs}
    assert before == after
    dump(OUTPUT / "index.json", {"tasks": entries, "validation": validations,
        "inputs_unchanged": True, "input_sha256": after, "new_api_calls": 0, "new_task_executions": 0})
    with zipfile.ZipFile(OUTPUT / "三个任务-隐私信息泄露过程图.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(OUTPUT / "index.json", "index.json")
        for entry in entries:
            for key in ("json", "png"):
                archive.write(OUTPUT / entry[key], entry[key])
    print(json.dumps({"output": str(OUTPUT), "entries": entries, "inputs_unchanged": True}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
