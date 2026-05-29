# Agent 性能 Baseline 报告

> 生成时间：2026-05-29T15:24:57  
> 来源报告：`E:\practical project\shopkeeper-agent-backend\eval\reports\expanded_55_rerun.json`

## 1. 总览

| 指标 | 值 |
|---|---:|
| Case 数 | 55 |
| 通过数 | 41 |
| 失败数 | 14 |
| 通过率 | 74.55% |
| 缺失 Trace 数 | 0 |
| 总耗时 ms | 135838.42 |
| 平均耗时 ms | 2469.79 |
| P50 ms | 2808.57 |
| P90 ms | 3996.83 |
| P95 ms | 4298.93 |
| 最大耗时 ms | 4620.02 |

## 2. 节点耗时统计

| 节点 | 次数 | 错误数 | 平均 ms | P50 | P90 | P95 | 最大 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| generate_sql | 34 | 0 | 1655.95 | 1569.54 | 2271.86 | 2404.25 | 2487.21 |
| recall_metric | 45 | 0 | 1715.45 | 1741.83 | 2007.38 | 2090.87 | 2199.1 |
| recall_column | 45 | 0 | 1389.21 | 1340.68 | 1756.7 | 1955.93 | 2217.85 |
| recall_value | 45 | 11 | 777.79 | 722.01 | 1177.75 | 1289.94 | 1533.59 |
| merge_retrieved_info | 45 | 0 | 8.22 | 8.05 | 10.43 | 11.05 | 21.21 |
| validate_sql | 34 | 0 | 3.29 | 3.16 | 4.2 | 4.58 | 5.26 |
| add_extra_context | 45 | 0 | 2.01 | 1.77 | 2.0 | 2.32 | 13.89 |
| run_sql | 34 | 0 | 1.16 | 1.07 | 1.54 | 1.86 | 2.35 |
| extract_keywords | 45 | 0 | 7.66 | 0.18 | 0.82 | 1.47 | 330.96 |
| filter_table | 45 | 0 | 0.23 | 0.22 | 0.25 | 0.31 | 1.0 |
| filter_metric | 45 | 0 | 0.2 | 0.22 | 0.24 | 0.28 | 0.33 |
| clarify_query | 49 | 0 | 0.13 | 0.11 | 0.19 | 0.23 | 0.55 |
| guard_query | 55 | 6 | 0.17 | 0.14 | 0.21 | 0.21 | 1.14 |

## 3. 最慢 Top 10 Case

| Case | 通过 | 耗时 ms | Trace | 问题 |
|---|---|---:|---|---|
| p2_007 | True | 4620.02 | `E:\practical project\shopkeeper-agent-backend\traces\2026-05-29\eval-p2_007-2e08e510.json` | 按会员等级统计 2025 年第一季度的订单数和销售额 |
| p2_009 | True | 4450.58 | `E:\practical project\shopkeeper-agent-backend\traces\2026-05-29\eval-p2_009-cc0b59cb.json` | 统计 2025 年第一季度各大区的 GMV，并按 GMV 从高到低排序 |
| p2_015 | True | 4307.09 | `E:\practical project\shopkeeper-agent-backend\traces\2026-05-29\eval-p2_015-c9a95da2.json` | 对比华北和华东的销售额 |
| p2_017 | True | 4295.44 | `E:\practical project\shopkeeper-agent-backend\traces\2026-05-29\eval-p2_017-e5db19c9.json` | 按大区统计食品饮料品类的销售额 |
| exp_008 | True | 4076.02 | `E:\practical project\shopkeeper-agent-backend\traces\2026-05-29\eval-exp_008-2b5bde0b.json` | 统计西南地区食品饮料品类的销售额 |
| exp_001 | True | 4014.09 | `E:\practical project\shopkeeper-agent-backend\traces\2026-05-29\eval-exp_001-d2382ba9.json` | 按品牌统计销售额，并按销售额从高到低排序 |
| exp_018 | True | 3970.93 | `E:\practical project\shopkeeper-agent-backend\traces\2026-05-29\eval-exp_018-07d135bb.json` | 统计华北地区的销售额、订单数和销量 |
| exp_011 | True | 3908.38 | `E:\practical project\shopkeeper-agent-backend\traces\2026-05-29\eval-exp_011-d664e8bc.json` | 统计 2025 年第二季度各大区的销售额 |
| exp_019 | True | 3864.93 | `E:\practical project\shopkeeper-agent-backend\traces\2026-05-29\eval-exp_019-e40fae2a.json` | 按大区统计销售额、订单数和销量 |
| p2_010 | True | 3808.28 | `E:\practical project\shopkeeper-agent-backend\traces\2026-05-29\eval-p2_010-b955548d.json` | 统计华北地区美的品牌的销售额 |

## 4. SQL EXPLAIN Risk Flags

| Risk Flag | 次数 |
|---|---:|
| FULL_TABLE_SCAN | 33 |
| NO_INDEX_USED | 34 |
| USING_TEMPORARY | 15 |
| USING_FILESORT | 4 |

## 5. 三路召回并行性检查

| 指标 | 值 |
|---|---:|
| 可检查 case 数 | 45 |
| 观察到并行的 case 数 | 45 |
| 是否观察到并行 | True |
| 三路耗时平均总和 ms | 3882.46 |
| 三路 wall time 平均 ms | 1732.47 |
| 平均估算节省 ms | 2149.99 |

## 6. 初步结论

- 若 P95 最高的节点集中在 LLM 调用，应优先减少不必要的模型调用和 prompt 长度。
- 若召回节点耗时高，应优先检查 Embedding、Qdrant、Elasticsearch 和并行召回情况。
- 若 validate_sql / run_sql 风险较多，应结合 EXPLAIN 结果完善索引设计。
- 本报告只做性能 baseline，不引入 Rerank、Memory 或 SQL 结果缓存。
