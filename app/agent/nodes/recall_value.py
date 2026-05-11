"""
字段取值召回节点

从字段值全文索引中召回候选取值。
"""

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.state import DataAgentState
from app.core.log import logger
from app.entities.value_info import ValueInfo
from app.prompt.prompt_loader import load_prompt


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

        prompt = PromptTemplate(
            template=load_prompt("extend_keywords_for_value_recall"),
            input_variables=["query"],
        )

        output_parser = JsonOutputParser()
        chain = prompt | llm | output_parser

        extended_keywords = await chain.ainvoke({"query": query})

        value_candidates = normalize_value_candidates([query] + keywords + extended_keywords)
        logger.info(f"字段取值候选词: {value_candidates}")

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

        logger.info(f"检索到字段取值: {[value_info.id for value_info in retrieved_value_infos]}")
        writer({"type": "progress", "step": step, "status": "success"})

        return {"retrieved_value_infos": retrieved_value_infos}

    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        raise