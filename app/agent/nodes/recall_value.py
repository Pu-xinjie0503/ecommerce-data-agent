"""
字段取值召回节点

从字段值全文索引中召回候选取值。
"""

import re
from dataclasses import dataclass

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.errors import AgentErrorType, build_error_state
from app.agent.exceptions import classify_es_exception
from app.agent.query_semantics import parse_query_semantics
from app.agent.state import DataAgentState, QuerySemanticsState
from app.core.log import logger
from app.entities.value_info import ValueInfo
from app.resilience.circuit_breaker import call_with_circuit_breaker
from app.resilience.fallback import build_recall_fallback


def normalize_value_candidates(texts: list[str]) -> list[str]:
    suffixes = ["地区", "区域", "大区", "品牌"]
    candidates: list[str] = []
    seen: set[str] = set()

    for text in texts:
        if not text:
            continue

        value = str(text).strip()
        if not value:
            continue

        normalized_values = [value]
        for suffix in suffixes:
            if value.endswith(suffix):
                normalized_values.append(value.removesuffix(suffix).strip())

        for normalized_value in normalized_values:
            if normalized_value and normalized_value not in seen:
                seen.add(normalized_value)
                candidates.append(normalized_value)

    return candidates


DOMAIN_LABELS: dict[str, str] = {
    "dim_region.region_name": "地区",
    "dim_region.province": "省份",
    "dim_product.brand": "品牌",
    "dim_product.category": "品类",
    "dim_product.product_name": "商品",
    "dim_customer.member_level": "会员等级",
    "dim_customer.gender": "性别",
}

DOMAIN_EXAMPLE_VALUES: dict[str, str] = {
    "dim_region.region_name": "华北、华东、华南等",
    "dim_region.province": "北京市、上海市、广东省等",
    "dim_product.brand": "美的、三星等",
    "dim_product.category": "食品饮料、手机数码等",
}


def dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


@dataclass(frozen=True)
class GroundingEvaluation:
    """字段值 Grounding 的确定性匹配结果。"""

    matched_values: list[str]
    missing_values: list[str]
    matched_by_column: dict[str, list[str]]
    missing_by_column: dict[str, list[str]]


def build_grounding_candidates(
    query_semantics: QuerySemanticsState,
) -> dict[str, list[str]]:
    """只返回解析器识别出的明确字段过滤值。"""

    return {
        column_id: dedupe_strings([value for value in values if value.strip()])
        for column_id, values in query_semantics["filter_values"].items()
        if values
    }


def normalize_grounding_value(value: str, column_id: str) -> str:
    """按字段域执行保守的值等价归一化。"""

    normalized = re.sub(r"\s+", "", value).casefold()
    suffixes_by_column = {
        "dim_region.region_name": ("地区", "区域", "大区"),
        "dim_product.brand": ("品牌",),
        "dim_product.category": ("品类", "类别"),
    }
    for suffix in suffixes_by_column.get(column_id, ()):
        if normalized.endswith(suffix):
            normalized = normalized.removesuffix(suffix)
            break
    return normalized


def evaluate_grounding(
    expected_by_column: dict[str, list[str]],
    value_infos: list[ValueInfo],
) -> GroundingEvaluation:
    """按列校验用户指定值是否真实存在，不接受仅语义相似的候选。"""

    matched_by_column: dict[str, list[str]] = {}
    missing_by_column: dict[str, list[str]] = {}
    for column_id, expected_values in expected_by_column.items():
        recalled_values = {
            normalize_grounding_value(value_info.value, column_id)
            for value_info in value_infos
            if value_info.column_id == column_id
        }
        matched = [
            value
            for value in expected_values
            if normalize_grounding_value(value, column_id) in recalled_values
        ]
        missing = [value for value in expected_values if value not in matched]
        matched_by_column[column_id] = matched
        missing_by_column[column_id] = missing

    return GroundingEvaluation(
        matched_values=[value for values in matched_by_column.values() for value in values],
        missing_values=[value for values in missing_by_column.values() for value in values],
        matched_by_column=matched_by_column,
        missing_by_column=missing_by_column,
    )


