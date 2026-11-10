"""长程双智能体实验 · 全局配置。

与 ../pipeline 完全独立：自己的 venv、自己的 runs 目录、自己的 mem0 图记忆库。
"""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

# ---------------------------------------------------------------- 模型

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
MODEL = "deepseek-flash"

# 注意：deepseek-v4.1 / deepseek-v4.1-flash 会被 API 拒（400），不要改回这两个名字。

# ---------------------------------------------------------------- 任务

SUITE_VERSION = "v1.2"
# 两个代表性任务：
#   user_task_1 = 纯答复型（utility 只看答复里有没有 1050）→ 必须让 B 知道"要回答什么"
#   user_task_4 = 纯 env 型（utility 只看有没有 10.00 → GB29… 的交易）→ B 不必知道用户原话
TASKS = [("banking", "user_task_1"), ("banking", "user_task_4")]

# ---------------------------------------------------------------- 长程

MAX_ROUNDS = 12        # A/B 交替的总轮次上限（每轮 = 一个 agent 动一次）
MAX_TOOL_STEPS = 4     # 单个 agent 一次行动内允许的连续工具调用轮数
MEM_TOP_K = 6          # 每轮从图记忆检索的条目上限
RECENT_KEEP = 2        # 除记忆外，还保留最近几轮的原文（短期上下文）
MEM_EVERY_N = 1        # 每 N 轮写一次记忆；--fast 时改成 2，用来压记忆开销

# ---------------------------------------------------------------- 路径

ROOT = Path(__file__).parent
RUNS = ROOT / "runs"

# 记忆库必须放在纯 ASCII 路径：kuzu 的 C++ 层打不开含中文的路径
# （实测 D:\...\隐私子刊\... 报 "Cannot open file"，换 D:\Lironghua\_longrun_mem 正常）
MEM_ROOT = Path(os.environ.get("LONGRUN_MEM_ROOT", r"D:\Lironghua\_longrun_mem"))

RUNS.mkdir(exist_ok=True)
MEM_ROOT.mkdir(parents=True, exist_ok=True)

# 记忆作用域：两个任务串成一条链时共用一个 user_id，才能体现"携带记忆"
MEM_USER = "maoyu_banking"
