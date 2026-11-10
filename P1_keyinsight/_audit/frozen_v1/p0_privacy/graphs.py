"""Construct and check category-specific undirected dependency/factor graphs."""
import itertools
import math

import networkx as nx

from .catalog import CATEGORIES, ONTOLOGY, PAPER


def make_graph(category_id, task_keys):
    spec = CATEGORIES[category_id]
    fields = set(spec["direct"].values()) | {entry[0] for entry in spec["joint"]}
    nodes = [{"id": "secret:" + f, "type": "sensitive_field_variable", "field": f,
              "label": ONTOLOGY[f], "domain": None, "prior": None,
              "value": None, "value_scope": "任务运行时绑定，不在类别模板中硬编码个人值"}
             for f in sorted(fields)]
    nodes += [{"id": "atom:" + a, "type": "message_atom_variable", "label": label,
               "domain": None, "binding": "披露信息.json 中的实际 span 和 parameter_path",
               "value": None} for a, label in spec["slots"].items()]
    factors = []
    for a, f in spec["direct"].items():
        factors.append({"id": "direct:" + a, "scope": ["secret:" + f, "atom:" + a],
                        "relation": "direct_encoding_candidate",
                        "description": "仅当实际披露片段确实编码该个人字段时实例化；同名槽位不证明有隐私",
                        "table": None, "calibration_status": "uncalibrated"})
    for i, (f, atoms, description) in enumerate(spec["joint"]):
        factors.append({"id": f"joint:{i}", "scope": ["secret:" + f] + ["atom:" + a for a in atoms],
                        "relation": "joint_inference_hypothesis", "description": description,
                        "table": None, "calibration_status": "uncalibrated"})
    # Each factor scope induces a clique in the primal dependency graph. Keeping
    # scopes avoids misrepresenting a joint hypothesis as independent pair costs.
    edge_factors = {}
    for factor in factors:
        for a, b in itertools.combinations(sorted(set(factor["scope"])), 2):
            edge_factors.setdefault((a, b), []).append(factor["id"])
    edges = [{"source": a, "target": b, "directed": False, "factor_ids": ids,
              "semantics": "同一依赖因子中的变量联系；不表示时间顺序、因果或已发生泄露"}
             for (a, b), ids in sorted(edge_factors.items())]
    g = nx.Graph()
    g.add_nodes_from(n["id"] for n in nodes)
    g.add_edges_from((e["source"], e["target"]) for e in edges)
    width, decomposition = nx.algorithms.approximation.treewidth_min_fill_in(g)
    if width > 7:
        raise ValueError(f"{category_id}: treewidth upper-bound certificate exceeds 7: {width}")
    bags = sorted(decomposition.nodes, key=lambda b: tuple(sorted(b)))
    bag_ids = {bag: f"bag:{i}" for i, bag in enumerate(bags)}
    return {
        "schema_version": "p0.ocelot.category_graph.v1", "category_id": category_id,
        "category_name": spec["name"], "task_keys": sorted(task_keys),
        "graph_type": "undirected_dependency_graph_with_factor_scopes",
        "graph_role": "类别级隐私依赖模板；不是 LangGraph 控制图，也不是任务执行事件图",
        "authoring": {"based_on": PAPER, "origin": "本实验按 AgentDojo 任务和工具语义编写的规则草案",
                      "official_ocelot_rubric": False, "validation": "structural_only",
                      "expert_reviewed": False, "held_out_calibration_completed": False},
        "task_signature": {"action_category": category_id, "native_tools": spec["tools"],
                           "resolution": "固定任务目录映射；运行时按实际工具及接收者再核对",
                           "receiver_classes": ["application_service", "business_target", "authorized_reader"]},
        "nodes": nodes, "edges": edges, "factors": factors,
        "necessity_rubric": {"rules": [{"id": f"{category_id}.necessity.{i+1}", "text": r}
                                        for i, r in enumerate(spec["rules"])],
                             "default": "接收者特定判断；工具参数必填不等于正文内每个敏感片段必要",
                             "admissible_levels": ["required", "helpful", "unnecessary", "unknown"]},
        "operators": ["identity", "generalize", "substitute", "redact", "drop"],
        "treewidth_check": {"method": "networkx.treewidth_min_fill_in", "upper_bound": width,
                            "exact_treewidth": None, "limit": 7, "passed": True,
                            "bags": [{"id": bag_ids[b], "nodes": sorted(b)} for b in bags],
                            "bag_edges": [{"source": bag_ids[a], "target": bag_ids[b]}
                                          for a, b in decomposition.edges]},
        "posterior_audit": {
            "status": "awaiting_calibration", "quantitative_ready": False,
            "gain_bits": None,
            "definition": "log2(max_s P(S=s | receiver_memory, background) / max_s P(S=s | background))",
            "needed": ["各变量的有限域", "接收者既有知识和先验", "依赖因子的概率或概率区间", "留出数据上的联合推断校准"],
            "domain_bound_k_le_16_verified": False,
            "interpretation": "节点和边提供推断结构，不足以单独计算可信数值；缺少概率时返回 null，不能以边数代替泄露量"},
        "notes": [spec["note"]] if spec["note"] else [],
    }


def min_entropy_gain(prior, posterior):
    """Calculation boundary for a calibrated, finite-domain audit supplied later.

    No posterior is inferred from an uncalibrated topology or an LLM confidence.
    The returned quantity is instance-specific and may be negative.
    """
    if not prior or set(prior) != set(posterior):
        raise ValueError("Prior and posterior must have the same nonempty finite domain")
    for distribution in (prior, posterior):
        if any(not math.isfinite(p) or not 0 <= p <= 1 for p in distribution.values()):
            raise ValueError("Invalid probability")
        if not math.isclose(sum(distribution.values()), 1, abs_tol=1e-8):
            raise ValueError("Probabilities must sum to one")
    return math.log2(max(posterior.values()) / max(prior.values()))
