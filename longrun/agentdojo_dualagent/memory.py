"""执行记忆（Execution Memory）。

携带长程任务执行记忆：本质就是 ExecutionGraph 的“可见面”（visible surface）+
一段由 Critic(B) 沉淀的事实/判语。每步只把压缩后的可见面注入 Agent A 的上下文，
而非把整段原始轨迹塞进 prompt —— 这正是长程任务能控制记忆占用的关键。
"""


class ExecutionMemory:
    def __init__(self, graph):
        self.graph = graph
        self.facts: list[str] = []

    def add_fact(self, text: str):
        if text:
            self.facts.append(text)

    def context_text(self, k: int = 8) -> str:
        vis = sorted(self.graph.visible_nodes(), key=lambda n: n.timestamp)
        lines = []
        for n in vis:
            lines.append(f"[{n.agent or 'sys'}] {n.label}: {n.detail}")
        for f in self.facts[-k:]:
            lines.append(f"[memory] {f}")
        return "\n".join(lines) if lines else "(empty)"

    def snapshot_bytes(self) -> int:
        """记忆占用空间 = 压缩后仅可见面的字节数。"""
        return self.graph.size_bytes(visible_only=True)
