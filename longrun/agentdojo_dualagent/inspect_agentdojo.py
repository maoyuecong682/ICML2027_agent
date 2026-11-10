"""探查 agentdojo 真实 API，供 bridge/solutions 编写使用（装好依赖后运行）。

输出：
- 目标 suite 的任务 id / prompt
- 工具名、描述、参数 schema
- 工具调用约定（tool.func(env, **kw) 还是 tool(env, **kw)）
- 选定任务的 utility 判定源码（决定 final answer 必须包含什么）
"""
import inspect
import json
import sys
import traceback

PY = "D:/Lironghua/隐私子刊/longrun/agentdojo_dualagent/venv/Scripts/python.exe"

SUITES = ["banking", "workspace"]
TASK_IDS = ["user_task_0", "user_task_1", "user_task_2"]


def main():
    import copy
    import agentdojo
    from agentdojo import load_suite
    print("agentdojo version:", getattr(agentdojo, "__version__", "?"))

    for suite_name in SUITES:
        print("\n" + "=" * 70)
        print("SUITE:", suite_name)
        print("=" * 70)
        try:
            suite = load_suite(suite_name)
        except Exception as e:
            print("load_suite FAILED:", repr(e))
            traceback.print_exc()
            continue
        print("suite type:", type(suite))
        print("has .tasks:", hasattr(suite, "tasks"), "| has .tools:", hasattr(suite, "tools"),
              "| has .env:", hasattr(suite, "env"))
        if hasattr(suite, "tasks"):
            print("task ids:", list(suite.tasks.keys())[:20])
        if hasattr(suite, "tools"):
            print("tool names:", [getattr(t, "name", "?") for t in suite.tools][:40])

        # 选第一个可加载的任务做深探
        if not hasattr(suite, "tasks"):
            continue
        for tid in TASK_IDS:
            if tid not in suite.tasks:
                continue
            task = suite.tasks[tid]
            print("\n--- TASK", tid, "---")
            print("prompt:", repr(task.prompt)[:400])
            print("task attrs:", [a for a in dir(task) if not a.startswith("_")])
            # utility 源码
            try:
                print("UTILITY SOURCE:\n", inspect.getsource(task.utility))
            except Exception as e:
                print("cannot get utility source:", e)
            # 工具调用约定测试
            env = copy.deepcopy(suite.env)
            tools = suite.tools
            if tools:
                t0 = tools[0]
                print("TOOL0 name:", getattr(t0, "name", "?"),
                      "| params:", json.dumps(getattr(t0, "parameters", None), ensure_ascii=False)[:300])
                # 尝试两种调用约定
                for conv in ["func", "call"]:
                    try:
                        if conv == "func":
                            r = t0.func(env)
                        else:
                            r = t0(env)
                        print(f"call via {conv} OK ->", str(r)[:120])
                        break
                    except Exception as e:
                        print(f"call via {conv} failed:", repr(e)[:120])
            break  # 每个 suite 只深探一个任务


if __name__ == "__main__":
    main()
