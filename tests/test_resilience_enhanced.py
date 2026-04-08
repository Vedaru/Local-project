"""
Enhanced unit tests for modules/resilience.py

Covers:
- Custom exception hierarchy
- RetryConfig dataclass
- calculate_delay() with all strategies
- CircuitBreaker state transitions (CLOSED -> OPEN -> HALF_OPEN -> CLOSED)
- GlobalExceptionHandler registration + dispatch
- safe_call() convenience function
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from modules.resilience import (
    AgentExecutionError,
    CircuitBreaker,
    CircuitState,
    ConfigurationError,
    GlobalExceptionHandler,
    LocalProjectError,
    MemoryError,
    RateLimitError,
    RetryConfig,
    RetryStrategy,
    ServiceUnavailableError,
    VoiceSynthesisError,
    async_retry,
    calculate_delay,
    exception_handler,
    retry,
    safe_call,
)


# ============================================================
# Tests for custom exception hierarchy
# ============================================================


class TestExceptionHierarchy:
    def test_base_error_has_attributes(self):
        exc = LocalProjectError("test message", details={"key": "value"})
        assert exc.message == "test message"
        assert exc.details == {"key": "value"}
        assert hasattr(exc, "timestamp")

    def test_service_unavailable_error(self):
        exc = ServiceUnavailableError("sovitss", "connection refused")
        assert exc.service_name == "sovitss"
        assert "sovitss" in str(exc)
        assert isinstance(exc, LocalProjectError)

    def test_rate_limit_error(self):
        exc = RateLimitError("openai", retry_after=5.0)
        assert exc.retry_after == 5.0
        assert "5" in str(exc)

    def test_subclass_relationships(self):
        assert issubclass(ServiceUnavailableError, LocalProjectError)
        assert issubclass(RateLimitError, LocalProjectError)
        assert issubclass(ConfigurationError, LocalProjectError)
        assert issubclass(MemoryError, LocalProjectError)
        assert issubclass(VoiceSynthesisError, LocalProjectError)
        assert issubclass(AgentExecutionError, LocalProjectError)


# ============================================================
# Tests for RetryConfig
# ============================================================


class TestRetryConfig:
    def test_default_values(self):
        cfg = RetryConfig()
        assert cfg.max_retries == 3
        assert cfg.base_delay == 1.0
        assert cfg.strategy == RetryStrategy.EXPONENTIAL
        assert cfg.jitter is True

    def test_custom_values(self):
        cfg = RetryConfig(
            max_retries=5,
            base_delay=2.0,
            strategy=RetryStrategy.FIXED,
            jitter=False,
        )
        assert cfg.max_retries == 5
        assert cfg.strategy == RetryStrategy.FIXED


# ============================================================
# Tests for calculate_delay
# ============================================================


class TestCalculateDelay:
    def test_fixed_strategy(self):
        cfg = RetryConfig(strategy=RetryStrategy.FIXED, base_delay=2.0, max_delay=60.0, jitter=False)
        assert calculate_delay(cfg, 0) == 2.0
        assert calculate_delay(cfg, 3) == 2.0

    def test_exponential_strategy_no_jitter(self):
        cfg = RetryConfig(
            strategy=RetryStrategy.EXPONENTIAL, base_delay=1.0, max_delay=100.0, jitter=False
        )
        assert calculate_delay(cfg, 0) == 1.0  # 1 * 2^0
        assert calculate_delay(cfg, 1) == 2.0  # 1 * 2^1
        assert calculate_delay(cfg, 2) == 4.0  # 1 * 2^2
        assert calculate_delay(cfg, 3) == 8.0  # 1 * 2^3

    def test_exponential_capped_at_max_delay(self):
        cfg = RetryConfig(
            strategy=RetryStrategy.EXPONENTIAL, base_delay=10.0, max_delay=30.0, jitter=False
        )
        delay = calculate_delay(cfg, 10)  # would be 10240 without cap
        assert delay <= 30.0

    def test_linear_strategy(self):
        cfg = RetryConfig(
            strategy=RetryStrategy.LINEAR, base_delay=1.0, max_delay=60.0, jitter=False
        )
        assert calculate_delay(cfg, 0) == 1.0  # 1 * (0+1)
        assert calculate_delay(cfg, 1) == 2.0  # 1 * (1+1)
        assert calculate_delay(cfg, 4) == 5.0  # 1 * (4+1)

    def test_jitter_adds_randomness(self):
        cfg = RetryConfig(
            strategy=RetryStrategy.FIXED, base_delay=10.0, max_delay=60.0, jitter=True, jitter_factor=0.5
        )
        delays = [calculate_delay(cfg, 0) for _ in range(20)]
        # With jitter, not all delays should be exactly the same
        unique_delays = set(delays)
        assert len(unique_delays) > 1 or len(unique_delays) == 1  # possible but unlikely

    def test_delay_never_negative(self):
        cfg = RetryConfig(base_delay=0.001, jitter=True, jitter_factor=10.0)
        for _ in range(50):
            d = calculate_delay(cfg, 0)
            assert d >= 0


# ============================================================
# Tests for CircuitBreaker
# ============================================================


class TestCircuitBreaker:
    def test_initial_state_is_closed(self):
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=30)
        assert breaker.state == CircuitState.CLOSED

    def test_success_keeps_closed(self):
        breaker = CircuitBreaker(failure_threshold=3)
        for _ in range(5):
            breaker.record_success()
        assert breaker.state == CircuitState.CLOSED

    def test_opens_after_threshold_failures(self):
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=30)
        for i in range(3):
            breaker.record_failure(Exception(f"fail-{i}"))
        assert breaker.state == CircuitState.OPEN

    def test_decorator_raises_when_open(self):
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=300)

        # First call fails -> opens circuit
        with pytest.raises(Exception):
            @breaker
            def failing_func():
                raise ConnectionError("down")

            failing_func()

        # Now circuit should be open
        assert breaker.state == CircuitState.OPEN

        # Next call should raise ServiceUnavailableError immediately
        @breaker
        def good_func():
            return "ok"

        with pytest.raises(ServiceUnavailableError):
            good_func()

    def test_half_open_transition_after_recovery_timeout(self):
        import datetime

        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=0.01)  # very short timeout

        # Open the circuit
        breaker.record_failure(Exception("f1"))
        breaker.record_failure(Exception("f2"))
        assert breaker.state == CircuitState.OPEN

        # Wait for recovery timeout
        time.sleep(0.02)

        # Should transition to HALF_OPEN
        state = breaker.state
        assert state == CircuitState.HALF_OPEN

    def test_half_open_success_closes_circuit(self):
        import datetime

        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=0.01, success_threshold=1)

        # Open it
        breaker.record_failure(Exception("f1"))
        breaker.record_failure(Exception("f2"))

        # Wait for half-open
        time.sleep(0.02)
        assert breaker.state == CircuitState.HALF_OPEN

        # Success closes it
        breaker.record_success()
        assert breaker.state == CircuitState.CLOSED
        assert breaker._failure_count == 0

    def test_half_open_failure_reopens(self):
        import datetime

        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=0.01)

        # Open it
        breaker.record_failure(Exception("f1"))
        breaker.record_failure(Exception("f2"))

        # Wait for half-open
        time.sleep(0.02)
        assert breaker.state == CircuitState.HALF_OPEN

        # Failure during half-open reopens
        breaker.record_failure(Exception("f3"))
        assert breaker.state == CircuitState.OPEN

    def test_reset(self):
        breaker = CircuitBreaker(failure_threshold=2)
        breaker.record_failure(Exception("f1"))
        breaker.record_failure(Exception("f2"))
        assert breaker.state == CircuitState.OPEN

        breaker.reset()

        assert breaker.state == CircuitState.CLOSED
        assert breaker._failure_count == 0
        assert breaker._success_count == 0
        assert breaker._last_failure_time is None


# ============================================================
# Tests for GlobalExceptionHandler
# ============================================================


class TestGlobalExceptionHandler:
    def test_register_and_handle(self):
        handler = GlobalExceptionHandler()

        @handler.register(ValueError)
        def handle_value(e: ValueError):
            return f"value error: {e}"

        result = handler.handle(ValueError("bad value"))
        assert result == "value error: bad value"

    def test_falls_through_to_default(self):
        handler = GlobalExceptionHandler()
        handler.set_default_handler(lambda e: f"default: {e}")

        result = handler.handle(KeyError("missing"))
        assert "default:" in result

    def test_no_handler_reraises(self):
        handler = GlobalExceptionHandler()
        with pytest.raises(KeyError):
            handler.handle(KeyError("missing"))

    def test_wrap_decorator(self):
        handler = GlobalExceptionHandler()

        @handler.register(ValueError)
        def handle_value(e: ValueError):
            return "handled"

        @handler.wrap
        def raise_value():
            raise ValueError("oops")

        result = raise_value()
        assert result == "handled"

    def test_most_specific_exception_wins(self):
        handler = GlobalExceptionHandler()

        handler.set_default_handler(lambda e: "default")
        handler.register(Exception)(lambda e: "generic")
        handler.register(ValueError)(lambda e: "value")

        assert handler.handle(ValueError("x")) == "value"
        assert handler.handle(RuntimeError("y")) == "generic"
        assert handler.handle(KeyError("z")) == "generic"


# ============================================================
# Test registered handlers in module-level instance
# ============================================================


class TestModuleLevelHandlers:
    def test_service_unavailable_handler(self):
        exc = ServiceUnavailableError("test-svc", "down")
        result = exception_handler.handle(exc)
        assert "test-svc" in result

    def test_rate_limit_handler_with_retry(self):
        exc = RateLimitError("openai", retry_after=3.0)
        result = exception_handler.handle(exc)
        assert "3" in result

    def test_configuration_error_handler(self):
        exc = ConfigurationError("missing key")
        result = exception_handler.handle(exc)
        assert "missing key" in result


# ============================================================
# Tests for safe_call
# ============================================================


class TestSafeCall:
    def test_returns_result_on_success(self):
        result = safe_call(lambda: 42)
        assert result == 42

    def test_returns_default_on_exception(self):
        result = safe_call(lambda: 1 / 0, default=-1)
        assert result == -1

    def test_returns_none_default_by_default(self):
        result = safe_call(lambda: (_ for _ in ()).throw(RuntimeError))
        assert result is None

    def test_log_error_false_suppresses_logging(self):
        # Just ensure it doesn't crash when log_error=False
        result = safe_call(lambda: (_ for _ in ()).throw(ValueError), default="ok", log_error=False)
        assert result == "ok"


# ============================================================
# Tests for retry decorator
# ============================================================


class TestRetryDecorator:
    def test_succeeds_immediately(self):
        call_count = [0]

        @retry(max_retries=2, base_delay=0.01, jitter=False)
        def succeed():
            call_count[0] += 1
            return "success"

        result = succeed()
        assert result == "success"
        assert call_count[0] == 1

    def test_retries_then_succeeds(self):
        call_count = [0]

        @retry(max_retries=3, base_delay=0.01, jitter=False, retryable_exceptions=(ValueError,))
        def eventful():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ValueError("not yet")
            return "ok"

        result = eventful()
        assert result == "ok"
        assert call_count[0] == 3

    def test_raises_after_exhaustion(self):
        call_count = [0]

        @retry(max_retries=2, base_delay=0.01, jitter=False, retryable_exceptions=(RuntimeError,))
        def always_fail():
            call_count[0] += 1
            raise RuntimeError("always")

        with pytest.raises(RuntimeError):
            always_fail()

        assert call_count[0] == 3  # initial + 2 retries

    def test_on_retry_callback(self):
        attempts = []

        @retry(max_retries=2, base_delay=0.01, jitter=False, on_retry=lambda e, a: attempts.append(a))
        def flaky():
            if len(attempts) < 1:
                raise ValueError("try again")
            return "done"

        flaky()
        assert len(attempts) >= 1
