"""
字段召回节点

根据关键词从字段向量知识库中召回候选字段。
"""

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.nodes.keyword_expansion_cache import expand_keywords_with_cache
from app.agent.state import DataAgentState
from app.core.log import logger
from app.entities.column_info import ColumnInfo


async def recall_column(
    state: DataAgentState,
    runtime: Runtime[DataAgentContext],
):
    """召回和用户问题语义相关的字段元数据"""

    writer = runtime.stream_writer
    step = "召回字段信息"
    writer({"type": "progress", "step": step, "status": "running"})

    try:
        query = state["query"]
        keywords = state["keywords"]

        column_qdrant_repository = runtime.context["column_qdrant_repository"]
        embedding_client = runtime.context["embedding_client"]

        extended_keywords = await expand_keywords_with_cache(
            recall_type="column",
            prompt_name="extend_keywords_for_column_recall",
            query=query,
            keywords=keywords,
        )

        keywords = set(keywords + extended_keywords)

        column_info_map: dict[str, ColumnInfo] = {}

        for keyword in keywords:
            embedding = await embedding_client.aembed_query(keyword)

            current_column_infos: list[ColumnInfo] = await column_qdrant_repository.search(
                embedding
            )

            for column_info in current_column_infos:
                if column_info.id not in column_info_map:
                    column_info_map[column_info.id] = column_info

        retrieved_column_infos: list[ColumnInfo] = list(column_info_map.values())

        logger.info(f"检索到字段信息: {list(column_info_map.keys())}")
        writer({"type": "progress", "step": step, "status": "success"})

        return {"retrieved_column_infos": retrieved_column_infos}

    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        raise