"""外部服务异常分类工具。"""

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

from app.agent.errors import AgentErrorType


class ExternalServiceError(RuntimeError):
    """外部服务调用异常基类。"""

    error_type: AgentErrorType

    def __init__(self, message: str, *, error_type: AgentErrorType):
        super().__init__(message)
        self.error_type = error_type


class LLMBusyError(ExternalServiceError):
    """等待 LLM 并发槽位超时。"""

    def __init__(self, message: str):
        super().__init__(message, error_type=AgentErrorType.LLM_BUSY)


class LLMTimeoutError(ExternalServiceError):
    """LLM 调用超时。"""

    def __init__(self, message: str):
        super().__init__(message, error_type=AgentErrorType.LLM_TIMEOUT)


class LLMServiceError(ExternalServiceError):
    """LLM 服务异常。"""

    def __init__(self, message: str, *, error_type: AgentErrorType = AgentErrorType.LLM_UNAVAILABLE):
        super().__init__(message, error_type=error_type)


class EmbeddingTimeoutError(ExternalServiceError):
    """Embedding 服务超时。"""

    def __init__(self, message: str):
        super().__init__(message, error_type=AgentErrorType.EMBEDDING_TIMEOUT)


class EmbeddingServiceError(ExternalServiceError):
    """Embedding 服务异常。"""

    def __init__(self, message: str):
        super().__init__(message, error_type=AgentErrorType.EMBEDDING_SERVICE_ERROR)


class MySQLTimeoutError(ExternalServiceError):
    """MySQL 查询超时。"""

    def __init__(self, message: str):
        super().__init__(message, error_type=AgentErrorType.MYSQL_TIMEOUT)


class MySQLExecutionError(ExternalServiceError):
    """MySQL 执行异常。"""

    def __init__(self, message: str):
        super().__init__(message, error_type=AgentErrorType.MYSQL_EXECUTION_ERROR)


@dataclass(frozen=True)
class LLMCallResult:
    """LLM 调用结果与并发保护观测数据。"""

    value: Any
    waited_for_slot: bool
    wait_ms: float
    call_ms: float
    max_concurrency: int


def classify_llm_exception(exc: Exception) -> AgentErrorType:
    """根据异常对象和文本特征粗粒度识别 LLM 错误类型。"""

    status_code = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status_code is None and response is not None:
        status_code = getattr(response, "status_code", None)

    message = str(exc).lower()
    if status_code == 401 or "unauthorized" in message or "authentication" in message:
        return AgentErrorType.LLM_AUTH_FAILED
    if status_code == 429 or "rate limit" in message or "rate_limit" in message:
        return AgentErrorType.LLM_RATE_LIMITED
    if "quota" in message or "insufficient" in message:
        return AgentErrorType.LLM_QUOTA_EXCEEDED
    return AgentErrorType.LLM_UNAVAILABLE


def classify_qdrant_exception(exc: Exception) -> AgentErrorType:
    """识别 Qdrant 超时或服务异常。"""

    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return AgentErrorType.QDRANT_TIMEOUT
    message = str(exc).lower()
    if "timeout" in message or "timed out" in message:
        return AgentErrorType.QDRANT_TIMEOUT
    return AgentErrorType.QDRANT_SERVICE_ERROR


def classify_es_exception(exc: Exception) -> AgentErrorType:
    """识别 Elasticsearch 超时或服务异常。"""

    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return AgentErrorType.ES_TIMEOUT
    message = str(exc).lower()
    if "timeout" in message or "timed out" in message:
        return AgentErrorType.ES_TIMEOUT
    return AgentErrorType.ES_SERVICE_ERROR


def classify_embedding_exception(exc: Exception) -> AgentErrorType:
    """识别 Embedding 超时或服务异常。"""

    if isinstance(exc, EmbeddingTimeoutError):
        return AgentErrorType.EMBEDDING_TIMEOUT
    if isinstance(exc, httpx.TimeoutException):
        return AgentErrorType.EMBEDDING_TIMEOUT
    message = str(exc).lower()
    if "timeout" in message or "timed out" in message:
        return AgentErrorType.EMBEDDING_TIMEOUT
    return AgentErrorType.EMBEDDING_SERVICE_ERROR


def classify_mysql_exception(exc: Exception) -> AgentErrorType:
    """识别 MySQL 超时或执行异常。"""

    if isinstance(exc, MySQLTimeoutError):
        return AgentErrorType.MYSQL_TIMEOUT
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return AgentErrorType.MYSQL_TIMEOUT
    message = str(exc).lower()
    if "timeout" in message or "timed out" in message:
        return AgentErrorType.MYSQL_TIMEOUT
    return AgentErrorType.MYSQL_EXECUTION_ERROR
