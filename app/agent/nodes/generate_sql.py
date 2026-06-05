import yaml
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.errors import AgentErrorType, build_error_state
from app.agent.exceptions import ExternalServiceError
from app.agent.llm import ainvoke_llm_chain, llm
from app.agent.state import DataAgentState
from app.core.log import logger
from app.prompt.prompt_loader import load_prompt
from app.utils.sql_parser import extract_sql


async def generate_sql(
    state: DataAgentState,
    runtime: Runtime[DataAgentContext],
):
    writer = runtime.stream_writer
    step = "生成SQL"

    writer({"type": "progress", "step": step, "status": "running"})

    try:
        table_infos = state["table_infos"]
        metric_infos = state["metric_infos"]
        date_info = state["date_info"]
        db_info = state["db_info"]
        query = state["query"]

        prompt = PromptTemplate(
            template=load_prompt("generate_sql"),
            input_variables=[
                "table_infos",
                "metric_infos",
                "date_info",
                "db_info",
                "query",
            ],
        )

        output_parser = StrOutputParser()
        chain = prompt | llm | output_parser

        llm_result = await ainvoke_llm_chain(
            chain,
            {
                "table_infos": yaml.dump(
                    table_infos,
                    allow_unicode=True,
                    sort_keys=False,
                ),
                "metric_infos": yaml.dump(
                    metric_infos,
                    allow_unicode=True,
                    sort_keys=False,
                ),
                "date_info": yaml.dump(
                    date_info,
                    allow_unicode=True,
                    sort_keys=False,
                ),
                "db_info": yaml.dump(
                    db_info,
                    allow_unicode=True,
                    sort_keys=False,
                ),
                "query": query,
            },
        )
        result = llm_result.value
        logger.info(
            f"LLM 生成 SQL 调用完成: wait_ms={llm_result.wait_ms:.2f} "
            f"call_ms={llm_result.call_ms:.2f} max_concurrency={llm_result.max_concurrency}"
        )

        raw_sql = result.strip()
        if not raw_sql:
            raise ValueError("LLM 没有返回 SQL 内容")

        clean_sql = extract_sql(raw_sql)

        logger.debug(f"LLM 原始 SQL 输出：{raw_sql}")
        logger.info(f"生成的SQL：{clean_sql}")

        writer({"type": "progress", "step": step, "status": "success"})

        return {
            "sql": clean_sql,
            "llm_wait_ms": llm_result.wait_ms,
            "llm_call_ms": llm_result.call_ms,
            "llm_max_concurrency": llm_result.max_concurrency,
        }

    except ExternalServiceError as e:
        logger.error(f"{step} external service failed: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        return {
            "error": str(e),
            **build_error_state(
                error_type=e.error_type,
                error_message=str(e),
                error_node="generate_sql",
                recoverable=True,
                suggested_action="请稍后重试，或检查 LLM 服务状态、限流和超时配置。",
            ),
        }

    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        error_type = (
            AgentErrorType.SQL_GENERATION_FAILED
            if "没有返回 SQL 内容" in str(e)
            else AgentErrorType.SQL_PARSE_FAILED
        )
        return {
            "error": str(e),
            **build_error_state(
                error_type=error_type,
                error_message=str(e),
                error_node="generate_sql",
                recoverable=False,
                suggested_action="请检查 SQL 生成提示词和召回上下文后重试。",
            ),
        }