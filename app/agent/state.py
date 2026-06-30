"""
电商问数 Agent 状态定义

State 是 LangGraph 各节点之间传递和更新的共享数据。
第 11 章新增关键词列表、三路召回结果，以及合并后的表上下文和指标上下文。
"""

from typing import Literal, TypedDict

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

    # 输入侧安全检查
    is_safe: bool
    risk_level: Literal["low", "medium", "high"]
    risk_type: Literal[
        "normal_query",
        "prompt_injection",
        "dangerous_sql",
        "sensitive_data_request",
        "write_or_destructive_operation",
    ]
    guard_reason: str
    final_answer: str

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

    # 查询澄清状态
    need_clarification: bool
    clarification_type: str | None
    clarification_question: str | None
    clarification_options: list[str]

    # 结构化执行结果
    success: bool
    error_type: str | None
    error_message: str | None
    error_node: str | None
    recoverable: bool
    suggested_action: str | None

    # 结构化非阻断告警
    warning_type: str | None
    warning_message: str | None
    recall_column_warning: str
    recall_metric_warning: str
    recall_value_warning: str
    dependency_warnings: list[str]
    missing_values: list[str]
    matched_values: list[str]

    # SQL 执行计划观测
    sql_explain: list[dict]
    risk_flags: list[str]
    index_suggestions: list[str]
    sql_rewrite_suggestions: list[str]
    governance_warnings: list[str]

    #结果
    result: list[dict]
