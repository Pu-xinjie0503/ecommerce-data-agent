# Agent 性能 Baseline 报告

> 生成时间：2026-05-29T23:52:13  
> 来源报告：`E:\practical project\shopkeeper-agent-backend\eval\reports\latest.json`  
> 对比基线：`E:\practical project\shopkeeper-agent-backend\eval\reports\performance_baseline_20260528.json`  
> 验收说明：本次 cache 验收使用 DeepSeek 官方 API / deepseek-chat；由于模型变化，pass_rate 仅用于链路验收，不作为同模型严格对比。

## 1. 总览

| 指标 | 值 |
|---|---:|
| Case 数 | 55 |
| 通过数 | 41 |
| 失败数 | 14 |
| 通过率 | 74.55% |
| 缺失 Trace 数 | 0 |
| 总耗时 ms | 87363.09 |
| 平均耗时 ms | 1588.42 |
| P50 ms | 1920.59 |
| P90 ms | 2534.9 |
| P95 ms | 2834.17 |
| 最大耗时 ms | 3508.38 |

## 2. 节点耗时统计

| 节点 | 次数 | 错误数 | 平均 ms | P50 | P90 | P95 | 最大 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| generate_sql | 34 | 1 | 1085.91 | 1069.2 | 1458.54 | 1557.88 | 1674.18 |
| recall_metric | 45 | 0 | 1011.51 | 935.25 | 1303.35 | 1514.37 | 2008.15 |
| recall_column | 45 | 0 | 933.7 | 887.81 | 1178.13 | 1450.98 | 1759.99 |
| recall_value | 45 | 11 | 906.52 | 844.82 | 1225.69 | 1280.91 | 1540.91 |
| merge_retrieved_info | 45 | 0 | 8.65 | 8.12 | 10.27 | 12.35 | 38.92 |
| validate_sql | 34 | 1 | 3.18 | 3.12 | 4.12 | 4.81 | 5.93 |
| add_extra_context | 45 | 0 | 1.93 | 1.71 | 2.17 | 2.34 | 13.48 |
| run_sql | 34 | 1 | 1.15 | 1.04 | 1.48 | 1.69 | 2.93 |
| extract_keywords | 45 | 0 | 7.61 | 0.19 | 0.64 | 0.92 | 329.41 |
| guard_query | 55 | 6 | 0.19 | 0.16 | 0.25 | 0.27 | 0.98 |
| filter_table | 45 | 0 | 0.19 | 0.12 | 0.25 | 0.27 | 1.22 |
| clarify_query | 49 | 0 | 0.14 | 0.12 | 0.22 | 0.26 | 0.43 |
| filter_metric | 45 | 0 | 0.2 | 0.16 | 0.24 | 0.26 | 0.96 |
| correct_sql | 1 | 1 | 0.16 | 0.16 | 0.16 | 0.16 | 0.16 |

## 3. 最慢 Top 10 Case

