import asyncio

from app.agent.nodes.recall_value import (
    build_grounding_candidates,
    evaluate_grounding,
    recall_value,
)
from app.agent.query_semantics import parse_query_semantics
from app.entities.value_info import ValueInfo


def test_build_grounding_candidates_only_uses_explicit_filters() -> None:
    """分析维度和指标不能进入字段值 Grounding。"""

    semantics = parse_query_semantics("按会员等级和商品品类统计销量")
    assert build_grounding_candidates(semantics) == {}


def test_build_grounding_candidates_preserves_column_domain() -> None:
    """明确品牌值必须保留与字段列的绑定关系。"""

    semantics = parse_query_semantics("统计火星牌商品的销售额")
    assert build_grounding_candidates(semantics) == {
        "dim_product.brand": ["火星牌"]
    }


def test_irrelevant_fuzzy_values_do_not_satisfy_grounding() -> None:
    """同域存在相似值不代表用户指定值真实存在。"""

    expected = {"dim_product.brand": ["火星牌"]}
    recalled = [
        ValueInfo(id="brand.samsung", value="三星", column_id="dim_product.brand"),
        ValueInfo(id="brand.midea", value="美的", column_id="dim_product.brand"),
    ]
    result = evaluate_grounding(expected, recalled)
    assert result.matched_values == []
    assert result.missing_values == ["火星牌"]


def test_grounding_matches_values_within_their_column() -> None:
    """字段值必须在对应列内精确命中。"""

    expected = {"dim_region.region_name": ["华北", "火星"]}
    recalled = [
        ValueInfo(id="region.north", value="华北", column_id="dim_region.region_name"),
        ValueInfo(id="brand.north", value="火星", column_id="dim_product.brand"),
    ]
    result = evaluate_grounding(expected, recalled)
    assert result.matched_values == ["华北"]
    assert result.missing_values == ["火星"]


class _ExactValueRepository:
    def __init__(self) -> None:
        self.queries: list[list[str]] = []

    async def search_exact_values(self, values: list[str]) -> list[ValueInfo]:
        self.queries.append(values)
        return [
            ValueInfo(
                id="brand.midea",
                value="美的",
                column_id="dim_product.brand",
            )
        ]


class _RuntimeWithRepository:
    def __init__(self, repository: _ExactValueRepository) -> None:
        self.context = {"value_es_repository": repository}
        self.events: list[dict] = []
        self.stream_writer = self.events.append


def test_recall_value_keeps_exact_enrichment_without_explicit_filters() -> None:
    """无显式过滤时仍应召回隐式已知值，但跳过校验和 LLM 扩展。"""

    repository = _ExactValueRepository()
    runtime = _RuntimeWithRepository(repository)
    state = {
        "query": "美的在华北卖了多少钱",
        "keywords": ["美的", "华北", "卖了多少钱"],
        "query_semantics": parse_query_semantics("美的在华北卖了多少钱"),
    }
    result = asyncio.run(recall_value(state, runtime))
    assert [value.value for value in result["retrieved_value_infos"]] == ["美的"]
    assert result["grounding_validation_skipped"] is True
    assert result["value_keyword_expansion_skipped"] is True
    assert result["grounding_skip_reason"] == "no_explicit_filter_values"
    assert result["value_exact_search_metrics"] == {
        "explicit_candidate_count": 0,
        "implicit_candidate_count": 3,
        "explicit_call_count": 0,
        "implicit_call_count": 1,
        "total_call_count": 1,
    }
    assert result["value_fuzzy_search_skipped"] is True
    assert repository.queries == [["美的", "华北", "卖了多少钱"]]
    assert runtime.events[-1]["status"] == "success"


def test_recall_value_returns_empty_enrichment_when_exact_lookup_misses() -> None:
    """隐式值 exact 未命中时应继续生成 SQL，不得误报 Grounding 失败。"""

    class _EmptyRepository(_ExactValueRepository):
        async def search_exact_values(self, values: list[str]) -> list[ValueInfo]:
            self.queries.append(values)
            return []

    repository = _EmptyRepository()
    runtime = _RuntimeWithRepository(repository)
    state = {
        "query": "按会员等级和商品品类统计销量",
        "keywords": ["会员等级", "商品品类", "销量"],
        "query_semantics": parse_query_semantics("按会员等级和商品品类统计销量"),
    }
    result = asyncio.run(recall_value(state, runtime))
    assert result == {
        "retrieved_value_infos": [],
        "grounding_validation_skipped": True,
        "value_keyword_expansion_skipped": True,
        "grounding_skip_reason": "no_explicit_filter_values",
        "value_exact_search_metrics": {
            "explicit_candidate_count": 0,
            "implicit_candidate_count": 3,
            "explicit_call_count": 0,
            "implicit_call_count": 1,
            "total_call_count": 1,
        },
        "value_fuzzy_search_skipped": True,
    }


def test_recall_value_queries_explicit_values_before_implicit_keywords() -> None:
    """显式过滤值必须独立召回，不能被隐式关键词挤出结果上限。"""

    class _PrioritizedRepository(_ExactValueRepository):
        async def search_exact_values(self, values: list[str]) -> list[ValueInfo]:
            self.queries.append(values)
            if values == ["美的"]:
                return [
                    ValueInfo(
                        id="brand.midea",
                        value="美的",
                        column_id="dim_product.brand",
                    )
                ]
            return [
                ValueInfo(
                    id="region.north",
                    value="华北",
                    column_id="dim_region.region_name",
                )
            ]

    repository = _PrioritizedRepository()
    runtime = _RuntimeWithRepository(repository)
    query = "统计美的品牌在华北的销售额"
    state = {
        "query": query,
        "keywords": ["美的", "华北", "销售额"],
        "query_semantics": parse_query_semantics(query),
    }

    result = asyncio.run(recall_value(state, runtime))

    assert repository.queries == [["美的"], ["华北", "销售额"]]
    assert {value.id for value in result["retrieved_value_infos"]} == {
        "brand.midea",
        "region.north",
    }
    assert result["grounding_validation_skipped"] is False
    assert result["value_exact_search_metrics"] == {
        "explicit_candidate_count": 1,
        "implicit_candidate_count": 2,
        "explicit_call_count": 1,
        "implicit_call_count": 1,
        "total_call_count": 2,
    }


def test_recall_value_keeps_explicit_grounding_when_implicit_enrichment_fails() -> None:
    """隐式 enrichment 失败不能丢弃已命中的显式 Grounding 证据。"""

    class _ImplicitFailureRepository(_ExactValueRepository):
        async def search_exact_values(self, values: list[str]) -> list[ValueInfo]:
            self.queries.append(values)
            if values == ["美的"]:
                return [
                    ValueInfo(
                        id="brand.midea",
                        value="美的",
                        column_id="dim_product.brand",
                    )
                ]
            raise TimeoutError("隐式字段值召回超时")

    repository = _ImplicitFailureRepository()
    runtime = _RuntimeWithRepository(repository)
    query = "统计美的品牌在华北的销售额"
    state = {
        "query": query,
        "keywords": ["美的", "华北", "销售额"],
        "query_semantics": parse_query_semantics(query),
    }

    result = asyncio.run(recall_value(state, runtime))

    assert [value.id for value in result["retrieved_value_infos"]] == ["brand.midea"]
    assert result["grounding_validation_skipped"] is False
    assert "隐式字段值召回" in result["recall_value_warning"]
