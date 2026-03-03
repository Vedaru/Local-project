"""
Unit tests for modules/health.py
"""
import pytest
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.health import (
    HealthStatus,
    HealthCheckResult,
    SystemHealth,
    HealthChecker,
    check_sovits_health,
    check_filesystem_health,
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
