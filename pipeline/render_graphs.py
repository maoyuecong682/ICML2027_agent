"""把执行图 / 隐私图渲染成自包含 HTML（本地可开）。

不依赖任何 CDN，直接内联 SVG。
"""
from __future__ import annotations

from xml.sax.saxutils import escape

W = 1100

TYPE_STYLE = {
    "TASK":  ("#E6F1FB", "#185FA5", "#0C447C", "任务"),
    "TURN":  ("#E6F1FB", "#185FA5", "#0C447C", "模型轮次"),
    "TOOL":  ("#F1EFE8", "#888780", "#2C2C2A", "工具调用"),
    "SHARE": ("#EEEDFE", "#534AB7", "#3C3489", "信息共享"),
    "UTIL":  ("#EAF3DE", "#3B6D11", "#173404", "判定"),
}


def esc(s) -> str:
    return escape(str(s))


def _clip(s, n):
    s = str(s)
    return s if len(s) <= n else s[: n - 3] + "..."


def svg_exec(run: dict) -> str:
    nodes = run["nodes"]
    row_h, gap = 48, 30
    step = row_h + gap
    H = 16 + len(nodes) * step - gap + 16
    out = [
        f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" '
        f'font-family="system-ui,-apple-system,Segoe UI,sans-serif">',
        "<defs><marker id=\"ar\" viewBox=\"0 0 10 10\" refX=\"8\" refY=\"5\" "
        "markerWidth=\"7\" markerHeight=\"7\" orient=\"auto-start-reverse\">"
        "<path d=\"M2 1L8 5L2 9\" fill=\"none\" stroke=\"#5F5E5A\" stroke-width=\"1.6\" "
        "stroke-linecap=\"round\" stroke-linejoin=\"round\"/></marker></defs>",
    ]
    for i, n in enumerate(nodes):
        y = 16 + i * step
        fill, stroke, txt, zh = TYPE_STYLE.get(n["type"], ("#F1EFE8", "#888780", "#2C2C2A", n["type"]))
        if i > 0:
            out.append(
                f'<path d="M584 {y - gap} L584 {y - 3}" fill="none" stroke="#5F5E5A" '
                f'stroke-width="1.4" marker-end="url(#ar)"/>'
            )
        else:
            out.append(
                f'<circle cx="584" cy="8" r="3.5" fill="#5F5E5A"/>'
            )
        out.append(
            f'<text x="104" y="{y + 24}" text-anchor="end" font-size="11.5" '
            f'font-weight="500" fill="{stroke}">{zh}</text>'
        )
        out.append(
            f'<rect x="112" y="{y}" width="944" height="{row_h}" rx="8" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="0.8"/>'
        )
        out.append(
            f'<text x="128" y="{y + 19}" font-size="13" font-weight="500" fill="{txt}">'
            f'{esc(_clip(n.get("label", n["type"]), 62))}</text>'
        )
        meta = n.get("meta", "")
        out.append(
            f'<text x="128" y="{y + 35}" font-size="11.5" fill="{stroke}">'
            f'{esc(_clip(meta, 96))}</text>'
        )
        if n.get("tokens"):
            out.append(
                f'<text x="1042" y="{y + 24}" text-anchor="end" font-size="11.5" '
                f'fill="{stroke}">{n["tokens"]["in"]} in / {n["tokens"]["out"]} out</text>'
            )
    out.append("</svg>")
    return "\n".join(out)


