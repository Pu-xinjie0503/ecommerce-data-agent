# MySQL 索引设计

## 1. 当前索引现状

当前项目的数仓初始化脚本位于 `docker/mysql/dw.sql`，Meta 初始化脚本位于 `docker/mysql/meta.sql`。

当前实际索引情况：

| 表 | 当前索引 | 说明 |
|---|---|---|
| `fact_order` | `order_id` 主键索引 | 事实表只有订单主键索引 |
| `dim_region` | `region_id` 主键索引 | 地区维表主键 |
| `dim_product` | `product_id` 主键索引 | 商品维表主键 |
| `dim_customer` | `customer_id` 主键索引 | 客户维表主键 |
| `dim_date` | `date_id` 主键索引 | 日期维表主键 |
| `table_info` | `id` 主键索引 | Meta 表 |
| `column_info` | `id` 主键索引 | Meta 表 |
| `metric_info` | `id` 主键索引 | Meta 表 |
| `column_metric` | `(column_id, metric_id)` 复合主键 | 字段指标关系表 |

当前没有发现额外二级索引、联合索引或显式外键索引。

## 2. 索引设计原则

本项目不应该一口气给所有字段都加索引，而应该按以下顺序判断：

1. 该字段是否出现在高频 SQL 的 `WHERE`、`JOIN`、`GROUP BY`、`ORDER BY` 中；
2. 该字段选择性是否足够高；
3. 当前 `EXPLAIN` 是否出现 `type = ALL`、`key = NULL`、`rows` 较大、`Using temporary` 或 `Using filesort`；
4. 建索引后是否能明显减少扫描行数；
5. 是否存在与已有索引重复或前缀冗余的问题。

索引优化必须通过典型 SQL 的 `EXPLAIN` 验证，而不是只凭经验添加。

## 3. 第一批候选索引

### 3.1 `fact_order` JOIN key 索引

`fact_order` 是事实表，数据量增长后最容易成为瓶颈。第一批候选索引应优先覆盖四个 JOIN key：

```sql
CREATE INDEX idx_fact_order_region_id ON fact_order(region_id);
CREATE INDEX idx_fact_order_product_id ON fact_order(product_id);
CREATE INDEX idx_fact_order_customer_id ON fact_order(customer_id);
CREATE INDEX idx_fact_order_date_id ON fact_order(date_id);
```

适用查询：

- 按地区过滤销售额；
- 按品牌或品类过滤销售额；
- 按会员等级聚合订单数；
- 按年份、季度、月份过滤销售额；
- 多维表 JOIN 后汇总 `order_amount` 或 `order_quantity`。

预期收益：

- 降低事实表 JOIN 和过滤阶段的扫描行数；
- 降低 `fact_order` 全表扫描概率；
- 为后续联合索引选择提供基线。

风险：

- 如果数据量很小，收益不明显；
- 如果后续添加联合索引，部分单列索引可能变成冗余索引。

### 3.2 `dim_region.region_name`

```sql
CREATE INDEX idx_dim_region_region_name ON dim_region(region_name);
```

适用查询：

- 华北地区销售额；
- 华东地区订单数；
- 按大区统计 GMV。

说明：自然语言问题常使用“华北”“华东”这类业务值，而不是 `region_id`。

### 3.3 `dim_product.brand` / `dim_product.category`

```sql
CREATE INDEX idx_dim_product_brand ON dim_product(brand);
CREATE INDEX idx_dim_product_category ON dim_product(category);
```

适用查询：

- 美的品牌销售额；
- 食品饮料品类销量；
- Top 品牌销售额；
- 按品类统计销量和销售额。

说明：品牌和品类是 NL2SQL 中高频过滤维度。

### 3.4 `dim_date(year, quarter)` / `dim_date(year, month)`

```sql
CREATE INDEX idx_dim_date_year_quarter ON dim_date(year, quarter);
CREATE INDEX idx_dim_date_year_month ON dim_date(year, month);
```

适用查询：

- 2025 年 Q1 销售额；
- 2025 年 3 月销售额；
- 某时间段下的地区或品牌销售额。

说明：自然语言通常按年月季度表达时间条件，而不是直接给出 `date_id`。

## 4. 联合索引候选方案

联合索引暂不直接落地，只作为候选方案，需要结合 `EXPLAIN` 和真实查询频率确认。

```sql
CREATE INDEX idx_fact_order_region_date ON fact_order(region_id, date_id);
CREATE INDEX idx_fact_order_product_date ON fact_order(product_id, date_id);
CREATE INDEX idx_fact_order_date_region ON fact_order(date_id, region_id);
CREATE INDEX idx_fact_order_date_product ON fact_order(date_id, product_id);
```

选择依据：

| 联合索引 | 适用查询 | 说明 |
|---|---|---|
| `(region_id, date_id)` | 某地区 + 时间过滤 | 如果先按地区限定，再按时间过滤 |
| `(date_id, region_id)` | 某时间范围内按地区统计 | 如果先按时间限定，再按地区分组或过滤 |
| `(product_id, date_id)` | 某品牌 / 商品 + 时间过滤 | 如果商品维表过滤后回到事实表 |
| `(date_id, product_id)` | 某时间范围内按商品统计 | 如果时间过滤更高频且选择性更好 |

联合索引顺序不是固定答案，需要通过以下信息决定：

- 真实高频查询中哪个字段先过滤；
- 字段选择性；
- `EXPLAIN` 中的 `key`、`rows` 和 `Extra`；
- 是否能同时覆盖 JOIN 和 WHERE；
- 是否会和单列索引产生冗余。

## 5. 验证方法

每条候选索引落地前后都应该对同一条 SQL 执行：

```sql
EXPLAIN <SQL>;
```

重点观察：

| 字段 | 判断标准 |
|---|---|
| `type` | 避免大表 `ALL` 全表扫描 |
| `possible_keys` | 是否出现候选索引 |
| `key` | 是否实际命中候选索引 |
| `rows` | 扫描行数是否下降 |
| `filtered` | 过滤比例是否改善 |
| `Extra` | 是否减少 `Using temporary` / `Using filesort` |

只有当 EXPLAIN 和查询频率都支持时，才建议真正把索引写入建表脚本或迁移脚本。
