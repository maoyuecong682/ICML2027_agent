"""agentdojo 桥接层。

把 agentdojo 的 suite / task / env / tools 包装成本系统能用的形式：
- make_env(suite)：构造带默认注入环境的可变 env 对象（同一对象被双智能体全程改写）。
- make_tool_callable(suite)：返回 {工具名: callable(env, **kwargs)}，内部走
  FunctionsRuntime.run_function（agentdojo 官方调用约定）。
- tool_specs(suite)：给 Planner(A) 的提示词用的工具清单（名称/说明/参数 schema）。
- check_utility(task, model_output, pre_env, post_env)：直接调用任务自带的 utility 判定。
"""
from __future__ import annotations
import copy
from agentdojo.task_suite import get_suite
from agentdojo.functions_runtime import FunctionsRuntime


def load_suite(version: str, suite_name: str):
    return get_suite(version, suite_name)


def make_env(suite):
    """深拷贝一份用于 pre 比对；返回的是会被改写的那一份 env。"""
    return suite.load_and_inject_default_environment({})


def make_tool_callable(suite):
    rt = FunctionsRuntime(suite.tools)
    callables = {}

    def _mk(name):
        def _call(env, **kwargs):
            result, error = rt.run_function(env, name, kwargs)
            if error is not None:
                return f"ERROR: {error}"
            return str(result)
        return _call
    for t in suite.tools:
        callables[t.name] = _mk(t.name)
    return callables


def tool_specs(suite):
    specs = []
    for t in suite.tools:
        try:
            schema = t.parameters.model_json_schema()
        except Exception:
            schema = {}
        specs.append({
            "name": t.name,
            "description": t.description or "",
            "parameters": schema,
        })
    return specs


def check_utility(task, model_output: str, pre_env, post_env) -> bool:
    try:
        return bool(task.utility(model_output, pre_env, post_env))
    except Exception as e:
        # 部分任务 utility 需要 strict 关键字；退化为宽松判定
        try:
            return bool(task.utility(model_output, pre_env, post_env, strict=False))
        except Exception:
            return False


def get_task(suite, task_id: str):
    return suite.user_tasks[task_id]
