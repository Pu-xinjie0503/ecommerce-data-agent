# Schema-Driven Query Semantics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变现有 LangGraph 拓扑和三路并行召回的前提下，用一套 Schema 驱动的共享语义规则替换澄清、字段值 Grounding、表字段过滤中的松散规则，消除正常查询误拦截并稳定保留 SQL 所需业务维度。

**Architecture:** 新增纯 Python 模块 `app/agent/query_semantics.py`，从 `conf/meta_config.yaml` 的字段/指标名称与别名构建领域词典，将 Query 解析为维度、分组字段、明确过滤值、指标、时间、排序和 Top N 等结构化提示。现有 `clarify_query` 在链路前部生成一次解析结果并写入 `DataAgentState`，`recall_value` 和 `filter_table` 只消费该结果；Graph 节点、召回并行关系、ES/Qdrant 接口和 SQL Prompt 暂不改变。

**Tech Stack:** Python 3.12、TypedDict、OmegaConf、LangGraph、Elasticsearch、pytest、现有 Trace/Eval 框架。

---

## 1. 范围与基线

### 本计划解决的问题

- `test_003_1`：把“按会员等级”“商品”误判成品类过滤值。
- `test_006_1`：把“订单数最多的三个”误判成品牌过滤值。
- `test_006_2`：已有“订单量”指标时仍触发排名指标澄清。
- `test_007_3`：把“不同”误判成地区过滤值。
- `test_009_1`～`test_009_3`：无法稳定识别“火星牌”“品牌为火星牌”中的明确品牌过滤值。
- `test_002_1`、`test_002_3`：`product_name` 在 SQL 生成前被过滤，只剩 `product_id`。
- `test_003_2`、`test_003_3`：`member_level` 被过滤，只剩 `customer_id`。
- `test_004_2`：无法把“各省”映射到 `dim_region.province`。
- `test_005_3`：无法把“地区季度维度”识别为 `region_name + quarter` 分组。

### 明确不在本计划中的内容

- 不新增 LLM 语义解析调用。
- 不改变 LangGraph 节点或边。
- 不修改 `prompts/generate_sql.prompt`，先隔离验证规则层收益。
- 不修改 `eval/cases_test.yaml`，确保 baseline-v3 与 candidate 使用同一测试集哈希。
- 不处理 SQL 修正循环上限；该问题单独制定计划，避免把准确率与长尾优化混为一个变量。
- 不承诺适配任意业务 Schema，仅覆盖当前电商问数领域与现有元数据结构。

### 固定 baseline

- Query Pass Rate：56.67%（17/30）。
- Execution Accuracy：52.38%（11/21）。
- API Branch Accuracy：70%（35/50）。
- 正常 API Case 的 Grounding 误拦截：15/25。
- API 技术错误率：0%。

---

## 2. 文件结构

### 新建文件

- `app/agent/query_semantics.py`：领域词典加载、最长别名匹配、语义分类和结构化解析；不得访问 LLM、ES、Qdrant 或数据库。
- `tests/test_query_semantics.py`：解析器表驱动测试，覆盖分组、过滤、指标、排序、Top N、时间和否定样例。
- `tests/test_clarify_query_semantics.py`：澄清节点基于统一语义的回归测试。
- `tests/test_recall_value_semantics.py`：字段值候选与 Grounding 判定的纯函数/仓储桩测试。
- `tests/test_filter_table_semantics.py`：字段保留规则测试，断言业务字段不会被主外键替代。
- `tests/test_trace_query_semantics.py`：Trace 中语义解析结果的摘要与截断测试。

### 修改文件

- `conf/meta_config.yaml`：补齐当前 Schema 的领域同义词，不写完整查询句式。
- `app/agent/state.py`：增加 `QuerySemanticsState` 及 `query_semantics` 字段。
- `app/agent/nodes/clarify_query.py`：先解析语义，再基于解析结果判断澄清。
- `app/agent/nodes/recall_value.py`：删除自行猜测过滤值的规则，仅 Grounding `filter_values`。
- `app/agent/nodes/filter_table.py`：按结构化维度、过滤字段和指标依赖保留表字段。
- `app/observability/trace_manager.py`：在节点输入/输出摘要中记录 `query_semantics`。
- `docs/evaluation/2026-08-17-evidence-v2-baseline.md`：用户完成 candidate 后补充前后指标与失败 Case 迁移，不在代码实现阶段提前写结论。

---

### Task 1: 定义语义状态契约

**Files:**
- Modify: `app/agent/state.py`
- Test: `tests/test_query_semantics.py`

