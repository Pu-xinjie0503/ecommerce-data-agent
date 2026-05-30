"""
字段取值召回节点

从字段值全文索引中召回候选取值。
"""

import re

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.errors import AgentErrorType, build_error_state
from app.agent.nodes.keyword_expansion_cache import expand_keywords_with_cache
from app.agent.state import DataAgentState
from app.core.log import logger
from app.entities.value_info import ValueInfo


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


DOMAIN_SUFFIXES: dict[str, list[str]] = {
    "dim_region": ["地区", "区域", "大区"],
    "dim_product.brand": ["品牌"],
    "dim_product.category": ["品类"],
}

DOMAIN_LABELS: dict[str, str] = {
    "dim_region": "地区",
    "dim_product.brand": "品牌",
    "dim_product.category": "品类",
}

DOMAIN_EXAMPLE_VALUES: dict[str, str] = {
    "dim_region": "华北、华东、华南等",
    "dim_product.brand": "美的、三星等",
    "dim_product.category": "食品饮料、手机数码等",
}


def detect_expected_domains(query: str) -> set[str]:
    """检测 query 中期望过滤的字段域。返回域前缀集合（如 {'dim_region'}）。

    只在用户明确指定了过滤值时返回域，group-by 语义（按大区/各地区）不算。
    """
    expected: set[str] = set()
    for domain, suffixes in DOMAIN_SUFFIXES.items():
        for suffix in suffixes:
            idx = query.find(suffix)
            if idx <= 0:
                continue
            # "按大区" / "各地区" 是 group-by，跳过
            if query[idx - 1] in "按各每":
                continue
            expected.add(domain)
            break
    return expected


def extract_domain_filter_values(query: str) -> dict[str, list[str]]:
    """提取用户明确指定的过滤值，按字段域归类。"""
    extracted: dict[str, list[str]] = {}
    for domain, suffixes in DOMAIN_SUFFIXES.items():
        values: list[str] = []
        for suffix in suffixes:
            idx = query.find(suffix)
            if idx <= 0:
                continue
            if query[idx - 1] in "按各每":
                continue
            prefix_text = query[:idx]
            segment = split_after_last_break(prefix_text)
            values.extend(split_multi_values(segment))
            break
        if values:
            extracted[domain] = dedupe_strings(values)
    return extracted


def split_after_last_break(text: str) -> str:
    break_words = ["统计", "查询", "对比"] + [s for suffixes in DOMAIN_SUFFIXES.values() for s in suffixes]
    last_pos = -1
    last_len = 0
    for word in break_words:
        pos = text.rfind(word)
        if pos >= 0 and pos + len(word) > last_pos + last_len:
            last_pos = pos
            last_len = len(word)
    for index, char in enumerate(text):
        if char in "，,；;：:" and index > last_pos:
            last_pos = index
            last_len = 1
    return text[last_pos + last_len:].strip() if last_pos >= 0 else text.strip()


