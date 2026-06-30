import unittest

from app.observability.sql_risk_analyzer import analyze_sql_risk


class TestSQLRiskAnalyzer(unittest.TestCase):
    def test_detect_full_scan_and_build_index_suggestion(self):
        sql = """
        SELECT SUM(t.order_amount)
        FROM fact_order t
        JOIN dim_region r ON t.region_id = r.region_id
        WHERE t.date_id >= 20250101
        GROUP BY r.region_name
        """
        explain_rows = [
            {
                "type": "ALL",
                "key": None,
                "rows": 50000,
                "Extra": "Using temporary; Using filesort",
            }
        ]

        result = analyze_sql_risk(sql, explain_rows)

        self.assertIn("FULL_TABLE_SCAN", result.risk_flags)
        self.assertIn("NO_INDEX_USED", result.risk_flags)
        self.assertIn("LARGE_ROWS_SCAN", result.risk_flags)
        self.assertTrue(result.index_suggestions)
        self.assertTrue(result.rewrite_suggestions)


if __name__ == "__main__":
    unittest.main()

