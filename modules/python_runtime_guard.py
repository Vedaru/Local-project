"""Python runtime compatibility guard for app and microservices.

Environment variables:
  PROJECT_MIN_PYTHON=3.10
  PROJECT_MAX_PYTHON_EXCLUSIVE=3.12
  PROJECT_STRICT_PYTHON_VERSION=0|1
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any, Optional


def _is_truthy(raw: str | None) -> bool:
    return (raw or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_major_minor(raw: str | None, default: tuple[int, int]) -> tuple[int, int]:
    text = (raw or "").strip()
    if not text:
        return default

    parts = text.split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
    except Exception:
        return default

    if major < 0 or minor < 0:
        return default
    return major, minor


def _normalize_current(current_version: Optional[tuple[int, ...]]) -> tuple[int, int, int]:
    source = current_version or tuple(sys.version_info[:3])
    major = int(source[0]) if len(source) > 0 else 0
    minor = int(source[1]) if len(source) > 1 else 0
    micro = int(source[2]) if len(source) > 2 else 0
    return major, minor, micro


@dataclass(frozen=True)
class PythonRuntimeStatus:
    current: tuple[int, int, int]
    min_inclusive: tuple[int, int]
    max_exclusive: tuple[int, int]
    supported: bool
    strict: bool
    message: str


def evaluate_python_runtime(
    *,
    current_version: Optional[tuple[int, ...]] = None,
    min_inclusive: tuple[int, int] = (3, 10),
    max_exclusive: tuple[int, int] = (3, 12),
    strict: bool = False,
) -> PythonRuntimeStatus:
    current = _normalize_current(current_version)
    current_mm = (current[0], current[1])

    supported = min_inclusive <= current_mm < max_exclusive
    if supported:
        message = (
            f"Python {current[0]}.{current[1]}.{current[2]} is within supported range "
            f">={min_inclusive[0]}.{min_inclusive[1]} and "
            f"<{max_exclusive[0]}.{max_exclusive[1]}."
        )
    else:
        message = (
            f"Python {current[0]}.{current[1]}.{current[2]} is outside supported range "
            f">={min_inclusive[0]}.{min_inclusive[1]} and "
            f"<{max_exclusive[0]}.{max_exclusive[1]}."
        )

    return PythonRuntimeStatus(
        current=current,
        min_inclusive=min_inclusive,
        max_exclusive=max_exclusive,
        supported=supported,
        strict=bool(strict),
        message=message,
    )


def evaluate_python_runtime_from_env(
    *,
    current_version: Optional[tuple[int, ...]] = None,
) -> PythonRuntimeStatus:
    min_inclusive = _parse_major_minor(os.getenv("PROJECT_MIN_PYTHON"), (3, 10))
    max_exclusive = _parse_major_minor(os.getenv("PROJECT_MAX_PYTHON_EXCLUSIVE"), (3, 12))
    strict = _is_truthy(os.getenv("PROJECT_STRICT_PYTHON_VERSION"))

    return evaluate_python_runtime(
        current_version=current_version,
        min_inclusive=min_inclusive,
        max_exclusive=max_exclusive,
        strict=strict,
    )


def ensure_supported_python_runtime(
    *,
    logger: Optional[Any] = None,
    current_version: Optional[tuple[int, ...]] = None,
) -> PythonRuntimeStatus:
    status = evaluate_python_runtime_from_env(current_version=current_version)

    if status.supported:
        if logger is not None:
            try:
                logger.info(status.message)
            except Exception:
                pass
        return status

    if logger is not None:
        try:
            logger.warning(status.message)
        except Exception:
            pass

    if status.strict:
        raise RuntimeError(status.message)
    return status
