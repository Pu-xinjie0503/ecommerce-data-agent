"""结果等价比较器测试。"""

from decimal import Decimal

from eval.result_comparator import compare_results


def test_compare_results_accepts_decimal_within_tolerance():
    """Decimal 与浮点数在容差内应视为相等。"""

    comparison = compare_results(
        actual=[{"total_sales": Decimal("10.000001")}],
        expected=[{"total_sales": 10.0}],
        tolerance=1e-5,
    )

    assert comparison.matched is True
    assert comparison.reasons == []


def test_compare_results_ignores_row_order_by_default():
    """无显式排序语义时，结果行顺序不应影响判定。"""

    comparison = compare_results(
        actual=[{"region": "华东", "sales": 20}, {"region": "华北", "sales": 10}],
        expected=[{"region": "华北", "sales": 10}, {"region": "华东", "sales": 20}],
    )

    assert comparison.matched is True


def test_compare_results_preserves_order_when_requested():
    """Top 与排序查询必须保留结果顺序。"""

    comparison = compare_results(
        actual=[{"region": "华北"}, {"region": "华东"}],
        expected=[{"region": "华东"}, {"region": "华北"}],
        ordered=True,
    )

    assert comparison.matched is False
    assert "行顺序或行值不一致" in comparison.reasons[0]


def test_compare_results_reports_column_mismatch():
    """列集合不一致时应返回可定位的原因。"""

    comparison = compare_results(
        actual=[{"sales": 10}],
        expected=[{"total_sales": 10}],
    )

    assert comparison.matched is False
    assert comparison.reasons == ["结果列不一致：actual=['sales'] expected=['total_sales']"]


def test_compare_results_preserves_duplicate_rows():
    """忽略顺序时也不能丢失重复行的数量信息。"""

    comparison = compare_results(
        actual=[{"value": None}, {"value": None}],
        expected=[{"value": None}],
    )

    assert comparison.matched is False
    assert comparison.reasons == ["结果行数不一致：actual=2 expected=1"]


def test_compare_results_can_ignore_alias_names():
    """Execution Accuracy 可忽略不同 SQL 写法产生的列别名。"""

    comparison = compare_results(
        actual=[{"sales": 10, "region": "华北"}],
        expected=[{"total_sales": 10, "region_name": "华北"}],
        compare_columns=False,
    )

    assert comparison.matched is True
