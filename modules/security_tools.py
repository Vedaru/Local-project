"""
Central mapping from OpenManus tool names to project security toggles.

Policy is loaded from project_config.yaml (`security.tools`) with environment overrides.
"""

from __future__ import annotations

import os
from typing import FrozenSet

from modules.logging_config import get_logger

_logger = get_logger("SecurityTools")

# tool_name -> env suffix for override, e.g. SECURITY_TOOL_BROWSER_AUTOMATION_ENABLED
_CATEGORY_ENV = {
    "browser": "BROWSER_AUTOMATION",
    "python": "PYTHON_EXECUTION",
    "shell": "SHELL_EXECUTION",
    "file_edit": "FILE_EDITOR",
    "mcp": "MCP",
}

# OpenManus / agent tool names -> category key
_TOOL_CATEGORY: dict[str, str] = {
    "browser_use": "browser",
    "crawl4ai": "browser",
    "python_execute": "python",
    "bash": "shell",
    "str_replace_editor": "file_edit",
    "mcp": "mcp",
}


def _env_override_bool(category: str) -> bool | None:
    suffix = _CATEGORY_ENV.get(category)
    if not suffix:
        return None
    raw = os.getenv(f"SECURITY_TOOL_{suffix}_ENABLED")
    if raw is None or str(raw).strip() == "":
        return None
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _defaults_from_tuning() -> dict[str, bool]:
    try:
        from modules.config_tuning import load_tuning

        st = load_tuning().security_tools
        return {
            "browser": st.browser_automation_enabled,
            "python": st.python_execution_enabled,
            "shell": st.shell_execution_enabled,
            "file_edit": st.file_editor_enabled,
            "mcp": st.mcp_enabled,
        }
    except Exception as exc:
        if isinstance(exc, (ImportError, OSError, ValueError)):
            _logger.debug("security.tools: tuning load skipped; defaulting all categories to enabled (%s)", exc)
        else:
            _logger.warning(
                "security.tools: unexpected error loading TuningConfig; defaulting all categories to enabled",
                exc_info=True,
            )
        return {
            "browser": True,
            "python": True,
            "shell": True,
            "file_edit": True,
            "mcp": True,
        }


def is_tool_allowed(tool_name: str) -> bool:
    """Return False if the tool is disabled by security policy."""
    name = (tool_name or "").strip().lower()
    category: str | None
    if name.startswith("mcp_"):
        category = "mcp"
    else:
        category = _TOOL_CATEGORY.get(name)
    if category is None:
        return True

    defaults = _defaults_from_tuning()
    base = defaults.get(category, True)
    override = _env_override_bool(category)
    allowed = override if override is not None else base
    return bool(allowed)


def disabled_tool_names() -> FrozenSet[str]:
    """Set of tool names that are currently disabled (for diagnostics)."""
    result: set[str] = set()
    for tname in _TOOL_CATEGORY:
        if not is_tool_allowed(tname):
            result.add(tname)
    return frozenset(result)
