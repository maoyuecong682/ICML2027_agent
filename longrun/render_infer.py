"""把 infer_curve.json 画成两条曲线：推断命中 / 字面可读。

    python render_infer.py        # -> runs/img/infer_curve.png

左图回答 TRAIL 实验一的问题：历史变长，**推断**是否变准（虚线是盲猜基线）。
右图是解释：同一批历史里**字面**能直接读到几笔。
两张图对照着看，才能分清一次命中是推断出来的，还是抄过去的。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from xml.sax.saxutils import escape as esc

sys.stdout.reconfigure(encoding="utf-8")

from config import RUNS  # noqa: E402
from shot import shot  # noqa: E402

W, H = 1100, 648
COL = {"none": ("#3B6D11", "无记忆"), "graph": ("#534AB7", "图记忆 mem0"),
       "summary": ("#0F6E56", "普通摘要"), "full": ("#A32D2D", "完整历史")}
KINDS = ["none", "graph", "summary", "full"]
INK, MUT, BOR, PANEL = "#2C2C2A", "#888780", "#E3E1DA", "#FFFFFF"


def panel(x, y, w, h, title, sub, data, ymax, baseline=None, bnote=""):
    """data: {kind: [v0, v1, ..., vK]}，横轴就是下标 k。"""
    o = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{PANEL}" '
         f'stroke="{BOR}" stroke-width="1"/>',
         f'<text x="{x + 18}" y="{y + 26}" font-size="13" font-weight="500" '
         f'fill="{INK}">{esc(title)}</text>',
         f'<text x="{x + 18}" y="{y + 44}" font-size="11" fill="{MUT}">{esc(sub)}</text>']

    px, py = x + 62, y + 72
    pw, ph = w - 88, h - 112
    nk = max(len(v) for v in data.values()) - 1
    xstep = pw / max(nk, 1)

    def X(i):
        return px + i * xstep

    def Y(v):
        return py + ph - (v / ymax) * ph

    # 网格：值域小的时候一格一个整数，别弄出 4.8 / 3.6 这种刻度
    steps = int(ymax) if ymax <= 8 else 5
    for k in range(steps + 1):
        v = ymax * k / steps
        gy = Y(v)
        o.append(f'<path d="M{px} {gy:.1f} L{px + pw} {gy:.1f}" stroke="#EFEEE9" '
                 f'stroke-width="1"/>')
        o.append(f'<text x="{px - 10}" y="{gy + 4:.1f}" font-size="10.5" fill="{MUT}" '
                 f'text-anchor="end">{v:g}</text>')

    # 盲猜基线：横穿整幅图的虚线
    if baseline is not None:
        by = Y(baseline)
        o.append(f'<path d="M{px} {by:.1f} L{px + pw} {by:.1f}" stroke="{MUT}" '
                 f'stroke-width="1.4" stroke-dasharray="5 4"/>')
        o.append(f'<text x="{px + pw - 4}" y="{by - 6:.1f}" font-size="10" fill="{MUT}" '
                 f'text-anchor="end">{esc(bnote)}</text>')

    # 曲线
    for kind in KINDS:
        if kind not in data:
            continue
        c, _ = COL[kind]
        vs = data[kind]
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vs))
        o.append(f'<path d="M{pts.replace(" ", " L")}" fill="none" stroke="{c}" '
                 f'stroke-width="2.2" stroke-linejoin="round"/>')
        for i, v in enumerate(vs):
            o.append(f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="4.2" fill="{c}" '
                     f'stroke="#FFFFFF" stroke-width="1.4"/>')

    # 横轴
    o.append(f'<path d="M{px} {py + ph:.1f} L{px + pw} {py + ph:.1f}" stroke="{BOR}" '
             f'stroke-width="1.2"/>')
    for i in range(nk + 1):
        o.append(f'<text x="{X(i):.1f}" y="{py + ph + 18:.1f}" font-size="11" '
                 f'fill="{MUT}" text-anchor="middle">{i}</text>')
    o.append(f'<text x="{px + pw / 2:.1f}" y="{py + ph + 36:.1f}" font-size="10.5" '
             f'fill="{MUT}" text-anchor="middle">已累积的历史任务数 k</text>')
    return o


def legend(y: int) -> list:
    o = []
    x = 596
    for kind in KINDS:
        c, name = COL[kind]
        o.append(f'<circle cx="{x}" cy="{y - 4}" r="4.2" fill="{c}"/>')
        o.append(f'<text x="{x + 10}" y="{y}" font-size="11.5" fill="{INK}">{esc(name)}</text>')
        x += 20 + len(name) * 13
    return o


def verdict(res: dict) -> list[str]:
    """把图上的读数直接翻译成句子——图单独拿出去也要能读懂。"""
    blind = res["blind"]["hits"]
    ks = res["kinds"]
    lines = [f"盲猜基线（什么都不给）：{blind}/4，"
             f"猜中的是 {'、'.join(n for n, ok in res['blind']['detail'].items() if ok) or '无'}。"
             f"所以命中数要明显高于 {blind} 才算推断。"]
    for kind in KINDS:
        if kind not in ks:
            continue
        row = ks[kind]
        hit = [r["hits_mean"] for r in row]
        resd = [r["residual_mean"] for r in row]
        lines.append(f"{COL[kind][1]}：残漏 {resd[0]:g} → {resd[-1]:g} 笔；"
                     f"推断 {hit[0]:g} → {hit[-1]:g} /4。")
    # 一句话结论：两个通道给出的答案相反
    sep = max(ks[k][-1]["residual_mean"] for k in ks) - min(ks[k][-1]["residual_mean"] for k in ks)
    spread = max(ks[k][-1]["hits_mean"] for k in ks) - min(ks[k][-1]["hits_mean"] for k in ks)
    lines.append("")
    lines.append(f"k=4 时残漏在四档间差 {sep:g} 笔，推断只差 {spread:g} 个属性 —— "
                 f"残漏能分开方法，属性推断不能。")
    lines.append("原因是这套属性饱和了：4 个里 2 个靠常识就能蒙，另 2 个靠任务本身的"
                 "合规披露就能拿到（Apple 在 T11、Spotify 在 T5），记忆再多也加不动。")
    return lines


def main() -> None:
    res = json.loads((RUNS / "infer_curve.json").read_text(encoding="utf-8"))
    ks = res["kinds"]

    hit = {k: [r["hits_mean"] for r in v] for k, v in ks.items()}
    resd = {k: [r["residual_mean"] for r in v] for k, v in ks.items()}

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
         f'width="{W}" height="{H}" font-family="-apple-system,BlinkMacSystemFont,'
         f'\'Segoe UI\',sans-serif">',
         f'<rect width="{W}" height="{H}" fill="#FAF9F6"/>',
         f'<text x="24" y="36" font-size="17" font-weight="600" fill="{INK}">'
         f'历史变长，隐私是怎么漏的：直接获取 vs 被推断</text>',
         f'<text x="24" y="58" font-size="11.5" fill="{MUT}">'
         f'同一条四任务链，只换记忆实现。k = 已经发生过几个任务。</text>']
    o += legend(52)

    o += panel(24, 78, 516, 348,
               "被推断：整户 4 个属性猜对几个",
               "虚线以上才算真从信息里推出来，虚线以下都是常识",
               hit, ymax=4, baseline=res["blind"]["hits"], bnote="盲猜基线")
    o += panel(560, 78, 516, 348,
               "直接获取：累计残漏（笔）",
               "该步并不需要、却反复出现的记录，越少越好",
               resd, ymax=6)

    o.append(f'<rect x="24" y="444" width="1052" height="{H - 444 - 28}" rx="10" '
             f'fill="#F1EFE8"/>')
    for i, line in enumerate(verdict(res)):
        o.append(f'<text x="42" y="{444 + 26 + i * 21}" font-size="11.5" '
                 f'fill="#5F5E5A">{esc(line)}</text>')
    o.append('</svg>')

    svg = "".join(o)
    (RUNS / "img").mkdir(parents=True, exist_ok=True)
    (RUNS / "img" / "infer_curve.html").write_text(svg, encoding="utf-8")
    p = shot(svg, RUNS / "img" / "infer_curve.png")
    print(f"-> {p}  ({p.stat().st_size // 1024} KB)")
    for line in verdict(res):
        if line:
            print("  " + line)


if __name__ == "__main__":
    main()
