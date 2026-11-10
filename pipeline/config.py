"""第一步的最小配置：DeepSeek API + AgentDojo travel 套件。"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

# DeepSeek 后端（对应 最小预实验.md 中的注：API / model）
# 已定：全局统一 backbone = deepseek-flash（两个 agent、注入检测、后续推断模型都用它）。
# deepseek-v4.1-flash 会被 API 拒绝（400），不要再写这个名字。
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
MODEL = "deepseek-flash"

# AgentDojo 任务设置（travel 套件 v1.2，先用最简单的 user_task_0）
SUITE_VERSION = "v1.2"
SUITE_NAME = "travel"
TASK_ID = "user_task_0"

MAX_STEPS = 20  # 每个 agent 的最大工具调用轮数
