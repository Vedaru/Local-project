"""Unit tests for markdown memory tool used by local agent."""

import asyncio
import sys
from pathlib import Path

import pytest

# Ensure `import app` resolves to modules/openmanus/app
sys.path.insert(0, str(Path(__file__).parent.parent / "modules" / "openmanus"))

from app.exceptions import ToolError
from app.tool.memory_md import MemoryMarkdownTool


def _patch_memory_root(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(
        MemoryMarkdownTool,
        "_memory_base_dir",
        classmethod(lambda cls: root),
    )


@pytest.mark.unit
def test_memory_md_write_and_view(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _patch_memory_root(monkeypatch, tmp_path / "agent_memory")
    tool = MemoryMarkdownTool()

    write_result = asyncio.run(
        tool.execute(
            command="write", scope="user", file="preferences.md", content="# User Preferences\n- Speak Chinese"
        )
    )
    assert "Memory file written" in write_result

    view_result = asyncio.run(tool.execute(command="view", scope="user", file="preferences.md"))
    assert "# User Preferences" in view_result
    assert "Speak Chinese" in view_result


@pytest.mark.unit
def test_memory_md_append_insert_and_replace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _patch_memory_root(monkeypatch, tmp_path / "agent_memory")
    tool = MemoryMarkdownTool()

    asyncio.run(tool.execute(command="write", scope="repo", file="notes.md", content="Line1\nLine3"))
    asyncio.run(tool.execute(command="insert", scope="repo", file="notes.md", line=1, content="Line2"))
    asyncio.run(tool.execute(command="append", scope="repo", file="notes.md", content="Line4"))
    asyncio.run(
        tool.execute(
            command="str_replace",
            scope="repo",
            file="notes.md",
            old_str="Line4",
            new_str="Line4-updated",
        )
    )

    final_text = asyncio.run(tool.execute(command="view", scope="repo", file="notes.md"))
    assert final_text == "Line1\nLine2\nLine3\nLine4-updated"


@pytest.mark.unit
def test_memory_md_list_and_path_safety(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _patch_memory_root(monkeypatch, tmp_path / "agent_memory")
    tool = MemoryMarkdownTool()

    asyncio.run(tool.execute(command="write", scope="user", file="a.md", content="A"))
    asyncio.run(tool.execute(command="write", scope="user", file="nested/b.md", content="B"))

    listed = asyncio.run(tool.execute(command="list", scope="user"))
    assert "a.md" in listed
    assert "nested/b.md" in listed

    with pytest.raises(ToolError):
        asyncio.run(tool.execute(command="view", scope="user", file="../escape.md"))