| Case | 通过 | 耗时 ms | Trace | 问题 |
|---|---|---:|---|---|
| p2_001 | True | 3508.38 | `E:\practical project\shopkeeper-agent-backend\traces\2026-05-29\eval-p2_001-4b0fe998.json` | 华北地区的总销售额 |
| exp_027 | False | 2964.1 | `E:\practical project\shopkeeper-agent-backend\traces\2026-05-29\eval-exp_027-b8b899af.json` | 看一下各品牌情况 |
| exp_003 | True | 2853.36 | `E:\practical project\shopkeeper-agent-backend\traces\2026-05-29\eval-exp_003-435e8151.json` | 统计各大区的销量，并按销量从低到高排序 |
| p2_009 | True | 2825.95 | `E:\practical project\shopkeeper-agent-backend\traces\2026-05-29\eval-p2_009-a6d29a0d.json` | 统计 2025 年第一季度各大区的 GMV，并按 GMV 从高到低排序 |
| exp_022 | False | 2679.74 | `E:\practical project\shopkeeper-agent-backend\traces\2026-05-29\eval-exp_022-68045978.json` | 帮我更新 fact_order 表里的订单金额 |
| exp_013 | True | 2594.67 | `E:\practical project\shopkeeper-agent-backend\traces\2026-05-29\eval-exp_013-3ad07669.json` | 按会员等级统计销售额 |
| p2_007 | True | 2445.25 | `E:\practical project\shopkeeper-agent-backend\traces\2026-05-29\eval-p2_007-377844ba.json` | 按会员等级统计 2025 年第一季度的订单数和销售额 |
| exp_011 | True | 2407.92 | `E:\practical project\shopkeeper-agent-backend\traces\2026-05-29\eval-exp_011-70dba973.json` | 统计 2025 年第二季度各大区的销售额 |
| exp_019 | True | 2368.57 | `E:\practical project\shopkeeper-agent-backend\traces\2026-05-29\eval-exp_019-8c0ebccc.json` | 按大区统计销售额、订单数和销量 |
| exp_018 | True | 2345.47 | `E:\practical project\shopkeeper-agent-backend\traces\2026-05-29\eval-exp_018-4313dd95.json` | 统计华北地区的销售额、订单数和销量 |

## 4. SQL EXPLAIN Risk Flags

| Risk Flag | 次数 |
|---|---:|
| FULL_TABLE_SCAN | 33 |
| NO_INDEX_USED | 33 |
| USING_FILESORT | 7 |
| USING_TEMPORARY | 15 |

## 5. 三路召回并行性检查

| 指标 | 值 |
|---|---:|
| 可检查 case 数 | 45 |
| 观察到并行的 case 数 | 45 |
| 是否观察到并行 | True |
| 三路耗时平均总和 ms | 2851.73 |
| 三路 wall time 平均 ms | 1086.73 |
| 平均估算节省 ms | 1764.99 |

## 6. Cache Stats

### 6.1 Embedding Cache

| 指标 | 值 |
|---|---:|
| embedding_cache_hit | 513 |
| embedding_cache_miss | 162 |
| embedding_cache_size | 122 |
| embedding_cache_hit_rate | 76.0% |

### 6.2 Keyword Expansion Cache

| recall_type | hit | miss | hit_rate |
|---|---:|---:|---:|
| column | 0 | 45 | 0.0% |
| metric | 0 | 45 | 0.0% |
| value | 0 | 45 | 0.0% |

### 6.3 适用范围说明

- 当前 cache 是进程内缓存，不是 Redis；缓存内容不会跨进程、跨服务实例共享。
- 本次 55 条 eval 是单进程连续运行，因此结果体现的是同一进程内关键词扩展与 embedding 的复用收益。
- 对完全冷启动的单条请求，缓存尚未预热，收益会小一些。
- 对重复问题、高频指标、高频字段和多用户长期运行场景，缓存复用更充分，收益会更明显。

## 7. Baseline 对比

| 指标 | Before | After | Delta |
|---|---:|---:|---:|
| total avg ms | 2469.79 | 1588.42 | -881.37 |
| P95 ms | 4298.93 | 2834.17 | -1464.76 |
| pass_rate | 74.55% | 74.55% | 0.0 |

| 节点 | Before avg ms | After avg ms | Delta |
|---|---:|---:|---:|
| recall_column | 1389.21 | 933.7 | -455.51 |
| recall_metric | 1715.45 | 1011.51 | -703.94 |
| recall_value | 777.79 | 906.52 | 128.73 |
| generate_sql | 1655.95 | 1085.91 | -570.04 |

## 8. 初步结论

- 若 P95 最高的节点集中在 LLM 调用，应优先减少不必要的模型调用和 prompt 长度。
- 若召回节点耗时高，应优先检查 Embedding、Qdrant、Elasticsearch 和并行召回情况。
- 当前阶段只评估召回链路缓存，不引入 Rerank、Memory、SQL 结果缓存或 MySQL 索引改造。
