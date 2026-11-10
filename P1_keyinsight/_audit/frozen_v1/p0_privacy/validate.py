"""Checks for evidence integrity, graph certificates, and absent-data semantics."""
import json
import re
from collections import Counter
from pathlib import Path

import networkx as nx

from .annotation import leaves, validate_response
from .catalog import CATEGORIES, categories_for


def validate_graph(graph):
    ids = {n["id"] for n in graph["nodes"]}
    assert len(ids) == len(graph["nodes"])
    edges = {tuple(sorted((e["source"], e["target"]))) for e in graph["edges"]}
    assert len(edges) == len(graph["edges"])
    assert all(a in ids and b in ids and a != b for a, b in edges)
    bags = {b["id"]: set(b["nodes"]) for b in graph["treewidth_check"]["bags"]}
    tree = nx.Graph()
    tree.add_nodes_from(bags)
    tree.add_edges_from((e["source"], e["target"]) for e in graph["treewidth_check"]["bag_edges"])
    assert nx.is_tree(tree)
    assert set.union(*bags.values()) == ids
    assert all(any({a, b} <= bag for bag in bags.values()) for a, b in edges)
    for node in ids:
        assert nx.is_connected(tree.subgraph([bid for bid, nodes in bags.items() if node in nodes]))
    assert max(len(bag) - 1 for bag in bags.values()) == graph["treewidth_check"]["upper_bound"] <= 7
    assert graph["posterior_audit"]["quantitative_ready"] is False
    assert graph["posterior_audit"]["gain_bits"] is None
    assert all(f["table"] is None and set(f["scope"]) <= ids for f in graph["factors"])
    for factor in graph["factors"]:
        scope = factor["scope"]
        assert all(tuple(sorted((a, b))) in edges for i, a in enumerate(scope) for b in scope[i+1:])


def validate_delivery(output):
    graph_bundle = json.loads((output / "类别-信息图.json").read_text(encoding="utf-8"))
    disclosures = json.loads((output / "披露信息.json").read_text(encoding="utf-8"))
    tasks = disclosures["tasks"]
    assert len(tasks) == len({t["task_key"] for t in tasks}) == 97
    assert len(graph_bundle["graphs"]) == len(CATEGORIES)
    for graph in graph_bundle["graphs"]:
        validate_graph(graph)
        assert graph["task_keys"] == sorted(t["task_key"] for t in tasks if graph["category_id"] in t["category_ids"])
    totals = Counter()
    for task in tasks:
        assert task["category_ids"] == categories_for(task["task_key"])
        if task["execution_status"] == "未执行":
            assert task["disclosures"] is None and task["model_annotation"] is None
            assert all(r["actual_disclosure_ids"] is None for r in task["receivers"])
            totals["unexecuted"] += 1
            continue
        totals["executed"] += 1
        assert task["annotation_status"] == "model_annotated"
        assert task["model_annotation"]["requested"] == task["model_annotation"]["returned"] == "deepseek-flash"
        observed = task["disclosures"]
        saved_path = output / "_audit" / task["task_key"].replace("/", "_") / "validated.json"
        saved = json.loads(saved_path.read_text(encoding="utf-8"))
        validate_response(saved["output"], observed)
        for disclosure in observed:
            totals["disclosures"] += 1
            if not disclosure["received_request_parameters"]:
                totals["empty_requests"] += 1
                assert disclosure["atoms"] == []
            values = dict(leaves(disclosure["received_request_parameters"]))
            for atom in disclosure["atoms"]:
                totals["atoms"] += 1
                assert values[atom["parameter_path"]][atom["span_start"]:atom["span_end"]] == atom["span"]
                assert atom["privacy_gain_bits"] is None
    assert totals["executed"] == 3 and totals["unexecuted"] == 94
    assert totals["disclosures"] == 6 and totals["empty_requests"] == 3
    for path in [output / "披露信息.json", output / "类别-信息图.json", *list((output / "_audit").rglob("*.json"))]:
        assert not re.search(r"sk-[A-Za-z0-9]{20,}", path.read_text(encoding="utf-8")), "Credential found in output"
    return {"passed": True, "counts": dict(totals), "graphs": len(CATEGORIES),
            "checks": ["97 native task mappings", "3 real / 94 unexecuted", "6 original received requests",
                       "3 empty requests have no atoms", "literal spans / offsets / provenance IDs",
                       "real DeepSeek requested and returned models", "valid tree decomposition certificates",
                       "no fabricated probability or leakage values", "no API credential in artifacts"]}