def svg_privacy(pg: dict) -> str:
    subj = pg["subject"]
    attrs = pg["attrs"]
    recvs = pg["receivers"]
    edges = pg["edges"]

    sx, sy, sw, sh = 30, 30, 300, 54
    rx_sub = 54
    attr_y0, attr_h, attr_gap = 118, 34, 10
    rx_, rw, rh, rgap = 730, 340, 52, 20

    attr_bottom = attr_y0 + len(attrs) * (attr_h + attr_gap) - attr_gap
    recv_bottom = sy + len(recvs) * (rh + rgap) - rgap
    H = max(attr_bottom, recv_bottom) + 40

    out = [
        f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" '
        f'font-family="system-ui,-apple-system,Segoe UI,sans-serif">',
        "<defs><marker id=\"arp\" viewBox=\"0 0 10 10\" refX=\"8\" refY=\"5\" "
        "markerWidth=\"7\" markerHeight=\"7\" orient=\"auto-start-reverse\">"
        "<path d=\"M2 1L8 5L2 9\" fill=\"none\" stroke=\"context-stroke\" stroke-width=\"1.6\" "
        "stroke-linecap=\"round\" stroke-linejoin=\"round\"/></marker></defs>",
    ]

    # 主体
    out.append(
        f'<ellipse cx="{sx + rx_sub}" cy="{sy + sh / 2}" rx="{rx_sub}" ry="{sh / 2}" fill="#E6F1FB" '
        f'stroke="#185FA5" stroke-width="0.8"/>'
    )
    out.append(
        f'<text x="{sx + rx_sub}" y="{sy + 22}" text-anchor="middle" font-size="12.5" '
        f'font-weight="500" fill="#0C447C">{esc(_clip(subj["name"], 14))}</text>'
    )
    out.append(
        f'<text x="{sx + rx_sub}" y="{sy + 39}" text-anchor="middle" font-size="10.5" '
        f'fill="#185FA5">信息主体</text>'
    )

    # 敏感属性
    for i, a in enumerate(attrs):
        y = attr_y0 + i * (attr_h + attr_gap)
        out.append(
            f'<path d="M16 {sy + sh} L16 {y + attr_h / 2} L{sx} {y + attr_h / 2}" fill="none" '
            f'stroke="#B4B2A9" stroke-width="1" stroke-dasharray="3 3"/>'
        )
        hot = a["level"] == "high"
        fill, stroke = ("#FAEEDA", "#BA7517") if hot else ("#F1EFE8", "#888780")
        out.append(
            f'<rect x="{sx}" y="{y}" width="{sw}" height="{attr_h}" rx="6" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="0.8"/>'
        )
        out.append(
            f'<text x="{sx + 12}" y="{y + 14}" font-size="11.5" font-weight="500" '
            f'fill="#2C2C2A">{esc(a["name"])}</text>'
        )
        out.append(
            f'<text x="{sx + 12}" y="{y + 27}" font-size="10.5" fill="#5F5E5A">'
            f'{esc(_clip(a["value"], 40))}</text>'
        )

    # 接收者
    ry_of = {}
    for i, r in enumerate(recvs):
        y = sy + i * (rh + rgap)
        ry_of[r["id"]] = y
        if r["recorded"]:
            fill, stroke, txt = "#E6F1FB", "#185FA5", "#0C447C"
        else:
            fill, stroke, txt = "#FCEBEB", "#A32D2D", "#791F1F"
        out.append(
            f'<rect x="{rx_}" y="{y}" width="{rw}" height="{rh}" rx="8" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="0.8"/>'
        )
        out.append(
            f'<text x="{rx_ + 14}" y="{y + 21}" font-size="12.5" font-weight="500" '
            f'fill="{txt}">{esc(_clip(r["name"], 30))}</text>'
        )
        tag = "已记录" if r["recorded"] else "未记录"
        out.append(
            f'<text x="{rx_ + 14}" y="{y + 38}" font-size="10.5" fill="{stroke}">'
            f'{esc(r["kind"])} · {tag}</text>'
        )

    # 披露边：同一个接收者的多条边按序错开，避免叠在一起
    from collections import defaultdict

    buckets = defaultdict(list)
    for e in edges:
        if e["dst"] in ry_of:
            buckets[e["dst"]].append(e)
    x1, y1 = sx + 2 * rx_sub, sy + sh / 2
    for dst, group in buckets.items():
        group.sort(key=lambda e: (not e["recorded"], e["mode"]))
        k = len(group)
        for i, e in enumerate(group):
            off = (i - (k - 1) / 2) * 16
            y2 = ry_of[dst] + rh / 2 + off
            color = "#185FA5" if e["recorded"] else "#A32D2D"
            dash = "" if e["recorded"] else ' stroke-dasharray="5 4"'
            out.append(
                f'<path d="M{x1} {y1} L{rx_ - 3} {y2}" fill="none" stroke="{color}" '
                f'stroke-width="1.4"{dash} marker-end="url(#arp)"/>'
            )
            t = 0.58 + i * 0.07
            lx = x1 + t * (rx_ - x1)
            ly = y1 + t * (y2 - y1) - 9
            label = f'{e["mode"]} · {_clip(", ".join(e["fields"]), 40)}'
            wlab = len(label) * 6.4 + 10
            out.append(
                f'<rect x="{lx - wlab / 2}" y="{ly - 11}" width="{wlab}" height="16" rx="3" '
                f'fill="#FFFFFF" opacity="0.92"/>'
            )
            out.append(
                f'<text x="{lx}" y="{ly}" text-anchor="middle" font-size="10.5" '
                f'fill="{color}">{esc(label)}</text>'
            )

    out.append("</svg>")
    return "\n".join(out)


