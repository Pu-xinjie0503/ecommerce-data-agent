"""SQL 执行节点

负责执行最终 SQL，并记录查询结果。
"""

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.core.log import logger


async def run_sql(
    state: DataAgentState,
    runtime: Runtime[DataAgentContext],
):
    """执行 SQL 并产出最终问数结果"""

    writer = runtime.stream_writer
    writer("执行SQL")

    sql = state["sql"]

    dw_mysql_repository = runtime.context["dw_mysql_repository"]

    result = await dw_mysql_repository.run(sql)

    logger.info(f"SQL执行结果：{result}")

    return {
        "result": result,
    }