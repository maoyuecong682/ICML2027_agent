"""双 agent 分工版渲染：agent 只画一个框，用 agent ↔ 命题 的箭头表示信息流通。"""
from __future__ import annotations

import re
from xml.sax.saxutils import escape

W = 1100

C = {
    "task": ("#F1EFE8", "#888780", "#2C2C2A"),
    "a": ("#E6F1FB", "#185FA5", "#0C447C"),
    "b": ("#E1F5EE", "#0F6E56", "#04342C"),
    "prop": ("#FAEEDA", "#BA7517", "#412402"),
    "env": ("#EEEDFE", "#534AB7", "#3C3489"),
    "util": ("#EAF3DE", "#3B6D11", "#173404"),
    "rec": ("#FBEAF0", "#993556", "#4B1528"),
    "priv": ("#E1F5EE", "#0F6E56", "#04342C"),
}

EDGE = {
    "recorded": ("#185FA5", ""),
    "explicit": ("#BA7517", ""),
    "implicit": ("#A32D2D", ' stroke-dasharray="5 4"'),
}


def esc(s) -> str:
    return escape(str(s))


def clip(s, n):
    import re
    s = re.sub(r"[*_`#>]+", "", str(s).replace("\n", " "))
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 3] + "..."


def _units(ch):
    return 1.0 if ord(ch) > 127 else 0.55


def fit(s, max_units):
    """按可视宽度裁剪：全角算 1 个单位，半角算 0.55。"""
    s = clip(s, 10 ** 6)
    out, u = [], 0.0
    for ch in s:
        cu = _units(ch)
        if u + cu > max_units:
            t = "".join(out).rstrip()
            return t if t.endswith("...") else re.sub(r"\.{3,}", "...", t + "...")
        out.append(ch)
        u += cu
    return "".join(out)


def _uw(s):
    return sum(_units(c) for c in s)


def wrap_fit(s, max_units, lines=2):
    """按可视宽度折行：优先在空格处断，中文逐字断；超出行数才截断。"""
    s = clip(s, 10 ** 6)
    out, cur = [], ""
    for word in s.split(" "):
        cand = (cur + " " + word).strip() if cur else word
        if _uw(cand) <= max_units:
            cur = cand
            continue
        if cur:
            out.append(cur)
            cur = ""
            if len(out) == lines:
                break
            cand = word
        # 单个词本身超长：硬切
        while _uw(cand) > max_units and len(out) < lines:
            cut, u = "", 0.0
            for ch in cand:
                if u + _units(ch) > max_units:
                    break
                cut, u = cut + ch, u + _units(ch)
            out.append(cut)
            cand = cand[len(cut):]
        cur = cand
        if len(out) == lines:
            break
    if cur and len(out) < lines:
        out.append(cur)
    if len(out) > lines or (cur and len(out) >= lines and cur not in out):
        pass
    out = out[:lines]
    # 若原文未被完整容纳，末行加省略号
    joined = "".join(x.strip() for x in out).replace(" ", "")
    if joined != s.replace(" ", ""):
        last = out[-1].rstrip()
        if not last.endswith("..."):
            out[-1] = (last[:-3] + "..." if _uw(last + "...") > max_units else last + "...")
        out[-1] = re.sub(r"\.{3,}", "...", out[-1])
    return out


def _box(x, y, w, h, color, title, subs, dashed=False, r=8, title_size=13.5):
    fill, stroke, txt = C[color]
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" '
           f'stroke="{stroke}" stroke-width="0.9"{dash}/>']
    subs = [fit(s, (w - 26) / 11.5) for s in subs if str(s).strip()]
    cy = y + 22 if len(subs) else y + h / 2
    ttl = fit(title, (w - 20) / (title_size * 0.92))
    out.append(f'<text x="{x + w / 2}" y="{cy}" text-anchor="middle" '
               f'dominant-baseline="central" font-size="{title_size}" font-weight="500" '
               f'fill="{txt}">{esc(ttl)}</text>')
    for i, s2 in enumerate(subs):
        out.append(f'<text x="{x + w / 2}" y="{cy + 19 + i * 16}" text-anchor="middle" '
                   f'dominant-baseline="central" font-size="11.5" fill="{stroke}">{esc(s2)}</text>')
    return "".join(out)


