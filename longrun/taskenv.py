"""AgentDojo 任务装载 + 工具集划分（A 只读 / B 只写）。

与 ../pipeline/graph_dual.py 的区别：这里把「工具互斥」从提示层约束升级为执行层约束——
`call()` 会校验调用方，越权调用直接拦下并记账（越权尝试率是可报告指标）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agentdojo.functions_runtime import FunctionsRuntime
from agentdojo.task_suite.load_suites import get_suite
from openai import OpenAI

from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, MODEL

TOOL_SPLIT = {
    "banking": {
        "A": ["read_file", "get_iban", "get_balance",
              "get_most_recent_transactions", "get_scheduled_transactions", "get_user_info"],
        "B": ["send_money", "schedule_transaction", "update_scheduled_transaction",
              "update_user_info", "update_password"],
    },
    "travel": {
        "A": ["get_user_information", "get_all_hotels_in_city", "get_hotels_prices",
              "get_rating_reviews_for_hotels", "get_hotels_address", "get_all_restaurants_in_city",
              "get_cuisine_type_for_restaurants", "get_restaurants_address",
              "get_rating_reviews_for_restaurants", "get_dietary_restrictions_for_all_restaurants",
              "get_contact_information_for_restaurants", "get_price_for_restaurants",
              "check_restaurant_opening_hours", "get_all_car_rental_companies_in_city",
              "get_car_types_available", "get_rating_reviews_for_car_rental",
              "get_car_fuel_options", "get_car_rental_address", "get_car_price_per_day",
              "get_flight_information", "search_calendar_events", "get_day_calendar_events"],
        "B": ["reserve_hotel", "reserve_restaurant", "reserve_car_rental",
              "send_email", "create_calendar_event", "cancel_calendar_event"],
    },
}


@dataclass
class TaskEnv:
    suite_name: str
    task_id: str
    suite: Any
    task: Any
    env: Any
    pre_env: Any
    runtime: Any
    tools_a: list
    tools_b: list
    client: Any
    tool_names: dict = field(default_factory=dict)
    denied: list = field(default_factory=list)   # 越权尝试：(agent, tool)

    @property
    def prompt(self) -> str:
        return self.task.PROMPT

    def allowed(self, agent: str) -> list:
        return TOOL_SPLIT[self.suite_name][agent]

    def call(self, agent: str, name: str, args: dict):
        """执行工具。越权直接拦截，返回 (None, 错误串) 并记账。"""
        if name not in self.allowed(agent):
            self.denied.append((agent, name))
            return None, f"DENIED: {agent} 无 {name} 权限（工具互斥）"
        return self.runtime.run_function(self.env, name, args)


def to_openai_tools(fns: list) -> list:
    return [{"type": "function",
             "function": {"name": f.name, "description": f.description,
                          "parameters": f.parameters.model_json_schema()}} for f in fns]


def load_task(suite_name: str, task_id: str, version: str = "v1.2") -> TaskEnv:
    suite = get_suite(version, suite_name)
    task = suite.get_user_task_by_id(task_id)
    env = task.init_environment(suite.load_and_inject_default_environment({}))
    pre_env = env.model_copy(deep=True)

    split = TOOL_SPLIT[suite_name]
    all_names = {f.name for f in suite.tools}
    a_names, b_names = set(split["A"]), set(split["B"])
    assert not (a_names & b_names), f"工具集重叠：{a_names & b_names}"
    assert not (all_names - (a_names | b_names)), f"未分配：{all_names - (a_names | b_names)}"

    by_name = {f.name: f for f in suite.tools}
    return TaskEnv(
        suite_name=suite_name, task_id=task_id, suite=suite, task=task,
        env=env, pre_env=pre_env,
        runtime=FunctionsRuntime(suite.tools),
        tools_a=to_openai_tools([by_name[n] for n in split["A"]]),
        tools_b=to_openai_tools([by_name[n] for n in split["B"]]),
        client=OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL),
        tool_names={f.name: f for f in suite.tools},
    )
