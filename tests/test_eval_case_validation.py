"""分层评测集格式、规模与隔离校验测试。"""

from pathlib import Path

import pytest

from eval.case_loader import (
    EvalCaseConfigError,
    load_case_file,
    normalize_case_config,
    validate_cases,
    validate_intent_isolation,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_normalize_case_config_expands_intent_queries():
    """一个意图的三种表达应展开为独立 Query，并继承 Gold SQL。"""

    cases = normalize_case_config(
        {
            "intents": [
                {
                    "intent_id": "sales-by-region",
                    "category": "multi_join",
                    "gold_sql": "SELECT 1 AS sales",
                    "queries": [
                        {"id": "q1", "query": "统计华北销售额"},
                        {"id": "q2", "query": "华北卖了多少钱"},
                    ],
                }
            ]
        }
    )

    assert [case["id"] for case in cases] == ["q1", "q2"]
    assert all(case["intent_id"] == "sales-by-region" for case in cases)
    assert all(case["gold_sql"] == "SELECT 1 AS sales" for case in cases)
    assert [case["paraphrase_id"] for case in cases] == [1, 2]


def test_validate_cases_requires_gold_sql_for_normal_query():
    """普通问数缺少 Gold SQL 时必须拒绝运行。"""

    cases = [
        {
            "id": "q1",
            "query": "统计销售额",
            "intent_id": "sales",
            "category": "simple",
        }
    ]

    with pytest.raises(EvalCaseConfigError, match="gold_sql"):
        validate_cases(cases, strict=True)


def test_validate_cases_allows_deterministic_branch_without_gold_sql():
    """安全拦截等确定性分支无需执行 Gold SQL。"""

    cases = [
        {
            "id": "unsafe-1",
            "query": "删除订单表",
            "intent_id": "unsafe-write",
            "category": "unsafe",
            "expected_blocked": True,
            "expected_error_type": "unsafe_query",
        }
    ]

    validate_cases(cases, strict=True)


def test_validate_intent_isolation_rejects_overlap():
    """开发集和隔离测试集不能共享业务意图。"""

    dev_cases = [{"intent_id": "sales", "id": "dev-1"}]
    test_cases = [{"intent_id": "sales", "id": "test-1"}]

    with pytest.raises(EvalCaseConfigError, match="sales"):
        validate_intent_isolation(dev_cases, test_cases)


def test_validate_cases_rejects_duplicate_query_ids():
    """重复 ID 会破坏 Trace 与 Case 的一一对应关系。"""

    cases = [
        {"id": "dup", "query": "问题一"},
        {"id": "dup", "query": "问题二"},
    ]

    with pytest.raises(EvalCaseConfigError, match="重复"):
        validate_cases(cases, strict=False)


def test_layered_datasets_have_expected_scale_and_isolated_intents():
    """正式数据集应稳定保持 40 个隔离意图和 120 条自然语言表达。"""

    dev_cases = load_case_file(PROJECT_ROOT / "eval" / "cases_dev.yaml")
    test_cases = load_case_file(PROJECT_ROOT / "eval" / "cases_test.yaml")

    validate_intent_isolation(dev_cases, test_cases)
    assert len(dev_cases) == 90
    assert len(test_cases) == 30

    dev_intents = {case["intent_id"] for case in dev_cases}
    test_intents = {case["intent_id"] for case in test_cases}
    assert len(dev_intents) == 30
    assert len(test_intents) == 10
    assert len(dev_intents | test_intents) == 40

    all_ids = [case["id"] for case in [*dev_cases, *test_cases]]
    assert len(all_ids) == len(set(all_ids)) == 120
