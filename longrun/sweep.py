"""记忆写入频率网格：每 1 / 2 / 3 轮写一次，看成本与召回质量怎么变。

    python sweep.py            # 跑 1/2/3 三档
    python sweep.py 1 2        # 只跑指定档位

每档都用独立记忆库（互不污染），但同一档内两个任务串成一条记忆链——
所以 task_4 能不能"一步动手"，取决于 task_1 留下的记忆够不够。
task_4 的轮次因此成了召回质量的行为学代理：2 轮 = 召回命中，4 轮 = 得重新问 A。
"""
from __future__ import annotations

import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

import ledger
from config import MEM_USER, RUNS, TASKS
from mem_bridge import ExecMemory

ledger.install()

from long_graph import run_long  # noqa: E402

KEY_FACTS = ("GB29", "Sushi", "10.0")


def recall_hit(hits: list) -> bool:
    return any(any(k in (h.get("memory") or "") for k in KEY_FACTS) for h in hits)


def one_level(n: int) -> dict:
    tag = f"sweep_e{n}"
    mem = ExecMemory(MEM_USER, tag=tag)
    print(f"\n{'='*60}\nmem_every = {n}   mem={mem.root}", flush=True)
    rows = []
    for suite, tid in TASKS:
        ledger.reset()
        fp0 = mem.footprint()
        r = run_long(suite, tid, mem, mem_every=n)
        fp1 = mem.footprint()
        lg = ledger.summary()
        hit = recall_hit(r["memory_hits_first"])
        row = {
            "task": f"{suite}/{tid}",
            "mem_every": n,
            "utility": r["utility"],
            "strict": r["strict"]["ok"],
            "rounds": r["n_rounds"],
            "a_turns": r["a_turns"], "b_turns": r["b_turns"],
            "tok_in": lg["total"]["in"], "tok_out": lg["total"]["out"],
            "calls": lg["total"]["calls"],
            "t_s": round(r["wall_ms"] / 1000, 1),
            "mem_calls": lg["by_tag"].get("mem0_add", {}).get("calls", 0),
            "mem_s": round(lg["by_tag"].get("mem0_add", {}).get("ms", 0) / 1000, 1),
            "n_memories": fp1["n_memories"],
            "graph_nodes": fp1["graph_nodes"],
            "graph_edges": fp1["graph_edges"],
            "mem_json_bytes": fp1["mem_json_bytes"],
            "recall_hit": hit,
            "recall_n": len(r["memory_hits_first"]),
        }
        rows.append(row)
        print(f"  {row['task']:26s} u={row['utility']} s={row['strict']} "
              f"轮次={row['rounds']} tok={row['tok_in']}/{row['tok_out']} "
              f"t={row['t_s']}s 记忆={row['n_memories']}条 "
              f"图={row['graph_nodes']}/{row['graph_edges']} 召回命中={hit}", flush=True)
    return {"mem_every": n, "rows": rows}


def main(levels):
    res = [one_level(n) for n in levels]
    out = RUNS / "sweep.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n-> {out}")
    return res


if __name__ == "__main__":
    ns = [int(x) for x in sys.argv[1:] if x.isdigit()] or [1, 2, 3]
    main(ns)
