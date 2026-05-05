"""
电商问数 Agent 状态定义

State 是 LangGraph 各节点之间传递和更新的共享数据。
第 11 章新增关键词列表、三路召回结果，以及合并后的表上下文和指标上下文。
"""

from typing import TypedDict

from app.entities.column_info import ColumnInfo
from app.entities.metric_info import MetricInfo
from app.entities.value_info import ValueInfo


class MetricInfoState(TypedDict):
    """面向 SQL 生成提示词的指标信息"""

    name: str
    description: str
    related_columns: list[str]
    alias: list[str]


class ColumnInfoState(TypedDict):
    """表上下文中的字段信息"""

    name: str
    type: str
    role: str
    examples: list
    description: str
    alias: list[str]


class TableInfoState(TypedDict):
    """SQL 生成阶段真正传给模型的表结构上下文"""

    name: str
    role: str
    description: str
    columns: list[ColumnInfoState]


class DateInfoState(TypedDict):
    """SQL 生成阶段使用的当前日期上下文"""

    date: str
    weekday: str
    quarter: str


class DBInfoState(TypedDict):
    """SQL 生成阶段使用的数据库环境信息"""

    dialect: str
    version: str


class DataAgentState(TypedDict, total=False):
    """一次问数链路中的核心状态"""

    # 用户输入
    query: str

    # 关键词抽取结果
    keywords: list[str]

    # 三路召回结果
    retrieved_column_infos: list[ColumnInfo]
    retrieved_metric_infos: list[MetricInfo]
    retrieved_value_infos: list[ValueInfo]

    # 合并后的上下文
    table_infos: list[TableInfoState]
    metric_infos: list[MetricInfoState]

    # 额外上下文
    date_info: DateInfoState
    db_info: DBInfoState

    # SQL 闭环
    sql: str
    error: str