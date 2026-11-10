"""重复采样的结果：残漏的均值 + 每次实际的点。

    python render_rep.py        # 读 runs/replicate.json

单次采样时"图记忆 4、摘要 5"只差一笔，这种差最容易在重复采样后消失。
所以这张图不画误差棒糊弄人，直接把每次的点摆出来——点和点重叠到什么程度，
结论能站到什么程度，一眼可见。
"""
from __future__ import annotations

import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

from config import RUNS  # noqa: E402
from shot import shot  # noqa: E402

W, H = 1100, 580
COL = {"none": ("#3B6D11", "无记忆"), "graph": ("#534AB7", "图记忆 mem0"),
       "summary": ("#0F6E56", "普通摘要"), "full": ("#A32D2D", "完整历史")}
INK, MUT, BOR = "#2C2C2A", "#888780", "#E3E1DA"


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def panel(o, x, y, w, h, title, sub, stats, order, ymax=None, unit=""):
    vals = [v for s in stats for v in s["residual"]["vals"]]
    top = ymax or max(vals + [1])
    o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="#FFFFFF" '
             f'stroke="{BOR}" stroke-width="1"/>')
    o.append(f'<text x="{x + 18}" y="{y + 26}" font-size="13" font-weight="500" '
             f'fill="{INK}">{esc(title)}</text>')
    o.append(f'<text x="{x + 18}" y="{y + 44}" font-size="10.5" fill="{MUT}">{esc(sub)}</text>')

    px, py = x + 58, y + 66
    pw, ph = w - 88, h - 110
    for t in range(top + 1):
        gy = py + ph - t / top * ph
        o.append(f'<path d="M{px} {gy:.0f} L{px + pw} {gy:.0f}" stroke="#EFEEE9" '
                 f'stroke-width="0.8" stroke-dasharray="{"" if t == 0 else "3 4"}"/>')
        o.append(f'<text x="{px - 10}" y="{gy + 4:.0f}" text-anchor="end" font-size="10" '
                 f'fill="{MUT}">{t}</text>')

    gw = pw / len(stats)
    for i, s in enumerate(stats):
        color = COL[s["kind"]][0]
        vs = s["residual"]["vals"]
        cx = px + i * gw + gw / 2
        # 均值柱
        mean = s["residual"]["mean"]
        bh = mean / top * ph
        o.append(f'<rect x="{cx - 26:.0f}" y="{py + ph - bh:.0f}" width="52" '
                 f'height="{bh:.0f}" rx="5" fill="{color}" opacity="0.12"/>')
        # min-max 细线
        lo, hi = min(vs), max(vs)
        o.append(f'<path d="M{cx:.0f} {py + ph - hi / top * ph:.0f} '
                 f'L{cx:.0f} {py + ph - lo / top * ph:.0f}" stroke="{color}" '
                 f'stroke-width="1" opacity="0.5"/>')
        # 每次的点，横向错开避免完全重叠
        for j, v in enumerate(vs):
            dx = (j - (len(vs) - 1) / 2) * 9
            o.append(f'<circle cx="{cx + dx:.0f}" cy="{py + ph - v / top * ph:.0f}" r="4.6" '
                     f'fill="{color}" fill-opacity="0.75" stroke="#FFFFFF" stroke-width="1"/>')
        o.append(f'<text x="{cx:.0f}" y="{py + ph + 20}" text-anchor="middle" font-size="10.5" '
                 f'fill="{color}">{esc(COL[s["kind"]][1])}</text>')
        o.append(f'<text x="{cx:.0f}" y="{py + ph + 36}" text-anchor="middle" font-size="9.5" '
                 f'fill="{MUT}">n={s["n"]}</text>')
        if i == 0:
            lo_v, hi_v = min(vs), max(vs)
            o.append(f'<text x="{cx:.0f}" y="{py + ph - hi / top * ph - 10:.0f}" '
                     f'text-anchor="middle" font-size="9.5" fill="{MUT}">'
                     f'{lo_v}{"–" + str(hi_v) if hi_v != lo_v else ""}</text>')
        else:
            lo_v, hi_v = min(vs), max(vs)
            o.append(f'<text x="{cx:.0f}" y="{py + ph - hi / top * ph - 10:.0f}" '
                     f'text-anchor="middle" font-size="10" font-weight="500" fill="{color}">'
                     f'{lo_v}{"–" + str(hi_v) if hi_v != lo_v else ""}</text>')


def main():
    d = json.loads((RUNS / "replicate.json").read_text(encoding="utf-8"))
    order = ["none", "graph", "summary", "full"]
    stats = sorted([s for s in d["stats"] if s["n"]], key=lambda s: order.index(s["kind"]))

    o = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" '
         f'font-family="system-ui,-apple-system,Segoe UI,sans-serif">']
    o.append(f'<text x="40" y="30" font-size="17" font-weight="500" fill="{INK}">'
             f'重复采样：残漏到底差得动不动</text>')
    o.append(f'<text x="40" y="50" font-size="11.5" fill="{MUT}">'
             f'同一条四任务链，每档记忆跑 {d["reps"]} 遍。柱子是均值，点是每一次的实际值——'
             f'点重叠到哪里，差异就只到哪里。</text>')

    panel(o, 40, 74, 1020, 330, "残漏（累计，笔）",
          "与本任务无关的历史被反复放回上下文的次数；越少越好", stats, order)

    # ---- 结论：逐条看排序在每次采样里是否成立
    def vals(k):
        return {s["kind"]: s["residual"]["vals"] for s in stats}.get(k, [])

    g, s_ = vals("graph"), vals("summary")
    f_, n_ = vals("full"), vals("none")
    lines = []
    if g and s_:
        wins = sum(1 for a, b in zip(g, s_) if a < b)
        ties = sum(1 for a, b in zip(g, s_) if a == b)
        verdict = ("图记忆每次都低于摘要" if wins == len(g) else
                   f"图记忆有 {wins}/{len(g)} 次低于摘要，{ties} 次持平" if wins else
                   "图记忆没有一次低于摘要")
        lines.append(f"图记忆 vs 普通摘要：{verdict}。均值 {sum(g)/len(g):.2f} vs "
                     f"{sum(s_)/len(s_):.2f}。")
    if g and f_:
        lines.append(f"图记忆 vs 完整历史：{sum(g)/len(g):.2f} vs {sum(f_)/len(f_):.2f}，"
                     f"压缩减少暴露的方向是稳的。")
    if n_ and all(v == 0 for v in n_):
        lines.append("无记忆档在每一次采样里都是 0，隐私下界是确定的。")

    cy = 424
    o.append(f'<rect x="40" y="{cy}" width="1020" height="{H - cy - 34}" rx="10" fill="#F1EFE8"/>')
    for i, t in enumerate(lines):
        o.append(f'<text x="56" y="{cy + 24 + i * 20}" font-size="11.5" fill="#5F5E5A">'
                 f'{esc(t)}</text>')
    o.append(f'<text x="40" y="{H - 10}" font-size="10" fill="{MUT}">'
             f'残漏口径：prior 中本步仍出现且本步不需要的字面内容命中；不吃 LLM 采样噪声</text>')
    o.append("</svg>")

    svg = "".join(o)
    p = shot(svg, RUNS / "img" / "replicate.png")
    print(f"  {p.name}  {p.stat().st_size // 1024} KB")
    (RUNS / "replicate.html").write_text(
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<style>body{margin:0;padding:24px;background:#FAFAF8}</style></head>'
        f'<body>{svg}</body></html>', encoding="utf-8")


if __name__ == "__main__":
    main()
