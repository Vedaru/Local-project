"""
错误处理与重试机制模块

提供统一的异常类型、重试装饰器（指数退避）和断路器模式。
"""

import functools
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

from .logging_config import get_logger

logger = get_logger("resilience")


# ============================================================
# 自定义异常类型
# ============================================================


class LocalProjectError(Exception):
    """Local-project 基础异常类"""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.timestamp = datetime.now()


class ServiceUnavailableError(LocalProjectError):
    """服务不可用异常（如 GPT-SoVITS、LLM API 等）"""

    def __init__(self, service_name: str, message: str = "", details: Optional[dict] = None):
        full_message = f"Service '{service_name}' is unavailable: {message}"
        super().__init__(full_message, details)
        self.service_name = service_name


class RateLimitError(LocalProjectError):
    """API 速率限制异常"""

    def __init__(self, service_name: str, retry_after: Optional[float] = None, details: Optional[dict] = None):
        message = f"Rate limit exceeded for '{service_name}'"
        if retry_after:
            message += f", retry after {retry_after}s"
        super().__init__(message, details)
        self.service_name = service_name
        self.retry_after = retry_after


class ConfigurationError(LocalProjectError):
    """配置错误异常"""

    pass


class MemoryError(LocalProjectError):
    """记忆系统异常"""

    pass


class VoiceSynthesisError(LocalProjectError):
    """语音合成异常"""

    pass


class AgentExecutionError(LocalProjectError):
    """Agent 执行异常"""

    pass


# ============================================================
# 重试策略
# ============================================================


class RetryStrategy(Enum):
    """重试策略枚举"""

    FIXED = "fixed"  # 固定间隔
    EXPONENTIAL = "exponential"  # 指数退避
    LINEAR = "linear"  # 线性增长


@dataclass
class RetryConfig:
    """重试配置"""

    max_retries: int = 3
    base_delay: float = 1.0  # 基础延迟（秒）
    max_delay: float = 60.0  # 最大延迟（秒）
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL
    jitter: bool = True  # 是否添加随机抖动
    jitter_factor: float = 0.1  # 抖动因子
    retryable_exceptions: tuple = (Exception,)  # 可重试的异常类型


def calculate_delay(config: RetryConfig, attempt: int) -> float:
    """计算重试延迟时间"""
    if config.strategy == RetryStrategy.FIXED:
        delay = config.base_delay
    elif config.strategy == RetryStrategy.EXPONENTIAL:
        delay = config.base_delay * (2**attempt)
    elif config.strategy == RetryStrategy.LINEAR:
        delay = config.base_delay * (attempt + 1)
    else:
        delay = config.base_delay

    # 限制最大延迟
    delay = min(delay, config.max_delay)

    # 添加随机抖动
    if config.jitter:
        jitter_range = delay * config.jitter_factor
        delay += random.uniform(-jitter_range, jitter_range)

    return max(0, delay)


def retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL,
    retryable_exceptions: tuple = (Exception,),
    on_retry: Optional[Callable[[Exception, int], None]] = None,
):
    """
    重试装饰器

    Args:
        max_retries: 最大重试次数
        base_delay: 基础延迟时间（秒）
        max_delay: 最大延迟时间（秒）
        strategy: 重试策略
        retryable_exceptions: 可重试的异常类型
        on_retry: 重试时的回调函数

    Example:
        @retry(max_retries=3, strategy=RetryStrategy.EXPONENTIAL)
        def call_api():
            # API call that may fail
            pass
    """
    config = RetryConfig(
        max_retries=max_retries,
        base_delay=base_delay,
        max_delay=max_delay,
        strategy=strategy,
        retryable_exceptions=retryable_exceptions,
    )

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception: Optional[Exception] = None

            for attempt in range(config.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except config.retryable_exceptions as e:
                    last_exception = e

                    if attempt < config.max_retries:
                        delay = calculate_delay(config, attempt)
                        logger.warning(
                            f"Retry {attempt + 1}/{config.max_retries} for {func.__name__} "
                            f"after {delay:.2f}s due to: {e}"
                        )

                        if on_retry:
                            on_retry(e, attempt)

                        time.sleep(delay)
                    else:
                        logger.error(f"All {config.max_retries} retries exhausted for {func.__name__}: {e}")

            raise last_exception

        return wrapper

    return decorator


def async_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL,
    retryable_exceptions: tuple = (Exception,),
    on_retry: Optional[Callable[[Exception, int], None]] = None,
):
    """
    异步重试装饰器

    与 retry 相同的参数，但用于 async 函数
    """
    import asyncio

    config = RetryConfig(
        max_retries=max_retries,
        base_delay=base_delay,
        max_delay=max_delay,
        strategy=strategy,
        retryable_exceptions=retryable_exceptions,
    )

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            last_exception: Optional[Exception] = None

            for attempt in range(config.max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except config.retryable_exceptions as e:
                    last_exception = e

                    if attempt < config.max_retries:
                        delay = calculate_delay(config, attempt)
                        logger.warning(
                            f"Retry {attempt + 1}/{config.max_retries} for {func.__name__} "
                            f"after {delay:.2f}s due to: {e}"
                        )

                        if on_retry:
                            on_retry(e, attempt)

                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"All {config.max_retries} retries exhausted for {func.__name__}: {e}")

            raise last_exception

        return wrapper

    return decorator


# ============================================================
# 断路器模式
# ============================================================


