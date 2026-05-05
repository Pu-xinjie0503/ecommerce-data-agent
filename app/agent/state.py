from typing import TypedDict

from app.entities.column_info import ColumnInfo
from app.entities.metric_info import MetricInfo
from app.entities.value_info import ValueInfo


class DataAgentState(TypedDict, total=False):
    """电商问数 Agent 状态"""

    # 用户原始问题
    query: str

    # 关键词抽取结果
    keywords: list[str]

    # 多路召回结果
    retrieved_column_infos: list[ColumnInfo]
    retrieved_metric_infos: list[MetricInfo]
    retrieved_value_infos: list[ValueInfo]