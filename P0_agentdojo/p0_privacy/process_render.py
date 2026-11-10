"""Deterministic PNG diagrams rendered from the delivered task graph JSON."""
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BG = "#f3f6fa"
INK = "#18324b"
MUTED = "#5e7083"
BLUE = "#2876ae"
TEAL = "#167d72"
AMBER = "#a86b19"
GREY = "#8d9aab"
NECESSITY = {"required": "必要", "helpful": "有帮助", "unnecessary": "不必要", "unknown": "待判断"}
OPS = {"identity": "保留", "generalize": "模糊化", "substitute": "替换", "redact": "遮盖", "drop": "删除"}


def font(size, bold=False):
    paths = (["C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/segoeuib.ttf"] if bold else
             ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/segoeui.ttf"])
    for path in paths:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def wrap(draw, text, fnt, width):
    result = []
    for paragraph in str(text).splitlines() or [""]:
        current = ""
        for char in paragraph:
            if current and draw.textlength(current + char, font=fnt) > width:
                result.append(current)
                current = char
            else:
                current += char
        result.append(current)
    return result


def text_block(draw, xy, text, size=25, color=INK, width=620, max_lines=None, bold=False, leading=8):
    f = font(size, bold)
    lines = wrap(draw, text, f, width)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        while draw.textlength(lines[-1] + "…", font=f) > width:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    for i, line in enumerate(lines):
        draw.text((xy[0], xy[1] + i*(size+leading)), line, font=f, fill=color)
    return xy[1] + len(lines)*(size+leading)


def arrow(draw, points, color=BLUE, dashed=False, width=4, head=True):
    for start, end in zip(points, points[1:]):
        length = math.dist(start, end)
        if dashed and length:
            steps = int(length / 17) + 1
            for i in range(0, steps, 2):
                a, b = i / steps, min(i+1, steps) / steps
                draw.line((start[0]+(end[0]-start[0])*a, start[1]+(end[1]-start[1])*a,
                           start[0]+(end[0]-start[0])*b, start[1]+(end[1]-start[1])*b), fill=color, width=width)
        else:
            draw.line((start, end), fill=color, width=width)
    if head:
        start, end = points[-2:]
        angle = math.atan2(end[1]-start[1], end[0]-start[0])
        draw.polygon([end, (end[0]-13*math.cos(angle-.46), end[1]-13*math.sin(angle-.46)),
                      (end[0]-13*math.cos(angle+.46), end[1]-13*math.sin(angle+.46))], fill=color)


def card(draw, box, fill="white", outline="#d7e1eb", stripe=None):
    draw.rounded_rectangle(box, radius=17, fill=fill, outline=outline, width=2)
    if stripe:
        draw.rounded_rectangle((box[0], box[1]+15, box[0]+6, box[3]-15), radius=3, fill=stripe)


def compact_parameters(parameters):
    if not parameters:
        return "{} · 无参数值"
    if set(parameters) == {"query"}:
        return "query: " + parameters["query"]
    if "filename" in parameters:
        return "filename: " + parameters["filename"] + "\ncontent: 清单、姓名、目的地及日期"
    return json.dumps(parameters, ensure_ascii=False)


def render(path):
    graph = json.loads(path.read_text(encoding="utf-8"))
    by_id = {n["id"]: n for n in graph["nodes"]}
    groups = sorted(graph["display_groups"], key=lambda g: (
        {"legal_name": 0, "travel_destination": 1, "travel_dates": 2, "query_intent": 0,
         "social_relationship": 1, "file_metadata": 3, "none": 4}.get(g["field"], 3),
        g["necessity"], g["id"]))
    group_positions, y = {}, 985
    for i, group in enumerate(groups):
        height = 205 if len(group["atom_ids"]) > 3 else 165
        group_positions[group["id"]] = (y, height, "A" + str(i+1))
        y += height + 25
    diagram_end = max(y+20, 1660)
    width, height = 2400, diagram_end + 340
    canvas = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, width, 12), fill=TEAL)
    text_block(draw, (65, 43), "隐私信息披露与潜在推断过程", 46, width=1800, bold=True)
    text_block(draw, (65, 112), graph["task"]["task_key"] + "  |  " + graph["title"], 31, width=2200)
    text_block(draw, (65, 166), graph["task"]["prompt"], 24, MUTED, 2250, 2)
    text_block(draw, (65, 244), "已发生的接收可核对原文；字段标注与推断假设均不能直接当作不当泄露结论。", 25, AMBER, 2250)

    # Section 1: two real tool requests, with separate memory states.
    card(draw, (40, 305, 2360, 837))
    text_block(draw, (70, 327), "01  实际接收过程", 32, bold=True)
    text_block(draw, (70, 378), "内部处理 / 来源概况", 25, MUTED, 590, bold=True)
    text_block(draw, (755, 378), "实际请求参数", 25, BLUE, 650, bold=True)
    receiver = graph["receiver_memory"][0]
    receiver_node = by_id[receiver["receiver_node"]]
    receiver_short = receiver_node["label"].replace("AgentDojo 模拟", "")
    text_block(draw, (1510, 378), receiver_short + " · 接收记忆", 25, TEAL, 750, bold=True)
    for i, step in enumerate(graph["timeline"]):
        request = by_id[step["request_node"]]
        state = by_id[step["after_memory"]]
        row_y = 432 + 176*i
        card(draw, (70, row_y, 675, row_y+145), "#f5f7fb", stripe=GREY)
        atoms = [n for n in graph["nodes"] if n["type"] == "disclosed_atom" and n["disclosure_id"] == request["disclosure_id"]]
        source_names = []
        for atom in atoms:
            for sid in atom["annotation"]["source_ids"]:
                if sid == "user:task":
                    label = "用户原始任务"
                else:
                    source = by_id["source:" + sid]
                    evidence = source["evidence"]
                    label = "此前 " + evidence["tool"] + " 返回的本地云盘资料"
                if label not in source_names:
                    source_names.append(label)
        if not source_names:
            source_names = ["原任务触发的无参数读取"]
        text_block(draw, (92, row_y+16), f"Agent {request['actor']} · {request['event_id']}", 26, bold=True, width=550)
        text_block(draw, (92, row_y+60), " / ".join(source_names), 23, MUTED, 550, 2)
        arrow(draw, [(687, row_y+72), (740, row_y+72)], GREY)
        card(draw, (755, row_y, 1420, row_y+145), "#edf5fc", stripe=BLUE)
        text_block(draw, (780, row_y+13), request["label"], 26, BLUE, 605, bold=True)
        text_block(draw, (780, row_y+56), compact_parameters(request["parameters"]), 23, INK, 605, 3)
        arrow(draw, [(1431, row_y+72), (1490, row_y+72)], TEAL)
        card(draw, (1505, row_y, 2320, row_y+145), "#eaf6f2", stripe=TEAL)
        text_block(draw, (1530, row_y+13), state["label"], 27, TEAL, 750, bold=True)
        detail = ("累计保留该请求；本次无参数值" if request["empty_parameters"] else
                  f"本次包含 {len(atoms)} 条既有片段标注")
        text_block(draw, (1530, row_y+57), detail + "\n累计历史保留；先验知识尚未建模", 23, MUTED, 750, 2)
        if i:
            arrow(draw, [(2292, row_y-31), (2292, row_y-6)], TEAL, width=3)
    text_block(draw, (70, 795), "A/B、用户本人不计入业务泄露出口；来源资料仅用于追溯，未把工具返回全文算成接收者的新披露。", 22, MUTED, 2240)

    # Section 2: visual atom groups, their original labels, and joint factors.
    card(draw, (40, 867, 2360, diagram_end))
    text_block(draw, (70, 889), "02  已接收片段 → 字段标注 → 类别推断因子", 31, bold=True, width=2000)
    text_block(draw, (80, 938), "片段组（A 编号供右侧引用）", 23, MUTED, 650)
    text_block(draw, (855, 938), "原有模型字段标注", 23, MUTED, 600)
    text_block(draw, (1660, 938), "联合线索：满足输入 ≠ 推断成功", 23, AMBER, 650)
    atom_to_group = {}
    field_anchors = {}
    fields = {n["field"]: n for n in graph["nodes"] if n["type"] == "sensitive_field"}
    for group in groups:
        gy, gh, tag = group_positions[group["id"]]
        for atom_id in group["atom_ids"]:
            atom_to_group[atom_id] = tag
        field_anchors.setdefault(group["field"], []).append(gy+gh/2)
    # Draw edges first, so their endpoints are clean at the card borders.
    field_centers = {field: sum(ys)/len(ys) for field, ys in field_anchors.items()}
    for group in groups:
        gy, gh, tag = group_positions[group["id"]]
        field = group["field"]
        indirect = any(by_id[a]["annotation"]["kind"] == "indirect" for a in group["atom_ids"])
        center = field_centers[field]
        arrow(draw, [(736, gy+gh/2), (790, gy+gh/2), (825, center), (850, center)],
              AMBER if indirect else TEAL, dashed=indirect)
    for group in groups:
        gy, gh, tag = group_positions[group["id"]]
        atoms = [by_id[a]["annotation"] for a in group["atom_ids"]]
        sensitive = group["field"] != "none"
        card(draw, (75, gy, 735, gy+gh), "#f4f8fb" if sensitive else "#f5f6f8", stripe=BLUE if sensitive else GREY)
        main = " / ".join(dict.fromkeys(a["span"] for a in atoms))
        text_block(draw, (97, gy+15), tag + "  " + main, 25, width=615, max_lines=3, bold=True)
        text_block(draw, (97, gy+gh-60),
            f"{len(atoms)} 条标注 · {NECESSITY[group['necessity']]} · 建议{OPS[group['op']]}", 22,
            AMBER if group["necessity"] == "unnecessary" else MUTED, 615)
        provenances = set(a["provenance"] for a in atoms)
        provenance = "本地云盘资料" if "user-local" in provenances else "用户原始任务"
        text_block(draw, (97, gy+gh-30), "来源：" + provenance + "（完整证据见 JSON）", 19, MUTED, 615)
    for field, center in field_centers.items():
        if field == "none":
            label, code, detail, color = "非敏感任务片段", "field = none", "保留原有模型判断；仍可作为上下文线索", GREY
        else:
            data = fields[field]
            indirect_only = not data["direct_values"]
            label, code = data["label"], field
            detail = "潜在间接关联 · 尚未验证" if indirect_only else "原文直接出现 · 未测量新增知识"
            color = AMBER if indirect_only else TEAL
        card(draw, (855, center-70, 1520, center+70), "#fff8ec" if color == AMBER else "#f0f8f5", stripe=color)
        text_block(draw, (880, center-53), label, 28, color, 610, 1, True)
        text_block(draw, (880, center-10), code, 22, MUTED, 610, 1)
        text_block(draw, (880, center+27), detail, 21, MUTED, 610, 1)

    # Each factor shows its full input scope rather than suggesting an OR rule.
    fy = 983
    for factor in graph["joint_factors"]:
        node = by_id[factor["factor_node"]]
        output = by_id[factor["output_node"]]
        ready = not factor["missing_slots"]
        fh = 230 if len(factor["required_slots"]) > 2 else 212
        color = AMBER if ready else GREY
        card(draw, (1650, fy, 2320, fy+fh), "#fff8ec" if ready else "#f5f6f8", stripe=color)
        text_block(draw, (1675, fy+15), output["label"], 27, color, 615, 1, True)
        chips = []
        for slot in factor["required_slots"]:
            tags = sorted({atom_to_group[a] for a in factor["support"][slot]})
            label = slot.split(":", 1)[1]
            chips.append(("/".join(tags) if tags else "缺失") + " · " + label)
        text_block(draw, (1675, fy+58), " + ".join(chips), 22, INK, 615, 2)
        arrow(draw, [(1680, fy+133), (1740, fy+133)], color, dashed=True, width=3)
        text_block(draw, (1755, fy+116), "线索齐备，仍待验证" if ready else "输入不全，联合路径未激活", 23, color, 520, 1)
        text_block(draw, (1675, fy+157), node["label"], 20, MUTED, 615, 2)
        fy += fh + 28
    # Category fields absent from actual annotations stay explicitly unobserved.
    category_ids = graph["task"]["category_ids"]
    if "credential_lookup" in category_ids:
        detail = "未观察到重置令牌、验证码进入业务接收视图。最终回复用户的链接不计入该出口。"
    elif "email_read" in category_ids:
        detail = "缺少 sender 参数；模型的家庭关系猜测与类别联合因子的激活状态分别记录。"
    else:
        detail = "姓名、目的地、日期在同一次请求共现。行程关联是待验证假设；不能断言住宅无人。"
    info_y = max(fy+5, 1330)
    text_block(draw, (1660, info_y), detail, 23, MUTED, 650, 4)
    text_block(draw, (1660, info_y+160), "类别因子未校准\n后验 / 秘密恢复：未运行\n隐私增益：null", 24, AMBER, 640, 3)

    # Footer: legends and scope, with source JSON as the lossless representation.
    y0 = diagram_end + 30
    arrow(draw, [(75, y0+20), (153, y0+20)], TEAL)
    text_block(draw, (175, y0+2), "实线：实际接收 / 直接字段标注（以文字说明为准）", 22, MUTED, 1070)
    arrow(draw, [(1250, y0+20), (1328, y0+20)], AMBER, dashed=True)
    text_block(draw, (1350, y0+2), "虚线：模型推断或类别假设", 22, MUTED, 900)
    text_block(draw, (75, y0+62),
        f"官方任务成功：{graph['task']['official_task_success']}   |   实际请求：{graph['statistics']['requests']}   |   "
        f"原有标注：{graph['statistics']['atoms']}   |   不当泄露结论：尚未评价", 25, INK, 2250, bold=True)
    text_block(draw, (75, y0+115), "建议仅供审计，本轮没有删改或重新发送。接收者可能已保存原始邮件或文件；写回不等于产生新的知识增益。", 23, MUTED, 2240, 2)
    text_block(draw, (75, y0+190),
        f"PNG 合并展示同类片段，标签可能缩略；本任务全部请求、{graph['statistics']['atoms']} 条原有标注、来源、节点、边与联合条件均保存在对应 JSON。",
        21, MUTED, 2240, 2)
    canvas.save(path.with_suffix(".png"), optimize=True)
