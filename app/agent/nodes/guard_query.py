"""输入侧安全拦截节点"""

import re
from dataclasses import dataclass
from typing import Literal

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.core.log import logger

RiskLevel = Literal["low", "medium", "high"]
RiskType = Literal[
    "normal_query",
    "prompt_injection",
    "dangerous_sql",
    "sensitive_data_request",
    "write_or_destructive_operation",
]

BLOCKED_ANSWER = "当前系统仅支持只读数据查询，不能执行删除、修改、建表、泄露系统提示词或查询敏感信息等操作。"


@dataclass(frozen=True)
class GuardRule:
    risk_type: RiskType
    risk_level: RiskLevel
    reason: str
    patterns: tuple[str, ...]


GUARD_RULES: tuple[GuardRule, ...] = (
    GuardRule(
        risk_type="prompt_injection",
        risk_level="high",
        reason="命中 prompt injection 或系统提示词泄露意图",
        patterns=(
            r"忽略.{0,12}(之前|以上|前面).{0,12}(指令|规则|要求)",
            r"忽略.{0,12}系统.{0,8}(提示|指令|规则)",
            r"不要.{0,12}(遵守|服从|理会).{0,12}(规则|限制|指令|系统)",
            r"绕过.{0,12}(限制|规则|安全|校验|审查)",
            r"输出.{0,12}(系统提示词|系统 prompt|system prompt|prompt)",
            r"泄露.{0,12}(prompt|提示词|系统提示|系统指令)",
            r"reveal.{0,20}(system prompt|prompt|instruction)",
            r"ignore.{0,20}(previous|prior|system).{0,20}(instruction|rule|prompt)",
        ),
    ),
    GuardRule(
        risk_type="write_or_destructive_operation",
        risk_level="high",
        reason="命中写操作或破坏性 SQL 意图",
        patterns=(
            r"\b(drop|delete|update|insert|alter|truncate|create)\b",
            r"删除.{0,12}(表|数据|记录|订单|用户|客户)",
            r"清空.{0,12}(表|数据|记录)",
            r"修改.{0,12}(表|数据|记录|字段)",
            r"插入.{0,12}(数据|记录)",
            r"新建.{0,12}(表|数据库)",
            r"建表",
        ),
    ),
    GuardRule(
        risk_type="sensitive_data_request",
        risk_level="high",
        reason="命中敏感信息查询意图",
        patterns=(
            r"密码",
            r"口令",
            r"身份证",
            r"手机号",
            r"银行卡",
            r"api[_-]?key",
            r"token",
            r"secret",
            r"access[_-]?key",
            r"密钥",
        ),
    ),
)


async def guard_query(
    state: DataAgentState,
    runtime: Runtime[DataAgentContext],
):
    """在 Agent 入口拦截明显不安全的用户问题"""

    step = "输入安全检查"
    writer = runtime.stream_writer
    writer({"type": "progress", "step": step, "status": "running"})

    query = state.get("query", "")
    result = check_query_safety(query)

    if result["is_safe"]:
        writer({"type": "progress", "step": step, "status": "success"})
    else:
        writer({"type": "progress", "step": step, "status": "blocked"})
        writer({"type": "guardrail", "data": result})
        writer({"type": "result", "data": result["final_answer"]})

    logger.info(f"输入安全检查结果: {result}")
    return result


def check_query_safety(query: str) -> dict[str, object]:
    normalized_query = query.strip().lower()
    for rule in GUARD_RULES:
        for pattern in rule.patterns:
            if re.search(pattern, normalized_query, flags=re.IGNORECASE):
                return {
                    "is_safe": False,
                    "risk_level": rule.risk_level,
                    "risk_type": rule.risk_type,
                    "guard_reason": rule.reason,
                    "final_answer": BLOCKED_ANSWER,
                    "sql": None,
                    "result": None,
                }

    return {
        "is_safe": True,
        "risk_level": "low",
        "risk_type": "normal_query",
        "guard_reason": "未命中输入侧安全拦截规则",
    }
