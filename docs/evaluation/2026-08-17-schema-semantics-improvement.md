# Schema 驱动查询语义改进记录

## 1. 记录目的

本文记录电商问数 Agent 从问题定位、规则重构、Trace 补强到 Candidate 评测的完整闭环。原始 Eval 报告和 Trace 是本地运行产物，受 `.gitignore` 管理，不进入 Git；本文只保留能够由固定数据集、报告和 Trace 复算的结论。

基线问题详见 [`2026-08-17-evidence-v2-baseline.md`](./2026-08-17-evidence-v2-baseline.md)，实现计划详见 [`2026-08-17-schema-driven-query-semantics.md`](../superpowers/plans/2026-08-17-schema-driven-query-semantics.md)。

## 2. 实验口径

### 2.1 隔离准确率评测

| 项目 | Baseline | Candidate |
|---|---|---|
| run_id | `baseline-v3-cold` | `candidate-v1-cold` |
| 代码版本 | `ccf75a9` | `bbebedd` |
| 数据集 | `eval/cases_test.yaml` | 同左 |
| 数据集 SHA-256 | `4036be6686164c7da925ef17d363622a1960ee444e26a98f00019b92ef67cab2` | 同左 |
| Prompt SHA-256 | `3925597e96a05d00ffb9e11780ceec5da55089ba4293cd3bd2c44b97f4d61215` | 同左 |
| 模型 | `deepseek-chat`，temperature=0 | 同左 |
| Embedding | `BAAI/bge-large-zh-v1.5` | 同左 |
| 缓存口径 | cold，无预热请求 | 同左 |
| 计量 Query | 30 | 30 |

数据集、Prompt、模型和缓存口径保持一致，主要变量是查询语义与 Grounding 实现。

### 2.2 API 并发评测

| 项目 | Baseline | Candidate |
|---|---|---|
| run_id | `baseline-v3-api` | `candidate-v1-api` |
| Case 文件 | `eval/benchmark_cases.yaml` | 同左 |
| Case SHA-256 | `ec82efb41981202a2ce55b9bca491d6379a29e640b62eabd0e8722b4615f712e` | 同左 |
| 并发数 | 10 | 10 |
| 预热请求 | 5，不计入统计 | 同左 |
| 计量请求 | 50 | 50 |

## 3. 基线问题

Baseline API 的技术错误率为 0%，但业务分支准确率只有 70%。25 次正常 Query 中有 15 次被错误 Grounding 拦截，稳定集中在三类表达：

| Query 类型 | 错误行为 | 根因 |
|---|---|---|
| `统计 2025 年 3 月华北地区的销售额` | 把时间与地区拼成一个字段值 | 时间、维度和值提取规则彼此独立，缺少区间占用和字段绑定 |
| `按会员等级和商品品类统计销量` | 把分组描述和通用名词当作过滤值 | 澄清、Grounding、表过滤各自维护松散关键词规则 |
| `订单数最多的三个品牌是什么` | 把排序和 Top N 描述当作品牌值 | 指标、排序、分组和值没有统一语义状态 |

同一套松散规则还造成以下问题：

- `product_name`、`member_level`、`province` 等展示字段可能在 SQL 生成前被过滤，只剩主外键。
- “订单量排名前三”已有明确指标，仍可能进入指标澄清。
- fuzzy 相似结果可能被错误当作字段值存在性证据。
- 字段值 LLM 扩展、exact 和 fuzzy 的调用情况没有请求级指标，性能结论难以复算。

## 4. 改进方法

### 4.1 统一 Schema 驱动语义

新增 `app/agent/query_semantics.py`，从 `conf/meta_config.yaml` 的字段名称和别名构建当前电商 Schema 的领域词典。每个安全 Query 在 `clarify_query` 中只解析一次，并写入共享状态：

```text
dimension_columns
group_by_columns
filter_values
metric_terms
time_expressions
order_direction
limit
parse_evidence
```

解析器使用最长别名匹配和确定性优先级，依次识别时间、指标、排序、Top N、维度、分组和显式过滤值。后续节点消费同一份结构化结果，不再重复猜测 Query 含义。

### 4.2 收敛 Grounding 职责

`recall_value` 调整为：

