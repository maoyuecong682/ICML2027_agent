"""长程双智能体实验入口：两个代表性任务串成一条记忆链。

    python run_long.py                 # 跑两个任务（共用一份图记忆）
    python run_long.py --render-only   # 只重绘，不调模型

记忆是"携带"的：task_1 跑完后，它的执行记忆留在 kuzu 图里；
task_4 启动时先 recall，B 因此可以先动（它已经"记得"这个用户和账户）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import ledger  # noqa: E402
from config import MEM_USER, RUNS, TASKS  # noqa: E402
from mem_baselines import make_memory  # noqa: E402

ledger.install()

from long_graph import run_long  # noqa: E402


def _clean(o):
    """去掉不能序列化的 pydantic env。"""
    return {k: v for k, v in o.items() if k not in ("env", "pre_env")}


def main(run_tag: str | None = None, use_memory: bool = True, only=None,
         mem_every: int = 1, chain=None, mem_kind: str = "graph",
         privacy: bool = False):
    from datetime import datetime
    tag = run_tag or datetime.now().strftime("%m%d_%H%M%S")
    if mem_kind == "none":
        use_memory = False
    mem = make_memory(mem_kind, MEM_USER, tag=tag)
    print(f"记忆库：{mem.root}  user={MEM_USER}  run={tag}  记忆类型={mem_kind}")
    tasks = chain or only or TASKS
    results = []
    for suite, tid in tasks:
        ledger.reset()
        fp0 = mem.footprint()
        print(f"\n{'='*64}\n{sut_name(suite, tid)}")
        try:
            r = run_long(suite, tid, mem, use_memory=use_memory,
                         mem_every=mem_every, privacy=privacy)
        except Exception:
            # 链式运行里单个任务炸掉不该把整条链一起带走，也不该让已跑的结果丢失
            import traceback
            traceback.print_exc()
            print(f"  !! {tid} 中断，跳过；已完成的 {len(results)} 个任务仍然落盘")
            continue
        fp1 = mem.footprint()
        lg = ledger.summary()
        r["footprint"] = {"before": fp0, "after": fp1}
        r["ledger"] = lg
        results.append(r)

        st = r.get("strict", {})
        print(f"  utility = {r['utility']}（benchmark 口径）   严格校验 = {st.get('ok')}  轮次 = {r['n_rounds']}")
        print(f"    严格校验说明：{st.get('note')}")
        for t in r["rounds"]:
            print(f"    [{t['actor']} r{t['round']:02d}] {t['signal']:10s} "
                  f"tools={t['tools']}  {t['summary'][:70]}")
        print(f"  工具调用 {len(r['tool_calls'])} 次，越权拦截 {len(r['denied'])} 次")
        print(f"  token: {lg['total']['in']} in / {lg['total']['out']} out "
              f"（{lg['total']['calls']} 次调用）")
        for k, v in lg["by_tag"].items():
            print(f"    {k:12s} {v['calls']:2d} 次  {v['in']:6d} in / {v['out']:5d} out  {v['ms']/1000:6.1f}s")
        print(f"  执行时间 t = {r['wall_ms']/1000:.1f}s")
        print(f"  记忆：条目 {fp0['n_memories']}→{fp1['n_memories']}，"
              f"图节点 {fp0['graph_nodes']}→{fp1['graph_nodes']}，"
              f"图边 {fp0['graph_edges']}→{fp1['graph_edges']}，"
              f"磁盘 {fp1['disk_bytes']/1024:.0f} KB")
        print(f"  原始文本 {fp1['raw_text_bytes']} B → 记忆 JSON {fp1['mem_json_bytes']} B")
        if privacy:
            gl = r.get("gate_log") or []
            drop = sum(1 for g in gl if g["action"].startswith("drop"))
            deg = sum(1 for g in gl if g["action"].startswith("degrade"))
            print(f"  门控：拦截 {len(gl)} 处（整句删 {drop}，降精度 {deg}）")
            for g in gl:
                print(f"    r{g['round']:02d} {g['action']:8s} #{g['id']} {g['subject']}")

    suffix = {"graph": "", "none": "_nomem", "full": "_full", "summary": "_summary"}.get(
        mem_kind, f"_{mem_kind}")
    if chain:
        suffix = "_chain" + suffix
    if mem_every > 1:
        suffix += f"_mEvery{mem_every}"
    if privacy:
        suffix += "_gate"
    out = RUNS / f"longrun_{tag}{suffix}.json"
    out.write_text(json.dumps({"run_tag": tag, "mem_root": str(mem.root),
                               "privacy": privacy,
                               "tasks": [_clean(r) for r in results]},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    if use_memory:
        (RUNS / "latest.txt").write_text(tag, encoding="utf-8")
    print(f"\n结果 -> {out}")
    return results


def sut_name(suite, tid):
    return f"{suite} / {tid}"


if __name__ == "__main__":
    if "--render-only" in sys.argv:
        from render_long import build_html
        tag = (RUNS / "latest.txt").read_text(encoding="utf-8").strip()
        data = json.loads((RUNS / f"longrun_{tag}.json").read_text(encoding="utf-8"))
        p = RUNS / "graphs.html"
        p.write_text(build_html(data), encoding="utf-8")
        print("HTML ->", p)
    else:
        only, chain = None, None
        if "--only" in sys.argv:
            i = sys.argv.index("--only")
            only = [(sys.argv[i + 1], sys.argv[i + 2])]
        if "--chain" in sys.argv:
            i = sys.argv.index("--chain")
            suite = sys.argv[i + 1]
            ids = sys.argv[i + 2].split(",")
            chain = [(suite, t.strip()) for t in ids if t.strip()]
        tag = sys.argv[sys.argv.index("--tag") + 1] if "--tag" in sys.argv else None
        main(run_tag=tag, use_memory="--no-mem" not in sys.argv, only=only, chain=chain,
             mem_every=2 if "--fast" in sys.argv else 1,
             privacy="--privacy" in sys.argv,
             mem_kind=(sys.argv[sys.argv.index("--memory") + 1]
                       if "--memory" in sys.argv else
                       ("none" if "--no-mem" in sys.argv else "graph")))