def _arrow(x1, y1, x2, y2, color="#5F5E5A", dash="", label=None, lpos=0.5, lsize=10.5,
           marker="ard"):
    out = [f'<path d="M{x1} {y1} L{x2} {y2}" fill="none" stroke="{color}" stroke-width="1.4"'
           f'{dash} marker-end="url(#{marker})"/>']
    if label:
        lx = x1 + (x2 - x1) * lpos
        ly = y1 + (y2 - y1) * lpos
        wl = len(label) * 5.6 + 10
        out.append(f'<rect x="{lx - wl / 2}" y="{ly - 10}" width="{wl}" height="15" rx="3" '
                   f'fill="#FFFFFF" opacity="0.93"/>')
        out.append(f'<text x="{lx}" y="{ly + 1.5}" text-anchor="middle" font-size="{lsize}" '
                   f'fill="{color}">{esc(label)}</text>')
    return "".join(out)


DEFS = ('<defs><marker id="ard" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" '
        'markerHeight="6" orient="auto-start-reverse"><path d="M2 1L8 5L2 9" fill="none" '
        'stroke="context-stroke" stroke-width="1.5" stroke-linecap="round" '
        'stroke-linejoin="round"/></marker></defs>')


def svg_exec(run: dict) -> str:
    """两路信息汇入 B：左路由 A 读数产生，右路是 B 的私有上下文。"""
    props = run["propositions"]
    priv = (run.get("private_context") or "").strip()
    n_props = len(props)
    n_priv = 1 if priv else 0
    toggle = run["env_changed"]
    uti_bottom = 514
    props_bottom = 130 + n_props * 77 - 15
    H = max(props_bottom, uti_bottom) + 28

    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" '
           f'font-family="system-ui,-apple-system,Segoe UI,sans-serif">{DEFS}']
    hdr = [("109", "任务"), ("420", "命题（A 侧读数）")]
    if n_priv:
        hdr.append(("975", "B 私有（A 不可见）"))
    hdr.append(("740", "环境与判定"))
    for x, t in hdr:
        out.append(f'<text x="{x}" y="18" text-anchor="middle" font-size="11.5" '
                   f'fill="#888780">{t}</text>')

    out.append(_box(24, 26, 176, 76, "task", run["task_id"],
                    wrap_fit(run["prompt"], (176 - 26) / 11.5, 2)))
    out.append(_arrow(109, 102, 109, 128))

    na, nb = len(run["tools"]["A"]), len(run["tools"]["B"])
    out.append(_box(24, 130, 160, 170, "a", "Agent A",
                    ["读取 / 评估", f"{na} 个只读工具", "不修改环境"], title_size=13))
    out.append(_box(660, 130, 160, 170, "b", "Agent B",
                    ["执行 / 计算 / 写入", f"{nb} 个写入工具", "两半信息交叉核对"], title_size=13))

    for i, pv in enumerate(props):
        py = 130 + i * 77
        if pv["kind"] == "data":
            title = f'{pv["id"]}  {pv["via"]}'
        elif pv["kind"] == "conclusion":
            title = f'{pv["id"]}  A 的判断'
        else:
            title = pv["id"]
        out.append(_box(230, py, 380, 62, "prop", title, [clip(pv["text"], 52)], r=6,
                        title_size=12.5))
        out.append(_arrow(186, 215, 228, py + 31, color="#185FA5"))
        out.append(_arrow(612, py + 31, 658, 215, color="#0F6E56"))

    if n_priv:
        out.append(_box(860, 130, 230, 76, "priv", "B 私有上下文",
                        wrap_fit(priv, (230 - 26) / 11.5, 2), r=6, title_size=12.5))
        out.append(_arrow(858, 168, 824, 200, color="#0F6E56"))
        out.append(f'<text x="975" y="222" text-anchor="middle" font-size="10.5" '
                   f'fill="#0F6E56">A 看不到这一半</text>')

    if toggle:
        wtool = run["writes"][0]["tool"] if run.get("writes") else "写入"
        out.append(_arrow(740, 302, 740, 336, label=wtool))
        lab = "；".join(run["env_detail"]) or "env 已变更"
        out.append(_box(660, 340, 160, 80, "env", "环境终态", [clip(lab, 22)], title_size=12.5))
        out.append(_arrow(740, 422, 740, 456))
    else:
        out.append(_arrow(740, 302, 740, 336, color="#B4B2A9", dash=' stroke-dasharray="5 4"'))
        out.append(_box(660, 340, 160, 80, "env", "环境未改变",
                        ["B 只计算，不落盘"], dashed=True, title_size=12.5))
        out.append(_arrow(740, 422, 740, 456, color="#B4B2A9", dash=' stroke-dasharray="5 4"'))

    out.append(_box(660, 460, 160, 54, "util", f"utility = {run['utility']}", []))
    out.append("</svg>")
    return "".join(out)


