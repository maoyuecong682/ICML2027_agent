"""主入口：在两个代表性 agentdojo 任务上跑通 A/B 双智能体长程系统，并采集指标。

运行（默认离线 Mock，可复现；换 Key 后加 --backend deepseek 即真实联网）：
    python run_tasks.py
    python run_tasks.py --backend deepseek --tasks banking:user_task_0

产出：
    results/graphs/<suite>_<task>.json   执行图（全量）
    results/graphs/<suite>_<task>.png    执行图结构可视化
    results/report.json                   指标汇总
并在终端打印每个任务的：完成与否 / 记忆占用 / token 消耗 / 执行时间 t。
"""
from __future__ import annotations
import argparse
import copy
import json
import sys
from pathlib import Path

from config import RESULTS_DIR, GRAPHS_DIR, BACKEND as CFG_BACKEND
from llm_backend import make_backend
from dual_agent import run_task
from agentdojo_bridge import (load_suite, make_env, make_tool_callable,
                              tool_specs, check_utility, get_task)
from solvers import get_oracle
import viz


# 代表性任务：一个状态变更（银行付账单），一个只读多工具检索（工作区日历）
REPRESENTATIVE = [
    ("banking", "user_task_0"),
    ("workspace", "user_task_0"),
]


def extract_model_output(final_state) -> str:
    msgs = final_state.get("messages", [])
    for m in reversed(msgs):
        if m.get("role") == "assistant" and (m.get("content") or "").strip():
            return m["content"]
    return ""


def run_one(suite_name, task_id, backend_kind, max_steps):
    suite = load_suite("v1", suite_name)
    task = get_task(suite, task_id)

    env = make_env(suite)
    pre_env = copy.deepcopy(env)            # utility 比对用的“任务前”环境
    tool_callable = make_tool_callable(suite)
    specs = tool_specs(suite)

    backend = make_backend(backend_kind)
    oracle = get_oracle(suite_name, task_id)
    backend.load_script(task_id, oracle)

    final, elapsed, graph, memory = run_task(
        task_id, task.PROMPT, specs, tool_callable, env, backend,
        max_steps=max_steps)

    model_output = extract_model_output(final)
    completed = check_utility(task, model_output, pre_env, env)

    raw_bytes = graph.size_bytes(visible_only=False)
    comp_bytes = memory.snapshot_bytes()    # = 压缩后仅可见面字节数
    total_nodes = len(graph.nodes)
    vis_nodes = len(graph.visible_nodes())
    total_edges = len(graph.edges)
    usage = dict(backend.total_usage)
    compression_ratio = round(raw_bytes / comp_bytes, 3) if comp_bytes else 1.0
    archived_nodes = total_nodes - vis_nodes

    # 落盘：执行图 JSON
    gj = GRAPHS_DIR / f"{suite_name}_{task_id}.json"
    gj.write_text(json.dumps(graph.to_dict(visible_only=False),
                             ensure_ascii=False, indent=2), encoding="utf-8")

    # 落盘：可视化 PNG
    gp = GRAPHS_DIR / f"{suite_name}_{task_id}.png"
    viz.render_graph_png(graph, str(gp),
                         title=f"Execution Graph — {suite_name}/{task_id}  "
                               f"(backend={backend_kind})")

    return {
        "suite": suite_name,
        "task_id": task_id,
        "prompt": task.PROMPT,
        "completed": bool(completed),
        "model_output": model_output,
        "memory_bytes_compressed": comp_bytes,
        "memory_bytes_raw": raw_bytes,
        "compression_ratio": compression_ratio,
        "archived_nodes": archived_nodes,
        "nodes_total": total_nodes,
        "nodes_visible": vis_nodes,
        "edges_total": total_edges,
        "tokens_prompt": usage["prompt_tokens"],
        "tokens_completion": usage["completion_tokens"],
        "tokens_total": usage["prompt_tokens"] + usage["completion_tokens"],
        "llm_calls": usage["calls"],
        "exec_time_sec": round(elapsed, 4),
        "steps": final.get("step", 0),
        "graph_json": str(gj),
        "graph_png": str(gp),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default=CFG_BACKEND, choices=["mock", "deepseek"])
    ap.add_argument("--tasks", default=None,
                    help="逗号分隔的 suite:task，如 banking:user_task_0,workspace:user_task_0")
    ap.add_argument("--max-steps", type=int, default=14)
    args = ap.parse_args()

    if args.tasks:
        pairs = [tuple(t.split(":", 1)) for t in args.tasks.split(",")]
    else:
        pairs = REPRESENTATIVE

    RESULTS_DIR.mkdir(exist_ok=True)
    GRAPHS_DIR.mkdir(exist_ok=True)

    report = {"backend": args.backend, "tasks": []}
    print("=" * 78)
    print(f"长程双智能体执行系统  |  backend={args.backend}  |  任务数={len(pairs)}")
    print("=" * 78)

    for suite_name, task_id in pairs:
        try:
            r = run_one(suite_name, task_id, args.backend, args.max_steps)
        except Exception as e:
            r = {"suite": suite_name, "task_id": task_id,
                 "completed": False, "error": repr(e)}
            import traceback; traceback.print_exc()
        report["tasks"].append(r)

        status = "✅ 完成" if r.get("completed") else "❌ 未完成"
        print(f"\n[{suite_name}/{task_id}] {status}")
        print(f"  任务: {r.get('prompt','')[:70]}")
        if "error" in r:
            print(f"  错误: {r['error']}")
            continue
        print(f"  执行步数 step        : {r['steps']}")
        print(f"  记忆占用(压缩后)     : {r['memory_bytes_compressed']} B  "
              f"(原始 {r['memory_bytes_raw']} B, 压缩比 {r['compression_ratio']}x, "
              f"归档 {r['archived_nodes']} 节点, "
              f"可见节点 {r['nodes_visible']}/{r['nodes_total']}, 边 {r['edges_total']})")
        print(f"  Token 消耗          : 总 {r['tokens_total']} "
              f"(prompt {r['tokens_prompt']} + completion {r['tokens_completion']}), "
              f"LLM 调用 {r['llm_calls']} 次")
        print(f"  执行时间 t           : {r['exec_time_sec']} s")
        print(f"  执行图 JSON / PNG    : {r['graph_json']}")
        print(f"                        {r['graph_png']}")

    (RESULTS_DIR / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n" + "=" * 78)
    print(f"指标汇总已写入: {RESULTS_DIR / 'report.json'}")
    print("=" * 78)


if __name__ == "__main__":
    main()
