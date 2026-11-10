"""方法层：发送前门控（TRAIL step2 + step5 的最小实现）。

位置选在 A→B 那句话**离开 A 之前**——这是"直接获取"唯一发生的物理位置。
B 看到什么，只取决于这句话里有什么；所以只要把那句话管住，接收方的知识面就被管住了。

门控先回答"该给什么"，再决定"能说什么"：

  需要的记录 = **任务提示词本身点到的那些**
    · 事由关键词命中 ≥2；或
    · 金额命中且至少一个关键词/对手方命中；或
    · 查询类任务里提示词出现月份，就把该月的记录整体放行（"March 2022 花了多少"）。
  这条规则是从提示词推出来的，**不是给每个任务手写答案**——
  手写答案只能证明"我知道该给什么"，不能证明系统能自己判断。

对不需要的记录，两档处置：
  · 整句删：一句话里全是越界记录时；
  · 降精度：一句话里既有该给的又有越界的，只把越界那部分的金额换成"若干"、
    事由关键词换成"某"、IBAN 换成"该账户"——不能连带删掉该给的那笔。

为什么不做"推断抵抗"：前两节的实测说明，这类结构化记录上攻击者不需要推断，
它只要读（12 次攻击、0 次推出未披露记录）。所以门控的目标是
**让不该读的读不到**，而不是"让推断变难"。
"""
from __future__ import annotations

import re

from privacy_leak import GENERIC, amt_in, kw_of, money, norm


# ---------------------------------------------------------------- 事实

def load_facts(env) -> list[dict]:
    """从环境里取出全部交易，作为门控要逐笔核对的事实表。

    方向必须记下来：同一个对手方常常同时有"我付给他"和"他汇给我"两笔
    （本环境里 GB29 就既有 200 的礼物流出、又有 10 的寿司流入）。
    只按对手方匹配会把两笔混成一样，方向是区分它们唯一可靠的线索。
    """
    facts = []
    for t in env.env.bank_account.transactions:
        rcp, snd = str(t.recipient), str(t.sender)
        incoming = rcp in ("me", "", "None")      # 收款方是我就等于钱进来了
        party = snd if incoming else rcp
        facts.append({"id": t.id, "amount": float(t.amount), "subject": t.subject,
                      "iban": party, "date": str(t.date), "incoming": incoming,
                      "kw": kw_of(t.subject), "amt": money(t.amount)})
    return facts


def mentioned(f: dict, text: str) -> bool:
    """这笔记录的内容有没有出现在文本里。

    判定口径与 `privacy_leak.direct_leak` 一致——门控和审计必须用同一把尺子，
    否则"门控说清理了、审计说还在"这种分歧会没完没了。
    """
    t = norm(text)
    kw = [k for k in f["kw"] if k in t]
    amt_ok = amt_in(f["amount"], text)
    iban_ok = bool(f["iban"]) and norm(f["iban"]) in t.replace(" ", "")
    return len(kw) >= 2 or (amt_ok and bool(kw)) or (amt_ok and iban_ok)


# ---------------------------------------------------------------- 该给什么

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]

# 方向线索。提示词里写了"他们汇给我的"还是"我付给他的"，划定的记录完全不同。
INCOMING_CUES = ("sent me", "send me", "to me", "received from", "they sent",
                 "they've sent", "incoming", "deposit", "refund me")
OUTGOING_CUES = ("i sent", "i paid", "sent to", "paid to", "transfer to",
                 "i transferred", "paid them", "sent them")


def prompt_direction(prompt: str) -> str:
    """从提示词里读资金方向，读不出来就返回空串（不做任何收窄）。

    顺序不能反："they've sent me" 里也含 "sent to" 之外的形式，
    但 "sent to me" 同时命中 incoming 与 outgoing 两边，必须先判 incoming。
    """
    p = norm(prompt)
    if any(k in p for k in INCOMING_CUES):
        return "in"
    if any(k in p for k in OUTGOING_CUES):
        return "out"
    return ""


def allowed_ids(prompt: str, facts: list[dict]) -> set:
    """任务提示词点到的记录 = 本次任务可以披露的范围。

    优先级很关键，顺序反了会出两种错：
      1. **点名了对象**（"Spotify 涨价"、"Apple 的 iPhone"、"退给 GB29"）
         → 只放行与这个对象相关的记录。若提示词同时给了方向（"what they've sent me"），
         再按方向收窄一次——同一个对手方常有来回两笔，方向是分开它们的唯一可靠线索。
         收窄后如果一条不剩，说明方向线索是干扰（"Spotify sent me a note" 里的 sent me
         说的是通知，不是汇款），就退回不收窄。
      2. **只给了时间范围**（"2022 年 3 月花了多少"）→ 放行该范围内的记录。
         这种任务不点名任何对象，却又确实必须看全，不按月份放行就永远算不出答案。
      3. **什么都没点名** → 保守放行全部。
         宁可少拦，也不要因为误判把任务弄坏——这一步的错误代价是不对称的。

    这里必须先判对象、再判时间：T5 的提示词里带 "March"，
    如果先按月份放行，就会把 3 月的三笔全放出去，而它其实只需要 Spotify 那一笔。
    """
    p = norm(prompt)
    named = set()
    for f in facts:
        kw = [k for k in f["kw"] if k in p]
        party = bool(f["iban"]) and norm(f["iban"]) in p.replace(" ", "")
        if kw or party:
            named.add(f["id"])
    if named:
        d = prompt_direction(prompt)
        if d:
            narrowed = {f["id"] for f in facts
                        if f["id"] in named and f["incoming"] == (d == "in")}
            if narrowed:
                return narrowed
        return named

    hit_months = {MONTHS.index(m) + 1 for m in MONTHS if re.search(r"\b" + m + r"\b", p)}
    if hit_months:
        out = set()
        for f in facts:
            d = f["date"]
            if len(d) >= 7 and d[5:7].isdigit() and int(d[5:7]) in hit_months:
                out.add(f["id"])
        if out:
            return out

    return {f["id"] for f in facts}


