import pytest

from app.agent.nodes.clarify_query import check_query_clarification


@pytest.mark.parametrize(
    "query",
    [
        "订单数最多的三个品牌是什么",
        "按订单量找出排名前三的品牌",
        "查询品牌订单数 Top 3",
    ],
)
def test_explicit_ranking_metric_does_not_clarify(query: str) -> None:
    """排名查询已经提供指标时不应再次要求澄清。"""

    assert check_query_clarification(query) is None


def test_ambiguous_ranking_still_clarifies() -> None:
    """只有排名目标但缺少指标时仍应澄清。"""

    result = check_query_clarification("哪个品类表现最好")
    assert result is not None
    assert result.clarification_type == "metric_ambiguity"


def test_ambiguous_recent_period_still_clarifies() -> None:
    """未给出明确范围的最近时间表达仍应澄清。"""

    result = check_query_clarification("统计最近一段时间的销售额")
    assert result is not None
    assert result.clarification_type == "time_range_ambiguity"
