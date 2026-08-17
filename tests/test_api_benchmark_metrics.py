"""API 压测指标与运行对比测试。"""

from __future__ import annotations

from argparse import Namespace

import pytest

import eval.benchmark_api as benchmark_api
from eval.benchmark_api import RequestResult, build_report, load_cases
from eval.compare_runs import compare_benchmark_reports
from eval.experiment import ExperimentCompatibilityError


def test_build_report_records_throughput_warmup_and_raw_requests():
    """压测报告必须保留可反向复算吞吐量和错误率的原始依据。"""

    args = _args()
    results = [
        _result(1, 100.0, "normal_success"),
        _result(2, 300.0, "technical_error", technical_error_type="llm_timeout"),
    ]

    report = build_report(args, results, total_duration_seconds=2.0)

    assert report["run_id"] == "bench-test"
    assert report["warmup_requests"] == 3
    assert report["cases_sha256"] == "cases-hash"
    assert report["summary"]["throughput_rps"] == 1.0
    assert report["summary"]["technical_error_rate"] == 50.0
    assert report["summary"]["p95_latency_ms"] == 290.0
    assert len(report["results"]) == 2


def test_load_cases_preserves_expected_branch():
    """固定压测集的预期分支必须进入每个计划请求。"""

    cases = load_cases("eval/benchmark_cases.yaml", "mixed-core8")

    assert cases[0]["branch"] == "normal"
    assert cases[5]["branch"] == "grounding_error"


def test_build_report_marks_unexpected_business_outcome_as_branch_mismatch():
    """正常 Case 被 Grounding 拦截时不能计入分支命中。"""

    args = _args()
    success = _result(1, 100.0, "normal_success")
    success.expected_branch = "normal"
    success.actual_branch = "normal"
    success.branch_matched = True
    unexpected = _result(2, 200.0, "expected_business_outcome")
    unexpected.business_outcome_type = "value_grounding_failed"
    unexpected.expected_branch = "normal"
    unexpected.actual_branch = "grounding_error"
    unexpected.branch_matched = False

    report = build_report(args, [success, unexpected], total_duration_seconds=1.0)

    assert report["summary"]["branch_matched_count"] == 1
    assert report["summary"]["branch_mismatch_count"] == 1
    assert report["summary"]["branch_accuracy"] == 50.0
    assert report["results"][1]["expected_branch"] == "normal"
    assert report["results"][1]["actual_branch"] == "grounding_error"
    assert report["results"][1]["branch_matched"] is False


@pytest.mark.parametrize(
    ("outcome_category", "business_outcome_type", "expected"),
    [
        ("normal_success", None, "normal"),
        ("technical_error", None, "technical_error"),
        ("expected_business_outcome", "value_grounding_failed", "grounding_error"),
        (
            "expected_business_outcome",
            "partial_value_grounding_failed",
            "grounding_warning",
        ),
        ("expected_business_outcome", "need_clarification", "clarification"),
        ("expected_business_outcome", "unsafe_query", "unsafe"),
    ],
)
def test_resolve_actual_branch_uses_case_branch_vocabulary(
    outcome_category: str,
    business_outcome_type: str | None,
    expected: str,
):
    """实际响应应转换为与 Case branch 相同的稳定分类。"""

    assert (
        benchmark_api.resolve_actual_branch(outcome_category, business_outcome_type)
        == expected
    )


def test_compare_benchmark_reports_calculates_latency_improvement():
    """同条件运行可计算 P95 降幅和吞吐提升。"""

    baseline = _comparable_report(p95=1000.0, throughput=2.0)
    candidate = _comparable_report(p95=750.0, throughput=2.5)

    comparison = compare_benchmark_reports(baseline, candidate)

    assert comparison["p95_latency_reduction_pct"] == 25.0
    assert comparison["throughput_improvement_pct"] == 25.0


@pytest.mark.parametrize("field", ["url", "concurrency", "requests", "cases_sha256"])
def test_compare_benchmark_reports_rejects_incompatible_runs(field: str):
    """请求条件不同的压测报告不能用于宣称性能提升。"""

    baseline = _comparable_report(p95=1000.0, throughput=2.0)
    candidate = _comparable_report(p95=750.0, throughput=2.5)
    candidate[field] = "different"

    with pytest.raises(ExperimentCompatibilityError, match=field):
        compare_benchmark_reports(baseline, candidate)


def _args() -> Namespace:
    return Namespace(
        url="http://127.0.0.1:8000/api/query",
        concurrency=10,
        requests=50,
        cases="eval/benchmark_cases.yaml",
        case_set="fixed",
        timeout=120.0,
        run_id="bench-test",
        warmup_requests=3,
        cases_sha256="cases-hash",
    )


def _result(
    index: int,
    duration_ms: float,
    outcome_category: str,
    *,
    technical_error_type: str | None = None,
) -> RequestResult:
    return RequestResult(
        request_index=index,
        case_id=f"case-{index}",
        query="统计销售额",
        duration_ms=duration_ms,
        success=outcome_category == "normal_success",
        failed=outcome_category == "technical_error",
        http_status=200,
        final_event_type="final",
        error_type=technical_error_type,
        warning_type=None,
        need_clarification=False,
        request_id=f"request-{index}",
        trace_path=f"trace-{index}.json",
        error_message=None,
        event_count=1,
        outcome_category=outcome_category,
        business_outcome_type=None,
        technical_error_type=technical_error_type,
    )


def _comparable_report(*, p95: float, throughput: float) -> dict:
    return {
        "run_id": "run-a",
        "url": "http://127.0.0.1:8000/api/query",
        "concurrency": 10,
        "requests": 50,
        "warmup_requests": 5,
        "cases_sha256": "cases-hash",
        "summary": {
            "p95_latency_ms": p95,
            "throughput_rps": throughput,
            "technical_error_rate": 0.0,
        },
    }
