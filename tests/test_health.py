"""
Unit tests for modules/health.py
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.health import (
    HealthChecker,
    HealthCheckResult,
    HealthStatus,
    SystemHealth,
    check_filesystem_health,
    check_sovits_health,
    check_tts_runtime_stats,
    check_web_fetch_runtime_stats,
)


class TestHealthCheckResult:
    """Tests for HealthCheckResult dataclass."""

    def test_health_check_result_creation(self):
        """Test creating a HealthCheckResult."""
        result = HealthCheckResult(
            service_name="test-service",
            status=HealthStatus.HEALTHY,
            message="All good",
        )
        assert result.service_name == "test-service"
        assert result.status == HealthStatus.HEALTHY
        assert result.message == "All good"

    def test_health_check_result_to_dict(self):
        """Test converting HealthCheckResult to dict."""
        result = HealthCheckResult(
            service_name="test",
            status=HealthStatus.HEALTHY,
            message="OK",
            response_time_ms=50.5,
        )
        d = result.to_dict()
        assert d["service"] == "test"
        assert d["status"] == "healthy"
        assert d["response_time_ms"] == 50.5


class TestSystemHealth:
    """Tests for SystemHealth dataclass."""

    def test_system_health_creation(self):
        """Test creating a SystemHealth object."""
        services = [
            HealthCheckResult("s1", HealthStatus.HEALTHY),
            HealthCheckResult("s2", HealthStatus.HEALTHY),
        ]
        health = SystemHealth(
            overall_status=HealthStatus.HEALTHY,
            services=services,
        )
        assert health.overall_status == HealthStatus.HEALTHY
        assert len(health.services) == 2

    def test_system_health_to_dict(self):
        """Test converting SystemHealth to dict."""
        services = [
            HealthCheckResult("s1", HealthStatus.HEALTHY),
        ]
        health = SystemHealth(
            overall_status=HealthStatus.HEALTHY,
            services=services,
        )
        d = health.to_dict()
        assert d["overall_status"] == "healthy"
        assert len(d["services"]) == 1


class TestHealthChecker:
    """Tests for HealthChecker class."""

    def test_register_and_check(self):
        """Test registering and running a health check."""
        checker = HealthChecker()

        def mock_check():
            return HealthCheckResult(
                service_name="mock",
                status=HealthStatus.HEALTHY,
            )

        checker.register("mock", mock_check)
        result = checker.check("mock")

        assert result.status == HealthStatus.HEALTHY

    def test_check_unregistered_service(self):
        """Test checking an unregistered service."""
        checker = HealthChecker()
        result = checker.check("nonexistent")

        assert result.status == HealthStatus.UNKNOWN
        assert "No health check registered" in result.message

    def test_check_all(self):
        """Test checking all registered services."""
        checker = HealthChecker()

        checker.register(
            "healthy",
            lambda: HealthCheckResult("healthy", HealthStatus.HEALTHY),
        )
        checker.register(
            "degraded",
            lambda: HealthCheckResult("degraded", HealthStatus.DEGRADED),
        )

        health = checker.check_all()

        assert len(health.services) == 2
        # Should be DEGRADED since not all services are HEALTHY
        assert health.overall_status == HealthStatus.DEGRADED

    def test_check_all_returns_unhealthy(self):
        """Test that UNHEALTHY status propagates correctly."""
        checker = HealthChecker()

        checker.register(
            "healthy",
            lambda: HealthCheckResult("healthy", HealthStatus.HEALTHY),
        )
        checker.register(
            "unhealthy",
            lambda: HealthCheckResult("unhealthy", HealthStatus.UNHEALTHY),
        )

        health = checker.check_all()
        assert health.overall_status == HealthStatus.UNHEALTHY

    def test_cached_results(self):
        """Test that results are cached."""
        checker = HealthChecker()
        checker.register(
            "test",
            lambda: HealthCheckResult("test", HealthStatus.HEALTHY),
        )

        # Run check
        checker.check("test")

        # Get cached result
        cached = checker.get_cached_result("test")
        assert cached is not None
        assert cached.status == HealthStatus.HEALTHY

    def test_unregister(self):
        """Test unregistering a health check."""
        checker = HealthChecker()
        checker.register(
            "test",
            lambda: HealthCheckResult("test", HealthStatus.HEALTHY),
        )

        checker.unregister("test")
        result = checker.check("test")

        assert result.status == HealthStatus.UNKNOWN


class TestCheckSovitsHealth:
    """Tests for check_sovits_health function."""

    @patch("modules.health.requests.get")
    def test_healthy_when_service_responds(self, mock_get):
        """Test HEALTHY status when service responds with 200."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        result = check_sovits_health()

        assert result.status == HealthStatus.HEALTHY
        assert result.response_time_ms is not None

    @patch("modules.health.requests.get")
    def test_unhealthy_on_connection_error(self, mock_get):
        """Test UNHEALTHY status on connection error."""
        import requests.exceptions

        mock_get.side_effect = requests.exceptions.ConnectionError()

        result = check_sovits_health()

        assert result.status == HealthStatus.UNHEALTHY
        assert "Connection refused" in result.message

    @patch("modules.health.requests.get")
    def test_unhealthy_on_timeout(self, mock_get):
        """Test UNHEALTHY status on timeout."""
        import requests.exceptions

        mock_get.side_effect = requests.exceptions.Timeout()

        result = check_sovits_health()

        assert result.status == HealthStatus.UNHEALTHY
        assert "timeout" in result.message.lower()


