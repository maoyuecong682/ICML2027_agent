"""最小连通测试：mem0 + kuzu 图库 + DeepSeek LLM + 本地 embedder。

    python test_mem.py
"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")

import ledger

ledger.install()

from mem_bridge import ExecMemory  # noqa: E402

SAMPLE = [
    "Agent A 在第 1 轮读取了用户账户，确认用户是 Emma Johnson，住在 1234 Elm Street。",
    "Agent A 在第 1 轮读到 2022-03-07 有一笔 Sushi dinner 支出 10.00，收款方是 GB29NWBK60161331926819。",
    "Agent B 在第 2 轮根据上面的收款人和金额执行了退款，金额必须等于 10.00。",
]


def main():
    m = ExecMemory("probe_user", reset=True)
    print("mem0 初始化 OK")
    for i, s in enumerate(SAMPLE, 1):
        ev = m.add(s, meta={"round": i})
        print(f"  add#{i} -> {ev}")
    print("\nsearch '退款金额是多少' ->")
    for h in m.recall("退款金额是多少", k=5):
        print("   ", h)
    print("\nfootprint:", m.footprint())
    print("\nledger:", ledger.summary())


if __name__ == "__main__":
    main()