- [ ] **Step 1: 写入失败的状态契约测试**

测试通过 `typing.get_type_hints` 验证统一字段存在，避免各节点自行发明 Key：

```python
from typing import get_type_hints

from app.agent.state import DataAgentState, QuerySemanticsState


def test_query_semantics_state_contract() -> None:
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
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `uv run python -m pytest tests/test_query_semantics.py::test_query_semantics_state_contract -q`

Expected: FAIL，提示无法导入 `QuerySemanticsState`。

- [ ] **Step 3: 增加最小 TypedDict 定义**

在 `app/agent/state.py` 中定义：

```python
class QuerySemanticsState(TypedDict):
    """当前电商领域内的结构化查询语义。"""

    dimension_columns: list[str]
    group_by_columns: list[str]
    filter_values: dict[str, list[str]]
    metric_terms: list[str]
    time_expressions: list[str]
    order_direction: Literal["asc", "desc"] | None
    limit: int | None
    parse_evidence: list[str]
```

并在 `DataAgentState` 中增加：

```python
query_semantics: QuerySemanticsState
```

- [ ] **Step 4: 运行契约测试**

Run: `uv run python -m pytest tests/test_query_semantics.py::test_query_semantics_state_contract -q`

Expected: `1 passed`。

- [ ] **Step 5: 提交状态契约**

```bash
git add app/agent/state.py tests/test_query_semantics.py
git commit -m "feat: 定义查询语义状态契约"
```

---

### Task 2: 建立 Schema 驱动的领域词典

**Files:**
- Create: `app/agent/query_semantics.py`
- Modify: `conf/meta_config.yaml`
- Modify: `tests/test_query_semantics.py`

- [ ] **Step 1: 编写最长别名匹配失败测试**

测试要求字段名称、英文名和别名统一映射到列 ID，并优先匹配长词：

```python
import pytest

from app.agent.query_semantics import find_dimension_mentions


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("按商品统计销售额", ["dim_product.product_name"]),
        ("按商品品类统计销量", ["dim_product.category"]),
        ("不同会员层级的销量", ["dim_customer.member_level"]),
        ("各省男女客户贡献的 GMV", ["dim_region.province", "dim_customer.gender"]),
        ("地区季度维度", ["dim_region.region_name", "dim_date.quarter"]),
    ],
)
def test_find_dimension_mentions(query: str, expected: list[str]) -> None:
    assert find_dimension_mentions(query) == expected
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `uv run python -m pytest tests/test_query_semantics.py::test_find_dimension_mentions -q`

Expected: FAIL，提示模块或函数不存在。

- [ ] **Step 3: 补充元数据别名**

只在 `conf/meta_config.yaml` 中增加领域名词，不加入“按……统计”这类完整 Case：

```yaml
# dim_region.province
alias: [省份, 省, 所在省份]

# dim_customer.member_level
alias: [会员等级, 用户等级, 会员层级, 用户层级]

# dim_product.product_name
alias: [商品名称, 产品名称, 商品, 产品, 单品]

# dim_product.category
alias: [商品类别, 商品品类, 品类, 分类, 类目]

# fact_order.order_quantity
alias: [销量, 购买数量, 件数, 销售件数]
```

其中“商品品类”必须在“商品”之前按长度匹配，避免错误映射到 `product_name`。

- [ ] **Step 4: 实现缓存词典与最长匹配**

`app/agent/query_semantics.py` 的公开边界与词典构建逻辑：

```python
import re
from functools import lru_cache
from pathlib import Path

from app.conf.meta_config import load_meta_config
from app.agent.state import QuerySemanticsState


@lru_cache(maxsize=1)
def build_dimension_alias_index() -> tuple[tuple[str, str], ...]:
    """从元数据构建按别名长度降序排列的维度词典。"""
    config = load_meta_config(Path(__file__).parents[2] / "conf" / "meta_config.yaml")
    entries: set[tuple[str, str]] = set()
    for table in config.tables:
        for column in table.columns:
            if column.role != "dimension":
                continue
            column_id = f"{table.name}.{column.name}"
            for alias in [column.name, *column.alias]:
                normalized_alias = alias.strip().lower()
                if normalized_alias:
                    entries.add((normalized_alias, column_id))
    return tuple(sorted(entries, key=lambda item: (-len(item[0]), item[0], item[1])))


def find_dimension_mentions(query: str) -> list[str]:
    """返回 Query 明确提及的业务维度列 ID，保持原文顺序并去重。"""
    normalized_query = query.lower()
    occupied: set[int] = set()
    matches: list[tuple[int, str]] = []
    for alias, column_id in build_dimension_alias_index():
        for match in re.finditer(re.escape(alias), normalized_query):
            positions = set(range(match.start(), match.end()))
            if positions & occupied:
                continue
            occupied.update(positions)
            matches.append((match.start(), column_id))
    result: list[str] = []
    for _, column_id in sorted(matches):
        if column_id not in result:
            result.append(column_id)
    return result
```

