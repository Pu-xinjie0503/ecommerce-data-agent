"""分层评测集加载、展开与隔离校验。"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class EvalCaseConfigError(ValueError):
    """评测集结构或隔离规则不合法。"""


def load_case_file(path: str | Path, *, strict: bool = True) -> list[dict[str, Any]]:
    """从 YAML 文件加载并校验评测 Case。"""

    import yaml

    case_path = Path(path)
    with case_path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    cases = normalize_case_config(data)
    validate_cases(cases, strict=strict)
    return cases


def normalize_case_config(data: Any) -> list[dict[str, Any]]:
    """兼容平铺 cases 与按意图组织的 intents 两种格式。"""

    if isinstance(data, list):
        return [dict(case) for case in data]
    if not isinstance(data, dict):
        raise EvalCaseConfigError("评测文件必须是对象或列表")
    if "cases" in data:
        cases = data.get("cases")
        if not isinstance(cases, list):
            raise EvalCaseConfigError("cases 必须是列表")
        return [dict(case) for case in cases]

    intents = data.get("intents")
    if not isinstance(intents, list):
        raise EvalCaseConfigError("评测文件必须包含 cases 或 intents 列表")

    expanded: list[dict[str, Any]] = []
    for intent in intents:
        if not isinstance(intent, dict):
            raise EvalCaseConfigError("每个 intent 必须是对象")
        queries = intent.get("queries")
        if not isinstance(queries, list) or not queries:
            raise EvalCaseConfigError(f"意图 {intent.get('intent_id')} 缺少 queries")
        shared = {key: value for key, value in intent.items() if key != "queries"}
        for index, query in enumerate(queries, start=1):
            if not isinstance(query, dict):
                raise EvalCaseConfigError("queries 中的每项必须是对象")
            case = {**shared, **query}
            case.setdefault("paraphrase_id", index)
            expanded.append(case)
    return expanded


def validate_cases(cases: list[dict[str, Any]], *, strict: bool) -> None:
    """校验 Case 标识、必填字段和 Gold SQL 约束。"""

    if not cases:
        raise EvalCaseConfigError("评测集不能为空")

    seen_ids: set[str] = set()
    for index, case in enumerate(cases, start=1):
        case_id = str(case.get("id") or "")
        if not case_id:
            raise EvalCaseConfigError(f"第 {index} 条 Case 缺少 id")
        if case_id in seen_ids:
            raise EvalCaseConfigError(f"Case id 重复：{case_id}")
        seen_ids.add(case_id)
        if not case.get("query"):
            raise EvalCaseConfigError(f"Case {case_id} 缺少 query")

        if not strict:
            continue
        for field in ("intent_id", "category"):
            if not case.get(field):
                raise EvalCaseConfigError(f"Case {case_id} 缺少 {field}")
        if not _is_non_sql_branch(case) and not case.get("gold_sql"):
            raise EvalCaseConfigError(f"普通问数 Case {case_id} 缺少 gold_sql")


def validate_intent_isolation(
    dev_cases: list[dict[str, Any]],
    test_cases: list[dict[str, Any]],
) -> None:
    """确保开发集和测试集不共享业务意图。"""

    dev_intents = {str(case.get("intent_id")) for case in dev_cases if case.get("intent_id")}
    test_intents = {str(case.get("intent_id")) for case in test_cases if case.get("intent_id")}
    overlaps = sorted(dev_intents & test_intents)
    if overlaps:
        raise EvalCaseConfigError(f"开发集与测试集存在重复意图：{', '.join(overlaps)}")


def _is_non_sql_branch(case: dict[str, Any]) -> bool:
    return bool(
        case.get("expected_blocked")
        or case.get("expected_clarification")
        or (
            case.get("expected_error_type")
            and not case.get("expected_warning_type")
        )
    )
