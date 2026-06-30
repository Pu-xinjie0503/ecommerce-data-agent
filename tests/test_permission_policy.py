import unittest

from app.security.permission_policy import (
    PermissionContext,
    PermissionDenied,
    apply_permission_policy,
)


class TestPermissionPolicy(unittest.TestCase):
    def test_admin_does_not_inject_permission(self):
        sql = "SELECT * FROM fact_order"

        result = apply_permission_policy(sql, PermissionContext(role="admin"))

        self.assertEqual(result.sql, sql)

    def test_inject_region_id_permission_for_fact_table(self):
        sql = "SELECT SUM(t.order_amount) FROM fact_order t WHERE t.date_id >= 20250101"
        permission = PermissionContext(
            user_id="u001",
            role="region_operator",
            allowed_region_ids=[1, 2],
        )

        result = apply_permission_policy(sql, permission)

        self.assertIn("t.region_id IN (1, 2)", result.sql)
        self.assertIn("AND", result.sql)

    def test_inject_region_name_permission_with_subquery(self):
        sql = "SELECT SUM(order_amount) FROM fact_order"
        permission = PermissionContext(
            user_id="u001",
            role="region_operator",
            allowed_region_names=["华北", "华东"],
        )

        result = apply_permission_policy(sql, permission)

        self.assertIn("SELECT region_id FROM dim_region", result.sql)
        self.assertIn("'华北'", result.sql)

    def test_reject_non_admin_without_scope(self):
        with self.assertRaises(PermissionDenied):
            apply_permission_policy(
                "SELECT * FROM fact_order",
                PermissionContext(role="region_operator"),
            )


if __name__ == "__main__":
    unittest.main()

