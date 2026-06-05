# API Benchmark 报告

生成时间：2026-06-05T16:01:28
URL：http://127.0.0.1:8000/api/query
case_set：mixed-core8
并发数：10
请求数：50

## 总体统计

| total_requests | normal_success_count | expected_business_outcome_count | technical_error_count | technical_error_rate | avg_latency_ms | p50 | p90 | p95 | p99 | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 50 | 26 | 24 | 0 | 0.0% | 2986.41 | 4209.66 | 4788.92 | 5609.01 | 6550.84 | 6610.57 |

## 预期业务分支分布

- value_grounding_failed: 6
- partial_value_grounding_failed: 6
- need_clarification: 6
- unsafe_query: 6

## 技术错误分布

- none: 0

## warning_type 分布

- partial_value_grounding_failed: 6

## 最慢 Top 10 请求

| rank | query | duration_ms | outcome_category | business_outcome_type | technical_error_type | warning_type | trace_path |
|---:|---|---:|---|---|---|---|---|
| 1 | 对比华北和火星地区的销售额 | 6610.57 | expected_business_outcome | partial_value_grounding_failed |  | partial_value_grounding_failed | E:\practical project\shopkeeper-agent-backend\traces\2026-06-05\ec41265a9f7d45f59c36bdb9c47dced5.json |
| 2 | 统计 2025 年第一季度的销售额 | 6488.67 | normal_success |  |  |  | E:\practical project\shopkeeper-agent-backend\traces\2026-06-05\9a086ce348334d56a2f7feb786f54580.json |
| 3 | 按大区统计销售额 | 5975.72 | normal_success |  |  |  | E:\practical project\shopkeeper-agent-backend\traces\2026-06-05\5d227cdc25f140eab1e8299d68330aaf.json |
| 4 | 统计 2025 年第一季度的销售额 | 5160.8 | normal_success |  |  |  | E:\practical project\shopkeeper-agent-backend\traces\2026-06-05\5c09e99a76754d69b9968ab6e0e36a37.json |
| 5 | 统计美的品牌的销售额 | 5079.58 | normal_success |  |  |  | E:\practical project\shopkeeper-agent-backend\traces\2026-06-05\4834849f894942a185fc75d77942ff26.json |
| 6 | 按大区统计销售额 | 4756.62 | normal_success |  |  |  | E:\practical project\shopkeeper-agent-backend\traces\2026-06-05\5860c10a0d8f4fcd8078b4288abab51b.json |
| 7 | 统计美的品牌的销售额 | 4741.41 | normal_success |  |  |  | E:\practical project\shopkeeper-agent-backend\traces\2026-06-05\296103a4c7fc4f38852480a8d6d97ca0.json |
| 8 | 华北地区的总销售额 | 4723.66 | normal_success |  |  |  | E:\practical project\shopkeeper-agent-backend\traces\2026-06-05\2464f22f34f84d659b75833170b3e9b7.json |
| 9 | 对比华北和火星地区的销售额 | 4639.12 | expected_business_outcome | partial_value_grounding_failed |  | partial_value_grounding_failed | E:\practical project\shopkeeper-agent-backend\traces\2026-06-05\b4ad11897bc04aaab3cc4005dd8a0326.json |
| 10 | 华北地区的总销售额 | 4623.79 | normal_success |  |  |  | E:\practical project\shopkeeper-agent-backend\traces\2026-06-05\ddb08169fc3941489fb332855c7bef10.json |
