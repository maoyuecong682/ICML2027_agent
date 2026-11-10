"""隐私图骨架：只从本次执行记录里可以直接观测到的披露抽取。

明确边界——这一版只做"骨架"，不含以下三项（它们是后续 P4/P5 的工作）：
  1. support_set：能联合推出某个敏感结论的证据边集合
  2. known_by    ：每个接收者当前是否已具备完整 support_set
  3. 关系推理    ：U-X17-并购 这类跨实体的传递推断
所以图上只画"事实级披露"，不画"推断级泄露"。
"""
from __future__ import annotations

from typing import Any

SENSITIVE_FIELDS = {
    "travel": [
        ("phone_number", "high"),
        ("passport_number", "high"),
        ("credit_card_number", "high"),
        ("bank_account_number", "high"),
        ("ID_number", "mid"),
        ("email", "mid"),
        ("address", "mid"),
    ],
    "banking": [
        ("iban", "high"),
        ("balance", "low"),
        ("transactions", "mid"),
    ],
}

# 工具 → (接收者取自哪个参数, 接收者显示前缀)
EXTERNAL_SINK = {
    "travel": {
        "reserve_hotel": ("hotel", "酒店"),
        "reserve_restaurant": ("restaurant", "餐厅"),
        "reserve_car_rental": ("company_name", "租车公司"),
        "send_email": ("address", "邮件收件人"),
    },
    "banking": {
        "send_money": ("recipient", "收款账户"),
        "schedule_transaction": ("recipient", "收款账户"),
        "update_scheduled_transaction": (None, "计划转账"),
    },
}


def _subject(env: Any, suite: str) -> dict:
    if suite == "travel":
        u = env.user
        return {"id": "s", "name": f"{u.first_name} {u.last_name}", "raw": u.model_dump()}
    u = env.user_account
    return {"id": "s", "name": f"{u.first_name} {u.last_name}", "raw": u.model_dump()}


def _attr_values(env: Any, suite: str) -> dict:
    if suite == "travel":
        return env.user.model_dump()
    return {"iban": env.bank_account.iban, "balance": env.bank_account.balance,
            "transactions": len(env.bank_account.transactions)}


def build_privacy_skeleton(run: dict) -> dict:
    suite = run["suite"]
    env = run["env"]
    pre_env = run["pre_env"]

    subj = _subject(env, suite)
    values = _attr_values(env, suite)
    attrs = [
        {"id": f"a:{f}", "name": f, "value": str(values.get(f, ""))[:64], "level": lvl}
        for f, lvl in SENSITIVE_FIELDS[suite] if f in values
    ]

    receivers = []
    edges = []

    # ---- 1. 模型服务商：每次 TURN 都是一次全量上下文上传
    turns = [n for n in run["nodes"] if n.get("api_call")]
    if turns:
        receivers.append({"id": "r:llm", "name": "DeepSeek API", "kind": "模型服务商",
                          "recorded": False})
        edges.append({
            "src": "s", "dst": "r:llm", "rel": "DISCLOSED",
            "fields": ["全部 messages（含此前所有 tool 返回）"],
            "via": f"{len(turns)} 次 chat.completions",
            "mode": "implicit", "recorded": False,
            "note": "每次调用都全量上传上下文，日志未记录",
        })

    # ---- 2. 内部接收者：AgentB 通过 SHARE 拿到执行记录
    shares = [n for n in run["nodes"] if n["type"] == "SHARE"]
    if shares:
        receivers.append({"id": "r:agentb", "name": "AgentB", "kind": "内部智能体",
                          "recorded": True})
        edges.append({
            "src": "s", "dst": "r:agentb", "rel": "DISCLOSED",
            "fields": [f"A 的执行记录（{shares[0]['detail'].get('payload_len', 0)} 字符）"],
            "via": "SHARE A→B / render_transcript",
            "mode": "explicit", "recorded": True,
            "note": "唯一被完整记录的一条披露",
        })

    # ---- 3. 外部接收者：由工具调用参数决定
    for n in run["nodes"]:
        if n["type"] != "TOOL":
            continue
        spec = EXTERNAL_SINK.get(suite, {}).get(n["label"])
        if not spec:
            continue
        key, prefix = spec
        target = n["detail"]["args"].get(key, "?") if key else "?"
        rid = f"r:ext:{target}"
        if not any(r["id"] == rid for r in receivers):
            receivers.append({
                "id": rid, "name": f"{prefix} {target}", "kind": "外部服务",
                "recorded": False,
            })
        fields = [k for k in n["detail"]["args"].keys()]
        edges.append({
            "src": "s", "dst": rid, "rel": "DISCLOSED",
            "fields": [f"工具参数：{', '.join(fields)}"],
            "via": n["label"],
            "mode": "explicit", "recorded": False,
            "note": "工具参数可见，但未落成披露记录",
        })

    # ---- 4. 隐式披露：工具内部把用户字段写进了业务对象，参数里看不到
    if suite == "travel":
        ci = getattr(env.reservation, "contact_information", None)
        title = getattr(env.reservation, "title", None)
        if ci and title:
            rid = f"r:ext:{title}"
            if not any(r["id"] == rid for r in receivers):
                receivers.append({"id": rid, "name": f"酒店 {title}", "kind": "外部服务",
                                  "recorded": False})
            edges.append({
                "src": "s", "dst": rid, "rel": "DISCLOSED",
                "fields": [f"phone_number = {ci}"],
                "via": "reserve_hotel 内部写 contact_information",
                "mode": "implicit", "recorded": False,
                "note": "参数里没有手机号，是函数内部塞进去的；日志完全看不出来",
            })
    else:
        pre_ids = {t.id for t in pre_env.bank_account.transactions}
        for t in env.bank_account.transactions:
            if t.id in pre_ids:
                continue
            rid = f"r:ext:{t.recipient}"
            if not any(r["id"] == rid for r in receivers):
                receivers.append({"id": rid, "name": f"收款账户 {t.recipient}",
                                  "kind": "外部服务", "recorded": False})
            edges.append({
                "src": "s", "dst": rid, "rel": "DISCLOSED",
                "fields": [f"sender iban = {t.sender}", f"amount = {t.amount}",
                           f"subject = {t.subject}"[:60]],
                "via": "send_money 内部写 transaction.sender",
                "mode": "implicit", "recorded": False,
                "note": "sender 是 get_iban(account) 自动填的，参数里没有",
            })

    return {
        "run_key": run["run_key"],
        "subject": subj,
        "attrs": attrs,
        "receivers": receivers,
        "edges": edges,
        "unimplemented": [
            "support_set（联合推断所需的证据边集合）",
            "known_by（各接收者是否已具备完整证据）",
            "关系传递推断（A 知道负责人 / B 知道项目性质 → 联合推出秘密）",
            "披露边的一致性校验与去重",
        ],
    }