实现约束：

- 仅加载 `role=dimension` 的字段，主键/外键不得作为业务维度别名命中结果。
- 同一文本区间只接受最长别名，例如“商品品类”不能同时命中“商品”。
- 同一列多次出现只保留一次。
- 词典只在进程内构建一次，不在每个请求重复读取 YAML。

- [ ] **Step 5: 运行维度词典测试**

Run: `uv run python -m pytest tests/test_query_semantics.py::test_find_dimension_mentions -q`

Expected: 全部 PASS。

- [ ] **Step 6: 提交领域词典**

```bash
git add app/agent/query_semantics.py conf/meta_config.yaml tests/test_query_semantics.py
git commit -m "feat: 建立Schema驱动领域词典"
```

---

### Task 3: 实现确定性的查询语义解析

**Files:**
- Modify: `app/agent/query_semantics.py`
- Modify: `tests/test_query_semantics.py`

- [ ] **Step 1: 编写正常查询语义表驱动测试**

至少覆盖 baseline 中的不同语法形态：

```python
import pytest

from app.agent.query_semantics import parse_query_semantics


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
    result = parse_query_semantics(query)
    assert result["group_by_columns"] == group_by
    assert result["filter_values"] == filters
    assert result["metric_terms"] == metrics
    assert result["order_direction"] == direction
    assert result["limit"] == limit
```

- [ ] **Step 2: 编写过滤值与时间隔离测试**

```python
@pytest.mark.parametrize(
    ("query", "expected_filters"),
    [
        ("统计 2025 年 3 月华北地区的销售额", {"dim_region.region_name": ["华北"]}),
        ("对比华北和火星地区的销售额", {"dim_region.region_name": ["华北", "火星"]}),
        ("统计火星牌商品的销售额", {"dim_product.brand": ["火星牌"]}),
        ("火星牌一共卖了多少钱", {"dim_product.brand": ["火星牌"]}),
        ("查询品牌为火星牌的 GMV", {"dim_product.brand": ["火星牌"]}),
        ("按会员等级和商品品类统计销量", {}),
        ("查询不同地区的平均订单金额", {}),
        ("订单数最多的三个品牌是什么", {}),
    ],
)
def test_parse_explicit_filter_values(query: str, expected_filters: dict[str, list[str]]) -> None:
    assert parse_query_semantics(query)["filter_values"] == expected_filters
```

- [ ] **Step 3: 运行测试并确认失败**

Run: `uv run python -m pytest tests/test_query_semantics.py -q`

Expected: 新增解析用例 FAIL。

- [ ] **Step 4: 按固定优先级实现解析器**

解析顺序必须固定，后面的步骤只能消费前面已识别的文本区间：

1. 规范化空白与大小写，但保留原文索引。
2. 提取明确时间表达，例如 `2025 年 3 月`、`Q1`、`最近 30 天`。
3. 识别指标词：`GMV/销售额`、`销量/件数`、`订单数/订单量`、`AOV/平均订单金额`。
4. 识别排序和 Top N：`最多/最高/Top 3/前三/三个`。
5. 使用最长别名匹配识别业务维度。
6. 使用分组语法识别 Group By：前缀 `按/各/每个/不同`，后缀 `维度/组合/分别`，以及多维度连接词 `和/与/及`。
7. 仅从未被时间、指标、排序、Top N、分组占用的文本中提取过滤值。

同一任务内定义以下私有数据结构与辅助函数，禁止让节点层直接操作正则匹配结果：

```python
@dataclass(frozen=True)
class SemanticSpan:
    start: int
    end: int
    text: str
    value: str
    evidence: str


@dataclass(frozen=True)
class RankingSemantics:
    direction: Literal["asc", "desc"] | None
    limit: int | None
    spans: tuple[SemanticSpan, ...]
```

