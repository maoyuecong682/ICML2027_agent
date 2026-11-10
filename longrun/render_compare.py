"""四档对照：无记忆 / 图记忆 / 普通摘要 / 完整历史。

    python render_compare.py        # 读 runs/cum_audit.json

回答一个问题：压缩到底买到了什么。横轴是任务链的步数，纵轴是**累计**残漏
（无关历史被反复放回上下文的次数），右侧给出任务能力与开销。
"""
from __future__ import annotations

import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

from config import RUNS  # noqa: E402
from shot import shot  # noqa: E402

W, H = 1100, 600
COL = {"none": ("#3B6D11", "#EAF3DE", "无记忆"),
       "graph": ("#534AB7", "#EEEDFE", "图记忆 mem0"),
       "summary": ("#0F6E56", "#E1F5EE", "普通摘要"),
       "full": ("#A32D2D", "#FCEBEB", "完整历史")}
INK, MUT, BOR = "#2C2C2A", "#888780", "#E3E1DA"


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main():
    data = json.loads((RUNS / "cum_audit.json").read_text(encoding="utf-8"))
    by = {r["kind"]: r for r in data}
    order = [k for k in ("none", "graph", "summary", "full") if k in by]
    n = max(r["n_steps"] for r in by.values())

    o = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" '
         f'font-family="system-ui,-apple-system,Segoe UI,sans-serif">']
    o.append(f'<text x="40" y="30" font-size="17" font-weight="500" fill="{INK}">'
             f'四档记忆的对照：压缩买到了什么</text>')
    o.append(f'<text x="40" y="50" font-size="11.5" fill="{MUT}">'
             f'同一条四任务链（新年礼物 → Spotify 差价 → Apple 补税 → 退款），只换记忆实现。'
             f'纵轴是累计残漏笔数——与本任务无关的历史被放回上下文的次数。</text>')

    # ---------------- 折线
    px, py, pw, ph = 96, 96, 540, 300
    vals = []
    for k in order:
        cum, run = [], 0
        for s in by[k]["steps"]:
            run += s["residual_n"]
            cum.append(run)
        vals += cum
    top = max(vals + [1])
    o.append(f'<path d="M{px} {py + ph} L{px + pw} {py + ph}" stroke="{BOR}" stroke-width="1"/>')
    for t in range(top + 1):
        gy = py + ph - t / top * ph
        o.append(f'<path d="M{px} {gy:.0f} L{px + pw} {gy:.0f}" stroke="#EFEEE9" '
                 f'stroke-width="0.8" stroke-dasharray="{"" if t == 0 else "3 4"}"/>')
        o.append(f'<text x="{px - 10}" y="{gy + 4:.0f}" text-anchor="end" font-size="10" '
                 f'fill="{MUT}">{t}</text>')
    step = pw / max(n - 1, 1)
    for i in range(n):
        cx = px + i * step
        o.append(f'<text x="{cx:.0f}" y="{py + ph + 20}" text-anchor="middle" font-size="10.5" '
                 f'fill="{INK}">{i + 1}</text>')
    o.append(f'<text x="{px + pw / 2}" y="{py + ph + 40}" text-anchor="middle" font-size="10.5" '
             f'fill="{MUT}">任务链第几步</text>')

    for k in order:
        color = COL[k][0]
        cum, run = [], 0
        for s in by[k]["steps"]:
            run += s["residual_n"]
            cum.append(run)
        d = " ".join(f'{"M" if i == 0 else "L"}{px + i * step:.0f} '
                     f'{py + ph - v / top * ph:.0f}' for i, v in enumerate(cum))
        o.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2.4" '
                 f'stroke-linejoin="round"/>')
        for i, v in enumerate(cum):
            cx, cy = px + i * step, py + ph - v / top * ph
            o.append(f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="4" fill="#FFFFFF" '
                     f'stroke="{color}" stroke-width="2"/>')
            if i == len(cum) - 1:
                o.append(f'<text x="{cx + 10:.0f}" y="{cy + 4:.0f}" font-size="11" '
                         f'font-weight="500" fill="{color}">{v}</text>')

    # 图例
    for i, k in enumerate(order):
        color, bg, name = COL[k]
        ly = py - 26 + (i // 2) * 18
        lx = px + 250 + (i % 2) * 150
        o.append(f'<path d="M{lx} {ly} h18" stroke="{color}" stroke-width="2.6"/>')
        o.append(f'<circle cx="{lx + 9}" cy="{ly}" r="3.6" fill="#FFFFFF" stroke="{color}" '
                 f'stroke-width="2"/>')
        o.append(f'<text x="{lx + 24}" y="{ly + 4}" font-size="10.5" fill="{INK}">{name}</text>')

    # ---------------- 汇总表
    tx = 662
    o.append(f'<text x="{tx}" y="{py - 20}" font-size="12.5" font-weight="500" fill="{INK}">'
             f'任务能力与开销</text>')
    heads = ["条件", "完成", "残漏", "事件", "token out", "时间", "记忆"]
    xs = [tx, tx + 88, tx + 120, tx + 152, tx + 186, tx + 266, tx + 312]
    for x, h in zip(xs, heads):
        o.append(f'<text x="{x}" y="{py + 2}" font-size="9.5" fill="{MUT}">{h}</text>')
    for i, k in enumerate(order):
        r = by[k]
        yy = py + 26 + i * 30
        color = COL[k][0]
        o.append(f'<path d="M{tx} {yy - 14} L{W - 40} {yy - 14}" stroke="#EFEEE9" '
                 f'stroke-width="0.8"/>')
        o.append(f'<text x="{tx}" y="{yy + 4}" font-size="10.5" font-weight="500" '
                 f'fill="{color}">{esc(COL[k][2])}</text>')
        cells = [f'{r["utility_pass"]}/{r["n_steps"]}', str(r["residual_total"]),
                 str(r["visible_total"]), f'{r["tok_out"]:,}', f'{r["t_total"]:.0f}s',
                 f'{r["steps"][-1]["mem_items"] if r["steps"] else 0} 条']
        for x, c in zip(xs[1:], cells):
            emph = (c == str(r["residual_total"]) and r["residual_total"] > 0)
            o.append(f'<text x="{x}" y="{yy + 4}" font-size="10.5" '
                     f'fill="{COL[k][0] if emph else "#5F5E5A"}">{esc(c)}</text>')

    # ---------------- 结论条
    cy = py + ph + 70
    o.append(f'<rect x="40" y="{cy}" width="1020" height="{H - cy - 30}" rx="10" fill="#F1EFE8"/>')
    lines = []
    if "graph" in by and "full" in by:
        g, f = by["graph"], by["full"]
        lines.append(
            f'残漏单调：无记忆 0 ＜ 图记忆 {g["residual_total"]} ＜ 普通摘要 '
            f'{by.get("summary", {}).get("residual_total", "?")} ＜ 完整历史 {f["residual_total"]}。'
            f'压缩确实减少暴露，但摘要比图记忆更差——它把历史糊成一段话，'
            f'没法按任务边界取舍。')
        lines.append(
            f'代价：图记忆输出 token {g["tok_out"]:,}，完整历史只有 {f["tok_out"]:,}，'
            f'时间 {g["t_total"]:.0f}s vs {f["t_total"]:.0f}s。'
            f'省下的 {f["residual_total"] - g["residual_total"]} 笔残漏是拿 20 倍的输出换来的。')
    if "summary" in by and "graph" in by:
        s, g = by["summary"], by["graph"]
        lines.append(
            f'可见事件少 ≠ 暴露少：摘要只有 {s["visible_total"]} 条可见事件（图记忆 {g["visible_total"]} 条），'
            f'残漏却更大（{s["residual_total"]} vs {g["residual_total"]}），'
            f'还引入了全表唯一一次新泄露。因为摘要每次把整段历史塞进一条消息，密度更高。')
    lines.append(
        "任务完成率不能直接比：task_7 的 A 侧会把 200.0 抄成相邻交易的 100.0（读数错误，与记忆无关）；"
        "摘要档的 task_4 判 0 是被压缩错的金额带偏，属摘要本身的问题。残漏是确定性的，不受这些影响。")
    for i, t in enumerate(lines):
        o.append(f'<text x="56" y="{cy + 24 + i * 20}" font-size="11" fill="#5F5E5A">'
                 f'{esc(t)}</text>')
    o.append(f'<text x="40" y="{H - 8}" font-size="10" fill="{MUT}">'
             f'残漏 = prior 中本步仍出现且本步不需要的（字面内容命中口径）</text>')
    o.append("</svg>")

    svg = "".join(o)
    p = shot(svg, RUNS / "img" / "mem_compare.png")
    print(f"  {p.name}  {p.stat().st_size // 1024} KB")
    (RUNS / "compare.html").write_text(
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<style>body{margin:0;padding:24px;background:#FAFAF8}</style></head>'
        f'<body>{svg}</body></html>', encoding="utf-8")


if __name__ == "__main__":
    main()
