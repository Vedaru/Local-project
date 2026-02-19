"""
Memory subsystem logging: delegate to centralized `ProjectLocal.Memory` logger.

Legacy code used a separate file per-day; we now centralize logs while keeping
accessors (`get_log_dir`) for callers that rely on the old API.
"""
from pathlib import Path
from ..logging_config import get_logger as _get_logger
import os

LOG_DIR = Path(__file__).parent.parent.parent / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Use centralized child logger for memory subsystem
memory_logger = _get_logger('Memory')


def get_logger():
    """Return the memory subsystem logger (ProjectLocal.Memory)."""
    return memory_logger


def get_log_dir():
    """Return the central log directory path (keeps backward compatibility)."""
    return str(LOG_DIR)


def get_log_path():
    """Return a recommended per-day filename (keeps backward compatibility)."""
    return os.path.join(get_log_dir(), f"memory_{Path().cwd().name}.log")
