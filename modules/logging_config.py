"""
Centralized logging configuration for ProjectLocal.

Features:
- Structured JSON file logs (daily rotation + retention)
- Colored human-readable console logs
- Per-module child loggers under the `ProjectLocal.*` namespace
- Context propagation via contextvars (trace_id / request_id / user_id)
- Helper API: get_logger(name), set_context(), clear_context()

This module is the single source of truth for logging in the application; other modules
should call `from modules.logging_config import get_logger` and use
`get_logger('MyModule')` to obtain a logger that writes to the centralized handlers.

Embedded OpenManus code may still use `structlog` / `loguru` internally; new project code
should prefer `get_logger` here for consistent rotation and JSON file output.

Microservices set `request_id` via `set_context(request_id=...)` in HTTP middleware (from the
`x-request-id` header) so structured JSON logs include correlation across Gateway → Orchestrator
→ downstream services.
"""

import contextlib
import contextvars
import json
import logging
import logging.handlers
import os
import sys
import traceback
from datetime import datetime, timezone
from typing import Any, Optional

# Context var for structured logging (per-task / per-thread)
_log_context: contextvars.ContextVar[Optional[dict[str, Any]]] = contextvars.ContextVar("log_context", default=None)


class JSONFormatter(logging.Formatter):
    """Format log records as compact JSON for machine parsing and storage."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "module": getattr(record, "module", None),
            "funcName": getattr(record, "funcName", None),
            "lineno": getattr(record, "lineno", None),
            "thread": getattr(record, "threadName", None),
            "process": getattr(record, "process", None),
            "message": record.getMessage(),
        }

        # Attach exception information if present
        # exc_info 是一个元组 (type, value, traceback)；不能直接 JSON 序列化
        if record.exc_info:
            payload["exception"] = "".join(traceback.format_exception(*record.exc_info))
            # 如果还想保留原始字符串可在这里添加 payload["exc_info"] = ...

        # Merge explicit contextvars (trace_id, request_id, user_id, etc.)
        ctx = _log_context.get() or {}
        if ctx:
            payload["context"] = ctx

        # Include extra attributes set on the LogRecord (avoid duplicates)
        extras = {
            k: v for k, v in record.__dict__.items() if k not in logging.LogRecord.__dict__ and k not in ("msg", "args")
        }
        if extras:
            payload.setdefault("extra", {}).update(extras)

        try:
            return json.dumps(payload, ensure_ascii=False)
        except TypeError as e:
            # 兜底：如果 payload 中仍有不可序列化对象，返回简化错误信息
            return json.dumps(
                {
                    "timestamp": payload.get("timestamp"),
                    "level": "ERROR",
                    "message": f"日志序列化失败: {str(e)} | 原消息: {payload.get('message')}",
                },
                ensure_ascii=False,
            )


class ColoredFormatter(logging.Formatter):
    """Human-friendly console formatter with minimal coloring when supported."""

    COLOR_MAP = {
        "DEBUG": "\u001b[37m",  # white
        "INFO": "\u001b[32m",  # green
        "WARNING": "\u001b[33m",  # yellow
        "ERROR": "\u001b[31m",  # red
        "CRITICAL": "\u001b[41m",  # red background
    }
    RESET = "\u001b[0m"

    def format(self, record: logging.LogRecord) -> str:
        level = record.levelname
        color = self.COLOR_MAP.get(level, "")
        ts = datetime.now().strftime("%H:%M:%S")
        name = record.name
        location = f"{record.module}:{record.lineno}"
        msg = record.getMessage()
        s = f"{ts} [{name}] {level}: {msg} ({location})"
        if color and sys.stdout.isatty():
            return f"{color}{s}{self.RESET}"
        return s


class ContextFilter(logging.Filter):
    """Inject contextvars into LogRecord so formatters can render them."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = _log_context.get() or {}
        for k, v in ctx.items():
            # attach only simple types to avoid serialization surprises
            with contextlib.suppress(Exception):
                setattr(record, k, v)
        return True


# Internal global logger instance for the application namespace
_global_logger: Optional[logging.Logger] = None


def set_context(**kwargs: Any) -> None:
    """Set or update the structured logging context for the current execution context.

    Example: set_context(trace_id='abc123', user_id=42)
    """
    ctx = dict(_log_context.get() or {})
    ctx.update({k: v for k, v in kwargs.items() if v is not None})
    _log_context.set(ctx)


def clear_context() -> None:
    """Clear logging context for current execution context."""
    _log_context.set({})


def setup_logging(
    log_dir: Optional[str] = None,
    level: int = logging.DEBUG,
    console_level: int = logging.INFO,
    retention_days: int = 7,
) -> logging.Logger:
    """Configure centralized logging for ProjectLocal.

    - JSON file logs (rotated daily, kept for `retention_days`)
    - Colored console output for humans
    - Project namespace root logger `ProjectLocal`
    """
    global _global_logger
    if _global_logger is not None:
        return _global_logger

    if log_dir is None:
        # default: <repo>/data/logs
        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "logs")
    os.makedirs(log_dir, exist_ok=True)

    # file name with date (rotate by midnight)
    base_filename = os.path.join(log_dir, "project_local.log")

    logger = logging.getLogger("ProjectLocal")
    logger.setLevel(level)
    logger.propagate = False

    # remove existing handlers to avoid duplication during re-imports
    logger.handlers.clear()

    # Timed rotating JSON file handler (daily)
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=base_filename,
        when="midnight",
        backupCount=max(1, retention_days),
        encoding="utf-8",
        utc=False,
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(JSONFormatter())
    file_handler.addFilter(ContextFilter())

    # Console handler (human readable)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_fmt = ColoredFormatter()
    console_handler.setFormatter(console_fmt)
    console_handler.addFilter(ContextFilter())

    # Add handlers to root ProjectLocal logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    # also route warnings module to logging
    logging.captureWarnings(True)

    # Save global
    _global_logger = logger

    # initial info message
    logger.info(f"Logging initialized — dir={log_dir} level={logging.getLevelName(level)}")
    return logger


def get_logger(name: str = "ProjectLocal") -> logging.Logger:
    """Return a logger in the `ProjectLocal` namespace.

    Usage:
        logger = get_logger('Ear')  # => ProjectLocal.Ear
    """
    global _global_logger
    if _global_logger is None:
        _global_logger = setup_logging()

    if not name or name == "ProjectLocal":
        return _global_logger

    child = logging.getLogger(f"ProjectLocal.{name}")
    # ensure child uses parent's handlers via propagation
    child.propagate = True
    # do not lower the child's level by default; it inherits effective level from parent
    return child


# convenience wrappers
def log_debug(msg: str, **kwargs: Any) -> None:
    get_logger().debug(msg, **kwargs)


def log_info(msg: str, **kwargs: Any) -> None:
    get_logger().info(msg, **kwargs)


def log_warning(msg: str, **kwargs: Any) -> None:
    get_logger().warning(msg, **kwargs)


def log_error(msg: str, **kwargs: Any) -> None:
    get_logger().error(msg, **kwargs)


def log_exception(msg: str, **kwargs: Any) -> None:
    get_logger().exception(msg, **kwargs)
