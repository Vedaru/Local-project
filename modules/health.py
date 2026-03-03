"""
健康检查模块

提供对关键服务的健康检查功能，包括：
- GPT-SoVITS 语音合成服务
- LLM API 服务
- 记忆系统（ChromaDB）
- 文件系统（临时目录等）
"""

import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Optional

import requests

from .logging_config import get_logger

logger = get_logger("health")


# ============================================================
# 健康状态定义
# ============================================================


class HealthStatus(Enum):
    """服务健康状态"""

    HEALTHY = "healthy"  # 健康
    DEGRADED = "degraded"  # 降级（部分功能可用）
    UNHEALTHY = "unhealthy"  # 不健康
    UNKNOWN = "unknown"  # 未知


@dataclass
class HealthCheckResult:
    """健康检查结果"""

    service_name: str
    status: HealthStatus
    message: str = ""
    response_time_ms: Optional[float] = None
    details: dict = field(default_factory=dict)
    checked_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "service": self.service_name,
            "status": self.status.value,
            "message": self.message,
            "response_time_ms": self.response_time_ms,
            "details": self.details,
            "checked_at": self.checked_at.isoformat(),
        }


@dataclass
class SystemHealth:
    """系统整体健康状态"""

    overall_status: HealthStatus
    services: list[HealthCheckResult]
    checked_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "overall_status": self.overall_status.value,
            "services": [s.to_dict() for s in self.services],
            "checked_at": self.checked_at.isoformat(),
        }


# ============================================================
# 健康检查函数
# ============================================================


def check_sovits_health(url: str = "http://127.0.0.1:9880") -> HealthCheckResult:
    """
    检查 GPT-SoVITS 服务健康状态

    Args:
        url: SoVITS API 基础 URL

    Returns:
        HealthCheckResult
    """
    service_name = "gpt-sovits"
    start_time = time.time()

    try:
        response = requests.get(f"{url}/docs", timeout=5)
        response_time = (time.time() - start_time) * 1000

        if response.status_code == 200:
            return HealthCheckResult(
                service_name=service_name,
                status=HealthStatus.HEALTHY,
                message="Service is running",
                response_time_ms=response_time,
            )
        else:
            return HealthCheckResult(
                service_name=service_name,
                status=HealthStatus.DEGRADED,
                message=f"Unexpected status code: {response.status_code}",
                response_time_ms=response_time,
            )

    except requests.exceptions.ConnectionError:
        return HealthCheckResult(
            service_name=service_name,
            status=HealthStatus.UNHEALTHY,
            message="Connection refused - service may not be running",
        )
    except requests.exceptions.Timeout:
        return HealthCheckResult(
            service_name=service_name,
            status=HealthStatus.UNHEALTHY,
            message="Connection timeout",
        )
    except Exception as e:
        return HealthCheckResult(
            service_name=service_name,
            status=HealthStatus.UNKNOWN,
            message=f"Unexpected error: {str(e)}",
        )


def check_llm_api_health(
    api_key: Optional[str] = None,
    base_url: str = "https://ark.cn-beijing.volces.com/api/v3",
) -> HealthCheckResult:
    """
    检查 LLM API 服务健康状态

    Args:
        api_key: API 密钥
        base_url: API 基础 URL

    Returns:
        HealthCheckResult
    """
    service_name = "llm-api"
    start_time = time.time()

    if not api_key:
        # 尝试从环境变量获取
        api_key = os.environ.get("ARK_API_KEY")

    if not api_key:
        return HealthCheckResult(
            service_name=service_name,
            status=HealthStatus.UNHEALTHY,
            message="API key not configured",
        )

    try:
        # 简单的连通性检查（不实际调用模型）
        response = requests.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        response_time = (time.time() - start_time) * 1000

        if response.status_code in (200, 401, 403):
            # 401/403 表示认证问题，但服务本身是可达的
            if response.status_code == 200:
                return HealthCheckResult(
                    service_name=service_name,
                    status=HealthStatus.HEALTHY,
                    message="API is reachable and authenticated",
                    response_time_ms=response_time,
                )
            else:
                return HealthCheckResult(
                    service_name=service_name,
                    status=HealthStatus.DEGRADED,
                    message="API is reachable but authentication may have issues",
                    response_time_ms=response_time,
                )
        else:
            return HealthCheckResult(
                service_name=service_name,
                status=HealthStatus.DEGRADED,
                message=f"Unexpected status: {response.status_code}",
                response_time_ms=response_time,
            )

    except requests.exceptions.ConnectionError:
        return HealthCheckResult(
            service_name=service_name,
            status=HealthStatus.UNHEALTHY,
            message="Cannot connect to API server",
        )
    except requests.exceptions.Timeout:
        return HealthCheckResult(
            service_name=service_name,
            status=HealthStatus.UNHEALTHY,
            message="API request timeout",
        )
    except Exception as e:
        return HealthCheckResult(
            service_name=service_name,
            status=HealthStatus.UNKNOWN,
            message=f"Unexpected error: {str(e)}",
        )


