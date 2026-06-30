"""轻量进程内熔断器。

用于本地原型项目中的外部依赖保护：连续失败后短时间跳过弱依赖调用，
避免每次请求都阻塞在已知不可用的服务上。
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import time
from typing import Optional, TypeVar


T = TypeVar("T")


class CircuitBreakerOpen(RuntimeError):
    """依赖处于熔断打开状态。"""


@dataclass
class CircuitBreaker:
    """按连续失败次数和冷却时间控制依赖调用。"""

    name: str
    failure_threshold: int = 3
    recovery_timeout_seconds: float = 30.0
    failure_count: int = 0
    opened_at: Optional[float] = None

    def allow_request(self) -> bool:
        if self.opened_at is None:
            return True

        if time.monotonic() - self.opened_at >= self.recovery_timeout_seconds:
            return True

        return False

    def record_success(self) -> None:
        self.failure_count = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.opened_at = time.monotonic()

    def assert_allow_request(self) -> None:
        if not self.allow_request():
            raise CircuitBreakerOpen(f"{self.name} 处于熔断状态，暂时跳过调用。")


_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(name: str) -> CircuitBreaker:
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(name=name)
    return _breakers[name]


async def call_with_circuit_breaker(
    name: str,
    operation: Callable[[], Awaitable[T]],
) -> T:
    """在熔断保护下调用异步外部依赖。"""

    breaker = get_circuit_breaker(name)
    breaker.assert_allow_request()

    try:
        result = await operation()
    except Exception:
        breaker.record_failure()
        raise

    breaker.record_success()
    return result
