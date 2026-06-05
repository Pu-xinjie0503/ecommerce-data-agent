"""
指标召回节点

根据用户问题从指标向量知识库中召回候选指标。
"""

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.errors import build_error_state
from app.agent.exceptions import (
    ExternalServiceError,
    classify_embedding_exception,
    classify_qdrant_exception,
)
from app.agent.nodes.keyword_expansion_cache import expand_keywords_with_cache
from app.agent.state import DataAgentState
from app.core.log import logger
from app.entities.metric_info import MetricInfo


async def recall_metric(
    state: DataAgentState,
    runtime: Runtime[DataAgentContext],
):
    """召回和用户问题语义相关的业务指标"""

    writer = runtime.stream_writer
    step = "召回指标信息"
    writer({"type": "progress", "step": step, "status": "running"})

    try:
        query = state["query"]
        keywords = state["keywords"]

        embedding_client = runtime.context["embedding_client"]
        metric_qdrant_repository = runtime.context["metric_qdrant_repository"]

        try:
            extended_keywords = await expand_keywords_with_cache(
                recall_type="metric",
                prompt_name="extend_keywords_for_metric_recall",
                query=query,
                keywords=keywords,
            )
        except ExternalServiceError as e:
            logger.error(f"{step} LLM keyword expansion failed: {e}")
            writer({"type": "progress", "step": step, "status": "error"})
            return {
                "retrieved_metric_infos": [],
                **build_error_state(
                    error_type=e.error_type,
                    error_message=str(e),
                    error_node="recall_metric",
                    recoverable=True,
                    suggested_action="请稍后重试，或检查 LLM 服务状态、限流和超时配置。",
                ),
            }

        keywords = set(keywords + extended_keywords)

        metric_info_map: dict[str, MetricInfo] = {}

        for keyword in keywords:
            try:
                embedding = await embedding_client.aembed_query(keyword)
            except Exception as e:
                error_type = classify_embedding_exception(e)
                logger.error(f"{step} embedding failed: {e}")
                writer({"type": "progress", "step": step, "status": "error"})
                return {
                    "retrieved_metric_infos": [],
                    **build_error_state(
                        error_type=error_type,
                        error_message=str(e),
                        error_node="recall_metric",
                        recoverable=True,
                        suggested_action="请稍后重试，或检查 Embedding 服务状态与超时配置。",
                    ),
                }

            try:
                current_metric_infos: list[MetricInfo] = await metric_qdrant_repository.search(
                    embedding
                )
            except Exception as e:
                error_type = classify_qdrant_exception(e)
                logger.error(f"{step} qdrant failed: {e}")
                writer({"type": "progress", "step": step, "status": "error"})
                return {
                    "retrieved_metric_infos": [],
                    **build_error_state(
                        error_type=error_type,
                        error_message=str(e),
                        error_node="recall_metric",
                        recoverable=True,
                        suggested_action="请稍后重试，或检查 Qdrant 服务状态与超时配置。",
                    ),
                }

            for metric_info in current_metric_infos:
                if metric_info.id not in metric_info_map:
                    metric_info_map[metric_info.id] = metric_info

        retrieved_metric_infos: list[MetricInfo] = list(metric_info_map.values())

        logger.info(f"检索到指标信息: {list(metric_info_map.keys())}")
        writer({"type": "progress", "step": step, "status": "success"})

        return {"retrieved_metric_infos": retrieved_metric_infos}

    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        raise