- `normalize_query(query)`：只折叠空白和大小写，保留可回溯到原文的字符顺序。
- `extract_time_expressions(query)`：返回带起止位置的时间表达。
- `extract_metric_terms(query)`：按最长词优先返回规范指标名及原文位置。
- `extract_ranking(query, metric_spans)`：解析升降序和阿拉伯/中文 Top N。
- `extract_dimension_mentions(query)`：在最长别名匹配基础上返回 `SemanticSpan`。
- `classify_group_by_columns(query, dimension_spans)`：只对分组触发语法覆盖的维度返回列 ID。
- `extract_filter_values(query, dimension_spans, excluded_spans, group_by_columns)`：跳过已占用区间并返回 `dict[column_id, values]`。
- `dedupe_span_values(spans)`：按原文位置稳定去重规范值。
- `build_parse_evidence(dimension_spans, group_by_columns, filter_values, metric_spans, ranking, time_spans)`：将每次命中的规则转换为中文可读证据。

公开函数保持单一入口，并始终返回完整字段集合：

```python
def parse_query_semantics(query: str) -> QuerySemanticsState:
    """将电商问数 Query 解析为可复用的确定性语义提示。"""
    normalized_query = normalize_query(query)
    time_spans = extract_time_expressions(normalized_query)
    metric_spans = extract_metric_terms(normalized_query)
    ranking = extract_ranking(normalized_query, metric_spans)
    dimension_spans = extract_dimension_mentions(normalized_query)
    group_by_columns = classify_group_by_columns(normalized_query, dimension_spans)
    filter_values = extract_filter_values(
        normalized_query,
        dimension_spans=dimension_spans,
        excluded_spans=[*time_spans, *metric_spans, *ranking.spans],
        group_by_columns=group_by_columns,
    )
    return QuerySemanticsState(
        dimension_columns=dedupe_span_values(dimension_spans),
        group_by_columns=group_by_columns,
        filter_values=filter_values,
        metric_terms=dedupe_span_values(metric_spans),
        time_expressions=[span.text for span in time_spans],
        order_direction=ranking.direction,
        limit=ranking.limit,
        parse_evidence=build_parse_evidence(
            dimension_spans=dimension_spans,
            group_by_columns=group_by_columns,
            filter_values=filter_values,
            metric_spans=metric_spans,
            ranking=ranking,
            time_spans=time_spans,
        ),
    )
```

过滤值规则必须双向支持：

- 值在字段前：`华北地区`、`美的品牌`。
- 值在字段后：`品牌为美的`、`地区是华北`。
- 当前电商领域品牌简称：`火星牌商品`、`火星牌一共卖了多少钱`。
- 多值连接：`华北和火星地区`。

`parse_evidence` 记录可检查的规则证据，例如：

```python
[
    "维度别名: 会员层级 -> dim_customer.member_level",
    "分组触发: 不同",
    "指标别名: 件 -> order_quantity",
]
```

- [ ] **Step 5: 运行解析器测试**

Run: `uv run python -m pytest tests/test_query_semantics.py -q`

Expected: 全部 PASS。

- [ ] **Step 6: 增加边界与否定用例**

必须验证以下内容不会变成过滤值：

```python
@pytest.mark.parametrize(
    "query",
    [
        "按品牌统计订单数",
        "各地区分别卖了多少钱",
        "每个商品的 GMV",
        "不同会员层级的销售件数",
        "品牌订单数 Top 3",
        "查询 2025 年第一季度各大区 GMV",
    ],
)
def test_analysis_phrases_are_not_filter_values(query: str) -> None:
    assert parse_query_semantics(query)["filter_values"] == {}
```

- [ ] **Step 7: 提交语义解析器**

```bash
git add app/agent/query_semantics.py tests/test_query_semantics.py
git commit -m "feat: 实现电商查询语义解析"
```

---

### Task 4: 统一澄清判断

**Files:**
- Modify: `app/agent/nodes/clarify_query.py`
- Create: `tests/test_clarify_query_semantics.py`

- [ ] **Step 1: 编写澄清回归测试**

```python
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
    assert check_query_clarification(query) is None


def test_ambiguous_ranking_still_clarifies() -> None:
    result = check_query_clarification("哪个品类表现最好")
    assert result is not None
    assert result.clarification_type == "metric_ambiguity"
```

- [ ] **Step 2: 运行测试并确认至少一条失败**

Run: `uv run python -m pytest tests/test_clarify_query_semantics.py -q`

Expected: “订单量排名前三”用例 FAIL。

- [ ] **Step 3: 让澄清逻辑消费统一语义**

调整接口，保留对旧调用的兼容：

