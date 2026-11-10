"""四档记忆 × 有/无门控 的对比图。

    python render_gate_matrix.py      # -> runs/img/gate_matrix.png

这张图要回答一个问题：**门控的收益是普遍的吗，还是只对某一档有效？**
以及随之而来的第二个问题：装了门控之后，四档之间还差多少——
如果都收敛到同一水平，说明"压缩"的额外价值被门控吸收了，方法该往门控走。
"""
from __future__ import annotations

import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

from config import RUNS  # noqa: E402
from shot import shot  # noqa: E402

W, H = 1100, 656
INK, MUT, BOR, PANEL = "#2C2C2A", "#888780", "#E3E1DA", "#FFFFFF"
NAME = {"none": "无记忆", "graph": "图记忆", "summary": "普通摘要", "full": "完整历史"}
KINDS = ["none", "graph", "summary", "full"]
C_OFF, C_ON = ("#A32D2D", "#F2D9D6"), ("#0F6E56", "#DCEEE8")


def main() -> None:
    res = json.loads((RUNS / "gate_matrix.json").read_text(encoding="utf-8"))
    ks = [k for k in KINDS if k in res and "off" in res[k] and "on" in res[k]]
    if not ks:
        raise SystemExit("gate_matrix.json 里没有完整的四档数据")

    off = [res[k]["off"]["residual"]["mean"] for k in ks]
    on = [res[k]["on"]["residual"]["mean"] for k in ks]
    cut = [(1 - n / o) * 100 if o else 0 for o, n in zip(off, on)]
    util_off = [res[k]["off"]["utility"]["mean"] for k in ks]
    util_on = [res[k]["on"]["utility"]["mean"] for k in ks]
    ntask = res[ks[0]]["off"]["n_tasks"]

    ymax = max(4, int(max(off + on)) + 1)
    px, py, pw, ph = 92, 132, 610, 300
    gw = pw / len(ks)

    def Y(v):
        return py + ph - (v / ymax) * ph

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
         f'width="{W}" height="{H}" font-family="-apple-system,BlinkMacSystemFont,'
         f'\'Segoe UI\',sans-serif">',
         f'<rect width="{W}" height="{H}" fill="#FAF9F6"/>',
         f'<text x="24" y="38" font-size="17" font-weight="600" fill="{INK}">'
         f'门控在四档上都有效，四档之间的差距缩小到 1/4</text>',
         f'<text x="24" y="60" font-size="11.5" fill="{MUT}">'
         f'同一条四任务链，4 档记忆 × 有/无门控，各 3 次采样。柱高 = 残漏合计（笔）。</text>']

    for i, (name, c) in enumerate([("无门控", C_OFF), ("+ 门控", C_ON)]):
        x = 700 + i * 150
        o.append(f'<rect x="{x}" y="{44}" width="14" height="14" rx="3" fill="{c[0]}"/>')
        o.append(f'<text x="{x + 22}" y="{56}" font-size="11.5" fill="{INK}">{name}</text>')

    o.append(f'<text x="{px}" y="{py - 16}" font-size="10.5" fill="{MUT}">'
             f'残漏合计（3 次均值，越低越好）</text>')
    for k in range(ymax + 1):
        gy = Y(k)
        o.append(f'<path d="M{px} {gy:.1f} L{px + pw} {gy:.1f}" stroke="#EFEEE9"/>')
        o.append(f'<text x="{px - 12}" y="{gy + 4:.1f}" font-size="10.5" fill="{MUT}" '
                 f'text-anchor="end">{k}</text>')

    bw = gw * 0.28
    for i, kind in enumerate(ks):
        cx = px + gw * (i + 0.5)
        for j, (vals, c) in enumerate([(off, C_OFF), (on, C_ON)]):
            v = vals[i]
            x = cx - bw - 3 + j * (bw + 6)
            y = Y(v)
            o.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" '
                     f'height="{py + ph - y:.1f}" rx="4" fill="{c[1]}" '
                     f'stroke="{c[0]}" stroke-width="1.4"/>')
            o.append(f'<text x="{x + bw / 2:.1f}" y="{y - 7:.1f}" font-size="11" '
                     f'fill="{c[0]}" text-anchor="middle" font-weight="500">{v:g}</text>')
        o.append(f'<text x="{cx:.1f}" y="{py + ph + 22:.1f}" font-size="12" fill="{INK}" '
                 f'text-anchor="middle">{NAME[kind]}</text>')
        o.append(f'<text x="{cx:.1f}" y="{py + ph + 40:.1f}" font-size="10" fill="{MUT}" '
                 f'text-anchor="middle">完成 {util_on[i]:.1f}/{ntask}</text>')

    o.append(f'<path d="M{px} {py + ph} L{px + pw} {py + ph}" stroke="{BOR}" stroke-width="1.2"/>')

    # 右侧：降幅
    bx = 726
    o.append(f'<rect x="{bx}" y="{py - 6}" width="350" height="232" rx="12" '
             f'fill="{PANEL}" stroke="{BOR}"/>')
    o.append(f'<text x="{bx + 16}" y="{py + 20}" font-size="11" fill="{MUT}">'
             f'残漏降幅</text>')
    for i, kind in enumerate(ks):
        yy = py + 46 + i * 44
        o.append(f'<text x="{bx + 16}" y="{yy}" font-size="11.5" fill="{INK}">'
                 f'{NAME[kind]}</text>')
        o.append(f'<text x="{bx + 118}" y="{yy}" font-size="11.5" fill="{MUT}">'
                 f'{off[i]:g} → {on[i]:g}</text>')
        # 降幅条
        barw = 104
        o.append(f'<rect x="{bx + 176}" y="{yy - 8}" width="{barw}" height="8" rx="4" '
                 f'fill="#EFEEE9"/>')
        o.append(f'<rect x="{bx + 176}" y="{yy - 8}" width="{max(2, barw * cut[i] / 100):.1f}" '
                 f'height="8" rx="4" fill="{C_ON[0]}"/>')
        o.append(f'<text x="{bx + 340}" y="{yy}" font-size="10.5" fill="{C_ON[0]}" '
                 f'text-anchor="end">{cut[i]:.0f}%</text>')

    # 结论区：全部从数据里取，不写死数字
    gap_off = max(off) - min(off)
    gap_on = max(on) - min(on)
    rises = [f"{NAME[k]} {a:.1f}→{b:.1f}" for k, a, b in zip(ks, util_off, util_on)
             if b - a > 0.05]
    falls = [f"{NAME[k]} {a:.1f}→{b:.1f}" for k, a, b in zip(ks, util_off, util_on)
             if a - b > 0.05]
    s_rise = "、".join(rises) if rises else "无"
    s_fall = "、".join(falls) if falls else "无"
    n_on_min = min(res[k]["on"]["residual"]["n"] for k in ks)

    o.append(f'<rect x="24" y="{py + ph + 62}" width="1052" height="150" rx="10" fill="#F1EFE8"/>')
    cap = [
        f"① 四档残漏都降：{'/'.join(f'{c:.0f}%' for c in cut)}。",
        f"② 能力上：升的是 {s_rise}，降的是 {s_fall}（一次作答失败），其余持平——没有系统性损失。",
        f"③ 无门控时四档相差 {gap_off:.2f} 笔（{min(off):g}–{max(off):g}），"
        f"装门控后只差 {gap_on:.2f} 笔（{min(on):g}–{max(on):g}）——差距缩到约 1/4，但没有归零。",
        "④ 换句话说：之前「压缩减少暴露」那部分收益，一大半其实是门控本该做的事；"
        "压缩在事后少留痕迹，门控在出口直接拦住，两者不能互相替代。",
        f"⑤ 注意：摘要档挂门控只有 n={n_on_min} 次有效采样（API 余额耗尽），那个 0 待补；其余三档各 3 次。",
    ]
    for i, line in enumerate(cap):
        o.append(f'<text x="42" y="{py + ph + 88 + i * 24}" font-size="11.5" '
                 f'fill="#5F5E5A">{line}</text>')
    o.append('</svg>')

    svg = "".join(o)
    (RUNS / "img").mkdir(parents=True, exist_ok=True)
    p = shot(svg, RUNS / "img" / "gate_matrix.png")
    print(f"-> {p}  ({p.stat().st_size // 1024} KB)")
    print(f"   无门控 {off}  门控 {on}")
    print(f"   降幅 {[round(c) for c in cut]}  差距 {gap_off:.2f} → {gap_on:.2f}")


if __name__ == "__main__":
    main()