def build_warning_message(domain: str, missing_values: list[str], matched_values: list[str]) -> str:
    label = DOMAIN_LABELS.get(domain, "字段")
    return (
        f"查询中部分{label}取值未匹配到：{'、'.join(missing_values)}。"
        f"当前结果只包含已匹配到的{label}：{'、'.join(matched_values)}。"
    )


def build_error_message(domain: str, missing_values: list[str]) -> str:
    label = DOMAIN_LABELS.get(domain, "字段")
    values = "、".join(missing_values)
    return f"未在{label}字段中找到{values}对应的取值。"


def build_suggested_action(domain: str) -> str:
    label = DOMAIN_LABELS.get(domain, "字段")
    examples = DOMAIN_EXAMPLE_VALUES.get(domain)
    if examples:
        return f"请检查{label}名称，或改用系统中存在的{label}，例如{examples}。"
    return f"请检查{label}名称，或改用系统中存在的{label}值。"


def dedupe_value_infos(value_infos: list[ValueInfo]) -> list[ValueInfo]:
    value_info_map: dict[str, ValueInfo] = {}

    for value_info in value_infos:
        if value_info.id not in value_info_map:
            value_info_map[value_info.id] = value_info

    return list(value_info_map.values())


async def recall_value(
    state: DataAgentState,
    runtime: Runtime[DataAgentContext],
):
    """召回和用户问题相关的字段取值"""

    writer = runtime.stream_writer
    step = "召回字段取值"
    writer({"type": "progress", "step": step, "status": "running"})

    try:
        query = state["query"]
        query_semantics = state.get("query_semantics") or parse_query_semantics(query)
        grounding_candidates = build_grounding_candidates(query_semantics)
        value_es_repository = runtime.context["value_es_repository"]
        explicit_values = [
            value
            for values in grounding_candidates.values()
            for value in values
        ]
        implicit_values = state.get("keywords", [])
        explicit_candidates = normalize_value_candidates(explicit_values)
        explicit_candidate_set = set(explicit_candidates)
        implicit_candidates = [
            value
            for value in normalize_value_candidates(implicit_values)
            if value not in explicit_candidate_set
        ]
        exact_search_metrics = {
            "explicit_candidate_count": len(explicit_candidates),
            "implicit_candidate_count": len(implicit_candidates),
            "explicit_call_count": 0,
            "implicit_call_count": 0,
            "total_call_count": 0,
        }
        value_search_observability = {
            "value_exact_search_metrics": exact_search_metrics,
            "value_fuzzy_search_skipped": True,
        }
        logger.info(f"显式字段值 exact 召回候选: {explicit_candidates}")
        logger.info(f"隐式字段值 exact 召回候选: {implicit_candidates}")
        if grounding_candidates:
            logger.info(f"字段取值 Grounding 目标: {grounding_candidates}")

        explicit_value_infos = []
        if explicit_candidates:
            try:
                exact_search_metrics["explicit_call_count"] += 1
                exact_search_metrics["total_call_count"] += 1
                explicit_value_infos = await call_with_circuit_breaker(
                    "elasticsearch_value",
                    lambda: value_es_repository.search_exact_values(explicit_candidates),
                )
            except Exception as e:
                classify_es_exception(e)
                logger.error(f"{step} es explicit exact search failed: {e}")
                writer({"type": "progress", "step": step, "status": "success"})
                return build_recall_fallback(
                    result_key="retrieved_value_infos",
                    warning_key="recall_value_warning",
                    dependency_name="Elasticsearch 显式字段值召回",
                    reason=str(e),
                ) | value_search_observability

        implicit_value_infos = []
        implicit_warning: dict[str, str] = {}
        if implicit_candidates:
            try:
                exact_search_metrics["implicit_call_count"] += 1
                exact_search_metrics["total_call_count"] += 1
                implicit_value_infos = await call_with_circuit_breaker(
                    "elasticsearch_value",
                    lambda: value_es_repository.search_exact_values(implicit_candidates),
                )
            except Exception as e:
                classify_es_exception(e)
                logger.warning(f"{step} es implicit exact search failed: {e}")
                fallback = build_recall_fallback(
                    result_key="retrieved_value_infos",
                    warning_key="recall_value_warning",
                    dependency_name="Elasticsearch 隐式字段值召回",
                    reason=str(e),
                )
                implicit_warning["recall_value_warning"] = fallback[
                    "recall_value_warning"
                ]

        retrieved_value_infos = dedupe_value_infos(
            [*explicit_value_infos, *implicit_value_infos]
        )
        logger.info(f"字段取值精确命中: {[value_info.id for value_info in retrieved_value_infos]}")

        if not grounding_candidates:
            logger.info("查询没有明确字段过滤值，跳过存在性校验并保留 exact 召回结果")
            writer({"type": "progress", "step": step, "status": "success"})
            return {
                "retrieved_value_infos": retrieved_value_infos,
                "grounding_validation_skipped": True,
                "value_keyword_expansion_skipped": True,
                "grounding_skip_reason": "no_explicit_filter_values",
                **value_search_observability,
                **implicit_warning,
            }

        evaluation = evaluate_grounding(grounding_candidates, retrieved_value_infos)
        failed_columns = [
            column_id
            for column_id, expected_values in grounding_candidates.items()
            if expected_values and not evaluation.matched_by_column[column_id]
        ]
        if failed_columns:
            failed_column = failed_columns[0]
            failed_missing_values = evaluation.missing_by_column[failed_column]
            error_msg = build_error_message(failed_column, failed_missing_values)
            logger.warning(f"字段取值 Grounding 失败: {error_msg}")
            writer({"type": "progress", "step": step, "status": "error"})
            return {
                "retrieved_value_infos": [],
                "missing_values": failed_missing_values,
                "matched_values": evaluation.matched_by_column[failed_column],
                "grounding_validation_skipped": False,
                "value_keyword_expansion_skipped": True,
                **value_search_observability,
                **implicit_warning,
                **build_error_state(
                    error_type=AgentErrorType.VALUE_GROUNDING_FAILED,
                    error_message=error_msg,
                    error_node="recall_value",
                    recoverable=True,
                    suggested_action=build_suggested_action(failed_column),
                ),
            }

        if evaluation.missing_values and evaluation.matched_values:
            warning_column = next(
                column_id
                for column_id, missing_values in evaluation.missing_by_column.items()
                if missing_values
            )
            warning_message = build_warning_message(
                warning_column,
                evaluation.missing_by_column[warning_column],
                evaluation.matched_by_column[warning_column],
            )
            logger.warning(f"字段取值部分 Grounding 失败: {warning_message}")
            writer({"type": "progress", "step": step, "status": "success"})
            return {
                "retrieved_value_infos": retrieved_value_infos,
                "warning_type": "partial_value_grounding_failed",
                "warning_message": warning_message,
                "missing_values": evaluation.missing_values,
                "matched_values": evaluation.matched_values,
                "grounding_validation_skipped": False,
                "value_keyword_expansion_skipped": True,
                **value_search_observability,
                **implicit_warning,
            }

        logger.info(f"检索到字段取值: {[value_info.id for value_info in retrieved_value_infos]}")
        writer({"type": "progress", "step": step, "status": "success"})

        return {
            "retrieved_value_infos": retrieved_value_infos,
            "grounding_validation_skipped": False,
            "value_keyword_expansion_skipped": True,
            **value_search_observability,
            **implicit_warning,
        }

    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        raise