```python
def check_query_clarification(
    query: str,
    query_semantics: QuerySemanticsState | None = None,
) -> ClarificationResult | None:
    semantics = query_semantics or parse_query_semantics(query)
    normalized_query = normalize_query(query)
    if has_ranking_intent(normalized_query) and not semantics["metric_terms"]:
        return ClarificationResult(
            clarification_type="metric_ambiguity",
            clarification_question="你想按销售额、销量，还是订单数来判断“最好”？",
            clarification_options=["销售额", "销量", "订单数"],
        )
    if has_recent_intent(normalized_query) and not semantics["time_expressions"]:
        return ClarificationResult(
            clarification_type="time_range_ambiguity",
            clarification_question="你说的“最近”是指最近 7 天、最近 30 天，还是最近一个自然月？",
            clarification_options=["最近7天", "最近30天", "最近一个自然月"],
        )
    if is_dimension_overview(normalized_query, semantics) and not semantics["metric_terms"]:
        return ClarificationResult(
            clarification_type="metric_ambiguity",
            clarification_question="你想按销售额、销量，还是订单数来看各维度情况？",
            clarification_options=["销售额", "销量", "订单数"],
        )
    if is_broad_analysis(normalized_query, semantics):
        return ClarificationResult(
            clarification_type="broad_analysis_request",
            clarification_question="你希望从哪个维度查看？例如按大区、商品品类、品牌或会员等级。",
            clarification_options=["按大区", "按商品品类", "按品牌", "按会员等级"],
        )
    return None
```

判断原则：

- 排名词存在但 `metric_terms` 为空才澄清指标。
- `最近/近期` 存在但 `time_expressions` 没有明确范围才澄清时间。
- 维度概况类查询没有指标才澄清。
- 不再维护与语义解析器重复的 `EXPLICIT_METRIC_WORDS`、`FILTER_WORDS`。

`clarify_query` 返回状态时同时写入：

```python
result["query_semantics"] = semantics
```

- [ ] **Step 4: 运行澄清测试和现有安全/评测单测**

Run: `uv run python -m pytest tests/test_clarify_query_semantics.py tests/test_eval_case_validation.py -q`

Expected: 全部 PASS。

- [ ] **Step 5: 提交澄清集成**

```bash
git add app/agent/nodes/clarify_query.py tests/test_clarify_query_semantics.py
git commit -m "fix: 统一查询澄清语义判断"
```

---

### Task 5: 让 Grounding 只验证明确过滤值

**Files:**
- Modify: `app/agent/nodes/recall_value.py`
- Create: `tests/test_recall_value_semantics.py`

- [ ] **Step 1: 编写候选范围失败测试**

将候选构造拆成纯函数，先验证正常分析词不再进入 ES 候选：

```python
from app.agent.nodes.recall_value import build_grounding_candidates


def test_build_grounding_candidates_only_uses_explicit_filters() -> None:
    semantics = {
        "dimension_columns": ["dim_customer.member_level", "dim_product.category"],
        "group_by_columns": ["dim_customer.member_level", "dim_product.category"],
        "filter_values": {},
        "metric_terms": ["order_quantity"],
        "time_expressions": [],
        "order_direction": None,
        "limit": None,
        "parse_evidence": [],
    }
    assert build_grounding_candidates(semantics) == {}


def test_build_grounding_candidates_preserves_domain() -> None:
    semantics = {
        "dimension_columns": ["dim_product.brand"],
        "group_by_columns": [],
        "filter_values": {"dim_product.brand": ["火星牌"]},
        "metric_terms": ["gmv"],
        "time_expressions": [],
        "order_direction": None,
        "limit": None,
        "parse_evidence": [],
    }
    assert build_grounding_candidates(semantics) == {
        "dim_product.brand": ["火星牌"]
    }
```

- [ ] **Step 2: 编写精确校验失败测试**

测试“模糊召回有结果”不等于“用户指定值已命中”：

```python
from app.entities.value_info import ValueInfo
from app.agent.nodes.recall_value import evaluate_grounding


def test_irrelevant_fuzzy_values_do_not_satisfy_grounding() -> None:
    expected = {"dim_product.brand": ["火星牌"]}
    recalled = [
        ValueInfo(id="brand.samsung", value="三星", column_id="dim_product.brand"),
        ValueInfo(id="brand.midea", value="美的", column_id="dim_product.brand"),
    ]
    result = evaluate_grounding(expected, recalled)
    assert result.matched_values == []
    assert result.missing_values == ["火星牌"]
```

- [ ] **Step 3: 运行测试并确认失败**

Run: `uv run python -m pytest tests/test_recall_value_semantics.py -q`

Expected: FAIL，提示辅助函数不存在。

- [ ] **Step 4: 收敛 `recall_value` 职责**

实现约束：

