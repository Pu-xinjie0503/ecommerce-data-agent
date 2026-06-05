"""Agent 结构化错误类型和状态构造工具。"""

from enum import Enum
from typing import Any


class AgentErrorType(str, Enum):
    UNSAFE_QUERY = "unsafe_query"
    KEYWORD_EXTRACT_FAILED = "keyword_extract_failed"
    VALUE_RECALL_EMPTY = "value_recall_empty"
    COLUMN_RECALL_EMPTY = "column_recall_empty"
    METRIC_RECALL_EMPTY = "metric_recall_empty"
    TABLE_FILTER_EMPTY = "table_filter_empty"
    METRIC_FILTER_EMPTY = "metric_filter_empty"
    SQL_GENERATION_FAILED = "sql_generation_failed"
    SQL_PARSE_FAILED = "sql_parse_failed"
    SQL_VALIDATION_FAILED = "sql_validation_failed"
    SQL_CORRECTION_FAILED = "sql_correction_failed"
    SQL_EXECUTION_FAILED = "sql_execution_failed"
    VALUE_GROUNDING_FAILED = "value_grounding_failed"
    EMPTY_RESULT = "empty_result"
    LLM_TIMEOUT = "llm_timeout"
    LLM_UNAVAILABLE = "llm_unavailable"
    LLM_RATE_LIMITED = "llm_rate_limited"
    LLM_QUOTA_EXCEEDED = "llm_quota_exceeded"
    LLM_AUTH_FAILED = "llm_auth_failed"
    LLM_BUSY = "llm_busy"
    EMBEDDING_TIMEOUT = "embedding_timeout"
    EMBEDDING_SERVICE_ERROR = "embedding_service_error"
    QDRANT_TIMEOUT = "qdrant_timeout"
    QDRANT_SERVICE_ERROR = "qdrant_service_error"
    ES_TIMEOUT = "es_timeout"
    ES_SERVICE_ERROR = "es_service_error"
    MYSQL_TIMEOUT = "mysql_timeout"
    MYSQL_EXECUTION_ERROR = "mysql_execution_error"
    API_REQUEST_TIMEOUT = "api_request_timeout"
    API_INTERNAL_ERROR = "api_internal_error"
    UNKNOWN_ERROR = "unknown_error"


def build_error_state(
    error_type: AgentErrorType,
    error_message: str,
    error_node: str,
    recoverable: bool,
    suggested_action: str | None = None,
) -> dict[str, Any]:
    return {
        "success": False,
        "error_type": error_type.value,
        "error_message": error_message,
        "error_node": error_node,
        "recoverable": recoverable,
        "suggested_action": suggested_action,
    }


def clear_error_state(success: bool = True) -> dict[str, Any]:
    return {
        "success": success,
        "error_type": None,
        "error_message": None,
        "error_node": None,
        "recoverable": False,
        "suggested_action": None,
    }
