import unittest

from app.utils.sql_parser import extract_sql


class TestSqlParser(unittest.TestCase):
    def test_extract_plain_select_sql(self):
        self.assertEqual(
            extract_sql("SELECT SUM(order_amount) FROM fact_order;"),
            "SELECT SUM(order_amount) FROM fact_order",
        )

    def test_extract_markdown_sql(self):
        raw_sql = """```sql
SELECT * FROM fact_order;
```"""

        self.assertEqual(extract_sql(raw_sql), "SELECT * FROM fact_order")

    def test_extract_sql_after_explanation(self):
        raw_sql = """下面是 SQL：
SELECT * FROM fact_order;
"""

        self.assertEqual(extract_sql(raw_sql), "SELECT * FROM fact_order")

    def test_cut_mysql_optimizer_output(self):
        raw_sql = """
SELECT SUM(t1.order_amount) AS total_sales
FROM fact_order t1
JOIN dim_region t2 ON t1.region_id = t2.region_id
WHERE t2.region_name = 'HB'
/* select#1 */ select sum(`dw`.`t1`.`order_amount`) AS `total_sales` from `dw`.`fact_order` `t1`
"""

        self.assertEqual(
            extract_sql(raw_sql),
            "SELECT SUM(t1.order_amount) AS total_sales FROM fact_order t1 JOIN dim_region t2 ON t1.region_id = t2.region_id WHERE t2.region_name = 'HB'",
        )

    def test_extract_first_statement_only(self):
        self.assertEqual(
            extract_sql("SELECT * FROM fact_order; SELECT * FROM dim_region;"),
            "SELECT * FROM fact_order",
        )

    def test_reject_delete_sql(self):
        with self.assertRaises(ValueError):
            extract_sql("DELETE FROM fact_order;")

    def test_reject_update_sql(self):
        with self.assertRaises(ValueError):
            extract_sql("UPDATE fact_order SET order_amount = 0;")

    def test_reject_drop_sql(self):
        with self.assertRaises(ValueError):
            extract_sql("DROP TABLE fact_order;")

    def test_reject_insert_sql(self):
        with self.assertRaises(ValueError):
            extract_sql("INSERT INTO fact_order(order_id) VALUES (1);")


if __name__ == "__main__":
    unittest.main()
