"""A/B 双智能体长程执行系统（LangGraph StateGraph 实现）。

节点：
  planner_A  (Agent A：规划/执行)  —— 基于压缩记忆 + 观察 决定下一步工具调用或宣告完成
  tool_exec  (执行器)              —— 在 env 上调用工具，记录 observation
  critic_B   (Agent B：校验/复盘)  —— 判断进展/错误/冗余/完成，决定是否触发压缩
  compress   (memo 压缩)          —— 调用 ExecutionGraph.compress（非破坏性）
  route      (路由)               —— 终止或回到 planner_A

关键设计：ExecutionGraph / ExecutionMemory / env / backend / tool_callable 都放在模块级
REGISTRY 里，state dict 只携带可序列化的轻量字段（task_id、计数、文本）。这样 LangGraph
内部对 state 的合并/拷贝不会碰到图对象，彻底规避序列化问题。
"""
from __future__ import annotations
import json
import sys
import time
import uuid
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, END, START

from execution_graph import ExecutionGraph
from memory import ExecutionMemory
from config import MAX_STEPS, COMPRESS_EVERY, MERGE_WINDOW, KEEP_RECENT

REG: dict = {}


def set_registry(task_id, env, tool_callable, backend):
    graph = ExecutionGraph()
    memory = ExecutionMemory(graph)
    REG[task_id] = {"env": env, "tool_callable": tool_callable,
                    "backend": backend, "graph": graph, "memory": memory}


PLANNER_SYS = """You are Agent A (Planner/Executor) in a long-horizon dual-agent system built on LangGraph.
You solve an agentdojo task using external tools.
TASK: {task}
COMPRESSED EXECUTION MEMORY (visible surface of the memo graph):
{memory}
AVAILABLE TOOLS:
{tools}
Rules:
- Decide the SINGLE next tool call that makes progress toward the task.
- Reply ONLY with a JSON tool call: {{"name": <tool_name>, "arguments": {{...}}}}
  OR reply with DONE followed by the final answer if the task is complete.
- Do NOT repeat a call that already achieved its effect.
"""

CRITIC_SYS = """You are Agent B (Critic/Verifier) in a long-horizon dual-agent system.
TASK: {task}
Given the last action and its observation, judge whether the task is complete,
whether the last action errored, and whether recent steps are redundant
(repeated identical calls).
Reply one line: VERDICT: <progress|error|done|redundant>. Then a short note.
"""


def _uid(prefix="n"):
    return prefix + uuid.uuid4().hex[:8]


def _fmt_tools(tools):
    out = []
    for t in tools:
        out.append(f"- {t['name']}: {t.get('description','')}\n"
                   f"  params: {json.dumps(t.get('parameters', {}), ensure_ascii=False)}")
    return "\n".join(out)


class AgentState(TypedDict):
    task_id: str
    task_prompt: str
    tools: list
    messages: Annotated[list, lambda a, b: a + b]
    step: int
    max_steps: int
    status: str
    last_action: dict
    last_observation: str
    last_action_ok: bool
    compress_flag: bool
    critique: str


def node_planner_A(state):
    reg = REG[state["task_id"]]
    backend = reg["backend"]
    g = reg["graph"]
    mem = reg["memory"].context_text()
    obs = state.get("last_observation", "(none)")
    system_prompt = PLANNER_SYS.format(task=state["task_prompt"], memory=mem,
                                       tools=_fmt_tools(state["tools"]))
    user = (f"Step {state['step']+1}/{state['max_steps']}. "
            f"Last observation: {obs}\nProvide the next action.")
    resp = backend.chat(system=system_prompt, user=user, role="planner",
                        task_id=state["task_id"], tools=state["tools"],
                        history=state["messages"])
    pn = g.add_node(type="planner", label=f"A:plan#{state['step']+1}",
                    detail=(resp.get("content", "") or "")[:200], agent="A",
                    tokens=resp["usage"]["prompt_tokens"] + resp["usage"]["completion_tokens"])
    if resp["tool_calls"]:
        tc = resp["tool_calls"][0]
        cid = _uid("call_")
        asst = {"role": "assistant", "content": resp.get("content", ""),
                "tool_calls": [{"id": cid, "name": tc["name"],
                                "arguments": tc["arguments"]}]}
        tcn = g.add_node(type="tool_call", label=f"A→{tc['name']}",
                         detail=tc["arguments"], agent="A", parent_ids=[pn],
                         meta={"tool": tc["name"], "args": tc["arguments"]})
        g.add_edge(pn, tcn, "control")
        return {"messages": [asst],
                "last_action": {"name": tc["name"], "arguments": tc["arguments"], "id": cid},
                "status": "running"}
    else:
        final = resp.get("content", "")
        asst = {"role": "assistant", "content": final}
        on = g.add_node(type="observation", label="A:DONE", detail=final[:200],
                        agent="A", parent_ids=[pn], meta={"final_answer": final})
        g.add_edge(pn, on, "control")
        return {"messages": [asst], "status": "done"}


