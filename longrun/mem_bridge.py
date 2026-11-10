"""mem0 图记忆封装（Mem0 0.1.118 · graph_store = kuzu 嵌入式图库）。

为什么锁 0.1.118：mem0 新版（1.x/2.x）已把 graph memory 从 OSS 移除，
`enable_graph` / `graph_store` 连同 Neo4j/Memgraph/Kuzu 驱动一起删掉了。

三个后端的选择理由：
  · llm       = openai 兼容 → 指向 https://api.deepseek.com/v1（deepseek-flash）
  · embedder  = langchain 自定义 Embeddings（DeepSeek 没有 /v1/embeddings，实测 404）
  · graph     = kuzu（嵌入式，本地文件，无需 docker；本机没有 docker，Neo4j 起不来）

Mem0 的"图压缩"就发生在这里：
  原文句子 --LLM抽实体/关系--> (entity, CONNECTED_TO, entity) 三元组
  新实体与旧实体按 name/embedding 比对 → 命中则 UPDATE 合并，不新增节点
  矛盾关系被删边 → 图规模不随对话轮数线性膨胀
所以 footprint 里要同时报：原始文本字节 vs 记忆条目数 vs 图节点/边数。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, MEM_ROOT, MODEL

# mem0 默认把 config.json / history.db / telemetry 迁移库写到 ~/.mem0，
# 多个进程会争同一个 qdrant local 锁（portalocker 报 AlreadyLocked）。
# 这里把它整体搬进本实验的独立目录，既隔离又免冲突。必须在 import mem0 之前设置。
os.environ.setdefault("MEM0_DIR", str(MEM_ROOT / "mem0_home"))
os.environ.setdefault("MEM0_TELEMETRY", "False")

from langchain.embeddings.base import Embeddings  # noqa: E402

try:
    from local_embed import DIM, embed as _ngram_embed
except Exception:  # pragma: no cover
    DIM = 256

    def _ngram_embed(t):
        return [0.0] * DIM


class LocalNgramEmbeddings(Embeddings):
    """确定性字符 n-gram 向量。只保留词面重合信息，不理解同义改写。"""

    def __init__(self, dim: int = DIM):
        self.dim = dim

    def embed_documents(self, texts):
        return [_ngram_embed(t) for t in texts]

    def embed_query(self, text):
        return _ngram_embed(text)


def _dir_bytes(p: Path) -> int:
    if not p.exists():
        return 0
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


class ExecMemory:
    def __init__(self, user_id: str, root: Path | None = None, tag: str | None = None,
                 reset: bool = False):
        from mem0 import Memory

        self.user_id = user_id
        base = Path(root or MEM_ROOT)
        self.root = base / tag if tag else base
        self.root.mkdir(parents=True, exist_ok=True)
        qdrant_path = self.root / "qdrant"
        kuzu_path = self.root / "kuzu"
        if reset:
            import shutil
            for p in (qdrant_path, kuzu_path):
                shutil.rmtree(p, ignore_errors=True)
        qdrant_path.mkdir(exist_ok=True)
        kuzu_path.mkdir(exist_ok=True)

        cfg = {
            "llm": {
                "provider": "openai",
                "config": {"model": MODEL, "api_key": DEEPSEEK_API_KEY,
                           "openai_base_url": DEEPSEEK_BASE_URL + "/v1",
                           "temperature": 0.1, "max_tokens": 4000},
            },
            "embedder": {
                "provider": "langchain",
                "config": {"model": LocalNgramEmbeddings(), "embedding_dims": DIM},
            },
            "vector_store": {
                "provider": "qdrant",
                "config": {"collection_name": "longrun_mem", "path": str(qdrant_path),
                           "embedding_model_dims": DIM, "on_disk": True},
            },
            "graph_store": {
                "provider": "kuzu",
                "config": {"db": str(kuzu_path / "graph.kuzu")},
            },
            "version": "v1.1",
        }
        self.m = Memory.from_config(cfg)
        self._extra_bytes = 0

    # ---------------------------------------------------------------- 写

    def add(self, text: str, meta: dict | None = None) -> list[dict]:
        """把一轮执行压进记忆。返回 mem0 的事件列表（ADD/UPDATE/DELETE）。"""
        raw = text or ""
        self._extra_bytes += len(raw.encode("utf-8"))
        try:
            out = self.m.add(raw, user_id=self.user_id, metadata=meta or {})
        except Exception as e:
            return [{"event": "ERROR", "error": str(e)[:160]}]
        res = out.get("results", out) if isinstance(out, dict) else out
        ev = []
        for r in (res or []):
            if isinstance(r, dict):
                ev.append({"event": r.get("event", "ADD"),
                           "memory": (r.get("memory") or "")[:90]})
        return ev

    # ---------------------------------------------------------------- 读

    def recall(self, query: str, k: int = 6) -> list[dict]:
        try:
            out = self.m.search(query, user_id=self.user_id, limit=k)
        except Exception:
            return []
        res = out.get("results", out) if isinstance(out, dict) else out
        hits = []
        for r in (res or []):
            if isinstance(r, dict) and r.get("memory"):
                hits.append({"memory": r["memory"], "score": round(float(r.get("score") or 0), 3)})
        return hits[:k]

    def all_items(self) -> list[dict]:
        try:
            out = self.m.get_all(user_id=self.user_id)
        except Exception:
            return []
        res = out.get("results", out) if isinstance(out, dict) else out
        return [r for r in (res or []) if isinstance(r, dict)]

    # ---------------------------------------------------------------- 占用

    def graph_stats(self) -> dict:
        st = {"nodes": 0, "edges": 0, "labels": [], "error": None}
        try:
            conn = self.m.graph.graph          # kuzu.Connection
            q = conn.execute("MATCH (n:Entity) RETURN count(n)")
            st["nodes"] = int(q.get_next()[0]) if q.has_next() else 0
            q2 = conn.execute("MATCH ()-[r:CONNECTED_TO]->() RETURN count(r)")
            st["edges"] = int(q2.get_next()[0]) if q2.has_next() else 0
        except Exception as e:
            st["error"] = str(e)[:200]
        return st

    def footprint(self) -> dict:
        items = self.all_items()
        blob = json.dumps(items, ensure_ascii=False)
        g = self.graph_stats()
        return {
            "user_id": self.user_id,
            "n_memories": len(items),
            "mem_json_bytes": len(blob.encode("utf-8")),
            "raw_text_bytes": self._extra_bytes,
            "graph_nodes": g["nodes"],
            "graph_edges": g["edges"],
            "graph_error": g["error"],
            "disk_bytes": _dir_bytes(self.root),
            "disk_kuzu_bytes": _dir_bytes(self.root / "kuzu"),
            "disk_qdrant_bytes": _dir_bytes(self.root / "qdrant"),
        }
