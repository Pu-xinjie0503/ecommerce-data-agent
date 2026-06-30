"""行级权限隔离策略。

样例数据库没有完整租户模型，因此这里用地区权限模拟生产中的行级权限控制。
核心原则是：权限条件由后端确定性注入，不能依赖 LLM 生成。
"""

from dataclasses import dataclass, field
import re
from typing import Optional


class PermissionDenied(ValueError):
    """SQL 无法满足当前用户权限边界。"""


SQL_KEYWORDS = {
    "where",
    "join",
    "left",
    "right",
    "inner",
    "outer",
    "on",
    "group",
    "order",
    "limit",
    "having",
}

CLAUSE_PATTERN = re.compile(
    r"\b(group\s+by|order\s+by|having|limit)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PermissionContext:
    """请求级权限上下文。"""

    user_id: str = "demo_admin"
    role: str = "admin"
    tenant_id: Optional[str] = None
    allowed_region_ids: list[int] = field(default_factory=list)
    allowed_region_names: list[str] = field(default_factory=list)

    def is_admin(self) -> bool:
        return self.role.lower() in {"admin", "platform_admin"}

    def has_region_scope(self) -> bool:
        return bool(self.allowed_region_ids or self.allowed_region_names)


@dataclass(frozen=True)
class PermissionPolicyResult:
    """权限注入后的 SQL 与说明。"""

    sql: str
    warnings: list[str] = field(default_factory=list)


def apply_permission_policy(sql: str, permission: PermissionContext) -> PermissionPolicyResult:
    """按用户可见范围注入行级权限条件。"""

    if permission.is_admin():
        return PermissionPolicyResult(sql=sql, warnings=["管理员角色未追加行级权限过滤。"])

    if not permission.has_region_scope():
        raise PermissionDenied("非管理员用户没有配置可访问地区范围，已拒绝执行。")

    if sql.lstrip().lower().startswith("with "):
        raise PermissionDenied("当前权限注入暂不支持 WITH 查询，请改写为普通 SELECT。")

    condition = build_region_condition(sql, permission)
    if not condition:
        raise PermissionDenied("SQL 未访问可注入地区权限的业务表，已拒绝执行。")

    governed_sql = inject_where_condition(sql, condition)
    return PermissionPolicyResult(
        sql=governed_sql,
        warnings=[f"已为用户 {permission.user_id} 注入地区权限过滤。"],
    )


def build_region_condition(sql: str, permission: PermissionContext) -> Optional[str]:
    """根据 SQL 中出现的表，构造地区权限条件。"""

    fact_alias = find_table_alias(sql, "fact_order")
    region_alias = find_table_alias(sql, "dim_region")

    if permission.allowed_region_ids and fact_alias:
        values = ", ".join(str(value) for value in permission.allowed_region_ids)
        return f"{fact_alias}.region_id IN ({values})"

    if permission.allowed_region_names and region_alias:
        values = ", ".join(quote_sql_string(value) for value in permission.allowed_region_names)
        return f"{region_alias}.region_name IN ({values})"

    if permission.allowed_region_names and fact_alias:
        values = ", ".join(quote_sql_string(value) for value in permission.allowed_region_names)
        return (
            f"{fact_alias}.region_id IN ("
            f"SELECT region_id FROM dim_region WHERE region_name IN ({values})"
            f")"
        )

    return None


def find_table_alias(sql: str, table_name: str) -> Optional[str]:
    """查找 FROM/JOIN 中的表别名，没有别名时返回表名。"""

    pattern = re.compile(
        rf"\b(?:from|join)\s+`?{re.escape(table_name)}`?(?:\s+(?:as\s+)?`?([a-zA-Z_][\w]*)`?)?",
        re.IGNORECASE,
    )
    match = pattern.search(sql)
    if not match:
        return None

    alias = match.group(1)
    if alias is None or alias.lower() in SQL_KEYWORDS:
        return table_name
    return alias


def inject_where_condition(sql: str, condition: str) -> str:
    """在 GROUP/ORDER/LIMIT 之前注入权限条件。"""

    clause_match = CLAUSE_PATTERN.search(sql)
    head = sql[: clause_match.start()].rstrip() if clause_match else sql.rstrip()
    tail = sql[clause_match.start() :].lstrip() if clause_match else ""

    connector = " AND " if re.search(r"\bwhere\b", head, flags=re.IGNORECASE) else " WHERE "
    governed = f"{head}{connector}({condition})"
    return f"{governed} {tail}".strip()


def quote_sql_string(value: str) -> str:
    """转义权限值，避免权限条件自身破坏 SQL 字符串。"""

    return "'" + value.replace("'", "''") + "'"
