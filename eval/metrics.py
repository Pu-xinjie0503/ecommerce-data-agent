"""评测报告的纯函数指标聚合。"""

from collections import defaultdict
from statistics import mean
from typing import Any, Iterable


def percentile(values: Iterable[float], quantile: float) -> float:
    """使用线性插值计算分位数。"""

    numbers = sorted(float(value) for value in values)
    if not numbers:
        return 0.0
    if not 0 <= quantile <= 1:
        raise ValueError("quantile 必须位于 0 到 1 之间")
    rank = (len(numbers) - 1) * quantile
    lower = int(rank)
    upper = min(lower + 1, len(numbers) - 1)
    weight = rank - lower
    return round(numbers[lower] * (1 - weight) + numbers[upper] * weight, 2)


def build_eval_metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """按 Query、意图和分类聚合评测指标。"""

    durations = [float(case.get("duration_ms") or 0.0) for case in cases]
    execution_cases = [case for case in cases if case.get("execution_matched") is not None]
    intents: dict[str, list[dict[str, Any]]] = defaultdict(list)
    categories: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for index, case in enumerate(cases):
        intents[str(case.get("intent_id") or case.get("id") or index)].append(case)
        categories[str(case.get("category") or "uncategorized")].append(case)

    intent_rates = [_rate(group, "passed") for group in intents.values()]
    category_metrics = {
        category: {
            "total": len(group),
            "passed": sum(bool(item.get("passed")) for item in group),
            "pass_rate": _rate(group, "passed"),
            "execution_accuracy": _rate(
                [item for item in group if item.get("execution_matched") is not None],
                "execution_matched",
            ),
        }
        for category, group in sorted(categories.items())
    }

    return {
        "total": len(cases),
        "passed": sum(bool(case.get("passed")) for case in cases),
        "query_pass_rate": _rate(cases, "passed"),
        "execution_accuracy": _rate(execution_cases, "execution_matched"),
        "intent_macro_accuracy": round(mean(intent_rates), 2) if intent_rates else 0.0,
        "sql_generation_rate": _rate(cases, "sql_generated"),
        "sql_execution_rate": _rate(cases, "sql_executed"),
        "latency_ms": {
            "avg": round(mean(durations), 2) if durations else 0.0,
            "p50": percentile(durations, 0.50),
            "p90": percentile(durations, 0.90),
            "p95": percentile(durations, 0.95),
        },
        "by_category": category_metrics,
    }


def _rate(items: list[dict[str, Any]], field: str) -> float:
    if not items:
        return 0.0
    return round(sum(bool(item.get(field)) for item in items) / len(items) * 100, 2)

