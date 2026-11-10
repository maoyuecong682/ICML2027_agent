"""Build the two requested JSON deliveries from immutable receiver evidence.

Run with the P0 venv: python -B -m p0_privacy.build [--graphs-only]
Only the offline annotator calls DeepSeek; no benchmark task is rerun.
"""
import argparse
import copy
import csv
import hashlib
import json
import os
import sys
import zipfile
from collections import Counter
from pathlib import Path

from agentdojo.task_suite.load_suites import get_suites

from p0.records import dump, now
from .annotation import annotate_task, leaves
from .catalog import CATEGORIES, ONTOLOGY, PAPER, categories_for
from .graphs import make_graph
from .recipients import attach_resolved_receivers

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "outputs" / "ocelot_20261028"
CSV = ROOT / "outputs" / "receiver_memory_20261028" / "task_接收者_接收到的全部记忆.csv"
EXECUTED = {"workspace/user_task_14", "workspace/user_task_22", "workspace/user_task_31"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def immutable_inputs():
    return sorted([CSV, *list((ROOT / "p0").glob("*.py")),
                   *[p for p in (ROOT / "runs" / "p0_20261028_seed20261028").rglob("*") if p.is_file()]])


def read_tasks():
    suites = get_suites("v1.2")
    native = {f"{s}/{t.ID}": t.PROMPT for s, suite in suites.items() for t in suite.user_tasks.values()}
    tasks = {}
    with CSV.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            key, prompt = row["task"].split("\n", 1)
            memory = json.loads(row["接收到的全部记忆"])
            if native.get(key) != prompt:
                raise ValueError(f"CSV prompt differs from native benchmark: {key}")
            executed = memory["执行状态"] == "已执行"
            if executed != (key in EXECUTED):
                raise ValueError(f"Unexpected execution scope: {key}")
            task = tasks.setdefault(key, {"task_key": key, "prompt": prompt,
                "category_ids": categories_for(key), "primary_category_id": categories_for(key)[0],
                "execution_status": "已执行" if executed else "未执行",
                "annotation_status": "pending" if executed else "not_executed",
                "official_task_success": memory.get("官方任务成功"),
                "receivers": [], "disclosures": [] if executed else None,
                "model_annotation": None, "privacy_gain_bits": None,
                "privacy_leakage_verdict": "not_evaluated",
                "note": "真实接收请求的模型标注，不等于已证明隐私泄露" if executed else "任务未执行；无实际披露和标注，null 不等于没有泄露"})
            if executed:
                # CSV remains historical task metadata, not the source of actual
                # recipient identities. Resolve every TOOL directly after loading.
                continue
            rid, name = row["接收者"].split("\n", 1)
            history = memory["本任务实际接收记忆"]
            receiver = {"receiver_id": rid, "name": name, "memory_space_id": memory["记忆空间ID"],
                        "visibility": memory["可见性"], "receipt_rules": memory["接收内容规则"],
                        "actual_disclosure_ids": [] if executed else None,
                        "background_knowledge": {"status": "not_modeled", "facts": None}}
            receiver["recipient_resolution_status"] = "legacy_static_candidate_not_observed"
            task["receivers"].append(receiver)
            if history is not None:
                raise ValueError("Unexecuted memory must be null")
    if set(tasks) != set(native) or len(tasks) != 97:
        raise ValueError("Must cover all 97 benchmark tasks")
    for key, task in tasks.items():
        if key in EXECUTED:
            graph_path = ROOT / "runs" / "p0_20261028_seed20261028" / key.replace("/", "_") / "graph.json"
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            attach_resolved_receivers(task, graph, graph_path, suites[key.split("/", 1)[0]])
            if task["recipient_resolution"]["resolution_status"] != "resolved":
                raise ValueError(f"Incomplete recipient resolution: {key}")
        else:
            task["recipient_resolution"] = {"resolution_status": "not_executed", "events": None}
        if not task["category_ids"] or any(c not in CATEGORIES for c in task["category_ids"]):
            raise ValueError(f"Invalid task categories: {key}")
    return list(tasks.values())


def attach_annotation(task, saved, graphs):
    by_id = {d["disclosure_id"]: d for d in task["disclosures"]}
    for result in saved["output"]["disclosures"]:
        disclosure = by_id[result["disclosure_id"]]
        values = dict(leaves(disclosure["received_request_parameters"]))
        sources = {s["source_id"]: s for s in disclosure["source_candidates"]}
        atoms = []
        for i, item in enumerate(result["atoms"]):
            atom = copy.deepcopy(item)
            text = values[atom["parameter_path"]]
            start = text.index(atom["span"])
            atom.update(atom_id=f"{disclosure['disclosure_id']}::atom:{i}", span_start=start,
                        span_end=start + len(atom["span"]), offset_unit="Unicode code points",
                        assessment_status="model_annotation_unreviewed", privacy_gain_bits=None)
            atom["provenance_evidence"] = [{"source_id": sid, "evidence": sources[sid]["evidence"],
                "match": "exact_substring" if atom["span"] in sources[sid]["text"] else "model_attribution_unverified"}
                for sid in atom["source_ids"]]
            atom["graph_bindings"] = []
            for cid in task["category_ids"]:
                graph = graphs[cid]
                target = "secret:" + atom["field"]
                if target not in {n["id"] for n in graph["nodes"]}:
                    continue
                candidate_atoms = sorted({v for f in graph["factors"] if target in f["scope"]
                                          for v in f["scope"] if v.startswith("atom:")})
                direct_atoms = sorted({v for f in graph["factors"] if target in f["scope"]
                                       and f["relation"] == "direct_encoding_candidate"
                                       for v in f["scope"] if v.startswith("atom:")})
                binding = {"category_id": cid, "secret_node": target,
                           "candidate_atom_nodes": direct_atoms or candidate_atoms,
                           "method": "field_match_to_template_not_causal_proof"}
                atom["graph_bindings"].append(binding)
                graph.setdefault("observed_bindings", []).append({"task_key": task["task_key"],
                    "disclosure_id": disclosure["disclosure_id"], "atom_id": atom["atom_id"], **binding})
            atom["graph_binding_status"] = ("not_sensitive" if atom["field"] == "none" else
                "candidate_binding" if atom["graph_bindings"] else "field_not_in_category_template_review_required")
            atoms.append(atom)
        disclosure.update(atoms=atoms, parameter_reviews=result["parameter_reviews"], annotation_notes=result["notes"])
    task.update(annotation_status="model_annotated", model_annotation=saved["model"])


def write_graphs(output, graphs, tasks):
    folder = output / "类别信息图"
    index = []
    for cid, graph in graphs.items():
        filename = f"{cid}-{graph['category_name']}.json"
        path = folder / filename
        dump(path, graph)
        index.append({"category_id": cid, "category_name": graph["category_name"],
                      "file": f"类别信息图/{filename}", "sha256": sha(path),
                      "tasks": len(graph["task_keys"]), "nodes": len(graph["nodes"]), "edges": len(graph["edges"])})
    aggregate = {"schema_version": "p0.ocelot.graph_bundle.v1", "based_on": PAPER,
        "category_count": len(graphs), "task_count": len(tasks),
        "status": "实验类别规则草案；已做结构校验，尚未概率校准或专家验证",
        "task_category_mapping": {t["task_key"]: t["category_ids"] for t in tasks},
        "index": index, "graphs": list(graphs.values())}
    dump(output / "类别-信息图.json", aggregate)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--graphs-only", action="store_true")
    parser.add_argument("--task-graph-dir", type=Path, default=ROOT / "outputs/graphiti_privacy")
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    inputs = {str(p.relative_to(ROOT)): sha(p) for p in immutable_inputs()}
    tasks = read_tasks()
    graphs = {cid: make_graph(cid, [t["task_key"] for t in tasks if cid in t["category_ids"]]) for cid in CATEGORIES}
    for graph in graphs.values():
        graph["observed_bindings"] = []
    write_graphs(output, graphs, tasks)
    print(f"Category graphs: {len(graphs)}; tasks: {len(tasks)}; observed disclosures: "
          f"{sum(len(t['disclosures'] or []) for t in tasks)}", flush=True)
    if args.graphs_only:
        return
    for task in tasks:
        if task["execution_status"] != "已执行":
            continue
        print("ANNOTATE " + task["task_key"], flush=True)
        saved = annotate_task(task, [graphs[c] for c in task["category_ids"]],
                              os.environ.get("DEEPSEEK_API_KEY", ""), output / "_audit" / task["task_key"].replace("/", "_"))
        attach_annotation(task, saved, graphs)
        print("ANNOTATED " + task["task_key"] + f" ({sum(len(d['atoms']) for d in task['disclosures'])} atoms)", flush=True)
    write_graphs(output, graphs, tasks)
    stats = {"tasks": len(tasks), "categories": len(graphs),
             "executed_tasks": sum(t["execution_status"] == "已执行" for t in tasks),
             "unexecuted_tasks": sum(t["execution_status"] == "未执行" for t in tasks),
             "receivers": sum(len(t["receivers"]) for t in tasks),
             "disclosures": sum(len(t["disclosures"] or []) for t in tasks),
             "atoms": sum(len(d["atoms"] or []) for t in tasks for d in t["disclosures"] or []),
             "annotation_models": sorted({t["model_annotation"]["returned"] for t in tasks if t["model_annotation"]})}
    package = {"schema_version": "p0.ocelot.disclosures.v1", "created_at": now(), "based_on": PAPER,
        "implemented_scope": ["类别依赖图模板", "真实接收请求的离线模型分解标注", "确定性 JSON/原文/来源引用校验"],
        "execution_agents": {"count": 2, "names": ["A", "B"], "provider": "DeepSeek", "model": "deepseek-flash"},
        "offline_annotator": {"provider": "DeepSeek", "model": "deepseek-flash", "execution_agent": False,
                              "label_status": "model_suggested_not_expert_ground_truth", "applies_operators": False},
        "statistics": stats, "ontology": ONTOLOGY,
        "source": {"csv": str(CSV.relative_to(ROOT)), "csv_sha256": sha(CSV),
                   "observed_recipient_resolution": "p0_privacy.recipients: actual TOOL + AgentDojo dependencies",
                   "unexecuted_recipients": "legacy static candidates; not observed or automatically verified",
                   "run": "runs/p0_20261028_seed20261028", "new_tasks_executed": 0},
        "boundary": {"included": ["业务应用服务", "实际目标地址/网站/商户", "获授权的内容访问者"],
                     "excluded": ["agent A", "agent B", "用户本人", "DeepSeek 模型服务", "本地审计器"],
                     "receipt_semantics": "AgentDojo 本地模拟边界投影，不代表真实互联网投递",
                     "receiver_collusion": False, "background_knowledge": "not_modeled",
                     "memory": "保留接收历史；不因发送方删除、压缩、撤销而抹除历史"},
        "status_semantics": {"null": "未执行、未建模或尚无足够证据；不是零泄露",
                             "empty_atoms": "该实际请求没有标出的敏感片段；不是全任务安全证明",
                             "field": "可能涉及的受保护变量；是否不当泄露另行评价",
                             "kind": "direct 直接编码，indirect 隐含或推断；relation 保留更细区分",
                             "op": "模型建议，本轮未改写实际披露",
                             "privacy_gain_bits": "未校准，统一 null；不把模型置信度或图边数当泄露量"},
        "not_implemented": ["接收者后验/秘密恢复实验", "经校准的概率因子与数值风险审计",
                            "在线发送前拦截", "预算账本与签名", "OCELOT Defender 微调"],
        "tasks": tasks}
    dump(output / "披露信息.json", package)
    after = {str(p.relative_to(ROOT)): sha(p) for p in immutable_inputs()}
    if inputs != after:
        raise RuntimeError("Immutable input changed during build")
    dump(output / "_audit" / "input_integrity.json", {"unchanged": True, "sha256": inputs})
    from .validate import validate_delivery
    validation = validate_delivery(output)
    dump(output / "_audit" / "validation.json", validation)
    with zipfile.ZipFile(output / "类别-信息图.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(output / "类别-信息图.json", "类别-信息图.json")
        for path in sorted((output / "类别信息图").glob("*.json")):
            archive.write(path, "类别信息图/" + path.name)
    print(json.dumps({"statistics": stats, "validation": validation, "output": str(output)}, ensure_ascii=False), flush=True)
    # Full construction always includes the task-specific Graphiti stage.
    # --graphs-only remains an explicit category-template-only workflow.
    from .task_graph import main as build_task_graphs
    build_task_graphs(["--annotation-dir", str(output), "--output-dir", str(args.task_graph_dir)])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
