"""Unit tests for startup self-check."""

from unittest.mock import MagicMock, patch

import pytest

from modules.health import HealthStatus
from modules.startup_self_check import (
    StartupCheckOptions,
    format_startup_report,
    load_startup_check_options,
    run_startup_self_check,
    should_abort_startup,
)


@pytest.mark.unit
def test_load_startup_check_options_respects_skip_env(monkeypatch):
    monkeypatch.setenv("SKIP_STARTUP_SELF_CHECK", "1")
    opts = load_startup_check_options()
    assert opts.enabled is False


@pytest.mark.unit
def test_should_abort_when_critical_failures():
    from modules.health import HealthCheckResult
    from modules.startup_self_check import StartupCheckReport

    report = StartupCheckReport(
        overall_status=HealthStatus.UNHEALTHY,
        items=[],
        critical_failures=["gateway: down"],
    )
    opts = StartupCheckOptions(enabled=True, abort_on_critical_failure=True)
    assert should_abort_startup(report, options=opts) is True


@pytest.mark.unit
def test_format_startup_report_contains_service_names():
    from modules.health import HealthCheckResult
    from modules.startup_self_check import StartupCheckReport

    report = StartupCheckReport(
        overall_status=HealthStatus.DEGRADED,
        items=[HealthCheckResult("gateway", HealthStatus.HEALTHY, message="ok")],
    )
    text = format_startup_report(report)
    assert "gateway" in text
    assert "开机自检" in text


@pytest.mark.unit
def test_run_startup_self_check_skipped_when_disabled():
    app_config = MagicMock()
    app_config.ref_audio = ""
    app_config.sovits_url = "http://127.0.0.1:9880"
    app_config.ark_base_url = ""
    app_config.get_api_key.return_value = "key"

    opts = StartupCheckOptions(enabled=False)
    report = run_startup_self_check(app_config, options=opts)
    assert report.ok_to_launch is True
    assert len(report.items) == 1


@pytest.mark.unit
@patch("modules.startup_self_check._check_agent_dependencies")
@patch("modules.startup_self_check.requests_get_local")
@patch("modules.startup_self_check.get_tuning")
@patch("modules.startup_self_check.check_llm_api_health")
@patch("modules.startup_self_check.check_sovits_health")
@patch("modules.startup_self_check.check_filesystem_health")
def test_run_startup_self_check_gateway_down_is_critical(
    mock_fs,
    mock_sovits,
    mock_llm,
    mock_tuning,
    mock_get,
    mock_agent_deps,
):
    from modules.health import HealthCheckResult

    mock_agent_deps.return_value = [
        HealthCheckResult("manus-import", HealthStatus.HEALTHY, message="ok"),
    ]

    mock_fs.return_value = __import__("modules.health", fromlist=["HealthCheckResult"]).HealthCheckResult(
        "filesystem", HealthStatus.HEALTHY
    )
    mock_sovits.return_value = __import__("modules.health", fromlist=["HealthCheckResult"]).HealthCheckResult(
        "gpt-sovits", HealthStatus.DEGRADED
    )
    mock_llm.return_value = __import__("modules.health", fromlist=["HealthCheckResult"]).HealthCheckResult(
        "llm-api", HealthStatus.HEALTHY
    )

    tuning = MagicMock()
    tuning.services.gateway_port = 18080
    tuning.services.orchestrator_port = 18081
    tuning.services.memory_service_port = 18082
    tuning.services.agent_service_port = 18083
    tuning.services.voice_service_port = 18084
    tuning.services.orchestrator_url = "http://localhost:18081"
    tuning.services.memory_service_url = "http://localhost:18082"
    tuning.services.agent_service_url = "http://localhost:18083"
    tuning.services.voice_service_url = "http://localhost:18084"
    mock_tuning.return_value = tuning

    mock_get.side_effect = ConnectionError("refused")

    app_config = MagicMock()
    app_config.ref_audio = "assets/audio_ref/test.wav"
    app_config.sovits_url = "http://127.0.0.1:9880"
    app_config.ark_base_url = "https://api.example.com"
    app_config.get_api_key.return_value = "k"

    with patch("modules.startup_self_check._check_tuning_config") as mock_tc:
        from modules.health import HealthCheckResult

        mock_tc.return_value = HealthCheckResult("tuning-config", HealthStatus.HEALTHY)
        with patch("modules.startup_self_check._check_ref_audio") as mock_ref:
            mock_ref.return_value = HealthCheckResult("ref-audio", HealthStatus.HEALTHY)
            with patch("modules.startup_self_check._check_pyaudio") as mock_pa:
                mock_pa.return_value = HealthCheckResult("pyaudio", HealthStatus.HEALTHY)
                report = run_startup_self_check(
                    app_config,
                    options=StartupCheckOptions(
                        enabled=True,
                        strict_mode=False,
                        run_smoke_test_suite=False,
                        run_full_test_suite=False,
                        timeout_sec=1.0,
                    ),
                )

    assert "gateway" in report.critical_failures[0] or any(
        "gateway" in f for f in report.critical_failures
    )
