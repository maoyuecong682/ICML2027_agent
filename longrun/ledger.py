"""LLM 调用记账：把 A/B 与 mem0 内部（实体抽取、关系更新）的 token 都记到同一本账上。

做法是 patch `Completions.create`，用 contextvar 标调用来源。这样 mem0 自己发起的
LLM 调用（它不向外暴露 usage）也能被计量，避免"记忆开销"被漏掉。
"""
from __future__ import annotations

import time
from collections import defaultdict

# 用全局标记而不是 contextvar：mem0 内部走线程池（executor.submit），
# contextvar 不会传播到子线程，导致它的 LLM 调用被记成 other。
# 我们的流程是串行的，全局标记足够，而且能把 mem0 的开销正确归因。
_CUR = {"tag": "other"}
LEDGER: list[dict] = []


def tag(name: str):
    return _TagCtx(name)


class _TagCtx:
    def __init__(self, name: str):
        self.name = name
        self.prev = "other"

    def __enter__(self):
        self.prev = _CUR["tag"]
        _CUR["tag"] = self.name
        return self

    def __exit__(self, *exc):
        _CUR["tag"] = self.prev
        return False


def install() -> bool:
    """幂等 patch。返回是否本次完成 patch。"""
    try:
        from openai.resources.chat.completions import Completions
    except Exception:
        return False
    orig = Completions.create
    if getattr(orig, "_ledger_patched", False):
        return False

    def wrapper(self, *a, **kw):
        t0 = time.perf_counter()
        r = orig(self, *a, **kw)
        ms = round((time.perf_counter() - t0) * 1000, 1)
        u = getattr(r, "usage", None)
        LEDGER.append({
            "tag": _CUR["tag"],
            "model": kw.get("model") or (a[0] if a else "?"),
            "in": getattr(u, "prompt_tokens", 0) or 0,
            "out": getattr(u, "completion_tokens", 0) or 0,
            "ms": ms,
            "t": time.time(),
        })
        return r

    wrapper._ledger_patched = True
    Completions.create = wrapper
    return True


def summary() -> dict:
    """按来源分组汇总。"""
    g = defaultdict(lambda: {"calls": 0, "in": 0, "out": 0, "ms": 0.0})
    for e in LEDGER:
        d = g[e["tag"]]
        d["calls"] += 1
        d["in"] += e["in"]
        d["out"] += e["out"]
        d["ms"] += e["ms"]
    out = {k: {**v, "ms": round(v["ms"], 1)} for k, v in g.items()}
    tot = {"calls": sum(v["calls"] for v in out.values()),
           "in": sum(v["in"] for v in out.values()),
           "out": sum(v["out"] for v in out.values()),
           "ms": round(sum(v["ms"] for v in out.values()), 1)}
    return {"by_tag": dict(out), "total": tot}


def reset():
    LEDGER.clear()