def split_multi_values(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []

    parts = re.split(r"和|与|、|,|，|及", text)
    values: list[str] = []
    for part in parts:
        value = part.strip()
        if not value or value in {"按", "各", "每个", "分别", "统计", "查询", "对比", "的"}:
            continue
        values.append(value)
    return values


def dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def find_matched_values(expected_values: list[str], value_infos: list[ValueInfo], domain: str) -> list[str]:
    matched: list[str] = []
    domain_value_infos = [vi for vi in value_infos if vi.column_id.startswith(domain)]
    for expected_value in expected_values:
        if any(vi.value == expected_value for vi in domain_value_infos):
            matched.append(expected_value)
    return matched


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
        keywords = state["keywords"]

        value_es_repository = runtime.context["value_es_repository"]

        extended_keywords = await expand_keywords_with_cache(
            recall_type="value",
            prompt_name="extend_keywords_for_value_recall",
            query=query,
            keywords=keywords,
        )

        value_candidates = normalize_value_candidates([query] + keywords + extended_keywords)
        logger.info(f"字段取值候选词: {value_candidates}")

        expected_domains = detect_expected_domains(query)
        domain_filter_values = extract_domain_filter_values(query)
        if expected_domains:
            logger.info(f"域期望: {expected_domains}")
            logger.info(f"字段取值 grounding 目标: {domain_filter_values}")

        exact_value_infos = await value_es_repository.search_exact_values(value_candidates)

        if exact_value_infos:
            retrieved_value_infos = dedupe_value_infos(exact_value_infos)
            logger.info(f"字段取值精确命中: {[value_info.id for value_info in retrieved_value_infos]}")
        else:
            logger.info("字段取值精确匹配未命中，退回模糊召回")
            fuzzy_value_infos: list[ValueInfo] = []

            for keyword in value_candidates:
                fuzzy_value_infos.extend(await value_es_repository.search(keyword))

            retrieved_value_infos = dedupe_value_infos(fuzzy_value_infos)

            # 如果有域期望，过滤掉不属于期望域的模糊结果
            if expected_domains:
                retrieved_value_infos = [
                    vi for vi in retrieved_value_infos
                    if any(vi.column_id.startswith(d) for d in expected_domains)
                ]
                logger.info(f"字段取值模糊召回域过滤后: {[value_info.id for value_info in retrieved_value_infos]}")

        # 逐值 grounding 检查
        if domain_filter_values:
            all_missing_values: list[str] = []
            all_matched_values: list[str] = []
            failed_domains: list[str] = []
            partial_warning_domain: str | None = None
            missing_values_by_domain: dict[str, list[str]] = {}
            matched_values_by_domain: dict[str, list[str]] = {}

            for domain, expected_values in domain_filter_values.items():
                matched_values = find_matched_values(expected_values, retrieved_value_infos, domain)
                missing_values = [value for value in expected_values if value not in matched_values]
                logger.info(
                    f"字段取值 grounding 结果: domain={domain}, "
                    f"matched={matched_values}, missing={missing_values}"
                )

                missing_values_by_domain[domain] = missing_values
                matched_values_by_domain[domain] = matched_values
                all_missing_values.extend(missing_values)
                all_matched_values.extend(matched_values)

                if expected_values and not matched_values:
                    failed_domains.append(domain)
                elif missing_values:
                    partial_warning_domain = partial_warning_domain or domain

            if failed_domains:
                failed_domain = failed_domains[0]
                failed_missing_values = missing_values_by_domain[failed_domain]
                error_msg = build_error_message(failed_domain, failed_missing_values)
                logger.warning(f"字段取值 grounding 失败: {error_msg}")
                writer({"type": "progress", "step": step, "status": "error"})
                return {
                    "retrieved_value_infos": [],
                    "missing_values": failed_missing_values,
                    "matched_values": matched_values_by_domain.get(failed_domain, []),
                    **build_error_state(
                        error_type=AgentErrorType.VALUE_GROUNDING_FAILED,
                        error_message=error_msg,
                        error_node="recall_value",
                        recoverable=True,
                        suggested_action=build_suggested_action(failed_domain),
                    ),
                }

            if all_missing_values and all_matched_values:
                warning_domain = partial_warning_domain or next(iter(domain_filter_values))
                warning_message = build_warning_message(
                    warning_domain,
                    missing_values_by_domain[warning_domain],
                    matched_values_by_domain[warning_domain],
                )
                logger.warning(f"字段取值部分 grounding 失败: {warning_message}")
                return_state = {
                    "retrieved_value_infos": retrieved_value_infos,
                    "warning_type": "partial_value_grounding_failed",
                    "warning_message": warning_message,
                    "missing_values": all_missing_values,
                    "matched_values": all_matched_values,
                }
                logger.info(f"检索到字段取值: {[value_info.id for value_info in retrieved_value_infos]}")
                writer({"type": "progress", "step": step, "status": "success"})
                return return_state

        logger.info(f"检索到字段取值: {[value_info.id for value_info in retrieved_value_infos]}")
        writer({"type": "progress", "step": step, "status": "success"})

        return {"retrieved_value_infos": retrieved_value_infos}

    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        raise