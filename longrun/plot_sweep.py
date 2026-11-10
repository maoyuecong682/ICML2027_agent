"""把 sweep.json 画成频率-成本-召回曲线。

    python plot_sweep.py        # 读 runs/sweep.json，出 sweep.html + png

四条曲线同一横轴（记忆写入频率 mem_every）：
  左上 执行时间 t       ← 成本
  右上 输出 token        ← 成本
  左下 图记忆边数        ← 记忆密度
  右下 task_4 轮次       ← 召回质量的行为学代理（越少越好 = 一次就命中）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from xml.sax.saxutils import escape

sys.stdout.reconfigure(encoding="utf-8")

from config import RUNS  # noqa: E402
from shot import shot  # noqa: E402

W, H = 1100, 760
C_A = ("#185FA5", "#E6F1FB")     # task_1
C_B = ("#0F6E56", "#E1F5EE")     # task_4
C_MEM = ("#534AB7", "#EEEDFE")

INK, MUTED, GRID, PANEL = "#2C2C2A", "#888780", "#E8E6E0", "#FFFFFF"


def esc(s) -> str:
    return escape(str(s))


def axis_scale(maxv: float, integer=False):
    """把最大值抬到「好读」的刻度上：返回 (轴顶, 每格步长)，保证 4 格整除。"""
    import math
    if maxv <= 0:
        maxv = 1
    raw = maxv / 4
    e = math.floor(math.log10(raw))
    step = None
    for c in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        s = c * 10 ** e
        if integer:
            s = max(1.0, math.ceil(s))
        if s >= raw:
            step = s
            break
    if step is None:
        step = 10 ** (e + 1)
    if integer:
        step = float(max(1, round(step)))
    return step * 4, step


def fmt_tick(v: float, step: float) -> str:
    if step >= 1:
        return f"{v:,.0f}"
    return f"{v:.1f}"


def panel(x, y, w, h, title, sub, series, ylabel, invert_good=False):
    """series: [(label, color, [(level, value_str, value_num)], fill)]"""
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{PANEL}" '
           f'stroke="{GRID}" stroke-width="1"/>']
    out.append(f'<text x="{x + 18}" y="{y + 26}" font-size="13" font-weight="500" '
               f'fill="{INK}">{esc(title)}</text>')
    out.append(f'<text x="{x + 18}" y="{y + 44}" font-size="11" fill="{MUTED}">{esc(sub)}</text>')

    # 绘图区
    px, py = x + 62, y + 74
    pw, ph = w - 92, h - 116

    allv = [v for _, _, pts, _ in series for _, _, v in pts]
    integer = all(float(v).is_integer() for v in allv) if allv else False
    vmax, step_v = axis_scale(max(allv) if allv else 1, integer=integer)
    levels = [lv for lv, _, _ in series[0][2]] if series else []
    n = max(len(levels) - 1, 1)
    xstep = pw / n

    def X(i):
        return px + i * xstep

    def Y(v):
        return py + ph - (v / vmax) * ph

    # 网格 + y 轴刻度
    for k in range(5):
        gy = py + ph * k / 4
        val = vmax - step_v * k
        out.append(f'<path d="M{px} {gy:.0f} L{px + pw} {gy:.0f}" stroke="{GRID}" '
                   f'stroke-width="0.8" stroke-dasharray="{"" if k == 4 else "3 4"}"/>')
        out.append(f'<text x="{px - 10}" y="{gy + 4:.0f}" text-anchor="end" font-size="10" '
                   f'fill="{MUTED}">{fmt_tick(val, step_v)}</text>')

    # x 轴
    for i, lv in enumerate(levels):
        out.append(f'<text x="{X(i):.0f}" y="{py + ph + 22}" text-anchor="middle" font-size="11" '
                   f'fill="{INK}">{lv}</text>')
    out.append(f'<text x="{px + pw / 2}" y="{py + ph + 44}" text-anchor="middle" font-size="10.5" '
               f'fill="{MUTED}">mem_every（每 N 轮写一次记忆）</text>')

    # 折线
    for si, (label, color, pts, fill) in enumerate(series):
        d = " ".join(f'{"M" if i == 0 else "L"}{X(i):.0f} {Y(v):.0f}'
                     for i, (_, _, v) in enumerate(pts))
        out.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2.2" '
                   f'stroke-linejoin="round" stroke-linecap="round"/>')
        # 两条线数值接近时标签会撞：谁在上面就标上方、谁在下面就标下方，
        # 让同一点的两个标签往相反方向散开。
        for i, (_, s, v) in enumerate(pts):
            cx, cy = X(i), Y(v)
            tw = len(s) * 7 + 8
            up = True
            if len(series) > 1:
                j = 1 - si
                if j < len(series) and i < len(series[j][2]):
                    up = v >= series[j][2][i][2]
            dy = -12 if up else 20
            # 贴顶/贴底时换到另一侧，避免被面板边框裁掉
            if cy + dy - 11 < py + 2:
                dy = 20
            elif cy + dy + 4 > py + ph - 2:
                dy = -12
            # 首尾点居中会把标签伸出绘图区、压到刻度上，做一次夹取
            tx = min(max(cx, px + tw / 2), px + pw - tw / 2)
            out.append(f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="4.5" fill="#FFFFFF" '
                       f'stroke="{color}" stroke-width="2"/>')
            out.append(f'<rect x="{tx - tw / 2:.0f}" y="{cy + dy - 11:.0f}" width="{tw}" '
                       f'height="15" rx="3" fill="#FFFFFF" opacity="0.86"/>')
            out.append(f'<text x="{tx:.0f}" y="{cy + dy:.0f}" text-anchor="middle" '
                       f'font-size="11" font-weight="500" fill="{color}">{esc(s)}</text>')

    # 图例
    lx = x + w - 18
    for label, color, _, _ in reversed(series):
        tw = len(label) * 7 + 22
        lx -= tw
        out.append(f'<circle cx="{lx + 5}" cy="{y + 22}" r="3.5" fill="{color}"/>')
        out.append(f'<text x="{lx + 14}" y="{y + 26}" font-size="10.5" fill="{INK}">'
                   f'{esc(label)}</text>')
    return "".join(out)


def build_svg(res: list) -> str:
    rows = {}
    for lvl in res:
        for r in lvl["rows"]:
            rows.setdefault(r["task"], {})[r["mem_every"]] = r
    levels = sorted({lv["mem_every"] for lv in res})
    t1, t4 = rows.get("banking/user_task_1", {}), rows.get("banking/user_task_4", {})

    def ser(d, key, fmt):
        return [(lv, fmt(d[lv][key]), float(d[lv][key])) for lv in levels if lv in d]

    def ser2(da, db, ka, kb, fmt):
        """两条任务合成一组"""
        out_a = [(lv, fmt(da[lv][ka]), float(da[lv][ka])) for lv in levels if lv in da]
        out_b = [(lv, fmt(db[lv][kb]), float(db[lv][kb])) for lv in levels if lv in db]
        return out_a, out_b

    a_t, b_t = ser2(t1, t4, "t_s", "t_s", lambda v: f"{v:.0f}s")
    a_o, b_o = ser2(t1, t4, "tok_out", "tok_out", lambda v: f"{int(v)}")
    a_e, b_e = ser2(t1, t4, "graph_edges", "graph_edges", lambda v: f"{int(v)}")
    b_r = ser(t4, "rounds", lambda v: f"{int(v)}轮") if t4 else []

    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" '
           f'font-family="system-ui,-apple-system,Segoe UI,sans-serif">']

    # 标题区
    out.append(f'<text x="40" y="36" font-size="17" font-weight="500" fill="{INK}">'
               f'记忆写入频率 × 成本 × 召回质量</text>')
    out.append(f'<text x="40" y="58" font-size="11.5" fill="{MUTED}">'
               f'横轴 mem_every = 每 N 轮把对话压进 mem0 图记忆一次。'
               f'N=1 为基线。四个面板共用横轴：上排是代价，下排是收益与副作用。</text>')

    pw = (W - 80 - 24) / 2
    out.append(panel(40, 78, pw, 300,
          "执行时间 t", "单任务墙钟耗时（含 mem0 抽取的 LLM 往返）",
          [("task_1", C_A[0], a_t, C_A[1]), ("task_4", C_B[0], b_t, C_B[1])], "秒"))
    out.append(panel(40 + pw + 24, 78, pw, 300,
          "输出 token", "生成侧开销，是降频最直接省下的部分",
          [("task_1", C_A[0], a_o, C_A[1]), ("task_4", C_B[0], b_o, C_B[1])], "token"))
    out.append(panel(40, 396, pw, 300,
          "图记忆密度", "kuzu 图里的边数——降频的代价所在",
          [("task_1", C_A[0], a_e, C_A[1]), ("task_4", C_B[0], b_e, C_B[1])], "边数"))
    out.append(panel(40 + pw + 24, 396, pw, 300,
          "跨任务召回质量", "task_4 的轮次：一次就命中 = 2 轮；要重新问 A = 4 轮",
          [("task_4 轮次", C_MEM[0], b_r, C_MEM[1])] if b_r else [], "轮"))
    out.append("</svg>")
    return "".join(out)


def build_table(res: list) -> str:
    rows = []
    for lvl in res:
        for r in lvl["rows"]:
            ok = r["utility"] == 1 and r["strict"]
            tag = ('<span style="color:#3B6D11">pass</span>' if ok
                   else '<span style="color:#A32D2D">fail</span>')
            rows.append(
                f"<tr><td>{r['mem_every']}</td><td>{esc(r['task'])}</td><td>{tag}</td>"
                f"<td>{r['rounds']}</td><td>{r['calls']}</td>"
                f"<td>{r['tok_in']} / {r['tok_out']}</td>"
                f"<td>{r['t_s']} s</td><td>{r['mem_calls']} 次 / {r['mem_s']} s</td>"
                f"<td>{r['n_memories']} 条 · {r['graph_nodes']}/{r['graph_edges']}</td>"
                f"<td>{r['mem_json_bytes']} B</td>"
                f"<td>{'命中' if r['recall_hit'] else '未命中'}（{r['recall_n']} 条）</td></tr>")
    return (
        "<table><tr><th>mem_every</th><th>任务</th><th>结果</th><th>轮次</th><th>调用</th>"
        "<th>token in/out</th><th>t</th><th>mem0 开销</th><th>记忆量</th><th>记忆 JSON</th>"
        "<th>跨任务召回</th></tr>" + "".join(rows) + "</table>")


def conclusion(res: list) -> str:
    """自动生成一句话结论，避免手填数字。"""
    rows = {}
    for lvl in res:
        for r in lvl["rows"]:
            rows.setdefault(r["task"], {})[r["mem_every"]] = r
    levels = sorted({lv["mem_every"] for lv in res})
    if len(levels) < 2:
        return ""
    parts = []
    for task, d in rows.items():
        lo, hi = d.get(levels[0]), d.get(levels[-1])
        if not (lo and hi) or not lo["t_s"]:
            continue
        dt = (1 - hi["t_s"] / lo["t_s"]) * 100
        do = (1 - hi["tok_out"] / lo["tok_out"]) * 100 if lo["tok_out"] else 0
        parts.append(
            f"{task.split('/')[-1]}：N={levels[0]}→{levels[-1]}，时间 −{dt:.0f}%、"
            f"输出 token −{do:.0f}%、轮次 {lo['rounds']}→{hi['rounds']}、"
            f"图边 {lo['graph_edges']}→{hi['graph_edges']}")
    return "；".join(parts)


CSS = """
*{box-sizing:border-box}
body{margin:0;padding:28px 24px 60px;background:#FAFAF8;color:#2C2C2A;
 font:14px/1.6 system-ui,-apple-system,"Microsoft YaHei",sans-serif}
