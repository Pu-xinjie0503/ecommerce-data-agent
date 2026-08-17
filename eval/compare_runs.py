"""比较两次评测或 API 压测运行，并输出可复算的提升指标。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from eval.experiment import validate_comparable


BENCHMARK_COMPARABLE_FIELDS = (
    "url",
    "concurrency",
    "requests",
    "warmup_requests",
    "cases_sha256",
)


def compare_benchmark_reports(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """比较同负载 API 压测报告的延迟、吞吐与技术错误率。"""

    validate_comparable(baseline, candidate, required_fields=BENCHMARK_COMPARABLE_FIELDS)
    baseline_summary = baseline["summary"]
    candidate_summary = candidate["summary"]
    return {
        "report_type": "api_benchmark",
        "baseline_run_id": baseline.get("run_id"),
        "candidate_run_id": candidate.get("run_id"),
        "p95_latency_reduction_pct": _reduction_pct(
            baseline_summary.get("p95_latency_ms", 0),
            candidate_summary.get("p95_latency_ms", 0),
        ),
        "throughput_improvement_pct": _improvement_pct(
            baseline_summary.get("throughput_rps", 0),
            candidate_summary.get("throughput_rps", 0),
        ),
        "technical_error_rate_delta_pp": round(
            float(candidate_summary.get("technical_error_rate", 0))
            - float(baseline_summary.get("technical_error_rate", 0)),
            2,
        ),
        "baseline_summary": baseline_summary,
        "candidate_summary": candidate_summary,
    }


def compare_eval_reports(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """比较同数据集 Agent 评测报告的准确率与延迟。"""

    validate_comparable(baseline["experiment"], candidate["experiment"])
    baseline_summary = baseline["summary"]
    candidate_summary = candidate["summary"]
    return {
        "report_type": "agent_eval",
        "baseline_run_id": baseline["experiment"].get("run_id"),
        "candidate_run_id": candidate["experiment"].get("run_id"),
        "execution_accuracy_delta_pp": _delta_pp(
            baseline_summary.get("execution_accuracy", 0),
            candidate_summary.get("execution_accuracy", 0),
        ),
        "intent_macro_accuracy_delta_pp": _delta_pp(
            baseline_summary.get("intent_macro_accuracy", 0),
            candidate_summary.get("intent_macro_accuracy", 0),
        ),
        "p95_latency_reduction_pct": _reduction_pct(
            baseline_summary.get("latency_ms", {}).get("p95", 0),
            candidate_summary.get("latency_ms", {}).get("p95", 0),
        ),
        "baseline_summary": baseline_summary,
        "candidate_summary": candidate_summary,
    }


def compare_reports(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """根据报告结构选择对应的比较逻辑。"""

    if "experiment" in baseline and "experiment" in candidate:
        return compare_eval_reports(baseline, candidate)
    return compare_benchmark_reports(baseline, candidate)


def _delta_pp(baseline: float, candidate: float) -> float:
    return round(float(candidate) - float(baseline), 2)


def _reduction_pct(baseline: float, candidate: float) -> float | None:
    baseline_value = float(baseline)
    if baseline_value == 0:
        return None
    return round((baseline_value - float(candidate)) / baseline_value * 100, 2)


def _improvement_pct(baseline: float, candidate: float) -> float | None:
    baseline_value = float(baseline)
    if baseline_value == 0:
        return None
    return round((float(candidate) - baseline_value) / baseline_value * 100, 2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="比较两次评测或 API 压测报告")
    parser.add_argument("--baseline", required=True, help="基线 JSON 报告")
    parser.add_argument("--candidate", required=True, help="候选 JSON 报告")
    parser.add_argument("--output", default=None, help="可选 JSON 对比结果输出路径")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with Path(args.baseline).open("r", encoding="utf-8") as file:
        baseline = json.load(file)
    with Path(args.candidate).open("r", encoding="utf-8") as file:
        candidate = json.load(file)

    comparison = compare_reports(baseline, candidate)
    content = json.dumps(comparison, ensure_ascii=False, indent=2)
    print(content)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content + "\n", encoding="utf-8")
        print(f"\n对比报告：{output_path}")


if __name__ == "__main__":
    main()
