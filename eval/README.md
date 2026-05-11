# 问数 Agent 自动化评估

本目录提供一套轻量级回归评估框架，用于批量执行自然语言问数 case，并检查最终 SQL 与执行结果的基础质量。

## 运行方式

在项目根目录执行：

```bash
uv run python -m eval.run_eval
```

脚本会真实调用现有 Agent graph，并依赖当前项目的 LLM、Embedding、Qdrant、Elasticsearch、Meta MySQL、DW MySQL 配置。

## 文件说明

- `cases.yaml`：标准测试集。
- `run_eval.py`：评估执行入口。
- `reports/latest.md`：最近一次 Markdown 评估报告。
- `reports/latest.json`：最近一次 JSON 评估报告。

## case 字段

每条 case 包含：

- `id`：用例唯一标识。
- `query`：自然语言问数问题。
- `expected_tables`：期望涉及的表，首版仅记录，不参与判定。
- `expected_metrics`：期望涉及的指标，首版仅记录，不参与判定。
- `expected_values`：期望涉及的字段值，首版仅记录，不参与判定。
- `must_contain_sql`：最终 SQL 必须包含的片段。
- `forbidden_sql`：最终 SQL 不允许包含的片段。
- `difficulty`：用例难度，可选 `easy`、`medium`、`hard`。
- `description`：用例说明。

## 判定规则

首版只评估最终 SQL 和执行结果：

1. 未生成 SQL：FAIL。
2. Agent 执行异常或最终 state 中存在错误：FAIL。
3. `must_contain_sql` 中任意片段没有出现在最终 SQL 中：FAIL。
4. `forbidden_sql` 中任意片段出现在最终 SQL 中：FAIL。
5. 其他情况：PASS。

## 后续可增强方向

- 增加召回命中率统计。
- 增加表命中率和指标命中率统计。
- 增加结果列、结果行数、数值范围等断言。
- 支持按 difficulty 或 id 过滤执行部分 case。
