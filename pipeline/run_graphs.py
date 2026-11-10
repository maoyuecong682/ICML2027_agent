"""入口：跑 travel 与 banking 各 1 个任务，落执行图 / 隐私图，渲染成本地 HTML。

用法：
    python run_graphs.py                 # 跑两个任务并渲染
    python run_graphs.py travel user_task_0 banking user_task_0
    python run_graphs.py --render-only   # 只读 runs/*.json 重新渲染，不调模型
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from graph_exec import run_task
from privacy_skeleton import build_privacy_skeleton
from render_graphs import build_html

sys.stdout.reconfigure(encoding="utf-8")

OUT = Path(__file__).parent / "runs"
DEFAULT = [("travel", "user_task_0"), ("banking", "user_task_0")]


def _dump(path: Path, obj: dict):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def render_only():
    items = []
    for suite, task_id in DEFAULT:
        stem = f"{suite}_{task_id}"
        run = json.loads((OUT / f"{stem}.exec.json").read_text(encoding="utf-8"))
        pg = json.loads((OUT / f"{stem}.privacy.json").read_text(encoding="utf-8"))
        items.append((run, pg))
    (OUT / "graphs.html").write_text(build_html(items), encoding="utf-8")
    print(f"HTML -> {OUT / 'graphs.html'}")


def main(pairs):
    OUT.mkdir(exist_ok=True)
    items = []
    for suite, task_id in pairs:
        print(f"\n=== {suite} / {task_id} ===")
        run = run_task(suite, task_id)
        print(f"  nodes={run['summary']['n_nodes']} "
              f"api={run['summary']['n_api_calls']} "
              f"tools={run['summary']['n_tool_calls']} "
              f"tokens={run['summary']['tokens_in']}in/{run['summary']['tokens_out']}out "
              f"utility={run['utility']} "
              f"wall={run['summary']['wall_ms']/1000:.1f}s")

        pg = build_privacy_skeleton(run)

        stem = f"{suite}_{task_id}"
        slim = {k: v for k, v in run.items() if k not in ("env", "pre_env")}
        _dump(OUT / f"{stem}.exec.json", slim)
        _dump(OUT / f"{stem}.privacy.json", pg)

        for n in run["nodes"]:
            print(f"    - {n['id']:>3} {n['type']:<5} {n['label'][:34]:<34} {n.get('meta','')[:52]}")
        items.append((run, pg))

    html = build_html(items)
    (OUT / "graphs.html").write_text(html, encoding="utf-8")
    print(f"\nHTML -> {OUT / 'graphs.html'}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--render-only":
        render_only()
    else:
        pairs = [(args[i], args[i + 1]) for i in range(0, len(args), 2)] if args else DEFAULT
        main(pairs)

