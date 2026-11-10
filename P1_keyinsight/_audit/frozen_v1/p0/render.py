"""Render the actual graph JSON to a PNG; labels shortened only for display."""
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

COLORS = {"A": "#dcecff", "B": "#d9f3e7", "tool": "#fff0d7", "system": "#e9e8f2"}


def font(size, bold=False):
    candidates = (["C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/segoeuib.ttf"] if bold else
                  ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/segoeui.ttf"])
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def wrap(draw, text, fnt, width, max_lines=3):
    lines, current = [], ""
    for char in str(text).replace("\n", " "):
        if draw.textlength(current+char, font=fnt) > width:
            lines.append(current)
            current = char
        else:
            current += char
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:-3] + "..."
    return lines


def arrow(draw, start, end, color, width=2):
    draw.line((start, end), fill=color, width=width)
    angle = math.atan2(end[1]-start[1], end[0]-start[0])
    head = [end, (end[0]-11*math.cos(angle-.45), end[1]-11*math.sin(angle-.45)),
            (end[0]-11*math.cos(angle+.45), end[1]-11*math.sin(angle+.45))]
    draw.polygon(head, fill=color)


def render_graph(path):
    graph = json.loads(path.read_text(encoding="utf-8"))
    nodes, result = graph["nodes"], graph["result"]
    width, row, top, lane_width = 1840, 132, 365, 425
    height = top + row*len(nodes) + 100
    canvas = Image.new("RGB", (width, height), "#f6f8fc")
    draw = ImageDraw.Draw(canvas)
    title_f, label_f, body_f, small_f = font(35, True), font(23, True), font(21), font(18)
    draw.text((50, 28), f"P0 | {graph['task']['suite']} / {graph['task']['task_id']}", font=title_f, fill="#152441")
    for i, line in enumerate(wrap(draw, graph["task"]["prompt"], body_f, width-100, 3)):
        draw.text((50, 93+i*29), line, font=body_f, fill="#283a55")
    utility = result.get("utility")
    summary = f"Official utility: {utility}  |  Status: {result['status']}  |  Time: {result['wall_seconds']} s"
    draw.text((50, 204), summary, font=label_f, fill="#174f3b" if utility == 1 else "#9b2c2c")
    draw.text((50, 246), "Both agents: DeepSeek / deepseek-flash | thinking disabled | full payloads in graph.json", font=small_f, fill="#526079")
    draw.text((50, 275), "Grey arrows: chronological sequence. Blue arrows: message/observation supplied to the next model call.", font=small_f, fill="#526079")
    lanes = ["B", "A", "tool", "system"]
    names = ["Agent B | task owner", "Agent A | reader", "AgentDojo tools", "Task / evaluation"]
    centers = {}
    for i, (lane, name) in enumerate(zip(lanes, names)):
        x = 45+i*lane_width
        centers[lane] = x+lane_width/2-8
        draw.rounded_rectangle((x, 320, x+lane_width-16, height-45), radius=14, fill="white", outline="#dce2ed", width=2)
        draw.text((x+15, 330), name, font=label_f, fill="#25344f")
    boxes = {}
    for i, node in enumerate(nodes):
        lane = "tool" if node["type"] == "TOOL" else node["actor"] if node["actor"] in ("A", "B") else "system"
        cx, y = centers[lane], top+i*row+15
        boxes[node["id"]] = (cx-190, y, cx+190, y+104, lane)
    # Draw all sequence edges and the most recent context edge to each LLM.
    # Full accumulated context dependencies remain available in the JSON.
    drawn = []
    for edge in graph["edges"]:
        if edge["kind"] == "sequence":
            drawn.append(edge)
    for node in nodes:
        if node["type"] == "LLM":
            incoming = [e for e in graph["edges"] if e["target"] == node["id"] and e["kind"] == "data"]
            if incoming:
                drawn.append(incoming[-1])
    for edge in drawn:
        a, b = boxes[edge["source"]], boxes[edge["target"]]
        start, end = ((a[0]+a[2])/2, a[3]), ((b[0]+b[2])/2, b[1])
        color = "#9aa7ba" if edge["kind"] == "sequence" else "#5085c6"
        arrow(draw, start, end, color, 3 if edge["kind"] == "data" else 2)
    for node in nodes:
        x1,y1,x2,y2,lane = boxes[node["id"]]
        bad = node["type"] in ("ERROR", "DENIED")
        draw.rounded_rectangle((x1,y1,x2,y2), radius=12, fill="#ffe1df" if bad else COLORS[lane], outline="#b6c4d9", width=2)
        draw.text((x1+12,y1+7), f"{node['id']}  {node['type']}", font=small_f, fill="#455672")
        label = node["label"]
        if node["type"] == "MESSAGE":
            label += " · " + node["payload"].get("query", node["payload"].get("content", ""))
        elif node["type"] == "TOOL":
            label += " · " + str(node["payload"].get("arguments", {}))
        for j,line in enumerate(wrap(draw, label, body_f, x2-x1-24, 2)):
            draw.text((x1+12,y1+35+j*28), line, font=body_f, fill="#172b49")
    draw.text((50,height-30), "Display truncation applies to labels only. Message contents and actual API inputs are retained without truncation.", font=small_f, fill="#526079")
    canvas.save(path.with_suffix(".png"))


def render_run(folder):
    for path in sorted(folder.glob("*/graph.json")):
        render_graph(path)


if __name__ == "__main__":
    import sys
    render_run(Path(sys.argv[1]))
