"""Build relationship DATA from disclosures only; no detector or model calls."""
import copy
import hashlib
import itertools
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs" / "ocelot_20261028" / "披露信息.json"
TARGET = SOURCE.with_name("信息之间的关系.json")


def pointer_get(value, pointer):
    for part in pointer.lstrip("/").split("/") if pointer else []:
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def build(source):
    tasks = []
    for ti, task in enumerate(source["tasks"]):
        out = {"task_id": task["task_key"], "category_ids": task["category_ids"],
               "execution_status": task["execution_status"],
               "receivers": copy.deepcopy(task["receivers"]),
               "disclosure_records": None, "information_units": None,
               "relations": None, "entities": None, "joint_information_groups": None,
               "inference_candidates": None}
        tasks.append(out)
        if task["disclosures"] is None:
            out["note"] = "未执行；没有实际信息关系记录，null 不表示没有隐私。"
            continue
        units, relations, entities, groups, candidates, records = [], [], [], [], [], []
        out.update(information_units=units, relations=relations, entities=entities,
                   joint_information_groups=groups, inference_candidates=candidates, disclosure_records=records)

        def relate(kind, subject, object_, evidence, status="observed_structural_relation", **extra):
            relations.append({"relation_id": task["task_key"] + f"::relation:{len(relations)}",
                              "type": kind, "subject": subject, "object": object_,
                              "status": status, "evidence": evidence, **extra})

        for di, disclosure in enumerate(task["disclosures"]):
            prefix = f"/tasks/{ti}/disclosures/{di}"
            did, rid = disclosure["disclosure_id"], disclosure["receiver_id"]
            records.append({"disclosure_id": did, "event_id": disclosure["event_id"],
                "receiver_id": rid, "time": disclosure["time"], "tool": disclosure["tool"],
                "source_pointer": prefix, "received_parameters": copy.deepcopy(disclosure["received_request_parameters"]),
                "information_unit_ids": [a["atom_id"] for a in disclosure["atoms"]]})
            local_units = []
            for ai, atom in enumerate(disclosure["atoms"]):
                uid = atom["atom_id"]
                evidence = {"source_pointer": prefix + f"/atoms/{ai}",
                            "parameter_path": atom["parameter_path"], "span_start": atom["span_start"],
                            "span_end": atom["span_end"], "offset_unit": atom["offset_unit"]}
                unit = {"information_id": uid, "span": atom["span"], "field": atom["field"],
                    "kind": atom["kind"], "relation_label": atom["relation"],
                    "necessity": atom["necessity"], "provenance": atom["provenance"], "op": atom["op"],
                    "assessment_status": atom["assessment_status"], "disclosure_id": did,
                    "receiver_id": rid, "time": disclosure["time"], "evidence": evidence,
                    "source_references": [{"source_id": sid, "scope": task["task_key"],
                         "evidence": next((copy.deepcopy(e) for e in atom["provenance_evidence"] if e["source_id"] == sid), None)}
                        for sid in atom["source_ids"]]}
                units.append(unit)
                local_units.append(unit)
                relate("contained_in_disclosure", uid, did, evidence)
                relate("visible_to_receiver", uid, rid, evidence)
                for sid in atom["source_ids"]:
                    relate("attributed_to_source", uid, task["task_key"] + "::source:" + sid, evidence,
                           "source_attribution_from_existing_annotation")
                if atom["field"] != "none":
                    relate("directly_encodes_field" if atom["kind"] == "direct" else "may_imply_field",
                           uid, "field:" + atom["field"], evidence,
                           "existing_model_annotation_unreviewed", inference_claim=atom["inference_claim"])
                if atom["kind"] == "indirect":
                    candidates.append({"candidate_id": uid + "::inference", "receiver_id": rid,
                        "target_field": atom["field"], "claim": atom["inference_claim"],
                        "all_of": [uid], "context_constraints": {"same_task": True, "same_receiver": True},
                        "origin": "existing_model_annotation", "evidence": evidence,
                        "status": "hypothesis_not_validated", "privacy_gain_bits": None,
                        "not_established": ["秘密恢复成功", "披露不当", "接收者知识新增"]})
            for a, b in itertools.combinations(local_units, 2):
                same_span = (a["evidence"]["parameter_path"], a["evidence"]["span_start"], a["evidence"]["span_end"]) == (
                    b["evidence"]["parameter_path"], b["evidence"]["span_start"], b["evidence"]["span_end"])
                relate("same_text_occurrence_different_labels" if same_span else "co_disclosed",
                       a["information_id"], b["information_id"], {"source_pointer": prefix,
                           "disclosure_id": did, "receiver_id": rid},
                       interpretation="共现不证明同一实体或因果；同一片段多标签不应重复计算泄露量")
            # A semantically linked trip requires exact values in one explicit
            # Trip: line. Same source or same disclosure alone is insufficient.
            direct = {f: [u for u in local_units if u["field"] == f and u["kind"] == "direct"
                          and u["evidence"]["parameter_path"] == "/content"]
                      for f in ("legal_name", "travel_destination", "travel_dates")}
            content = disclosure["received_request_parameters"].get("content", "")
            for person, destination, dates in itertools.product(*direct.values()):
                lines = content.split("\\n") if "\\n" in content else content.splitlines()
                matches = [line for line in lines if line.startswith("Trip:") and
                           all(u["span"] in line for u in (person, destination, dates))]
                if len(matches) != 1:
                    continue
                line = matches[0]
                start = content.index(line)
                evidence = {"source_pointer": prefix + "/received_request_parameters/content",
                            "parameter_path": "/content", "quote": line, "span_start": start,
                            "span_end": start + len(line), "offset_unit": "Unicode code points"}
                group_id = did + "::trip:0"
                person_id = did + "::person:0"
                participants = [person["information_id"], destination["information_id"], dates["information_id"]]
                entities.append({"entity_id": person_id, "type": "person_mention", "name": person["span"],
                                 "evidence_information_ids": [person["information_id"]],
                                 "identity_scope": "仅限本次披露，不跨任务合并同名人员"})
                entities.append({"entity_id": group_id, "type": "planned_trip_mention",
                                 "destination": destination["span"], "date_text": dates["span"],
                                 "evidence_information_ids": participants,
                                 "status": "文本描述的计划，非现实出行已发生证明"})
                relate("planned_traveler_of", person_id, group_id, evidence,
                       "explicit_text_association", information_ids=participants)
                for slot, unit in (("traveler", person), ("destination", destination), ("dates", dates)):
                    relate("trip_component", unit["information_id"], group_id, evidence,
                           "explicit_text_association", role=slot)
                groups.append({"group_id": group_id, "type": "person_linked_travel_plan",
                    "receiver_id": rid, "disclosure_id": did, "information_ids": participants,
                    "roles": {"traveler": person["information_id"], "destination": destination["information_id"],
                              "dates": dates["information_id"]}, "evidence": evidence,
                    "binding_method": "all_three_values_in_one_explicit_Trip_line",
                    "member_offsets": {u["information_id"]: {"start": start + line.index(u["span"]),
                        "end": start + line.index(u["span"]) + len(u["span"])} for u in (person, destination, dates)},
                    "status": "explicit_text_association_not_leakage_verdict"})
                candidates.append({"candidate_id": group_id + "::inference", "receiver_id": rid,
                    "target_field": "travel_itinerary", "claim": person["span"] + " 的行程可关联到 " + destination["span"] + " 与 " + dates["span"],
                    "all_of": participants, "association_group_id": group_id,
                    "context_constraints": {"same_task": True, "same_receiver": True, "same_trip": group_id},
                    "origin": "explicit_disclosure_text_association", "evidence": evidence,
                    "status": "associated_plan_visible_recovery_not_tested", "privacy_gain_bits": None,
                    "not_established": ["实际已经出行", "住宅无人", "披露不当", "接收者知识新增"]})
        out["note"] = "关系由现有标注与原文整理；不执行直接或间接隐私检测，也不补造缺失的语义关系。"
    return {"schema_version": "p0.information_relations.v1", "source": {
        "file": str(SOURCE.relative_to(ROOT)).replace("\\", "/"), "sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "only_input": True}, "purpose": "供后续确定性检测器使用的信息关系数据，本轮不构建检测器",
        "boundary": copy.deepcopy(source["boundary"]), "ontology": copy.deepcopy(source["ontology"]),
        "semantics": {"information_unit": "沿用原有 atom_id；字段标签不等于已确认的隐私泄露",
            "relation": "类型明确的二元联系；联合关系另用 group 和 all_of 完整记录",
            "co_disclosed": "同次披露共现，不默认属于同一人或事件",
            "joint_information_group": "原文明确联系的多个片段，保留人员/事件/接收者和来源范围",
            "inference_candidate": "仅记录有证据的候选判断或关联，不是检测结果或完备规则库",
            "all_of": "后续检测需核对全部输入及上下文，不能把输入列表解释成任一满足即可",
            "unexecuted": "94 个任务的关系为 null，不能解释成没有隐私",
            "unknown": "没有完整实体识别、概率校准或常识推断，不保证覆盖所有间接隐私"},
        "tasks": tasks}


def validate(data, original):
    assert len(data["tasks"]) == 97
    totals = Counter()
    for task, raw in zip(data["tasks"], original["tasks"]):
        assert task["task_id"] == raw["task_key"]
        if raw["disclosures"] is None:
            assert task["relations"] is None and task["information_units"] is None
            totals["unexecuted_tasks"] += 1
            continue
        totals["executed_tasks"] += 1
        original_atoms = {a["atom_id"]: (a, d) for d in raw["disclosures"] for a in d["atoms"]}
        units = {u["information_id"]: u for u in task["information_units"]}
        assert units.keys() == original_atoms.keys()
        targets = set(units) | {d["disclosure_id"] for d in raw["disclosures"]} | {
            r["receiver_id"] for r in raw["receivers"]} | {e["entity_id"] for e in task["entities"]}
        for a, d in original_atoms.values():
            value = pointer_get(d["received_request_parameters"], a["parameter_path"])
            assert value[a["span_start"]:a["span_end"]] == a["span"]
        for relation in task["relations"]:
            assert relation["subject"] in targets
            assert relation["object"] in targets or relation["object"].startswith(("field:", task["task_id"] + "::source:"))
        for group in task["joint_information_groups"]:
            assert set(group["information_ids"]) <= set(units)
            assert len({units[i]["receiver_id"] for i in group["information_ids"]}) == 1
            quote = pointer_get(original, group["evidence"]["source_pointer"])
            assert quote[group["evidence"]["span_start"]:group["evidence"]["span_end"]] == group["evidence"]["quote"]
            for uid, offsets in group["member_offsets"].items():
                assert quote[offsets["start"]:offsets["end"]] == units[uid]["span"]
        for candidate in task["inference_candidates"]:
            assert set(candidate["all_of"]) <= set(units)
            assert all(units[i]["receiver_id"] == candidate["receiver_id"] for i in candidate["all_of"])
            assert candidate["privacy_gain_bits"] is None
        totals["information_units"] += len(units)
        totals["relations"] += len(task["relations"])
        totals["explicit_joint_groups"] += len(task["joint_information_groups"])
        totals["inference_candidates"] += len(task["inference_candidates"])
    assert totals["executed_tasks"] == 3 and totals["unexecuted_tasks"] == 94
    assert totals["information_units"] == 15 and totals["explicit_joint_groups"] == 1
    return dict(totals)


def main():
    before = SOURCE.read_bytes()
    original = json.loads(before.decode("utf-8"))
    data = build(original)
    data["statistics"] = validate(data, original)
    data["validation"] = {"passed": True, "checks": ["97 task scope", "15 original atom references",
        "verbatim spans and association evidence", "receiver isolation", "no fabricated unexecuted relations"],
        "detector_implemented": False, "new_model_calls": 0}
    assert SOURCE.read_bytes() == before
    TARGET.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    validate(json.loads(TARGET.read_text(encoding="utf-8")), original)
    print(json.dumps({"output": str(TARGET), "statistics": data["statistics"], "source_unchanged": True,
                      "detector_implemented": False}, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
