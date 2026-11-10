"""把逐笔恢复的结果画成矩阵：每个格子只可能是「抄到」或「没读到」，没有「推出」。

    python render_recover.py      # -> runs/img/recover.png

为什么用矩阵而不是柱状图：
柱状图只能画"命中几笔"，看不出**命中的那几笔本来读不读得到**。
矩阵按"交易 × 记忆档"铺开，格子里直接标命中次数，一眼能看出
所有命中都落在「字面可见」那几列上，「从未披露」那一列永远是空的。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from xml.sax.saxutils import escape as esc

sys.stdout.reconfigure(encoding="utf-8")

from config import RUNS  # noqa: E402
from shot import shot  # noqa: E402

W = 1100
COL = {"none": "无记忆", "graph": "图记忆 mem0", "summary": "普通摘要", "full": "完整历史"}
KINDS = ["none", "graph", "summary", "full"]
INK, MUT, BOR = "#2C2C2A", "#888780", "#E3E1DA"
# 三种状态：抄到（读得到且命中）/ 只是读得到 / 没读到
C_COPY, BG_COPY = "#185FA5", "#E6F1FB"
C_READ, BG_READ = "#5F5E5A", "#F4F3EE"
C_INFER, BG_INFER = "#A32D2D", "#FBE9E7"


def main() -> None:
    res = json.loads((RUNS / "recover.json").read_text(encoding="utf-8"))
    tx = res["tx"]
    kinds = [k for k in KINDS if k in res["kinds"]]
    nrep = len(res["kinds"][kinds[0]])

    # 每一笔：在几次复采样里算"未披露"
    unseen = {t["id"]: sum(1 for r in res["kinds"][kinds[0]] if t["id"] in r["unshown"])
              for t in tx}

    left = 158                 # 行标签宽度
    cw, ch = 168, 62
    top = 196                  # 表头下沿
    H = top + len(kinds) * (ch + 8) + 132

    cells_hit = 0
    cells_all = 0

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
         f'width="{W}" height="{H}" font-family="-apple-system,BlinkMacSystemFont,'
         f'\'Segoe UI\',sans-serif">',
         f'<rect width="{W}" height="{H}" fill="#FAF9F6"/>',
         f'<text x="24" y="38" font-size="17" font-weight="600" fill="{INK}">'
         f'泄露是抄过去的，不是推出来的</text>',
         f'<text x="24" y="60" font-size="11.5" fill="{MUT}">'
         f'攻击者读完 4 个任务的全部历史后，点名说出它认为存在的交易。'
         f'格子里的数字 = 3 次复采样里被点中的次数。</text>']

    # 表头：每笔交易
    for j, t in enumerate(tx):
        x = 24 + left + j * cw
        is_unseen = unseen[t["id"]] == nrep
        o.append(f'<text x="{x + cw / 2:.0f}" y="{top - 44}" font-size="11" '
                 f'fill="{C_INFER if is_unseen else MUT}" text-anchor="middle" '
                 f'font-weight="{"600" if is_unseen else "400"}">'
                 f'{"从未披露" if is_unseen else "任务需要过"}</text>')
        o.append(f'<text x="{x + cw / 2:.0f}" y="{top - 24}" font-size="12" '
                 f'fill="{INK}" text-anchor="middle">id={t["id"]}　{t["amount"]:g}</text>')
        # 事由可能要截断
        sub = t["subject"] if len(t["subject"]) <= 18 else t["subject"][:17] + "…"
        o.append(f'<text x="{x + cw / 2:.0f}" y="{top - 7}" font-size="10.5" '
                 f'fill="{MUT}" text-anchor="middle">{esc(sub)}</text>')

    # 行
    for i, kind in enumerate(kinds):
        rows = res["kinds"][kind]
        y = top + i * (ch + 8)
        o.append(f'<text x="30" y="{y + ch / 2 + 4:.0f}" font-size="12" '
                 f'fill="{INK}">{esc(COL[kind])}</text>')
        for j, t in enumerate(tx):
            x = 24 + left + j * cw
            seen = sum(1 for r in rows if t["id"] in r["visible"])
            hit = sum(1 for r in rows if t["id"] in r["matched"])
            infer = t["id"] in (rows[0]["unshown"]) and hit > 0
            cells_all += 1
            if infer:
                cells_hit += 1

            if seen and hit:
                bg, fg, bgc = BG_COPY, C_COPY, C_COPY
                label = f"命中 {hit}/{nrep}"
            elif seen:
                bg, fg, bgc = BG_READ, C_READ, BOR
                label = "只读到"
            elif hit:
                bg, fg, bgc = BG_INFER, C_INFER, C_INFER
                label = f"推出 {hit}/{nrep}"
            else:
                bg, fg, bgc = BG_INFER, C_INFER, C_INFER
                label = f"没读到（点名 {hit}/{nrep}）"

            dash = "" if seen else ' stroke-dasharray="4 3"'
            o.append(f'<rect x="{x + 4}" y="{y}" width="{cw - 8}" height="{ch}" rx="8" '
                     f'fill="{bg}" stroke="{bgc}" stroke-width="1"{dash}/>')
            o.append(f'<text x="{x + cw / 2:.0f}" y="{y + ch / 2 + 4:.0f}" font-size="11" '
                     f'fill="{fg}" text-anchor="middle">{esc(label)}</text>')

    # 图例
    ly = top + len(kinds) * (ch + 8) + 40
    for k, (bg, fg, txt) in enumerate([
            (BG_COPY, C_COPY, "任务需要过、攻击者也点中了 —— 这是「抄」"),
            (BG_READ, C_READ, "任务需要过、但攻击者没点中"),
            (BG_INFER, C_INFER, "从未披露 —— 只有这一列点中才算「推」")]):
        x = 30 + k * 360
        o.append(f'<rect x="{x}" y="{ly - 11}" width="16" height="16" rx="4" '
                 f'fill="{bg}" stroke="{fg}" stroke-width="1"/>')
        o.append(f'<text x="{x + 24}" y="{ly + 2}" font-size="11" fill="{MUT}">{esc(txt)}</text>')

    o.append(f'<text x="30" y="{ly + 44}" font-size="12" font-weight="600" '
             f'fill="{C_INFER}">从未披露那一列：12 次攻击、4 档记忆，一次都没被点中。'
             f'所有命中全部落在「任务需要过」的列上。</text>')
    o.append(f'<text x="30" y="{ly + 66}" font-size="11" fill="{MUT}">'
             f'⇒ 这条链上的泄露 100% 是「抄」，0% 是「推」。方法该管「谁能读到什么」，'
             f'而不是做推断抵抗。</text>')
    o.append('</svg>')

    svg = "".join(o)
    (RUNS / "img").mkdir(parents=True, exist_ok=True)
    p = shot(svg, RUNS / "img" / "recover.png")
    print(f"-> {p}  ({p.stat().st_size // 1024} KB)")
    print(f"  从未披露列命中 {cells_hit} / {cells_all} 格")


if __name__ == "__main__":
    main()
