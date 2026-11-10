"""离线重放：不调模型，估计门控规则改动会带来什么。

    python replay_gate.py            # 三档各 3 次，旧规则 vs 新规则

为什么需要它：门控是确定性规则，但它的输入（A 的措辞、检索到的记忆）
来自真实执行。重新跑一遍要花 3 次链 × 3 档的模型调用；而"规则改一行会怎样"
这个问题，可以直接拿**已经录下来的原文**重放一遍来估。

重放的可信度靠一步验证：用**旧规则**重放未门控的轨迹，
结果应当接近真实门控运行（图记忆 1.33 笔）。对得上，才说明重放没骗人。

必须承认的偏差：真实门控会改变 A 下一轮看到的内容，重放做不到这个反馈回路；
被门控删掉的句子原本可能引发后续对话。所以重放是**估计**，不是实验结果，
只能用来判断"这个改动方向值不值得花额度去跑"。
"""
from __future__ import annotations

import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

import privacy_ops
from config import RUNS  # noqa: E402
from infer_curve import BASE, KINDS, SUF  # noqa: E402
from privacy_leak import direct_leak, join, secret_sets  # noqa: E402


def ungated_file(kind: str, rep: int):
    name = (f"longrun_{BASE[kind]}{SUF[kind]}" if rep == 1
            else f"longrun_rep{rep}_{kind}{SUF[kind]}")
    return RUNS / name


def recipient_events(task: dict) -> tuple[list[str], list[str], list[str]]:
    """把一条轨迹按"接收方什么时候看到什么"拆开，保持事件顺序。

    返回 (检索到的记忆, A 的留言, 其余接收方可见内容)。
    其余部分（B 自己的最终答复）重放时原样保留——它是 B 说的话，
    真实门控也不改它。
    """
    mems, msgs, tail = [], [], []
    for e in task.get("trace") or []:
        ch, src, tgt = e.get("channel"), e.get("source"), e.get("target")
        if ch == "shared_memory" and tgt == "B":
            mems.append(str(e.get("content") or ""))
        elif ch == "inter_agent_message" and tgt == "B" and src == "A":
            msgs.append(str(e.get("content") or ""))
        elif ch == "final_output" and src == "B":
            tail.append(str(e.get("content") or ""))
    return mems, msgs, tail


def replay(chain: dict, facts: list[dict], use_direction: bool) -> list[dict]:
    orig = privacy_ops.prompt_direction
    if not use_direction:
        privacy_ops.prompt_direction = lambda p: ""      # 还原旧规则
    steps, prior = [], set()
    try:
        for task in chain["tasks"]:
            allowed = privacy_ops.allowed_ids(task["prompt"], facts)
            gate = privacy_ops.Gate(facts, allowed)

            mems, msgs, tail = recipient_events(task)
            kept_hits, _ = gate.screen_hits([{"memory": m} for m in mems])
            kept_msgs = [gate.screen(m)[0] for m in msgs]
            text = join([{"content": h["memory"]} for h in kept_hits]
                        + [{"content": m} for m in kept_msgs if m.strip()]
                        + [{"content": m} for m in tail])

            need, _ = secret_sets(task)
            need_ids = {x["id"] for x in need}
            leaked = {x["id"] for x in direct_leak(facts, text) if x["leaked"]}
            steps.append({"task": task["task_id"],
                          "residual": sorted((prior & leaked) - need_ids),
                          "leaked": sorted(leaked), "allowed": sorted(allowed)})
            prior |= need_ids
    finally:
        privacy_ops.prompt_direction = orig
    return steps


def main() -> None:
    from taskenv import load_task
    from privacy_ops import load_facts

    # 全链同一个账户，取一份初始环境即可（load_task 每次给的都是未改动的初始状态）
    facts = load_facts(load_task("banking", "user_task_7"))

    print(f"{'记忆档':<9}{'旧规则 残漏':>16}{'新规则 残漏':>16}   逐步（新规则，第 1 次）")
    for kind in KINDS:
        old_tot, new_tot = [], []
        detail = ""
        for rep in (1, 2, 3):
            f = ungated_file(kind, rep)
            if not f.exists():
                continue
            chain = json.loads(f.read_text(encoding="utf-8"))
            o = replay(chain, facts, use_direction=False)
            n = replay(chain, facts, use_direction=True)
            old_tot.append(sum(len(s["residual"]) for s in o))
            new_tot.append(sum(len(s["residual"]) for s in n))
            if rep == 1:
                detail = " ".join(f"{s['task'].replace('user_task_', 'T')}:"
                                  f"{len(s['residual'])}" for s in n)
        if not old_tot:
            continue
        mo = sum(old_tot) / len(old_tot)
        mn = sum(new_tot) / len(new_tot)
        print(f"{kind:<9}{f'{mo:.2f} {old_tot}':>16}{f'{mn:.2f} {new_tot}':>16}   {detail}")


if __name__ == "__main__":
    main()
