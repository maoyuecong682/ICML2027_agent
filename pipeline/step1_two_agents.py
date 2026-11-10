"""第一步：双 agent（A、B）+ AgentDojo travel 任务的最小跑通。

流程：
1. 加载 travel 套件的 user_task_0（EASY，订巴黎酒店任务）；
2. Agent A 在任务环境上执行（工具调用循环）；
3. A 的执行记录共享给 Agent B，B 在同一环境上继续并给出最终回答；
4. 用任务自带的 utility 判定任务是否完成（0/1）。
"""
import sys

from openai import OpenAI

from agentdojo.functions_runtime import FunctionsRuntime
from agentdojo.task_suite.load_suites import get_suite

from agents import AgentA, AgentB, to_openai_tools
from config import (DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, MODEL,
                    SUITE_VERSION, SUITE_NAME, TASK_ID, MAX_STEPS)

sys.stdout.reconfigure(encoding="utf-8")


def main():
    suite = get_suite(SUITE_VERSION, SUITE_NAME)
    task = suite.get_user_task_by_id(TASK_ID)

    env = task.init_environment(suite.load_and_inject_default_environment({}))
    pre_env = env.model_copy(deep=True)
    runtime = FunctionsRuntime(suite.tools)
    tools = to_openai_tools(suite.tools)

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    print(f"任务 {task.ID}（{task.DIFFICULTY}）: {task.PROMPT}\n")

    a = AgentA(client, MODEL)
    a_answer, a_transcript = a.run(task.PROMPT, tools, runtime, env, MAX_STEPS)
    print(f"[AgentA 最终回答] {a_answer}\n")
    print(f"[AgentA 执行记录（将共享给 B）] {len(a_transcript)} 条\n")

    b = AgentB(client, MODEL)
    b_answer, b_transcript = b.run(task.PROMPT, a_transcript, tools, runtime, env, MAX_STEPS)
    print(f"[AgentB 最终回答] {b_answer}\n")

    utility = task.utility(b_answer, pre_env, env)
    print(f"任务完成（utility）: {'1' if utility else '0'}")


if __name__ == "__main__":
    main()
