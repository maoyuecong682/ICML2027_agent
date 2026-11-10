"""LLM 后端抽象：DeepSeek（真实） + Mock（离线，可复现）。

两者接口一致：chat(system, user, role, task_id, tools, history)
  -> {"content": str, "tool_calls": [{"name", "arguments"(json str)}],
      "verdict": optional, "usage": {"prompt_tokens","completion_tokens"}}

- DeepSeekBackend：走 OpenAI 兼容协议，model=deepseek-flash，读取 response.usage（真实计费）。
- MockBackend：离线运行。用 tiktoken 对“真实 prompt/completion 文本”精确计 token，
  工具决策由外部载入的“求解脚本”（oracle plan）驱动 —— 等价于真实 LLM 会产生的计划，
  从而让图构建/记忆/压缩/计时/可视化全部真实跑通。
"""
import json
import tiktoken

from config import (DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL,
                    EFFORT)


class LLMBackend:
    def __init__(self):
        self.total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}

    def chat(self, system, user, role="planner", task_id=None,
             tools=None, history=None):
        raise NotImplementedError


class DeepSeekBackend(LLMBackend):
    def __init__(self):
        super().__init__()
        from openai import OpenAI
        self.client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
        self.model = DEEPSEEK_MODEL

    def chat(self, system, user, role="planner", task_id=None,
             tools=None, history=None):
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user}]
        kwargs = dict(model=self.model, messages=messages, temperature=0.0)
        if EFFORT:
            kwargs["extra_body"] = {"effort": EFFORT}
        if role == "planner" and tools:
            kwargs["tools"] = tools          # OpenAI 工具格式
            kwargs["tool_choice"] = "auto"
        resp = self.client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        tool_calls = []
        if getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                tool_calls.append({"name": tc.function.name,
                                   "arguments": tc.function.arguments})
        u = resp.usage
        self.total_usage["prompt_tokens"] += u.prompt_tokens
        self.total_usage["completion_tokens"] += u.completion_tokens
        self.total_usage["calls"] += 1
        return {"content": msg.content or "",
                "tool_calls": tool_calls,
                "usage": {"prompt_tokens": u.prompt_tokens,
                          "completion_tokens": u.completion_tokens}}


class MockBackend(LLMBackend):
    """离线后端：脚本驱动 + 真实 token 计数。"""
    def __init__(self):
        super().__init__()
        self.scripts = {}      # task_id -> list[step]
        self._idx = {}         # task_id -> cursor
        self._planner_done = False
        try:
            self.enc = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self.enc = None

    def load_script(self, task_id, steps):
        self.scripts[task_id] = list(steps)
        self._idx[task_id] = 0
        self._planner_done = False  # 每个任务开始时复位，避免跨任务串味

    def _count(self, text):
        if self.enc:
            return len(self.enc.encode(text))
        return max(1, len(text) // 4)

    def chat(self, system, user, role="planner", task_id=None,
             tools=None, history=None):
        prompt_text = system + "\n" + user
        if tools:
            prompt_text += "\n" + json.dumps(tools, ensure_ascii=False)
        pt = self._count(prompt_text)

        if role == "planner":
            steps = self.scripts.get(task_id, [])
            i = self._idx.get(task_id, 0)
            if i >= len(steps) or "done" in steps[i]:
                if i < len(steps):
                    completion = steps[i].get("done", "DONE.")
                else:
                    completion = "DONE: task finished."
                self._planner_done = True
                ct = self._count(completion)
                self.total_usage["prompt_tokens"] += pt
                self.total_usage["completion_tokens"] += ct
                self.total_usage["calls"] += 1
                return {"content": completion, "tool_calls": [],
                        "usage": {"prompt_tokens": pt, "completion_tokens": ct}}
            step = steps[i]
            self._idx[task_id] = i + 1
            tc = step["tool"]
            completion = json.dumps({"name": tc["name"],
                                     "arguments": tc["arguments"]},
                                    ensure_ascii=False)
            ct = self._count(completion)
            self.total_usage["prompt_tokens"] += pt
            self.total_usage["completion_tokens"] += ct
            self.total_usage["calls"] += 1
            return {"content": "",
                    "tool_calls": [{"name": tc["name"],
                                    "arguments": json.dumps(tc["arguments"],
                                                           ensure_ascii=False)}],
                    "usage": {"prompt_tokens": pt, "completion_tokens": ct}}
        else:  # critic
            if self._planner_done:
                verdict, completion = "done", "VERDICT: done"
            else:
                verdict, completion = "progress", "VERDICT: progress"
            ct = self._count(completion)
            self.total_usage["prompt_tokens"] += pt
            self.total_usage["completion_tokens"] += ct
            self.total_usage["calls"] += 1
            return {"content": completion, "verdict": verdict, "tool_calls": [],
                    "usage": {"prompt_tokens": pt, "completion_tokens": ct}}


def make_backend(kind: str = "mock") -> LLMBackend:
    if kind == "deepseek":
        return DeepSeekBackend()
    return MockBackend()
