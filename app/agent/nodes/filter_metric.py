import asyncio

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.core.log import logger


async def filter_metric(
    state: DataAgentState,
    runtime: Runtime[DataAgentContext],
):
    writer = runtime.stream_writer
    step = "过滤指标信息"

    writer({"type": "progress", "step": step, "status": "running"})

    try:
        await asyncio.sleep(0.5)

        writer({"type": "progress", "step": step, "status": "success"})

        return {}

    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        raise