"""SQL 执行前安全策略。

这里处理的是确定性的后端安全边界，不依赖 LLM 自觉生成安全 SQL。
"""

from dataclasses import dataclass, field
import re
from typing import Optional


class SQLPolicyViolation(ValueError):
    """SQL 不满足执行前安全策略。"""


SENSITIVE_FIELD_PATTERN = re.compile(
    r"\b("
    r"password|passwd|pwd|token|secret|api_key|access_key|"
    r"phone|mobile|id_card|identity_card|bank_card"
    r")\b",
    re.IGNORECASE,
)

DANGEROUS_SQL_PATTERN = re.compile(
    r"\b("
    r"insert|update|delete|drop|alter|truncate|create|replace|merge|"
    r"grant|revoke|call|exec|execute|load|outfile"
    r")\b",
    re.IGNORECASE,
)

LIMIT_PATTERN = re.compile(r"\blimit\s+(\d+)(?:\s*,\s*(\d+))?", re.IGNORECASE)


@dataclass(frozen=True)
class SQLPolicyResult:
    """SQL 安全治理后的结果。"""

    sql: str
    warnings: list[str] = field(default_factory=list)


def enforce_sql_policy(sql: str, max_limit: int = 500) -> SQLPolicyResult:
    """校验只读安全边界，并给没有 LIMIT 的查询补充结果集上限。"""

    normalized_sql = sql.strip()
    warnings: list[str] = []

    if not normalized_sql:
        raise SQLPolicyViolation("SQL 为空，已拒绝执行。")

    if ";" in normalized_sql:
        raise SQLPolicyViolation("检测到多语句 SQL，已拒绝执行。")

    if not re.match(r"^(select|with)\b", normalized_sql, flags=re.IGNORECASE):
        raise SQLPolicyViolation("只允许 SELECT/WITH 只读查询。")

    if DANGEROUS_SQL_PATTERN.search(normalized_sql):
        raise SQLPolicyViolation("SQL 包含写入、DDL 或高风险关键字，已拒绝执行。")

    if SENSITIVE_FIELD_PATTERN.search(normalized_sql):
        raise SQLPolicyViolation("SQL 访问疑似敏感字段，已拒绝执行。")

    limited_sql, limit_warning = enforce_limit(normalized_sql, max_limit=max_limit)
    if limit_warning:
        warnings.append(limit_warning)

    return SQLPolicyResult(sql=limited_sql, warnings=warnings)


def enforce_limit(sql: str, max_limit: int = 500) -> tuple[str, Optional[str]]:
    """确保查询有结果集上限，并把过大的 LIMIT 收敛到允许范围。"""

    match = LIMIT_PATTERN.search(sql)
    if not match:
        return f"{sql} LIMIT {max_limit}", f"未检测到 LIMIT，已自动追加 LIMIT {max_limit}。"

    limit_value = int(match.group(2) or match.group(1))
    if limit_value <= max_limit:
        return sql, None

    replacement = f"LIMIT {match.group(1)}, {max_limit}" if match.group(2) else f"LIMIT {max_limit}"
    capped_sql = f"{sql[:match.start()]}{replacement}{sql[match.end():]}"
    return capped_sql, f"检测到 LIMIT {limit_value} 超过上限，已收敛到 LIMIT {max_limit}。"
