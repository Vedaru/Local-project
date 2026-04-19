"""Tests for modules.security_tools."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from modules.security_tools import is_tool_allowed


def test_tools_allowed_by_default() -> None:
    assert is_tool_allowed("browser_use") is True
    assert is_tool_allowed("python_execute") is True


def test_tools_respect_yaml_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tuning_file = tmp_path / "tuning.yaml"
    tuning_file.write_text(
        yaml.dump(
            {
                "security": {
                    "tools": {
                        "browser_automation_enabled": False,
                        "python_execution_enabled": True,
                        "shell_execution_enabled": True,
                        "file_editor_enabled": True,
                        "mcp_enabled": True,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("modules.config_tuning.TUNING_PATH", str(tuning_file))
    assert is_tool_allowed("browser_use") is False
    assert is_tool_allowed("crawl4ai") is False
    assert is_tool_allowed("python_execute") is True


def test_env_overrides_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tuning_file = tmp_path / "tuning.yaml"
    tuning_file.write_text(
        yaml.dump({"security": {"tools": {"browser_automation_enabled": False}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr("modules.config_tuning.TUNING_PATH", str(tuning_file))
    monkeypatch.setenv("SECURITY_TOOL_BROWSER_AUTOMATION_ENABLED", "true")
    assert is_tool_allowed("browser_use") is True


def _security_tools_yaml(**kwargs: bool) -> dict:
    base = {
        "browser_automation_enabled": True,
        "python_execution_enabled": True,
        "shell_execution_enabled": True,
        "file_editor_enabled": True,
        "mcp_enabled": True,
    }
    base.update(kwargs)
    return {"security": {"tools": base}}


@pytest.mark.parametrize(
    "tool_name,disabled_key,expected",
    [
        ("browser_use", "browser_automation_enabled", False),
        ("crawl4ai", "browser_automation_enabled", False),
        ("python_execute", "python_execution_enabled", False),
        ("bash", "shell_execution_enabled", False),
        ("str_replace_editor", "file_editor_enabled", False),
        ("mcp", "mcp_enabled", False),
        ("mcp_server", "mcp_enabled", False),
        ("unknown_custom_tool", "browser_automation_enabled", True),
    ],
)
def test_tool_gating_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    disabled_key: str,
    expected: bool,
) -> None:
    """Each category disables exactly one tool; unrelated tools stay allowed if category unknown."""
    kwargs = {disabled_key: False}
    tuning_file = tmp_path / "tuning.yaml"
    tuning_file.write_text(yaml.dump(_security_tools_yaml(**kwargs)), encoding="utf-8")
    monkeypatch.setattr("modules.config_tuning.TUNING_PATH", str(tuning_file))
    assert is_tool_allowed(tool_name) is expected