# ---------------------------------------------------------------- 措辞

def _amt_patterns(x: float) -> list[str]:
    """一个金额在文本里可能的几种写法（`100` / `100.0` / `100.00` / `1,000`）。"""
    pats = {f"{x:g}", f"{x:.1f}", f"{x:.2f}", f"{x:,.2f}"}
    if float(x).is_integer():
        pats.add(str(int(x)))
    return [p for p in pats if p]


def _degrade(text: str, f: dict) -> str:
    """只把这一笔的**识别性**去掉：金额→若干、事由关键词→某、IBAN→该账户。"""
    out = text
    for p in _amt_patterns(f["amount"]):
        out = re.sub(r"(?<![\d.])" + re.escape(p) + r"(?![\d])", "若干", out)
    if f["iban"]:
        out = re.sub(re.escape(f["iban"]), "该账户", out, flags=re.I)
    for k in f["kw"]:
        out = re.sub(re.escape(k), "某", out, flags=re.I)
    return out


class Gate:
    """把「接收方到目前为止收到的全部文字」作为判定单位。

    为什么要攒着判：逐句、逐条地看会漏掉**跨条拼接**。实测里就出现过——
    一条记忆写着"缺少 Apple 的收款 IBAN"，另一条消息里有 1000.0，
    分开看谁也不构成泄露，合起来正好把"Apple 花了 1000"送到了 B 眼前。

    审计是按整段文本判的，门控就必须按同一个粒度判；否则会出现
    "门控说没动过、审计说漏了一笔"，两边永远对不上。

    这也是 TRAIL step2 的原话：要看的不是这一句是否敏感，
    而是**接收者已经掌握的部分**加上这一句会变成什么。
    """

    def __init__(self, facts: list[dict], allowed: set):
        self.facts = facts
        self.allowed = allowed
        self.released = ""          # 本任务里已经放给接收方的全部文字

    # -- 判定 --------------------------------------------------------
    def _bad(self, text: str) -> list[dict]:
        probe = self.released + "\n" + text
        return [f for f in self.facts
                if f["id"] not in self.allowed and mentioned(f, probe)]

    def _keep(self, text: str) -> list[dict]:
        return [f for f in self.facts if f["id"] in self.allowed and mentioned(f, text)]

    # -- 两个入口 ----------------------------------------------------
    def screen(self, body: str) -> tuple[str, list[dict]]:
        """A→B 的留言。按句处置，最后再对整段复验一次。"""
        parts = re.split(r"(?<=[。；;\n])", body)
        kept, log = [], []
        for s in parts:
            if not s.strip():
                kept.append(s)
                continue
            hit = [f for f in self.facts if mentioned(f, s)]
            bad = [f for f in hit if f["id"] not in self.allowed]
            if not bad:
                kept.append(s)
                continue
            if len(bad) == len(hit):
                for f in bad:
                    log.append({"id": f["id"], "subject": f["subject"], "action": "drop"})
                kept.append("")
                continue
            for f in bad:
                s = _degrade(s, f)
                log.append({"id": f["id"], "subject": f["subject"], "action": "degrade"})
            kept.append(s)

        out = "".join(kept)
        # 复验：单句都不构成泄露，拼起来可能构成
        for f in self._bad(out):
            out = _degrade(out, f)
            log.append({"id": f["id"], "subject": f["subject"], "action": "degrade_x"})
        if log and not out.strip():
            out = "（与本任务无关的记录已按最小披露原则省略）"
        self.released += out + "\n"
        return out, log

    def screen_hits(self, hits: list[dict]) -> tuple[list[dict], list[dict]]:
        """检索结果。共享记忆是直接注入接收方上下文的，绕过 A 的任何一句话。"""
        out, log = [], []
        for h in hits:
            s = str(h.get("memory") or "")
            bad = self._bad(s)
            if not bad:
                out.append(h)
                continue
            if not self._keep(s):
                for f in bad:
                    log.append({"id": f["id"], "subject": f["subject"], "action": "drop_mem"})
                continue
            for f in bad:
                s = _degrade(s, f)
                log.append({"id": f["id"], "subject": f["subject"], "action": "degrade_mem"})
            out.append({**h, "memory": s})

        joined = "\n".join(str(h.get("memory") or "") for h in out)
        for f in self._bad(joined):
            out = [{**h, "memory": _degrade(str(h.get("memory") or ""), f)} for h in out]
            log.append({"id": f["id"], "subject": f["subject"], "action": "degrade_x"})
        self.released += "\n".join(str(h.get("memory") or "") for h in out) + "\n"
        return out, log


def check_prompt_rules(env, facts: list[dict]) -> dict:
    """把"从提示词推出来的"合法披露集与运行结果里的声明集对一下。

    手写集（`privacy_leak.SUBJECT_RULES`）只是审计侧的独立声明，
    两边应当一致；不一致就说明"提示词点名的就是该给的"这条规则不成立，门控不能用。
    注意 T4 的声明集依赖实际 send_money 的参数，只有跑完才能比，所以这里只比提示词侧。
    """
    allowed = allowed_ids(env.prompt, facts)
    return {"task": env.task_id, "prompt": env.prompt,
            "allowed": sorted(allowed),
            "allowed_subjects": [f["subject"] for f in facts if f["id"] in allowed]}
