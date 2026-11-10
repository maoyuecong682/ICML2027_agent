"""全局配置：DeepSeek 连接 + 双智能体/压缩超参。

说明：
- 默认 BACKEND=mock 是因为提供的 DeepSeek Key 返回 Insufficient Balance（余额不足），
  无法做在线推理。改成 BACKEND=deepseek 并填入有余额的 Key 即可真实联网运行。
- deepseek-flash 即 DeepSeek-V4.1-Flash（官方 models 列表已确认存在）。
"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
BACKEND = os.getenv("BACKEND", "mock")          # "deepseek" 或 "mock"
EFFORT = os.getenv("EFFORT", "low")             # deepseek-flash 支持 low/high/max

# 双智能体长程执行参数（直接用字面量，避免被 shell 环境变量意外覆盖）
MAX_STEPS = 14        # 长程任务最大步数
COMPRESS_EVERY = 2    # 每 N 步触发一次 memo 压缩
MERGE_WINDOW = 2      # 连续相同工具调用 >= 该值则合并为 summary 节点
KEEP_RECENT = 5       # 压缩后保留的最近可见节点数（可见面大小）

RESULTS_DIR = BASE_DIR / "results"
GRAPHS_DIR = RESULTS_DIR / "graphs"
RESULTS_DIR.mkdir(exist_ok=True)
GRAPHS_DIR.mkdir(exist_ok=True)
