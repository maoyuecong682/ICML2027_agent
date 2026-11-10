"""重复采样：给四档对照的每个数字配上范围。

    python replicate.py 3            # 每种记忆跑 3 遍（含已有的第 1 遍）
    python replicate.py 3 --audit    # 跑完顺便审计并汇总

为什么必须做：图记忆残漏 4、普通摘要 5，只差 1 笔。单次采样下这个差完全可能是噪声，
而"摘要比图记忆更差"正是要写进论文的结论之一。不给范围就等于没证明。

残漏/新漏是确定性的（只看字面命中），不依赖推断攻击，
所以审计走 `--no-infer`，几十秒就能出一批，不必为每条链付两次 LLM 往返。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from config import RUNS  # noqa: E402

CHAIN = [("banking", t) for t in
         ("user_task_7", "user_task_5", "user_task_11", "user_task_4")]
KINDS = ["none", "graph", "summary", "full"]
SUF = {"none": "_chain_nomem.json", "graph": "_chain.json",
       "summary": "_chain_summary.json", "full": "_chain_full.json"}
HERE = Path(__file__).parent


def run_missing(reps: int) -> None:
    """已有的第 1 遍不重跑，只补第 2..reps 遍。

    每个采样起独立进程：一个进程里连续建多个 mem0 实例容易在 kuzu/qdrant 上出事，
    而且一旦中途炸掉，已跑完的那些结果还能各自落盘。
    """
    ids = ",".join(t for _, t in CHAIN)
    for rep in range(2, reps + 1):
        for kind in KINDS:
            tag = f"rep{rep}_{kind}"
            print(f"\n{'#'*70}\n# 重复采样 {rep}/{reps}　记忆={kind}　tag={tag}\n{'#'*70}",
                  flush=True)
            with open(RUNS / f"_rep{rep}_{kind}.log", "w", encoding="utf-8") as fh:
                p = subprocess.run(
                    [sys.executable, "run_long.py", "--tag", tag,
                     "--chain", CHAIN[0][0], ids, "--memory", kind],
                    cwd=str(HERE), stdout=fh, stderr=subprocess.STDOUT)
            print(f"  exit={p.returncode}", flush=True)


def collect(reps: int) -> list[dict]:
    """把第 1 遍（正式实验的 tag）与 rep2..n 一起收进来。"""
    from cum_audit import run_chain
    base = {"none": "1027_030948", "graph": "1027_024823",
            "summary": "1027_031124", "full": "1027_031522"}
    out = []
    for kind in KINDS:
        files = [RUNS / f"longrun_{base[kind]}{SUF[kind]}"]
        files += [RUNS / f"longrun_rep{r}_{kind}{SUF[kind]}" for r in range(2, reps + 1)]
        for i, f in enumerate(files, 1):
            if not f.exists():
                print(f"  跳过（不存在）：{f.name}")
                continue
            r = run_chain(f, do_infer=False)
            r["rep"] = i
            out.append(r)
    return out


def stats(rows: list[dict]) -> dict:
    def rng(key):
        v = [r[key] for r in rows]
        return {"mean": round(sum(v) / len(v), 2), "min": min(v), "max": max(v), "n": len(v),
                "vals": v}
    return {"kind": rows[0]["kind"], "n": len(rows),
            "residual": rng("residual_total"),
            "new_leak": rng("new_leak_total"),
            "visible": rng("visible_total"),
            "utility": rng("utility_pass"),
            "tok_out": rng("tok_out"),
            "t_total": rng("t_total")}


def main():
    reps = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 3
    if "--audit" not in sys.argv:
        run_missing(reps)
    rows = collect(reps)

    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["kind"], []).append(r)
    summ = [stats(v) for k, v in by.items() if v]

    print(f"\n{'='*78}\n重复采样汇总（n = 每档次数）")
    print(f"{'条件':<10}{'n':<4}{'残漏 mean[min-max]':<26}{'新漏':<12}"
          f"{'可见事件':<16}{'完成':<14}{'token out':<18}")
    for s in sorted(summ, key=lambda x: KINDS.index(x["kind"])):
        f = lambda d: f'{d["mean"]}[{d["min"]}-{d["max"]}]'
        print(f'{s["kind"]:<10}{s["n"]:<4}{f(s["residual"]):<26}{f(s["new_leak"]):<12}'
              f'{f(s["visible"]):<16}{f(s["utility"]):<14}{f(s["tok_out"]):<18}')

    out = RUNS / "replicate.json"
    out.write_text(json.dumps({"reps": reps, "stats": summ,
                               "runs": [{k: r[k] for k in
                                         ("source", "kind", "rep", "residual_total",
                                          "new_leak_total", "visible_total",
                                          "utility_pass", "t_total", "tok_out")}
                                        for r in rows]},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n->", out)


if __name__ == "__main__":
    main()
