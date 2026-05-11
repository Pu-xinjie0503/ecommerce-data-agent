"""Agent 结构化 Trace 数据结构定义。"""

from typing import Any, Literal, TypedDict

TraceStepStatus = Literal["running", "success", "failed"]
TraceStatus = Literal["running", "success", "failed"]


class TraceStep(TypedDict):
    name: str
    status: TraceStepStatus
    start_time: str
    end_time: str | None
    duration_ms: float | None
    input_summary: dict[str, Any]
    output_summary: dict[str, Any]
    error_message: str | None


class TraceRecord(TypedDict):
    request_id: str
    query: str
    status: TraceStatus
    start_time: str
    end_time: str | None
    duration_ms: float | None
    trace_path: str | None
    steps: list[TraceStep]
