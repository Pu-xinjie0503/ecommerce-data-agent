"""模糊问数澄清节点。"""

import re
from dataclasses import dataclass

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.errors import clear_error_state
from app.agent.state import DataAgentState
from app.core.log import logger


@dataclass(frozen=True)
class ClarificationResult:
    clarification_type: str
    clarification_question: str
    clarification_options: list[str]


AMBIGUOUS_RANKING_WORDS = (
    "最好",
    "最差",
    "卖得最好",
    "卖得最差",
    "表现最好",
    "表现最差",
    "排名",
)
EXPLICIT_METRIC_WORDS = (
    "gmv",
    "销售额",
    "销量",
    "订单数",
    "客单价",
    "aov",
)
RECENT_WORDS = ("最近", "近期")
BROAD_ANALYSIS_PATTERNS = (
    r"^(帮我)?分析一下(整体)?(销售|订单)情况$",
    r"^(帮我)?看一下(整体)?(销售|订单)情况$",
    r"^(销售|订单)情况怎么样$",
    r"^(整体)?(销售|订单)情况(如何|怎么样)$",
)
DIMENSION_ANALYSIS_PATTERNS = (
    r"^(帮我)?(看一下|看看|查看|分析一下)?各?(品牌|品类|商品品类|大区|地区|会员等级|会员)(的)?(情况|表现|概况|趋势)$",
    r"^各?(品牌|品类|商品品类|大区|地区|会员等级|会员)(情况|表现|概况|趋势)(如何|怎么样)?$",
)
DIMENSION_WORDS = (
    "大区",
    "地区",
    "品类",
    "商品品类",
    "品牌",
    "会员等级",
    "会员",
    "按",
    "各",
)
FILTER_WORDS = (
    "华北",
    "华东",
    "华南",
    "美的",
    "食品饮料",
    "手机数码",
)
CLEAR_TIME_PATTERN = re.compile(
    r"(\d+\s*天|\d+\s*个月|本月|上月|本季度|上季度|今年|去年|今天|昨天|本周|上周|"
    r"\d{4}\s*年\s*\d{1,2}\s*月|第\s*[一二三四1-4]\s*季度|Q[1-4])",
    flags=re.IGNORECASE,
)


async def clarify_query(
    state: DataAgentState,
    runtime: Runtime[DataAgentContext],
):
    """在进入召回前识别需要业务澄清的模糊问题。"""

    step = "查询澄清判断"
    writer = runtime.stream_writer
    writer({"type": "progress", "step": step, "status": "running"})

    query = state.get("query", "")
    clarification = check_query_clarification(query)
    if clarification is None:
        writer({"type": "progress", "step": step, "status": "success"})
        result = {
            "need_clarification": False,
            "clarification_type": None,
            "clarification_question": None,
            "clarification_options": [],
            **clear_error_state(success=True),
        }
    else:
        result = {
            "need_clarification": True,
            "clarification_type": clarification.clarification_type,
            "clarification_question": clarification.clarification_question,
            "clarification_options": clarification.clarification_options,
            "sql": None,
            "result": None,
            **clear_error_state(success=False),
        }
        writer({"type": "progress", "step": step, "status": "need_clarification"})
        writer({"type": "clarification", "data": result})
        writer({"type": "result", "data": clarification.clarification_question})

    logger.info(f"查询澄清判断结果: {result}")
    return result


def check_query_clarification(query: str) -> ClarificationResult | None:
    normalized_query = normalize_query(query)
    if needs_metric_clarification(normalized_query):
        return ClarificationResult(
            clarification_type="metric_ambiguity",
            clarification_question="你想按销售额、销量，还是订单数来判断“最好”？",
            clarification_options=["销售额", "销量", "订单数"],
        )

    if needs_time_clarification(normalized_query):
        return ClarificationResult(
            clarification_type="time_range_ambiguity",
            clarification_question="你说的“最近”是指最近 7 天、最近 30 天，还是最近一个自然月？",
            clarification_options=["最近7天", "最近30天", "最近一个自然月"],
        )

    if needs_dimension_metric_clarification(normalized_query):
        return ClarificationResult(
            clarification_type="metric_ambiguity",
            clarification_question="你想按销售额、销量，还是订单数来看各维度情况？",
            clarification_options=["销售额", "销量", "订单数"],
        )

    if needs_broad_analysis_clarification(normalized_query):
        return ClarificationResult(
            clarification_type="broad_analysis_request",
            clarification_question="你希望从哪个维度查看？例如按大区、商品品类、品牌或会员等级。",
            clarification_options=["按大区", "按商品品类", "按品牌", "按会员等级"],
        )

    return None


def normalize_query(query: str) -> str:
    return re.sub(r"\s+", "", query.strip().lower())


def needs_metric_clarification(query: str) -> bool:
    return any(word in query for word in AMBIGUOUS_RANKING_WORDS) and not has_explicit_metric(query)


def needs_time_clarification(query: str) -> bool:
    return any(word in query for word in RECENT_WORDS) and not has_clear_time_range(query)


def needs_dimension_metric_clarification(query: str) -> bool:
    if has_explicit_metric(query):
        return False
    return any(re.search(pattern, query) for pattern in DIMENSION_ANALYSIS_PATTERNS)


def needs_broad_analysis_clarification(query: str) -> bool:
    if not any(re.search(pattern, query) for pattern in BROAD_ANALYSIS_PATTERNS):
        return False
    return not (
        has_explicit_metric(query)
        or has_clear_time_range(query)
        or has_dimension(query)
        or has_filter_condition(query)
    )


def has_explicit_metric(query: str) -> bool:
    return any(word in query for word in EXPLICIT_METRIC_WORDS)


def has_clear_time_range(query: str) -> bool:
    return bool(CLEAR_TIME_PATTERN.search(query))


def has_dimension(query: str) -> bool:
    return any(word in query for word in DIMENSION_WORDS)


def has_filter_condition(query: str) -> bool:
    return any(word in query for word in FILTER_WORDS)