1. 只对 `filter_values` 中按列绑定的显式值做存在性校验。
2. 显式值和隐式关键词分别执行 ES exact，避免显式证据被隐式候选挤出 Top N。
3. 两组 exact 结果去重后进入 SQL 上下文。
4. 没有显式过滤值时保留隐式 exact enrichment，但跳过存在性校验。
5. 移除字段值 LLM 扩展和 fuzzy 正确性判定。
6. 隐式 enrichment 失败时保留已命中的显式 Grounding 证据，并返回弱依赖告警。

### 4.3 按语义保留 SQL 必需字段

`filter_table` 根据以下依赖集合保留字段和表：

```text
分组字段
+ 显式过滤字段
+ 指标依赖事实字段
+ 时间表达所需日期字段
+ 召回字段值所属字段
+ Join 所需主外键
```

如果语义依赖字段没有进入候选上下文，节点记录 warning 并保留过滤前上下文，避免静默退化成只含 ID 的表。

### 4.4 补齐 Trace 证据

Trace 新增：

- `query_semantics` 与 `parse_evidence`
- `grounding_validation_skipped`
- `grounding_skip_reason`
- `value_keyword_expansion_skipped`
- `value_fuzzy_search_skipped`
- 显式/隐式 exact 候选数与实际调用次数

请求根指标增加 `grounding` 聚合，使后续报告可以直接复算调用量，而不是根据代码路径估算。

## 5. 静态与单元验证

| 验证项 | 结果 |
|---|---:|
| 全量单元测试 | 123 passed |
| Eval Query 静态扫描 | 120/120 |
| 开发集 | 90 条 |
| 隔离测试集 | 30 条 |
| 识别为显式过滤的 Query | 34 条 |
| 分析类 Query 显式过滤误判 | 0 条 |
| Python compileall | 通过 |
| `git diff --check` | 通过 |

静态扫描只证明规则输出符合预期形状，最终准确率仍以真实 Agent、数据库和报告运行结果为准。

## 6. 隔离准确率结果

| 指标 | Baseline | Candidate | 变化 |
|---|---:|---:|---:|
| 通过 Query | 17/30 | 28/30 | +11 |
| Query Pass Rate | 56.67% | 93.33% | +36.66 个百分点 |
| Execution Accuracy | 52.38% | 90.48% | +38.10 个百分点 |
| Intent Macro Accuracy | 56.67% | 93.33% | +36.66 个百分点 |
| 平均延迟 | 1844.80 ms | 1797.80 ms | -47.00 ms |
| P95 延迟 | 3333.70 ms | 3042.47 ms | -291.23 ms，下降 8.74% |

13 个 Baseline 失败中有 11 个转为通过，没有新增回归。字段值召回节点的观测结果为：

| `recall_value` | Baseline | Candidate | 变化 |
|---|---:|---:|---:|
| 平均耗时 | 807.57 ms | 4.79 ms | 下降约 99.4% |
| P50 | 769.38 ms | 3.80 ms | 下降约 99.5% |
| P95 | 1018.72 ms | 5.99 ms | 下降约 99.4% |

Candidate 的 24 条 `recall_value` Trace 中：

- 24/24 跳过字段值 LLM 扩展和 fuzzy。
- 21 条无显式过滤，跳过存在性校验。
- 3 条包含显式过滤并执行校验。
- 共记录 3 次显式 exact、24 次隐式 exact。

30 条 Cold Eval Trace 中有 27 条记录 `query_semantics`；其余 3 条是危险查询，在 `guard_query` 阶段已经结束，没有进入语义解析，属于预期的拓扑行为。

## 7. API 并发结果

| 指标 | Baseline | Candidate | 变化 |
|---|---:|---:|---:|
| HTTP 200 | 50/50 | 50/50 | 保持 |
| SSE final | 50/50 | 50/50 | 保持 |
| Trace | 50/50 | 50/50 | 保持 |
| 技术错误率 | 0% | 0% | 保持 |
| API Branch Accuracy | 70%（35/50） | 100%（50/50） | +30 个百分点 |
| 正常 Query 成功 | 10/25 | 25/25 | +15 |
| 正常 Query Grounding 误拦截 | 15/25 | 0/25 | 全部消除 |
| 预期业务分支命中 | 25/25 | 25/25 | 无回归 |
| 混合请求 P95 | 5238.22 ms | 3802.05 ms | 下降 27.42% |
| 最大延迟 | 6447.14 ms | 4999.04 ms | 下降 22.46% |

