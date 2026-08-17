from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

RECALL_STEP_NAMES = ("recall_column", "recall_metric", "recall_value")
RECALL_STEP_NAMES_BY_TYPE = ("column", "metric", "value")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    args = parse_args()
    report_path = resolve_path(args.report)
    report = read_json(report_path)
    cases = report.get("cases") or []

    analyzed_cases = []
    step_durations: dict[str, list[float]] = defaultdict(list)
    step_errors: Counter[str] = Counter()
    risk_flags: Counter[str] = Counter()
    missing_traces = 0
    parallel_checks = []

    cache_accumulator = new_cache_accumulator()

    for case in cases:
        analyzed = analyze_case(case)
        analyzed_cases.append(analyzed)

        if analyzed["missing_trace"]:
            missing_traces += 1
            continue

        for step in analyzed["steps"]:
            name = step.get("name")
            duration = to_float(step.get("duration_ms"))
            if name and duration is not None:
                step_durations[name].append(duration)
                if step.get("status") == "failed":
                    step_errors[name] += 1

        collect_cache_stats(analyzed["steps"], cache_accumulator)

        for flag in analyzed["risk_flags"]:
            risk_flags[flag] += 1

        if analyzed["parallel_recall"]:
            parallel_checks.append(analyzed["parallel_recall"])

    case_durations = [
        duration
        for duration in (to_float(case.get("duration_ms")) for case in analyzed_cases)
        if duration is not None
    ]
    step_stats = build_step_stats(step_durations, step_errors)
    summary = build_summary(report, analyzed_cases, case_durations, missing_traces)
    parallel_summary = summarize_parallel_recall(parallel_checks)
    cache_stats = build_cache_stats(cache_accumulator)
    baseline = read_optional_json(resolve_path(args.baseline)) if args.baseline else None
    comparison = build_comparison(baseline, summary, step_stats, slowest_cases(analyzed_cases, args.top_n))

    output = {
        "source_report": str(report_path),
        "baseline_report": str(resolve_path(args.baseline)) if args.baseline else None,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "validation_note": "本次 cache 验收使用 DeepSeek 官方 API / deepseek-chat；由于模型变化，pass_rate 仅用于链路验收，不作为同模型严格对比。",
        "summary": summary,
        "step_stats": step_stats,
        "slowest_cases": slowest_cases(analyzed_cases, args.top_n),
        "risk_flags": dict(risk_flags),
        "parallel_recall": parallel_summary,
        "cache_stats": cache_stats,
        "comparison": comparison,
    }

    today = datetime.now().strftime("%Y%m%d")
    json_path = resolve_output_path(args.out_json, PROJECT_ROOT / "eval" / "reports" / f"performance_cache_compare_{today}.json")
    md_path = resolve_output_path(args.out_md, PROJECT_ROOT / "eval" / f"performance_cache_compare_{today}.md")

    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(output, args.top_n), encoding="utf-8")

    print(f"JSON 报告已生成：{json_path}")
    print(f"Markdown 报告已生成：{md_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="聚合 eval trace 的节点耗时，生成性能 baseline 报告。")
    parser.add_argument("--report", default="eval/reports/latest.json", help="eval 结果 JSON 路径")
    parser.add_argument("--out-json", default=None, help="输出 JSON 报告路径")
    parser.add_argument("--out-md", default=None, help="输出 Markdown 报告路径")
    parser.add_argument("--top-n", type=int, default=10, help="最慢 case 数量")
    parser.add_argument("--baseline", default="eval/reports/performance_baseline_20260528.json", help="性能对比基线 JSON 路径")
    return parser.parse_args()


def analyze_case(case: dict[str, Any]) -> dict[str, Any]:
    trace_path = case.get("trace_path")
    trace = None
    trace_file = resolve_trace_path(trace_path) if trace_path else None
    if trace_file and trace_file.exists():
        trace = read_json(trace_file)

    steps = trace.get("steps", []) if trace else []
    return {
        "id": case.get("id"),
        "query": case.get("query"),
        "passed": case.get("passed"),
        "duration_ms": case.get("duration_ms"),
        "trace_path": str(trace_file) if trace_file else trace_path,
        "missing_trace": trace is None,
        "steps": steps,
        "risk_flags": extract_risk_flags(steps),
        "parallel_recall": extract_parallel_recall(trace) if trace else None,
    }


def extract_risk_flags(steps: list[dict[str, Any]]) -> list[str]:
    flags = []
    for step in steps:
        if step.get("name") != "validate_sql":
            continue
        summary = step.get("output_summary") or {}
        raw_flags = summary.get("risk_flags") or []
        if isinstance(raw_flags, list):
            flags.extend(str(flag) for flag in raw_flags)
        elif raw_flags:
            flags.append(str(raw_flags))
    return flags


def analyze_parallel_recall(steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    recall_steps = {step.get("name"): step for step in steps if step.get("name") in RECALL_STEP_NAMES}
    if len(recall_steps) < len(RECALL_STEP_NAMES):
        return None

    intervals = []
    for name in RECALL_STEP_NAMES:
        step = recall_steps[name]
        start = parse_time(step.get("start_time"))
        end = parse_time(step.get("end_time"))
        duration = to_float(step.get("duration_ms"))
        if start is None or end is None or duration is None:
            return None
        intervals.append({"name": name, "start": start, "end": end, "duration_ms": duration})

    latest_start = max(item["start"] for item in intervals)
    earliest_end = min(item["end"] for item in intervals)
    first_start = min(item["start"] for item in intervals)
    last_end = max(item["end"] for item in intervals)
    wall_time_ms = (last_end - first_start).total_seconds() * 1000
    duration_sum_ms = sum(item["duration_ms"] for item in intervals)

    return {
        "observed": latest_start < earliest_end,
        "duration_sum_ms": round(duration_sum_ms, 2),
        "wall_time_ms": round(wall_time_ms, 2),
        "estimated_saved_ms": round(max(0.0, duration_sum_ms - wall_time_ms), 2),
        "estimated_saved_ratio": round(
            max(0.0, duration_sum_ms - wall_time_ms) / duration_sum_ms * 100,
            2,
        ) if duration_sum_ms else 0.0,
        "source": "steps",
        "steps": [
            {"name": item["name"], "duration_ms": item["duration_ms"]}
            for item in intervals
        ],
    }


def extract_parallel_recall(trace: dict[str, Any]) -> dict[str, Any] | None:
    """优先读取新 Trace 根指标，旧 Trace 则从节点时间戳复算。"""

    steps = trace.get("steps") or []
    recalculated = analyze_parallel_recall(steps)
    root_metrics = (trace.get("metrics") or {}).get("recall_parallel") or {}
    if not root_metrics.get("available"):
        return recalculated

    return {
        "observed": recalculated.get("observed") if recalculated else True,
        "duration_sum_ms": root_metrics.get("sequential_estimated_ms"),
        "wall_time_ms": root_metrics.get("parallel_wall_ms"),
        "estimated_saved_ms": root_metrics.get("estimated_saved_ms"),
        "estimated_saved_ratio": root_metrics.get("estimated_saved_ratio"),
        "source": "trace.metrics",
        "steps": recalculated.get("steps", []) if recalculated else [],
    }


def new_cache_accumulator() -> dict[str, Any]:
    return {
        "embedding": Counter(),
        "keyword_expansion": Counter(),
    }


def collect_cache_stats(steps: list[dict[str, Any]], accumulator: dict[str, Any]) -> None:
    for step in steps:
        output_summary = step.get("output_summary") or {}
        cache_stats = output_summary.get("cache_stats") or {}
        if not isinstance(cache_stats, dict):
            continue
        for key, value in cache_stats.items():
            if isinstance(value, bool) or key.endswith("_hit_rate") or key.endswith("_enabled"):
                continue
            number = int(to_float(value) or 0)
            if key.startswith("embedding_cache_"):
                if key.endswith("_size"):
                    accumulator["embedding"][key] = max(accumulator["embedding"].get(key, 0), number)
                else:
                    accumulator["embedding"][key] += number
            elif key.startswith("keyword_expand_cache_"):
                if key.endswith("_size"):
                    accumulator["keyword_expansion"][key] = max(
                        accumulator["keyword_expansion"].get(key, 0),
                        number,
                    )
                else:
                    accumulator["keyword_expansion"][key] += number


def build_cache_stats(accumulator: dict[str, Any]) -> dict[str, Any]:
    embedding = accumulator["embedding"]
    keyword = accumulator["keyword_expansion"]
    embedding_hit = embedding.get("embedding_cache_hit", 0)
    embedding_miss = embedding.get("embedding_cache_miss", 0)
    keyword_hit = sum(keyword.get(f"keyword_expand_cache_hit_{name}", 0) for name in RECALL_STEP_NAMES_BY_TYPE)
    keyword_miss = sum(keyword.get(f"keyword_expand_cache_miss_{name}", 0) for name in RECALL_STEP_NAMES_BY_TYPE)

    return {
        "embedding": {
            "embedding_cache_hit": embedding_hit,
            "embedding_cache_miss": embedding_miss,
            "embedding_cache_bypass": embedding.get("embedding_cache_bypass", 0),
            "embedding_cache_size": embedding.get("embedding_cache_size", 0),
            "embedding_cache_hit_rate": hit_rate(embedding_hit, embedding_miss),
        },
        "keyword_expansion": {
            recall_type: {
                "hit": keyword.get(f"keyword_expand_cache_hit_{recall_type}", 0),
                "miss": keyword.get(f"keyword_expand_cache_miss_{recall_type}", 0),
                "hit_rate": hit_rate(
                    keyword.get(f"keyword_expand_cache_hit_{recall_type}", 0),
                    keyword.get(f"keyword_expand_cache_miss_{recall_type}", 0),
                ),
            }
            for recall_type in RECALL_STEP_NAMES_BY_TYPE
        },
        "overall": {
            "embedding_cache_hit_rate": hit_rate(embedding_hit, embedding_miss),
            "keyword_expand_cache_hit": keyword_hit,
            "keyword_expand_cache_miss": keyword_miss,
            "keyword_expand_cache_bypass": keyword.get("keyword_expand_cache_bypass", 0),
            "keyword_expand_cache_hit_rate": hit_rate(keyword_hit, keyword_miss),
        },
    }


def hit_rate(hit: int, miss: int) -> float:
    total = hit + miss
    return round(hit / total * 100, 2) if total else 0.0


def read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return read_json(path)


def build_comparison(
    baseline: dict[str, Any] | None,
    summary: dict[str, Any],
    step_stats: list[dict[str, Any]],
    current_slowest_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    if not baseline:
        return {"available": False}

    baseline_summary = baseline.get("summary") or {}
    baseline_steps = {row.get("name"): row for row in baseline.get("step_stats") or []}
    current_steps = {row.get("name"): row for row in step_stats}
    focused_nodes = ["recall_column", "recall_metric", "recall_value", "generate_sql"]

    return {
        "available": True,
        "baseline_total_avg_ms": baseline_summary.get("avg_duration_ms"),
        "current_total_avg_ms": summary.get("avg_duration_ms"),
        "total_avg_delta_ms": delta(summary.get("avg_duration_ms"), baseline_summary.get("avg_duration_ms")),
        "baseline_p95_ms": baseline_summary.get("p95_duration_ms"),
        "current_p95_ms": summary.get("p95_duration_ms"),
        "p95_delta_ms": delta(summary.get("p95_duration_ms"), baseline_summary.get("p95_duration_ms")),
        "baseline_pass_rate": baseline_summary.get("pass_rate"),
        "current_pass_rate": summary.get("pass_rate"),
        "pass_rate_delta": delta(summary.get("pass_rate"), baseline_summary.get("pass_rate")),
        "node_deltas": [
            {
                "name": name,
                "baseline_avg_ms": (baseline_steps.get(name) or {}).get("avg_ms"),
                "current_avg_ms": (current_steps.get(name) or {}).get("avg_ms"),
                "avg_delta_ms": delta(
                    (current_steps.get(name) or {}).get("avg_ms"),
                    (baseline_steps.get(name) or {}).get("avg_ms"),
                ),
            }
            for name in focused_nodes
        ],
        "baseline_slowest_cases": baseline.get("slowest_cases") or [],
        "current_slowest_cases": current_slowest_cases,
    }


def delta(current: Any, baseline: Any) -> float | None:
    current_value = to_float(current)
    baseline_value = to_float(baseline)
    if current_value is None or baseline_value is None:
        return None
    return round(current_value - baseline_value, 2)


def build_summary(report: dict[str, Any], cases: list[dict[str, Any]], durations: list[float], missing_traces: int) -> dict[str, Any]:
    summary = report.get("summary") or {}
    return {
        "case_file": report.get("case_file"),
        "total_cases": len(cases),
        "passed": summary.get("passed"),
        "failed": summary.get("failed"),
        "pass_rate": summary.get("pass_rate"),
        "missing_traces": missing_traces,
        "total_duration_ms": round(sum(durations), 2),
        "avg_duration_ms": round(avg(durations), 2),
        "p50_duration_ms": percentile(durations, 50),
        "p90_duration_ms": percentile(durations, 90),
        "p95_duration_ms": percentile(durations, 95),
        "max_duration_ms": round(max(durations), 2) if durations else None,
    }


def build_step_stats(step_durations: dict[str, list[float]], step_errors: Counter[str]) -> list[dict[str, Any]]:
    rows = []
    for name, durations in step_durations.items():
        rows.append({
            "name": name,
            "count": len(durations),
            "error_count": step_errors.get(name, 0),
            "avg_ms": round(avg(durations), 2),
            "p50_ms": percentile(durations, 50),
            "p90_ms": percentile(durations, 90),
            "p95_ms": percentile(durations, 95),
            "max_ms": round(max(durations), 2),
        })
    return sorted(rows, key=lambda row: row["p95_ms"] or 0, reverse=True)


def summarize_parallel_recall(checks: list[dict[str, Any]]) -> dict[str, Any]:
    if not checks:
        return {"checked_cases": 0, "parallel_observed_cases": 0, "parallel_recall_observed": False}

    observed = [check for check in checks if check["observed"]]
    return {
        "checked_cases": len(checks),
        "parallel_observed_cases": len(observed),
        "parallel_recall_observed": bool(observed),
        "avg_duration_sum_ms": round(avg([check["duration_sum_ms"] for check in checks]), 2),
        "avg_wall_time_ms": round(avg([check["wall_time_ms"] for check in checks]), 2),
        "avg_estimated_saved_ms": round(avg([check["estimated_saved_ms"] for check in checks]), 2),
        "avg_estimated_saved_ratio": round(
            avg([check.get("estimated_saved_ratio", 0.0) for check in checks]),
            2,
        ),
    }


def slowest_cases(cases: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    sorted_cases = sorted(
        cases,
        key=lambda case: to_float(case.get("duration_ms")) or 0,
        reverse=True,
    )
    return [
        {
            "id": case.get("id"),
            "query": case.get("query"),
            "passed": case.get("passed"),
            "duration_ms": case.get("duration_ms"),
            "trace_path": case.get("trace_path"),
            "missing_trace": case.get("missing_trace"),
        }
        for case in sorted_cases[:top_n]
    ]


def render_markdown(output: dict[str, Any], top_n: int) -> str:
    summary = output["summary"]
    lines = [
        "# Agent 性能 Baseline 报告",
        "",
        f"> 生成时间：{output['generated_at']}  ",
        f"> 来源报告：`{output['source_report']}`  ",
        f"> 对比基线：`{output.get('baseline_report')}`  ",
        f"> 验收说明：{output.get('validation_note')}",
        "",
        "## 1. 总览",
        "",
        "| 指标 | 值 |",
        "|---|---:|",
        f"| Case 数 | {summary['total_cases']} |",
        f"| 通过数 | {summary.get('passed')} |",
        f"| 失败数 | {summary.get('failed')} |",
        f"| 通过率 | {summary.get('pass_rate')}% |",
        f"| 缺失 Trace 数 | {summary['missing_traces']} |",
        f"| 总耗时 ms | {summary['total_duration_ms']} |",
        f"| 平均耗时 ms | {summary['avg_duration_ms']} |",
        f"| P50 ms | {summary['p50_duration_ms']} |",
        f"| P90 ms | {summary['p90_duration_ms']} |",
        f"| P95 ms | {summary['p95_duration_ms']} |",
        f"| 最大耗时 ms | {summary['max_duration_ms']} |",
        "",
        "## 2. 节点耗时统计",
        "",
        "| 节点 | 次数 | 错误数 | 平均 ms | P50 | P90 | P95 | 最大 ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in output["step_stats"]:
        lines.append(
            f"| {row['name']} | {row['count']} | {row['error_count']} | {row['avg_ms']} | "
            f"{row['p50_ms']} | {row['p90_ms']} | {row['p95_ms']} | {row['max_ms']} |"
        )

    lines.extend([
        "",
        f"## 3. 最慢 Top {top_n} Case",
        "",
        "| Case | 通过 | 耗时 ms | Trace | 问题 |",
        "|---|---|---:|---|---|",
    ])
    for case in output["slowest_cases"]:
        query = str(case.get("query") or "").replace("|", "\\|")
        lines.append(
            f"| {case.get('id')} | {case.get('passed')} | {case.get('duration_ms')} | "
            f"`{case.get('trace_path')}` | {query} |"
        )

    lines.extend([
        "",
        "## 4. SQL EXPLAIN Risk Flags",
        "",
    ])
    if output["risk_flags"]:
        lines.extend(["| Risk Flag | 次数 |", "|---|---:|"])
        for flag, count in output["risk_flags"].items():
            lines.append(f"| {flag} | {count} |")
    else:
        lines.append("当前报告中未统计到 SQL EXPLAIN risk flag。")

    parallel = output["parallel_recall"]
    lines.extend([
        "",
        "## 5. 三路召回并行性检查",
        "",
        "| 指标 | 值 |",
        "|---|---:|",
        f"| 可检查 case 数 | {parallel.get('checked_cases')} |",
        f"| 观察到并行的 case 数 | {parallel.get('parallel_observed_cases')} |",
        f"| 是否观察到并行 | {parallel.get('parallel_recall_observed')} |",
        f"| 三路耗时平均总和 ms | {parallel.get('avg_duration_sum_ms')} |",
        f"| 三路 wall time 平均 ms | {parallel.get('avg_wall_time_ms')} |",
        f"| 平均估算节省 ms | {parallel.get('avg_estimated_saved_ms')} |",
    ])

    cache_stats = output.get("cache_stats") or {}
    embedding_cache = cache_stats.get("embedding") or {}
    keyword_cache = cache_stats.get("keyword_expansion") or {}
    lines.extend([
        "",
        "## 6. Cache Stats",
        "",
        "### 6.1 Embedding Cache",
        "",
        "| 指标 | 值 |",
        "|---|---:|",
        f"| embedding_cache_hit | {embedding_cache.get('embedding_cache_hit')} |",
        f"| embedding_cache_miss | {embedding_cache.get('embedding_cache_miss')} |",
        f"| embedding_cache_size | {embedding_cache.get('embedding_cache_size')} |",
        f"| embedding_cache_hit_rate | {embedding_cache.get('embedding_cache_hit_rate')}% |",
        "",
        "### 6.2 Keyword Expansion Cache",
        "",
        "| recall_type | hit | miss | hit_rate |",
        "|---|---:|---:|---:|",
    ])
    for recall_type in RECALL_STEP_NAMES_BY_TYPE:
        row = keyword_cache.get(recall_type) or {}
        lines.append(
            f"| {recall_type} | {row.get('hit')} | {row.get('miss')} | {row.get('hit_rate')}% |"
        )

    lines.extend([
        "",
        "### 6.3 适用范围说明",
        "",
        "- 当前 cache 是进程内缓存，不是 Redis；缓存内容不会跨进程、跨服务实例共享。",
        "- 本次 55 条 eval 是单进程连续运行，因此结果体现的是同一进程内关键词扩展与 embedding 的复用收益。",
        "- 对完全冷启动的单条请求，缓存尚未预热，收益会小一些。",
        "- 对重复问题、高频指标、高频字段和多用户长期运行场景，缓存复用更充分，收益会更明显。",
    ])

    comparison = output.get("comparison") or {}
    lines.extend([
        "",
        "## 7. Baseline 对比",
        "",
    ])
    if comparison.get("available"):
        lines.extend([
            "| 指标 | Before | After | Delta |",
            "|---|---:|---:|---:|",
            f"| total avg ms | {comparison.get('baseline_total_avg_ms')} | {comparison.get('current_total_avg_ms')} | {comparison.get('total_avg_delta_ms')} |",
            f"| P95 ms | {comparison.get('baseline_p95_ms')} | {comparison.get('current_p95_ms')} | {comparison.get('p95_delta_ms')} |",
            f"| pass_rate | {comparison.get('baseline_pass_rate')}% | {comparison.get('current_pass_rate')}% | {comparison.get('pass_rate_delta')} |",
            "",
            "| 节点 | Before avg ms | After avg ms | Delta |",
            "|---|---:|---:|---:|",
        ])
        for row in comparison.get("node_deltas") or []:
            lines.append(
                f"| {row.get('name')} | {row.get('baseline_avg_ms')} | {row.get('current_avg_ms')} | {row.get('avg_delta_ms')} |"
            )
    else:
        lines.append("未找到可用 baseline JSON，跳过前后对比。")

    lines.extend([
        "",
        "## 8. 初步结论",
        "",
        "- 若 P95 最高的节点集中在 LLM 调用，应优先减少不必要的模型调用和 prompt 长度。",
        "- 若召回节点耗时高，应优先检查 Embedding、Qdrant、Elasticsearch 和并行召回情况。",
        "- 当前阶段只评估召回链路缓存，不引入 Rerank、Memory、SQL 结果缓存或 MySQL 索引改造。",
        "",
    ])
    return "\n".join(lines)


def percentile(values: list[float], percent: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    rank = (len(ordered) - 1) * percent / 100
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return round(ordered[int(rank)], 2)
    weight = rank - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 2)


def avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def resolve_path(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else PROJECT_ROOT / path


def resolve_output_path(value: str | None, default: Path) -> Path:
    if not value:
        return default
    return resolve_path(value)


def resolve_trace_path(path: str | None) -> Path | None:
    if not path:
        return None
    trace_path = Path(path)
    if trace_path.exists():
        return trace_path
    if not trace_path.is_absolute():
        candidate = PROJECT_ROOT / trace_path
        return candidate
    try:
        return PROJECT_ROOT / trace_path.relative_to(PROJECT_ROOT)
    except ValueError:
        return trace_path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