ROW_H = 78
CARD_H = 54
CHIP_H = 36


def _chip(cx, cw, y, name, tag, color, dash, txt, fill):
    """一个接收者 chip。文字按可视宽度裁剪，保证不出框。"""
    name = fit(name, (cw - 16) / 11.0)
    return "".join([
        f'<rect x="{cx:.0f}" y="{y}" width="{cw:.0f}" height="{CHIP_H}" rx="6" '
        f'fill="{fill}" stroke="{color}" stroke-width="0.9"{dash}/>',
        f'<text x="{cx + 8:.0f}" y="{y + 15}" font-size="10.5" font-weight="500" '
        f'fill="{txt}">{esc(name)}</text>',
        f'<text x="{cx + 8:.0f}" y="{y + 29}" font-size="9.5" fill="{color}">{esc(tag)}</text>',
    ])


def svg_privacy(pg: dict) -> str:
    """逐行展开：一个敏感命题一行，右侧按接收者挂 chip，箭头走顶部总线再落到 chip 上。"""
    props, recvs = pg["props"], pg["receivers"]
    rows_y = [134 + i * ROW_H for i in range(len(props))]
    H = (rows_y[-1] if rows_y else 134) + CARD_H - 6 + 30

    # 全图统一列宽：让不同命题行的接收者列对齐成网格
    k_max = max([len(p["to"]) + (1 if p.get("private") else 0) for p in props] + [1])
    room = 1052 - 466
    cw_all = min(190.0, (room - (k_max - 1) * 10) / k_max)

    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" '
           f'font-family="system-ui,-apple-system,Segoe UI,sans-serif">{DEFS}']
    out.append('<text x="130" y="18" text-anchor="middle" font-size="11.5" fill="#888780">信息主体</text>')
    out.append('<text x="230" y="18" text-anchor="middle" font-size="11.5" fill="#888780">敏感命题</text>')
    out.append('<text x="770" y="18" text-anchor="middle" font-size="11.5" fill="#888780">'
               '接收者（箭头表示这条命题被谁知道了）</text>')
    out.append(_box(30, 26, 200, 64, "a", "用户", [pg["subject"]], title_size=12.5))

    last_mid = (rows_y[-1] + CARD_H / 2) if rows_y else 90
    out.append(f'<path d="M16 {90} L16 {last_mid:.0f}" fill="none" stroke="#B4B2A9" stroke-width="1" '
               f'stroke-dasharray="3 3"/>')

    for i, pv in enumerate(props):
        y = rows_y[i]
        out.append(f'<path d="M16 {y + CARD_H / 2:.0f} L28 {y + CARD_H / 2:.0f}" fill="none" '
                   f'stroke="#B4B2A9" stroke-width="1" stroke-dasharray="3 3"/>')
        pc = "priv" if pv.get("private") else "prop"
        out.append(_box(30, y, 380, CARD_H, pc, pv["name"], [clip(pv["value"], 52)], r=6,
                        title_size=12.5))

        targets = [t for t in pv["to"] if any(x["id"] == t["recv"] for x in recvs)]
        blind = bool(pv.get("private"))  # 私有分片：先画一个「A 不可见」的空位
        k = max(len(targets) + (1 if blind else 0), 1)
        cw = cw_all
        bus = y - 8
        if targets or blind:
            span_r = 466 + (k - 1) * (cw + 10) + cw - 1
            out.append(f'<path d="M412 {y + CARD_H / 2:.0f} L446 {y + CARD_H / 2:.0f} L446 {bus}" '
                       f'fill="none" stroke="#B4B2A9" stroke-width="1.1"/>')
            out.append(f'<path d="M446 {bus} L{span_r:.0f} {bus}" fill="none" '
                       f'stroke="#B4B2A9" stroke-width="1.1"/>')

        cy = y + 4
        if blind:
            out.append(_chip(466, cw, cy, "Agent A", "不可见（分片外）", "#B4B2A9",
                             ' stroke-dasharray="3 3"', "#888780", "#FAFAF8"))
        for j, t in enumerate(targets):
            cx = 466 + (j + (1 if blind else 0)) * (cw + 10)
            color, dash = EDGE["recorded" if t["recorded"] else t["mode"]]
            out.append(f'<path d="M{cx + cw / 2:.0f} {bus} L{cx + cw / 2:.0f} {cy - 2}" fill="none" '
                       f'stroke="{color}" stroke-width="1.3" marker-end="url(#ard)"/>')
            fill, stroke, txt = C["rec"]
            tag = "已记录" if t["recorded"] else ("隐式" if t["mode"] == "implicit" else "未记录")
            r = next(x for x in recvs if x["id"] == t["recv"])
            out.append(_chip(cx, cw, cy, r["name"], tag, color, dash, txt, fill))
    out.append("</svg>")
    return "".join(out)


