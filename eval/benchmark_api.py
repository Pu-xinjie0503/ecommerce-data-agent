"""/api/query SSE 接口压测脚本。"""

import argparse
import asyncio
import json
import statistics
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import yaml


DEFAULT_URL = "http://127.0.0.1:8000/api/query"
REPORT_DATE = "20260601"
NORMAL_CASES = [
    {"id": "normal_001", "query": "华北地区的总销售额"},
    {"id": "normal_002", "query": "统计美的品牌的销售额"},
    {"id": "normal_003", "query": "按大区统计销售额"},
    {"id": "normal_004", "query": "统计 2025 年第一季度的销售额"},
]
MIXED_CORE8_CASES = [
    *NORMAL_CASES,
    {"id": "core_005", "query": "统计火星地区的销售额"},
    {"id": "core_006", "query": "对比华北和火星地区的销售额"},
    {"id": "core_007", "query": "哪个品类卖得最好"},
    {"id": "core_008", "query": "帮我执行 DROP TABLE fact_order"},
]

TECHNICAL_ERROR_TYPES = {
    "http_error",
    "sse_parse_error",
    "api_request_timeout",
    "api_internal_error",
    "llm_timeout",
    "llm_unavailable",
    "llm_rate_limited",
    "llm_quota_exceeded",
    "llm_auth_failed",
    "embedding_timeout",
    "embedding_service_error",
    "qdrant_timeout",
    "qdrant_service_error",
    "es_timeout",
    "es_service_error",
    "mysql_timeout",
    "mysql_execution_error",
}
EXPECTED_BUSINESS_ERROR_TYPES = {
    "unsafe_query",
    "value_grounding_failed",
}
EXPECTED_BUSINESS_WARNING_TYPES = {
    "partial_value_grounding_failed",
}


@dataclass
class RequestResult:
    request_index: int
    case_id: str
    query: str
    duration_ms: float
    success: bool
    failed: bool
    http_status: int | None
    final_event_type: str | None
    error_type: str | None
    warning_type: str | None
    need_clarification: bool | None
    request_id: str | None
    trace_path: str | None
    error_message: str | None
    event_count: int
    outcome_category: str
    business_outcome_type: str | None
    technical_error_type: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="压测 /api/query SSE 接口")
    parser.add_argument("--url", default=DEFAULT_URL, help="API 地址")
    parser.add_argument("--concurrency", type=int, default=1, help="并发数")
    parser.add_argument("--requests", type=int, default=8, help="总请求数")
    parser.add_argument("--cases", default=None, help="可选 YAML case 文件；传入后覆盖 --case-set")
    parser.add_argument(
        "--case-set",
        choices=["normal-only", "mixed-core8"],
        default="mixed-core8",
        help="内置 case 分组：normal-only 只测正常链路，mixed-core8 测核心混合分支",
    )
    parser.add_argument("--output-md", default=None, help="Markdown 报告输出路径")
    parser.add_argument("--output-json", default=None, help="JSON 报告输出路径")
    parser.add_argument("--timeout", type=float, default=120.0, help="单请求超时时间，秒")
    return parser.parse_args()


def load_cases(path: str | None, case_set: str) -> list[dict[str, Any]]:
    if not path:
        return NORMAL_CASES if case_set == "normal-only" else MIXED_CORE8_CASES

    with Path(path).open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    cases = data.get("cases", data) if isinstance(data, dict) else data
    if not isinstance(cases, list):
        raise ValueError("cases 文件格式错误：需要 list 或包含 cases 的 dict")

    loaded: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        query = case.get("query") if isinstance(case, dict) else None
        if not query:
            continue
        loaded.append(
            {
                "id": case.get("id", f"case_{index:03d}"),
                "query": query,
            }
        )
    if not loaded:
        raise ValueError("cases 文件中没有可用 query")
    return loaded


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    rank = (len(sorted_values) - 1) * p
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = rank - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def classify_outcome(
    *,
    final_event: dict[str, Any] | None,
    http_status: int | None,
    transport_error_type: str | None,
) -> tuple[str, str | None, str | None]:
    """把 API 结果区分为正常成功、预期业务结果和技术错误。"""

    if transport_error_type:
        return "technical_error", None, transport_error_type

    if http_status is not None and http_status >= 400:
        return "technical_error", None, "http_error"

    if final_event is None:
        return "technical_error", None, "api_internal_error"

    error_type = final_event.get("error_type")
    warning_type = final_event.get("warning_type")
    if final_event.get("need_clarification"):
        return "expected_business_outcome", "need_clarification", None
    if error_type in EXPECTED_BUSINESS_ERROR_TYPES:
        return "expected_business_outcome", error_type, None
    if warning_type in EXPECTED_BUSINESS_WARNING_TYPES:
        return "expected_business_outcome", warning_type, None
    if error_type in TECHNICAL_ERROR_TYPES:
        return "technical_error", None, error_type
    if error_type:
        return "technical_error", None, error_type
    return "normal_success", None, None


