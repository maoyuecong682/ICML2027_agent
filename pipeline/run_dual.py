"""入口：纯读任务 + 读写任务，各出执行图与隐私图。

    python run_dual.py                  # 跑两个任务并渲染
    python run_dual.py --render-only    # 只读 runs_dual/*.json 重绘，不调模型
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from graph_dual import run_task, TOOL_SPLIT
from privacy_dual import build_privacy
from render_dual import build_html

sys.stdout.reconfigure(encoding="utf-8")

OUT = Path(__file__).parent / "runs_dual"
# 纯读任务 / 读写任务（读写任务已换成数据自洽的 user_task_4）
TASKS = [("banking", "user_task_1"), ("banking", "user_task_4")]
NOTE = {"banking/user_task_1": "纯读任务：A 只读，B 只算，环境不变",
        "banking/user_task_4": "读写任务：A 读交易定位金额，B 原路退款"}


def _dump(p: Path, o: dict):
    p.write_text(json.dumps(o, ensure_ascii=False, indent=2), encoding="utf-8")


def render_only():
    items = []
    for suite, tid in TASKS:
        stem = f"{suite}_{tid}"
        items.append((json.loads((OUT / f"{stem}.exec.json").read_text(encoding="utf-8")),
                      json.loads((OUT / f"{stem}.privacy.json").read_text(encoding="utf-8"))))
    (OUT / "graphs.html").write_text(build_html(items, "纯读 / 读写各一。"), encoding="utf-8")
    print(f"HTML -> {OUT / 'graphs.html'}")


def main(tasks=None):
    tasks = tasks or TASKS
    OUT.mkdir(exist_ok=True)
    items = []
    for suite, tid in tasks:
        run = run_task(suite, tid)
        pg = build_privacy(run, run["env"], run["pre_env"])
        s = run["summary"]
        print(f"\n=== {suite}/{tid} ===")
        print(f"  utility={run['utility']}  A轮={s['a_turns']} B轮={s['b_turns']} "
              f"读={s['n_reads']} 写={s['n_writes']} "
              f"token={s['tokens_in']}in/{s['tokens_out']}out "
              f"模型={s['api_ms']/1000:.1f}s 端到端={s['wall_ms']/1000:.1f}s")
        print(f"  命题 {len(run['propositions'])} 条 / 环境变更 {run['env_changed'] or '无'}")
        for p in run["propositions"]:
            print(f"    {p['id']} [{p['kind']:10s}] {p['text'][:78]}")
        print(f"  隐私边 {pg['n_edges']} 条，接收者 {[r['name'] for r in pg['receivers']]}")

        stem = f"{suite}_{tid}"
        slim = {k: v for k, v in run.items() if k not in ("env", "pre_env")}
        _dump(OUT / f"{stem}.exec.json", slim)
        _dump(OUT / f"{stem}.privacy.json", pg)
        items.append((slim, pg))

    note = "；".join(NOTE.get(f"{s}/{t}", "") for s, t in tasks).strip("；")
    (OUT / "graphs.html").write_text(build_html(items, note), encoding="utf-8")
    print(f"\nHTML -> {OUT / 'graphs.html'}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--render-only" in sys.argv:
        render_only()
    elif args:
        main([(args[i], args[i + 1]) for i in range(0, len(args), 2)])
    else:
        main()
