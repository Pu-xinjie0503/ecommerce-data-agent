"""SQL 校验节点

负责在真正执行查询前，用数据库 EXPLAIN 解析一次生成的 SQL。
校验结果不在这里决定流程走向，而是通过 state["error"] 交给 graph.py 的条件边判断。
"""

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.core.log import logger
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository


async def validate_sql(
    state: DataAgentState,
    runtime: Runtime[DataAgentContext],
):
    """校验 SQL，并返回 error 字段控制后续条件分支"""

    writer = runtime.stream_writer
    writer("校验SQL")

    sql = state["sql"]

    dw_mysql_repository: DWMySQLRepository = runtime.context["dw_mysql_repository"]

    try:
        await dw_mysql_repository.validate(sql)
        logger.info("SQL语法正确")
        return {
            "error": None,
        }
    except Exception as e:
        logger.info(f"SQL语法错误：{str(e)}")
        return {
            "error": str(e),
        }