"""Trace 请求级指标测试。"""

from app.observability.trace_manager import TraceManager
from app.observability.trace_metrics import build_trace_metrics


def test_build_trace_metrics_calculates_parallel_recall_savings():
    """三路召回应同时保存串行估算和并行墙钟证据。"""

    metrics = build_trace_metrics(
        [
            _step(
                "recall_column",
                "2026-08-17T10:00:00.000",
                "2026-08-17T10:00:01.000",
                1000,
                {"embedding_cache_hit": 2, "embedding_cache_miss": 1},
            ),
            _step(
                "recall_metric",
                "2026-08-17T10:00:00.100",
                "2026-08-17T10:00:00.900",
                800,
                {"embedding_cache_hit": 1, "embedding_cache_miss": 1},
            ),
            _step(
                "recall_value",
                "2026-08-17T10:00:00.200",
                "2026-08-17T10:00:00.700",
                500,
                {"keyword_expand_cache_bypass": 1},
            ),
        ]
    )

    assert metrics["step_count"] == 3
    assert metrics["failed_step_count"] == 0
    assert metrics["cache_totals"]["embedding_cache_hit"] == 3
    assert metrics["cache_totals"]["embedding_cache_miss"] == 2
    assert metrics["recall_parallel"] == {
        "available": True,
        "required_nodes": ["recall_column", "recall_metric", "recall_value"],
        "sequential_estimated_ms": 2300.0,
        "parallel_wall_ms": 1000.0,
        "estimated_saved_ms": 1300.0,
        "estimated_saved_ratio": 56.52,
    }


def test_trace_manager_persists_experiment_and_metrics():
    """请求 Trace 必须关联运行 ID、Case 与数据集哈希。"""

    manager = TraceManager(
        request_id="eval-case-001",
        query="统计华北销售额",
        experiment={
            "run_id": "run-001",
            "case_id": "case-001",
            "intent_id": "sales-by-region",
            "dataset_sha256": "hash",
            "cache_mode": "cold",
        },
    )
    manager.record["steps"].append(
        _step("guard_query", "2026-08-17T10:00:00.000", "2026-08-17T10:00:00.001", 1)
    )

    manager.finish("success")

    assert manager.record["experiment"]["run_id"] == "run-001"
    assert manager.record["metrics"]["step_count"] == 1
    assert manager.record["metrics"]["recall_parallel"]["available"] is False


def test_build_trace_metrics_records_grounding_validation_shortcut():
    """Grounding 校验和 LLM 扩展跳过状态应提升为请求级指标。"""

    step = _step(
        "recall_value",
        "2026-08-17T10:00:00.000",
        "2026-08-17T10:00:00.001",
        1,
    )
    step["output_summary"].update(
        {
            "grounding_validation_skipped": True,
            "value_keyword_expansion_skipped": True,
            "value_fuzzy_search_skipped": True,
            "grounding_skip_reason": "no_explicit_filter_values",
            "value_exact_search_metrics": {
                "explicit_candidate_count": 0,
                "implicit_candidate_count": 3,
                "explicit_call_count": 0,
                "implicit_call_count": 1,
                "total_call_count": 1,
            },
        }
    )

    metrics = build_trace_metrics([step])

    assert metrics["grounding"] == {
        "validation_skipped": True,
        "skip_reason": "no_explicit_filter_values",
        "has_explicit_filter_values": False,
        "value_keyword_expansion_skipped": True,
        "value_fuzzy_search_skipped": True,
        "exact_search": {
            "explicit_candidate_count": 0,
            "implicit_candidate_count": 3,
            "explicit_call_count": 0,
            "implicit_call_count": 1,
            "total_call_count": 1,
        },
    }


def _step(name, start_time, end_time, duration_ms, cache_stats=None):
    return {
        "name": name,
        "status": "success",
        "start_time": start_time,
        "end_time": end_time,
        "duration_ms": duration_ms,
        "input_summary": {},
        "output_summary": {"cache_stats": cache_stats or {}},
        "error_message": None,
        "error_type": None,
        "error_node": None,
        "recoverable": None,
        "suggested_action": None,
    }
