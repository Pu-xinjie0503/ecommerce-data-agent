import pytest

from app.agent.nodes.filter_table import filter_tables_by_semantics
from app.agent.query_semantics import parse_query_semantics


def _column(name: str, role: str) -> dict:
    return {
        "name": name,
        "type": "varchar",
        "role": role,
        "examples": [],
        "description": name,
        "alias": [],
    }


TABLE_INFOS = [
    {
        "name": "fact_order",
        "role": "fact",
        "description": "订单事实表",
        "columns": [
            _column("order_id", "primary_key"),
            _column("customer_id", "foreign_key"),
            _column("product_id", "foreign_key"),
            _column("date_id", "foreign_key"),
            _column("region_id", "foreign_key"),
            _column("order_amount", "measure"),
            _column("order_quantity", "measure"),
        ],
    },
    {
        "name": "dim_product",
        "role": "dim",
        "description": "商品维度表",
        "columns": [
            _column("product_id", "primary_key"),
            _column("product_name", "dimension"),
            _column("category", "dimension"),
            _column("brand", "dimension"),
        ],
    },
    {
        "name": "dim_customer",
        "role": "dim",
        "description": "客户维度表",
        "columns": [
            _column("customer_id", "primary_key"),
            _column("gender", "dimension"),
            _column("member_level", "dimension"),
        ],
    },
    {
        "name": "dim_region",
        "role": "dim",
        "description": "地区维度表",
        "columns": [
            _column("region_id", "primary_key"),
            _column("province", "dimension"),
            _column("region_name", "dimension"),
        ],
    },
    {
        "name": "dim_date",
        "role": "dim",
        "description": "日期维度表",
        "columns": [
            _column("date_id", "primary_key"),
            _column("year", "dimension"),
            _column("quarter", "dimension"),
            _column("month", "dimension"),
            _column("day", "dimension"),
        ],
    },
]


def _columns_of(table_infos: list[dict], table_name: str) -> set[str]:
    table = next(table for table in table_infos if table["name"] == table_name)
    return {column["name"] for column in table["columns"]}


@pytest.mark.parametrize(
    ("query", "required_by_table"),
    [
        (
            "按商品统计销售额",
            {
                "fact_order": {"order_amount"},
                "dim_product": {"product_id", "product_name"},
            },
        ),
        (
            "不同会员层级在各品类买了多少件",
            {
                "fact_order": {"order_quantity"},
                "dim_customer": {"customer_id", "member_level"},
                "dim_product": {"product_id", "category"},
            },
        ),
        (
            "各省男女客户分别贡献了多少 GMV",
            {
                "fact_order": {"order_amount"},
                "dim_region": {"region_id", "province"},
                "dim_customer": {"customer_id", "gender"},
            },
        ),
        (
            "查询地区季度维度的 GMV、销售件数和订单量",
            {
                "fact_order": {"order_id", "order_amount", "order_quantity"},
                "dim_region": {"region_id", "region_name"},
                "dim_date": {"date_id", "quarter"},
            },
        ),
    ],
)
def test_filter_tables_keeps_semantic_business_columns(
    query: str,
    required_by_table: dict[str, set[str]],
) -> None:
    """字段过滤必须保留语义要求的展示维度和度量字段。"""

    filtered = filter_tables_by_semantics(
        table_infos=TABLE_INFOS,
        query_semantics=parse_query_semantics(query),
        metric_infos=[],
        retrieved_value_infos=[],
    )
    for table_name, required_columns in required_by_table.items():
        assert required_columns <= _columns_of(filtered, table_name)


@pytest.mark.parametrize(
    ("query", "required_columns"),
    [
        ("统计 2025 年 3 月销售额", {"date_id", "year", "month"}),
        ("统计 2025 年第一季度订单数", {"date_id", "year", "quarter"}),
        ("统计 2025 年 2 月 10 日到 20 日销售额", {"date_id"}),
    ],
)
def test_filter_tables_keeps_columns_required_by_time_expressions(
    query: str,
    required_columns: set[str],
) -> None:
    """时间过滤所需日期列不能在 SQL 生成前被移除。"""

    filtered = filter_tables_by_semantics(
        table_infos=TABLE_INFOS,
        query_semantics=parse_query_semantics(query),
        metric_infos=[],
        retrieved_value_infos=[],
    )

    assert required_columns <= _columns_of(filtered, "dim_date")
