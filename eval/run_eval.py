"""轻量级问数 Agent 回归评估脚本。"""

import asyncio
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = PROJECT_ROOT / "eval" / "cases.yaml"
REPORTS_DIR = PROJECT_ROOT / "eval" / "reports"
LATEST_JSON_PATH = REPORTS_DIR / "latest.json"
LATEST_MD_PATH = REPORTS_DIR / "latest.md"


class EvalConfigError(ValueError):
    pass


class EvalQueryError(RuntimeError):
    def __init__(self, message: str, trace_path: str):
        super().__init__(message)
        self.trace_path = trace_path


def load_cases() -> list[dict[str, Any]]:
    with CASES_PATH.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)

    if isinstance(data, dict):
        cases = data.get("cases")
    else:
        cases = data

    if not isinstance(cases, list) or not cases:
        raise EvalConfigError("eval/cases.yaml 必须包含非空 cases 列表")

    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            raise EvalConfigError(f"第 {index} 条 case 必须是对象")
        if not case.get("id"):
            raise EvalConfigError(f"第 {index} 条 case 缺少 id")
        if not case.get("query"):
            raise EvalConfigError(f"case {case.get('id')} 缺少 query")

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


async def run_agent_query(query: str, case_id: str) -> dict[str, Any]:
    if qdrant_client_manager.client is None:
        raise RuntimeError("Qdrant client 未初始化")
    if es_client_manager.client is None:
        raise RuntimeError("Elasticsearch client 未初始化")
    if meta_mysql_client_manager.session_factory is None:
        raise RuntimeError("Meta MySQL session_factory 未初始化")
    if dw_mysql_client_manager.session_factory is None:
        raise RuntimeError("DW MySQL session_factory 未初始化")

    request_id = f"eval-{case_id}-{uuid.uuid4().hex[:8]}"
    request_id_token = request_id_ctx_var.set(request_id)
    trace_manager = TraceManager(request_id=request_id, query=query)

    try:
        async with (
            meta_mysql_client_manager.session_factory() as meta_session,
            dw_mysql_client_manager.session_factory() as dw_session,
        ):
            context = DataAgentContext(
                column_qdrant_repository=ColumnQdrantRepository(qdrant_client_manager.client),
                embedding_client=embedding_client_manager,
                metric_qdrant_repository=MetricQdrantRepository(qdrant_client_manager.client),
                value_es_repository=ValueESRepository(es_client_manager.client),
                meta_mysql_repository=MetaMySQLRepository(meta_session),
                dw_mysql_repository=DWMySQLRepository(dw_session),
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
            return {"final_state": final_state, "trace_path": trace_path}
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


async def run_case(case: dict[str, Any]) -> dict[str, Any]:
    started_at = time.perf_counter()
    final_state: dict[str, Any] = {}
    trace_path = ""
    exception: str | None = None

    try:
        agent_result = await run_agent_query(case["query"], case["id"])
        final_state = agent_result["final_state"]
        trace_path = agent_result["trace_path"]
    except EvalQueryError as exc:
        exception = str(exc)
        trace_path = exc.trace_path
    except Exception as exc:
        exception = str(exc)

    duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
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
    passed, reasons, sql_generated, sql_executed = evaluate_case_result(
        case=case,
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

    return {
        "id": case["id"],
        "query": case["query"],
        "difficulty": case.get("difficulty"),
        "description": case.get("description"),
        "passed": passed,
        "reasons": reasons,
        "sql_generated": sql_generated,
        "sql_executed": sql_executed,
        "sql": normalize_sql(sql),
        "result_preview": result_preview(result),
        "result_row_count": result_row_count(result),
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
        "error": exception or state_error,
    }


def build_summary(case_reports: list[dict[str, Any]], duration_seconds: float) -> dict[str, Any]:
    total = len(case_reports)
    passed = sum(1 for item in case_reports if item["passed"])
    failed = total - passed
    pass_rate = round(passed / total * 100, 2) if total else 0.0

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": pass_rate,
        "duration_seconds": round(duration_seconds, 2),
    }


def write_json_report(report: dict[str, Any]) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with LATEST_JSON_PATH.open("w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2, default=str)


def write_markdown_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    lines = [
        "# 问数 Agent 自动化评估报告",
        "",
        f"生成时间：{report['generated_at']}",
        "",
        "## 总体统计",
        "",
        "| total | passed | failed | pass_rate | duration_seconds |",
        "|---:|---:|---:|---:|---:|",
        (
            f"| {summary['total']} | {summary['passed']} | {summary['failed']} | "
            f"{summary['pass_rate']}% | {summary['duration_seconds']} |"
        ),
        "",
        "## Case 明细",
        "",
        "| id | difficulty | status | duration_ms | trace_path | reasons |",
        "|---|---|---|---:|---|---|",
    ]

    for item in report["cases"]:
        status = "PASS" if item["passed"] else "FAIL"
        reasons = "；".join(item["reasons"]) if item["reasons"] else "-"
        lines.append(
            f"| {item['id']} | {item['difficulty']} | {status} | "
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

    with LATEST_MD_PATH.open("w", encoding="utf-8") as file:
        file.write("\n".join(lines))


def print_case_report(case_report: dict[str, Any]) -> None:
    status = "PASS" if case_report["passed"] else "FAIL"
    print(
        f"[{status}] {case_report['id']} {case_report['query']} "
        f"({case_report['duration_ms']} ms) trace={case_report.get('trace_path') or '-'}"
    )
    for reason in case_report["reasons"]:
        print(f"  - {reason}")


def print_summary(summary: dict[str, Any]) -> None:
    print("\n总体统计")
    print(f"  total: {summary['total']}")
    print(f"  passed: {summary['passed']}")
    print(f"  failed: {summary['failed']}")
    print(f"  pass_rate: {summary['pass_rate']}%")
    print(f"  duration_seconds: {summary['duration_seconds']}")
    print(f"\n报告已保存：{LATEST_MD_PATH}")
    print(f"报告已保存：{LATEST_JSON_PATH}")


async def main() -> None:
    cases = load_cases()
    started_at = time.perf_counter()
    case_reports: list[dict[str, Any]] = []

    init_clients()
    try:
        for case in cases:
            case_report = await run_case(case)
            case_reports.append(case_report)
            print_case_report(case_report)
    finally:
        await close_clients()

    duration_seconds = time.perf_counter() - started_at
    summary = build_summary(case_reports, duration_seconds)
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "cases": case_reports,
    }
    write_json_report(report)
    write_markdown_report(report)
    print_summary(summary)


if __name__ == "__main__":
    asyncio.run(main())