class TestCheckFilesystemHealth:
    """Tests for check_filesystem_health function."""

    def test_healthy_with_existing_paths(self, tmp_path):
        """Test HEALTHY status with accessible paths."""
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        result = check_filesystem_health([str(test_dir)])

        assert result.status == HealthStatus.HEALTHY

    def test_creates_missing_directories(self, tmp_path):
        """Test that missing directories are created."""
        new_dir = tmp_path / "new_dir"

        result = check_filesystem_health([str(new_dir)])

        assert result.status == HealthStatus.HEALTHY
        assert new_dir.exists()


class TestRuntimeStatsHealthChecks:
    """Tests for closure-mode runtime stats health checks."""

    def test_web_fetch_runtime_healthy_with_success(self):
        result = check_web_fetch_runtime_stats(
            lambda: {
                "requests": 5,
                "extension_success": 4,
                "binary_success": 0,
                "extension_empty_or_error": 1,
                "extension_unusable": 0,
                "binary_empty_or_error": 0,
                "binary_unavailable": 0,
            }
        )

        assert result.status == HealthStatus.HEALTHY
        assert "Successful web fetches" in result.message

    def test_web_fetch_runtime_degraded_without_success(self):
        result = check_web_fetch_runtime_stats(
            lambda: {
                "requests": 3,
                "extension_success": 0,
                "binary_success": 0,
                "extension_empty_or_error": 2,
                "extension_unusable": 1,
                "binary_empty_or_error": 0,
                "binary_unavailable": 0,
            }
        )

        assert result.status == HealthStatus.DEGRADED
        assert "No successful web fetch" in result.message

    def test_tts_runtime_unknown_without_provider(self):
        result = check_tts_runtime_stats()
        assert result.status == HealthStatus.UNKNOWN
        assert "provider not registered" in result.message

    def test_tts_runtime_healthy_with_success(self):
        result = check_tts_runtime_stats(
            lambda: {
                "stream_attempts": 4,
                "sync_requests": 0,
                "stream_success": 3,
                "buffered_fallback_success": 0,
                "sync_success": 0,
                "stream_errors": 1,
                "buffered_fallback_errors": 0,
                "sync_errors": 0,
            }
        )

        assert result.status == HealthStatus.HEALTHY
        assert "Successful TTS requests" in result.message

    def test_tts_runtime_degraded_when_errors_dominate(self):
        result = check_tts_runtime_stats(
            lambda: {
                "stream_attempts": 6,
                "sync_requests": 0,
                "stream_success": 1,
                "buffered_fallback_success": 0,
                "sync_success": 0,
                "stream_errors": 4,
                "buffered_fallback_errors": 0,
                "sync_errors": 0,
            }
        )

        assert result.status == HealthStatus.DEGRADED
        assert "Partial TTS success" in result.message
