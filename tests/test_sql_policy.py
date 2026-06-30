import unittest

from app.security.sql_policy import SQLPolicyViolation, enforce_sql_policy


class TestSQLPolicy(unittest.TestCase):
    def test_append_limit_when_missing(self):
        result = enforce_sql_policy("SELECT * FROM fact_order", max_limit=100)

        self.assertEqual(result.sql, "SELECT * FROM fact_order LIMIT 100")
        self.assertTrue(result.warnings)

    def test_cap_large_limit(self):
        result = enforce_sql_policy("SELECT * FROM fact_order LIMIT 1000", max_limit=100)

        self.assertEqual(result.sql, "SELECT * FROM fact_order LIMIT 100")

    def test_reject_dangerous_sql(self):
        with self.assertRaises(SQLPolicyViolation):
            enforce_sql_policy("SELECT * FROM fact_order WHERE order_id IN (DELETE FROM t)")

    def test_reject_sensitive_field(self):
        with self.assertRaises(SQLPolicyViolation):
            enforce_sql_policy("SELECT password FROM dim_customer")


if __name__ == "__main__":
    unittest.main()

