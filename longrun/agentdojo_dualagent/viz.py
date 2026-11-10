"""执行图结构可视化：垂直泳道时间线（swimlane timeline）。

为什么用时间线而不是力导向图：长程任务的轨迹是按步推进的序列，泳道
（Agent A 动作 / Observation / Agent B 校验）能一眼看清"谁在什么时候做了什么"，
以及 memo 压缩后"哪些节点还在记忆里（亮色=可见面）、哪些已归档（灰色虚线）"。

实现要点：节点用 scatter 画（marker 在显示空间里始终是正圆，不受坐标轴纵横比影响），
避免用 Circle patch 被拉伸成椭圆。
"""
from __future__ import annotations
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyArrowPatch

# 中文字体（Windows 自带 Microsoft YaHei）
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

from execution_graph import ExecutionGraph

TYPE_COLOR = {
    "planner": "#3b82f6",
    "tool_call": "#22c55e",
    "observation": "#f59e0b",
    "critic": "#a855f7",
    "summary": "#ef4444",
}
TYPE_LABEL = {
    "planner": "A:Planner",
    "tool_call": "Tool Call",
    "observation": "Observation",
    "critic": "B:Critic",
    "summary": "Summary(merged)",
}
EDGE_COLOR = {"control": "#64748b", "data": "#0ea5e9",
              "summary_of": "#ef4444", "critique": "#a855f7"}
TYPE_TAG = {"planner": "A", "tool_call": "T", "observation": "O",
            "critic": "B", "summary": "S"}
LANE = {"planner": 0, "tool_call": 0, "summary": 0, "observation": 1, "critic": 2}
LANE_X = [0.16, 0.50, 0.84]
LANE_NAMES = ["Agent A  (plan / tool call)", "Observation", "Agent B  (verify)"]


def render_graph_png(g: ExecutionGraph, out_path: str, title: str = "Execution Graph"):
    nodes = sorted(g.nodes.values(), key=lambda n: (n.timestamp, n.id))
    n = len(nodes)
    if n == 0:
        fig, ax = plt.subplots(figsize=(8, 2))
        ax.text(0.5, 0.5, "empty graph", ha="center")
        fig.savefig(out_path, dpi=140, bbox_inches="tight")
        plt.close(fig)
        return out_path

    H = max(6.2, 0.62 * n + 2.6)
    fig = plt.figure(figsize=(12.5, H))
    ax = fig.add_axes([0.06, 0.07, 0.90, 0.80])
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(n - 0.25, -2.0)      # 反转 y 轴：执行顺序自上而下
    ax.axis("off")

    # 节点坐标
    pos = {}
    for i, nd in enumerate(nodes):
        pos[nd.id] = (LANE_X[LANE.get(nd.type, 0)], float(i))

    # 泳道竖线 + 泳道名（顶部）
    for lane, name in enumerate(LANE_NAMES):
        ax.plot([LANE_X[lane], LANE_X[lane]], [-0.35, n - 0.55],
                color="#e5e9f0", lw=1.2, zorder=0)
        ax.text(LANE_X[lane], -0.75, name, ha="center", va="bottom",
                fontsize=10, color="#334155", fontweight="bold")

    # 边
    for e in g.edges:
        if e.src not in pos or e.dst not in pos:
            continue
        color = EDGE_COLOR.get(e.kind, "#94a3b8")
        ls = "--" if e.kind == "summary_of" else "-"
        ax.add_patch(FancyArrowPatch(
            pos[e.src], pos[e.dst], connectionstyle="arc3,rad=0.10",
            arrowstyle="-|>", mutation_scale=11, color=color,
            lw=1.3, ls=ls, alpha=0.8, zorder=1))

    # 节点：可见 / 归档 两批分别 scatter
    vis = [nd for nd in nodes if nd.visibility == 1]
    arc = [nd for nd in nodes if nd.visibility != 1]
    if vis:
        ax.scatter([pos[x.id][0] for x in vis], [pos[x.id][1] for x in vis],
                   s=[360 if x.type == "summary" else 300 for x in vis],
                   c=[TYPE_COLOR.get(x.type, "#94a3b8") for x in vis],
                   edgecolors="#1e293b", linewidths=1.4, zorder=3, alpha=0.97)
    if arc:
        ax.scatter([pos[x.id][0] for x in arc], [pos[x.id][1] for x in arc],
                   s=230, c="#f1f5f9", edgecolors="#94a3b8", linewidths=1.2,
                   zorder=2, alpha=0.9)

    # 标签 + 类型字母
    for nd in nodes:
        x, y = pos[nd.id]
        visible = nd.visibility == 1
        col = "#0f172a" if visible else "#9aa4b2"
        label = nd.label if len(nd.label) <= 30 else nd.label[:29] + "…"
        dx = -13 if nd.type == "critic" else 13
        ax.annotate(label, (x, y), textcoords="offset points",
                    xytext=(dx, 0), ha="right" if dx < 0 else "left",
                    va="center", fontsize=8.6, color=col, zorder=4)
        ax.annotate(TYPE_TAG.get(nd.type, "?"), (x, y), textcoords="offset points",
                    xytext=(0, 0), ha="center", va="center", fontsize=8,
                    color="white" if visible else "#94a3b8",
                    fontweight="bold", zorder=5)

    # 标题 / 指标 / 脚注（figure 坐标，避免与数据区冲突）
    total, nvis = len(g.nodes), len(g.visible_nodes())
    fig.text(0.06, 0.955, title, fontsize=14.5, fontweight="bold", color="#0f172a")
    fig.text(0.06, 0.915,
             f"nodes={total}    visible={nvis}    archived={total - nvis}    "
             f"edges={len(g.edges)}", fontsize=9.8, color="#475569")
    fig.text(0.06, 0.018,
             "亮色实心 = 仍在记忆中的可见面（visible surface）      "
             "灰色虚线圆 = 已归档（archived，仅保留血缘，可追溯/可还原）",
             fontsize=8.4, color="#64748b")

    handles = [mpatches.Patch(color=c, label=TYPE_LABEL[t]) for t, c in TYPE_COLOR.items()]
    handles.append(mpatches.Patch(facecolor="#f1f5f9", edgecolor="#94a3b8",
                                  label="archived（已压缩出可见面）"))
    ax.legend(handles=handles, loc="upper right", fontsize=7.8, framealpha=0.95,
              ncol=2, bbox_to_anchor=(1.0, 1.16))

    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path