def node_tool_exec(state):
    la = state.get("last_action")
    if not la:
        return {}
    reg = REG[state["task_id"]]
    g = reg["graph"]
    fn = reg["tool_callable"].get(la["name"])
    obs_str = ""
    ok = True
    try:
        if fn is None:
            raise ValueError(f"no tool named {la['name']}")
        obs = fn(reg["env"], **json.loads(la["arguments"]))
        obs_str = str(obs)
    except Exception as e:
        obs_str = f"ERROR: {e}"
        ok = False
    tcnodes = [n for n in g.nodes.values() if n.type == "tool_call"]
    tcid = tcnodes[-1].id if tcnodes else None
    toolmsg = {"role": "tool", "tool_call_id": la["id"],
               "content": obs_str, "name": la["name"]}
    on = g.add_node(type="observation", label=f"obs:{la['name']}",
                    detail=obs_str[:200], agent="system",
                    parent_ids=[tcid] if tcid else [])
    if tcid:
        g.add_edge(tcid, on, "data")
    reg["memory"].add_fact(f"Action {la['name']} -> {obs_str[:120]}")
    return {"messages": [toolmsg], "last_observation": obs_str,
            "last_action": None, "step": state["step"] + 1,
            "last_action_ok": ok}


def node_critic_B(state):
    reg = REG[state["task_id"]]
    backend = reg["backend"]
    la = state.get("last_action") or {}
    obs = state.get("last_observation", "")
    gsum = reg["graph"].summary()
    system_prompt = CRITIC_SYS.format(task=state["task_prompt"])
    user = (f"Last action: {la.get('name')}({la.get('arguments')})\n"
            f"Observation: {obs}\nGraph summary: {gsum}\nVerdict?")
    resp = backend.chat(system=system_prompt, user=user, role="critic",
                        task_id=state["task_id"])
    g = reg["graph"]
    g.add_node(type="critic", label="B:verify",
               detail=(resp.get("verdict") or "") + " " + (resp.get("content", "")[:120]),
               agent="B",
               tokens=resp["usage"]["prompt_tokens"] + resp["usage"]["completion_tokens"])
    verdict = resp.get("verdict", "progress")
    compress_flag = (state["step"] % COMPRESS_EVERY == 0) or (verdict == "redundant")
    return {"status": state["status"], "critique": resp.get("content", ""),
            "compress_flag": compress_flag}


def node_compress(state):
    g = REG[state["task_id"]]["graph"]
    g.compress(llm=REG[state["task_id"]]["backend"],
               merge_window=MERGE_WINDOW, keep_recent=KEEP_RECENT)
    return {}


def route_after_planner(state):
    return "exec" if state.get("last_action") else "critic"


def route_after_critic(state):
    return "compress" if state.get("compress_flag") else "route"


def should_continue(state):
    if state["status"] == "done" or state["step"] >= state["max_steps"]:
        return "end"
    return "planner"


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("planner_A", node_planner_A)
    g.add_node("tool_exec", node_tool_exec)
    g.add_node("critic_B", node_critic_B)
    g.add_node("compress", node_compress)
    g.add_node("route", lambda s: {})
    g.add_edge(START, "planner_A")
    g.add_conditional_edges("planner_A", route_after_planner,
                            {"exec": "tool_exec", "critic": "critic_B"})
    g.add_edge("tool_exec", "critic_B")
    g.add_conditional_edges("critic_B", route_after_critic,
                            {"compress": "compress", "route": "route"})
    g.add_edge("compress", "route")
    g.add_conditional_edges("route", should_continue,
                            {"planner": "planner_A", "end": END})
    return g.compile()


def run_task(task_id, task_prompt, tools_spec, tool_callable, env, backend,
             max_steps=MAX_STEPS):
    set_registry(task_id, env, tool_callable, backend)
    init = dict(
        task_id=task_id, task_prompt=task_prompt, tools=tools_spec,
        messages=[{"role": "system", "content": "You are a helpful agent solving tasks via tools."},
                  {"role": "user", "content": task_prompt}],
        step=0, max_steps=max_steps, status="running",
        last_action=None, last_observation="", last_action_ok=True,
        compress_flag=False, critique="",
    )
    t0 = time.perf_counter()
    app = build_graph()
    final = app.invoke(init)
    t1 = time.perf_counter()
    graph = REG[task_id]["graph"]
    memory = REG[task_id]["memory"]
    return final, (t1 - t0), graph, memory