CSS = """
:root{--bd:#E3E1DA;--mut:#5F5E5A;--ink:#2C2C2A}
*{box-sizing:border-box}
body{margin:0;padding:30px 26px 60px;background:#FAFAF8;color:var(--ink);
 font:14px/1.6 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:1160px;margin:0 auto}
h1{font-size:20px;font-weight:600;margin:0 0 6px}
.sub{color:var(--mut);font-size:13px;margin-bottom:26px}
section{background:#fff;border:1px solid var(--bd);border-radius:12px;padding:20px 22px;margin-bottom:24px}
h2{font-size:16px;font-weight:600;margin:0 0 4px}
h3{font-size:13.5px;font-weight:600;margin:22px 0 8px;color:#3C3489}
.path{font-family:ui-monospace,Consolas,monospace;font-size:12px;color:#185FA5}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0 14px}
.chip{background:#F1EFE8;border-radius:999px;padding:3px 11px;font-size:12px;color:#444441}
.chip b{font-weight:600;color:#2C2C2A}
.chip.ok{background:#EAF3DE;color:#173404}
.chip.bad{background:#FCEBEB;color:#791F1F}
.split{display:flex;gap:10px;flex-wrap:wrap;margin:10px 0 4px;font-size:12px}
.tag{background:#E6F1FB;color:#0C447C;border-radius:6px;padding:3px 9px}
.tag.b{background:#E1F5EE;color:#04342C}
.note{font-size:12.5px;color:var(--mut);margin-top:10px;padding-left:13px;border-left:2px solid var(--bd)}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--mut);margin-top:8px}
.dot{display:inline-block;width:16px;height:2px;vertical-align:middle;margin-right:6px}
table.mini{border-collapse:collapse;font-size:12px;margin-top:10px}
table.mini td{border-bottom:1px solid #EFEEE9;padding:4px 14px 4px 0;color:#444441}
table.mini td:first-child{color:#5F5E5A}
"""


