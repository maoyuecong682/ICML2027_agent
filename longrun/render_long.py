"""长程执行图可视化：锯齿交替的 A/B 轮次链 + 记忆层 + 指标。

    python render_long.py            # 读 runs/latest 的 json，出 html + png
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

sys.stdout.reconfigure(encoding="utf-8")

from config import RUNS  # noqa: E402
from shot import shot  # noqa: E402

W = 1100

C = {
    "a": ("#E6F1FB", "#185FA5", "#0C447C"),
    "b": ("#E1F5EE", "#0F6E56", "#04342C"),
    "mem": ("#EEEDFE", "#534AB7", "#3C3489"),
    "task": ("#F1EFE8", "#888780", "#2C2C2A"),
    "ok": ("#EAF3DE", "#3B6D11", "#173404"),
    "bad": ("#FCEBEB", "#A32D2D", "#501313"),
    "ink": ("#FFFFFF", "#B4B2A9", "#2C2C2A"),
}

SIG = {
    "need_info": ("#BA7517", "向 A 要字段"),
    "info_ready": ("#185FA5", "A 给出事实"),
    "executed": ("#3B6D11", "B 已写环境"),
    "verified": ("#27500A", "A 复核通过"),
    "done": ("#27500A", "B 给出答复"),
    "blocked": ("#A32D2D", "读不到"),
    "unknown": ("#888780", "未解析"),
}


def esc(s) -> str:
    return escape(str(s))


def _u(ch):
    return 1.0 if ord(ch) > 127 else 0.55


def fit(s, max_units):
    s = re.sub(r"\s+", " ", str(s).replace("\n", " ")).strip()
    out, u = [], 0.0
    for ch in s:
        cu = _u(ch)
        if u + cu > max_units:
            t = "".join(out).rstrip()
            return t if t.endswith("...") else re.sub(r"\.{3,}", "...", t + "...")
        out.append(ch)
        u += cu
    return "".join(out)


DEFS = ('<defs><marker id="ar" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" '
        'markerHeight="6" orient="auto-start-reverse"><path d="M2 1L8 5L2 9" fill="none" '
        'stroke="context-stroke" stroke-width="1.5" stroke-linecap="round" '
        'stroke-linejoin="round"/></marker></defs>')


def _chip(x, y, label, value, w=150, color="ink"):
    fill, stroke, txt = C[color]
    return "".join([
        f'<rect x="{x}" y="{y}" width="{w}" height="52" rx="8" fill="{fill}" '
        f'stroke="{stroke}" stroke-width="0.5"/>',
        f'<text x="{x + 12}" y="{y + 18}" font-size="11" fill="#888780">{esc(label)}</text>',
        f'<text x="{x + 12}" y="{y + 38}" font-size="14" font-weight="500" '
        f'fill="{txt}">{esc(value)}</text>',
    ])


def svg_task(run: dict) -> str:
    rounds = run["rounds"]
    n = max(len(rounds), 1)
    fp = run.get("footprint", {}).get("after", {})
    lg = run.get("ledger", {}).get("total", {})

    step = (1020 - 96) / max(n - 1, 1)
    nw = max(84, min(120, step - 14))
    xs = [40 + i * step for i in range(n)]
    y_top, y_bot = 196, 300

    H = 608
    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" '
           f'font-family="system-ui,-apple-system,Segoe UI,sans-serif">{DEFS}']

    # ---- 任务条
    out.append(f'<rect x="40" y="20" width="1020" height="60" rx="10" fill="{C["task"][0]}" '
               f'stroke="{C["task"][1]}" stroke-width="0.5"/>')
    out.append(f'<text x="58" y="44" font-size="13" font-weight="500" fill="#2C2C2A">'
               f'{esc(run["suite"])} / {esc(run["task_id"])}　'
               f'<tspan fill="#5F5E5A" font-weight="400">'
               f'{esc(run["difficulty"].replace("TaskDifficulty.", ""))}</tspan></text>')
    out.append(f'<text x="58" y="66" font-size="12" fill="#5F5E5A">'
               f'{esc(fit(run["prompt"], 96))}</text>')

    # ---- 指标
    ok = run["utility"] == 1
    cards = [
        ("是否完成", "utility = 1" if ok else "utility = 0", "ok" if ok else "bad"),
        ("轮次", f"{run['n_rounds']} 轮（A{run['a_turns']} / B{run['b_turns']}）", "ink"),
        ("token", f"{lg.get('in', 0)} in / {lg.get('out', 0)} out", "ink"),
        ("执行时间 t", f"{run['wall_ms'] / 1000:.1f} s", "ink"),
        ("记忆条目 / 图规模", f"{fp.get('n_memories', 0)} 条 · {fp.get('graph_nodes', 0)} 节点 · "
                             f"{fp.get('graph_edges', 0)} 边", "mem"),
        ("记忆占用", f"{fp.get('disk_bytes', 0) / 1024:.0f} KB", "mem"),
    ]
    cw = (1020 - 5 * 10) / 6
    for i, (lab, val, col) in enumerate(cards):
        out.append(_chip(40 + i * (cw + 10), 96, lab, fit(val, (cw - 22) / 7.2), cw, col))

    # ---- 锯齿链
    out.append(f'<text x="40" y="176" font-size="11" fill="#888780">'
               f'调用序列：上 = Agent A（只读 / 评估），下 = Agent B（执行 / 计算 / 写入）；'
               f'顺序由上一轮信号决定，没有预设流程</text>')

    for i, t in enumerate(rounds):
        is_a = t["actor"] == "A"
        y = y_top if is_a else y_bot
        x = xs[i]
        fill, stroke, txt = C["a" if is_a else "b"]
        sig = t["signal"]
        scol = SIG.get(sig, SIG["unknown"])[0]
        out.append(f'<rect x="{x:.0f}" y="{y}" width="{nw:.0f}" height="66" rx="9" '
                   f'fill="{fill}" stroke="{stroke}" stroke-width="0.9"/>')
        out.append(f'<text x="{x + 10:.0f}" y="{y + 20}" font-size="11" font-weight="500" '
                   f'fill="{txt}">r{t["round"]:02d} · {t["actor"]}</text>')
        out.append(f'<text x="{x + 10:.0f}" y="{y + 38}" font-size="11" fill="{scol}">'
                   f'{esc(sig)}</text>')
        tl = ", ".join(t["tools"]) or "无工具"
        out.append(f'<text x="{x + 10:.0f}" y="{y + 55}" font-size="10" fill="#5F5E5A">'
                   f'{esc(fit(tl, (nw - 18) / 9.6))}</text>')
        # 记忆写入：节点下方一行小字，不画框
        ops = [m for m in run["memory_ops"]
               if m.get("op") == "add" and m.get("round") == t["round"]]
        if ops:
            ev = len(ops[0].get("events") or [])
            nm = ops[0].get("n_memories", 0)
            out.append(f'<path d="M{x + nw / 2:.0f} {y + 66} L{x + nw / 2:.0f} {y + 84}" '
                       f'stroke="#B4B2A9" stroke-width="0.7" stroke-dasharray="2 3"/>')
            out.append(f'<text x="{x + nw / 2:.0f}" y="{y + 96}" text-anchor="middle" '
                       f'font-size="9.5" fill="#534AB7">+{ev}条 → 共{nm}条</text>')

    # 轮次之间的连线（颜色 = 发起方的信号）
    for i in range(n - 1):
        x1 = xs[i] + nw
        x2 = xs[i + 1]
        y1 = (y_top if rounds[i]["actor"] == "A" else y_bot) + 33
        y2 = (y_top if rounds[i + 1]["actor"] == "A" else y_bot) + 33
        col = SIG.get(rounds[i]["signal"], SIG["unknown"])[0]
        out.append(f'<path d="M{x1 + 1:.0f} {y1} L{x2 - 3:.0f} {y2}" fill="none" stroke="{col}" '
                   f'stroke-width="1.2" marker-end="url(#ar)" opacity="0.85"/>')
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        lab = rounds[i]["signal"]
        wl = len(lab) * 5.6 + 8
        out.append(f'<rect x="{mx - wl / 2:.0f}" y="{my - 8}" width="{wl:.0f}" height="14" '
                   f'rx="3" fill="#FFFFFF" opacity="0.92"/>')
        out.append(f'<text x="{mx:.0f}" y="{my + 2}" text-anchor="middle" font-size="9.5" '
                   f'fill="{col}">{esc(lab)}</text>')

    # ---- 记忆汇总（一行文字，不画大框）
    out.append(f'<text x="40" y="432" font-size="11" font-weight="500" fill="#3C3489">'
               f'mem0 图记忆（kuzu 嵌入式）· 每轮写入后由 LLM 抽实体-关系并合并去重</text>')
    out.append(f'<text x="40" y="450" font-size="11" fill="#534AB7">'
               f'原文累计 {fp.get("raw_text_bytes", 0)} B → 记忆 {fp.get("n_memories", 0)} 条'
               f'（JSON {fp.get("mem_json_bytes", 0)} B）· 图 {fp.get("graph_nodes", 0)} 节点 / '
               f'{fp.get("graph_edges", 0)} 边 · 落盘 {fp.get("disk_bytes", 0) / 1024:.0f} KB'
               f'（kuzu {fp.get("disk_kuzu_bytes", 0) / 1024:.0f} + '
               f'qdrant {fp.get("disk_qdrant_bytes", 0) / 1024:.0f}）</text>')

    # ---- token 分项
    by = run.get("ledger", {}).get("by_tag", {})
    out.append(f'<text x="40" y="478" font-size="11" fill="#888780">'
               f'消耗分项（token / 调用次数 / LLM 耗时）</text>')
    names = {"agent_a": "Agent A 对话", "agent_b": "Agent B 对话",
             "mem0_search": "mem0 检索", "mem0_add": "mem0 写入（实体/关系抽取）",
             "other": "未归因"}
    rows = [(names.get(k, k), v) for k, v in by.items()]
    rows.sort(key=lambda kv: -kv[1]["in"])
    bw = (1020 - 3 * 10) / max(len(rows), 1)
    for i, (nm, v) in enumerate(rows):
        x = 40 + i * (bw + 10)
        col = "a" if nm.startswith("Agent A") else ("b" if nm.startswith("Agent B") else "mem")
        fill, stroke, txt = C[col]
        out.append(f'<rect x="{x:.0f}" y="488" width="{bw:.0f}" height="58" rx="8" fill="{fill}" '
                   f'stroke="{stroke}" stroke-width="0.5"/>')
        out.append(f'<text x="{x + 10:.0f}" y="506" font-size="11" fill="{stroke}">'
                   f'{esc(fit(nm, (bw - 20) / 6))}</text>')
        out.append(f'<text x="{x + 10:.0f}" y="524" font-size="12" font-weight="500" fill="{txt}">'
                   f'{v["in"]} in / {v["out"]} out</text>')
        out.append(f'<text x="{x + 10:.0f}" y="539" font-size="10" fill="{stroke}">'
                   f'{v["calls"]} 次调用 · {v["ms"] / 1000:.1f}s</text>')

    # ---- 环境变化
    note = "；".join(run.get("env_detail") or []) or "环境未改变（纯答复型任务）"
    out.append(f'<text x="40" y="572" font-size="11" fill="#5F5E5A">环境终态：'
               f'{esc(fit(note, 110))}</text>')
    out.append(f'<text x="40" y="592" font-size="11" fill="#888780">'
               f'model={esc(run["model"])} · 越权拦截 {len(run.get("denied") or [])} 次 · '
               f'记忆读写 {len(run.get("memory_ops") or [])} 次</text>')
    out.append("</svg>")
    return "".join(out)


CSS = """
*{box-sizing:border-box}
body{margin:0;padding:28px 24px 60px;background:#FAFAF8;color:#2C2C2A;
 font:14px/1.6 system-ui,-apple-system,"Microsoft YaHei",sans-serif}
