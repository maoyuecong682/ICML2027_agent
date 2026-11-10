"""四档记忆 × 有/无门控：把方法层的收益摊成一张表。

    python gate_matrix.py          # -> runs/gate_matrix.json

为什么要有这张表：只报"图记忆 5.0 → 1.33"说明不了方法本身值多少——
可能只是图记忆这一档特别差。四档一起装门控才能回答：
  · 门控的收益是**依赖记忆类型**，还是各档都差不多？
  · 装了门控之后，压缩还有没有额外价值（残漏会不会都掉到同一水平）？

残漏是确定性的（正则匹配），所以全部重算、不调模型。
"""
from __future__ import annotations

import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

from config import RUNS  # noqa: E402
from infer_curve import BASE, KINDS, SUF, account_items, residual_curve  # noqa: E402
from privacy_leak import channel_texts  # noqa: E402


def ungated_file(kind: str, rep: int):
    name = (f"longrun_{BASE[kind]}{SUF[kind]}" if rep == 1
            else f"longrun_rep{rep}_{kind}{SUF[kind]}")
    return RUNS / name


def gated_file(kind: str, rep: int):
    if kind == "graph":
        return RUNS / f"longrun_gate{rep}_chain_gate.json"
    return RUNS / f"longrun_gate_{kind}{rep}{SUF[kind][:-5]}_gate.json"


def measure(path) -> dict | None:
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    # 链没跑完就不参与比较：累积残漏是逐步累加的量，缺一步就不可比
    if len(d["tasks"]) < 4:
        return None
    items = account_items(d["tasks"][0]["suite"], d["tasks"][0]["task_id"])
    cum = residual_curve(d, items)
    visible = sum(len(channel_texts(t.get("trace") or [])["recipient"])
                  for t in d["tasks"])
    return {"residual": cum[-1], "cum": cum,
            "utility": sum(1 for t in d["tasks"] if t.get("utility")),
            "n_tasks": len(d["tasks"]),
            "visible": visible,
            "tok_out": sum((t.get("ledger") or {}).get("total", {}).get("out", 0)
                           for t in d["tasks"]),
            "gate": sum(len(t.get("gate_log") or []) for t in d["tasks"])}


def stat(vals: list[float]) -> dict:
    return {"mean": round(sum(vals) / len(vals), 2), "min": min(vals),
            "max": max(vals), "vals": vals, "n": len(vals)}


def main() -> None:
    res = {}
    for kind in KINDS:
        row = {}
        for arm, fn in (("off", ungated_file), ("on", gated_file)):
            rows = [m for m in (measure(fn(kind, r)) for r in (1, 2, 3)) if m]
            if not rows:
                continue
            row[arm] = {
                "residual": stat([x["residual"] for x in rows]),
                "utility": stat([x["utility"] for x in rows]),
                "visible": stat([x["visible"] for x in rows]),
                "tok_out": stat([round(x["tok_out"] / 1000) for x in rows]),
                "gate": stat([x["gate"] for x in rows]),
                "n_tasks": rows[0]["n_tasks"],
            }
        res[kind] = row

    (RUNS / "gate_matrix.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{'记忆档':<9}{'残漏 无门控':>15}{'残漏 有门控':>15}{'降幅':>8}"
          f"{'任务完成':>14}{'可见事件':>15}{'门控动作':>10}")
    for kind in KINDS:
        row = res.get(kind) or {}
        if "off" not in row or "on" not in row:
            print(f"{kind:<9}（数据不全，见下方缺失提示）")
            continue
        o, n = row["off"], row["on"]
        ro, rn = o["residual"], n["residual"]
        cut = (1 - rn["mean"] / ro["mean"]) * 100 if ro["mean"] else 0.0
        s_off = f"{ro['mean']:.2f} [{ro['min']}-{ro['max']}]"
        s_on = f"{rn['mean']:.2f} [{rn['min']}-{rn['max']}]"
        s_util = f"{o['utility']['mean']:.2f} → {n['utility']['mean']:.2f}"
        s_vis = f"{o['visible']['mean']:.1f} → {n['visible']['mean']:.1f}"
        print(f"{kind:<9}{s_off:>15}{s_on:>15}{f'{cut:.0f}%':>8}"
              f"{s_util:>14}{s_vis:>15}{n['gate']['mean']:>10.1f}")
        print(f"{'':<9}（无门控 n={ro['n']}，门控 n={rn['n']}）")
    print(f"\n（任务完成满分 = {list(res.values())[0]['off']['n_tasks']}）")
    print("\n-> runs/gate_matrix.json")


if __name__ == "__main__":
    main()
