# 电商问数 Agent 评测证据化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可复现的 NL2SQL 结果等价评测、Trace 性能证据、缓存消融和 API 稳定性报告，使后续运行结果可以直接支持简历量化结论。

**Architecture:** 将纯离线的结果比较、指标聚合和实验可比性校验拆成独立模块，由现有 `run_eval.py` 负责调用 Agent 和 Gold SQL。Trace 请求级保存实验上下文，节点级保存耗时和缓存增量；分析脚本只消费原始 JSON，不依赖人工整理。

**Tech Stack:** Python 3.9+、pytest、PyYAML、LangGraph、SQLAlchemy、现有 Trace JSON。

---

### Task 1: 结果等价比较器

**Files:**
- Create: `eval/result_comparator.py`
- Create: `tests/test_result_comparator.py`

- [ ] 先编写失败测试，覆盖空值、Decimal/浮点容差、忽略行顺序、保留行顺序、列缺失和重复行。
- [ ] 运行 `uv run pytest tests/test_result_comparator.py -q`，确认因模块缺失而失败。
- [ ] 实现 `compare_results(actual, expected, ordered=False, tolerance=1e-6)`，返回结构化比较结果和失败原因。
- [ ] 再次运行测试，确认全部通过。

### Task 2: 分类指标与实验可比性

**Files:**
- Create: `eval/metrics.py`
- Create: `eval/experiment.py`
- Create: `tests/test_eval_metrics.py`
- Create: `tests/test_experiment.py`

- [ ] 先编写失败测试，覆盖 Execution Accuracy、按意图宏平均、分类统计、延迟分位数和零样本边界。
- [ ] 编写失败测试，要求模型、Prompt 哈希、Case 哈希和缓存模式之外的关键参数一致才允许比较。
- [ ] 运行两个测试文件并确认预期失败。
- [ ] 实现纯函数指标聚合、文件 SHA-256、实验元数据和可比性校验。
- [ ] 运行测试并确认通过。

### Task 3: 缓存控制与统计

**Files:**
- Modify: `app/clients/embedding_client_manager.py`
- Modify: `app/agent/nodes/keyword_expansion_cache.py`
- Modify: `app/conf/app_config.py`
- Modify: `conf/app_config.yaml`
- Create: `tests/test_cache_control.py`

- [ ] 先编写失败测试，验证 disabled 模式不读写缓存、clear 同时清空内容和统计、快照包含命中率。
- [ ] 运行测试确认失败原因是缺少缓存控制接口。
- [ ] 增加统一的 `enabled`、`clear_cache(reset_stats=True)` 和稳定统计快照。
- [ ] 运行缓存测试与既有测试，确认通过。

### Task 4: Trace 请求级实验元数据

**Files:**
- Modify: `app/observability/trace_schema.py`
- Modify: `app/observability/trace_manager.py`
- Modify: `app/agent/graph.py`
- Create: `tests/test_trace_metrics.py`

- [ ] 先编写失败测试，验证 Trace 保存 `experiment`、请求级 `metrics` 和节点缓存统计。
- [ ] 运行测试确认失败。
- [ ] 扩展 `TraceManager`，允许注入实验元数据并在结束时生成节点数、失败节点数、缓存总计和三路召回原始时间戳。
- [ ] 保持 Trace 摘要截断和敏感数据边界不变。
- [ ] 运行 Trace 与全量单元测试。

### Task 5: Trace 性能分析

**Files:**
- Modify: `eval/analyze_trace_latency.py`
- Create: `tests/test_trace_analysis.py`

- [ ] 先编写失败测试，使用固定 Trace Fixture 验证串行估算、并行墙钟、节省毫秒和节省比例。
- [ ] 运行测试确认失败。
- [ ] 实现缺失节点识别、Case 级明细、均值及 P50/P90/P95 汇总。
- [ ] 运行测试确认通过。

### Task 6: 评测执行入口

**Files:**
- Modify: `eval/run_eval.py`
- Create: `tests/test_eval_case_validation.py`

- [ ] 先编写失败测试，验证普通 Case 必须有 `gold_sql`，分支 Case 必须有确定性预期，意图不能跨开发集和测试集。
- [ ] 运行测试确认失败。
- [ ] 接入 Gold SQL 执行、结果等价比较、分类指标、实验元数据和按运行 ID 隔离的报告目录。
- [ ] 保留旧 Case 字段作为诊断信息，不再让字符串片段覆盖结果等价结论。
- [ ] 运行离线单元测试；不启动 Docker 时跳过真实 Agent 集成运行。

### Task 7: 分层评测集

**Files:**
- Create: `eval/cases_dev.yaml`
- Create: `eval/cases_test.yaml`
- Create: `eval/benchmark_cases.yaml`

- [ ] 依据现有 MySQL Schema 编写 40 个意图及 Gold SQL。
- [ ] 为每个意图补充 3 种自然语言表达，并记录 category、ordered_result 和 tolerance。
- [ ] 使用加载校验测试确认 120 条表达、意图级隔离、ID 唯一和 Gold SQL 完整。

### Task 8: API Benchmark 与统一运行脚本

**Files:**
- Modify: `eval/benchmark_api.py`
- Create: `eval/compare_runs.py`
- Create: `eval/run_benchmarks.py`
- Create: `tests/test_api_benchmark_metrics.py`

- [ ] 先编写失败测试，覆盖 warmup 排除、吞吐量、技术错误率、分位数和不兼容运行拒绝比较。
- [ ] 运行测试确认失败。
- [ ] 增加固定 Case 文件、预热请求、运行 ID、原始请求明细和统一报告目录。
- [ ] 实现关闭/冷/暖缓存运行编排与 A/B 报告生成，但不在未启动 Docker 时自动运行外部依赖。
- [ ] 运行测试确认通过。

### Task 9: 文档与最终验证

**Files:**
- Modify: `eval/README.md`
- Modify: `README.md`

- [ ] 记录 Docker 启动后的完整运行顺序、预期控制台日志、报告字段和简历引用规则。
- [ ] 运行 `uv run pytest tests -q`。
- [ ] 运行 `uv run python -m compileall app eval tests`。
- [ ] 检查 `git diff --check` 和 `git status --short`。
- [ ] 明确说明未运行的 Docker/LLM 集成评测，并等待用户运行后分析 Trace。

