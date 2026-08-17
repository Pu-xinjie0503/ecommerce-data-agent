"""当前电商领域的确定性查询语义解析。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from app.agent.state import QuerySemanticsState
from app.conf.meta_config import load_meta_config


@dataclass(frozen=True)
class SemanticSpan:
    """原始 Query 中一段已识别的业务语义。"""

    start: int
    end: int
    text: str
    value: str
    evidence: str


@dataclass(frozen=True)
class RankingSemantics:
    """排序方向、Top N 及其占用的原文区间。"""

    direction: Literal["asc", "desc"] | None
    limit: int | None
    spans: tuple[SemanticSpan, ...]


METRIC_ALIASES: tuple[tuple[str, str], ...] = (
    ("平均订单金额", "aov"),
    ("平均订单额", "aov"),
    ("平均客单价", "aov"),
    ("销售件数", "order_quantity"),
    ("购买数量", "order_quantity"),
    ("订单数量", "order_count"),
    ("卖了多少钱", "gmv"),
    ("平均多少钱", "aov"),
    ("订单数", "order_count"),
    ("订单量", "order_count"),
    ("销售金额", "gmv"),
    ("订单金额", "gmv"),
    ("销售额", "gmv"),
    ("成交额", "gmv"),
    ("多少件", "order_quantity"),
    ("客单价", "aov"),
    ("销量", "order_quantity"),
    ("件数", "order_quantity"),
    ("gmv", "gmv"),
    ("aov", "aov"),
)

TIME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*[日号]"
        r"\s*(?:到|至|-)\s*\d{1,2}\s*[日号]"
    ),
    re.compile(r"\d{4}-\d{1,2}-\d{1,2}\s*(?:到|至|-)\s*\d{4}-\d{1,2}-\d{1,2}"),
    re.compile(r"\d{4}\s*年\s*\d{1,2}\s*月"),
    re.compile(r"\d{4}-\d{1,2}"),
    re.compile(r"\d{4}\s*年"),
    re.compile(r"[一二三四五六七八九十]{1,2}月份?"),
    re.compile(r"\d{1,2}\s*月\s*\d{1,2}\s*[日号]\s*(?:到|至)\s*\d{1,2}\s*月\s*\d{1,2}\s*[日号]"),
    re.compile(r"第\s*[一二三四1-4]\s*季度", flags=re.IGNORECASE),
    re.compile(r"\d{4}\s*[一二三四1-4]\s*季度"),
    re.compile(r"q[1-4]", flags=re.IGNORECASE),
    re.compile(r"最近\s*\d+\s*(?:天|个月)"),
    re.compile(r"本月|上月|本季度|上季度|今年|去年|本周|上周|今天|昨天"),
)

CHINESE_NUMBERS: dict[str, int] = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

GROUP_TRIGGERS = ("按", "各", "每个", "每款", "不同")
QUERY_PREFIXES = ("统计", "查询", "查看", "对比", "分析", "计算", "请问", "帮我")
ANALYSIS_WORDS = (
    "哪个",
    "哪些",
    "哪一个",
    "找出",
    "筛选",
    "排名",
    "最高",
    "最低",
    "最多",
    "最少",
    "最后",
    "超过",
    "大于",
    "小于",
    "高于",
    "低于",
    "过万",
)
NON_VALUE_WORDS = (
    "所有",
    "合计",
    "累计",
    "多少",
    "哪个",
    "哪些",
    "找出",
    "筛选",
    "排名",
    "最高",
    "最低",
    "最多",
    "最少",
    "最后",
    "超过",
    "大于",
    "小于",
    "高于",
    "低于",
    "过万",
)


@lru_cache(maxsize=1)
def build_dimension_alias_index() -> tuple[tuple[str, str], ...]:
    """从元数据构建按别名长度降序排列的维度词典。"""

    config_path = Path(__file__).parents[2] / "conf" / "meta_config.yaml"
    config = load_meta_config(config_path)
    entries: set[tuple[str, str]] = set()
    for table in config.tables:
        for column in table.columns:
            if column.role != "dimension":
                continue
            column_id = f"{table.name}.{column.name}"
            for alias in [column.name, *column.alias]:
                normalized_alias = alias.strip().lower()
                if normalized_alias:
                    entries.add((normalized_alias, column_id))
    return tuple(sorted(entries, key=lambda item: (-len(item[0]), item[0], item[1])))


def _find_alias_spans(query: str) -> list[SemanticSpan]:
    normalized_query = query.lower()
    occupied: set[int] = set()
    matches: list[SemanticSpan] = []
    for alias, column_id in build_dimension_alias_index():
        for match in re.finditer(re.escape(alias), normalized_query):
            positions = set(range(match.start(), match.end()))
            if positions & occupied:
                continue
            occupied.update(positions)
            matches.append(
                SemanticSpan(
                    start=match.start(),
                    end=match.end(),
                    text=query[match.start() : match.end()],
                    value=column_id,
                    evidence=f"维度别名: {query[match.start():match.end()]} -> {column_id}",
                )
            )
    return sorted(matches, key=lambda span: span.start)


def find_dimension_mentions(query: str) -> list[str]:
    """返回 Query 明确提及的业务维度列 ID，保持原文顺序并去重。"""

    return _dedupe(span.value for span in _find_alias_spans(query))


def _extract_time_spans(query: str) -> list[SemanticSpan]:
    spans: list[SemanticSpan] = []
    occupied: set[int] = set()
    for pattern in TIME_PATTERNS:
        for match in pattern.finditer(query):
            positions = set(range(match.start(), match.end()))
            if positions & occupied:
                continue
            occupied.update(positions)
            spans.append(
                SemanticSpan(
                    start=match.start(),
                    end=match.end(),
                    text=match.group(0),
                    value=match.group(0),
                    evidence=f"时间表达: {match.group(0)}",
                )
            )
    return sorted(spans, key=lambda span: span.start)


def _extract_metric_spans(query: str) -> list[SemanticSpan]:
    normalized_query = query.lower()
    occupied: set[int] = set()
    spans: list[SemanticSpan] = []
    for alias, metric in sorted(METRIC_ALIASES, key=lambda item: -len(item[0])):
        for match in re.finditer(re.escape(alias), normalized_query):
            positions = set(range(match.start(), match.end()))
            if positions & occupied:
                continue
            occupied.update(positions)
            spans.append(
                SemanticSpan(
                    start=match.start(),
                    end=match.end(),
                    text=query[match.start() : match.end()],
                    value=metric,
                    evidence=f"指标别名: {query[match.start():match.end()]} -> {metric}",
                )
            )
    return sorted(spans, key=lambda span: span.start)


def _parse_limit(text: str) -> int | None:
    digit_match = re.search(r"\d+", text)
    if digit_match:
        return int(digit_match.group(0))
    for token, value in CHINESE_NUMBERS.items():
        if token in text:
            return value
    return None


def _extract_ranking(query: str) -> RankingSemantics:
    patterns = (
        re.compile(r"(?:top\s*\d+|前\s*[一二两三四五六七八九十\d]+)", re.IGNORECASE),
        re.compile(r"(?:最多|最高|最大|最好)(?:的)?[一二两三四五六七八九十\d]*个?"),
        re.compile(r"排名\s*(?:第|前)?[一二两三四五六七八九十\d]+"),
        re.compile(r"排名\s*最后"),
        re.compile(r"(?:最少|最低|最小|最差)(?:的)?[一二两三四五六七八九十\d]*个?"),
    )
    spans: list[SemanticSpan] = []
    direction: Literal["asc", "desc"] | None = None
    limit: int | None = None
    for pattern in patterns:
        for match in pattern.finditer(query):
            text = match.group(0)
            current_direction: Literal["asc", "desc"] = (
                "asc" if any(word in text for word in ("最少", "最低", "最小", "最差")) else "desc"
            )
            direction = direction or current_direction
            limit = limit or _parse_limit(text)
            if limit is None and any(
                word in text for word in ("最高", "最大", "最好", "最低", "最小", "最差", "最后")
            ):
                limit = 1
            spans.append(
                SemanticSpan(
                    start=match.start(),
                    end=match.end(),
                    text=text,
                    value=current_direction,
                    evidence=f"排序表达: {text} -> {current_direction}",
                )
            )
    return RankingSemantics(direction=direction, limit=limit, spans=tuple(spans))


def _classify_group_by_columns(
    query: str,
    dimensions: list[SemanticSpan],
    ranking: RankingSemantics,
    time_spans: list[SemanticSpan],
) -> list[str]:
    if not dimensions:
        return []

    normalized_query = query.lower()
    has_global_group = any(trigger in normalized_query for trigger in GROUP_TRIGGERS)
    has_dimension_suffix = any(word in normalized_query for word in ("维度", "组合", "分别"))
    has_analysis_group = ranking.direction is not None or any(
        word in normalized_query for word in ANALYSIS_WORDS
    )
    if not (has_global_group or has_dimension_suffix or has_analysis_group):
        return []

    grouped: list[str] = []
    for dimension in dimensions:
        overlaps_time = any(
            dimension.start < time_span.end and time_span.start < dimension.end
            for time_span in time_spans
        )
        if dimension.value.startswith("dim_date.") and overlaps_time:
            continue
        grouped.append(dimension.value)
    return _dedupe(grouped)


def _remove_time_expressions(text: str, time_spans: list[SemanticSpan]) -> str:
    result = text
    for span in time_spans:
        result = result.replace(span.text, " ")
    return result


def _clean_filter_segment(text: str) -> list[str]:
    value = text.strip(" \t\r\n，,；;：:")
    for prefix in QUERY_PREFIXES:
        position = value.rfind(prefix)
        if position >= 0:
            value = value[position + len(prefix) :]
    value = value.strip()
    value = re.sub(r"^的", "", value)
    if not value:
        return []
    if "的" in value and not value.endswith("的"):
        value = value.rsplit("的", 1)[-1].strip()
    if any(word in value for word in NON_VALUE_WORDS):
        return []
    value = re.sub(r"^(?:购买|买了?|来自|位于|在|为|是|等于)+", "", value)
    value = value.strip()
    value = re.sub(r"^的", "", value)
    if not value:
        return []
    parts = re.split(r"和|与|、|,|，|及", value)
    ignored = {"按", "各", "每个", "每款", "不同", "分别", "的"}
    cleaned_parts = [re.sub(r"^的", "", part.strip()) for part in parts]
    return [part for part in cleaned_parts if part and part not in ignored]


def _extract_postfix_value(query: str, dimension: SemanticSpan) -> list[str]:
    suffix = query[dimension.end :]
    match = re.match(
        r"\s*(?:为|是|等于)\s*(.+?)(?=(?:的)?\s*(?:gmv|销售额|销售金额|销量|订单数|订单量|aov)|[，,；;]|$)",
        suffix,
        flags=re.IGNORECASE,
    )
    return _clean_filter_segment(match.group(1)) if match else []


def _extract_brand_shorthand(query: str) -> list[str]:
    patterns = (
        re.compile(r"(?:统计|查询|查看)?\s*([\u4e00-\u9fffA-Za-z0-9]+牌)(?=商品)"),
        re.compile(r"(?:统计|查询|查看)?\s*([\u4e00-\u9fffA-Za-z0-9]+牌)(?=一共|总共|卖了)"),
    )
    values: list[str] = []
    for pattern in patterns:
        match = pattern.search(query)
        if match:
            cleaned = _clean_filter_segment(match.group(1))
            values.extend(cleaned)
    return _dedupe(values)


def _extract_gender_filter(query: str) -> list[str]:
    match = re.search(r"(女性|男性|女|男)(?:性)?客户", query)
    if not match:
        return []
    return ["女" if "女" in match.group(1) else "男"]


def _extract_filter_values(
    query: str,
    dimensions: list[SemanticSpan],
    group_by_columns: list[str],
    time_spans: list[SemanticSpan],
) -> dict[str, list[str]]:
    filters: dict[str, list[str]] = {}

    brand_values = _extract_brand_shorthand(query)
    if brand_values:
        filters["dim_product.brand"] = brand_values

    gender_values = _extract_gender_filter(query)
    if gender_values and "dim_customer.gender" not in group_by_columns:
        filters["dim_customer.gender"] = gender_values

    for index, dimension in enumerate(dimensions):
        if dimension.value.startswith("dim_date."):
            continue
        if any(
            dimension.start < time_span.end and time_span.start < dimension.end
            for time_span in time_spans
        ):
            continue
        if dimension.value in group_by_columns:
            continue
        if dimension.value in filters:
            continue

        postfix_values = _extract_postfix_value(query, dimension)
        if postfix_values:
            filters[dimension.value] = _dedupe(postfix_values)
            continue

        previous_boundaries = [
            previous.end
            for previous in dimensions[:index]
            if previous.end <= dimension.start
        ]
        previous_boundaries.extend(
            time_span.end
            for time_span in time_spans
            if time_span.end <= dimension.start
        )
        boundary = max(previous_boundaries, default=0)
        prefix = _remove_time_expressions(query[boundary : dimension.start], time_spans)
        prefix_values = _clean_filter_segment(prefix)
        if not prefix_values:
            continue

        if dimension.value == "dim_product.product_name":
            continue
        filters[dimension.value] = _dedupe(prefix_values)

    return filters


def parse_query_semantics(query: str) -> QuerySemanticsState:
    """将电商问数 Query 解析为可复用的确定性语义提示。"""

    time_spans = _extract_time_spans(query)
    metric_spans = _extract_metric_spans(query)
    ranking = _extract_ranking(query)
    dimension_spans = _find_alias_spans(query)
    group_by_columns = _classify_group_by_columns(
        query,
        dimension_spans,
        ranking,
        time_spans,
    )
    filter_values = _extract_filter_values(
        query,
        dimensions=dimension_spans,
        group_by_columns=group_by_columns,
        time_spans=time_spans,
    )

    evidence = [
        *(span.evidence for span in time_spans),
        *(span.evidence for span in metric_spans),
        *(span.evidence for span in ranking.spans),
        *(span.evidence for span in dimension_spans),
    ]
    for column_id in group_by_columns:
        evidence.append(f"分组字段: {column_id}")
    for column_id, values in filter_values.items():
        evidence.append(f"过滤字段: {column_id} -> {'、'.join(values)}")

    return QuerySemanticsState(
        dimension_columns=_dedupe(span.value for span in dimension_spans),
        group_by_columns=group_by_columns,
        filter_values=filter_values,
        metric_terms=_dedupe(span.value for span in metric_spans),
        time_expressions=[span.text for span in time_spans],
        order_direction=ranking.direction,
        limit=ranking.limit,
        parse_evidence=evidence,
    )


def _dedupe(values) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