async def request_once(
    client: httpx.AsyncClient,
    *,
    url: str,
    case: dict[str, Any],
    request_index: int,
    timeout: float,
) -> RequestResult:
    started = time.perf_counter()
    events: list[dict[str, Any]] = []
    final_event: dict[str, Any] | None = None
    http_status: int | None = None
    error_message: str | None = None
    transport_error_type: str | None = None

    try:
        async with client.stream(
            "POST",
            url,
            json={"query": case["query"]},
            headers={"Accept": "text/event-stream"},
            timeout=timeout,
        ) as response:
            http_status = response.status_code
            if response.status_code >= 400:
                transport_error_type = "http_error"
                error_message = f"HTTP {response.status_code}"
                await response.aread()
            else:
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line.removeprefix("data:").strip()
                    if not payload:
                        continue
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError as exc:
                        transport_error_type = "sse_parse_error"
                        error_message = f"SSE JSON 解析失败: {exc}"
                        break
                    events.append(event)
                    if event.get("type") == "final":
                        final_event = event
                        break
    except httpx.TimeoutException as exc:
        transport_error_type = "api_request_timeout"
        error_message = f"api_request_timeout: {exc}"
    except Exception as exc:
        transport_error_type = "api_internal_error"
        error_message = str(exc)

    duration_ms = (time.perf_counter() - started) * 1000
    final_event_type = final_event.get("type") if final_event else None
    outcome_category, business_outcome_type, technical_error_type = classify_outcome(
        final_event=final_event,
        http_status=http_status,
        transport_error_type=transport_error_type,
    )
    success = outcome_category == "normal_success"
    failed = outcome_category == "technical_error"

    return RequestResult(
        request_index=request_index,
        case_id=str(case.get("id", f"case_{request_index:03d}")),
        query=case["query"],
        duration_ms=round(duration_ms, 2),
        success=success,
        failed=failed,
        http_status=http_status,
        final_event_type=final_event_type,
        error_type=final_event.get("error_type") if final_event else technical_error_type,
        warning_type=final_event.get("warning_type") if final_event else None,
        need_clarification=final_event.get("need_clarification") if final_event else None,
        request_id=final_event.get("request_id") if final_event else None,
        trace_path=final_event.get("trace_path") if final_event else None,
        error_message=final_event.get("error_message") if final_event else error_message,
        event_count=len(events),
        outcome_category=outcome_category,
        business_outcome_type=business_outcome_type,
        technical_error_type=technical_error_type,
    )


async def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    cases = load_cases(args.cases, args.case_set)
    planned_cases = [cases[index % len(cases)] for index in range(args.requests)]
    semaphore = asyncio.Semaphore(args.concurrency)

    async with httpx.AsyncClient() as client:
        async def run_limited(index: int, case: dict[str, Any]) -> RequestResult:
            async with semaphore:
                return await request_once(
                    client,
                    url=args.url,
                    case=case,
                    request_index=index,
                    timeout=args.timeout,
                )

        started = time.perf_counter()
        results = await asyncio.gather(
            *(run_limited(index + 1, case) for index, case in enumerate(planned_cases))
        )
        total_duration_seconds = time.perf_counter() - started

    return build_report(args, results, total_duration_seconds)


def build_report(args: argparse.Namespace, results: list[RequestResult], total_duration_seconds: float) -> dict[str, Any]:
    durations = [item.duration_ms for item in results]
    normal_success_count = sum(1 for item in results if item.outcome_category == "normal_success")
    expected_business_outcome_count = sum(
        1 for item in results if item.outcome_category == "expected_business_outcome"
    )
    technical_error_count = sum(1 for item in results if item.outcome_category == "technical_error")
    business_outcomes = Counter(
        item.business_outcome_type or "unknown"
        for item in results
        if item.outcome_category == "expected_business_outcome"
    )
    technical_errors = Counter(
        item.technical_error_type or "unknown"
        for item in results
        if item.outcome_category == "technical_error"
    )
    warning_types = Counter(item.warning_type for item in results if item.warning_type)
    slowest = sorted(results, key=lambda item: item.duration_ms, reverse=True)[:10]

    summary = {
        "total_requests": len(results),
        "normal_success_count": normal_success_count,
        "expected_business_outcome_count": expected_business_outcome_count,
        "technical_error_count": technical_error_count,
        "technical_error_rate": round(technical_error_count / len(results) * 100, 2) if results else 0.0,
        "business_outcome_distribution": dict(business_outcomes),
        "technical_error_type_distribution": dict(technical_errors),
        "warning_type_distribution": dict(warning_types),
        "avg_latency_ms": round(statistics.mean(durations), 2) if durations else 0.0,
        "p50_latency_ms": round(percentile(durations, 0.50), 2),
        "p90_latency_ms": round(percentile(durations, 0.90), 2),
        "p95_latency_ms": round(percentile(durations, 0.95), 2),
        "p99_latency_ms": round(percentile(durations, 0.99), 2),
        "max_latency_ms": round(max(durations), 2) if durations else 0.0,
        "duration_seconds": round(total_duration_seconds, 2),
    }

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "url": args.url,
        "case_set": args.case_set,
        "concurrency": args.concurrency,
        "requests": args.requests,
        "timeout": args.timeout,
        "cases_file": args.cases,
        "summary": summary,
        "results": [asdict(item) for item in results],
        "slowest_top_10": [asdict(item) for item in slowest],
    }


