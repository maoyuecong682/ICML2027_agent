"""探针：确认 mem0 0.1.118 的 graph_store / embedder / llm 支持哪些 provider。

    python probe_mem0.py
"""
from __future__ import annotations

import sys
import traceback

sys.stdout.reconfigure(encoding="utf-8")

try:
    import mem0
    print("[ok] mem0", getattr(mem0, "__version__", "?"))
except Exception as e:
    print("[fail] import mem0:", e)
    raise SystemExit(1)

print("\n=== graph_store providers ===")
try:
    from mem0.memory.graph_memory import MemoryGraph
    from mem0.graphs.utils import GraphStoreFactory  # 可能路径不同
    print("GraphStoreFactory:", GraphStoreFactory)
except Exception:
    traceback.print_exc(limit=1)

print("\n=== 逐个 provider 工厂 ===")
for name in ["neo4j", "memgraph", "kuzu", "neptune", "kuzu_multi"]:
    try:
        from mem0.graphs.utils import GraphStoreFactory
        f = GraphStoreFactory.create(name, {})
        print(f"  {name:10s} -> OK {type(f).__name__}")
    except Exception as e:
        print(f"  {name:10s} -> {type(e).__name__}: {str(e)[:90]}")

print("\n=== embedder providers ===")
try:
    from mem0.utils.factory import EmbedderFactory
    print("  ", [m for m in dir(EmbedderFactory) if not m.startswith("_")])
    for name in ["openai", "huggingface", "ollama", "azure_openai", "lmstudio", "langchain"]:
        try:
            e = EmbedderFactory.create(name, {}, None)
            print(f"  {name:14s} -> OK {type(e).__name__}")
        except Exception as ex:
            print(f"  {name:14s} -> {type(ex).__name__}: {str(ex)[:70]}")
except Exception:
    traceback.print_exc(limit=1)

print("\n=== config 里认哪些键 ===")
import inspect
from mem0.memory.main import Memory
src = inspect.getsource(Memory.from_config)
print(src[:800])
