"""
电商问数 Agent 使用的大模型实例
"""

import asyncio
import time
from typing import Any

from langchain.chat_models import init_chat_model

from app.agent.exceptions import (
    LLMCallResult,
    LLMBusyError,
    LLMServiceError,
    LLMTimeoutError,
    classify_llm_exception,
)
from app.conf.app_config import app_config


llm = init_chat_model(
    model=app_config.llm.model_name,
    model_provider="openai",
    base_url=app_config.llm.base_url,
    api_key=app_config.llm.api_key,
    temperature=0,
)

LLM_MAX_CONCURRENCY = app_config.llm.max_concurrency
_llm_semaphore = asyncio.Semaphore(LLM_MAX_CONCURRENCY)


async def ainvoke_llm_chain(
    chain,
    payload: dict[str, Any],
    *,
    timeout_seconds: int | float | None = None,
    slot_timeout_seconds: int | float | None = None,
) -> LLMCallResult:
    """通过统一的 LLM 并发保护和超时控制调用 LangChain chain。"""

    call_timeout = timeout_seconds or app_config.llm.timeout_seconds
    slot_timeout = slot_timeout_seconds or app_config.llm.slot_timeout_seconds

    wait_started = time.perf_counter()
    try:
        await asyncio.wait_for(_llm_semaphore.acquire(), timeout=slot_timeout)
    except asyncio.TimeoutError as exc:
        raise LLMBusyError(
            f"等待 LLM 并发槽位超过 {slot_timeout} 秒，max_concurrency={LLM_MAX_CONCURRENCY}"
        ) from exc

    wait_ms = (time.perf_counter() - wait_started) * 1000
    call_started = time.perf_counter()
    try:
        try:
            value = await asyncio.wait_for(chain.ainvoke(payload), timeout=call_timeout)
        except asyncio.TimeoutError as exc:
            raise LLMTimeoutError(f"LLM 调用超过 {call_timeout} 秒") from exc
        except Exception as exc:
            raise LLMServiceError(str(exc), error_type=classify_llm_exception(exc)) from exc

        return LLMCallResult(
            value=value,
            waited_for_slot=wait_ms > 0,
            wait_ms=wait_ms,
            call_ms=(time.perf_counter() - call_started) * 1000,
            max_concurrency=LLM_MAX_CONCURRENCY,
        )
    finally:
        _llm_semaphore.release()


if __name__ == "__main__":
    print(llm.invoke("你好").content)