def _chips(run) -> str:
    s = run["summary"]
    ok = "chip ok" if run["utility"] == 1 else "chip bad"
    return "".join([
        f'<span class="{ok}">utility <b>{run["utility"]}</b></span>',
        f'<span class="chip">A 轮次 <b>{s["a_turns"]}</b></span>',
        f'<span class="chip">B 轮次 <b>{s["b_turns"]}</b></span>',
        f'<span class="chip">读取 <b>{s["n_reads"]}</b></span>',
        f'<span class="chip">写入 <b>{s["n_writes"]}</b></span>',
        f'<span class="chip">token <b>{s["tokens_in"]} in / {s["tokens_out"]} out</b></span>',
        f'<span class="chip">模型耗时 <b>{s["api_ms"]/1000:.1f}s</b></span>',
        f'<span class="chip">端到端 <b>{s["wall_ms"]/1000:.1f}s</b></span>',
    ])


def build_html(items, title_note: str = "") -> str:
    parts = [
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
        "<title>双 agent 分工 · 执行图与隐私图</title>", f"<style>{CSS}</style></head><body><div class=\"wrap\">",
        "<h1>双 agent 分工 · 执行图 / 隐私图</h1>",
        '<div class="sub">A 只做读取与评估，B 只做执行、计算与写入；两者工具集互斥、无重叠。'
        "每个 agent 画成一个框，箭头表示命题在 agent 之间以及流向接收者的方向。"
        f"全局 backbone：<code>deepseek-flash</code>。{title_note}</div>",
    ]
    for run, pg in items:
        parts.append("<section>")
        parts.append(f'<h2>{esc(run["suite"])} · {esc(run["task_id"])}'
                     f'<span style="font-weight:400;color:#5F5E5A;font-size:13px">'
                     f' · {esc(run["difficulty"].replace("TaskDifficulty.", ""))}</span></h2>')
        parts.append(f'<div class="path">{esc(run["prompt"])}</div>')
        parts.append(f'<div class="chips">{_chips(run)}</div>')
        parts.append('<div class="split">')
        parts.append('<span class="tag">A：' + esc("、".join(run["tools"]["A"])) + "</span>")
        parts.append('<span class="tag b">B：' + esc("、".join(run["tools"]["B"])) + "</span>")
        parts.append("</div>")

        parts.append("<h3>执行图</h3>")
        parts.append(svg_exec(run))
        parts.append('<div class="legend">'
                     '<span><span class="dot" style="background:#185FA5"></span>A 读取产生的命题</span>'
                     '<span><span class="dot" style="background:#0F6E56"></span>命题交给 B</span>'
                     '<span><span class="dot" style="background:#534AB7"></span>B 对环境的写入</span>'
                     "</div>")

        parts.append("<h3>隐私图</h3>")
        parts.append(svg_privacy(pg))
        parts.append('<div class="legend">'
                     '<span><span class="dot" style="background:#185FA5"></span>已记录的披露（经 SHARE 交给 B）</span>'
                     '<span><span class="dot" style="background:#BA7517"></span>发生了但没记录的读取</span>'
                     '<span><span class="dot" style="background:#A32D2D"></span>隐式 / 未记录（模型上传、工具内部写入）</span>'
                     "</div>")
        rows = "".join(
            f'<tr><td>{esc(p["name"])}</td><td>{esc(clip(p["value"], 40))}</td>'
            f'<td>{esc("、".join(t["recv"] for t in p["to"]))}</td></tr>'
            for p in pg["props"])
        parts.append('<table class="mini"><tr><td>敏感命题</td><td>值</td><td>流向</td></tr>'
                     f"{rows}</table>")
        parts.append('<div class="note">隐私图只画事实级披露；'
                     + "、".join(esc(x) for x in pg["unimplemented"]) + " 尚未实现。</div>")
        parts.append("</section>")
    parts.append("</div></body></html>")
    return "".join(parts)
