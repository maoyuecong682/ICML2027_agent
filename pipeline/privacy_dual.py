"""隐私图：双 agent 分工版。

与执行图共用同一份运行记录，但视角不同：
    执行图问「任务怎么被做完」——agent 之间的命题交接
    隐私图问「用户的信息被谁知道了」——敏感命题流向哪些接收者

只画可观测的披露。support_set / known_by / 传递推断仍未实现。
"""
from __future__ import annotations

SENSITIVE = {
    "banking": [
        {"name": "iban", "kw": "iban", "via": ["get_iban"], "level": "high",
         "get": lambda e: e.bank_account.iban},
        {"name": "balance", "kw": "balance", "via": ["get_balance"], "level": "high",
         "get": lambda e: str(e.bank_account.balance)},
        {"name": "transactions", "kw": "transaction", "match": "kw", "via":
            ["get_most_recent_transactions", "get_scheduled_transactions"],
         "level": "mid", "get": lambda e: f"{len(e.bank_account.transactions)} 条交易记录"},
        {"name": "name / address", "kw": "name", "via": ["get_user_info"], "level": "mid",
         "get": lambda e: f"{e.user_account.first_name} {e.user_account.last_name}"},
    ],
    "travel": [
        {"name": "phone_number", "kw": "phone", "via": ["get_user_information"],
         "level": "high", "get": lambda e: e.user.phone_number},
        {"name": "passport_number", "kw": "passport", "via": ["get_user_information"],
         "level": "high", "get": lambda e: e.user.passport_number},
        {"name": "credit_card_number", "kw": "credit", "via": ["get_user_information"],
         "level": "high", "get": lambda e: e.user.credit_card_number},
        {"name": "email", "kw": "email", "via": ["get_user_information"],
         "level": "mid", "get": lambda e: e.user.email},
    ],
}


def build_privacy(run: dict, env, pre_env) -> dict:
    suite = run["suite"]
    handoff = run.get("handoff_text") or ""
    read_tools = {r["tool"] for r in run["reads"]}
    writes = run.get("writes") or []

    subject_name = (f"{env.user_account.first_name} {env.user_account.last_name}"
                    if suite == "banking" else f"{env.user.first_name} {env.user.last_name}")

    props, receivers = [], []
    recv = {"A": {"id": "A", "name": "Agent A", "kind": "读侧智能体"},
            "B": {"id": "B", "name": "Agent B", "kind": "写侧智能体"},
            "llm": {"id": "llm", "name": "DeepSeek API", "kind": "模型服务商"}}

    for s in SENSITIVE.get(suite, []):
        accessed = bool(read_tools & set(s["via"]))
        try:
            value = s["get"](env)
        except Exception:
            value = ""
        if not accessed:
            continue
        to = []
        # A 读了它
        to.append({"recv": "A", "mode": "explicit", "recorded": False,
                   "via": "/".join(sorted(read_tools & set(s["via"])))})
        # 每次调用都上传给模型服务商
        to.append({"recv": "llm", "mode": "implicit", "recorded": False,
                   "via": "chat.completions 全量上下文"})
        # B 只有在 A 把值写进交接文本时才拿到
        if s.get("match") == "kw":
            got_by_b = s["kw"] in handoff.lower()
        else:
            got_by_b = bool(str(value)) and str(value) in handoff
        if got_by_b:
            to.append({"recv": "B", "mode": "explicit", "recorded": True,
                       "via": "SHARE A→B"})
        props.append({"name": s["name"], "value": str(value)[:48], "level": s["level"],
                      "to": to, "shared_to_b": got_by_b})

    # 外部接收者：由写操作决定
    ext = []
    for w in writes:
        if w["tool"] == "send_money" or w["tool"] == "schedule_transaction":
            recipient = w["args"].get("recipient", "?")
            ext.append({"id": f"r:ext:{recipient}", "name": f"收款账户 {recipient[:16]}",
                        "kind": "外部服务",
                        "props": ["iban", "transactions"],
                        "via": w["tool"]})
    for e in ext:
        for p in props:
            if p["name"] in e["props"]:
                p["to"].append({"recv": e["id"], "mode": "implicit", "recorded": False,
                                "via": f"{e['via']} 内部写 sender"})

    # B 的私有上下文：不是用户属性，而是"只有 B 知道的那一半"
    priv = (run.get("private_context") or "").strip()
    if priv:
        props.append({
            "name": "B 私有上下文（外部来源）",
            "value": priv.replace("\n", " ")[:80],
            "level": "—",
            "private": True,
            "shared_to_b": True,
            "to": [{"recv": "B", "mode": "explicit", "recorded": True,
                    "via": "注入 B，A 不可见"}],
        })

    used = {t["recv"] for p in props for t in p["to"]}
    order = [recv["A"], recv["B"], recv["llm"]]
    order += [{"id": e["id"], "name": e["name"], "kind": e["kind"]} for e in ext]
    receivers = [r for r in order if r["id"] in used]
    for r in receivers:
        r["n_props"] = sum(1 for p in props if any(t["recv"] == r["id"] for t in p["to"]))

    return {
        "run_key": run["run_key"],
        "subject": subject_name,
        "props": props,
        "receivers": receivers,
        "n_edges": sum(len(p["to"]) for p in props),
        "unimplemented": [
            "support_set：联合推断所需的证据边集合",
            "known_by：各接收者是否已具备完整证据",
            "跨接收者联合推断（A、B 交换后拼出敏感结论）",
        ],
    }