- 从 `state["query_semantics"]["filter_values"]` 获取按列 ID 绑定的过滤值。
- `filter_values` 为空时仍使用已有关键词做 ES exact enrichment，但跳过存在性校验、字段值关键词扩展 LLM 和 fuzzy 召回；隐式已知值可继续补充 SQL 上下文。
- `filter_values` 非空时，显式值与隐式关键词必须分两次 exact 查询，显式值优先且不受隐式候选 Top N 截断影响，两组结果去重合并。
- fuzzy 结果不参与存在性判定；当前实现直接跳过 fuzzy，避免相似但不等价的值造成误放行。
- 匹配采用可解释的规范化等价：去空格、大小写折叠，以及配置允许的领域后缀归一化；禁止用向量相似度直接判定“值存在”。
- 全部缺失返回 `value_grounding_failed`；部分缺失保留现有 `partial_value_grounding_failed`。
- 错误信息继续携带 `missing_values`、`matched_values` 和字段域。

旧函数 `detect_expected_domains()`、`extract_domain_filter_values()`、`split_after_last_break()` 在所有调用迁移后删除，避免两套规则并存。

- [ ] **Step 5: 运行 Grounding 单测**

Run: `uv run python -m pytest tests/test_recall_value_semantics.py -q`

Expected: 全部 PASS。

- [ ] **Step 6: 提交 Grounding 集成**

```bash
git add app/agent/nodes/recall_value.py tests/test_recall_value_semantics.py
git commit -m "fix: 仅校验明确字段过滤值"
```

---

### Task 6: 使用统一语义保留 SQL 必需字段

**Files:**
- Modify: `app/agent/nodes/filter_table.py`
- Create: `tests/test_filter_table_semantics.py`

- [ ] **Step 1: 编写字段保留失败测试**

构造最小 `TableInfoState`，逐条覆盖 baseline：

```python
import pytest

from app.agent.nodes.filter_table import collect_required_columns


@pytest.mark.parametrize(
    ("query", "expected_columns"),
    [
        ("按商品统计销售额", {"dim_product.product_name", "fact_order.order_amount"}),
        (
            "不同会员层级在各品类买了多少件",
            {
                "dim_customer.member_level",
                "dim_product.category",
                "fact_order.order_quantity",
            },
        ),
        (
            "各省男女客户分别贡献了多少 GMV",
            {
                "dim_region.province",
                "dim_customer.gender",
                "fact_order.order_amount",
            },
        ),
        (
            "查询地区季度维度的 GMV、销售件数和订单量",
            {
                "dim_region.region_name",
                "dim_date.quarter",
                "fact_order.order_amount",
                "fact_order.order_quantity",
                "fact_order.order_id",
            },
        ),
    ],
)
def test_collect_required_columns_from_semantics(
    query: str,
    expected_columns: set[str],
) -> None:
    semantics = parse_query_semantics(query)
    actual = collect_required_columns(semantics, metric_infos=[], retrieved_value_infos=[])
    assert expected_columns <= actual
```

- [ ] **Step 2: 编写主键不能替代展示维度的测试**

```python
def test_product_name_is_kept_with_join_keys() -> None:
    filtered = filter_tables_by_semantics(
        table_infos=PRODUCT_TABLES,
        query_semantics=parse_query_semantics("按商品统计销售额"),
        metric_infos=[],
        retrieved_value_infos=[],
    )
    product_columns = columns_of(filtered, "dim_product")
    assert "product_name" in product_columns
    assert "product_id" in product_columns
```

- [ ] **Step 3: 运行测试并确认失败**

Run: `uv run python -m pytest tests/test_filter_table_semantics.py -q`

Expected: FAIL，现有接口仍依赖 Query 字符串硬编码。

- [ ] **Step 4: 改造字段/表过滤规则**

新的依赖来源必须按以下顺序合并：

```text
group_by_columns
+ filter_values.keys()
+ metric_terms 对应的事实字段
+ metric_infos.related_columns
+ retrieved_value_infos.column_id
+ 各候选表 join 所需主外键
```

领域指标到事实字段的确定性映射集中放在 `query_semantics.py`：

```python
METRIC_REQUIRED_COLUMNS = {
    "gmv": {"fact_order.order_amount"},
    "order_quantity": {"fact_order.order_quantity"},
    "order_count": {"fact_order.order_id"},
    "aov": {"fact_order.order_amount", "fact_order.order_id"},
}
```

