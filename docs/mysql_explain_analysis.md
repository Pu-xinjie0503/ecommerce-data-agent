# MySQL EXPLAIN 分析

> 本文档先整理 8 条典型问数 SQL 的 EXPLAIN 观察点、潜在风险和候选索引。当前不伪造实测 EXPLAIN 输出；如果本地 MySQL 环境已启动，应将实际 `EXPLAIN` 结果补充到对应章节。

## 1. 观察字段

每条 SQL 都重点观察以下字段：

| 字段 | 关注点 |
|---|---|
| `type` | 是否出现 `ALL` 全表扫描 |
| `possible_keys` | 优化器认为可能使用哪些索引 |
| `key` | 实际使用了哪个索引 |
| `rows` | 预估扫描行数 |
| `filtered` | 过滤比例 |
| `Extra` | 是否出现 `Using temporary`、`Using filesort` |

当前项目已在 `validate_sql` 阶段采集 EXPLAIN，并将以下风险作为 warning 写入 Trace：

- `FULL_TABLE_SCAN`
- `NO_INDEX_USED`
- `LARGE_ROWS_SCAN`
- `USING_TEMPORARY`
- `USING_FILESORT`

## 2. 华北地区销售额

### 查询目标

统计华北地区的总销售额。

### 示例 SQL

```sql
SELECT SUM(f.order_amount) AS total_sales
FROM fact_order f
JOIN dim_region r ON f.region_id = r.region_id
WHERE r.region_name = '华北';
```

### 当前索引条件下的预期风险

- `dim_region.region_name` 当前没有二级索引；
- `fact_order.region_id` 当前没有二级索引；
- 当 `fact_order` 数据量增长后，JOIN 可能扫描大量事实表数据。

### 候选索引

```sql
CREATE INDEX idx_dim_region_region_name ON dim_region(region_name);
CREATE INDEX idx_fact_order_region_id ON fact_order(region_id);
```

### 验证重点

- `dim_region` 是否命中 `idx_dim_region_region_name`；
- `fact_order` 是否命中 `idx_fact_order_region_id`；
- `rows` 是否下降。

## 3. 美的品牌销售额

### 查询目标

统计美的品牌的总销售额。

### 示例 SQL

```sql
SELECT SUM(f.order_amount) AS total_sales
FROM fact_order f
JOIN dim_product p ON f.product_id = p.product_id
WHERE p.brand = '美的';
```

### 当前索引条件下的预期风险

- `dim_product.brand` 当前没有二级索引；
- `fact_order.product_id` 当前没有二级索引。

### 候选索引

```sql
CREATE INDEX idx_dim_product_brand ON dim_product(brand);
CREATE INDEX idx_fact_order_product_id ON fact_order(product_id);
```

### 验证重点

- 商品维表是否先通过 brand 过滤；
- 过滤后的 product_id 回表 JOIN 是否命中事实表索引。

## 4. 2025 年 Q1 销售额

### 查询目标

统计 2025 年第一季度的总销售额。

### 示例 SQL

```sql
SELECT SUM(f.order_amount) AS total_sales
FROM fact_order f
JOIN dim_date d ON f.date_id = d.date_id
WHERE d.year = 2025 AND d.quarter = 'Q1';
```

### 当前索引条件下的预期风险

- `dim_date(year, quarter)` 当前没有联合索引；
- `fact_order.date_id` 当前没有二级索引。

### 候选索引

```sql
CREATE INDEX idx_dim_date_year_quarter ON dim_date(year, quarter);
CREATE INDEX idx_fact_order_date_id ON fact_order(date_id);
```

### 验证重点

- `dim_date` 是否命中 `(year, quarter)`；
- `fact_order` 是否通过 `date_id` 索引 JOIN。

## 5. 按大区统计 GMV

### 查询目标

按大区统计总 GMV。

### 示例 SQL

```sql
SELECT r.region_name, SUM(f.order_amount) AS gmv
FROM fact_order f
JOIN dim_region r ON f.region_id = r.region_id
GROUP BY r.region_name;
```

### 当前索引条件下的预期风险

- `fact_order.region_id` 当前没有索引；
- `GROUP BY r.region_name` 可能出现 `Using temporary`；
- 如果事实表很大，可能先扫描全表再聚合。

### 候选索引

```sql
CREATE INDEX idx_fact_order_region_id ON fact_order(region_id);
CREATE INDEX idx_dim_region_region_name ON dim_region(region_name);
```

### 验证重点

- JOIN 是否命中 `fact_order.region_id`；
- `Extra` 是否出现 `Using temporary` 或 `Using filesort`；
- 是否需要通过 SQL 改写减少排序成本。

## 6. 按会员等级统计订单数

### 查询目标

按会员等级统计订单数。

### 示例 SQL

```sql
SELECT c.member_level, COUNT(*) AS order_count
FROM fact_order f
JOIN dim_customer c ON f.customer_id = c.customer_id
GROUP BY c.member_level;
```

