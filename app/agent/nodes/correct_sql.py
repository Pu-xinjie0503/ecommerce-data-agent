import yaml
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.errors import AgentErrorType, build_error_state, clear_error_state
from app.agent.llm import llm
from app.agent.state import DataAgentState
from app.core.log import logger
from app.prompt.prompt_loader import load_prompt
from app.utils.sql_parser import extract_sql


async def correct_sql(
    state: DataAgentState,
    runtime: Runtime[DataAgentContext],
):
    writer = runtime.stream_writer
    step = "校正SQL"

    writer({"type": "progress", "step": step, "status": "running"})

    try:
        table_infos = state["table_infos"]
        metric_infos = state["metric_infos"]
        date_info = state["date_info"]
        db_info = state["db_info"]
        query = state["query"]

        sql = state["sql"]
        error = state["error"]

        prompt = PromptTemplate(
            template=load_prompt("correct_sql"),
            input_variables=[
                "table_infos",
                "metric_infos",
                "date_info",
                "db_info",
                "query",
                "sql",
                "error",
            ],
        )

        output_parser = StrOutputParser()
        chain = prompt | llm | output_parser

        result = await chain.ainvoke(
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
                "sql": sql,
                "error": error,
            }
        )

        raw_sql = result.strip()
        if not raw_sql:
            raise ValueError("LLM 没有返回校正 SQL 内容")

        clean_sql = extract_sql(raw_sql)

        logger.debug(f"LLM 原始校正 SQL 输出：{raw_sql}")
        logger.info(f"校正后的SQL：{clean_sql}")

        writer({"type": "progress", "step": step, "status": "success"})

        return {
            "sql": clean_sql,
            "error": None,
            **clear_error_state(success=True),
        }

    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        return {
            "error": str(e),
            **build_error_state(
                error_type=AgentErrorType.SQL_CORRECTION_FAILED,
                error_message=str(e),
                error_node="correct_sql",
                recoverable=False,
                suggested_action="请检查原始 SQL、校验错误和可用表字段上下文后重试。",
            ),
        }