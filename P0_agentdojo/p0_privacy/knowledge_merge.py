"""Optional, evidence-preserving knowledge pooling between task recipients.

The default is OFF. Local reasoning is identical in both arms; only the ON arm
computes a coalition closure. This is an offline simulation, not data delivery.
"""
import argparse
import copy
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECORD = ROOT / "outputs/recipient_resolution_20261102/workspace_user_task_31.json"
DEFAULT_OUTPUT = ROOT / "outputs/task31_接收者知识合并.json"
DEFAULT_RUN = ROOT / "runs/p0_20261028_seed20261028"
SCHEMA = "p0.receiver_knowledge_merge.v1"
LIMITS = {"iterations": 50, "facts": 1000, "supports": 128, "proofs": 128}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode("utf-8")).hexdigest()


def fact_id(claim):
    return "fact:" + digest(claim)[:24]


def aliases(entries):
    result = {}
    for entry in entries:
        if not entry.get("justification") or entry["alias"] in result:
            raise ValueError("Equivalences require a justification and unique aliases")
        result[entry["alias"]] = entry["canonical"]
    for start in result:
        seen, current = set(), start
        while current in result:
            if current in seen:
                raise ValueError("Cyclic equivalence")
            seen.add(current)
            current = result[current]
        result[start] = current
    return result


def claim_value(claim, entity_map, predicate_map):
    if set(claim) - {"subject", "predicate", "object", "context"}:
        raise ValueError("Unsupported claim field; place temporal/conditional scope in context")
    subject, predicate = claim["subject"], claim["predicate"]
    if not isinstance(subject, str) or not isinstance(predicate, str):
        raise ValueError("Subject and predicate must be identifiers")
    obj = copy.deepcopy(claim["object"])
    if isinstance(obj, dict) and set(obj) == {"entity_id"}:
        obj["entity_id"] = entity_map.get(obj["entity_id"], obj["entity_id"])
    return {"subject": entity_map.get(subject, subject),
            "predicate": predicate_map.get(predicate, predicate), "object": obj,
            "context": copy.deepcopy(claim.get("context", {}))}


