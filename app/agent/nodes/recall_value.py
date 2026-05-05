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

        keywords = set(keywords + extended_keywords)

        value_info_map: dict[str, ValueInfo] = {}

        for keyword in keywords:
            current_value_infos: list[ValueInfo] = await value_es_repository.search(keyword)

            for value_info in current_value_infos:
                if value_info.id not in value_info_map:
                    value_info_map[value_info.id] = value_info

        retrieved_value_infos: list[ValueInfo] = list(value_info_map.values())

        logger.info(f"检索到字段取值: {list(value_info_map.keys())}")
        writer({"type": "progress", "step": step, "status": "success"})

        return {"retrieved_value_infos": retrieved_value_infos}

    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        raise