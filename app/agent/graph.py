"""
电商问数 Agent 图编排

使用 LangGraph 把问数智能体的各个节点串成一条可观测的执行链路。

当前链路已经落地：
1. 关键词抽取
2. 多路召回
   - 字段召回：Qdrant 向量检索
   - 字段取值召回：Elasticsearch 全文检索
   - 指标召回：Qdrant 向量检索
3. 召回信息合并
4. 候选表过滤
5. 候选指标过滤
6. 补充额外上下文
7. SQL 生成
8. SQL 校验
9. SQL 修正或执行
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.constants import END, START
from langgraph.graph import StateGraph
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.errors import AgentErrorType
from app.agent.nodes.add_extra_context import add_extra_context
from app.agent.nodes.clarify_query import clarify_query
from app.agent.nodes.correct_sql import correct_sql
from app.agent.nodes.extract_keywords import extract_keywords
from app.agent.nodes.filter_metric import filter_metric
from app.agent.nodes.filter_table import filter_table
from app.agent.nodes.generate_sql import generate_sql
from app.agent.nodes.govern_sql import govern_sql
from app.agent.nodes.guard_query import guard_query
from app.agent.nodes.keyword_expansion_cache import trace_keyword_cache_stats
from app.agent.nodes.merge_retrieved_info import merge_retrieved_info
from app.agent.nodes.recall_column import recall_column
from app.agent.nodes.recall_metric import recall_metric
from app.agent.nodes.recall_value import recall_value
from app.agent.nodes.run_sql import run_sql
from app.agent.nodes.validate_sql import validate_sql
from app.agent.state import DataAgentState
from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.es_client_manager import es_client_manager
from app.clients.mysql_client_manager import (
    dw_mysql_client_manager,
    meta_mysql_client_manager,
)
from app.clients.qdrant_client_manager import qdrant_client_manager
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository


def build_trace_output(output: dict[str, Any], cache_stats: dict[str, int]) -> dict[str, Any]:
    """构造仅用于 Trace 的节点输出，避免缓存统计进入 Agent State。"""

    trace_output = dict(output)
    has_activity = any(
        value
        for key, value in cache_stats.items()
        if not key.endswith("_size")
    )
    if has_activity:
        trace_output["cache_stats"] = cache_stats
    return trace_output


def trace_node(
    name: str,
    node_func: Callable[
        [DataAgentState, Runtime[DataAgentContext]], Awaitable[dict[str, Any]]
    ],
):
    async def wrapped_node(state: DataAgentState, runtime: Runtime[DataAgentContext]):
        trace_manager = runtime.context.get("trace_manager")
        if trace_manager is None:
            return await node_func(state, runtime)

        trace_manager.start_step(name, dict(state))
        embedding_client = runtime.context.get("embedding_client")
        with embedding_client.trace_cache_stats() as embedding_stats, trace_keyword_cache_stats() as keyword_stats:
            try:
                output = await node_func(state, runtime)
            except Exception as exc:
                cache_stats = {
                    **embedding_stats.to_dict(cache_size=len(getattr(embedding_client, "_cache", {}))),
                    **keyword_stats.to_dict(),
                }
                trace_manager.end_step(
                    name,
                    output=build_trace_output(
                        {
                            "success": False,
                            "error_type": state.get("error_type") or AgentErrorType.UNKNOWN_ERROR.value,
                            "error_message": str(exc),
                            "error_node": name,
                            "recoverable": False,
                            "suggested_action": state.get("suggested_action"),
                        },
                        cache_stats,
                    ),
                    error=str(exc),
                )
                raise

            error_message = None
            if isinstance(output, dict) and output.get("success") is False:
                error_message = output.get("error_message")
            cache_stats = {
                **embedding_stats.to_dict(cache_size=len(getattr(embedding_client, "_cache", {}))),
                **keyword_stats.to_dict(),
            }
            trace_manager.end_step(
                name,
                output=build_trace_output(output, cache_stats),
                error=error_message,
            )
            return output

    return wrapped_node


# StateGraph 声明整张图使用的状态结构和运行时上下文结构
graph_builder = StateGraph(
    state_schema=DataAgentState,
    context_schema=DataAgentContext,
)


# 注册节点：每个节点负责问数链路中的一个清晰步骤
# trace_node 只做旁路可观测性记录，不改变节点输入输出语义
graph_builder.add_node("guard_query", trace_node("guard_query", guard_query))
graph_builder.add_node("clarify_query", trace_node("clarify_query", clarify_query))
graph_builder.add_node("extract_keywords", trace_node("extract_keywords", extract_keywords))
graph_builder.add_node("recall_column", trace_node("recall_column", recall_column))
graph_builder.add_node("recall_value", trace_node("recall_value", recall_value))
graph_builder.add_node("recall_metric", trace_node("recall_metric", recall_metric))
graph_builder.add_node(
    "merge_retrieved_info",
    trace_node("merge_retrieved_info", merge_retrieved_info),
)

graph_builder.add_node("filter_metric", trace_node("filter_metric", filter_metric))
graph_builder.add_node("filter_table", trace_node("filter_table", filter_table))
graph_builder.add_node("add_extra_context", trace_node("add_extra_context", add_extra_context))
graph_builder.add_node("generate_sql", trace_node("generate_sql", generate_sql))
graph_builder.add_node("govern_sql", trace_node("govern_sql", govern_sql))
graph_builder.add_node("validate_sql", trace_node("validate_sql", validate_sql))
graph_builder.add_node("correct_sql", trace_node("correct_sql", correct_sql))
graph_builder.add_node("run_sql", trace_node("run_sql", run_sql))


# 从用户问题开始，先做输入侧安全检查
# 安全请求继续进入澄清判断；不安全请求直接结束，不进入后续 Agent 链路
graph_builder.add_edge(START, "guard_query")
graph_builder.add_conditional_edges(
    source="guard_query",
    path=lambda state: "clarify_query" if state["is_safe"] else END,
    path_map={
        "clarify_query": "clarify_query",
        END: END,
    },
)


# 安全请求进入查询澄清判断；需要澄清的问题直接结束，不生成 SQL
graph_builder.add_conditional_edges(
    source="clarify_query",
    path=lambda state: END if state.get("need_clarification") else "extract_keywords",
    path_map={
        END: END,
        "extract_keywords": "extract_keywords",
    },
)


# 关键词抽取后，并行进入三类召回
# 1. recall_column：召回字段信息
# 2. recall_value：召回字段真实取值
# 3. recall_metric：召回业务指标信息
graph_builder.add_edge("extract_keywords", "recall_column")
graph_builder.add_edge("extract_keywords", "recall_value")
graph_builder.add_edge("extract_keywords", "recall_metric")


# 三路召回都进入统一的信息合并节点
graph_builder.add_edge("recall_column", "merge_retrieved_info")
graph_builder.add_edge("recall_value", "merge_retrieved_info")
graph_builder.add_edge("recall_metric", "merge_retrieved_info")


# 合并后的候选信息继续拆成两条线：
# 1. filter_table：过滤候选表
# 2. filter_metric：过滤候选指标
graph_builder.add_edge("merge_retrieved_info", "filter_table")
graph_builder.add_edge("merge_retrieved_info", "filter_metric")


# 表和指标都过滤完成后，统一补充 SQL 生成所需额外上下文
graph_builder.add_edge("filter_table", "add_extra_context")
graph_builder.add_edge("filter_metric", "add_extra_context")


# 补充上下文后，检查是否有 grounding 错误；有则直接结束，无则生成 SQL
graph_builder.add_conditional_edges(
    source="add_extra_context",
    path=lambda state: END if state.get("error_type") else "generate_sql",
    path_map={
        END: END,
        "generate_sql": "generate_sql",
    },
)


# 生成 SQL 后：成功进入校验，LLM/解析等失败直接结束，避免下游覆盖原始错误类型
graph_builder.add_conditional_edges(
    source="generate_sql",
    path=lambda state: END if state.get("error_type") else "govern_sql",
    path_map={
        END: END,
        "govern_sql": "govern_sql",
    },
)


# SQL 执行前治理：只读安全、权限注入和 LIMIT 兜底通过后，再进入数据库 EXPLAIN 校验
graph_builder.add_conditional_edges(
    source="govern_sql",
    path=lambda state: END if state.get("error_type") else "validate_sql",
    path_map={
        END: END,
        "validate_sql": "validate_sql",
    },
)


# SQL 校验通过：直接执行
# 只有 SQL 语法校验失败进入修正；MySQL 等外部错误直接结束
def route_after_validate_sql(state: DataAgentState):
    if state.get("error") is None:
        return "run_sql"
    if state.get("error_type") == AgentErrorType.SQL_VALIDATION_FAILED.value:
        return "correct_sql"
    return END


graph_builder.add_conditional_edges(
    source="validate_sql",
    path=route_after_validate_sql,
    path_map={
        "run_sql": "run_sql",
        "correct_sql": "correct_sql",
        END: END,
    },
)


# 修正 SQL 后：成功再执行；修正失败直接结束
graph_builder.add_conditional_edges(
    source="correct_sql",
    path=lambda state: END if state.get("error_type") else "govern_sql",
    path_map={
        END: END,
        "govern_sql": "govern_sql",
    },
)


# SQL 执行结束，整条图结束
graph_builder.add_edge("run_sql", END)


# 编译后的 graph 是对外使用的 Agent 执行入口
graph = graph_builder.compile()


# 可以临时打开这一行，查看 Mermaid 图结构
# print(graph.get_graph().draw_mermaid())


if __name__ == "__main__":

    async def test():
        """本地调试关键词抽取、多路召回、合并、过滤、SQL 生成执行链路"""

        # 多路召回和上下文补全会访问：
        # Qdrant、Embedding、Elasticsearch、Meta MySQL、DW MySQL
        qdrant_client_manager.init()
        embedding_client_manager.init()
        es_client_manager.init()
        meta_mysql_client_manager.init()
        dw_mysql_client_manager.init()

        # Meta MySQL 用来补齐元数据
        # DW MySQL 用来读取数据库方言、版本，并执行最终 SQL
        async with (
            meta_mysql_client_manager.session_factory() as meta_session,
            dw_mysql_client_manager.session_factory() as dw_session,
        ):
            meta_mysql_repository = MetaMySQLRepository(meta_session)
            dw_mysql_repository = DWMySQLRepository(dw_session)

            # 字段和指标分别使用不同 Qdrant collection
            column_qdrant_repository = ColumnQdrantRepository(
                qdrant_client_manager.client
            )
            metric_qdrant_repository = MetricQdrantRepository(
                qdrant_client_manager.client
            )

            # 字段取值检索使用 Elasticsearch index
            value_es_repository = ValueESRepository(es_client_manager.client)

            # 当前只需要传入原始问题
            # 后续节点会逐步写回关键词、召回结果、过滤结果、SQL 等状态
            state = DataAgentState(
                query="统计华北地区的销售总额",
            )

            context = DataAgentContext(
                column_qdrant_repository=column_qdrant_repository,
                embedding_client=embedding_client_manager,
                metric_qdrant_repository=metric_qdrant_repository,
                value_es_repository=value_es_repository,
                meta_mysql_repository=meta_mysql_repository,
                dw_mysql_repository=dw_mysql_repository,
            )

            # stream_mode="custom" 会接收各节点通过 runtime.stream_writer 写出的进度信息
            async for chunk in graph.astream(
                input=state,
                context=context,
                stream_mode="custom",
            ):
                print(chunk)

        # 关闭显式创建的异步客户端，避免本地调试时连接资源悬挂
        await qdrant_client_manager.close()
        await es_client_manager.close()
        await meta_mysql_client_manager.close()
        await dw_mysql_client_manager.close()

    asyncio.run(test())
