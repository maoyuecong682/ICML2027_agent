"""两档对照基线：完整历史 / 普通摘要。

为什么必须有：只有"图记忆 vs 无记忆"两档，说不出压缩本身值不值。
论文要的是同一个任务链下四档对照——

    none     不记忆
    graph    mem0 图记忆（本方法所处的位置）
    summary  普通摘要（一段话，每轮合并）
    full     完整历史原文（暴露上限）

接口与 `mem_bridge.ExecMemory` 完全对齐（recall / add / footprint / graph_stats /
all_items / root / user_id），所以 `long_graph.build_graph` 一行都不用改，直接换实现。

`full` 的 recall 故意**不截断**：完整历史的含义就是"把一切都留在手边"，
它既是成本上限，也是隐私暴露的上限，用作参照系。
"""
from __future__ import annotations

import json
from pathlib import Path

from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, MEM_ROOT, MODEL


def _dir_bytes(p: Path) -> int:
    if not p.exists():
        return 0
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


class _BaseMem:
    kind = "base"

    def __init__(self, user_id: str, tag: str | None = None):
        self.user_id = user_id
        self.root = (MEM_ROOT / (tag or "baseline")) / self.kind
        self.root.mkdir(parents=True, exist_ok=True)
        self.store = self.root / "items.json"
        self._items: list[dict] = []
        self._raw_bytes = 0
        self._load()

    # -- 持久化：都落一个小 json，footprint 才有东西可量
    def _load(self):
        if self.store.exists():
            try:
                d = json.loads(self.store.read_text(encoding="utf-8"))
                self._items = d.get("items", [])
                self._raw_bytes = d.get("raw_bytes", 0)
            except Exception:
                self._items, self._raw_bytes = [], 0

    def _save(self):
        self.store.write_text(json.dumps(
            {"items": self._items, "raw_bytes": self._raw_bytes},
            ensure_ascii=False), encoding="utf-8")

    # -- 接口
    def all_items(self) -> list[dict]:
        return list(self._items)

    def graph_stats(self) -> dict:
        return {"nodes": 0, "edges": 0, "labels": [], "error": None}

    def footprint(self) -> dict:
        blob = json.dumps(self._items, ensure_ascii=False)
        return {
            "user_id": self.user_id,
            "n_memories": len(self._items),
            "mem_json_bytes": len(blob.encode("utf-8")),
            "raw_text_bytes": self._raw_bytes,
            "graph_nodes": 0, "graph_edges": 0, "graph_error": None,
            "disk_bytes": _dir_bytes(self.root),
            "disk_kuzu_bytes": 0, "disk_qdrant_bytes": 0,
        }

    def add(self, text: str, meta: dict | None = None) -> list[dict]:
        raise NotImplementedError

    def recall(self, query: str, k: int = 6) -> list[dict]:
        raise NotImplementedError


class FullHistoryMemory(_BaseMem):
    """完整历史：一条不删、一句不压，recall 全给。"""

    kind = "full"

    def add(self, text: str, meta: dict | None = None) -> list[dict]:
        raw = text or ""
        self._raw_bytes += len(raw.encode("utf-8"))
        self._items.append({"id": len(self._items) + 1, "memory": raw})
        self._save()
        return [{"event": "ADD", "memory": raw}]

    def recall(self, query: str, k: int = 6) -> list[dict]:
        # 故意不按 k 截断：完整历史就是要全部留在上下文里
        return [{"memory": it["memory"], "score": 1.0, "id": it["id"]}
                for it in self._items]


SUMMARY_SYS = (
    "你在维护一份跨任务的执行摘要。把「已有摘要」和「本轮新记录」合并成一段摘要。\n"
    "要求：不超过 180 字；保留金额、对象（IBAN 或机构名）、日期、事由这些关键字段；"
    "不要评论、不要建议、不要编造；只输出摘要正文。"
)


class SummaryMemory(_BaseMem):
    """普通摘要：整段历史压成一段话，每轮重新合并。"""

    kind = "summary"

    def __init__(self, user_id: str, tag: str | None = None):
        super().__init__(user_id, tag)
        from openai import OpenAI
        self.client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    @property
    def summary(self) -> str:
        return self._items[0]["memory"] if self._items else ""

    def add(self, text: str, meta: dict | None = None) -> list[dict]:
        import ledger
        raw = text or ""
        self._raw_bytes += len(raw.encode("utf-8"))
        with ledger.tag("baseline_summary"):
            r = self.client.chat.completions.create(
                model=MODEL, temperature=0,
                messages=[{"role": "system", "content": SUMMARY_SYS},
                          {"role": "user", "content":
                           f"# 已有摘要\n{self.summary or '（空）'}\n\n# 本轮新记录\n{raw}"}])
        new = (r.choices[0].message.content or "").strip()
        before = self.summary
        self._items = [{"id": 1, "memory": new}]
        self._save()
        return [{"event": "UPDATE" if before else "ADD", "memory": new}]

    def recall(self, query: str, k: int = 6) -> list[dict]:
        s = self.summary
        return [{"memory": s, "score": 1.0, "id": 1}] if s else []


class NullMemory(_BaseMem):
    """不记忆。保留同一套接口，调用方不用写分支。"""

    kind = "none"

    def add(self, text: str, meta: dict | None = None) -> list[dict]:
        return []

    def recall(self, query: str, k: int = 6) -> list[dict]:
        return []


def make_memory(kind: str, user_id: str, tag: str | None = None):
    """工厂：graph 走 mem0（惰性 import，避免无记忆档也去抢 kuzu/qdrant 的锁）。"""
    kind = (kind or "graph").lower()
    if kind == "graph":
        from mem_bridge import ExecMemory
        return ExecMemory(user_id, tag=tag)
    if kind == "full":
        return FullHistoryMemory(user_id, tag)
    if kind == "summary":
        return SummaryMemory(user_id, tag)
    if kind == "none":
        return NullMemory(user_id, tag)
    raise ValueError(f"未知记忆类型：{kind}")
