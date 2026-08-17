from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.query_semantics import parse_query_semantics
from app.agent.state import (
    ColumnInfoState,
    DataAgentState,
    MetricInfoState,
    QuerySemanticsState,
    TableInfoState,
)
from app.core.log import logger
from app.entities.value_info import ValueInfo


METRIC_REQUIRED_COLUMNS: dict[str, set[str]] = {
    "gmv": {"fact_order.order_amount"},
    "order_quantity": {"fact_order.order_quantity"},
    "order_count": {"fact_order.order_id"},
    "aov": {"fact_order.order_amount", "fact_order.order_id"},
}


def collect_time_columns(query_semantics: QuerySemanticsState) -> set[str]:
    """返回时间过滤所需的日期维度列。"""

    if not query_semantics["time_expressions"]:
        return set()

    mentioned_date_columns = {
        column_id
        for column_id in query_semantics["dimension_columns"]
        if column_id.startswith("dim_date.")
    }
    return {"dim_date.date_id", *mentioned_date_columns}


def parse_column_id(column_id: str) -> tuple[str, str] | None:
    if "." not in column_id:
        return None

    table_name, column_name = column_id.rsplit(".", 1)
    return table_name, column_name


def collect_metric_columns(metric_infos: list[MetricInfoState]) -> set[str]:
    metric_columns: set[str] = set()

    for metric_info in metric_infos:
        metric_columns.update(metric_info.get("related_columns", []))

    return metric_columns


def collect_value_columns(retrieved_value_infos: list[ValueInfo]) -> set[str]:
    return {
        retrieved_value_info.column_id
        for retrieved_value_info in retrieved_value_infos
        if retrieved_value_info.column_id
    }


def collect_required_columns(
    query_semantics: QuerySemanticsState,
    metric_infos: list[MetricInfoState],
    retrieved_value_infos: list[ValueInfo],
) -> set[str]:
    required_columns = collect_metric_columns(metric_infos)
    required_columns.update(collect_value_columns(retrieved_value_infos))
    required_columns.update(query_semantics["group_by_columns"])
    required_columns.update(query_semantics["filter_values"].keys())
    required_columns.update(collect_time_columns(query_semantics))
    for metric_term in query_semantics["metric_terms"]:
        required_columns.update(METRIC_REQUIRED_COLUMNS.get(metric_term, set()))

    return required_columns


def collect_required_tables(required_columns: set[str]) -> set[str]:
    required_tables = {"fact_order"}

    for column_id in required_columns:
        parsed_column_id = parse_column_id(column_id)
        if parsed_column_id:
            required_tables.add(parsed_column_id[0])

    return required_tables


def should_keep_column(table_name: str, column_info: ColumnInfoState, required_columns: set[str]) -> bool:
    column_name = column_info["name"]
    column_id = f"{table_name}.{column_name}"

    if column_info["role"] in {"primary_key", "foreign_key"}:
        return True

    if column_id in required_columns:
        return True

    return False


def filter_table_columns(table_info: TableInfoState, required_columns: set[str]) -> TableInfoState | None:
    table_name = table_info["name"]
    filtered_columns = [
        column_info
        for column_info in table_info["columns"]
        if should_keep_column(table_name, column_info, required_columns)
    ]

    if not filtered_columns:
        return None

    return TableInfoState(
        name=table_info["name"],
        role=table_info["role"],
        description=table_info["description"],
        columns=filtered_columns,
    )


def filter_tables_by_semantics(
    table_infos: list[TableInfoState],
    query_semantics: QuerySemanticsState,
    metric_infos: list[MetricInfoState],
    retrieved_value_infos: list[ValueInfo],
) -> list[TableInfoState]:
    if not table_infos:
        return []

    required_columns = collect_required_columns(
        query_semantics,
        metric_infos,
        retrieved_value_infos,
    )
    required_tables = collect_required_tables(required_columns)

    available_columns = {
        f"{table_info['name']}.{column_info['name']}"
        for table_info in table_infos
        for column_info in table_info["columns"]
    }
    missing_columns = required_columns - available_columns
    if missing_columns:
        logger.warning(f"语义依赖字段未进入候选上下文，保留过滤前表信息: {sorted(missing_columns)}")
        return table_infos

    filtered_table_infos: list[TableInfoState] = []

    for table_info in table_infos:
        table_name = table_info["name"]
        if table_name not in required_tables:
            continue

        filtered_table_info = filter_table_columns(table_info, required_columns)
        if filtered_table_info:
            filtered_table_infos.append(filtered_table_info)

    if not filtered_table_infos:
        return table_infos

    return filtered_table_infos


async def filter_table(
    state: DataAgentState,
    runtime: Runtime[DataAgentContext],
):
    writer = runtime.stream_writer
    step = "过滤表信息"

    writer({"type": "progress", "step": step, "status": "running"})

    if state.get("error_type"):
        writer({"type": "progress", "step": step, "status": "error"})
        return {}

    try:
        query = state["query"]
        query_semantics = state.get("query_semantics") or parse_query_semantics(query)
        table_infos = state.get("table_infos", [])
        metric_infos = state.get("metric_infos", [])
        retrieved_value_infos = state.get("retrieved_value_infos", [])

        logger.info(f"过滤前表信息: {[table_info['name'] for table_info in table_infos]}")

        filtered_table_infos = filter_tables_by_semantics(
            table_infos=table_infos,
            query_semantics=query_semantics,
            metric_infos=metric_infos,
            retrieved_value_infos=retrieved_value_infos,
        )

        logger.info(f"过滤后表信息: {[table_info['name'] for table_info in filtered_table_infos]}")
        writer({"type": "progress", "step": step, "status": "success"})

        return {"table_infos": filtered_table_infos}

    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        raise
