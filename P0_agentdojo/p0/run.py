"""Sample once, run once per task, and retain every attempted task including failures."""
import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import random
import sys
import time
import traceback
from collections import Counter
from dataclasses import replace
from pathlib import Path

from agentdojo.task_suite.load_suites import get_suites

from .backend import DeepSeek
from .config import Config
from .pipeline import TwoAgentPipeline
from .policy import Permissions
from .records import Records, dump, now

ROOT = Path(__file__).resolve().parents[1]


def sample(config):
    suites = get_suites(config.suite_version)
    pool = [(name, task.ID) for name, suite in sorted(suites.items())
            for task in sorted(suite.user_tasks.values(), key=lambda t: int(t.ID.rsplit("_", 1)[1]))]
    selected = random.Random(config.seed).sample(pool, config.sample_size)
    return {"algorithm": "random.Random(seed).sample(sorted full population, 3)",
            "seed": config.seed, "suite_version": config.suite_version,
            "population_count": len(pool), "population": [list(p) for p in pool],
            "selection_before_execution": True,
            "tasks": [{"suite": name, "task_id": tid,
                       "prompt": suites[name].get_user_task_by_id(tid).PROMPT,
                       "difficulty": str(suites[name].get_user_task_by_id(tid).DIFFICULTY)} for name, tid in selected]}


def environment_manifest():
    packages = ["agentdojo", "langgraph", "langgraph-checkpoint", "openai", "Pillow"]
    return {"python": sys.version, "executable": sys.executable, "platform": platform.platform(),
            "packages": {p: importlib.metadata.version(p) for p in packages}}


def code_hashes():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "p0").glob("*.py"))}


def run_one(task_info, config, folder, api_key):
    records = Records(folder)
    suite = get_suites(config.suite_version)[task_info["suite"]]
    task = suite.get_user_task_by_id(task_info["task_id"])
    pipeline = TwoAgentPipeline(suite.name, DeepSeek(api_key, config, records), config, records)
    t0 = time.perf_counter()
    result = {**task_info, "started_at": now(), "config": config.public(),
              "utility": None, "error": None, "status": "started", "injection": None}
    try:
        utility, _ = suite.run_task_with_pipeline(pipeline, task, injection_task=None, injections={})
        result.update(utility=int(utility), status=pipeline.final_state["status"],
                      answer=pipeline.final_state["answer"])
        records.event("EVALUATION", "system", f"Official utility = {int(utility)}",
                      {"utility": int(utility), "entrypoint": "TaskSuite.run_task_with_pipeline",
                       "evaluation_order": "utility_from_traces, falling back to utility",
                       "pipeline_status": pipeline.final_state["status"]})
    except Exception as exc:
        result.update(status="error", error={"type": type(exc).__name__, "message": str(exc)})
        records.event("ERROR", "system", type(exc).__name__, result["error"])
        (folder / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
    result.update(finished_at=now(), wall_seconds=round(time.perf_counter()-t0, 3),
                  agents=records.usage(), events=len(records.nodes),
                  event_counts=dict(Counter(n["type"] for n in records.nodes)))
    if pipeline.environment_before is not None:
        pre, post = pipeline.environment_before.model_dump(mode="json"), pipeline.environment_after.model_dump(mode="json")
        dump(folder / "environment.before.json", pre)
        dump(folder / "environment.after.json", post)
        result["changed_environment_fields"] = [k for k in pre if pre[k] != post[k]]
    # This aggregate list belongs only to the evaluator, never to an agent's context.
    dump(folder / "evaluation_messages.json", [
        {**msg, **({"tool_calls": [t.model_dump() for t in msg["tool_calls"]]} if msg.get("tool_calls") else {}),
         **({"tool_call": msg["tool_call"].model_dump()} if msg.get("tool_call") else {})}
        for msg in pipeline.evaluation_messages])
    dump(folder / "result.json", result)
    dump(folder / "execution_memory.json", pipeline.execution_memory)
    if hasattr(pipeline, "workflow"):
        dump(folder / "workflow.json", pipeline.workflow)
    dump(folder / "graph.json", {"schema_version": "p0.execution.v1", "task": task_info,
         "config": config.public(), "result": result,
         "edge_semantics": {"sequence": "observed chronological next event; not causal proof",
                            "data": "observation/message explicitly supplied in context; not inferred causal influence"},
         "nodes": records.nodes, "edges": records.edges})
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="p0_20261028_seed20261028")
    parser.add_argument("--seed", type=int, default=Config.seed)
    parser.add_argument("--sample-only", action="store_true")
    args = parser.parse_args()
    if Path(args.run_id).name != args.run_id or args.run_id in (".", ".."):
        parser.error("run-id must be a single directory name")
    config = replace(Config(), seed=args.seed)
    folder = ROOT / "runs" / args.run_id
    folder.mkdir(parents=True, exist_ok=False)
    for name, suite in get_suites(config.suite_version).items():
        Permissions(name, [t.name for t in suite.tools])
    selection = sample(config)
    dump(folder / "selection.json", selection)
    dump(folder / "manifest.json", {"created_at": now(), "config": config.public(),
         "environment": environment_manifest(), "source_sha256": code_hashes()})
    if args.sample_only:
        print(json.dumps(selection["tasks"], ensure_ascii=False, indent=2))
        return
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Set DEEPSEEK_API_KEY in the process environment; no key is written to this workspace")
    print(f"Both agents: {config.base_url} / {config.model}; thinking=disabled", flush=True)
    results = []
    for task in selection["tasks"]:
        name = f"{task['suite']}_{task['task_id']}"
        print(f"START {name}: {task['prompt']}", flush=True)
        result = run_one(task, config, folder / name, api_key)
        results.append(result)
        dump(folder / "summary.json", {"attempted": len(results), "selected": len(selection["tasks"]),
             "official_successes": sum(r["utility"] == 1 for r in results), "tasks": results})
        print(f"END {name}: status={result['status']} utility={result['utility']} {result['wall_seconds']}s", flush=True)
    from .render import render_run
    render_run(folder)
    from .report import write_report
    write_report(folder)
    print(f"Artifacts: {folder}\nReport: {ROOT / 'P0.md'}", flush=True)


if __name__ == "__main__":
    main()
