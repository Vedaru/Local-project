"""
开机自检 — GUI 启动前检查环境、微服务、Agent 依赖，并可严格运行 pytest 测试集。

配置见 project_config.yaml `startup` 段；SKIP_STARTUP_SELF_CHECK=1 可跳过。
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml

from modules.agent.dependencies import (
    AGENT_RUNTIME_DEPENDENCIES,
    AgentDependencySpec,
    is_module_importable,
    missing_agent_dependencies,
    verify_manus_importable,
)
from modules.config import AppConfig, PROJECT_ROOT
from modules.config_tuning import TUNING_PATH, get_tuning
from modules.health import (
    HealthCheckResult,
    HealthStatus,
    check_filesystem_health,
    check_llm_api_health,
    check_sovits_health,
)
from modules.logging_config import get_logger
from modules.utils import requests_get_local

logger = get_logger("StartupSelfCheck")

# modules.config.PROJECT_ROOT 为 str
_PROJECT_ROOT = Path(PROJECT_ROOT)

MICROSERVICE_RUNTIME_DEPENDENCIES: tuple[AgentDependencySpec, ...] = (
    AgentDependencySpec("fastapi", "fastapi>=0.128.6,<0.136", True, "微服务 API 框架"),
    AgentDependencySpec("starlette", "starlette>=1.0.0,<2.0.0", True, "与 mcp 等依赖一致"),
    AgentDependencySpec("uvicorn", "uvicorn[standard]>=0.34.0,<0.37", True, "ASGI 服务"),
)

_STATUS_ICON = {
    HealthStatus.HEALTHY: "[OK]",
    HealthStatus.DEGRADED: "[WARN]",
    HealthStatus.UNHEALTHY: "[FAIL]",
    HealthStatus.UNKNOWN: "[??]",
}


@dataclass
class StartupCheckOptions:
    enabled: bool = True
    strict_mode: bool = True
    abort_on_critical_failure: bool = True
    run_full_test_suite: bool = False
    run_smoke_test_suite: bool = True
    test_suite_timeout_sec: float = 300.0
    timeout_sec: float = 5.0


@dataclass
class StartupCheckReport:
    """开机自检汇总。"""

    overall_status: HealthStatus
    items: list[HealthCheckResult] = field(default_factory=list)
    critical_failures: list[str] = field(default_factory=list)
    checked_at: datetime = field(default_factory=datetime.now)

    @property
    def ok_to_launch(self) -> bool:
        return not self.critical_failures


def load_startup_check_options() -> StartupCheckOptions:
    opts = StartupCheckOptions()
    if os.path.exists(TUNING_PATH):
        try:
            with open(TUNING_PATH, encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            startup_raw = raw.get("startup") if isinstance(raw, dict) else None
            if isinstance(startup_raw, dict):
                if "self_check_enabled" in startup_raw:
                    opts.enabled = bool(startup_raw["self_check_enabled"])
                if "strict_mode" in startup_raw:
                    opts.strict_mode = bool(startup_raw["strict_mode"])
                if "abort_on_critical_failure" in startup_raw:
                    opts.abort_on_critical_failure = bool(startup_raw["abort_on_critical_failure"])
                if "run_full_test_suite" in startup_raw:
                    opts.run_full_test_suite = bool(startup_raw["run_full_test_suite"])
                if "run_smoke_test_suite" in startup_raw:
                    opts.run_smoke_test_suite = bool(startup_raw["run_smoke_test_suite"])
                if "test_suite_timeout_sec" in startup_raw:
                    opts.test_suite_timeout_sec = max(30.0, float(startup_raw["test_suite_timeout_sec"]))
                if "timeout_sec" in startup_raw:
                    opts.timeout_sec = max(1.0, float(startup_raw["timeout_sec"]))
        except (OSError, TypeError, ValueError) as exc:
            logger.debug("读取 startup 配置失败，使用默认: %s", exc)

    skip = (os.getenv("SKIP_STARTUP_SELF_CHECK") or "").strip().lower()
    if skip in ("1", "true", "yes", "on"):
        opts.enabled = False
    strict_env = (os.getenv("STARTUP_STRICT_MODE") or "").strip().lower()
    if strict_env in ("0", "false", "no", "off"):
        opts.strict_mode = False
    elif strict_env in ("1", "true", "yes", "on"):
        opts.strict_mode = True
    return opts


def _check_http_endpoint(
    service_name: str,
    url: str,
    *,
    timeout: float,
    critical: bool = False,
    accept_status: tuple[int, ...] = (200,),
) -> HealthCheckResult:
    start = datetime.now()
    try:
        response = requests_get_local(url, timeout=timeout)
        elapsed_ms = (datetime.now() - start).total_seconds() * 1000
        if response.status_code in accept_status:
            return HealthCheckResult(
                service_name=service_name,
                status=HealthStatus.HEALTHY,
                message=f"{url} -> {response.status_code}",
                response_time_ms=elapsed_ms,
                details={"critical": critical},
            )
        status = HealthStatus.UNHEALTHY if critical else HealthStatus.DEGRADED
        return HealthCheckResult(
            service_name=service_name,
            status=status,
            message=f"{url} -> HTTP {response.status_code}",
            response_time_ms=elapsed_ms,
            details={"critical": critical},
        )
    except Exception as exc:
        status = HealthStatus.UNHEALTHY if critical else HealthStatus.DEGRADED
        return HealthCheckResult(
            service_name=service_name,
            status=status,
            message=f"{url} 不可达: {exc}",
            details={"critical": critical},
        )


def _check_dependency_specs(specs: tuple, *, strict: bool) -> list[HealthCheckResult]:
    results: list[HealthCheckResult] = []
    for spec in specs:
        if not strict and not spec.critical:
            continue
        if is_module_importable(spec.module_name):
            results.append(
                HealthCheckResult(
                    service_name=f"dep-{spec.module_name}",
                    status=HealthStatus.HEALTHY,
                    message=spec.description or spec.module_name,
                    details={"critical": spec.critical},
                )
            )
        else:
            results.append(
                HealthCheckResult(
                    service_name=f"dep-{spec.module_name}",
                    status=HealthStatus.UNHEALTHY if spec.critical else HealthStatus.DEGRADED,
                    message=f"未安装 {spec.pip_spec}",
                    details={"critical": spec.critical, "pip": spec.pip_spec},
                )
            )

    return results


def _check_agent_dependencies(*, strict: bool) -> list[HealthCheckResult]:
    results = _check_dependency_specs(AGENT_RUNTIME_DEPENDENCIES, strict=strict)
    ok, msg = verify_manus_importable()
    results.append(
        HealthCheckResult(
            service_name="manus-import",
            status=HealthStatus.HEALTHY if ok else HealthStatus.UNHEALTHY,
            message=msg,
            details={"critical": True},
        )
    )
    return results


def _check_microservice_dependencies(*, strict: bool) -> list[HealthCheckResult]:
    return _check_dependency_specs(MICROSERVICE_RUNTIME_DEPENDENCIES, strict=strict)


def _check_fastapi_starlette_compat() -> HealthCheckResult:
    try:
        import fastapi
        import starlette

        fv = tuple(int(x) for x in fastapi.__version__.split(".")[:2])
        sv = tuple(int(x) for x in starlette.__version__.split(".")[:2])
        if sv >= (1, 0) and fv < (0, 128):
            return HealthCheckResult(
                service_name="fastapi-starlette",
                status=HealthStatus.UNHEALTHY,
                message=(
                    f"不兼容: fastapi {fastapi.__version__} + starlette {starlette.__version__} "
                    "(请 pip install fastapi==0.115.12 starlette==0.41.3)"
                ),
                details={"critical": True},
            )
        return HealthCheckResult(
            service_name="fastapi-starlette",
            status=HealthStatus.HEALTHY,
            message=f"fastapi {fastapi.__version__} + starlette {starlette.__version__}",
            details={"critical": True},
        )
    except Exception as exc:
        return HealthCheckResult(
            service_name="fastapi-starlette",
            status=HealthStatus.UNHEALTHY,
            message=str(exc),
            details={"critical": True},
        )


def _check_pyaudio(*, strict: bool) -> HealthCheckResult:
    try:
        import pyaudio

        pa = pyaudio.PyAudio()
        try:
            device_count = pa.get_device_count()
        finally:
            pa.terminate()
        return HealthCheckResult(
            service_name="pyaudio",
            status=HealthStatus.HEALTHY,
            message=f"PyAudio 可用 (devices={device_count})",
            details={"critical": False},
        )
    except ImportError:
        return HealthCheckResult(
            service_name="pyaudio",
            status=HealthStatus.DEGRADED if not strict else HealthStatus.UNHEALTHY,
            message="未安装 pyaudio，将使用 winsound / Viewer 回退播放",
            details={"critical": strict},
        )
    except Exception as exc:
        return HealthCheckResult(
            service_name="pyaudio",
            status=HealthStatus.DEGRADED,
            message=f"PyAudio 初始化异常: {exc}",
            details={"critical": False},
        )


def _check_ref_audio(app_config: AppConfig, *, strict: bool) -> HealthCheckResult:
    ref_path = (app_config.ref_audio or "").strip()
    if not ref_path:
        return HealthCheckResult(
            service_name="ref-audio",
            status=HealthStatus.DEGRADED if not strict else HealthStatus.UNHEALTHY,
            message="未配置参考音频 ref_audio",
            details={"critical": strict},
        )
    path = ref_path if os.path.isabs(ref_path) else os.path.join(PROJECT_ROOT, ref_path)
    if os.path.isfile(path):
        return HealthCheckResult(
            service_name="ref-audio",
            status=HealthStatus.HEALTHY,
            message=f"参考音频存在: {os.path.basename(path)}",
        )
    return HealthCheckResult(
        service_name="ref-audio",
        status=HealthStatus.DEGRADED if not strict else HealthStatus.UNHEALTHY,
        message=f"参考音频不存在: {path}",
        details={"critical": strict},
    )


def _check_tuning_config() -> HealthCheckResult:
    try:
        tuning = get_tuning()
        ports = (
            f"gateway={tuning.services.gateway_port}, "
            f"voice={tuning.services.voice_service_port}"
        )
        return HealthCheckResult(
            service_name="tuning-config",
            status=HealthStatus.HEALTHY,
            message=f"行为配置已加载 ({ports})",
            details={"critical": True},
        )
    except Exception as exc:
        return HealthCheckResult(
            service_name="tuning-config",
            status=HealthStatus.UNHEALTHY,
            message=f"加载 tuning 失败: {exc}",
            details={"critical": True},
        )


SMOKE_TEST_PATHS: tuple[str, ...] = (
    "tests/test_startup_self_check.py",
    "tests/test_health.py",
    "tests/test_utils.py",
    "tests/test_config_module.py",
    "tests/test_config_split.py",
    "tests/test_audio_playback_cleanup.py",
    "tests/test_orchestrator_core.py",
    "tests/test_shared_types.py",
    "tests/test_agent_speak.py",
    "tests/test_voice_tts_chain.py",
)


def _run_pytest_suite(timeout_sec: float, *, paths: list[str], label: str) -> HealthCheckResult:
    if not paths:
        return HealthCheckResult(
            service_name="pytest-suite",
            status=HealthStatus.UNHEALTHY,
            message="未指定测试路径",
            details={"critical": True},
        )
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *paths,
        "-q",
        "--tb=line",
        "--disable-warnings",
    ]
    logger.info("严格自检：运行 %s (timeout=%.0fs)...", label, timeout_sec)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env={**os.environ, "CT2_USE_CUDA": "0"},
        )
    except subprocess.TimeoutExpired:
        return HealthCheckResult(
            service_name="pytest-suite",
            status=HealthStatus.UNHEALTHY,
            message=f"pytest 超时 (>{timeout_sec:.0f}s)",
            details={"critical": True},
        )
    except Exception as exc:
        return HealthCheckResult(
            service_name="pytest-suite",
            status=HealthStatus.UNHEALTHY,
            message=f"pytest 启动失败: {exc}",
            details={"critical": True},
        )

    tail = (proc.stdout or "")[-800:] + "\n" + (proc.stderr or "")[-400:]
    if proc.returncode == 0:
        return HealthCheckResult(
            service_name="pytest-suite",
            status=HealthStatus.HEALTHY,
            message="全部单元测试通过",
            details={"critical": True, "output_tail": tail.strip()},
        )
    return HealthCheckResult(
        service_name="pytest-suite",
        status=HealthStatus.UNHEALTHY,
        message=f"pytest 失败 (exit={proc.returncode})",
        details={"critical": True, "output_tail": tail.strip()},
    )


def _local_service_base(url: str, port: int) -> str:
    base = (url or "").strip().rstrip("/")
    if base and ("127.0.0.1" in base or "localhost" in base.lower()):
        return base
    return f"http://127.0.0.1:{port}"


def _collect_critical_failures(items: list[HealthCheckResult], *, strict: bool) -> list[str]:
    failures: list[str] = []
    # gpt-sovits 由 voice 模块在后台线程异步启动，自检时可能尚未就绪，不阻塞启动。
    _async_services = {"gpt-sovits"}
    for item in items:
        is_critical = bool((item.details or {}).get("critical"))
        if item.service_name in ("gateway", "orchestrator", "manus-import", "pytest-suite"):
            is_critical = True
        if item.service_name == "tuning-config" and item.status == HealthStatus.UNHEALTHY:
            is_critical = True
        if strict and item.status in (HealthStatus.UNHEALTHY, HealthStatus.DEGRADED):
            if item.service_name not in _async_services:
                is_critical = True
        if is_critical and item.status != HealthStatus.HEALTHY:
            failures.append(f"{item.service_name}: {item.message}")
    return failures


def run_startup_self_check(
    app_config: AppConfig,
    *,
    options: Optional[StartupCheckOptions] = None,
) -> StartupCheckReport:
    opts = options or load_startup_check_options()
    if not opts.enabled:
        return StartupCheckReport(
            overall_status=HealthStatus.HEALTHY,
            items=[
                HealthCheckResult(
                    service_name="startup-self-check",
                    status=HealthStatus.HEALTHY,
                    message="已跳过 (SKIP_STARTUP_SELF_CHECK 或配置关闭)",
                )
            ],
        )

    strict = opts.strict_mode
    timeout = opts.timeout_sec
    tuning = get_tuning()
    svc = tuning.services
    gateway_base = _local_service_base("", svc.gateway_port)

    items: list[HealthCheckResult] = [
        _check_tuning_config(),
        check_filesystem_health(),
        _check_ref_audio(app_config, strict=strict),
        _check_pyaudio(strict=strict),
        _check_fastapi_starlette_compat(),
        *_check_microservice_dependencies(strict=strict),
        *_check_agent_dependencies(strict=strict),
        _check_http_endpoint(
            "gateway",
            f"{gateway_base}/health",
            timeout=timeout,
            critical=True,
        ),
        _check_http_endpoint(
            "orchestrator",
            f"{_local_service_base(svc.orchestrator_url, svc.orchestrator_port)}/health",
            timeout=timeout,
            critical=True,
        ),
        _check_http_endpoint(
            "memory-service",
            f"{_local_service_base(svc.memory_service_url, svc.memory_service_port)}/health",
            timeout=timeout,
            critical=strict,
        ),
        _check_http_endpoint(
            "agent-service",
            f"{_local_service_base(svc.agent_service_url, svc.agent_service_port)}/health",
            timeout=timeout,
            critical=strict,
        ),
        _check_http_endpoint(
            "voice-service",
            f"{_local_service_base(svc.voice_service_url, svc.voice_service_port)}/health/live",
            timeout=timeout,
            critical=strict,
            accept_status=(200, 503),
        ),
        check_sovits_health(app_config.sovits_url or "http://127.0.0.1:9880"),
        check_llm_api_health(
            api_key=app_config.get_api_key() if hasattr(app_config, "get_api_key") else None,
            base_url=app_config.ark_base_url or "https://ark.cn-beijing.volces.com/api/v3",
        ),
    ]

    if strict:
        for idx, item in enumerate(items):
            if item.service_name == "llm-api" and item.status != HealthStatus.HEALTHY:
                merged_details = {**(item.details or {}), "critical": True}
                items[idx] = HealthCheckResult(
                    service_name=item.service_name,
                    status=item.status,
                    message=item.message,
                    response_time_ms=item.response_time_ms,
                    details=merged_details,
                    checked_at=item.checked_at,
                )

    if strict:
        if opts.run_full_test_suite:
            items.append(
                _run_pytest_suite(
                    opts.test_suite_timeout_sec,
                    paths=[str(_PROJECT_ROOT / "tests")],
                    label="完整测试集 tests/",
                )
            )
        elif opts.run_smoke_test_suite:
            smoke_paths = [
                str(_PROJECT_ROOT / rel) for rel in SMOKE_TEST_PATHS if (_PROJECT_ROOT / rel).exists()
            ]
            items.append(
                _run_pytest_suite(
                    opts.test_suite_timeout_sec,
                    paths=smoke_paths,
                    label="冒烟测试集",
                )
            )

    missing = missing_agent_dependencies(include_optional=False)
    if missing:
        pip_line = " ".join(s.pip_spec for s in missing)
        logger.warning("Agent 缺失依赖，可执行: python -m pip install %s", pip_line)

    critical_failures = _collect_critical_failures(items, strict=strict)

    if critical_failures:
        overall = HealthStatus.UNHEALTHY
    elif any(r.status == HealthStatus.UNHEALTHY for r in items):
        overall = HealthStatus.DEGRADED
    elif any(r.status == HealthStatus.DEGRADED for r in items):
        overall = HealthStatus.DEGRADED
    elif all(r.status == HealthStatus.HEALTHY for r in items):
        overall = HealthStatus.HEALTHY
    else:
        overall = HealthStatus.UNKNOWN

    return StartupCheckReport(
        overall_status=overall,
        items=items,
        critical_failures=critical_failures if opts.abort_on_critical_failure else [],
    )


def format_startup_report(report: StartupCheckReport) -> str:
    lines = [
        "========== Project Local 开机自检 ==========",
        f"整体: {report.overall_status.value}",
    ]
    for item in report.items:
        icon = _STATUS_ICON.get(item.status, "[??]")
        line = f"  {icon} {item.service_name}: {item.message}"
        if item.response_time_ms is not None:
            line += f" ({item.response_time_ms:.0f}ms)"
        lines.append(line)
        tail = (item.details or {}).get("output_tail")
        if tail and item.status != HealthStatus.HEALTHY:
            for tail_line in str(tail).splitlines()[-5:]:
                lines.append(f"      > {tail_line}")
    if report.critical_failures:
        lines.append("--- 未通过项（严格模式：任一项失败将阻止启动）---")
        for msg in report.critical_failures:
            lines.append(f"  * {msg}")
    lines.append("==========================================")
    return "\n".join(lines)


def log_startup_report(report_logger: Any, report: StartupCheckReport) -> None:
    text = format_startup_report(report)
    for line in text.splitlines():
        if "[FAIL]" in line or "未通过项" in line or line.strip().startswith("* ") or line.strip().startswith(">"):
            report_logger.warning(line)
        elif "[WARN]" in line:
            report_logger.warning(line)
        else:
            report_logger.info(line)


def should_abort_startup(report: StartupCheckReport, *, options: Optional[StartupCheckOptions] = None) -> bool:
    opts = options or load_startup_check_options()
    if not opts.enabled:
        return False
    if not opts.abort_on_critical_failure:
        return False
    return not report.ok_to_launch