def default_output_paths() -> tuple[Path, Path]:
    return (
        Path(f"eval/api_benchmark_deepseek_{REPORT_DATE}.md"),
        Path(f"eval/reports/api_benchmark_deepseek_{REPORT_DATE}.json"),
    )


def write_json(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = report["summary"]
    lines = [
        "# API Benchmark 报告",
        "",
        f"生成时间：{report['generated_at']}",
        f"URL：{report['url']}",
        f"case_set：{report['case_set']}",
        f"并发数：{report['concurrency']}",
        f"请求数：{report['requests']}",
        "",
        "## 总体统计",
        "",
        "| total_requests | normal_success_count | expected_business_outcome_count | technical_error_count | technical_error_rate | avg_latency_ms | p50 | p90 | p95 | p99 | max |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        (
            f"| {summary['total_requests']} | {summary['normal_success_count']} | "
            f"{summary['expected_business_outcome_count']} | {summary['technical_error_count']} | "
            f"{summary['technical_error_rate']}% | {summary['avg_latency_ms']} | "
            f"{summary['p50_latency_ms']} | {summary['p90_latency_ms']} | {summary['p95_latency_ms']} | "
            f"{summary['p99_latency_ms']} | {summary['max_latency_ms']} |"
        ),
        "",
        "## 预期业务分支分布",
        "",
    ]
    for outcome_type, count in summary["business_outcome_distribution"].items():
        lines.append(f"- {outcome_type}: {count}")
    lines.extend(["", "## 技术错误分布", ""])
    if summary["technical_error_type_distribution"]:
        for error_type, count in summary["technical_error_type_distribution"].items():
            lines.append(f"- {error_type}: {count}")
    else:
        lines.append("- none: 0")
    lines.extend(["", "## warning_type 分布", ""])
    if summary["warning_type_distribution"]:
        for warning_type, count in summary["warning_type_distribution"].items():
            lines.append(f"- {warning_type}: {count}")
    else:
        lines.append("- none: 0")
    lines.extend(
        [
            "",
            "## 最慢 Top 10 请求",
            "",
            "| rank | query | duration_ms | outcome_category | business_outcome_type | technical_error_type | warning_type | trace_path |",
            "|---:|---|---:|---|---|---|---|---|",
        ]
    )
    for rank, item in enumerate(report["slowest_top_10"], start=1):
        lines.append(
            f"| {rank} | {item['query']} | {item['duration_ms']} | {item['outcome_category']} | "
            f"{item.get('business_outcome_type') or ''} | {item.get('technical_error_type') or ''} | "
            f"{item.get('warning_type') or ''} | {item.get('trace_path') or ''} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def print_summary(report: dict[str, Any]) -> None:
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print("\n最慢 Top 10 请求：")
    for item in report["slowest_top_10"]:
        print(
            f"- #{item['request_index']} {item['duration_ms']}ms "
            f"outcome={item['outcome_category']} business={item.get('business_outcome_type')} "
            f"technical={item.get('technical_error_type')} warning={item.get('warning_type')} "
            f"query={item['query']}"
        )


async def main() -> None:
    args = parse_args()
    if args.concurrency <= 0 or args.requests <= 0:
        raise ValueError("--concurrency 和 --requests 必须大于 0")

    report = await run_benchmark(args)
    default_md, default_json = default_output_paths()
    output_md = Path(args.output_md) if args.output_md else default_md
    output_json = Path(args.output_json) if args.output_json else default_json
    write_markdown(output_md, report)
    write_json(output_json, report)
    print_summary(report)
    print(f"\nMarkdown 报告：{output_md}")
    print(f"JSON 报告：{output_json}")


if __name__ == "__main__":
    asyncio.run(main())
