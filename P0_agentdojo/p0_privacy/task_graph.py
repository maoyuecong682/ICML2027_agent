"""Task privacy graph construction. Graphiti is mandatory; simplification is optional.

Actual requests -> recipient projections -> Graphiti -> evidence/attribute/AND
factor projection -> optional recipient pooling -> validated graph export.
"""
import argparse
import asyncio
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

from p0.records import dump, now
from .knowledge_merge import DEFAULT_RUN, ROOT, experiment_report, input_from_observed_graph, pointer_value
from .process_graph import build_task_graph, validate_graph

DEFAULT_OUTPUT = ROOT / "outputs/graphiti_privacy"
DEFAULT_ANNOTATIONS = ROOT / "outputs/ocelot_20261028"
DEFAULT_TASKS = ["workspace/user_task_14", "workspace/user_task_22", "workspace/user_task_31"]
SEMANTICS = {
    "same_observed_request": "Graphiti episode 与实际请求是同一份参数证据",
    "semantic_subject": "模型抽取关系的主语；未自动确认语义正确",
    "semantic_object": "模型抽取关系的宾语；未自动确认语义正确",
    "supports_semantic_claim": "片段逐字存在并被模型引用；存在证据不等于证明语义",
    "normalized_fact": "由完整参数或明确模板提取的事实；保留参数路径和原文",
    "and_premise": "AND 组合的必要前提，全部具备才可输出",
    "documented_association": "同一 Trip 行明确绑定的姓名、目的地、日期；不是已出行证明",
    "lexical_entity_alignment": "原文与 Graphiti 实体名称精确相同；仅词面绑定，不是身份认证",
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def semantic_evidence(edge, native, data):
    """Validate model-proposed evidence within the correct receiver's episode."""
    values = edge.get("attributes", {})
    quote, pointer = values.get("quote"), values.get("parameter_pointer")
    if not isinstance(quote, str) or not quote or not isinstance(pointer, str):
        return []
    receipts = {r["receipt_id"]: r for r in data["receipts"]}
    evidence = []
    for eid in edge["episodes"]:
        did = native["episode_receipt_map"].get(eid)
        if did not in receipts:
            continue
        receipt = receipts[did]
        if receipt["receiver_id"] != edge["receiver_id"]:
            continue
        try:
            text = pointer_value(receipt["parameters"], pointer)
        except (KeyError, ValueError, IndexError, TypeError):
            continue
        if isinstance(text, str) and quote in text:
            start = text.index(quote)
            evidence.append({"receipt_id": did, "parameter_pointer": pointer, "quote": quote,
                             "span_start": start, "span_end": start + len(quote)})
    return evidence


def project_graph(data, native, annotation_task, categories, metadata, merge_mode="off"):
    # The existing evidence graph is retained as the privacy-specific layer;
    # Graphiti supplies an additional persistent semantic graph, not just a label.
    graph = build_task_graph(annotation_task, categories, metadata)
    graph["schema_version"] = "p0.task_privacy_graph.graphiti.v1"
    graph["graph_role"] = "Graphiti实体/关系 + 接收证据 + 隐私属性 + 显式AND依赖的任务级隐私图"
    graph["construction_engine"] = copy.deepcopy(native["config"])
    graph["graphiti_native"] = copy.deepcopy(native)
    graph["simplification"] = {"applied": False, "input_stage": "complete_constructed_graph"}
    graph["recipient_knowledge_merge"] = experiment_report(data, merge_mode)
    graph["edge_semantics"].update(SEMANTICS)
    graph["quarantined_semantic_relations"] = []
    nodes, edges = graph["nodes"], graph["edges"]
    by_id = {n["id"]: n for n in nodes}

    def node(nid, kind, label, **values):
        if nid in by_id:
            raise ValueError("Duplicate graph node ID")
        value = {"id": nid, "type": kind, "label": label, **values}
        nodes.append(value)
        by_id[nid] = value
        return value

    def edge(source, target, kind, **values):
        edges.append({"id": "edge:" + str(len(edges)), "source": source, "target": target,
                      "kind": kind, "semantics": graph["edge_semantics"][kind], **values})

    receipts = {r["receipt_id"]: r for r in data["receipts"]}
    requests = {n["disclosure_id"]: n["id"] for n in nodes if n["type"] == "actual_disclosure"}
    if set(receipts) != set(requests):
        raise ValueError("Annotations and actual observed requests differ")
    for disclosure in annotation_task["disclosures"]:
        if disclosure["received_request_parameters"] != receipts[disclosure["disclosure_id"]]["parameters"]:
            raise ValueError("Annotated parameters differ from the observed trace")
        for atom in disclosure["atoms"]:
            text = str(pointer_value(receipts[disclosure["disclosure_id"]]["parameters"], atom["parameter_path"]))
            if text[atom["span_start"]:atom["span_end"]] != atom["span"]:
                raise ValueError("Existing privacy annotation no longer matches its source")
    for episode in native["episodes"]:
        did = native["episode_receipt_map"].get(episode["uuid"])
        if did not in receipts or episode["receiver_id"] != receipts[did]["receiver_id"]:
            raise ValueError("Graphiti episode crosses an evidence boundary")
        eid = "graphiti:episode:" + episode["uuid"]
        node(eid, "graphiti_episode", receipts[did]["tool"], receiver_id=episode["receiver_id"],
             graphiti_uuid=episode["uuid"], observed_at=episode["valid_at"])
        edge(eid, requests[did], "same_observed_request")
    for entity in native["nodes"]:
        node("graphiti:entity:" + entity["uuid"], "graphiti_entity", entity["name"],
             receiver_id=entity["receiver_id"], graphiti_uuid=entity["uuid"],
             group_id=entity["group_id"], model_summary=entity["summary"],
             assessment_status="model_extracted_unreviewed")
    accepted = []
    for relation in native["edges"]:
        source, target = ("graphiti:entity:" + relation[k] for k in ("source_node_uuid", "target_node_uuid"))
        proof = semantic_evidence(relation, native, data)
        if (not proof or source not in by_id or target not in by_id or
                any(by_id[n]["receiver_id"] != relation["receiver_id"] for n in (source, target))):
            graph["quarantined_semantic_relations"].append({"graphiti_uuid": relation["uuid"],
                                                          "reason": "invalid_quote_path_endpoint_or_receiver"})
            continue
        nid = "graphiti:claim:" + relation["uuid"]
        node(nid, "graphiti_relation_claim", relation["fact"], receiver_id=relation["receiver_id"],
             predicate=relation["attributes"].get("relation_label", relation["name"]),
             evidence=proof, valid_at=relation["valid_at"], invalid_at=relation["invalid_at"],
             status="quote_verified_semantics_unreviewed")
        edge(source, nid, "semantic_subject")
        edge(nid, target, "semantic_object")
        for support in proof:
            edge(requests[support["receipt_id"]], nid, "supports_semantic_claim", evidence=support)
        accepted.append(nid)
    for fact in data["facts"]:
        nid = "normalized:" + fact["fact_id"]
        node(nid, "normalized_received_fact", str(fact["claim"]["object"]),
             receiver_id=fact["receiver_id"], claim=copy.deepcopy(fact["claim"]),
             evidence=copy.deepcopy(fact["evidence"]), receipt_id=fact["receipt_id"],
             extraction_method=fact["extraction_method"],
             **({'tool': fact['tool']} if fact.get('tool') else {}),
             **({'observed_at': fact['observed_at']} if fact.get('observed_at') else {}))
        edge(requests[fact["receipt_id"]], nid, "normalized_fact")
        for entity in native["nodes"]:
            if entity["receiver_id"] == fact["receiver_id"] and entity["name"] == fact["claim"]["object"]:
                edge(nid, "graphiti:entity:" + entity["uuid"], "lexical_entity_alignment")
    # An explicit same-line association has a different status from a speculative
    # category hypothesis such as "the home is empty".
    trips = {}
    for fact in data["facts"]:
        if fact["extraction_method"] == "packing_list_template_v1" and fact["claim"]["predicate"].startswith("travel."):
            trips.setdefault((fact["receiver_id"], fact["claim"]["subject"]), {})[fact["claim"]["predicate"]] = fact
    for index, ((rid, _), slots) in enumerate(trips.items()):
        required = ("travel.traveler", "travel.destination", "travel.period")
        if not all(k in slots for k in required):
            continue
        fid, cid = f"association:{index}", f"association_fact:{index}"
        values = {k: slots[k]["claim"]["object"] for k in required}
        node(fid, "explicit_and_factor", "姓名 ∧ 目的地 ∧ 日期（同一 Trip 行）", receiver_id=rid,
             operator="AND", status="all_explicit_premises_available", required_predicates=list(required))
        node(cid, "composite_privacy_fact", "文档明示的个人旅行计划", receiver_id=rid, values=values,
             status="explicit_document_association_not_actual_trip_proof", privacy_gain_bits=None)
        for key in required:
            edge("normalized:" + slots[key]["fact_id"], fid, "and_premise", slot=key)
        edge(fid, cid, "documented_association")
    graph["statistics"].update(nodes=len(nodes), edges=len(edges), graphiti_episodes=len(native["episodes"]),
                               graphiti_entities=len(native["nodes"]), graphiti_relations=len(native["edges"]),
                               quote_verified_graphiti_relations=len(accepted),
                               quarantined_graphiti_relations=len(graph["quarantined_semantic_relations"]),
                               node_types=dict(Counter(n["type"] for n in nodes)))
    graph["validation"] = validate_task_graph(graph, annotation_task)
    return graph


def validate_task_graph(graph, task):
    previous = validate_graph(graph, task)
    nodes = {n["id"]: n for n in graph["nodes"]}
    if len(nodes) != len(graph["nodes"]):
        raise ValueError("Duplicate privacy graph nodes")
    for relation in graph["edges"]:
        a, b = nodes[relation["source"]], nodes[relation["target"]]
        if a.get("receiver_id") and b.get("receiver_id") and a["receiver_id"] != b["receiver_id"]:
            raise ValueError("Cross-receiver edge without explicit pooling")
    for factor in (n for n in nodes.values() if n["type"] == "explicit_and_factor"):
        supports = [e["slot"] for e in graph["edges"] if e["kind"] == "and_premise" and e["target"] == factor["id"]]
        if sorted(supports) != sorted(factor["required_predicates"]):
            raise ValueError("An AND factor lacks a required premise")
    if graph["simplification"]["applied"]:
        raise ValueError("Construction must preserve the graph before simplification")
    return {**previous, "checks": previous["checks"] + ["Graphiti persistent episode readback",
            "semantic quotes and parameter pointers", "task and receiver isolation", "explicit AND composition",
            "full graph before simplification"]}


def graph_mermaid(graph):
    """Readable projection of actual nodes; full graph remains in the JSON."""
    selected = [n for n in graph["nodes"] if n["type"] in {
        "business_receiver", "actual_disclosure", "disclosed_atom", "sensitive_field",
        "category_inference_factor", "explicit_and_factor", "composite_privacy_fact"}]
    # The composition's normalized premises are necessary to display its AND.
    normalized = {e["source"] for e in graph["edges"] if e["kind"] == "and_premise"}
    selected.extend(n for n in graph["nodes"] if n["id"] in normalized)
    ids = {n["id"]: "n" + str(i) for i, n in enumerate(selected)}
    lines = ["flowchart LR"]
    for n in selected:
        label = str(n["label"]).replace('"', "'").replace("\n", " ").replace("<", "&lt;").replace(">", "&gt;")
        if n["type"] == "actual_disclosure" and n["empty_parameters"]:
            label += "（空参数）"
        if n["type"] == "category_inference_factor":
            label += " · " + ("缺少前提" if n["missing_slots"] else "待验证假设")
        lines.append(f'  {ids[n["id"]]}["{label}"]')
    allowed = {"received", "contains_atom", "direct_label", "indirect_label", "factor_support",
               "factor_output", "and_premise", "documented_association"}
    for e in graph["edges"]:
        if e["kind"] not in allowed or e["source"] not in ids or e["target"] not in ids:
            continue
        dotted = e["kind"] in {"indirect_label", "factor_support", "factor_output"}
        lines.append(f'  {ids[e["source"]]} {"-.->" if dotted else "-->"}|{e["kind"]}| {ids[e["target"]]}')
    return "\n".join(lines)


def graph_terminal(graph):
    """Draw a readable symbol graph from the actual exported node/edge data."""
    nodes = {n["id"]: n for n in graph["nodes"]}
    ontology = graph["sources"]["ontology"]
    stats = graph["statistics"]
    lines = [f"┌─ {graph['task']['task_key']} ─ {stats['nodes']} 节点 / {stats['edges']} 边",
             "│  实线：已记录内容； -?->：待验证假设；AND：全部前提必须具备"]
    for receiver in (n for n in nodes.values() if n["type"] == "business_receiver"):
        rid = receiver["receiver_id"]
        lines.append("├─ [接收者] " + receiver["label"])
        for request in (n for n in nodes.values() if n["type"] == "actual_disclosure" and n["receiver_id"] == rid):
            lines.append(f"│  ├─ [{request['event_id']} {request['label']}] ──接收──> [该接收者]")
            if request["empty_parameters"]:
                lines.append("│  │  └─ {} （空参数；不虚构披露字段）")
            else:
                for atom in (n for n in nodes.values() if n["type"] == "disclosed_atom"
                             and n["disclosure_id"] == request["disclosure_id"]):
                    annotation = atom["annotation"]
                    value = atom["label"].replace("\n", "\\n")
                    field = annotation["field"]
                    target = ontology.get(field, "普通内容（未标敏感）" if field == "none" else field)
                    arrow = "──>" if annotation["kind"] == "direct" else "-?->"
                    lines.append(f"│  │  ├─ [{value}] {arrow} [{target}]")
    lines.append("├─ [Graphiti 实体关系；原文引用已校验，语义仍可复核]")
    native = graph["graphiti_native"]
    names = {n["uuid"]: n["name"] for n in native["nodes"]}
    accepted = {n["id"] for n in nodes.values() if n["type"] == "graphiti_relation_claim"}
    relations = [r for r in native["edges"] if "graphiti:claim:" + r["uuid"] in accepted]
    if not relations:
        for name in names.values():
            lines.append("│  └─ [" + name + "] （主题实体；未补造实体间关系）")
    else:
        for relation in relations:
            lines.append(f"│  ├─ [{names[relation['source_node_uuid']]}] "
                         f"─{relation['attributes']['relation_label']}─> [{names[relation['target_node_uuid']]}]")
    lines.append("├─ [隐私关联与推断依赖]")
    for factor in (n for n in nodes.values() if n["type"] == "explicit_and_factor"):
        premises = [nodes[e["source"]]["label"] for e in graph["edges"]
                    if e["kind"] == "and_premise" and e["target"] == factor["id"]]
        lines.append("│  ├─ [" + "] ∧ [".join(premises) + "]")
        lines.append("│  │       └─AND──> [文档明示的个人旅行计划；不是实际出行证明]")
    slots = {"query": "查询词", "sender": "发件人", "service": "服务名", "email": "邮箱/个人标识",
             "traveler_name": "姓名", "destination": "目的地", "dates": "日期", "packing_items": "行李物品"}
    for factor in graph["joint_factors"]:
        labels = [slots.get(s.split(":", 1)[-1], s) + ("×缺失" if s in factor["missing_slots"] else "✓")
                  for s in factor["required_slots"]]
        status = "未激活" if factor["missing_slots"] else "待验证，不当作已恢复隐私"
        lines.append("│  ├─ AND(" + " ∧ ".join(labels) + ") -?-> [" +
                     nodes[factor["output_node"]]["label"] + "：" + status + "]")
    modes = graph["recipient_knowledge_merge"]["outputs"]
    status = modes["on"]["status"] if "on" in modes else "disabled"
    lines.extend(["└─ 接收者合并：" + status + "；图简化：未执行", ""])
    return "\n".join(lines)


def write_terminal_views(graphs, output_dir):
    md = ["# Graphiti 任务隐私图", "", "以下为终端符号展示投影；完整节点、语义关系与证据见同目录 JSON。此展示不执行图简化。", ""]
    for key, graph in graphs.items():
        drawing = graph_terminal(graph)
        md.extend(["## " + key, "", "```text", drawing, "```", ""])
        print(drawing, flush=True)
    (Path(output_dir) / "任务隐私图.md").write_text("\n".join(md), encoding="utf-8")


async def construct(args):
    from .graphiti_backend import GraphitiConfig, GraphitiStore

    annotation_path = args.annotation_dir / "披露信息.json"
    categories_path = args.annotation_dir / "类别-信息图.json"
    annotations = json.loads(annotation_path.read_text(encoding="utf-8"))
    category_data = json.loads(categories_path.read_text(encoding="utf-8"))
    tasks = {t["task_key"]: t for t in annotations["tasks"]}
    categories = {c["category_id"]: c for c in category_data["graphs"]}
    source_paths = [annotation_path, categories_path]
    datasets = []
    for key in args.tasks:
        if key not in tasks or tasks[key]["execution_status"] != "已执行":
            raise ValueError("Task needs an actual trace and evidence annotations: " + key)
        path = args.run_dir / key.replace("/", "_") / "graph.json"
        datasets.append(input_from_observed_graph(path))
        source_paths.append(path)
    before = {str(p.resolve()): sha(p) for p in source_paths}
    metadata = {"input_sha256": before, "ontology": annotations["ontology"],
                "method": "Graphiti.add_episode plus evidence-validated privacy projection"}
    store = GraphitiStore(GraphitiConfig.from_env(), args.output_dir)
    graphs = {}
    try:
        await store.initialize()
        for data in datasets:
            native = await store.ingest(data)
            key = data["task_key"]
            graphs[key] = project_graph(data, native, tasks[key], categories, metadata, args.receiver_merge)
            graphs[key]["privacy_projection_storage"] = await store.persist_projection(graphs[key])
            print("PRIVACY_GRAPH " + key + " " + str(graphs[key]["statistics"]), flush=True)
        if before != {str(p.resolve()): sha(p) for p in source_paths}:
            raise ValueError("An immutable graph input changed")
        bundle = {"schema_version": "p0.task_privacy_graph.graphiti.bundle.v1", "created_at": now(),
                  "architecture": {"construction": "Graphiti (mandatory)", "privacy_projection": "evidence + fields + AND factors",
                                   "receiver_merge": args.receiver_merge, "simplification": "not_applied"},
                  "engine": store.config.public(), "input_integrity": {"unchanged": True, "sha256": before},
                  "run": {"new_model_calls": store.llm.calls, "model_cache_hits": store.llm.cache_hits,
                          "new_task_executions": 0, "task_count": len(graphs)}, "graphs": graphs}
        path = args.output_dir / "任务隐私图.json"
        dump(path, bundle)
        write_terminal_views(graphs, args.output_dir)
        if getattr(args, 'simplify', False):
            from .simplification import config_from_args, export_bundle
            export_bundle(bundle, config_from_args(args), args.output_dir)
        print(json.dumps({"output": str(path), "tasks": list(graphs), "run": bundle["run"]}, ensure_ascii=False), flush=True)
        return bundle
    finally:
        await store.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", nargs="+", default=DEFAULT_TASKS)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--annotation-dir", type=Path, default=DEFAULT_ANNOTATIONS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--receiver-merge", choices=("off", "on", "both"), default="off")
    from .simplification import add_arguments
    add_arguments(parser)
    args = parser.parse_args(argv)
    load_dotenv(args.env_file or ROOT / ".env", override=False)
    return asyncio.run(construct(args))


if __name__ == "__main__":
    main()
