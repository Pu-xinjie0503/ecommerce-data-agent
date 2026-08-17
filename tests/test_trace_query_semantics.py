from app.agent.query_semantics import parse_query_semantics
from app.observability.trace_manager import summarize_payload


def test_trace_summary_contains_query_semantics() -> None:
    """Trace 应保留可复核的查询语义结果。"""

    semantics = parse_query_semantics("订单数最多的三个品牌是什么")
    summary = summarize_payload(
        {
            "query": "订单数最多的三个品牌是什么",
            "query_semantics": semantics,
        }
    )
    assert summary["query_semantics"]["group_by_columns"] == ["dim_product.brand"]
    assert summary["query_semantics"]["metric_terms"] == ["order_count"]
    assert summary["query_semantics"]["order_direction"] == "desc"
    assert summary["query_semantics"]["limit"] == 3


def test_trace_summary_contains_grounding_validation_skip_reason() -> None:
    """无显式过滤时应记录校验和 LLM 扩展的跳过状态。"""

    summary = summarize_payload(
        {
            "retrieved_value_infos": [],
            "grounding_validation_skipped": True,
            "value_keyword_expansion_skipped": True,
            "value_fuzzy_search_skipped": True,
            "grounding_skip_reason": "no_explicit_filter_values",
            "value_exact_search_metrics": {"total_call_count": 1},
        }
    )
    assert summary["grounding_validation_skipped"] is True
    assert summary["value_keyword_expansion_skipped"] is True
    assert summary["value_fuzzy_search_skipped"] is True
    assert summary["grounding_skip_reason"] == "no_explicit_filter_values"
    assert summary["value_exact_search_metrics"] == {"total_call_count": 1}
