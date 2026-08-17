import pytest

from typing import get_type_hints

from app.agent.query_semantics import find_dimension_mentions, parse_query_semantics
from app.agent.state import DataAgentState, QuerySemanticsState


def test_query_semantics_state_contract() -> None:
    """查询语义状态必须提供所有节点共享的稳定字段。"""

    semantic_fields = get_type_hints(QuerySemanticsState)
    assert set(semantic_fields) == {
        "dimension_columns",
        "group_by_columns",
        "filter_values",
        "metric_terms",
        "time_expressions",
        "order_direction",
        "limit",
        "parse_evidence",
    }
    assert "query_semantics" in get_type_hints(DataAgentState)


def test_grounding_observability_state_contract() -> None:
    """Grounding 跳过策略必须进入共享状态契约，供 Trace 和评测统计使用。"""

    state_fields = get_type_hints(DataAgentState)
    assert state_fields["grounding_validation_skipped"] is bool
    assert state_fields["value_keyword_expansion_skipped"] is bool
    assert state_fields["grounding_skip_reason"] == str | None


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("按商品统计销售额", ["dim_product.product_name"]),
        ("按商品品类统计销量", ["dim_product.category"]),
        ("不同会员层级的销量", ["dim_customer.member_level"]),
        (
            "各省男女客户贡献的 GMV",
            ["dim_region.province", "dim_customer.gender"],
        ),
        (
            "地区季度维度",
            ["dim_region.region_name", "dim_date.quarter"],
        ),
    ],
)
def test_find_dimension_mentions(query: str, expected: list[str]) -> None:
    """字段别名应按最长文本匹配并映射到业务维度列。"""

    assert find_dimension_mentions(query) == expected


@pytest.mark.parametrize(
    ("query", "group_by", "filters", "metrics", "direction", "limit"),
    [
        (
            "按会员等级和商品品类统计销量",
            ["dim_customer.member_level", "dim_product.category"],
            {},
            ["order_quantity"],
            None,
            None,
        ),
        (
            "不同会员层级在各品类买了多少件",
            ["dim_customer.member_level", "dim_product.category"],
            {},
            ["order_quantity"],
            None,
            None,
        ),
        (
            "订单数最多的三个品牌是什么",
            ["dim_product.brand"],
            {},
            ["order_count"],
            "desc",
            3,
        ),
        (
            "查询地区季度维度的 GMV、销售件数和订单量",
            ["dim_region.region_name", "dim_date.quarter"],
            {},
            ["gmv", "order_quantity", "order_count"],
            None,
            None,
        ),
    ],
)
def test_parse_query_semantics_for_analysis_query(
    query: str,
    group_by: list[str],
    filters: dict[str, list[str]],
    metrics: list[str],
    direction: str | None,
    limit: int | None,
) -> None:
    """分析语句应区分分组、过滤、指标和排序语义。"""

    result = parse_query_semantics(query)
    assert result["group_by_columns"] == group_by
    assert result["filter_values"] == filters
    assert result["metric_terms"] == metrics
    assert result["order_direction"] == direction
    assert result["limit"] == limit


@pytest.mark.parametrize(
    ("query", "expected_filters"),
    [
        (
            "统计 2025 年 3 月华北地区的销售额",
            {"dim_region.region_name": ["华北"]},
        ),
        (
            "对比华北和火星地区的销售额",
            {"dim_region.region_name": ["华北", "火星"]},
        ),
        ("统计火星牌商品的销售额", {"dim_product.brand": ["火星牌"]}),
        ("火星牌一共卖了多少钱", {"dim_product.brand": ["火星牌"]}),
        ("查询品牌为火星牌的 GMV", {"dim_product.brand": ["火星牌"]}),
        ("按会员等级和商品品类统计销量", {}),
        ("查询不同地区的平均订单金额", {}),
        ("订单数最多的三个品牌是什么", {}),
    ],
)
def test_parse_explicit_filter_values(
    query: str,
    expected_filters: dict[str, list[str]],
) -> None:
    """Grounding 候选只能来自明确过滤条件。"""

    assert parse_query_semantics(query)["filter_values"] == expected_filters


def test_parse_time_expression_without_contaminating_region_value() -> None:
    """时间表达不能与地区过滤值拼接。"""

    result = parse_query_semantics("统计 2025 年 3 月华北地区的销售额")
    assert result["time_expressions"] == ["2025 年 3 月"]
    assert result["filter_values"] == {"dim_region.region_name": ["华北"]}


@pytest.mark.parametrize(
    ("query", "expected_filters"),
    [
        (
            "统计华北地区美的品牌的销售额",
            {
                "dim_region.region_name": ["华北"],
                "dim_product.brand": ["美的"],
            },
        ),
        (
            "统计华东地区食品饮料品类的销量",
            {
                "dim_region.region_name": ["华东"],
                "dim_product.category": ["食品饮料"],
            },
        ),
        (
            "统计黄金会员购买苹果品牌的销售额",
            {
                "dim_customer.member_level": ["黄金"],
                "dim_product.brand": ["苹果"],
            },
        ),
        (
            "统计女性客户购买鞋靴品类的销售额",
            {
                "dim_customer.gender": ["女"],
                "dim_product.category": ["鞋靴"],
            },
        ),
    ],
)
def test_parse_multiple_explicit_domain_filters(
    query: str,
    expected_filters: dict[str, list[str]],
) -> None:
    """多个字段标签应分别绑定离自己最近的取值。"""

    assert parse_query_semantics(query)["filter_values"] == expected_filters


@pytest.mark.parametrize(
    "query",
    [
        "所有订单合计卖出多少件商品",
        "统计 2025 年 2 月 10 日到 20 日的销售额",
        "找出 GMV 排名第一的地区",
        "哪个品类销量排名最后",
        "统计销售额超过一万元的品牌",
        "哪些品牌的 GMV 大于 10000 元",
        "美的在华北卖了多少钱",
    ],
)
def test_non_filter_phrases_do_not_create_explicit_filters(query: str) -> None:
    """日期、排名、Having 和无字段标签表达不应伪造成显式过滤值。"""

    assert parse_query_semantics(query)["filter_values"] == {}


def test_time_grouping_excludes_time_filter_dimensions() -> None:
    """按天统计月份数据时只按天分组，年月属于时间过滤。"""

    result = parse_query_semantics("按天统计 2025 年 3 月的销售额")
    assert result["group_by_columns"] == ["dim_date.day"]


@pytest.mark.parametrize(
    "query",
    [
        "男性和女性客户分别下了多少单",
        "各省男女客户分别贡献了多少 GMV",
    ],
)
def test_gender_comparison_is_grouping_not_filter(query: str) -> None:
    """同时提及男女时表示性别分组，不是只过滤其中一个值。"""

    assert parse_query_semantics(query)["filter_values"] == {}


def test_member_value_uses_nearest_possessive_segment() -> None:
    """隐式地区不能与后面的会员等级值拼接。"""

    result = parse_query_semantics("华东的白银会员一共下了多少单")
    assert result["filter_values"] == {"dim_customer.member_level": ["白银"]}
