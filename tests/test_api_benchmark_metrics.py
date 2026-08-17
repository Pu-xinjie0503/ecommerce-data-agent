"""API 压测指标与运行对比测试。"""

from __future__ import annotations

from argparse import Namespace

import pytest

from eval.benchmark_api import RequestResult, build_report
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
