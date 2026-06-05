from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import ColumnInfoState, DataAgentState, MetricInfoState, TableInfoState
from app.core.log import logger
from app.entities.value_info import ValueInfo


GROUP_BY_TRIGGERS = ["各", "按", "每个", "分别", "分组"]
TIME_KEYWORDS = ["年", "月", "季度", "第一季度", "第二季度", "第三季度", "第四季度", "Q1", "Q2", "Q3", "Q4"]
REGION_KEYWORDS = ["大区", "地区", "省份", "华北", "华南", "华东", "华中", "东北", "西北", "西南"]
PRODUCT_KEYWORDS = ["品牌", "商品", "品类", "销量"]
CUSTOMER_KEYWORDS = ["会员等级", "会员", "客户"]


def has_any(query: str, keywords: list[str]) -> bool:
    query_lower = query.lower()
    return any(keyword.lower() in query_lower for keyword in keywords)


def parse_column_id(column_id: str) -> tuple[str, str] | None:
    if "." not in column_id:
        return None

    table_name, column_name = column_id.rsplit(".", 1)
    return table_name, column_name


def detect_group_by_columns(query: str) -> set[str]:
    if not has_any(query, GROUP_BY_TRIGGERS):
        return set()

    group_by_columns: set[str] = set()

    if "品类" in query or "商品品类" in query:
        group_by_columns.add("dim_product.category")

    if "大区" in query or "地区" in query:
        group_by_columns.add("dim_region.region_name")

    if "会员等级" in query:
        group_by_columns.add("dim_customer.member_level")

    return group_by_columns


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
    query: str,
    metric_infos: list[MetricInfoState],
    retrieved_value_infos: list[ValueInfo],
) -> set[str]:
    required_columns = collect_metric_columns(metric_infos)
    required_columns.update(collect_value_columns(retrieved_value_infos))
    required_columns.update(detect_group_by_columns(query))

    if has_any(query, TIME_KEYWORDS):
        required_columns.update(
            {
                "dim_date.date_id",
                "dim_date.year",
                "dim_date.quarter",
                "dim_date.month",
                "dim_date.day",
            }
        )

    if "销量" in query:
        required_columns.add("fact_order.order_quantity")

    return required_columns


def collect_required_tables(query: str, required_columns: set[str]) -> set[str]:
    required_tables = {"fact_order"}

    for column_id in required_columns:
        parsed_column_id = parse_column_id(column_id)
        if parsed_column_id:
            required_tables.add(parsed_column_id[0])

    if has_any(query, TIME_KEYWORDS):
        required_tables.add("dim_date")

    if has_any(query, PRODUCT_KEYWORDS):
        required_tables.add("dim_product")

    if has_any(query, REGION_KEYWORDS):
        required_tables.add("dim_region")

    if has_any(query, CUSTOMER_KEYWORDS):
        required_tables.add("dim_customer")

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


def filter_tables_by_rules(
    query: str,
    table_infos: list[TableInfoState],
    metric_infos: list[MetricInfoState],
    retrieved_value_infos: list[ValueInfo],
) -> list[TableInfoState]:
    if not table_infos:
        return []

    required_columns = collect_required_columns(query, metric_infos, retrieved_value_infos)
    required_tables = collect_required_tables(query, required_columns)

    filtered_table_infos: list[TableInfoState] = []

    for table_info in table_infos:
        table_name = table_info["name"]
        if table_name not in required_tables and table_info["role"] != "fact":
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
        table_infos = state.get("table_infos", [])
        metric_infos = state.get("metric_infos", [])
        retrieved_value_infos = state.get("retrieved_value_infos", [])

        logger.info(f"过滤前表信息: {[table_info['name'] for table_info in table_infos]}")

        filtered_table_infos = filter_tables_by_rules(
            query=query,
            table_infos=table_infos,
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