def check_chromadb_health(data_dir: Optional[str] = None) -> HealthCheckResult:
    """
    检查 ChromaDB 记忆系统健康状态

    Args:
        data_dir: ChromaDB 数据目录

    Returns:
        HealthCheckResult
    """
    service_name = "chromadb"
    start_time = time.time()

    try:
        import chromadb

        client = chromadb.PersistentClient(path=data_dir) if data_dir else chromadb.Client()

        # 尝试列出集合
        collections = client.list_collections()
        response_time = (time.time() - start_time) * 1000

        return HealthCheckResult(
            service_name=service_name,
            status=HealthStatus.HEALTHY,
            message=f"ChromaDB operational with {len(collections)} collections",
            response_time_ms=response_time,
            details={"collection_count": len(collections)},
        )

    except ImportError:
        return HealthCheckResult(
            service_name=service_name,
            status=HealthStatus.UNHEALTHY,
            message="ChromaDB not installed",
        )
    except Exception as e:
        return HealthCheckResult(
            service_name=service_name,
            status=HealthStatus.UNHEALTHY,
            message=f"ChromaDB error: {str(e)}",
        )


def check_filesystem_health(paths: Optional[list[str]] = None) -> HealthCheckResult:
    """
    检查文件系统健康状态

    Args:
        paths: 需要检查的路径列表

    Returns:
        HealthCheckResult
    """
    service_name = "filesystem"

    if paths is None:
        # 默认检查项目相关目录
        from .config import PROJECT_ROOT

        paths = [
            os.path.join(PROJECT_ROOT, "data"),
            os.path.join(PROJECT_ROOT, "data", "temp"),
            os.path.join(PROJECT_ROOT, "data", "chroma_db"),
        ]

    issues = []
    checked_paths = []

    for path in paths:
        try:
            if os.path.exists(path):
                if os.access(path, os.R_OK | os.W_OK):
                    checked_paths.append({"path": path, "status": "ok"})
                else:
                    issues.append(f"Permission denied: {path}")
                    checked_paths.append({"path": path, "status": "permission_denied"})
            else:
                # 尝试创建目录
                os.makedirs(path, exist_ok=True)
                checked_paths.append({"path": path, "status": "created"})
        except OSError as e:
            issues.append(f"Cannot access {path}: {e}")
            checked_paths.append({"path": path, "status": "error", "error": str(e)})

    if not issues:
        return HealthCheckResult(
            service_name=service_name,
            status=HealthStatus.HEALTHY,
            message=f"All {len(paths)} paths are accessible",
            details={"paths": checked_paths},
        )
    elif len(issues) < len(paths):
        return HealthCheckResult(
            service_name=service_name,
            status=HealthStatus.DEGRADED,
            message=f"{len(issues)} path issues found",
            details={"paths": checked_paths, "issues": issues},
        )
    else:
        return HealthCheckResult(
            service_name=service_name,
            status=HealthStatus.UNHEALTHY,
            message="All paths have issues",
            details={"paths": checked_paths, "issues": issues},
        )


# ============================================================
# 健康检查管理器
# ============================================================


