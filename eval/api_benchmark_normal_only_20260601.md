# API Benchmark 报告

生成时间：2026-06-05T16:00:52
URL：http://127.0.0.1:8000/api/query
case_set：normal-only
并发数：5
请求数：20

## 总体统计

| total_requests | normal_success_count | expected_business_outcome_count | technical_error_count | technical_error_rate | avg_latency_ms | p50 | p90 | p95 | p99 | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 20 | 20 | 0 | 0 | 0.0% | 3603.27 | 2448.1 | 7798.41 | 8588.84 | 8624.64 | 8633.59 |

## 预期业务分支分布


## 技术错误分布

- none: 0

## warning_type 分布

- none: 0

## 最慢 Top 10 请求

| rank | query | duration_ms | outcome_category | business_outcome_type | technical_error_type | warning_type | trace_path |
|---:|---|---:|---|---|---|---|---|
| 1 | 华北地区的总销售额 | 8633.59 | normal_success |  |  |  | E:\practical project\shopkeeper-agent-backend\traces\2026-06-05\8aef488bc11749fcb081c5cbd6d0eb36.json |
| 2 | 统计美的品牌的销售额 | 8586.49 | normal_success |  |  |  | E:\practical project\shopkeeper-agent-backend\traces\2026-06-05\489f7fe37d9a40ccba3d437d1daa0602.json |
| 3 | 统计 2025 年第一季度的销售额 | 7710.84 | normal_success |  |  |  | E:\practical project\shopkeeper-agent-backend\traces\2026-06-05\61e0d2512a48479584a14461dd45da01.json |
| 4 | 按大区统计销售额 | 7351.15 | normal_success |  |  |  | E:\practical project\shopkeeper-agent-backend\traces\2026-06-05\aba3454b99a34b63bfedd0b305b26fd2.json |
| 5 | 华北地区的总销售额 | 7347.08 | normal_success |  |  |  | E:\practical project\shopkeeper-agent-backend\traces\2026-06-05\553b01618aef4072ad56a635aa9b9eca.json |
| 6 | 统计 2025 年第一季度的销售额 | 2645.19 | normal_success |  |  |  | E:\practical project\shopkeeper-agent-backend\traces\2026-06-05\bfe76a3858864baa9079cd5a253011a6.json |
| 7 | 按大区统计销售额 | 2594.07 | normal_success |  |  |  | E:\practical project\shopkeeper-agent-backend\traces\2026-06-05\9409e4391d074dc0a123f2292593cec4.json |
| 8 | 华北地区的总销售额 | 2540.63 | normal_success |  |  |  | E:\practical project\shopkeeper-agent-backend\traces\2026-06-05\86ec64adc6fe49dbae36d4836103bc96.json |
| 9 | 统计美的品牌的销售额 | 2489.81 | normal_success |  |  |  | E:\practical project\shopkeeper-agent-backend\traces\2026-06-05\94ae7b0c7e5545c89c0e623a14a18d7c.json |
| 10 | 按大区统计销售额 | 2459.95 | normal_success |  |  |  | E:\practical project\shopkeeper-agent-backend\traces\2026-06-05\1c735914da384192864fdc2f09fa8315.json |