CSS = """
:root{--bd:#E3E1DA;--mut:#5F5E5A;--ink:#2C2C2A;}
*{box-sizing:border-box}
body{margin:0;padding:32px 28px 64px;background:#FAFAF8;color:var(--ink);
 font:14px/1.6 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:1160px;margin:0 auto}
h1{font-size:20px;font-weight:600;margin:0 0 6px}
.sub{color:var(--mut);font-size:13px;margin-bottom:28px}
section{background:#fff;border:1px solid var(--bd);border-radius:12px;padding:22px 24px;
 margin-bottom:26px}
h2{font-size:16px;font-weight:600;margin:0 0 4px}
h3{font-size:13.5px;font-weight:600;margin:26px 0 10px;color:#3C3489}
.path{font-family:ui-monospace,Consolas,monospace;font-size:12px;color:#185FA5}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 18px}
.chip{background:#F1EFE8;border-radius:999px;padding:3px 11px;font-size:12px;color:#444441}
.chip b{font-weight:600;color:#2C2C2A}
.chip.ok{background:#EAF3DE;color:#173404}
.chip.bad{background:#FCEBEB;color:#791F1F}
.note{font-size:12.5px;color:var(--mut);margin-top:12px;padding-left:14px;
 border-left:2px solid var(--bd)}
ul.unimpl{margin:8px 0 0;padding-left:20px;font-size:12.5px;color:var(--mut)}
.legend{display:flex;gap:18px;flex-wrap:wrap;font-size:12px;color:var(--mut);margin-top:10px}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}
"""


def _chips(run) -> str:
    s = run["summary"]
    u = run["utility"]
    cls = "chip ok" if u == 1 else "chip bad"
    return "".join([
        f'<span class="{cls}">utility <b>{u}</b></span>',
        f'<span class="chip">图节点 <b>{s["n_nodes"]}</b></span>',
        f'<span class="chip">模型调用 <b>{s["n_api_calls"]}</b></span>',
        f'<span class="chip">工具调用 <b>{s["n_tool_calls"]}</b></span>',
        f'<span class="chip">token <b>{s["tokens_in"]}↑ {s["tokens_out"]}↓</b></span>',
        f'<span class="chip">耗时 <b>{s["wall_ms"] / 1000:.1f}s</b></span>',
    ])


def build_html(items: list) -> str:
    parts = [
        "<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">",
        "<title>执行图 / 隐私图 · travel 与 banking</title>",
        f"<style>{CSS}</style></head><body><div class=\"wrap\">",
        "<h1>执行图 / 隐私图 · AgentDojo travel 与 banking</h1>",
        "<div class=\"sub\">LangGraph StateGraph 构建的<b>执行图</b>（TASK / TURN / TOOL / SHARE / UTIL），"
        "以及从同一次执行记录里抽出的<b>隐私图骨架</b>。"
        "全局 backbone：<code>deepseek-flash</code>。记忆整理与隐私判断尚未接入。</div>",
    ]
    for run, pg in items:
        parts.append("<section>")
        parts.append(f'<h2>{esc(run["suite"])} · {esc(run["task_id"])}</h2>')
        parts.append(f'<div class="path">{esc(run["prompt"][:150])}</div>')
        parts.append(f'<div class="chips">{_chips(run)}</div>')
        parts.append('<h3>执行图（StateGraph 真实轨迹）</h3>')
        parts.append(svg_exec(run))
        parts.append(
            '<div class="legend"><span>节点按实际执行顺序排列；'
            '灰色为工具调用，紫色为跨 agent 共享，绿色为 utility 判定。</span></div>'
        )
        parts.append('<h3>隐私图（骨架 · 仅可观测披露）</h3>')
        parts.append(svg_privacy(pg))
        parts.append(
            '<div class="legend">'
            '<span><span class="dot" style="background:#185FA5"></span>已记录的披露</span>'
            '<span><span class="dot" style="background:#A32D2D"></span>已发生但未记录的披露</span>'
            '<span>虚线 = 隐式 / 未记录</span></div>'
        )
        unim = "".join(f"<li>{esc(x)}</li>" for x in pg["unimplemented"])
        parts.append(
            f'<div class="note">这一版隐私图只画事实级披露，'
            f'以下三项尚未实现，故图上没有：<ul class="unimpl">{unim}</ul></div>'
        )
        parts.append("</section>")
    parts.append("</div></body></html>")
    return "\n".join(parts)