class HealthChecker:
    """
    健康检查管理器

    支持注册多个健康检查函数，并提供定期检查和状态查询功能。

    Example:
        checker = HealthChecker()
        checker.register("sovits", check_sovits_health)
        checker.register("llm", lambda: check_llm_api_health(api_key="xxx"))

        # 一次性检查所有服务
        health = checker.check_all()

        # 启动后台定期检查
        checker.start_background_checks(interval=60)
    """

    def __init__(self):
        self._checks: dict[str, Callable[[], HealthCheckResult]] = {}
        self._results: dict[str, HealthCheckResult] = {}
        self._background_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def register(self, name: str, check_func: Callable[[], HealthCheckResult]):
        """
        注册健康检查函数

        Args:
            name: 检查名称
            check_func: 无参数的检查函数，返回 HealthCheckResult
        """
        with self._lock:
            self._checks[name] = check_func
            logger.debug(f"Registered health check: {name}")

    def unregister(self, name: str):
        """取消注册健康检查"""
        with self._lock:
            if name in self._checks:
                del self._checks[name]
                if name in self._results:
                    del self._results[name]

    def check(self, name: str) -> HealthCheckResult:
        """
        执行单个健康检查

        Args:
            name: 检查名称

        Returns:
            HealthCheckResult
        """
        with self._lock:
            if name not in self._checks:
                return HealthCheckResult(
                    service_name=name,
                    status=HealthStatus.UNKNOWN,
                    message=f"No health check registered for '{name}'",
                )
            check_func = self._checks[name]

        try:
            result = check_func()
            with self._lock:
                self._results[name] = result
            return result
        except Exception as e:
            result = HealthCheckResult(
                service_name=name,
                status=HealthStatus.UNKNOWN,
                message=f"Health check failed: {str(e)}",
            )
            with self._lock:
                self._results[name] = result
            return result

    def check_all(self) -> SystemHealth:
        """
        执行所有已注册的健康检查

        Returns:
            SystemHealth 包含所有检查结果
        """
        with self._lock:
            check_names = list(self._checks.keys())

        results = []
        for name in check_names:
            result = self.check(name)
            results.append(result)

        # 计算整体状态
        if not results:
            overall = HealthStatus.UNKNOWN
        elif all(r.status == HealthStatus.HEALTHY for r in results):
            overall = HealthStatus.HEALTHY
        elif any(r.status == HealthStatus.UNHEALTHY for r in results):
            overall = HealthStatus.UNHEALTHY
        else:
            overall = HealthStatus.DEGRADED

        return SystemHealth(overall_status=overall, services=results)

    def get_cached_result(self, name: str) -> Optional[HealthCheckResult]:
        """获取缓存的检查结果（不执行新的检查）"""
        with self._lock:
            return self._results.get(name)

    def get_all_cached_results(self) -> dict[str, HealthCheckResult]:
        """获取所有缓存的检查结果"""
        with self._lock:
            return dict(self._results)

    def start_background_checks(self, interval: float = 60.0):
        """
        启动后台定期健康检查

        Args:
            interval: 检查间隔（秒）
        """
        if self._background_thread and self._background_thread.is_alive():
            logger.warning("Background health checks already running")
            return

        self._stop_event.clear()

        def background_check_loop():
            logger.info(f"Starting background health checks (interval: {interval}s)")
            while not self._stop_event.is_set():
                try:
                    self.check_all()
                except Exception as e:
                    logger.error(f"Background health check error: {e}")
                self._stop_event.wait(interval)
            logger.info("Background health checks stopped")

        self._background_thread = threading.Thread(target=background_check_loop, daemon=True, name="HealthChecker")
        self._background_thread.start()

    def stop_background_checks(self):
        """停止后台健康检查"""
        self._stop_event.set()
        if self._background_thread:
            self._background_thread.join(timeout=5)
            self._background_thread = None


# ============================================================
# 全局健康检查器实例
# ============================================================

# 创建全局实例
health_checker = HealthChecker()


def setup_default_checks(
    sovits_url: str = "http://127.0.0.1:9880",
    llm_api_key: Optional[str] = None,
    chromadb_path: Optional[str] = None,
):
    """
    设置默认的健康检查

    Args:
        sovits_url: GPT-SoVITS 服务 URL
        llm_api_key: LLM API 密钥
        chromadb_path: ChromaDB 数据目录
    """
    health_checker.register("sovits", lambda: check_sovits_health(sovits_url))
    health_checker.register("llm-api", lambda: check_llm_api_health(llm_api_key))
    health_checker.register("chromadb", lambda: check_chromadb_health(chromadb_path))
    health_checker.register("filesystem", check_filesystem_health)

    logger.info("Default health checks registered")


def get_health_summary() -> str:
    """
    获取健康状态摘要（用于日志或显示）

    Returns:
        格式化的健康状态字符串
    """
    results = health_checker.get_all_cached_results()
    if not results:
        return "No health checks have been performed yet"

    lines = ["=== System Health ==="]
    for name, result in results.items():
        status_icon = {
            HealthStatus.HEALTHY: "✅",
            HealthStatus.DEGRADED: "⚠️",
            HealthStatus.UNHEALTHY: "❌",
            HealthStatus.UNKNOWN: "❓",
        }.get(result.status, "❓")

        line = f"  {status_icon} {name}: {result.status.value}"
        if result.response_time_ms:
            line += f" ({result.response_time_ms:.0f}ms)"
        if result.message:
            line += f" - {result.message}"
        lines.append(line)

    return "\n".join(lines)
