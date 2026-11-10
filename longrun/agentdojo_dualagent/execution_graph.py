"""执行图（Execution Graph）+ memo 图结构压缩。

设计（参考 All-Mem / TeleMem / MemORAI 的“图即记忆”范式）：
- 长程任务的每一步都被记录为一个带类型的节点（planner / tool_call / observation / critic / summary）。
- 节点之间用有向边连接（control / data / summary_of / critique），形成可追溯的执行轨迹图。
- memo 压缩分两步，且“非破坏性”（保留血缘，仅切换可见性）：
    1) MERGE：把连续、相同工具的冗余 tool_call 折叠为一个 summary 节点（保留 summary_of 边指向原文）。
    2) VISIBLE SURFACE（可见面）：只保留最近 K 个节点 + 所有 summary 节点可见，其余置为 archived
       （visibility=0），但节点与边全部保留，保证可追溯、可还原。
- memory footprint（记忆占用）= 压缩后“仅可见面”的序列化字节数。
"""
from __future__ import annotations
import json
import uuid
from dataclasses import dataclass, field, asdict


@dataclass
class GraphNode:
    id: str
    type: str            # planner | tool_call | observation | critic | summary
    label: str
    detail: str = ""
    agent: str = ""      # "A" | "B" | "system"
    tokens: int = 0
    timestamp: float = 0.0
    visibility: int = 1  # 1=可见(visible surface) 0=已归档(archived)
    parent_ids: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)


@dataclass
class GraphEdge:
    src: str
    dst: str
    kind: str            # control | data | summary_of | critique


class ExecutionGraph:
    def __init__(self):
        self.nodes: dict[str, GraphNode] = {}
        self.edges: list[GraphEdge] = []
        self._order: list[str] = []
        self._sid = 0

    # ---------- 写入 ----------
    def add_node(self, type, label, detail="", agent="", tokens=0,
                 parent_ids=None, meta=None, timestamp=0.0) -> str:
        nid = type[0] + uuid.uuid4().hex[:8]
        node = GraphNode(
            id=nid, type=type, label=label, detail=detail, agent=agent,
            tokens=tokens, timestamp=timestamp or len(self._order),
            visibility=1, parent_ids=parent_ids or [], meta=meta or {},
        )
        self.nodes[nid] = node
        self._order.append(nid)
        return nid

    def add_edge(self, src, dst, kind):
        if src and dst and src != dst:
            self.edges.append(GraphEdge(src, dst, kind))

    # ---------- 查询 ----------
    def visible_nodes(self):
        return [n for n in self.nodes.values() if n.visibility == 1]

    def summary(self):
        total = len(self.nodes)
        vis = len(self.visible_nodes())
        arch = total - vis
        return f"nodes={total} visible={vis} archived={arch} edges={len(self.edges)}"

    # ---------- 序列化 / 体积 ----------
    def to_dict(self, visible_only=False):
        if visible_only:
            nodes = [asdict(n) for n in self.nodes.values() if n.visibility == 1]
            edges = [asdict(e) for e in self.edges
                     if (self.nodes.get(e.src) and self.nodes[e.src].visibility == 1)
                     or (self.nodes.get(e.dst) and self.nodes[e.dst].visibility == 1)]
        else:
            nodes = [asdict(n) for n in self.nodes.values()]
            edges = [asdict(e) for e in self.edges]
        return {"nodes": nodes, "edges": edges}

    def size_bytes(self, visible_only=False) -> int:
        return len(json.dumps(self.to_dict(visible_only),
                              ensure_ascii=False).encode("utf-8"))

    def to_networkx(self):
        import networkx as nx
        G = nx.DiGraph()
        for nid, n in self.nodes.items():
            G.add_node(nid, type=n.type, label=n.label, agent=n.agent,
                       visibility=n.visibility, tokens=n.tokens)
        for e in self.edges:
            G.add_edge(e.src, e.dst, kind=e.kind)
        return G

    # ---------- memo 图结构压缩 ----------
    def compress(self, llm=None, merge_window=3, keep_recent=6) -> int:
        """返回压缩后可见节点数。非破坏性：归档节点与边全部保留。"""
        order = list(self._order)
        new_order: list[str] = []
        i = 0
        while i < len(order):
            nid = order[i]
            node = self.nodes[nid]
            run = [nid]
            if node.type == "tool_call":
                while (i + len(run) < len(order)
                       and self.nodes[order[i + len(run)]].type == "tool_call"
                       and self.nodes[order[i + len(run)]].meta.get("tool")
                       == node.meta.get("tool")):
                    run.append(order[i + len(run)])
            if len(run) >= merge_window:
                # 生成 summary 节点，折叠冗余连续调用
                s_id = f"S{self._sid}"; self._sid += 1
                args_seq = " | ".join(self.nodes[r].meta.get("args", "") for r in run)
                s = GraphNode(
                    id=s_id, type="summary",
                    label=f"×{len(run)} {node.meta.get('tool')}",
                    detail=f"merged consecutive identical calls: {args_seq}",
                    agent="system", visibility=1,
                    timestamp=self.nodes[run[0]].timestamp,
                )
                self.nodes[s_id] = s
                in_edges = [e for e in self.edges if e.dst == run[0]]
                out_edges = [e for e in self.edges if e.src == run[-1]]
                self.edges = [e for e in self.edges
                              if e.dst != run[0] and e.src != run[-1]]
                for e in in_edges:
                    self.edges.append(GraphEdge(e.src, s_id, e.kind))
                for e in out_edges:
                    self.edges.append(GraphEdge(s_id, e.dst, e.kind))
                for r in run:
                    self.nodes[r].visibility = 0
                    self.edges.append(GraphEdge(s_id, r, "summary_of"))
                new_order.append(s_id)
                i += len(run)
            else:
                new_order.append(nid)
                i += 1
        self._order = new_order

        # 可见面：最近 keep_recent 个节点 + 所有 summary 节点
        visible_ids = {s for s in new_order if self.nodes[s].type == "summary"}
        for s in new_order[-keep_recent:]:
            visible_ids.add(s)
        for nid, n in self.nodes.items():
            n.visibility = 1 if nid in visible_ids else 0
        return len(visible_ids)
