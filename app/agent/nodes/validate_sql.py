from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.errors import AgentErrorType, build_error_state, clear_error_state
from app.agent.exceptions import ExternalServiceError
from app.agent.state import DataAgentState
from app.core.log import logger
from app.observability.sql_risk_analyzer import analyze_sql_risk
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.utils.sql_parser import extract_sql


async def validate_sql(
    state: DataAgentState,
    runtime: Runtime[DataAgentContext],
):
    writer = runtime.stream_writer
    step = "校验SQL"

    writer({"type": "progress", "step": step, "status": "running"})

    try:
        dw_mysql_repository: DWMySQLRepository = runtime.context["dw_mysql_repository"]

        try:
            sql = extract_sql(state["sql"])
            explain_rows = await dw_mysql_repository.validate(sql)
            risk_analysis = analyze_sql_risk(sql, explain_rows)

            logger.info("SQL语法正确")
            writer({"type": "progress", "step": step, "status": "success"})

            result = {
                "sql": sql,
                "error": None,
                "sql_explain": explain_rows,
                "risk_flags": risk_analysis.risk_flags,
                "index_suggestions": risk_analysis.index_suggestions,
                "sql_rewrite_suggestions": risk_analysis.rewrite_suggestions,
                **clear_error_state(success=True),
            }

            return result

        except ExternalServiceError as e:
            logger.error(f"SQL 校验依赖服务异常：{str(e)}")
            writer({"type": "progress", "step": step, "status": "error"})
            return {
                "error": str(e),
                **build_error_state(
                    error_type=e.error_type,
                    error_message=str(e),
                    error_node="validate_sql",
                    recoverable=True,
                    suggested_action="请稍后重试，或检查 MySQL 服务状态与超时配置。",
                ),
            }

        except Exception as e:
            logger.info(f"SQL语法错误：{str(e)}")
            writer({"type": "progress", "step": step, "status": "success"})

            return {
                "error": str(e),
                **build_error_state(
                    error_type=AgentErrorType.SQL_VALIDATION_FAILED,
                    error_message=str(e),
                    error_node="validate_sql",
                    recoverable=True,
                    suggested_action="try_correct_sql",
                ),
            }

    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        raise