.wrap{max-width:1160px;margin:0 auto}
h1{font-size:20px;font-weight:500;margin:0 0 4px}
.sub{color:#5F5E5A;font-size:13px;margin-bottom:22px}
section{background:#fff;border:1px solid #E3E1DA;border-radius:12px;padding:18px 20px;margin-bottom:22px}
h2{font-size:15px;font-weight:500;margin:0 0 10px}
table{border-collapse:collapse;font-size:12px;width:100%}
td,th{border-bottom:1px solid #EFEEE9;padding:6px 10px;text-align:left}
th{color:#5F5E5A;font-weight:500}
td.mono{font-family:ui-monospace,Consolas,monospace;font-size:11px;color:#444441}
"""


def build_html(data: dict) -> str:
    runs = data["tasks"]
    parts = [
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
        "<title>长程双智能体执行图</title>", f"<style>{CSS}</style></head><body><div class='wrap'>",
        "<h1>长程双智能体 · 执行图</h1>",
        f"<div class='sub'>Agent A（只读 / 评估）与 Agent B（执行 / 计算 / 写入）反复交替，"
        f"每轮结束后由 mem0 把该轮压进 kuzu 图记忆；下一轮的上下文由「图记忆检索 + 最近 k 轮」组成，"
        f"不重放全历史。run={esc(data.get('run_tag', ''))}，"
        f"记忆库 {esc(data.get('mem_root', ''))}。</div>",
    ]
    for run in runs:
        parts.append("<section>")
        parts.append(f"<h2>{esc(run['suite'])} · {esc(run['task_id'])}</h2>")
        parts.append(svg_task(run))
        rows = "".join(
            f'<tr><td>r{t["round"]:02d}</td><td>{esc(t["actor"])}</td>'
            f'<td>{esc(t["signal"])}</td><td class="mono">{esc(", ".join(t["tools"]) or "—")}</td>'
            f'<td>{esc(fit(t["summary"], 70))}</td></tr>'
            for t in run["rounds"])
        parts.append("<table><tr><th>轮次</th><th>agent</th><th>信号</th><th>工具</th>"
                     f"<th>这一轮做了什么</th></tr>{rows}</table>")
        parts.append("</section>")
    parts.append("</div></body></html>")
    return "".join(parts)


def main():
    tag = (RUNS / "latest.txt").read_text(encoding="utf-8").strip()
    data = json.loads((RUNS / f"longrun_{tag}.json").read_text(encoding="utf-8"))
    html = build_html(data)
    (RUNS / "graphs.html").write_text(html, encoding="utf-8")
    img = RUNS / "img"
    for run in data["tasks"]:
        p = shot(svg_task(run), img / f"{run['suite']}_{run['task_id']}_long.png")
        print(f"  {p.name}  {p.stat().st_size // 1024} KB")
    # 有/无记忆对照图
    nomem = sorted(RUNS.glob("longrun_*_nomem.json"))
    for f in nomem:
        d2 = json.loads(f.read_text(encoding="utf-8"))
        for run in d2["tasks"]:
            p = shot(svg_task(run), img / f"{run['suite']}_{run['task_id']}_nomem.png")
            print(f"  {p.name}  {p.stat().st_size // 1024} KB")
    print("HTML ->", RUNS / "graphs.html")


if __name__ == "__main__":
    main()
