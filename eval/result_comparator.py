"""SQL 执行结果的语义等价比较。"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from numbers import Number
from typing import Any, Mapping


@dataclass(frozen=True)
class ResultComparison:
    """一次结果比较的判定与原因。"""

    matched: bool
    reasons: list[str]


def compare_results(
    actual: Any,
    expected: Any,
    *,
    ordered: bool = False,
    tolerance: float = 1e-6,
    compare_columns: bool = True,
) -> ResultComparison:
    """比较两个查询结果，支持数值容差和可选的行顺序语义。"""

    actual_rows = _normalize_rows(actual)
    expected_rows = _normalize_rows(expected)

    if len(actual_rows) != len(expected_rows):
        return ResultComparison(
            matched=False,
            reasons=[f"结果行数不一致：actual={len(actual_rows)} expected={len(expected_rows)}"],
        )

    actual_columns = _collect_columns(actual_rows)
    expected_columns = _collect_columns(expected_rows)
    if compare_columns and actual_columns != expected_columns:
        return ResultComparison(
            matched=False,
            reasons=[
                f"结果列不一致：actual={sorted(actual_columns)} expected={sorted(expected_columns)}"
            ],
        )

    if ordered:
        for index, (actual_row, expected_row) in enumerate(
            zip(actual_rows, expected_rows),
            start=1,
        ):
            if not _rows_equal(
                actual_row,
                expected_row,
                tolerance,
                compare_columns=compare_columns,
            ):
                return ResultComparison(
                    matched=False,
                    reasons=[f"第 {index} 行顺序或行值不一致"],
                )
        return ResultComparison(matched=True, reasons=[])

    unmatched_expected = list(expected_rows)
    for actual_row in actual_rows:
        match_index = next(
            (
                index
                for index, expected_row in enumerate(unmatched_expected)
                if _rows_equal(
                    actual_row,
                    expected_row,
                    tolerance,
                    compare_columns=compare_columns,
                )
            ),
            None,
        )
        if match_index is None:
            return ResultComparison(
                matched=False,
                reasons=[f"结果行值不一致：未找到匹配行 {actual_row}"],
            )
        unmatched_expected.pop(match_index)

    return ResultComparison(matched=True, reasons=[])


def _normalize_rows(result: Any) -> list[dict[str, Any]]:
    if result is None:
        return []
    rows = result if isinstance(result, list) else [result]
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, Mapping):
            normalized.append(
                {str(key).lower(): _normalize_value(value) for key, value in row.items()}
            )
            continue
        if hasattr(row, "_mapping"):
            normalized.append(
                {
                    str(key).lower(): _normalize_value(value)
                    for key, value in row._mapping.items()
                }
            )
            continue
        normalized.append({"value": _normalize_value(row)})
    return normalized


def _normalize_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _collect_columns(rows: list[dict[str, Any]]) -> set[str]:
    return {column for row in rows for column in row}


def _rows_equal(
    actual: dict[str, Any],
    expected: dict[str, Any],
    tolerance: float,
    *,
    compare_columns: bool,
) -> bool:
    if len(actual) != len(expected):
        return False
    if not compare_columns:
        return all(
            _values_equal(actual_value, expected_value, tolerance)
            for actual_value, expected_value in zip(actual.values(), expected.values())
        )
    if actual.keys() != expected.keys():
        return False
    return all(
        _values_equal(actual[column], expected[column], tolerance)
        for column in actual
    )


def _values_equal(actual: Any, expected: Any, tolerance: float) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return actual is expected
    if isinstance(actual, Number) and isinstance(expected, Number):
        return abs(float(actual) - float(expected)) <= tolerance
    return actual == expected
