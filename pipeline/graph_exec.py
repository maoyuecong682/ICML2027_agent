"""执行图构建（LangGraph StateGraph）。

只做执行图：节点类型限定为 TASK / TURN / TOOL / SHARE / UTIL。
本模块不接记忆整理、不接隐私判断——那些是后续阶段的事。

图示：
    START → start_task → agent_turn ─┬─(tool_calls)→ tool_exec → agent_turn
                                     ├─(A 终结)→ handoff → agent_turn
                                     └─(B 终结)→ judge → END
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

import operator

from langgraph.graph import StateGraph, START, END
from openai import OpenAI

from agentdojo.functions_runtime import FunctionsRuntime
from agentdojo.task_suite.load_suites import get_suite

from agents import AgentA, AgentB, to_openai_tools
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, MODEL, MAX_STEPS

SYSTEM_A = AgentA.system_prompt
SYSTEM_B = AgentB.system_prompt


# ---------------------------------------------------------------- 运行上下文

@dataclass
class Ctx:
    """不可序列化的运行时对象放在这里，不进 LangGraph state。"""

    run_key: str
    suite: Any
    task: Any
    env: Any
    pre_env: Any
    runtime: Any
    tools: list
    client: Any
    model: str = MODEL
    counter: int = 0

    def next_id(self) -> str:
        self.counter += 1
        return f"n{self.counter}"


def make_ctx(suite_name: str, task_id: str, suite_version: str = "v1.2") -> Ctx:
    suite = get_suite(suite_version, suite_name)
    task = suite.get_user_task_by_id(task_id)
    env = task.init_environment(suite.load_and_inject_default_environment({}))
    pre_env = env.model_copy(deep=True)
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    return Ctx(
        run_key=f"{suite_name}/{task_id}",
        suite=suite,
        task=task,
        env=env,
        pre_env=pre_env,
        runtime=FunctionsRuntime(suite.tools),
        tools=to_openai_tools(suite.tools),
        client=client,
    )


# ---------------------------------------------------------------- State

class ExecState(TypedDict):
    agent: str                                   # "A" | "B"
    step: int
    status: str                                  # running | tool_pending | final
    messages: list
    pending_tools: list
    answers: dict
    transcript: Annotated[list, operator.add]
    nodes: Annotated[list, operator.add]
    edges: Annotated[list, operator.add]
    last_id: str
    utility: int


def _assistant_msg(msg) -> dict:
    return {
        "role": "assistant",
        "content": msg.content,
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in msg.tool_calls
        ],
    }


def _render_transcript(transcript: list) -> str:
    """与 agents.render_transcript 等价的渲染，但吃的是本模块的 transcript 结构。"""
    lines = []
    for t in transcript:
        if t["kind"] == "tool_call":
            args = t.get("args", {})
            lines.append(
                f"[步骤{t['step']}] Agent{t['agent']} 调用工具 {t['tool']}({args}) -> {str(t['result'])[:200]}"
            )
        else:
            lines.append(f"[步骤{t['step']}] Agent{t['agent']} 最终回答: {t['content']}")
    return "\n".join(lines)


def _summarize_args(args: dict) -> str:
    parts = []
    for k, v in args.items():
        s = str(v)
        if len(s) > 46:
            s = s[:43] + "..."
        parts.append(f"{k}={s}")
    out = ", ".join(parts)
    return out if len(out) <= 96 else out[:93] + "..."


# ---------------------------------------------------------------- 建图

def build_graph(ctx: Ctx):
    """返回 (compiled_graph, ctx)。节点函数闭包持有 ctx。"""

    def start_task(state: ExecState) -> dict:
        nid = ctx.next_id()
        node = {
            "id": nid,
            "type": "TASK",
            "label": ctx.task.ID,
            "meta": f"{ctx.suite.name} · {ctx.task.DIFFICULTY}",
            "detail": {"prompt": ctx.task.PROMPT},
        }
        return {
            "nodes": [node],
            "edges": [],
            "last_id": nid,
            "agent": "A",
            "step": 0,
            "status": "running",
            "answers": {},
            "messages": [
                {"role": "system", "content": SYSTEM_A},
                {"role": "user", "content": ctx.task.PROMPT},
            ],
            "pending_tools": [],
            "transcript": [],
        }

    def agent_turn(state: ExecState) -> dict:
        agent = state["agent"]
        step = state["step"] + 1
        if step > MAX_STEPS:
            nid = ctx.next_id()
            node = {"id": nid, "type": "TURN", "label": f"{agent}#{step}",
                    "meta": "超出 max_steps，强制收尾", "detail": {"tool_calls": [], "text": ""}}
            return {"nodes": [node],
                    "edges": [{"src": state["last_id"], "dst": nid, "rel": "NEXT"}],
                    "last_id": nid, "status": "final",
                    "answers": {**state["answers"], agent: ""},
                    "transcript": [{"agent": agent, "step": step, "kind": "final_answer",
                                    "content": ""}]}

        t0 = time.perf_counter()
        resp = ctx.client.chat.completions.create(
            model=ctx.model, messages=state["messages"], tools=ctx.tools
        )
        dt_ms = round((time.perf_counter() - t0) * 1000, 1)
        msg = resp.choices[0].message
        usage = resp.usage
        has_tool = bool(msg.tool_calls)

        nid = ctx.next_id()
        node = {
            "id": nid,
            "type": "TURN",
            "label": f"TURN {agent}#{step}",
            "meta": f"{ctx.model} · {dt_ms} ms · {usage.prompt_tokens}↑{usage.completion_tokens}↓",
            "detail": {
                "agent": agent,
                "step": step,
                "tool_calls": [tc.function.name for tc in (msg.tool_calls or [])],
                "text": (msg.content or "")[:400],
                "finish_reason": resp.choices[0].finish_reason,
            },
            "tokens": {"in": usage.prompt_tokens, "out": usage.completion_tokens},
            "t_ms": dt_ms,
            "api_call": True,
        }
        out = {
            "nodes": [node],
            "edges": [{"src": state["last_id"], "dst": nid, "rel": "NEXT"}],
            "last_id": nid,
            "step": step,
        }

        if has_tool:
            out["messages"] = state["messages"] + [_assistant_msg(msg)]
            out["status"] = "tool_pending"
            out["pending_tools"] = [
                {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments}
                for tc in msg.tool_calls
            ]
            return out

        final = msg.content or ""
        out["status"] = "final"
        out["answers"] = {**state["answers"], agent: final}
        out["transcript"] = [{"agent": agent, "step": step, "kind": "final_answer", "content": final}]
        return out

    def tool_exec(state: ExecState) -> dict:
        nodes, edges, msgs, transcript = [], [], list(state["messages"]), []
        prev = state["last_id"]
        for tc in state["pending_tools"]:
            args = json.loads(tc["arguments"]) if tc["arguments"] else {}
            result, err = ctx.runtime.run_function(ctx.env, tc["name"], args)
            output = err if err is not None else result
            msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": str(output)})

            nid = ctx.next_id()
            nodes.append({
                "id": nid,
                "type": "TOOL",
                "label": tc["name"],
                "meta": _summarize_args(args),
                "detail": {"name": tc["name"], "args": args, "result": str(output)[:600]},
                "sink": "local",
            })
            edges.append({"src": prev, "dst": nid, "rel": "CALLED"})
            prev = nid
            transcript.append({"agent": state["agent"], "step": state["step"],
                               "kind": "tool_call", "tool": tc["name"],
                               "args": args, "result": str(output)})
        return {"nodes": nodes, "edges": edges, "last_id": prev,
                "messages": msgs, "status": "running", "pending_tools": [],
                "transcript": transcript}

    def handoff(state: ExecState) -> dict:
        shared = _render_transcript(state["transcript"])
        nid = ctx.next_id()
        node = {
            "id": nid,
            "type": "SHARE",
            "label": "SHARE  A → B",
            "meta": f"{len(state['transcript'])} 条记录 · {len(shared)} 字符",
            "detail": {"from": "A", "to": "B", "payload_len": len(shared),
                       "payload": shared[:800]},
        }
        b_prompt = f"{ctx.task.PROMPT}\n\n[Agent A 共享给你的执行记录]\n{shared}"
        return {
            "nodes": [node],
            "edges": [{"src": state["last_id"], "dst": nid, "rel": "SHARED"}],
            "last_id": nid,
            "agent": "B",
            "step": 0,
            "status": "running",
            "messages": [
                {"role": "system", "content": SYSTEM_B},
                {"role": "user", "content": b_prompt},
            ],
        }

    def judge(state: ExecState) -> dict:
        utility = bool(ctx.task.utility(state["answers"].get("B", ""), ctx.pre_env, ctx.env))
        nid = ctx.next_id()
        node = {
            "id": nid,
            "type": "UTIL",
            "label": f"UTIL = {int(utility)}",
            "meta": "task.utility(answer_B, pre_env, env)",
            "detail": {"utility": int(utility)},
        }
        return {
            "nodes": [node],
            "edges": [{"src": state["last_id"], "dst": nid, "rel": "NEXT"}],
            "last_id": nid,
            "status": "final",
            "utility": int(utility),
        }

    def route_after_turn(state: ExecState) -> str:
        if state["status"] == "tool_pending":
            return "tool"
        return "a_done" if state["agent"] == "A" else "b_done"

    g = StateGraph(ExecState)
    g.add_node("start_task", start_task)
    g.add_node("agent_turn", agent_turn)
    g.add_node("tool_exec", tool_exec)
    g.add_node("handoff", handoff)
    g.add_node("judge", judge)

    g.add_edge(START, "start_task")
    g.add_edge("start_task", "agent_turn")
    g.add_conditional_edges("agent_turn", route_after_turn,
                            {"tool": "tool_exec", "a_done": "handoff", "b_done": "judge"})
    g.add_edge("tool_exec", "agent_turn")
    g.add_edge("handoff", "agent_turn")
    g.add_edge("judge", END)
    return g.compile(), ctx


def run_task(suite_name: str, task_id: str) -> dict:
    """跑一个任务，返回执行图记录。"""
    graph, ctx = build_graph(make_ctx(suite_name, task_id))
    init: ExecState = {"agent": "A", "step": 0, "status": "running", "messages": [],
                       "pending_tools": [], "answers": {}, "transcript": [],
                       "nodes": [], "edges": [], "last_id": ""}
    t0 = time.perf_counter()
    result = graph.invoke(init, config={"recursion_limit": 100})
    wall_ms = round((time.perf_counter() - t0) * 1000, 1)
    return {
        "run_key": ctx.run_key,
        "suite": suite_name,
        "task_id": task_id,
        "difficulty": str(ctx.task.DIFFICULTY),
        "prompt": ctx.task.PROMPT,
        "model": ctx.model,
        "nodes": result["nodes"],
        "edges": result["edges"],
        "answers": result["answers"],
        "utility": int(result.get("utility", 0)),
        "summary": {
            "n_nodes": len(result["nodes"]),
            "n_api_calls": sum(1 for n in result["nodes"] if n.get("api_call")),
            "n_tool_calls": sum(1 for n in result["nodes"] if n["type"] == "TOOL"),
            "tokens_in": sum(n.get("tokens", {}).get("in", 0) for n in result["nodes"]),
            "tokens_out": sum(n.get("tokens", {}).get("out", 0) for n in result["nodes"]),
            "wall_ms": wall_ms,
        },
        "env": ctx.env,
        "pre_env": ctx.pre_env,
    }
