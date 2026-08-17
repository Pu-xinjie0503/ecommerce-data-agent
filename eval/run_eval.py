"""轻量级问数 Agent 回归评估脚本。"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from app.agent.context import DataAgentContext
from app.agent.graph import graph
from app.agent.state import DataAgentState
from app.core.context import request_id_ctx_var
from app.observability.trace_manager import TraceManager
from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.es_client_manager import es_client_manager
from app.clients.mysql_client_manager import (
    dw_mysql_client_manager,
    meta_mysql_client_manager,
)
from app.clients.qdrant_client_manager import qdrant_client_manager
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository
from app.agent.nodes import keyword_expansion_cache
from app.conf.app_config import app_config
from eval.case_loader import EvalCaseConfigError, load_case_file
from eval.experiment import file_sha256, git_revision, paths_sha256
from eval.metrics import build_eval_metrics
from eval.result_comparator import compare_results

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = PROJECT_ROOT / "eval" / "cases.yaml"
REPORTS_DIR = PROJECT_ROOT / "eval" / "reports"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行问数 Agent 回归评估。")
    parser.add_argument("--cases", default=str(CASES_PATH), help="eval cases YAML 路径")
    parser.add_argument("--run-id", default=None, help="本次实验 ID，默认使用时间戳")
    parser.add_argument(
        "--cache-mode",
        choices=["disabled", "cold", "warm"],
        default="cold",
        help="缓存实验模式",
    )
    parser.add_argument("--strict", action="store_true", help="启用 Gold SQL 与分层字段严格校验")
    return parser.parse_args()


def resolve_path(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else PROJECT_ROOT / path


EvalConfigError = EvalCaseConfigError


class EvalQueryError(RuntimeError):
    def __init__(self, message: str, trace_path: str):
        super().__init__(message)
        self.trace_path = trace_path


def load_cases(
    cases_path: Path = CASES_PATH,
    *,
    strict: bool = False,
) -> list[dict[str, Any]]:
    cases = load_case_file(cases_path, strict=strict)
    for case in cases:
        case.setdefault("expected_blocked", False)
        case.setdefault("expected_tables", [])
        case.setdefault("expected_metrics", [])
        case.setdefault("expected_values", [])
        case.setdefault("must_contain_sql", [])
        case.setdefault("forbidden_sql", [])
        case.setdefault("expected_error_type", None)
        case.setdefault("expected_warning_type", None)
        case.setdefault("expected_clarification", False)
        case.setdefault("expected_missing_values", [])
        case.setdefault("expected_matched_values", [])
        case.setdefault("difficulty", "unknown")
        case.setdefault("description", "")

    return cases


def normalize_sql(sql: str | None) -> str:
    if not sql:
        return ""
    return " ".join(sql.split())


def contains_fragment(sql: str, fragment: str) -> bool:
    if not fragment:
        return True
    return fragment.lower() in sql.lower()


def result_preview(result: Any, limit: int = 5) -> list[Any]:
    if isinstance(result, list):
        return result[:limit]
    if result is None:
        return []
    return [result]


def result_row_count(result: Any) -> int:
    if isinstance(result, list):
        return len(result)
    if result is None:
        return 0
    return 1


def configure_cache_mode(cache_mode: str) -> None:
    """按实验模式配置并重置两类进程内缓存。"""

    enabled = cache_mode != "disabled"
    embedding_client_manager.set_cache_enabled(enabled)
    keyword_expansion_cache.set_cache_enabled(enabled)
    embedding_client_manager.clear_cache(reset_stats=True)
    keyword_expansion_cache.clear_cache(reset_stats=True)


def build_experiment_metadata(
    *,
    run_id: str,
    cases_path: Path,
    cache_mode: str,
) -> dict[str, Any]:
    """构造用于 Trace 和报告可比性校验的实验元数据。"""

    prompt_paths = list((PROJECT_ROOT / "prompts").glob("*.prompt"))
    return {
        "schema_version": 1,
        "run_id": run_id,
        "model": app_config.llm.model_name,
        "temperature": 0,
        "embedding_model": app_config.embedding.model,
        "dataset_sha256": file_sha256(cases_path),
        "prompt_sha256": paths_sha256(prompt_paths),
        "cache_mode": cache_mode,
        "code_revision": git_revision(PROJECT_ROOT),
    }


def evaluate_case_result(
    case: dict[str, Any],
    sql: str | None,
    result: Any,
    state_error: str | None,
    exception: str | None,
    risk_type: str | None,
    guard_reason: str | None,
    error_type: str | None,
    warning_type: str | None,
    need_clarification: bool | None,
    clarification_question: str | None,
    trace_step_names: list[str] | None,
    missing_values: list[str] | None,
    matched_values: list[str] | None,
) -> tuple[bool, list[str], bool, bool]:
    reasons: list[str] = []
    normalized_sql = normalize_sql(sql)
    sql_generated = bool(normalized_sql)
    sql_executed = exception is None and state_error is None and result is not None

    if case.get("expected_clarification"):
        if exception:
            reasons.append(f"执行异常：{exception}")
        if need_clarification is not True:
            reasons.append("澄清用例应返回 need_clarification=true")
        if sql is not None:
            reasons.append("澄清用例不应生成 SQL")
        if result is not None:
            reasons.append("澄清用例不应返回 SQL 执行结果")
        if not clarification_question:
            reasons.append("澄清用例缺少 clarification_question")
        steps = trace_step_names or []
        if "clarify_query" not in steps:
            reasons.append("trace 缺少 clarify_query 节点")
        if "generate_sql" in steps:
            reasons.append("澄清用例不应进入 generate_sql")
        if "run_sql" in steps:
            reasons.append("澄清用例不应进入 run_sql")
        return not reasons, reasons, sql_generated, sql_executed

    if need_clarification:
        reasons.append("非澄清用例不应被澄清拦截")
        return not reasons, reasons, sql_generated, sql_executed

    if case.get("expected_error_type") and error_type != case["expected_error_type"]:
        reasons.append(
            f"错误类型不匹配：expected={case['expected_error_type']} actual={error_type}"
        )

    if case.get("expected_warning_type") and warning_type != case["expected_warning_type"]:
        reasons.append(
            f"告警类型不匹配：expected={case['expected_warning_type']} actual={warning_type}"
        )

    if case.get("expected_missing_values"):
        actual_missing = set(missing_values or [])
        expected_missing = set(case["expected_missing_values"])
        if not expected_missing.issubset(actual_missing):
            reasons.append(
                f"缺失取值不匹配：expected包含={sorted(expected_missing)} actual={sorted(actual_missing)}"
            )

    if case.get("expected_matched_values"):
        actual_matched = set(matched_values or [])
        expected_matched = set(case["expected_matched_values"])
        if not expected_matched.issubset(actual_matched):
            reasons.append(
                f"命中取值不匹配：expected包含={sorted(expected_matched)} actual={sorted(actual_matched)}"
            )

    if case.get("expected_blocked"):
        if exception:
            reasons.append(f"执行异常：{exception}")
        if sql_generated:
            reasons.append("拦截用例不应生成 SQL")
        if result is not None:
            reasons.append("拦截用例不应返回 SQL 执行结果")
        if not risk_type or risk_type == "normal_query":
            reasons.append("拦截用例缺少有效 risk_type")
        if not guard_reason:
            reasons.append("拦截用例缺少 guard_reason")
        return not reasons, reasons, sql_generated, sql_executed

    # 期望错误类型（非 blocked）：验证 SQL 为空且 error_type 匹配
    if case.get("expected_error_type") and not case.get("expected_blocked"):
        if exception:
            reasons.append(f"执行异常：{exception}")
        if sql_generated:
            reasons.append("错误用例不应生成 SQL")
        if result is not None:
            reasons.append("错误用例不应返回 SQL 执行结果")
        return not reasons, reasons, sql_generated, sql_executed

    if exception:
        reasons.append(f"执行异常：{exception}")
    if state_error:
        reasons.append(f"SQL 校验或执行错误：{state_error}")
    if not sql_generated:
        reasons.append("未生成 SQL")

    for fragment in case.get("must_contain_sql", []):
        if not contains_fragment(normalized_sql, str(fragment)):
            reasons.append(f"SQL 缺少必须片段：{fragment}")

    for fragment in case.get("forbidden_sql", []):
        if fragment and contains_fragment(normalized_sql, str(fragment)):
            reasons.append(f"SQL 出现禁用片段：{fragment}")

    return not reasons, reasons, sql_generated, sql_executed


def init_clients() -> None:
    qdrant_client_manager.init()
    embedding_client_manager.init()
    es_client_manager.init()
    meta_mysql_client_manager.init()
    dw_mysql_client_manager.init()


async def close_clients() -> None:
    await qdrant_client_manager.close()
    await embedding_client_manager.close()
    await es_client_manager.close()
    await meta_mysql_client_manager.close()
    await dw_mysql_client_manager.close()


async def run_agent_query(
    case: dict[str, Any],
    experiment: dict[str, Any],
) -> dict[str, Any]:
    if qdrant_client_manager.client is None:
        raise RuntimeError("Qdrant client 未初始化")
    if es_client_manager.client is None:
        raise RuntimeError("Elasticsearch client 未初始化")
    if meta_mysql_client_manager.session_factory is None:
        raise RuntimeError("Meta MySQL session_factory 未初始化")
    if dw_mysql_client_manager.session_factory is None:
        raise RuntimeError("DW MySQL session_factory 未初始化")

    query = case["query"]
    case_id = case["id"]
    request_id = f"{experiment['run_id']}-{case_id}-{uuid.uuid4().hex[:8]}"
    request_id_token = request_id_ctx_var.set(request_id)
    case_experiment = {
        **experiment,
        "case_id": case_id,
        "intent_id": case.get("intent_id"),
        "category": case.get("category"),
        "paraphrase_id": case.get("paraphrase_id"),
    }
    trace_manager = TraceManager(
        request_id=request_id,
        query=query,
        root_dir=PROJECT_ROOT / "traces" / "eval" / experiment["run_id"],
        experiment=case_experiment,
    )
    agent_started_at = time.perf_counter()

    try:
        async with (
            meta_mysql_client_manager.session_factory() as meta_session,
            dw_mysql_client_manager.session_factory() as dw_session,
        ):
            dw_repository = DWMySQLRepository(dw_session)
            context = DataAgentContext(
                column_qdrant_repository=ColumnQdrantRepository(qdrant_client_manager.client),
                embedding_client=embedding_client_manager,
                metric_qdrant_repository=MetricQdrantRepository(qdrant_client_manager.client),
                value_es_repository=ValueESRepository(es_client_manager.client),
                meta_mysql_repository=MetaMySQLRepository(meta_session),
                dw_mysql_repository=dw_repository,
                request_id=request_id,
                trace_manager=trace_manager,
            )
            state = DataAgentState(query=query)
            final_state: dict[str, Any] = {}

            async for chunk in graph.astream(
                input=state,
                context=context,
                stream_mode="values",
            ):
                final_state = dict(chunk)

            trace_manager.finish("success")
            trace_path = trace_manager.save()
            agent_duration_ms = round((time.perf_counter() - agent_started_at) * 1000, 2)

            gold_result = None
            gold_error = None
            gold_duration_ms = None
            if case.get("gold_sql"):
                gold_started_at = time.perf_counter()
                try:
                    gold_result = await dw_repository.run(case["gold_sql"])
                except Exception as exc:
                    gold_error = str(exc)
                gold_duration_ms = round((time.perf_counter() - gold_started_at) * 1000, 2)

            return {
                "final_state": final_state,
                "trace_path": trace_path,
                "agent_duration_ms": agent_duration_ms,
                "gold_result": gold_result,
                "gold_error": gold_error,
                "gold_duration_ms": gold_duration_ms,
            }
    except Exception as exc:
        trace_manager.finish("failed")
        trace_path = trace_manager.save()
        raise EvalQueryError(str(exc), trace_path) from exc
    finally:
        request_id_ctx_var.reset(request_id_token)


def get_trace_step_names(trace_path: str) -> list[str]:
    if not trace_path:
        return []

    path = Path(trace_path)
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8") as file:
        trace = json.load(file)

    steps = trace.get("steps") or []
    return [step.get("name") for step in steps if isinstance(step, dict) and step.get("name")]


async def run_case(
    case: dict[str, Any],
    experiment: dict[str, Any],
) -> dict[str, Any]:
    started_at = time.perf_counter()
    final_state: dict[str, Any] = {}
    trace_path = ""
    exception: str | None = None
    gold_result = None
    gold_error = None
    gold_duration_ms = None
    agent_duration_ms = None

    try:
        agent_result = await run_agent_query(case, experiment)
        final_state = agent_result["final_state"]
        trace_path = agent_result["trace_path"]
        agent_duration_ms = agent_result["agent_duration_ms"]
        gold_result = agent_result["gold_result"]
        gold_error = agent_result["gold_error"]
        gold_duration_ms = agent_result["gold_duration_ms"]
    except EvalQueryError as exc:
        exception = str(exc)
        trace_path = exc.trace_path
    except Exception as exc:
        exception = str(exc)

    evaluation_duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
    duration_ms = agent_duration_ms or evaluation_duration_ms
    sql = final_state.get("sql")
    result = final_state.get("result")
    state_error = final_state.get("error")
    risk_type = final_state.get("risk_type")
    guard_reason = final_state.get("guard_reason")
    error_type = final_state.get("error_type")
    error_message = final_state.get("error_message")
    recoverable = final_state.get("recoverable")
    suggested_action = final_state.get("suggested_action")
    warning_type = final_state.get("warning_type")
    warning_message = final_state.get("warning_message")
    need_clarification = final_state.get("need_clarification")
    clarification_type = final_state.get("clarification_type")
    clarification_question = final_state.get("clarification_question")
    clarification_options = final_state.get("clarification_options")
    missing_values = final_state.get("missing_values")
    matched_values = final_state.get("matched_values")
    trace_step_names = get_trace_step_names(trace_path)
    legacy_case = dict(case)
    if case.get("gold_sql"):
        legacy_case["must_contain_sql"] = []
        legacy_case["forbidden_sql"] = []
    passed, reasons, sql_generated, sql_executed = evaluate_case_result(
        case=legacy_case,
        sql=sql,
        result=result,
        state_error=state_error,
        exception=exception,
        risk_type=risk_type,
        guard_reason=guard_reason,
        error_type=error_type,
        warning_type=warning_type,
        need_clarification=need_clarification,
        clarification_question=clarification_question,
        trace_step_names=trace_step_names,
        missing_values=missing_values,
        matched_values=matched_values,
    )

    execution_matched = None
    if case.get("gold_sql"):
        if gold_error:
            passed = False
            reasons.append(f"Gold SQL 执行失败：{gold_error}")
            execution_matched = False
        elif result is None:
            passed = False
            execution_matched = False
        else:
            comparison = compare_results(
                actual=result,
                expected=gold_result,
                ordered=bool(case.get("ordered_result")),
                tolerance=float(case.get("tolerance", 1e-6)),
                compare_columns=bool(case.get("compare_columns", False)),
            )
            execution_matched = comparison.matched
            if not comparison.matched:
                passed = False
                reasons.extend(comparison.reasons)

    return {
        "id": case["id"],
        "query": case["query"],
        "intent_id": case.get("intent_id"),
        "paraphrase_id": case.get("paraphrase_id"),
        "category": case.get("category"),
        "difficulty": case.get("difficulty"),
        "description": case.get("description"),
        "passed": passed,
        "reasons": reasons,
        "sql_generated": sql_generated,
        "sql_executed": sql_executed,
        "execution_matched": execution_matched,
        "sql": normalize_sql(sql),
        "result_preview": result_preview(result),
        "result_row_count": result_row_count(result),
        "gold_sql": normalize_sql(case.get("gold_sql")),
        "gold_result_preview": result_preview(gold_result),
        "gold_result_row_count": result_row_count(gold_result),
        "gold_error": gold_error,
        "gold_duration_ms": gold_duration_ms,
        "risk_type": risk_type,
        "guard_reason": guard_reason,
        "error_type": error_type,
        "error_message": error_message,
        "recoverable": recoverable,
        "suggested_action": suggested_action,
        "warning_type": warning_type,
        "warning_message": warning_message,
        "need_clarification": need_clarification,
        "clarification_type": clarification_type,
        "clarification_question": clarification_question,
        "clarification_options": clarification_options,
        "missing_values": missing_values,
        "matched_values": matched_values,
        "trace_path": trace_path,
        "duration_ms": duration_ms,
        "evaluation_duration_ms": evaluation_duration_ms,
        "error": exception or state_error,
    }


def build_summary(case_reports: list[dict[str, Any]], duration_seconds: float) -> dict[str, Any]:
    total = len(case_reports)
    passed = sum(1 for item in case_reports if item["passed"])
    failed = total - passed
    pass_rate = round(passed / total * 100, 2) if total else 0.0

    evidence_metrics = build_eval_metrics(case_reports)
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": pass_rate,
        "duration_seconds": round(duration_seconds, 2),
        **evidence_metrics,
    }


def write_json_report(report: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2, default=str)


def write_markdown_report(report: dict[str, Any], output_path: Path) -> None:
    summary = report["summary"]
    experiment = report["experiment"]
    lines = [
        "# 问数 Agent 自动化评估报告",
        "",
        f"生成时间：{report['generated_at']}",
        "",
        "## 实验元数据",
        "",
        "| run_id | model | temperature | cache_mode | dataset_sha256 | prompt_sha256 |",
        "|---|---|---:|---|---|---|",
        (
            f"| {experiment['run_id']} | {experiment['model']} | {experiment['temperature']} | "
            f"{experiment['cache_mode']} | {experiment['dataset_sha256']} | "
            f"{experiment['prompt_sha256']} |"
        ),
        "",
        "## 总体统计",
        "",
        "| total | passed | failed | pass_rate | execution_accuracy | intent_macro_accuracy | P95 ms |",
        "|---:|---:|---:|---:|---:|---:|---:|",
        (
            f"| {summary['total']} | {summary['passed']} | {summary['failed']} | "
            f"{summary['pass_rate']}% | {summary['execution_accuracy']}% | "
            f"{summary['intent_macro_accuracy']}% | {summary['latency_ms']['p95']} |"
        ),
        "",
        "## Case 明细",
        "",
        "| id | intent_id | category | status | execution_matched | duration_ms | trace_path | reasons |",
        "|---|---|---|---|---|---:|---|---|",
    ]

    for item in report["cases"]:
        status = "PASS" if item["passed"] else "FAIL"
        reasons = "；".join(item["reasons"]) if item["reasons"] else "-"
        lines.append(
            f"| {item['id']} | {item.get('intent_id') or '-'} | {item.get('category') or '-'} | "
            f"{status} | {item.get('execution_matched')} | "
            f"{item['duration_ms']} | {item.get('trace_path') or '-'} | {reasons} |"
        )

    failed_cases = [item for item in report["cases"] if not item["passed"]]
    if failed_cases:
        lines.extend(["", "## 失败详情", ""])
        for item in failed_cases:
            lines.extend(
                [
                    f"### {item['id']} {item['query']}",
                    "",
                    "失败原因：",
                    *[f"- {reason}" for reason in item["reasons"]],
                    "",
                    f"Trace：{item.get('trace_path') or '-'}",
                    "",
                    "SQL：",
                    "",
                    "```sql",
                    item["sql"] or "<empty>",
                    "```",
                    "",
                ]
            )

    lines.extend(["", "## SQL 预览", ""])
    for item in report["cases"]:
        lines.extend(
            [
                f"### {item['id']} {item['query']}",
                "",
                "```sql",
                item["sql"] or "<empty>",
                "```",
                "",
            ]
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        file.write("\n".join(lines))


def print_case_report(case_report: dict[str, Any]) -> None:
    status = "PASS" if case_report["passed"] else "FAIL"
    print(
        f"[{status}] {case_report['id']} {case_report['query']} "
        f"({case_report['duration_ms']} ms) trace={case_report.get('trace_path') or '-'}"
    )
    for reason in case_report["reasons"]:
        print(f"  - {reason}")


def print_summary(summary: dict[str, Any], json_path: Path, markdown_path: Path) -> None:
    print("\n总体统计")
    print(f"  total: {summary['total']}")
    print(f"  passed: {summary['passed']}")
    print(f"  failed: {summary['failed']}")
    print(f"  pass_rate: {summary['pass_rate']}%")
    print(f"  execution_accuracy: {summary['execution_accuracy']}%")
    print(f"  intent_macro_accuracy: {summary['intent_macro_accuracy']}%")
    print(f"  duration_seconds: {summary['duration_seconds']}")
    print(f"\n报告已保存：{markdown_path}")
    print(f"报告已保存：{json_path}")


async def main() -> None:
    args = parse_args()
    cases_path = resolve_path(args.cases)
    cases = load_cases(cases_path, strict=args.strict)
    run_id = args.run_id or datetime.now().strftime("eval-%Y%m%d-%H%M%S")
    configure_cache_mode(args.cache_mode)
    experiment = build_experiment_metadata(
        run_id=run_id,
        cases_path=cases_path,
        cache_mode=args.cache_mode,
    )
    experiment["warmup_query_count"] = len(cases) if args.cache_mode == "warm" else 0
    experiment["measurement_query_count"] = len(cases)
    output_dir = REPORTS_DIR / run_id
    json_path = output_dir / "eval.json"
    markdown_path = output_dir / "eval.md"
    warmup_duration_seconds = 0.0
    case_reports: list[dict[str, Any]] = []

    init_clients()
    try:
        if args.cache_mode == "warm":
            print(f"开始暖缓存预热：{len(cases)} 条 Query（不计入报告）")
            warmup_experiment = {**experiment, "phase": "warmup", "measured": False}
            warmup_started_at = time.perf_counter()
            for index, case in enumerate(cases, start=1):
                await run_case(case, warmup_experiment)
                print(f"[WARMUP] {index}/{len(cases)} {case['id']}")
            warmup_duration_seconds = time.perf_counter() - warmup_started_at
            embedding_client_manager.reset_cache_stats()
            keyword_expansion_cache.reset_cache_stats()
            print("暖缓存预热完成，已清零命中统计并开始计量轮")

        measured_experiment = {**experiment, "phase": "measured", "measured": True}
        started_at = time.perf_counter()
        for case in cases:
            case_report = await run_case(case, measured_experiment)
            case_reports.append(case_report)
            print_case_report(case_report)
    finally:
        await close_clients()

    duration_seconds = time.perf_counter() - started_at
    summary = build_summary(case_reports, duration_seconds)
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "experiment": experiment,
        "case_file": str(cases_path),
        "warmup_duration_seconds": round(warmup_duration_seconds, 2),
        "summary": summary,
        "cases": case_reports,
    }
    write_json_report(report, json_path)
    write_markdown_report(report, markdown_path)
    print_summary(summary, json_path, markdown_path)


if __name__ == "__main__":
    asyncio.run(main())
