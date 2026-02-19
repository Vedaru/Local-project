"""
Avatar 日志模块 - 统一的日志管理
"""

from typing import Optional
from ..logging_config import get_logger as _get_global_logger


class AvatarLogger:
    """Adapter for avatar-specific logging that delegates to the centralized logger.

    Other avatar modules continue to import from `modules.avatar.logger` and call
    `log_info(...)` etc.; internally we forward those calls to
    `ProjectLocal.Avatar` child logger so logs remain module-separated and
    serialized to the central JSON files.
    """

    _instance: Optional['AvatarLogger'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # idempotent init
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.logger = _get_global_logger('Avatar')
        self.logger.debug("AvatarLogger initialized (delegated to centralized logger)")

    def debug(self, message: str):
        self.logger.debug(message)

    def info(self, message: str):
        self.logger.info(message)

    def warning(self, message: str):
        self.logger.warning(message)

    def error(self, message: str):
        self.logger.error(message)

    def js_log(self, level: str, message: str, line_number: int):
        self.logger.debug(f"[JS {level}] {message} (line {line_number})")


# global accessor
_logger: Optional[AvatarLogger] = None


def get_logger() -> AvatarLogger:
    global _logger
    if _logger is None:
        _logger = AvatarLogger()
    return _logger


# convenience
def log_debug(message: str):
    get_logger().debug(message)


def log_info(message: str):
    get_logger().info(message)


def log_warning(message: str):
    get_logger().warning(message)


def log_error(message: str):
    get_logger().error(message)


def log_js(level: str, message: str, line_number: int):
    get_logger().js_log(level, message, line_number)