def pointer_value(value, pointer):
    if not pointer:
        return value
    if not pointer.startswith("/"):
        raise ValueError("Evidence pointer must be a JSON Pointer")
    for part in pointer[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def variables(value):
    if isinstance(value, str) and value.startswith("?"):
        return {value}
    if isinstance(value, dict):
        return set().union(*(variables(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(variables(v) for v in value))
    return set()


def unify(pattern, value, bindings):
    if isinstance(pattern, str) and pattern.startswith("?"):
        if pattern in bindings:
            return bindings if encoded(bindings[pattern]) == encoded(value) else None
        return {**bindings, pattern: value}
    if isinstance(pattern, dict):
        if not isinstance(value, dict) or set(pattern) != set(value):
            return None
        for key in pattern:
            bindings = unify(pattern[key], value[key], bindings)
            if bindings is None:
                return None
        return bindings
    if isinstance(pattern, list):
        if not isinstance(value, list) or len(pattern) != len(value):
            return None
        for a, b in zip(pattern, value):
            bindings = unify(a, b, bindings)
            if bindings is None:
                return None
        return bindings
    return bindings if encoded(pattern) == encoded(value) else None


def substitute(value, bindings):
    if isinstance(value, str) and value.startswith("?"):
        return copy.deepcopy(bindings[value])
    if isinstance(value, dict):
        return {k: substitute(v, bindings) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, bindings) for v in value]
    return value


def minimal_supports(supports):
    ordered = sorted(set(supports), key=lambda s: (len(s), sorted(s)))
    result = []
    for support in ordered:
        if not any(old <= support for old in result):
            result.append(support)
    if len(result) > LIMITS["supports"]:
        raise ValueError("Support limit exceeded; analysis was not completed")
    return result


def prepare(data):
    """Validate evidence and normalize without granting knowledge to recipients."""
    entities = aliases(data.get("entity_equivalences", []))
    predicates = aliases(data.get("predicate_equivalences", []))
    receivers = {r["receiver_id"]: r for r in data["receivers"]}
    if len(receivers) != len(data["receivers"]):
        raise ValueError("Duplicate receiver ID")
    receipts = {r["receipt_id"]: r for r in data["receipts"]}
    if len(receipts) != len(data["receipts"]):
        raise ValueError("Duplicate receipt ID")
    for receipt in receipts.values():
        if receipt["receiver_id"] not in receivers or receipt["status"] != "received":
            raise ValueError("Only confirmed received views may enter this module")
        if receipt.get("trace_kind") != data["trace_kind"]:
            raise ValueError("Observed and reference traces cannot be mixed")
    facts, seen = {}, set()
    for atom in data["facts"]:
        if atom["fact_id"] in seen:
            raise ValueError("Duplicate source fact ID")
        seen.add(atom["fact_id"])
        receipt = receipts[atom["receipt_id"]]
        if atom["receiver_id"] != receipt["receiver_id"]:
            raise ValueError("Fact receiver differs from its evidence receiver")
        evidence = atom["evidence"]
        source = pointer_value(receipt["parameters"], evidence["parameter_pointer"])
        if "span" in evidence:
            start, end = evidence["span"]
            if not isinstance(source, str) or not 0 <= start < end <= len(source):
                raise ValueError("Invalid source span")
            source = source[start:end]
        if encoded(source) != encoded(evidence["quoted_value"]):
            raise ValueError("Evidence does not match the received parameters")
        claim = claim_value(atom["claim"], entities, predicates)
        if variables(claim):
            raise ValueError("Facts must be ground; variable syntax is reserved for rules")
        fid = fact_id(claim)
        node = facts.setdefault(fid, {"claim": claim, "occurrences": [], "proofs": [], "supports": []})
        node["occurrences"].append(copy.deepcopy(atom))
        node["supports"] = minimal_supports(node["supports"] + [frozenset([atom["receiver_id"]])])
    rules, rule_ids = [], set()
    for rule in data.get("rules", []):
        if rule["rule_id"] in rule_ids or not rule.get("justification") or not rule["premises"]:
            raise ValueError("Rules require unique IDs, nonempty AND premises and a justification")
        rule_ids.add(rule["rule_id"])
        premises = [claim_value(p, entities, predicates) for p in rule["premises"]]
        conclusion = claim_value(rule["conclusion"], entities, predicates)
        bound = set().union(*(variables(p) for p in premises))
        if not variables(conclusion) <= bound:
            raise ValueError("Conclusion variables must be bound in rule premises")
        rules.append({**rule, "premises": premises, "conclusion": conclusion})
    return receivers, facts, rules, {predicates.get(p, p) for p in data.get("single_valued_predicates", [])}


def closure(initial, rules):
    """Positive AND rules; retain alternative values and minimal receiver sets."""
    facts = copy.deepcopy(initial)
    for _ in range(LIMITS["iterations"]):
        changed = False
        for rule in rules:
            rows = [({}, [])]
            snapshot = list(facts.items())
            for pattern in rule["premises"]:
                next_rows = []
                for bindings, premises in rows:
                    for fid, node in snapshot:
                        result = unify(pattern, node["claim"], bindings)
                        if result is not None:
                            next_rows.append((result, premises + [fid]))
                            if len(next_rows) > 10000:
                                raise ValueError("Rule join limit exceeded; analysis was not completed")
                rows = next_rows
            for bindings, premises in rows:
                claim = substitute(rule["conclusion"], bindings)
                fid = fact_id(claim)
                if fid not in facts:
                    if len(facts) >= LIMITS["facts"]:
                        raise ValueError("Fact limit exceeded; analysis was not completed")
                    facts[fid] = {"claim": claim, "occurrences": [], "proofs": [], "supports": []}
                    changed = True
                node = facts[fid]
                proof = {"rule_id": rule["rule_id"], "premise_fact_ids": premises, "operator": "AND"}
                if proof not in node["proofs"]:
                    if len(node["proofs"]) >= LIMITS["proofs"]:
                        raise ValueError("Proof limit exceeded; analysis was not completed")
                    node["proofs"].append(proof)
                    changed = True
                combined = [frozenset()]
                for premise in premises:
                    combined = minimal_supports([a | b for a in combined for b in facts[premise]["supports"]])
                supports = minimal_supports(node["supports"] + combined)
                if supports != node["supports"]:
                    node["supports"] = supports
                    changed = True
        if not changed:
            return facts
    raise ValueError("Reasoning limit exceeded; analysis was not completed")


def conflict_analysis(facts, single_valued):
    buckets = {}
    for fid, node in facts.items():
        claim = node["claim"]
        if claim["predicate"] in single_valued:
            key = encoded({k: claim[k] for k in ("subject", "predicate", "context")})
            buckets.setdefault(key, []).append(fid)
    conflicts, taint = [], {fid: set() for fid in facts}
    for key, alternatives in sorted(buckets.items()):
        if len(alternatives) < 2:
            continue
        cid = "conflict:" + digest(key)[:24]
        conflicts.append({"conflict_id": cid, "scope": json.loads(key),
                          "alternative_fact_ids": sorted(alternatives), "resolution": "retain_all_unresolved"})
        for fid in alternatives:
            taint[fid].add(cid)
    changed = True
    while changed:
        changed = False
        for fid, node in facts.items():
            inherited = set().union(*(taint[p] for proof in node["proofs"] for p in proof["premise_fact_ids"]))
            if not inherited <= taint[fid]:
                taint[fid].update(inherited)
                changed = True
    return conflicts, taint


def export_facts(facts, single_valued):
    conflicts, taint = conflict_analysis(facts, single_valued)
    nodes = []
    for fid, node in sorted(facts.items()):
        nodes.append({"fact_id": fid, "claim": node["claim"], "occurrences": node["occurrences"],
                      "proofs": node["proofs"], "minimal_receiver_sets": [sorted(s) for s in node["supports"]],
                      "conflict_ids": sorted(taint[fid]),
                      "epistemic_status": "conflict_related" if taint[fid] else
                      "received_assertion" if node["occurrences"] else "conditional_on_declared_rules"})
    return nodes, conflicts


def merge_knowledge(data, *, enabled=False):
    """Pure API. OFF and single-receiver ON preserve the same local baseline."""
    receivers, initial, rules, single_valued = prepare(data)
    local, baseline = {}, {}
    for rid in sorted(receivers):
        own = {}
        for fid, node in initial.items():
            occurrences = [a for a in node["occurrences"] if a["receiver_id"] == rid]
            if occurrences:
                own[fid] = {"claim": copy.deepcopy(node["claim"]), "occurrences": occurrences,
                            "proofs": [], "supports": [frozenset([rid])]}
        view = closure(own, rules)
        nodes, conflicts = export_facts(view, single_valued)
        local[rid] = {"received_fact_ids": sorted(own), "inferred_fact_ids": sorted(set(view) - set(own)),
                      "knowledge": nodes, "conflicts": conflicts}
        baseline[rid] = view
    complete = bool(receivers) and all(r.get("view_complete") is True for r in receivers.values())
    status = ("disabled" if not enabled else "insufficient_information" if not complete else
              "skipped_single_receiver" if len(receivers) == 1 else "merged")
    output = {"schema_version": SCHEMA, "task_key": data["task_key"], "enabled": enabled,
              "input_sha256": digest(data), "status": status, "receiver_count": len(receivers),
              "analysis_scope": "supplied_received_views_and_declared_rules_only; no_unknown_background_knowledge",
              "receiver_knowledge": local, "coalition_knowledge": None, "alignments": [],
              "joint_inferences": [], "new_joint_inferences": [],
              "unresolved_items": copy.deepcopy(data.get("unresolved_items", [])),
              "privacy_leakage_verdict": "not_evaluated"}
    if not complete:
        output["unresolved_items"].append({"reason": "one_or_more_received_views_are_missing_or_incomplete"})
        if enabled:
            output["new_joint_inferences"] = None
    if status != "merged":
        return output
    coalition = closure(initial, rules)
    nodes, conflicts = export_facts(coalition, single_valued)
    local_union = set().union(*(set(v) for v in baseline.values()))
    new = set(coalition) - local_union
    inferred = set(coalition) - set(initial)
    output["coalition_knowledge"] = {"simulation_only": True, "members": sorted(receivers),
                                      "knowledge": nodes, "conflicts": conflicts}
    output["alignments"] = [{"canonical_fact_id": fid,
        "source_fact_ids": [a["fact_id"] for a in node["occurrences"]],
        "receivers": sorted({a["receiver_id"] for a in node["occurrences"]}),
        "method": "exact_claim_or_explicitly_justified_equivalence"}
        for fid, node in sorted(initial.items()) if len(node["occurrences"]) > 1]
    output["joint_inferences"] = sorted(inferred)
    output["new_joint_inferences"] = sorted(new)
    return output


def compare_knowledge(off, on):
    """Separate knowledge received from a peer from genuinely joint inference.

    Gains describe hypothetical access to the coalition view. They never update
    actual receiver memory and are not automatically classified as sensitive.
    """
    if (off["enabled"] or not on["enabled"] or off["input_sha256"] != on["input_sha256"]
            or off["receiver_knowledge"] != on["receiver_knowledge"]):
        raise ValueError("Comparison requires the same input and the same local reasoning baseline")
    local = {rid: {n["fact_id"] for n in view["knowledge"]}
             for rid, view in off["receiver_knowledge"].items()}
    available = set().union(*local.values())
    unknown = on["status"] == "insufficient_information"
    pool = {} if on["coalition_knowledge"] is None else {
        n["fact_id"]: n for n in on["coalition_knowledge"]["knowledge"]}
    new_joint = None if unknown else [pool[fid] for fid in on["new_joint_inferences"]]
    gains = {}
    for rid, own in local.items():
        new = set(pool) - own
        gains[rid] = {
            "existing_knowledge_from_peers": None if unknown else [pool[fid] for fid in sorted(new & available)],
            "new_jointly_inferred_knowledge": None if unknown else [pool[fid] for fid in sorted(new - available)],
            "new_to_receiver_count": None if unknown else len(new)}
    summary = {
        "skipped_single_receiver": "只有一个业务接收者，按约定跳过合并；相较关闭组，没有因跨接收者合并新增的知识。",
        "insufficient_information": "接收内容投影不完整，无法判断合并新增了什么知识，不能解释为零增益。",
        "merged": "已分别比较从其他接收者获得的既有知识、以及只有合并才能推断的新知识；敏感性尚未自动判定。",
    }[on["status"]]
    return {"status": on["status"], "summary_zh": summary,
            "same_input_and_local_baseline_verified": True,
            "access_semantics": "hypothetical_pool_access; no_actual_delivery",
            "new_joint_knowledge_count": None if unknown else len(new_joint),
            "new_joint_knowledge": new_joint, "per_receiver_gains": gains,
            "privacy_classification": "not_evaluated"}


def leaves(value, path=""):
    if isinstance(value, dict):
        for key, child in value.items():
            pointer = str(key).replace("~", "~0").replace("/", "~1")
            yield from leaves(child, path + "/" + pointer)
    elif isinstance(value, list):
        for i, child in enumerate(value):
            yield from leaves(child, path + "/" + str(i))
    else:
        yield path, value


def extract_receipt_facts(receipt, task_key):
    """Lossless scalar fields plus a bounded packing-list template extractor.

    Free text is retained whole, not assumed fully understood. Trip entities are
    receipt-scoped: similar names alone never establish cross-receipt identity.
    """
    result, notes = [], []
    rid, did = receipt["receiver_id"], receipt["receipt_id"]
    context = {"task_key": task_key}

    def add(label, subject, predicate, value, pointer, span=None, method="exact_parameter"):
        source = pointer_value(receipt["parameters"], pointer)
        evidence = {"parameter_pointer": pointer, "quoted_value": source if span is None else source[slice(*span)]}
        if span is not None:
            evidence["span"] = list(span)
        result.append({"fact_id": did + "::" + label, "receiver_id": rid, "receipt_id": did,
                       "claim": {"subject": subject, "predicate": predicate, "object": value, "context": context},
                       "extraction_method": method, "evidence": evidence,
                       **({'tool': receipt['tool']} if receipt.get('tool') else {}),
                       **({'observed_at': receipt['time']} if receipt.get('time') else {})})

    for pointer, value in leaves(receipt["parameters"]):
        add(pointer, "request:" + did, "request.parameter:" + pointer, value, pointer)
    text = receipt["parameters"].get("content")
    if isinstance(text, str):
        match = re.search(r"^Trip: (?P<destination>[^,\n]+), (?P<period>[^\n]+?) \((?P<traveler>[^()\n]+)\)$", text, re.M)
        if match:
            for group in ("destination", "period", "traveler"):
                add(group, "trip:" + did, "travel." + group, match[group], "/content", match.span(group),
                    "packing_list_template_v1")
            # Only parse bullets in the explicit Packing List section.
            heading = re.search(r"^Packing List[^\n]*:\s*\n", text, re.M)
            if heading:
                for i, item in enumerate(re.finditer(r"^  - (?P<item>[^\n]+)$", text[heading.end():], re.M)):
                    span = tuple(n + heading.end() for n in item.span("item"))
                    add("item:" + str(i), "trip:" + did, "packing.item", item["item"], "/content", span,
                        "packing_list_template_v1")
        notes.append({"receipt_id": did, "reason": "free_text_semantics_not_exhaustively_extracted",
                      "raw_content_retained": True})
    return result, notes


def input_from_observed_record(path):
    """Bridge actual recipient projections; exclude returned/source-candidate text."""
    path = Path(path)
    raw = path.read_bytes()
    return input_from_record(json.loads(raw), {"record": str(path.resolve()),
                                             "record_sha256": hashlib.sha256(raw).hexdigest()})


def input_from_observed_graph(path):
    """Resolve a real trace in memory, without creating intermediary JSON files."""
    from . import recipients

    path = Path(path).resolve()
    graph = json.loads(path.read_text(encoding="utf-8"))
    task_key = graph["task"]["suite"] + "/" + graph["task"]["task_id"]
    record = recipients.attach_resolved_receivers({"task_key": task_key, "prompt": graph["task"]["prompt"]},
                                                 graph, path)
    resolver_path = Path(recipients.__file__).resolve()
    return input_from_record(record, {
        "projection": "recipient_views_resolved_in_memory_from_observed_graph",
        "resolver_path": str(resolver_path), "resolver_sha256": hashlib.sha256(resolver_path.read_bytes()).hexdigest()})


def input_from_record(record, source):
    """Shared validation for persisted and in-memory recipient projections."""
    resolution = record["recipient_resolution"]
    if resolution.get("input_semantics") != "actual_TOOL_events_and_registered_AgentDojo_Function_dependencies":
        raise ValueError("This adapter requires an observed run, not a reference workflow or recipient catalogue")
    receivers = [{"receiver_id": r["receiver_id"], "name": r["name"],
                  "view_complete": resolution["resolution_status"] == "resolved",
                  "background_knowledge": "not_modeled"} for r in record["receivers"]]
    data = {"schema_version": SCHEMA + ".input", "task_key": record["task_key"], "task_text": record["prompt"],
            "trace_kind": "observed", "knowledge_scope": "received_request_parameters_in_this_task_only",
            "task_text_is_receiver_knowledge": False, "receivers": receivers, "receipts": [], "facts": [],
            "entity_equivalences": [], "predicate_equivalences": [], "rules": [],
            "single_valued_predicates": ["travel.destination", "travel.period", "travel.traveler"],
            "unresolved_items": [], "source": {**copy.deepcopy(source), "graphs": []}}
    expected = {(e["event_id"], r["receiver_id"], encoded(r["received_request_parameters"]))
                for e in resolution["events"] for r in e["receipts"]}
    actual = [(d["event_id"], d["receiver_id"], encoded(d["received_request_parameters"]))
              for d in record["disclosures"]]
    if len(set(actual)) != len(actual) or set(actual) != expected:
        raise ValueError("Disclosures do not cover the resolved received views exactly")
    if {r["receiver_id"] for r in receivers} != {rid for _, rid, _ in expected}:
        raise ValueError("Receiver list does not match resolved receipts")
    graphs = {}
    for disclosure in record["disclosures"]:
        graph_name, event_id = disclosure["evidence"].rsplit("#", 1)
        graph_path = Path(graph_name)
        if graph_name not in graphs:
            raw = graph_path.read_bytes()
            graphs[graph_name] = (json.loads(raw), hashlib.sha256(raw).hexdigest())
            data["source"]["graphs"].append({"path": str(graph_path.resolve()), "sha256": graphs[graph_name][1]})
        graph, graph_hash = graphs[graph_name]
        event = next(n for n in graph["nodes"] if n["id"] == event_id)
        if (disclosure["source_graph_sha256"] != graph_hash or event["type"] != "TOOL"
                or disclosure["event_id"] != event_id or disclosure["time"] != event["timestamp"]
                or event["payload"]["arguments"] != disclosure["received_request_parameters"]
                or event["payload"]["name"] != disclosure["tool"]
                or graph["task"]["prompt"] != record["prompt"]):
            raise ValueError("Recipient projection does not match its source trace")
        receipt = {"receipt_id": disclosure["disclosure_id"], "receiver_id": disclosure["receiver_id"],
                   "event_id": event_id, "time": disclosure["time"], "tool": disclosure["tool"],
                   "status": "received", "trace_kind": "observed",
                   "parameters": copy.deepcopy(disclosure["received_request_parameters"]),
                   "evidence": disclosure["evidence"], "tool_error": disclosure["tool_error"]}
        data["receipts"].append(receipt)
        facts, notes = extract_receipt_facts(receipt, record["task_key"])
        data["facts"].extend(facts)
        data["unresolved_items"].extend(notes)
    source_events = {n["id"] for graph, _ in graphs.values() for n in graph["nodes"] if n["type"] == "TOOL"}
    if source_events != {e["event_id"] for e in resolution["events"]}:
        raise ValueError("Recipient resolution does not cover the source tool events")
    if resolution.get("destination_ids"):
        data["unresolved_items"].append({"reason": "downstream_destinations_need_separate_received_content_projections",
                                         "destination_ids": resolution["destination_ids"]})
        for rid in resolution["destination_ids"]:
            if not any(r["receiver_id"] == rid for r in receivers):
                receivers.append({"receiver_id": rid, "name": rid, "view_complete": False,
                                  "background_knowledge": "not_modeled"})
    return data


def experiment_report(data, mode):
    modes = ("off", "on") if mode == "both" else (mode,)
    outputs = {arm: merge_knowledge(data, enabled=arm == "on") for arm in modes}
    report = {"schema_version": SCHEMA + ".experiment", "input": data, "outputs": outputs,
              "experiment": {"default": "off", "variable": "receiver_knowledge_pooling",
                             "same_input_and_local_reasoning_in_both_arms": True,
                             "limits": LIMITS, "real_delivery_performed": False}}
    if len(outputs) == 2:
        report["comparison"] = compare_knowledge(outputs["off"], outputs["on"])
        report["experiment"]["identical_local_baseline_verified"] = True
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--observed-record", type=Path)
    source.add_argument("--input", type=Path, help="Normalized input including receiver-specific evidence and rules")
    source.add_argument("--tasks", nargs="+", help="Task keys from real traces; resolved in memory")
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--receiver-merge", choices=("off", "on", "both"), default="off")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.tasks:
        datasets = []
        for task_key in args.tasks:
            if not re.fullmatch(r"[\w-]+/[\w-]+", task_key):
                raise ValueError("Expected task key suite/task_id")
            data = input_from_observed_graph(args.run_dir / task_key.replace("/", "_") / "graph.json")
            if data["task_key"] != task_key:
                raise ValueError("Task key does not match the source trace")
            datasets.append(data)
        if len(set(args.tasks)) != len(args.tasks):
            raise ValueError("Duplicate task key")
    else:
        datasets = [(json.loads(args.input.read_text(encoding="utf-8")) if args.input else
                     input_from_observed_record(args.observed_record or DEFAULT_RECORD))]
    output = args.output or (ROOT / "outputs/接收者知识合并对照.json" if args.tasks else DEFAULT_OUTPUT)
    protected = [p for p in (args.input, args.observed_record or DEFAULT_RECORD) if p]
    protected.extend(Path(g["path"]) for data in datasets for g in data.get("source", {}).get("graphs", []))
    if output.resolve() in {p.resolve() for p in protected}:
        raise ValueError("Output must not overwrite the input")
    reports = [experiment_report(data, args.receiver_merge) for data in datasets]
    report = ({"schema_version": SCHEMA + ".batch", "task_count": len(reports),
               "tasks": {r["input"]["task_key"]: r for r in reports}} if args.tasks else reports[0])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "tasks": [
        {"task_key": r["input"]["task_key"], "statuses": {m: o["status"] for m, o in r["outputs"].items()},
         "receiver_count": len(r["input"]["receivers"]), "received_fact_count": len(r["input"]["facts"]),
         "new_joint_knowledge_count": r.get("comparison", {}).get("new_joint_knowledge_count")}
        for r in reports]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
