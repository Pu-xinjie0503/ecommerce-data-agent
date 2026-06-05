"""问数查询服务

负责把 API 层传入的自然语言问题转换成一次 LangGraph 工作流执行：
创建初始 State、组装 Runtime Context、消费 graph.astream 的流式输出，
并统一包装成 SSE 文本返回给路由层。
"""

import asyncio
import json
import uuid

from app.clients.embedding_client_manager import EmbeddingClientManager

from app.agent.context import DataAgentContext
from app.agent.errors import AgentErrorType
from app.agent.graph import graph
from app.agent.state import DataAgentState
from app.core.context import request_id_ctx_var
from app.observability.trace_manager import TraceManager
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository


class QueryService:
    """封装一次问数查询所需的业务编排逻辑"""

    def __init__(
        self,
        meta_mysql_repository: MetaMySQLRepository,
        embedding_client: EmbeddingClientManager,
        dw_mysql_repository: DWMySQLRepository,
        column_qdrant_repository: ColumnQdrantRepository,
        metric_qdrant_repository: MetricQdrantRepository,
        value_es_repository: ValueESRepository,
    ):
        self.meta_mysql_repository = meta_mysql_repository
        self.dw_mysql_repository = dw_mysql_repository

        self.embedding_client = embedding_client
        self.column_qdrant_repository = column_qdrant_repository
        self.metric_qdrant_repository = metric_qdrant_repository
        self.value_es_repository = value_es_repository

    async def query(self, query: str):
        """执行一次问数工作流，并逐段产出 SSE 消息"""

        request_id = uuid.uuid4().hex
        request_id_token = request_id_ctx_var.set(request_id)
        trace_manager = TraceManager(request_id=request_id, query=query)
        state = DataAgentState(query=query)

        context = DataAgentContext(
            column_qdrant_repository=self.column_qdrant_repository,
            embedding_client=self.embedding_client,
            metric_qdrant_repository=self.metric_qdrant_repository,
            value_es_repository=self.value_es_repository,
            meta_mysql_repository=self.meta_mysql_repository,
            dw_mysql_repository=self.dw_mysql_repository,
            request_id=request_id,
            trace_manager=trace_manager,
        )

        try:
            final_state: dict = {}
            async for stream_mode, chunk in graph.astream(
                input=state,
                context=context,
                stream_mode=["custom", "values"],
            ):
                if stream_mode == "custom":
                    yield f"data: {json.dumps(chunk, ensure_ascii=False, default=str)}\n\n"
                elif stream_mode == "values":
                    final_state = dict(chunk)

            trace_status = "failed" if final_state.get("error_type") else "success"
            trace_manager.finish(trace_status)
            trace_path = trace_manager.save()
            final_response = build_final_response(
                request_id=request_id,
                state=final_state,
                trace_path=trace_path,
            )
            yield f"data: {json.dumps(final_response, ensure_ascii=False, default=str)}\n\n"

        except Exception as e:
            trace_manager.finish("failed")
            trace_path = trace_manager.save()
            error_type = (
                AgentErrorType.API_REQUEST_TIMEOUT.value
                if isinstance(e, asyncio.TimeoutError)
                else AgentErrorType.API_INTERNAL_ERROR.value
            )
            error = build_final_response(
                request_id=request_id,
                state={
                    "success": False,
                    "error_type": error_type,
                    "error_message": str(e),
                    "error_node": "query_service",
                    "recoverable": False,
                    "suggested_action": "请查看 trace 定位失败节点后重试。",
                },
                trace_path=trace_path,
            )
            yield f"data: {json.dumps(error, ensure_ascii=False, default=str)}\n\n"
        finally:
            request_id_ctx_var.reset(request_id_token)


def build_final_response(request_id: str, state: dict, trace_path: str) -> dict:
    if state.get("need_clarification"):
        return {
            "type": "final",
            "request_id": request_id,
            "success": False,
            "status": "need_clarification",
            "need_clarification": True,
            "clarification_type": state.get("clarification_type"),
            "clarification_question": state.get("clarification_question"),
            "clarification_options": state.get("clarification_options", []),
            "sql": None,
            "result": None,
            "error_type": state.get("error_type"),
            "error_message": state.get("error_message"),
            "recoverable": state.get("recoverable", False),
            "suggested_action": state.get("suggested_action"),
            "trace_path": trace_path,
        }

    return {
        "type": "final",
        "request_id": request_id,
        "success": state.get("success", state.get("error_type") is None),
        "status": "success" if state.get("error_type") is None else "failed",
        "need_clarification": False,
        "clarification_type": state.get("clarification_type"),
        "clarification_question": state.get("clarification_question"),
        "clarification_options": state.get("clarification_options", []),
        "sql": state.get("sql"),
        "result": state.get("result"),
        "error_type": state.get("error_type"),
        "error_message": state.get("error_message"),
        "recoverable": state.get("recoverable", False),
        "suggested_action": state.get("suggested_action"),
        "warning_type": state.get("warning_type"),
        "warning_message": state.get("warning_message"),
        "missing_values": state.get("missing_values"),
        "matched_values": state.get("matched_values"),
        "trace_path": trace_path,
    }