### 当前索引条件下的预期风险

- `fact_order.customer_id` 当前没有索引；
- `dim_customer.member_level` 当前没有索引；
- `GROUP BY` 可能出现临时表。

### 候选索引

```sql
CREATE INDEX idx_fact_order_customer_id ON fact_order(customer_id);
CREATE INDEX idx_dim_customer_member_level ON dim_customer(member_level);
```

### 验证重点

- JOIN 是否命中 `fact_order.customer_id`；
- `member_level` 索引是否对当前数据量有实际收益；
- `Extra` 是否出现 `Using temporary`。

## 7. 按品类统计销量和销售额

### 查询目标

按商品品类统计销量和销售额。

### 示例 SQL

```sql
SELECT p.category,
       SUM(f.order_quantity) AS total_quantity,
       SUM(f.order_amount) AS total_sales
FROM fact_order f
JOIN dim_product p ON f.product_id = p.product_id
GROUP BY p.category;
```

### 当前索引条件下的预期风险

- `fact_order.product_id` 当前没有索引；
- `dim_product.category` 当前没有索引；
- 分组聚合可能出现临时表。

### 候选索引

```sql
CREATE INDEX idx_fact_order_product_id ON fact_order(product_id);
CREATE INDEX idx_dim_product_category ON dim_product(category);
```

### 验证重点

- JOIN 是否命中商品索引；
- `GROUP BY category` 是否需要额外优化；
- 是否有 `Using temporary` 或 `Using filesort`。

## 8. Top 品牌销售额

### 查询目标

统计销售额最高的品牌。

### 示例 SQL

```sql
SELECT p.brand, SUM(f.order_amount) AS total_sales
FROM fact_order f
JOIN dim_product p ON f.product_id = p.product_id
GROUP BY p.brand
ORDER BY total_sales DESC
LIMIT 10;
```

### 当前索引条件下的预期风险

- 聚合结果按表达式排序，可能出现 `Using filesort`；
- `fact_order.product_id` 当前没有索引；
- `dim_product.brand` 当前没有索引。

### 候选索引

```sql
CREATE INDEX idx_fact_order_product_id ON fact_order(product_id);
CREATE INDEX idx_dim_product_brand ON dim_product(brand);
```

### 验证重点

- `ORDER BY SUM(...)` 通常难以仅靠普通索引完全避免排序；
- 高频场景可考虑预聚合表，但本阶段不做 SQL 结果缓存或预聚合落地。

## 9. 地区 + 时间 + 品牌组合查询

### 查询目标

统计某地区、某时间范围、某品牌的销售额。

### 示例 SQL

```sql
SELECT SUM(f.order_amount) AS total_sales
FROM fact_order f
JOIN dim_region r ON f.region_id = r.region_id
JOIN dim_product p ON f.product_id = p.product_id
JOIN dim_date d ON f.date_id = d.date_id
WHERE r.region_name = '华北'
  AND p.brand = '美的'
  AND d.year = 2025
  AND d.quarter = 'Q1';
```

### 当前索引条件下的预期风险

- 多表 JOIN 叠加多个维度过滤；
- `fact_order.region_id`、`product_id`、`date_id` 当前都没有索引；
- 如果只建单列索引，优化器可能只能选择其中一个索引；
- 未来可能需要联合索引。

### 第一批候选索引

```sql
CREATE INDEX idx_fact_order_region_id ON fact_order(region_id);
CREATE INDEX idx_fact_order_product_id ON fact_order(product_id);
CREATE INDEX idx_fact_order_date_id ON fact_order(date_id);
CREATE INDEX idx_dim_region_region_name ON dim_region(region_name);
CREATE INDEX idx_dim_product_brand ON dim_product(brand);
CREATE INDEX idx_dim_date_year_quarter ON dim_date(year, quarter);
```

### 联合索引候选

```sql
CREATE INDEX idx_fact_order_region_date ON fact_order(region_id, date_id);
CREATE INDEX idx_fact_order_product_date ON fact_order(product_id, date_id);
CREATE INDEX idx_fact_order_date_region ON fact_order(date_id, region_id);
CREATE INDEX idx_fact_order_date_product ON fact_order(date_id, product_id);
```

### 为什么暂不直接添加联合索引

联合索引的顺序取决于真实查询模式和字段选择性。如果高频问题通常先限定时间，再按地区或品牌统计，`date_id` 放前面可能更合适；如果通常先限定地区或商品，再限定时间，则 `region_id` 或 `product_id` 放前面更合适。因此需要先采集典型 SQL 的 EXPLAIN 结果，再决定最终索引。

## 10. 后续实测补充模板

每条 SQL 实测后补充：

```text
EXPLAIN 执行时间：YYYY-MM-DD HH:mm:ss
当前索引版本：baseline / index_batch_1

type:
possible_keys:
key:
rows:
filtered:
Extra:

risk_flags:
结论：
下一步：
```
