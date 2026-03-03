"""
Unit tests for modules/resilience.py
"""

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.resilience import (
    CircuitBreaker,
    CircuitState,
    LocalProjectError,
    RateLimitError,
    RetryConfig,
    RetryStrategy,
    ServiceUnavailableError,
    calculate_delay,
    exception_handler,
    retry,
    safe_call,
)


class TestRetryDecorator:
    """Tests for retry decorator."""

    def test_retry_succeeds_first_try(self):
        """Test that successful call returns immediately."""
        call_count = 0

        @retry(max_retries=3)
        def successful_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = successful_func()
        assert result == "success"
        assert call_count == 1

    def test_retry_succeeds_after_failures(self):
        """Test that retry eventually succeeds."""
        call_count = 0

        @retry(max_retries=3, base_delay=0.01)
        def eventually_succeeds():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Not yet")
            return "success"

        result = eventually_succeeds()
        assert result == "success"
        assert call_count == 3

    def test_retry_exhausts_retries(self):
        """Test that exception is raised after all retries fail."""

        @retry(max_retries=2, base_delay=0.01)
        def always_fails():
            raise ValueError("Always fails")

        with pytest.raises(ValueError, match="Always fails"):
            always_fails()

    def test_retry_respects_retryable_exceptions(self):
        """Test that only specified exceptions trigger retry."""

        @retry(max_retries=3, base_delay=0.01, retryable_exceptions=(ValueError,))
        def raises_type_error():
            raise TypeError("Not retryable")

        with pytest.raises(TypeError):
            raises_type_error()

    def test_retry_calls_on_retry_callback(self):
        """Test that on_retry callback is called."""
        callback_calls = []
        call_count = 0

        def on_retry_callback(exc, attempt):
            callback_calls.append((str(exc), attempt))

        @retry(max_retries=2, base_delay=0.01, on_retry=on_retry_callback)
        def fails_once():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("First failure")
            return "success"

        result = fails_once()
        assert result == "success"
        assert len(callback_calls) == 1
        assert "First failure" in callback_calls[0][0]


class TestCalculateDelay:
    """Tests for delay calculation."""

    def test_fixed_delay(self):
        """Test fixed delay strategy."""
        config = RetryConfig(
            base_delay=1.0,
            strategy=RetryStrategy.FIXED,
            jitter=False,
        )
        assert calculate_delay(config, 0) == 1.0
        assert calculate_delay(config, 1) == 1.0
        assert calculate_delay(config, 5) == 1.0

    def test_exponential_delay(self):
        """Test exponential backoff strategy."""
        config = RetryConfig(
            base_delay=1.0,
            max_delay=100.0,
            strategy=RetryStrategy.EXPONENTIAL,
            jitter=False,
        )
        assert calculate_delay(config, 0) == 1.0
        assert calculate_delay(config, 1) == 2.0
        assert calculate_delay(config, 2) == 4.0
        assert calculate_delay(config, 3) == 8.0

    def test_linear_delay(self):
        """Test linear delay strategy."""
        config = RetryConfig(
            base_delay=1.0,
            strategy=RetryStrategy.LINEAR,
            jitter=False,
        )
        assert calculate_delay(config, 0) == 1.0
        assert calculate_delay(config, 1) == 2.0
        assert calculate_delay(config, 2) == 3.0

    def test_max_delay_limit(self):
        """Test that delay is capped at max_delay."""
        config = RetryConfig(
            base_delay=1.0,
            max_delay=5.0,
            strategy=RetryStrategy.EXPONENTIAL,
            jitter=False,
        )
        assert calculate_delay(config, 10) == 5.0


class TestCircuitBreaker:
    """Tests for circuit breaker."""

    def test_circuit_starts_closed(self):
        """Test that circuit starts in closed state."""
        breaker = CircuitBreaker(failure_threshold=3)
        assert breaker.state == CircuitState.CLOSED

    def test_circuit_opens_after_threshold(self):
        """Test that circuit opens after failure threshold."""
        breaker = CircuitBreaker(failure_threshold=3)

        @breaker
        def failing_func():
            raise ValueError("Failure")

        for _ in range(3):
            with pytest.raises(ValueError):
                failing_func()

        assert breaker.state == CircuitState.OPEN

    def test_circuit_rejects_when_open(self):
        """Test that calls are rejected when circuit is open."""
        breaker = CircuitBreaker(failure_threshold=1)

        @breaker
        def failing_func():
            raise ValueError("Failure")

        with pytest.raises(ValueError):
            failing_func()

        with pytest.raises(ServiceUnavailableError):
            failing_func()

    def test_circuit_resets_on_success(self):
        """Test that failure count resets on success."""
        breaker = CircuitBreaker(failure_threshold=3)
        call_count = 0

        @breaker
        def sometimes_fails():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Failure")
            return "success"

        with pytest.raises(ValueError):
            sometimes_fails()
        with pytest.raises(ValueError):
            sometimes_fails()

        # Third call succeeds
        result = sometimes_fails()
        assert result == "success"
        assert breaker.state == CircuitState.CLOSED


class TestCustomExceptions:
    """Tests for custom exception classes."""

    def test_local_project_error(self):
        """Test LocalProjectError creation."""
        error = LocalProjectError("Test error", {"key": "value"})
        assert error.message == "Test error"
        assert error.details == {"key": "value"}
        assert error.timestamp is not None

    def test_service_unavailable_error(self):
        """Test ServiceUnavailableError creation."""
        error = ServiceUnavailableError("test-service", "Connection refused")
        assert "test-service" in str(error)
        assert error.service_name == "test-service"

    def test_rate_limit_error(self):
        """Test RateLimitError creation."""
        error = RateLimitError("api", retry_after=30)
        assert error.retry_after == 30
        assert "30" in str(error)


class TestSafeCall:
    """Tests for safe_call function."""

    def test_safe_call_returns_result(self):
        """Test that safe_call returns function result."""
        result = safe_call(lambda: 42)
        assert result == 42

    def test_safe_call_returns_default_on_error(self):
        """Test that safe_call returns default on error."""
        result = safe_call(lambda: 1 / 0, default="error")
        assert result == "error"

    def test_safe_call_with_args(self):
        """Test safe_call with function arguments."""
        result = safe_call(lambda x, y: x + y, 1, 2)
        assert result == 3

    def test_safe_call_with_kwargs(self):
        """Test safe_call with keyword arguments."""
        result = safe_call(lambda x, y=10: x + y, 5, y=20)
        assert result == 25