class CircuitState(Enum):
    """断路器状态"""

    CLOSED = "closed"  # 正常状态
    OPEN = "open"  # 断开状态（直接失败）
    HALF_OPEN = "half_open"  # 半开状态（尝试恢复）


@dataclass
class CircuitBreaker:
    """
    断路器实现

    当连续失败次数超过阈值时，断路器会打开，
    后续调用会直接失败而不尝试执行，避免雪崩效应。

    Example:
        breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=30)

        @breaker
        def call_external_service():
            # Service call
            pass
    """

    failure_threshold: int = 5  # 触发断路的失败次数
    recovery_timeout: float = 30.0  # 恢复超时时间（秒）
    success_threshold: int = 2  # 半开状态下恢复所需的成功次数

    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _success_count: int = field(default=0, init=False)
    _last_failure_time: Optional[datetime] = field(default=None, init=False)

    @property
    def state(self) -> CircuitState:
        """获取当前断路器状态"""
        if self._state == CircuitState.OPEN and self._last_failure_time:
            # 检查是否应该转换为半开状态
            elapsed = (datetime.now() - self._last_failure_time).total_seconds()
            if elapsed >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0
                logger.info("Circuit breaker transitioning to HALF_OPEN")
        return self._state

    def record_success(self):
        """记录成功调用"""
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.success_threshold:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                logger.info("Circuit breaker CLOSED (recovered)")
        elif self._state == CircuitState.CLOSED:
            self._failure_count = 0

    def record_failure(self, exception: Exception):
        """记录失败调用"""
        self._failure_count += 1
        self._last_failure_time = datetime.now()

        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
            logger.warning("Circuit breaker OPEN (failed during half-open)")
        elif self._state == CircuitState.CLOSED:
            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(f"Circuit breaker OPEN after {self._failure_count} failures")

    def __call__(self, func: Callable) -> Callable:
        """作为装饰器使用"""

        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            current_state = self.state

            if current_state == CircuitState.OPEN:
                raise ServiceUnavailableError(
                    service_name=func.__name__,
                    message="Circuit breaker is OPEN",
                    details={"failure_count": self._failure_count},
                )

            try:
                result = func(*args, **kwargs)
                self.record_success()
                return result
            except Exception as e:
                self.record_failure(e)
                raise

        return wrapper

    def reset(self):
        """重置断路器状态"""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = None
        logger.info("Circuit breaker reset to CLOSED")


# ============================================================
# 全局异常处理器
# ============================================================


class GlobalExceptionHandler:
    """
    全局异常处理器

    捕获并记录所有未处理的异常，提供统一的错误处理机制。
    """

    def __init__(self):
        self._handlers: dict[type[Exception], Callable] = {}
        self._default_handler: Optional[Callable] = None

    def register(self, exception_type: type[Exception]) -> Callable[[Callable], Callable]:
        """注册特定异常类型的处理器"""

        def decorator(handler: Callable) -> Callable:
            self._handlers[exception_type] = handler
            return handler

        return decorator

    def set_default_handler(self, handler: Callable):
        """设置默认异常处理器"""
        self._default_handler = handler

    def handle(self, exception: Exception) -> Any:
        """处理异常"""
        # 查找最匹配的处理器
        for exc_type, handler in self._handlers.items():
            if isinstance(exception, exc_type):
                return handler(exception)

        # 使用默认处理器
        if self._default_handler:
            return self._default_handler(exception)

        # 没有处理器，重新抛出
        logger.error(f"Unhandled exception: {exception}", exc_info=True)
        raise exception

    def wrap(self, func: Callable) -> Callable:
        """包装函数，自动处理异常"""

        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                return self.handle(e)

        return wrapper


# 全局异常处理器实例
exception_handler = GlobalExceptionHandler()


# 注册默认的异常处理器
@exception_handler.register(ServiceUnavailableError)
def handle_service_unavailable(e: ServiceUnavailableError) -> str:
    logger.error(f"Service unavailable: {e.service_name} - {e.message}")
    return f"服务暂时不可用：{e.service_name}，请稍后重试。"


@exception_handler.register(RateLimitError)
def handle_rate_limit(e: RateLimitError) -> str:
    logger.warning(f"Rate limit hit: {e.service_name}")
    if e.retry_after:
        return f"请求过于频繁，请在 {e.retry_after} 秒后重试。"
    return "请求过于频繁，请稍后重试。"


@exception_handler.register(ConfigurationError)
def handle_configuration_error(e: ConfigurationError) -> str:
    logger.error(f"Configuration error: {e.message}")
    return f"配置错误：{e.message}"


# 设置默认处理器
def default_exception_handler(e: Exception) -> str:
    logger.error(f"Unexpected error: {e}", exc_info=True)
    return "发生了意外错误，请稍后重试。"


exception_handler.set_default_handler(default_exception_handler)


# ============================================================
# 便捷函数
# ============================================================


def safe_call(
    func: Callable,
    *args,
    default: Any = None,
    log_error: bool = True,
    **kwargs,
) -> Any:
    """
    安全调用函数，捕获异常并返回默认值

    Args:
        func: 要调用的函数
        *args: 位置参数
        default: 出错时的默认返回值
        log_error: 是否记录错误日志
        **kwargs: 关键字参数

    Returns:
        函数返回值或默认值
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        if log_error:
            logger.error(f"Error in {func.__name__}: {e}")
        return default
