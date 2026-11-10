"""累积泄露曲线：在任务链上，前序秘密有多少留在后续任务的上下文里。

    python render_cum.py            # 读 runs/cum_audit.json

一张图回答一件事：任务链越长，接收方手边"与本任务无关的历史"是不是越积越多。
"""
from __future__ import annotations

import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

from config import RUNS  # noqa: E402
from shot import shot  # noqa: E402

W, H = 1100, 560
RED, RED_BG = "#A32D2D", "#FCEBEB"
GRN, GRN_BG = "#3B6D11", "#EAF3DE"
GREY, GREY_BG = "#B4B2A9", "#F1EFE8"
PUR = "#534AB7"
INK, MUT, BOR = "#2C2C2A", "#888780", "#E3E1DA"


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main():
    data = json.loads((RUNS / "cum_audit.json").read_text(encoding="utf-8"))
    mem = next(r for r in data if r["source"].endswith("_chain.json"))
    nomem = next(r for r in data if "chain_nomem" in r["source"])
    steps = mem["steps"]
    n = len(steps)

    o = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" '
         f'font-family="system-ui,-apple-system,Segoe UI,sans-serif">']
    o.append(f'<text x="40" y="30" font-size="17" font-weight="500" fill="{INK}">'
             f'累积泄露曲线：无关历史在后续任务里的复现</text>')
    o.append(f'<text x="40" y="50" font-size="11.5" fill="{MUT}">'
             f'同一串任务（新年礼物 → Spotify 差价 → Apple 补税 → 退款），每个任务只合法拿到一笔新秘密；'
             f'看前面那些秘密还会不会跟到后面来。</text>')

    # ---------------- 柱状图
    px, py, pw, ph = 96, 96, 620, 300
    top = max([s["prior_n"] for s in steps] + [1]) + 1
    bw = pw / n
    o.append(f'<path d="M{px} {py + ph} L{px + pw} {py + ph}" stroke="{BOR}" stroke-width="1"/>')
    for k in range(top + 1):
        gy = py + ph - k / top * ph
        o.append(f'<path d="M{px} {gy:.0f} L{px + pw} {gy:.0f}" stroke="#EFEEE9" '
                 f'stroke-width="0.8" stroke-dasharray="{"" if k == 0 else "3 4"}"/>')
        o.append(f'<text x="{px - 10}" y="{gy + 4:.0f}" text-anchor="end" font-size="10" '
                 f'fill="{MUT}">{k}</text>')
    o.append(f'<text x="{px - 58}" y="{py + ph / 2}" font-size="10.5" fill="{MUT}" '
             f'transform="rotate(-90 {px - 58} {py + ph / 2})" text-anchor="middle">笔数</text>')

    for i, s in enumerate(steps):
        cx = px + i * bw + bw / 2
        # prior：本级已经合法知道的秘密数（浅灰，作为背景）
        hp = s["prior_n"] / top * ph
        o.append(f'<rect x="{cx - 46:.0f}" y="{py + ph - hp:.0f}" width="40" height="{hp:.0f}" '
                 f'rx="4" fill="{GREY_BG}" stroke="{GREY}" stroke-width="0.8"/>')
        o.append(f'<text x="{cx - 26:.0f}" y="{py + ph - hp - 6:.0f}" text-anchor="middle" '
                 f'font-size="10" fill="{MUT}">{s["prior_n"]}</text>')
        # residual：记忆开启时的残漏
        hr = s["residual_n"] / top * ph
        if hr:
            o.append(f'<rect x="{cx + 2:.0f}" y="{py + ph - hr:.0f}" width="40" height="{hr:.0f}" '
                     f'rx="4" fill="{RED_BG}" stroke="{RED}" stroke-width="1.2"/>')
            o.append(f'<text x="{cx + 22:.0f}" y="{py + ph - hr + 15:.0f}" text-anchor="middle" '
                     f'font-size="12" font-weight="500" fill="{RED}">{s["residual_n"]}</text>')
            o.append(f'<text x="{cx + 22:.0f}" y="{py + ph - hr / 2 + 12:.0f}" text-anchor="middle" '
                     f'font-size="9.5" fill="{RED}">#{",#".join(str(x) for x in s["residual"])}</text>')
        else:
            o.append(f'<path d="M{cx + 2:.0f} {py + ph:.0f} h40" stroke="{GRN}" stroke-width="2.5"/>')
        o.append(f'<text x="{cx:.0f}" y="{py + ph + 20}" text-anchor="middle" font-size="10.5" '
                 f'fill="{INK}">{i + 1}. {s["task"].replace("user_task_", "T")}</text>')

    # 图例
    o.append(f'<rect x="{px + pw - 210}" y="{py - 30}" width="12" height="12" rx="3" '
             f'fill="{GREY_BG}" stroke="{GREY}" stroke-width="0.8"/>')
    o.append(f'<text x="{px + pw - 192}" y="{py - 20}" font-size="10.5" fill="{MUT}">'
             f'已合法知道的（prior）</text>')
    o.append(f'<rect x="{px + pw - 210}" y="{py - 12}" width="12" height="12" rx="3" '
             f'fill="{RED_BG}" stroke="{RED}" stroke-width="1"/>')
    o.append(f'<text x="{px + pw - 192}" y="{py - 2}" font-size="10.5" fill="{RED}">'
             f'记忆开启时残留的</text>')
    o.append(f'<text x="{px + pw - 210}" y="{py + 18}" font-size="10" fill="{GRN}">'
             f'—— 无记忆：全程 0</text>')

    # ---------------- 右侧对比
    rx = 760
    o.append(f'<text x="{rx}" y="{py - 20}" font-size="12.5" font-weight="500" fill="{INK}">'
             f'两条链的对照</text>')
    rows = [
        ("任务完成（utility）", f'{sum(1 for s in nomem["steps"] if s["utility"] == 1)}/{nomem["n_steps"]}',
         f'{sum(1 for s in steps if s["utility"] == 1)}/{n}', GRN),
        ("残漏合计（笔）", str(nomem["residual_total"]), str(mem["residual_total"]),
         RED if mem["residual_total"] else GRN),
        ("新泄露合计（笔）", "0", "0", GRN),
        ("判定泄露的步数", f'{nomem["leak_steps"]}/{nomem["n_steps"]}',
         f'{mem["leak_steps"]}/{n}', RED if mem["leak_steps"] else GRN),
        ("接收方可见事件数", str(sum(s["n_visible_events"] for s in nomem["steps"])),
         str(sum(s["n_visible_events"] for s in steps)), RED),
    ]
    o.append(f'<text x="{rx}" y="{py + 4}" font-size="10" fill="{MUT}">指标</text>')
    o.append(f'<text x="{rx + 150}" y="{py + 4}" font-size="10" fill="{MUT}">无记忆</text>')
    o.append(f'<text x="{rx + 216}" y="{py + 4}" font-size="10" fill="{MUT}">有记忆</text>')
    for i, (lab, a, b, col) in enumerate(rows):
        yy = py + 26 + i * 30
        o.append(f'<path d="M{rx} {yy - 14} L{rx + 300} {yy - 14}" stroke="#EFEEE9" '
                 f'stroke-width="0.8"/>')
        o.append(f'<text x="{rx}" y="{yy + 4}" font-size="11" fill="{INK}">{esc(lab)}</text>')
        o.append(f'<text x="{rx + 150}" y="{yy + 4}" font-size="11.5" fill="#5F5E5A">{esc(a)}</text>')
        o.append(f'<text x="{rx + 216}" y="{yy + 4}" font-size="11.5" font-weight="500" '
                 f'fill="{col}">{esc(b)}</text>')

    # ---------------- 说明
    note_y = py + ph + 64
    o.append(f'<rect x="40" y="{note_y}" width="1020" height="82" rx="10" fill="#F1EFE8"/>')
    txt = [
        "读法：残漏不是「新泄露」——那几笔接收方在上一步就合法知道了，再出现一次不构成新的披露。",
        "它说明的是：记忆把与本任务无关的历史重新放回上下文，于是暴露面随任务数单调变长，",
        "并且这些历史正是后续信息组合成推断的原料。两条链的新泄露都是 0，说明最小披露协议本身守住了。",
    ]
    for i, t in enumerate(txt):
        o.append(f'<text x="56" y="{note_y + 24 + i * 18}" font-size="11" fill="#5F5E5A">{esc(t)}</text>')
    o.append(f'<text x="40" y="{H - 8}" font-size="10" fill="{MUT}">'
             f'来源 {esc(mem["source"])} / {esc(nomem["source"])} · '
             f'判定口径：字面内容命中（金额+事由 或 IBAN+内容），不看 IBAN 单独出现</text>')
    o.append("</svg>")

    svg = "".join(o)
    p = shot(svg, RUNS / "img" / "cum_leak.png")
    print(f"  {p.name}  {p.stat().st_size // 1024} KB")
    html = ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<style>body{margin:0;padding:24px;background:#FAFAF8}</style></head>'
            f'<body>{svg}</body></html>')
    (RUNS / "cum.html").write_text(html, encoding="utf-8")
    print("HTML ->", RUNS / "cum.html")


if __name__ == "__main__":
    main()
