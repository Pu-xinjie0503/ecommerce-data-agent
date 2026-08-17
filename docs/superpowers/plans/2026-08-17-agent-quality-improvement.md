# Agent 质量改进与效果验证计划

## 目标

先修复测量工具，建立可信 baseline；再针对 Grounding、SQL 语义与修正循环改进 Agent；最后使用同一模型、Prompt、Case 和并发条件生成 candidate，形成可复算的前后对比。

## 当前状态

- [x] 固化 `evidence-v2` 运行事实与人工校正结论。
- [x] API 压测保留预期分支并输出 `branch_accuracy`。
- [x] 结果比较器消除同名列顺序导致的假阴性。
- [x] 离线单元测试、编译与格式检查通过。
- [ ] 用户运行测量工具修复后的 `baseline-v3`。
- [ ] 改进 Grounding、SQL 语义和修正循环。
- [ ] 运行 candidate 并生成最终改进报告。

## 阶段一：修复测量口径

### API 分支校验

修改文件：

- `eval/benchmark_api.py`
- `tests/test_api_benchmark_metrics.py`

要求：

- 加载并保留 Case 的 `branch`。
- 每条请求记录 `expected_branch`、`actual_branch` 和 `branch_matched`。
- 正常 Case 返回 Grounding、澄清或安全分支时必须判为分支不匹配。
- 汇总 `branch_matched_count`、`branch_mismatch_count` 和 `branch_accuracy`。
- Markdown 报告列出分支不匹配明细。

### 结果比较器

修改文件：

- `eval/result_comparator.py`
- `tests/test_result_comparator.py`

要求：

- 两侧列名集合相同时，始终按列名对齐，不受 SELECT 列顺序影响。
- 列名不同且允许忽略别名时，保留现有按位置比较的兼容行为。
- 不放宽列数、重复行、排序结果和数值容差约束。

### 阶段一验收

- 先观察新增测试按预期失败。
- 最小实现后运行对应测试和全量单元测试。
- 不修改 Grounding、Graph 路由或 Prompt。
- 用户重新运行，生成可信的 `baseline-v3`。

## 阶段二：改进 Agent 行为

### Grounding 候选提取

目标：区分维度取值、时间表达、聚合描述、分组描述和排序描述。

回归场景：

- 从 `2025 年 3 月华北地区` 中只提取地区值 `华北`。
- `按会员等级`、`商品`、`不同` 不作为具体字段值。
- `订单数最多的三个` 进入排序/Top N 语义，不作为品牌值。
- `火星牌` 等明确过滤值仍进入 Grounding，并在不存在时拦截。

### SQL 修正循环

目标：任何请求的 SQL 修正次数不超过 3 次。

要求：

- State 记录修正次数和最近一次失败 SQL。
- 相同 SQL 与相同错误连续出现时提前停止。
- 超过上限返回结构化错误、保存 Trace，不继续循环。
- Trace 根指标记录修正次数和终止原因。

### SQL 语义问题

重点回归：

- 商品与品类粒度不可混用。
- 省份、地区名称和 `region_id` 不可混用。
- 会员等级不可退化为 `customer_id`。
- 品牌 Top 3 必须按品牌分组并正确排序、LIMIT。

## 阶段三：验证提升

运行顺序：

1. 单元测试。
2. 90 条开发集，用于定位和迭代。
3. 30 条隔离测试集，只用于 baseline/candidate 验收。
4. 10 并发、50 请求固定 API 压测。
5. disabled/cold/warm 缓存消融与 Trace 分析。

可比条件：

- 模型、温度一致。
- Prompt SHA-256 一致；若优化目标就是 Prompt，必须明确记录 Prompt 变更并只将其作为候选变量。
- Case SHA-256 一致。
- API URL、并发数、请求数和预热数一致。
- baseline 与 candidate 均保留逐 Case 和逐请求原始记录。

## 验收指标

| 指标 | Evidence V2 | Candidate 目标 |
|---|---:|---:|
| API 技术错误率 | 0% | 保持 0% |
| API 分支命中率 | 70%（人工校正） | 至少 90% |
| 正常问数 Grounding 误拦截 | 15/25 | 0/25 |
| 预期业务分支命中 | 25/25 | 保持 25/25 |
| SQL 最大修正次数 | 约 99 | 不超过 3 |
| 单 Case 异常最大耗时 | 98.81 秒 | 不再出现循环型长尾 |
| Execution Accuracy | 旧值不可用 | 使用修复后的 baseline 计算提升 |

## 最终改进报告模板

每个问题使用相同结构记录：

1. 问题现象与影响范围。
2. Case、Trace 和原始指标证据。
3. 根因定位过程。
4. 修改文件与解决方法。
5. 新增回归测试。
6. baseline 指标。
7. candidate 指标。
8. 绝对变化、相对变化与统计口径。
9. 剩余限制和不能外推的结论。

最终报告至少包含 Grounding、SQL 语义、修正循环、准确率、延迟、缓存与 API 稳定性七个部分。
