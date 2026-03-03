"""
应用程序启动器模块

将应用程序的初始化、配置加载、服务启动等逻辑与 GUI 分离。
提供统一的应用程序生命周期管理。
"""

import atexit
import signal
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .config import (
    GPT_SOVITS_PATH,
    MODEL_NAME,
    PROMPT_TEXT,
    REF_AUDIO,
    SOVITS_URL,
    SYSTEM_PROMPT,
    data_dir,
)
from .health import get_health_summary, health_checker, setup_default_checks
from .logging_config import get_logger
from .resilience import (
    RetryStrategy,
    ServiceUnavailableError,
    retry,
    safe_call,
)
from .utils import check_sovits_service, start_gpt_sovits_api

logger = get_logger("launcher")


# ============================================================
# 服务状态跟踪
# ============================================================


@dataclass
class ServiceStatus:
    """服务状态"""

    name: str
    initialized: bool = False
    instance: Any = None
    error: Optional[str] = None


@dataclass
class ApplicationContext:
    """
    应用程序上下文

    保存所有已初始化的服务和组件实例，便于统一管理和清理。
    """

    services: Dict[str, ServiceStatus] = field(default_factory=dict)
    cleanup_handlers: List[Callable] = field(default_factory=list)
    _shutdown_requested: bool = False

    def register_service(self, name: str, instance: Any) -> None:
        """注册服务实例"""
        self.services[name] = ServiceStatus(name=name, initialized=True, instance=instance)
        logger.debug(f"Service registered: {name}")

    def register_cleanup(self, handler: Callable) -> None:
        """注册清理处理器"""
        self.cleanup_handlers.append(handler)

    def get_service(self, name: str) -> Optional[Any]:
        """获取服务实例"""
        status = self.services.get(name)
        return status.instance if status and status.initialized else None

    def cleanup(self) -> None:
        """执行所有清理操作"""
        if self._shutdown_requested:
            return
        self._shutdown_requested = True

        logger.info("Starting application cleanup...")

        for handler in reversed(self.cleanup_handlers):
            try:
                handler()
            except Exception as e:
                logger.error(f"Cleanup handler error: {e}")

        logger.info("Application cleanup completed")


# 全局应用上下文
app_context = ApplicationContext()


# ============================================================
# 服务初始化函数
# ============================================================


def init_memory_manager() -> Any:
    """
    初始化记忆管理器

    Returns:
        MemoryManager 实例
    """
    from .memory import MemoryManager

    logger.info("Initializing memory manager...")
    memory_manager = MemoryManager()
    memory_manager.cleanup_old_memories()

    app_context.register_service("memory_manager", memory_manager)
    app_context.register_cleanup(lambda: safe_call(memory_manager.close))

    return memory_manager


def init_voice_manager() -> Any:
    """
    初始化语音管理器

    Returns:
        VoiceManager 实例
    """
    from .voice import VoiceManager

    logger.info("Initializing voice manager...")
    voice_manager = VoiceManager(
        sovits_url=SOVITS_URL,
        ref_audio=REF_AUDIO,
        prompt_text=PROMPT_TEXT,
    )

    app_context.register_service("voice_manager", voice_manager)
    return voice_manager


def init_agent(system_prompt: Optional[str] = None, max_steps: int = 100) -> Any:
    """
    初始化 AI Agent

    Args:
        system_prompt: 系统提示词
        max_steps: 最大执行步数

    Returns:
        ManusAgent 实例
    """
    from .agent.core import ManusAgent

    logger.info("Initializing AI agent...")
    agent = ManusAgent(
        system_prompt=system_prompt or SYSTEM_PROMPT,
        max_steps=max_steps,
    )

    app_context.register_service("agent", agent)
    app_context.register_cleanup(lambda: safe_call(agent.cleanup))

    return agent


@retry(
    max_retries=3,
    base_delay=2.0,
    strategy=RetryStrategy.EXPONENTIAL,
    retryable_exceptions=(Exception,),
)
def init_sovits_service() -> Any:
    """
    初始化 GPT-SoVITS 服务（带重试）

    Returns:
        子进程对象或 None
    """
    logger.info("Starting GPT-SoVITS service...")

    # 首先检查服务是否已经在运行
    if check_sovits_service():
        logger.info("GPT-SoVITS service is already running")
        return None

    process = start_gpt_sovits_api(GPT_SOVITS_PATH)

    if process is None:
        raise ServiceUnavailableError(
            service_name="gpt-sovits",
            message="Failed to start GPT-SoVITS service",
        )

    app_context.register_service("sovits_process", process)
    app_context.register_cleanup(lambda: safe_call(lambda: (process.terminate(), process.wait())))

    return process


# ============================================================
# 应用程序生命周期
# ============================================================


def setup_signal_handlers() -> None:
    """设置信号处理器"""

    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}, initiating shutdown...")
        app_context.cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 注册 atexit 处理器
    atexit.register(app_context.cleanup)


def setup_health_checks() -> None:
    """设置健康检查"""
    setup_default_checks(
        sovits_url=SOVITS_URL,
        chromadb_path=data_dir,
    )


def initialize_core_services(
    enable_sovits: bool = True,
    enable_agent: bool = True,
) -> Dict[str, Any]:
    """
    初始化核心服务

    Args:
        enable_sovits: 是否启用 GPT-SoVITS 服务
        enable_agent: 是否启用 AI Agent

    Returns:
        包含所有初始化服务的字典
    """
    services = {}

    # 设置信号处理
    setup_signal_handlers()

    # 设置健康检查
    setup_health_checks()

    # 初始化记忆管理器（必需）
    services["memory_manager"] = init_memory_manager()

    # 初始化语音管理器（必需）
    services["voice_manager"] = init_voice_manager()

    # 初始化 GPT-SoVITS（可选）
    if enable_sovits:
        try:
            services["sovits_process"] = init_sovits_service()
        except ServiceUnavailableError as e:
            logger.warning(f"GPT-SoVITS initialization failed: {e}")
            services["sovits_process"] = None

    # 初始化 Agent（可选）
    if enable_agent:
        try:
            services["agent"] = init_agent()
        except Exception as e:
            logger.warning(f"Agent initialization failed: {e}")
            services["agent"] = None

    # 执行初始健康检查
    health = health_checker.check_all()
    logger.info(f"Initial health check: {health.overall_status.value}")
    logger.debug(get_health_summary())

    return services


def get_startup_info() -> Dict[str, Any]:
    """
    获取启动信息

    Returns:
        包含各种配置信息的字典
    """
    return {
        "model_name": MODEL_NAME,
        "sovits_url": SOVITS_URL,
        "data_dir": data_dir,
        "system_prompt_length": len(SYSTEM_PROMPT) if SYSTEM_PROMPT else 0,
    }


def print_startup_banner() -> None:
    """打印启动横幅"""
    info = get_startup_info()
    logger.info("=" * 50)
    logger.info("🤖 Project Local Starting...")
    logger.info(f"   Model: {info['model_name']}")
    logger.info(f"   SoVITS URL: {info['sovits_url']}")
    logger.info("=" * 50)