Baseline 的 15 次错分正好是三个正常 Case 各重复 5 次；Candidate 中全部恢复为正常成功。

### 7.1 延迟口径说明

Candidate 的混合请求平均延迟从 1559.87 ms 上升到 1876.93 ms，不能据此判断性能退化。Baseline 把 15 个正常 Query 提前错误拦截，没有执行完整 SQL 链路；Candidate 修复后，这 15 个请求会继续完成召回、生成、校验和执行，两个总体平均值的请求构成不同。

对 Baseline 和 Candidate 都正常执行的相同 Case 比较：

| 指标 | Baseline | Candidate | 变化 |
|---|---:|---:|---:|
| 样本数 | 10 | 10 | 同口径 |
| 平均延迟 | 3607.73 ms | 2771.84 ms | 下降 23.17% |
| P50 | 3487.24 ms | 2789.01 ms | 下降约 20.02% |
| P95 | 4686.79 ms | 3438.26 ms | 下降约 26.64% |

API Candidate 的 35 条 `recall_value` Trace 中：

- 平均耗时从 36.32 ms 降至 7.53 ms，下降约 79.27%。
- P95 从 104.24 ms 降至 21.10 ms，下降约 79.76%。
- 35/35 跳过字段值 LLM 扩展和 fuzzy。
- 共记录 15 次显式 exact、35 次隐式 exact。

50 条 API Trace 中有 40 条记录 `query_semantics`；其余 10 条是危险 SQL 和 Prompt Injection，在安全节点提前结束。

以上延迟均是一次本地 10 并发运行的观测值，不宣称具有统计显著性。

## 8. 剩余两个评测器假阴性

Candidate 的两条官方失败均成功生成并执行了业务结果正确的 SQL，但当前比较规则将其判为失败：

### 8.1 `test_004_2`：部分列同名时的列对齐问题

Agent 和 Gold 都按 `province + gender` 聚合 GMV，结果均为 11 行且数值一致。Agent 的 SELECT 顺序是 `province, gender, total_gmv`，Gold 是 `gender, province, total_sales`。

比较器发现聚合别名不同后整体退回按位置比较，导致两个同名维度列也不再按列名对齐，产生假阴性。

### 8.2 `test_006_1`：Top N 并列顺序不确定

Agent 与 Gold 的 Top 3 品牌集合和订单数完全一致。三个品牌的订单数均为 11，而 Gold SQL 只有 `ORDER BY order_count DESC`，没有确定性二级排序。数据库允许并列项以任意顺序返回，但评测器要求逐行顺序一致，因此产生假阴性。

在修复比较器并重新运行前，正式指标保持 `28/30` 和 `90.48%`，不把人工复核结果直接记为 100%。

## 9. 最终结论

- Schema 驱动的共享语义状态替代了澄清、Grounding 和表过滤中的重复松散规则。
- Cold Eval Query Pass Rate 从 56.67% 提升至 93.33%，Execution Accuracy 从 52.38% 提升至 90.48%。
- API Branch Accuracy 从 70% 提升至 100%，15/25 的正常查询误拦截降为 0/25。
- 10 并发、50 请求中技术错误率保持 0%，HTTP、SSE final 和 Trace 均为 50/50。
- 同口径正常请求平均延迟下降 23.17%，字段值召回节点在 Cold Eval 中平均耗时下降约 99.4%。
- 两个剩余失败已经定位为评测器假阴性，暂不修改 Agent 业务规则来迎合错误判定。

## 10. 结论边界

- 结果只代表当前电商问数领域、现有 Schema、固定本地数据和测试集。
- 120 条静态 Query 和 30 条隔离测试不能代替真实生产流量。
- 一次延迟运行只能作为观测证据，不能证明统计显著性。
- 原始报告与 Trace 保留在本地 `eval/reports/` 和 `traces/`，不提交版本库。
- 后续优先修复结果比较器的列对齐与并列排序语义，再扩大测试集。
