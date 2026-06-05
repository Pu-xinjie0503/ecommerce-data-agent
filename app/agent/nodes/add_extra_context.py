from datetime import date

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.errors import build_error_state
from app.agent.exceptions import ExternalServiceError
from app.agent.state import DataAgentState, DateInfoState, DBInfoState
from app.core.log import logger


async def add_extra_context(
    state: DataAgentState,
    runtime: Runtime[DataAgentContext],
):
    writer = runtime.stream_writer
    step = "添加额外上下文"

    writer({"type": "progress", "step": step, "status": "running"})

    try:
        dw_mysql_repository = runtime.context["dw_mysql_repository"]

        today = date.today()
        date_str = today.strftime("%Y-%m-%d")
        weekday = today.strftime("%A")
        quarter = f"Q{(today.month - 1) // 3 + 1}"

        date_info = DateInfoState(
            date=date_str,
            weekday=weekday,
            quarter=quarter,
        )

        db = await dw_mysql_repository.get_db_info()
        db_info = DBInfoState(**db)

        logger.info(f"数据库信息：{db_info}")
        logger.info(f"日期信息：{date_info}")

        writer({"type": "progress", "step": step, "status": "success"})

        return {
            "date_info": date_info,
            "db_info": db_info,
        }

    except ExternalServiceError as e:
        logger.error(f"{step} external service failed: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        return {
            **build_error_state(
                error_type=e.error_type,
                error_message=str(e),
                error_node="add_extra_context",
                recoverable=True,
                suggested_action="请稍后重试，或检查 MySQL 服务状态与超时配置。",
            ),
        }

    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        raise