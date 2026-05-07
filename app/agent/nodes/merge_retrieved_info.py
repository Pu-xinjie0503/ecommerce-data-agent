from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import (
    ColumnInfoState,
    DataAgentState,
    MetricInfoState,
    TableInfoState,
)
from app.core.log import logger
from app.entities.column_info import ColumnInfo
from app.entities.metric_info import MetricInfo
from app.entities.table_info import TableInfo
from app.entities.value_info import ValueInfo

import json

def normalize_examples(examples):
    if examples is None:
        return []

    if isinstance(examples, list):
        return examples

    if isinstance(examples, tuple):
        return list(examples)

    if isinstance(examples, str):
        text = examples.strip()

        if not text:
            return []

        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
            return [parsed]
        except Exception:
            return [text]

    return [examples]

async def merge_retrieved_info(
    state: DataAgentState,
    runtime: Runtime[DataAgentContext],
):
    """合并召回结果，输出后续 SQL 生成需要的表结构上下文和指标上下文"""

    writer = runtime.stream_writer
    step = "合并召回信息"
    writer({"type": "progress", "step": step, "status": "running"})

    try:
        retrieved_column_infos: list[ColumnInfo] = state["retrieved_column_infos"]
        retrieved_metric_infos: list[MetricInfo] = state["retrieved_metric_infos"]
        retrieved_value_infos: list[ValueInfo] = state["retrieved_value_infos"]

        meta_mysql_repository = runtime.context["meta_mysql_repository"]

        # 1. 先把字段召回结果转成 Map：column_id -> ColumnInfo
        # 这样后续可以按字段 ID 快速去重和补齐。
        retrieved_column_infos_map: dict[str, ColumnInfo] = {
            retrieved_column_info.id: retrieved_column_info
            for retrieved_column_info in retrieved_column_infos
        }

        # 2. 根据指标依赖字段补齐字段信息
        # 比如召回到了 GMV，就必须把 GMV 依赖的 order_amount 字段补进来。
        for retrieved_metric_info in retrieved_metric_infos:
            for related_column in retrieved_metric_info.related_columns:
                if related_column not in retrieved_column_infos_map:
                    column_info = await meta_mysql_repository.get_column_info_by_id(
                        related_column
                    )

                    if column_info is None:
                        logger.warning(f"未找到指标依赖字段：{related_column}")
                        continue

                    retrieved_column_infos_map[related_column] = column_info

        # 3. 根据字段取值补齐字段信息，并把真实值加入 examples
        # 比如召回到 dim_region.region_name.华北，
        # 就把 华北 加入 dim_region.region_name 的 examples。
        for retrieved_value_info in retrieved_value_infos:
            value = retrieved_value_info.value
            column_id = retrieved_value_info.column_id

            if column_id not in retrieved_column_infos_map:
                column_info: ColumnInfo | None = (
                    await meta_mysql_repository.get_column_info_by_id(column_id)
                )

                if column_info is None:
                    logger.warning(f"未找到字段取值所属字段：{column_id}")
                    continue

                retrieved_column_infos_map[column_id] = column_info

            column_info = retrieved_column_infos_map[column_id]

            column_info.examples = normalize_examples(column_info.examples)

            if value not in column_info.examples:
                column_info.examples.append(value)

        # 4. 按 table_id 对字段分组
        # 从 column_id -> ColumnInfo 变成 table_id -> list[ColumnInfo]
        table_to_columns_map: dict[str, list[ColumnInfo]] = {}

        for column_info in retrieved_column_infos_map.values():
            table_id = column_info.table_id

            if table_id not in table_to_columns_map:
                table_to_columns_map[table_id] = []

            table_to_columns_map[table_id].append(column_info)

        # 5. 为每张候选表补齐主键和外键
        # 避免 SQL 生成阶段缺少 join 条件。
        for table_id in table_to_columns_map.keys():
            key_columns: list[ColumnInfo] = (
                await meta_mysql_repository.get_key_columns_by_table_id(table_id)
            )

            column_ids = [
                column_info.id
                for column_info in table_to_columns_map[table_id]
            ]

            for key_column in key_columns:
                if key_column.id not in column_ids:
                    table_to_columns_map[table_id].append(key_column)

        # 6. 组装 table_infos
        table_infos: list[TableInfoState] = []

        for table_id, column_infos in table_to_columns_map.items():
            table_info: TableInfo | None = (
                await meta_mysql_repository.get_table_info_by_id(table_id)
            )

            if table_info is None:
                logger.warning(f"未找到表信息：{table_id}")
                continue

            columns = [
                ColumnInfoState(
                    name=column_info.name,
                    type=column_info.type,
                    role=column_info.role,
                    examples=normalize_examples(column_info.examples),
                    description=column_info.description,
                    alias=column_info.alias,
                )
                for column_info in column_infos
            ]

            table_info_state = TableInfoState(
                name=table_info.name,
                role=table_info.role,
                description=table_info.description,
                columns=columns,
            )

            table_infos.append(table_info_state)

        # 7. 组装 metric_infos
        metric_infos: list[MetricInfoState] = [
            MetricInfoState(
                name=retrieved_metric_info.name,
                description=retrieved_metric_info.description,
                related_columns=retrieved_metric_info.related_columns,
                alias=retrieved_metric_info.alias,
            )
            for retrieved_metric_info in retrieved_metric_infos
        ]

        logger.info(f"合并后的表信息：{[table_info['name'] for table_info in table_infos]}")
        logger.info(f"合并后的指标信息：{[metric_info['name'] for metric_info in metric_infos]}")

        writer({"type": "progress", "step": step, "status": "success"})
        return {
            "table_infos": table_infos,
            "metric_infos": metric_infos,
        }
    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        raise