.wrap{max-width:1160px;margin:0 auto}
h1{font-size:20px;font-weight:500;margin:0 0 4px}
.sub{color:#5F5E5A;font-size:13px;margin-bottom:20px}
section{background:#fff;border:1px solid #E3E1DA;border-radius:12px;padding:16px 18px;margin-bottom:20px}
h2{font-size:15px;font-weight:500;margin:0 0 10px}
table{border-collapse:collapse;font-size:12px;width:100%}
td,th{border-bottom:1px solid #EFEEE9;padding:6px 9px;text-align:left;white-space:nowrap}
th{color:#5F5E5A;font-weight:500}
.note{font-size:12.5px;color:#3C3489;background:#EEEDFE;border-left:3px solid #534AB7;
 padding:10px 14px;border-radius:0 8px 8px 0;margin-top:14px}
"""


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else (RUNS / "sweep.json")
    data = json.loads(src.read_text(encoding="utf-8"))
    svg = build_svg(data)
    html = [
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
        "<title>记忆写入频率曲线</title>", f"<style>{CSS}</style></head><body><div class='wrap'>",
        "<h1>记忆写入频率曲线</h1>",
        "<div class='sub'>同一批 AgentDojo 任务，只改「每几轮写一次记忆」这一个变量；"
        "每档都用全新记忆库，档内两个任务串成记忆链。</div>",
        f"<section>{svg}</section>",
        "<section><h2>原始数据</h2>", build_table(data), "</section>",
    ]
    con = conclusion(data)
    if con:
        html.append(f"<div class='note'><b>曲线读法</b>：{esc(con)}</div>")
    html.append("</div></body></html>")
    out_html = RUNS / "sweep.html"
    out_html.write_text("".join(html), encoding="utf-8")
    p = shot(svg, RUNS / "img" / "sweep.png")
    print(f"  {p.name}  {p.stat().st_size // 1024} KB")
    print("HTML ->", out_html)


if __name__ == "__main__":
    main()
