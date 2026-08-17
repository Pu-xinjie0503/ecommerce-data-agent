"""从 Trace 节点构建请求级可复算指标。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

RECALL_NODES = ("recall_column", "recall_metric", "recall_value")


def build_trace_metrics(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """汇总节点状态、缓存增量和三路召回并行收益。"""

    return {
        "step_count": len(steps),
        "failed_step_count": sum(step.get("status") == "failed" for step in steps),
        "cache_totals": _aggregate_cache_totals(steps),
        "recall_parallel": _build_recall_parallel_metrics(steps),
    }


def _aggregate_cache_totals(steps: list[dict[str, Any]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for step in steps:
        output = step.get("output_summary") or {}
        cache_stats = output.get("cache_stats") or {}
        if not isinstance(cache_stats, dict):
            continue
        for key, value in cache_stats.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or key.endswith(("_size", "_hit_rate"))
            ):
                continue
            totals[key] = totals.get(key, 0) + int(value)
    return dict(sorted(totals.items()))


def _build_recall_parallel_metrics(steps: list[dict[str, Any]]) -> dict[str, Any]:
    by_name = {step.get("name"): step for step in steps}
    recall_steps = [by_name.get(name) for name in RECALL_NODES]
    if not all(recall_steps):
        return {
            "available": False,
            "required_nodes": list(RECALL_NODES),
            "missing_nodes": [
                name for name, step in zip(RECALL_NODES, recall_steps) if step is None
            ],
        }

    completed_steps = [step for step in recall_steps if step is not None]
    if any(
        step.get("duration_ms") is None
        or not step.get("start_time")
        or not step.get("end_time")
        for step in completed_steps
    ):
        return {
            "available": False,
            "required_nodes": list(RECALL_NODES),
            "missing_nodes": [],
            "reason": "召回节点缺少时间戳或耗时",
        }

    starts = [_parse_time(step["start_time"]) for step in completed_steps]
    ends = [_parse_time(step["end_time"]) for step in completed_steps]
    sequential_ms = sum(float(step["duration_ms"]) for step in completed_steps)
    wall_ms = (max(ends) - min(starts)).total_seconds() * 1000
    saved_ms = max(0.0, sequential_ms - wall_ms)
    saved_ratio = saved_ms / sequential_ms * 100 if sequential_ms else 0.0

    return {
        "available": True,
        "required_nodes": list(RECALL_NODES),
        "sequential_estimated_ms": round(sequential_ms, 2),
        "parallel_wall_ms": round(wall_ms, 2),
        "estimated_saved_ms": round(saved_ms, 2),
        "estimated_saved_ratio": round(saved_ratio, 2),
    }


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)

