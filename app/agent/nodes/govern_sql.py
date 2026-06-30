"""SQL 执行前治理节点。

负责在数据库 EXPLAIN 和执行之前，统一完成只读安全校验、结果集上限和权限条件注入。
"""

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.errors import AgentErrorType, build_error_state, clear_error_state
from app.agent.state import DataAgentState
from app.core.log import logger
from app.security.permission_policy import (
    PermissionContext,
    PermissionDenied,
    apply_permission_policy,
)
from app.security.sql_policy import SQLPolicyViolation, enforce_sql_policy
from app.utils.sql_parser import extract_sql


async def govern_sql(
    state: DataAgentState,
    runtime: Runtime[DataAgentContext],
):
    """治理 LLM 生成的 SQL，保证后续校验和执行使用同一条安全 SQL。"""

    writer = runtime.stream_writer
    step = "SQL执行前治理"
    writer({"type": "progress", "step": step, "status": "running"})

    try:
        sql = extract_sql(state["sql"])
        policy_result = enforce_sql_policy(sql)
        permission_context = runtime.context.get("permission_context") or PermissionContext()
        permission_result = apply_permission_policy(policy_result.sql, permission_context)

        governance_warnings = policy_result.warnings + permission_result.warnings
        logger.info(f"SQL执行前治理完成: {permission_result.sql}")
        writer({"type": "progress", "step": step, "status": "success"})

        return {
            "sql": permission_result.sql,
            "governance_warnings": governance_warnings,
            **clear_error_state(success=True),
        }

    except SQLPolicyViolation as e:
        logger.warning(f"{step} SQL安全策略拒绝: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        return {
            "error": str(e),
            **build_error_state(
                error_type=AgentErrorType.SQL_POLICY_VIOLATION,
                error_message=str(e),
                error_node="govern_sql",
                recoverable=False,
                suggested_action="请改写为只读、单语句、非敏感字段查询。",
            ),
        }

    except PermissionDenied as e:
        logger.warning(f"{step} 权限策略拒绝: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        return {
            "error": str(e),
            **build_error_state(
                error_type=AgentErrorType.PERMISSION_DENIED,
                error_message=str(e),
                error_node="govern_sql",
                recoverable=False,
                suggested_action="请确认当前用户的数据权限范围，或联系管理员补充授权。",
            ),
        }

    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        return {
            "error": str(e),
            **build_error_state(
                error_type=AgentErrorType.SQL_POLICY_VIOLATION,
                error_message=str(e),
                error_node="govern_sql",
                recoverable=False,
                suggested_action="请检查生成 SQL、权限上下文和执行前治理策略。",
            ),
        }
