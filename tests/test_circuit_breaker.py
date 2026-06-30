import unittest

from app.resilience.circuit_breaker import CircuitBreaker, CircuitBreakerOpen


class TestCircuitBreaker(unittest.TestCase):
    def test_open_after_consecutive_failures(self):
        breaker = CircuitBreaker(
            name="test_dependency",
            failure_threshold=2,
            recovery_timeout_seconds=30,
        )

        breaker.record_failure()
        self.assertTrue(breaker.allow_request())

        breaker.record_failure()
        self.assertFalse(breaker.allow_request())

        with self.assertRaises(CircuitBreakerOpen):
            breaker.assert_allow_request()

    def test_recover_after_success(self):
        breaker = CircuitBreaker(name="test_dependency", failure_threshold=1)

        breaker.record_failure()
        self.assertFalse(breaker.allow_request())

        breaker.record_success()
        self.assertTrue(breaker.allow_request())
        self.assertEqual(breaker.failure_count, 0)

    def test_allow_probe_after_cooldown(self):
        breaker = CircuitBreaker(
            name="test_dependency",
            failure_threshold=1,
            recovery_timeout_seconds=0,
        )

        breaker.record_failure()

        self.assertTrue(breaker.allow_request())


if __name__ == "__main__":
    unittest.main()

