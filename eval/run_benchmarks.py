"""统一执行缓存消融评测与 API 稳定性压测。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from eval.compare_runs import compare_eval_reports


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = PROJECT_ROOT / "eval" / "reports"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行可复现的 Agent 评测与 API 压测套件")
    parser.add_argument("--suite-id", default=None, help="套件 ID，默认按当前时间生成")
    parser.add_argument("--cases", default="eval/cases_test.yaml", help="缓存消融使用的严格评测集")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000/api/query", help="API 地址")
    parser.add_argument("--concurrency", type=int, default=10, help="API 压测并发数")
    parser.add_argument("--requests", type=int, default=50, help="API 计量请求数")
    parser.add_argument("--warmup-requests", type=int, default=5, help="API 预热请求数")
    parser.add_argument("--skip-eval", action="store_true", help="跳过 disabled/cold/warm 评测")
    parser.add_argument("--skip-api", action="store_true", help="跳过 API 稳定性压测")
    return parser.parse_args()


def run_command(command: list[str]) -> None:
    """执行子命令并在失败时立即停止，保留原始控制台日志。"""

    print(f"\n执行：{' '.join(command)}")
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_cache_comparison(suite_id: str) -> Path:
    """比较关闭缓存与暖缓存运行，写出机器可读证据。"""

    baseline_path = REPORTS_DIR / f"{suite_id}-disabled" / "eval.json"
    candidate_path = REPORTS_DIR / f"{suite_id}-warm" / "eval.json"
    comparison = compare_eval_reports(load_json(baseline_path), load_json(candidate_path))
    comparison["baseline_trace_analysis"] = load_json(
        REPORTS_DIR / f"{suite_id}-disabled" / "trace_analysis.json"
    )
    comparison["candidate_trace_analysis"] = load_json(
        REPORTS_DIR / f"{suite_id}-warm" / "trace_analysis.json"
    )
    output_path = REPORTS_DIR / suite_id / "cache_comparison.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def main() -> None:
    args = parse_args()
    if args.concurrency <= 0 or args.requests <= 0 or args.warmup_requests < 0:
        raise ValueError("并发数和请求数必须大于 0，预热请求数不能小于 0")

    suite_id = args.suite_id or datetime.now().strftime("evidence-%Y%m%d-%H%M%S")
    if not args.skip_eval:
        for cache_mode in ("disabled", "cold", "warm"):
            run_id = f"{suite_id}-{cache_mode}"
            run_command(
                [
                    sys.executable,
                    "-m",
                    "eval.run_eval",
                    "--cases",
                    args.cases,
                    "--strict",
                    "--cache-mode",
                    cache_mode,
                    "--run-id",
                    run_id,
                ]
            )
            run_command(
                [
                    sys.executable,
                    "-m",
                    "eval.analyze_trace_latency",
                    "--report",
                    f"eval/reports/{run_id}/eval.json",
                ]
            )
        comparison_path = write_cache_comparison(suite_id)
        print(f"\n缓存消融对比：{comparison_path}")

    if not args.skip_api:
        run_command(
            [
                sys.executable,
                "-m",
                "eval.benchmark_api",
                "--url",
                args.api_url,
                "--cases",
                "eval/benchmark_cases.yaml",
                "--concurrency",
                str(args.concurrency),
                "--requests",
                str(args.requests),
                "--warmup-requests",
                str(args.warmup_requests),
                "--run-id",
                f"{suite_id}-api",
            ]
        )

    print(f"\n评测套件完成：suite_id={suite_id}")


if __name__ == "__main__":
    main()
