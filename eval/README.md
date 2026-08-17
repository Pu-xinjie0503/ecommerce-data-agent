# 问数 Agent 评测与性能证据

本目录用于生成可复现、可比较、可回溯到原始 Case 和 Trace 的实验报告。没有实际报告时，不应在简历中填写性能提升或准确率数字。

## 1. 评测集口径

| 文件 | 用途 | 意图数 | Query 数 |
|---|---|---:|---:|
| `cases_dev.yaml` | 开发与回归定位 | 30 | 90 |
| `cases_test.yaml` | 隔离测试与最终准确率 | 10 | 30 |
| `benchmark_cases.yaml` | API 混合链路压测 | 10 | 按请求数循环 |

同一意图的三种自然语言表达只进入同一个集合。报告同时给出 Query 通过率和意图宏平均，最终准确率优先引用隔离测试集的 `execution_accuracy` 与 `intent_macro_accuracy`，不能用近义改写数量放大结果。

普通问数通过执行 Agent SQL 与 Gold SQL 比较结果等价性判定，支持数值容差、忽略非排序结果的行顺序及忽略列别名。安全、Grounding 和澄清使用确定性分支断言，并按类别单独统计。

## 2. 环境启动后运行

先确认 Docker 依赖、LLM、Embedding 和 API 服务均已按主 README 启动。以下命令都在项目根目录执行。

只运行隔离测试集的冷缓存评测：

```bash
uv run python -m eval.run_eval --cases eval/cases_test.yaml --strict --cache-mode cold --run-id evidence-test-cold
```

运行完整证据套件，包括关闭/冷/暖缓存评测、Trace 分析和 10 并发 50 请求 API 压测：

```bash
uv run python -m eval.run_benchmarks --suite-id evidence-v1 --concurrency 10 --requests 50 --warmup-requests 5
```

如果 API 尚未启动，可先跳过 API：

```bash
uv run python -m eval.run_benchmarks --suite-id evidence-v1 --skip-api
```

API 启动后单独补稳定性压测：

```bash
uv run python -m eval.benchmark_api --cases eval/benchmark_cases.yaml --concurrency 10 --requests 50 --warmup-requests 5 --run-id evidence-v1-api
```

暖缓存模式会先执行一轮完整预热，预热 Trace 标记为 `phase=warmup`，不计入准确率和延迟；清零统计但保留缓存内容后，计量轮 Trace 标记为 `phase=measured`。因此暖缓存是“同问题精确重复”的收益上限，不应包装成真实流量命中率。

## 3. 预期控制台记录

评测时每条计量 Query 会输出：

```text
[PASS] test_001_1 按省份统计销售额 (3120.45 ms) trace=...json
```

暖缓存预热会额外输出：

```text
开始暖缓存预热：30 条 Query（不计入报告）
[WARMUP] 1/30 test_001_1
暖缓存预热完成，已清零命中统计并开始计量轮
```

运行结束会打印 Execution Accuracy、意图宏平均、耗时和报告路径。API 压测会打印技术错误率、分支准确率、吞吐量、P50/P90/P95/P99 与最慢请求。

API 报告中的 `technical_error_rate` 只衡量 HTTP、SSE 和外部依赖是否发生技术故障；`branch_accuracy` 才衡量每个 Case 是否进入预期的正常、Grounding、澄清或安全分支。正常 Case 被 Grounding 拦截时技术错误率仍可为 0%，但 `branch_matched` 必须为 `false`。

## 4. 报告与 Trace

每次运行按 ID 隔离：

```text
eval/reports/<run_id>/eval.json
eval/reports/<run_id>/eval.md
eval/reports/<run_id>/trace_analysis.json
eval/reports/<run_id>/trace_analysis.md
eval/reports/<run_id>/benchmark.json
eval/reports/<run_id>/benchmark.md
traces/eval/<run_id>/*.json
```

统一套件还会生成 `eval/reports/<suite_id>/cache_comparison.json`。

`eval.json` 保存模型、温度、数据集 SHA-256、Prompt SHA-256、Git revision、缓存模式、逐 Case 结果和 Gold SQL 等价比较。每条 Trace 根节点保存相同实验元数据，以及节点数、失败节点数、缓存增量和三路召回并行指标。

三路召回收益可以从 Trace 反向复算：

```text
串行估算 = recall_column + recall_metric + recall_value
并行墙钟 = max(结束时间) - min(开始时间)
估算节省 = 串行估算 - 并行墙钟
节省比例 = 估算节省 / 串行估算
```

## 5. 对比与简历引用规则

建议采用两阶段流程：第一次运行当前代码形成 baseline；后续根据 `cases_dev.yaml` 和 Trace 修复召回、Prompt 或分支逻辑，再用完全相同的模型、温度、Prompt 文件和 Case 文件生成 candidate。隔离测试集只用于基线与最终验收，不应逐条调参。只有 baseline/candidate 均存在且通过可比性校验，才能写“准确率提升 Y 个百分点”；只有一次报告时只能写“Execution Accuracy 达到 X%”。

手动比较两次同条件报告：

```bash
uv run python -m eval.compare_runs --baseline eval/reports/<baseline>/eval.json --candidate eval/reports/<candidate>/eval.json --output eval/reports/<candidate>/comparison.json
```

模型、温度、数据集哈希或 Prompt 哈希不同，工具会拒绝计算准确率或延迟提升。API 压测还要求 URL、并发数、请求数、预热数和 Case 哈希一致。

简历数字必须满足以下条件：

- 写清使用的隔离测试集规模和运行 ID。
- 准确率引用 `execution_accuracy`，同时保留 `intent_macro_accuracy` 防止近义表达抬高分数。
- 并行收益引用 `trace_analysis.json.parallel_recall`，并使用“相较串行估算”限定语。
- 缓存命中率区分 disabled、cold、warm；暖缓存只能描述精确重复上限。
- 稳定性引用 `benchmark.json` 的原始 50 条请求、技术错误分类、P95 和吞吐量。
- 不把当前小数据集结果表述为大数据量 MySQL 查询性能提升。

用户运行后，需要保留对应 `eval/reports/<run_id>/` 和 `traces/eval/<run_id>/`。后续结论应由这些原始文件计算，不能手工估算或沿用旧的 55 条评测数字。
