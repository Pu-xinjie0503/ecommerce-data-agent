"""基于 EXPLAIN 的 SQL 风险分析与索引建议。"""

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SQLRiskAnalysis:
    """SQL 执行计划风险分析结果。"""

    risk_flags: list[str] = field(default_factory=list)
    index_suggestions: list[str] = field(default_factory=list)
    rewrite_suggestions: list[str] = field(default_factory=list)


def analyze_sql_risk(
    sql: str,
    explain_rows: list[dict],
    large_rows_threshold: int = 10000,
) -> SQLRiskAnalysis:
    """根据 EXPLAIN 结果和 SQL 结构生成风险标记与优化建议。"""

    flags: set[str] = set()
    for row in explain_rows:
        access_type = str(row.get("type") or "").upper()
        used_key = row.get("key")
        rows = row.get("rows")
        extra = str(row.get("Extra") or "")

        if access_type == "ALL":
            flags.add("FULL_TABLE_SCAN")
        if not used_key:
            flags.add("NO_INDEX_USED")
        if isinstance(rows, (int, float)) and rows >= large_rows_threshold:
            flags.add("LARGE_ROWS_SCAN")
        if "Using temporary" in extra:
            flags.add("USING_TEMPORARY")
        if "Using filesort" in extra:
            flags.add("USING_FILESORT")

    return SQLRiskAnalysis(
        risk_flags=sorted(flags),
        index_suggestions=build_index_suggestions(sql, flags),
        rewrite_suggestions=build_rewrite_suggestions(sql, flags),
    )


def build_index_suggestions(sql: str, flags: set[str]) -> list[str]:
    suggestions: list[str] = []
    normalized = sql.lower()

    if "fact_order" in normalized and "region_id" in normalized and "date_id" in normalized:
        suggestions.append("fact_order 可考虑建立联合索引 (region_id, date_id)，用于地区过滤和时间范围查询。")
    elif "fact_order" in normalized and "region_id" in normalized:
        suggestions.append("fact_order 可考虑为 region_id 建立索引，降低按地区过滤时的扫描行数。")
    elif "fact_order" in normalized and "date_id" in normalized:
        suggestions.append("fact_order 可考虑为 date_id 建立索引，降低按时间范围过滤时的扫描行数。")

    join_columns = extract_join_columns(sql)
    for left, right in join_columns:
        suggestions.append(f"JOIN 条件 {left} = {right} 涉及的外键列应确认已有索引，维表连接键应保持主键或唯一索引。")

    if "USING_FILESORT" in flags:
        order_columns = extract_clause_columns(sql, "order by")
        if order_columns:
            suggestions.append(f"ORDER BY 字段 {', '.join(order_columns)} 可结合高频 WHERE 字段设计联合索引。")

    if "USING_TEMPORARY" in flags:
        group_columns = extract_clause_columns(sql, "group by")
        if group_columns:
            suggestions.append(f"GROUP BY 字段 {', '.join(group_columns)} 可结合过滤字段设计联合索引；大范围聚合可考虑预聚合表。")

    if not suggestions and {"FULL_TABLE_SCAN", "NO_INDEX_USED"} & flags:
        suggestions.append("建议检查 WHERE、JOIN、GROUP BY、ORDER BY 中的高频字段，并结合选择性设计联合索引。")

    return dedupe(suggestions)


def build_rewrite_suggestions(sql: str, flags: set[str]) -> list[str]:
    suggestions: list[str] = []
    normalized = sql.lower()

    if re.search(r"\bdate\s*\(", normalized):
        suggestions.append("避免在时间字段上使用 DATE() 等函数，改为范围条件以便命中索引。")

    if re.search(r"\blike\s+'%", normalized):
        suggestions.append("避免前置通配 LIKE '%xxx'，普通 BTree 索引无法利用该条件。")

    if "FULL_TABLE_SCAN" in flags or "LARGE_ROWS_SCAN" in flags:
        suggestions.append("优先增加时间、地区、商品等高选择性过滤条件，减少事实表扫描范围。")

    if "USING_TEMPORARY" in flags:
        suggestions.append("大范围 GROUP BY 可以考虑离线汇总表或按常用维度预聚合。")

    return dedupe(suggestions)


def extract_join_columns(sql: str) -> list[tuple[str, str]]:
    return re.findall(
        r"([a-zA-Z_][\w]*\.[a-zA-Z_][\w]*)\s*=\s*([a-zA-Z_][\w]*\.[a-zA-Z_][\w]*)",
        sql,
        flags=re.IGNORECASE,
    )


def extract_clause_columns(sql: str, clause: str) -> list[str]:
    pattern = re.compile(
        rf"\b{clause}\b\s+(.+?)(?:\border\s+by\b|\bgroup\s+by\b|\bhaving\b|\blimit\b|$)",
        re.IGNORECASE,
    )
    match = pattern.search(sql)
    if not match:
        return []

    columns = []
    for raw_column in match.group(1).split(","):
        column = raw_column.strip()
        column = re.sub(r"\s+(asc|desc)\b", "", column, flags=re.IGNORECASE)
        if column:
            columns.append(column)
    return columns


def dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item not in seen:
            result.append(item)
            seen.add(item)
    return result
