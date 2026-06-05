from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.errors import AgentErrorType, build_error_state, clear_error_state
from app.agent.exceptions import ExternalServiceError
from app.agent.state import DataAgentState
from app.core.log import logger
from app.utils.sql_parser import extract_sql


async def run_sql(
    state: DataAgentState,
    runtime: Runtime[DataAgentContext],
):
    writer = runtime.stream_writer
    step = "执行SQL"

    writer({"type": "progress", "step": step, "status": "running"})

    try:
        sql = extract_sql(state["sql"])

        dw_mysql_repository = runtime.context["dw_mysql_repository"]

        result = await dw_mysql_repository.run(sql)

        logger.info(f"SQL执行结果：{result}")

        writer({"type": "progress", "step": step, "status": "success"})
        writer({"type": "result", "data": result})

        result_state = clear_error_state(success=True)
        if is_empty_result(result):
            result_state.update(
                {
                    "error_type": AgentErrorType.EMPTY_RESULT.value,
                    "error_message": "SQL 执行成功，但结果为空或聚合结果为 None。",
                    "error_node": "run_sql",
                    "recoverable": True,
                    "suggested_action": "请确认查询条件、时间范围或底层数据是否存在。",
                }
            )

        return {
            "result": result,
            **result_state,
        }

    except ExternalServiceError as e:
        logger.error(f"{step} external service failed: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        return {
            "result": None,
            **build_error_state(
                error_type=e.error_type,
                error_message=str(e),
                error_node="run_sql",
                recoverable=True,
                suggested_action="请稍后重试，或检查 MySQL 服务状态与超时配置。",
            ),
        }

    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        return {
            "result": None,
            **build_error_state(
                error_type=AgentErrorType.SQL_EXECUTION_FAILED,
                error_message=str(e),
                error_node="run_sql",
                recoverable=False,
                suggested_action="请检查数据库连接、SQL 执行权限和生成 SQL 的表字段是否有效。",
            ),
        }


def is_empty_result(result: object) -> bool:
    if result == []:
        return True
    if isinstance(result, list) and len(result) == 1 and isinstance(result[0], dict):
        return all(value is None for value in result[0].values())
    return False