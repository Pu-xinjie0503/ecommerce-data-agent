"""评测指标聚合测试。"""

from eval.metrics import build_eval_metrics, percentile


def test_build_eval_metrics_reports_query_and_intent_accuracy():
    """Query 准确率与意图宏平均应分别计算。"""

    cases = [
        {
            "intent_id": "sales_by_region",
            "category": "multi_join",
            "passed": True,
            "execution_matched": True,
            "sql_generated": True,
            "sql_executed": True,
            "duration_ms": 100,
        },
        {
            "intent_id": "sales_by_region",
            "category": "multi_join",
            "passed": False,
            "execution_matched": False,
            "sql_generated": True,
            "sql_executed": True,
            "duration_ms": 200,
        },
        {
            "intent_id": "top_brand",
            "category": "ranking",
            "passed": True,
            "execution_matched": True,
            "sql_generated": True,
            "sql_executed": True,
            "duration_ms": 300,
        },
    ]

    metrics = build_eval_metrics(cases)

    assert metrics["query_pass_rate"] == 66.67
    assert metrics["execution_accuracy"] == 66.67
    assert metrics["intent_macro_accuracy"] == 75.0
    assert metrics["sql_generation_rate"] == 100.0
    assert metrics["sql_execution_rate"] == 100.0
    assert metrics["latency_ms"] == {"avg": 200.0, "p50": 200.0, "p90": 280.0, "p95": 290.0}
    assert metrics["by_category"]["multi_join"]["pass_rate"] == 50.0


def test_build_eval_metrics_handles_empty_cases():
    """空评测集不应触发除零错误。"""

    metrics = build_eval_metrics([])

    assert metrics["total"] == 0
    assert metrics["query_pass_rate"] == 0.0
    assert metrics["intent_macro_accuracy"] == 0.0
    assert metrics["latency_ms"] == {"avg": 0.0, "p50": 0.0, "p90": 0.0, "p95": 0.0}


def test_percentile_uses_linear_interpolation():
    """分位数应使用线性插值，确保与既有报告口径一致。"""

    assert percentile([100, 200, 300], 0.9) == 280.0