删除 `filter_table.py` 中与统一解析器重复的 `GROUP_BY_TRIGGERS`、`REGION_KEYWORDS`、`PRODUCT_KEYWORDS`、`CUSTOMER_KEYWORDS` 和 `detect_group_by_columns()`。

保留防御性兜底：如果语义依赖列因召回缺失未出现在 `table_infos`，记录 warning 并保留原候选上下文，不得静默降级成只含 ID 字段的表。

- [ ] **Step 5: 运行字段过滤测试**

Run: `uv run python -m pytest tests/test_filter_table_semantics.py -q`

Expected: 全部 PASS。

- [ ] **Step 6: 提交字段过滤集成**

```bash
git add app/agent/nodes/filter_table.py tests/test_filter_table_semantics.py
git commit -m "fix: 按查询语义保留业务字段"
```

---

### Task 7: 将语义证据写入 Trace

**Files:**
- Modify: `app/observability/trace_manager.py`
- Create: `tests/test_trace_query_semantics.py`

- [ ] **Step 1: 编写 Trace 摘要失败测试**

```python
from app.observability.trace_manager import summarize_payload


def test_trace_summary_contains_query_semantics() -> None:
    semantics = parse_query_semantics("订单数最多的三个品牌是什么")
    summary = summarize_payload({"query": "订单数最多的三个品牌是什么", "query_semantics": semantics})
    assert summary["query_semantics"]["group_by_columns"] == ["dim_product.brand"]
    assert summary["query_semantics"]["metric_terms"] == ["order_count"]
    assert summary["query_semantics"]["order_direction"] == "desc"
    assert summary["query_semantics"]["limit"] == 3
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `uv run python -m pytest tests/test_trace_query_semantics.py -q`

Expected: FAIL，摘要中没有 `query_semantics`。

- [ ] **Step 3: 增加受控 Trace 摘要**

在 `summarize_payload()` 中显式加入 `query_semantics`，使用现有 `safe_jsonable()` 做深度和长度限制。不得把完整元数据词典写进每条 Trace。

同时记录 Grounding 的可复算证据：`grounding_validation_skipped`、`grounding_skip_reason`、`value_keyword_expansion_skipped`、`value_fuzzy_search_skipped`，以及 `value_exact_search_metrics` 中的显式/隐式候选数和实际调用次数。请求根指标的 `grounding` 聚合必须保留这些字段，后续报告不得根据代码路径估算调用次数。

- [ ] **Step 4: 运行 Trace 测试**

Run: `uv run python -m pytest tests/test_trace_query_semantics.py tests/test_trace_metrics.py tests/test_trace_analysis.py -q`

Expected: 全部 PASS。

- [ ] **Step 5: 提交 Trace 证据**

```bash
git add app/observability/trace_manager.py tests/test_trace_query_semantics.py
git commit -m "feat: 在Trace中记录查询语义"
```

---

### Task 8: 完成静态回归与代码清理

**Files:**
- Modify: `app/agent/nodes/clarify_query.py`
- Modify: `app/agent/nodes/recall_value.py`
- Modify: `app/agent/nodes/filter_table.py`
- Test: `tests/`

- [ ] **Step 1: 搜索重复规则**

Run:

```bash
rg -n "EXPLICIT_METRIC_WORDS|FILTER_WORDS|DOMAIN_SUFFIXES|split_after_last_break|GROUP_BY_TRIGGERS|REGION_KEYWORDS|PRODUCT_KEYWORDS|CUSTOMER_KEYWORDS" app
```

Expected: 旧的重复语义规则无残留；只允许统一解析模块保留领域级常量。

- [ ] **Step 2: 运行新增规则层测试**

Run:

```bash
uv run python -m pytest tests/test_query_semantics.py tests/test_clarify_query_semantics.py tests/test_recall_value_semantics.py tests/test_filter_table_semantics.py tests/test_trace_query_semantics.py -q
```

Expected: 全部 PASS。

- [ ] **Step 3: 运行全量单元测试**

Run: `uv run python -m pytest tests -q`

Expected: 现有 65 条测试与新增测试全部 PASS，无回归。

- [ ] **Step 4: 运行编译和 Diff 检查**

Run:

```bash
uv run python -m compileall app eval tests
git diff --check
```

Expected: 两条命令退出码均为 0。

- [ ] **Step 5: 提交代码清理**

```bash
git add app tests conf/meta_config.yaml
git commit -m "refactor: 收敛电商问数语义规则"
```

---

### Task 9: 用户运行固定 Candidate 并生成提升结论

**Files:**
- Runtime output, ignored: `eval/reports/candidate-v1-cold/`
- Runtime output, ignored: `eval/reports/candidate-v1-api/`
- Runtime output, ignored: `traces/`
- Modify after results: `docs/evaluation/2026-08-17-evidence-v2-baseline.md`

- [ ] **Step 1: 用户运行隔离准确率评测**

Run:

```bash
uv run python -m eval.run_eval --cases eval/cases_test.yaml --strict --cache-mode cold --run-id candidate-v1-cold
```

Expected:

- 报告和 30 条 Trace 完整生成。
- `dataset_sha256` 与 `baseline-v3-cold` 一致。
- Trace 中存在 `query_semantics`。
- 重点检查 13 条 baseline 失败 Case，不以总分替代逐 Case 分析。

- [ ] **Step 2: 用户运行固定 API 压测**

Run:

```bash
uv run python -m eval.benchmark_api --cases eval/benchmark_cases.yaml --concurrency 10 --requests 50 --warmup-requests 5 --run-id candidate-v1-api
```

Expected:

- 50/50 HTTP 200、SSE final、Trace。
- 技术错误率保持 0%。
- 正常 Query 不再因分组、排序或时间描述进入 Grounding 错误分支。

- [ ] **Step 3: 按固定口径比较 baseline 与 candidate**

必须输出：

```text
Query Pass Rate：candidate - 56.67 个百分点/相对变化
Execution Accuracy：candidate - 52.38 个百分点/相对变化
API Branch Accuracy：candidate - 70 个百分点/相对变化
Grounding 误拦截：15/25 -> candidate
预期业务分支：25/25 -> candidate
技术错误率：0% -> candidate
正常成功查询 P50/P95：baseline -> candidate
```

性能结论需额外统计：`filter_values={}` 的请求是否跳过字段值扩展 LLM、fuzzy 召回和存在性校验，以及仍保留的 ES exact enrichment 调用次数；依据必须来自 Trace 节点耗时与 Grounding 指标。一次运行的延迟变化只描述为观测值，不宣称具有统计显著性。

- [ ] **Step 4: 写入最终问题闭环记录**

每类问题按以下模板更新评测文档：

```text
问题现象
→ baseline Case/Trace
→ 根因规则
→ 修改文件
→ 单元回归
→ candidate Case/Trace
→ 指标提升
→ 剩余限制
```

- [ ] **Step 5: 提交评测结论**

```bash
git add docs/evaluation/2026-08-17-evidence-v2-baseline.md
git commit -m "docs: 记录查询语义改进效果"
```

---

## 3. Candidate 验收门槛

以下条件必须同时满足，不能只看总准确率：

| 指标 | Baseline | Candidate 最低门槛 |
|---|---:|---:|
| API 技术错误率 | 0% | 保持 0% |
| API Branch Accuracy | 70% | 至少 90% |
| 正常 Query Grounding 误拦截 | 15/25 | 0/25 |
| 预期业务分支命中 | 25/25 | 保持 25/25 |
| Query Pass Rate | 56.67% | 至少 80% |
| Execution Accuracy | 52.38% | 至少 75% |
| Trace 语义证据 | 无 | 30/30 可检查 |

若 Grounding 分支达到目标但 Execution Accuracy 仍低，应先检查 candidate Trace 中传给 `generate_sql` 的 `table_infos` 是否已经包含正确业务字段：

- 正确字段存在但 SQL 仍选 ID：进入独立的 SQL Prompt/生成约束改进计划。
- 正确字段仍缺失：回到统一语义解析或元数据别名，不应直接调 Prompt 掩盖上游问题。

## 4. 风险与防回归策略

- **“商品”歧义：** 当前领域约定“按商品”映射 `product_name`，“商品品类/类目”映射 `category`，通过最长别名匹配解决。
- **“订单量”歧义：** 当前评测口径约定为订单数 `order_count`；“销量/件数/销售件数”映射 `order_quantity`，必须在单测中固定。
- **品牌“牌”后缀：** 只在品牌语境或 `X牌商品/X牌一共` 的领域句式中作为品牌值，不把所有以“牌”结尾的词无条件视为品牌。
- **模糊召回误判：** 当前 Grounding 链路不使用 fuzzy；值是否存在只通过按字段绑定、规范化后的 exact 等价判断。
- **元数据缓存：** 测试修改 YAML 后需显式清理 `build_dimension_alias_index.cache_clear()`，避免测试间污染。
- **Trace 体积：** 只记录本次解析结果与证据，不记录完整词典。
- **评测污染：** 不根据 `cases_test.yaml` 动态生成规则，不修改隔离测试集；新增表达只进入单元测试或开发集。
