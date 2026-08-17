"""模糊问数澄清节点。"""

import re
from dataclasses import dataclass

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.errors import clear_error_state
from app.agent.query_semantics import parse_query_semantics
from app.agent.state import DataAgentState, QuerySemanticsState
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
async def clarify_query(
    state: DataAgentState,
    runtime: Runtime[DataAgentContext],
):
    """在进入召回前识别需要业务澄清的模糊问题。"""

    step = "查询澄清判断"
    writer = runtime.stream_writer
    writer({"type": "progress", "step": step, "status": "running"})

    query = state.get("query", "")
    query_semantics = parse_query_semantics(query)
    clarification = check_query_clarification(query, query_semantics)
    if clarification is None:
        writer({"type": "progress", "step": step, "status": "success"})
        result = {
            "need_clarification": False,
            "clarification_type": None,
            "clarification_question": None,
            "clarification_options": [],
            "query_semantics": query_semantics,
            **clear_error_state(success=True),
        }
    else:
        result = {
            "need_clarification": True,
            "clarification_type": clarification.clarification_type,
            "clarification_question": clarification.clarification_question,
            "clarification_options": clarification.clarification_options,
            "query_semantics": query_semantics,
            "sql": None,
            "result": None,
            **clear_error_state(success=False),
        }
        writer({"type": "progress", "step": step, "status": "need_clarification"})
        writer({"type": "clarification", "data": result})
        writer({"type": "result", "data": clarification.clarification_question})

    logger.info(f"查询澄清判断结果: {result}")
    return result


def check_query_clarification(
    query: str,
    query_semantics: QuerySemanticsState | None = None,
) -> ClarificationResult | None:
    normalized_query = normalize_query(query)
    semantics = query_semantics or parse_query_semantics(query)
    if needs_metric_clarification(normalized_query, semantics):
        return ClarificationResult(
            clarification_type="metric_ambiguity",
            clarification_question="你想按销售额、销量，还是订单数来判断“最好”？",
            clarification_options=["销售额", "销量", "订单数"],
        )

    if needs_time_clarification(normalized_query, semantics):
        return ClarificationResult(
            clarification_type="time_range_ambiguity",
            clarification_question="你说的“最近”是指最近 7 天、最近 30 天，还是最近一个自然月？",
            clarification_options=["最近7天", "最近30天", "最近一个自然月"],
        )

    if needs_dimension_metric_clarification(normalized_query, semantics):
        return ClarificationResult(
            clarification_type="metric_ambiguity",
            clarification_question="你想按销售额、销量，还是订单数来看各维度情况？",
            clarification_options=["销售额", "销量", "订单数"],
        )

    if needs_broad_analysis_clarification(normalized_query, semantics):
        return ClarificationResult(
            clarification_type="broad_analysis_request",
            clarification_question="你希望从哪个维度查看？例如按大区、商品品类、品牌或会员等级。",
            clarification_options=["按大区", "按商品品类", "按品牌", "按会员等级"],
        )

    return None


def normalize_query(query: str) -> str:
    return re.sub(r"\s+", "", query.strip().lower())


def needs_metric_clarification(query: str, semantics: QuerySemanticsState) -> bool:
    return any(word in query for word in AMBIGUOUS_RANKING_WORDS) and not semantics["metric_terms"]


def needs_time_clarification(query: str, semantics: QuerySemanticsState) -> bool:
    return any(word in query for word in RECENT_WORDS) and not semantics["time_expressions"]


def needs_dimension_metric_clarification(query: str, semantics: QuerySemanticsState) -> bool:
    if semantics["metric_terms"]:
        return False
    return any(re.search(pattern, query) for pattern in DIMENSION_ANALYSIS_PATTERNS)


def needs_broad_analysis_clarification(query: str, semantics: QuerySemanticsState) -> bool:
    if not any(re.search(pattern, query) for pattern in BROAD_ANALYSIS_PATTERNS):
        return False
    return not (
        semantics["metric_terms"]
        or semantics["time_expressions"]
        or semantics["dimension_columns"]
        or semantics["filter_values"]
    )
