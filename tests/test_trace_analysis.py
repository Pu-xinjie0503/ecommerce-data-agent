"""Trace 离线分析测试。"""

from eval.analyze_trace_latency import (
    analyze_parallel_recall,
    build_cache_stats,
    collect_cache_stats,
    extract_parallel_recall,
    new_cache_accumulator,
)


def test_analyze_parallel_recall_reports_saved_ratio():
    """旧 Trace 复算也必须输出与新 Trace 相同的节省比例。"""

    result = analyze_parallel_recall(_recall_steps())

    assert result["duration_sum_ms"] == 2300.0
    assert result["wall_time_ms"] == 1000.0
    assert result["estimated_saved_ms"] == 1300.0
    assert result["estimated_saved_ratio"] == 56.52


def test_extract_parallel_recall_prefers_root_metrics():
    """新 Trace 应直接使用根节点指标并标记来源。"""

    trace = {
        "metrics": {
            "recall_parallel": {
                "available": True,
                "sequential_estimated_ms": 2300.0,
                "parallel_wall_ms": 1000.0,
                "estimated_saved_ms": 1300.0,
                "estimated_saved_ratio": 56.52,
            }
        },
        "steps": _recall_steps(),
    }

    result = extract_parallel_recall(trace)

    assert result["source"] == "trace.metrics"
    assert result["estimated_saved_ratio"] == 56.52


def test_collect_cache_stats_ignores_derived_fields_and_keeps_bypass():
    """派生比例不能参与累加，缓存大小取最大值。"""

    accumulator = new_cache_accumulator()
    steps = [
        {
            "output_summary": {
                "cache_stats": {
                    "embedding_cache_enabled": True,
                    "embedding_cache_hit": 3,
                    "embedding_cache_miss": 1,
                    "embedding_cache_bypass": 2,
                    "embedding_cache_size": 5,
                    "embedding_cache_hit_rate": 75.0,
                }
            }
        },
        {
            "output_summary": {
                "cache_stats": {
                    "embedding_cache_hit": 1,
                    "embedding_cache_size": 7,
                }
            }
        },
    ]

    collect_cache_stats(steps, accumulator)
    stats = build_cache_stats(accumulator)

    assert stats["embedding"]["embedding_cache_hit"] == 4
    assert stats["embedding"]["embedding_cache_miss"] == 1
    assert stats["embedding"]["embedding_cache_bypass"] == 2
    assert stats["embedding"]["embedding_cache_size"] == 7
    assert stats["embedding"]["embedding_cache_hit_rate"] == 80.0


def _recall_steps():
    return [
        _step("recall_column", "10:00:00.000", "10:00:01.000", 1000),
        _step("recall_metric", "10:00:00.100", "10:00:00.900", 800),
        _step("recall_value", "10:00:00.200", "10:00:00.700", 500),
    ]


def _step(name, start, end, duration):
    return {
        "name": name,
        "status": "success",
        "start_time": f"2026-08-17T{start}",
        "end_time": f"2026-08-17T{end}",
        "duration_ms": duration,
        "output_summary": {},
    }

