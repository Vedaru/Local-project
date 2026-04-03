from __future__ import annotations

import datetime
from pathlib import Path
from typing import List, Literal, Optional

from app.config import config
from app.exceptions import ToolError
from app.tool import BaseTool

Scope = Literal["user", "session", "repo"]
Command = Literal[
    "list",
    "view",
    "write",
    "append",
    "str_replace",
    "insert",
    "delete",
]

_SESSION_ID = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


class MemoryMarkdownTool(BaseTool):
    """Manage markdown memory files for local agent workflows."""

    name: str = "memory_md"
    description: str = (
        "Manage local markdown memory notes for the agent. "
        "Use scopes: `user` (persistent preferences), `session` (current run), `repo` (project notes)."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": ["list", "view", "write", "append", "str_replace", "insert", "delete"],
                "description": "Operation to execute on markdown memory files.",
            },
            "scope": {
                "type": "string",
                "enum": ["user", "session", "repo"],
                "description": "Memory scope where notes are stored.",
            },
            "file": {
                "type": "string",
                "description": "Relative markdown file path inside scope, e.g. `preferences.md`.",
            },
            "content": {
                "type": "string",
                "description": "Text content for `write`, `append`, and `insert` commands.",
            },
            "old_str": {
                "type": "string",
                "description": "Exact string to replace for `str_replace` command.",
            },
            "new_str": {
                "type": "string",
                "description": "New string used by `str_replace` command.",
            },
            "line": {
                "type": "integer",
                "description": "0-based line number for `insert` command.",
            },
            "view_range": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Optional [start_line, end_line] (1-based, inclusive) for `view`.",
            },
        },
        "required": ["command", "scope"],
    }

    @classmethod
    def _memory_base_dir(cls) -> Path:
        base_dir = config.workspace_root.parent / "data" / "agent_memory_md"
        base_dir.mkdir(parents=True, exist_ok=True)
        return base_dir

    @classmethod
    def _scope_dir(cls, scope: Scope) -> Path:
        base_dir = cls._memory_base_dir()
        if scope == "session":
            target = base_dir / "session" / _SESSION_ID
        elif scope in ("user", "repo"):
            target = base_dir / scope
        else:
            raise ToolError(f"Unsupported scope: {scope}")

        target.mkdir(parents=True, exist_ok=True)
        return target

    @classmethod
    def _resolve_file(cls, scope: Scope, file: str) -> Path:
        if not file:
            raise ToolError("Parameter `file` is required for this command")

        relative = Path(file)
        if relative.is_absolute():
            raise ToolError("`file` must be a relative path within the selected scope")
        if relative.suffix.lower() != ".md":
            raise ToolError("Only markdown files are allowed. `file` must end with `.md`")

        scope_dir = cls._scope_dir(scope).resolve()
        resolved = (scope_dir / relative).resolve()

        try:
            resolved.relative_to(scope_dir)
        except ValueError as e:
            raise ToolError("Path traversal is not allowed in `file`") from e

        return resolved

    @staticmethod
    def _apply_view_range(content: str, view_range: Optional[List[int]]) -> str:
        if not view_range:
            return content
        if len(view_range) != 2:
            raise ToolError("`view_range` must be [start_line, end_line]")

        start_line, end_line = view_range
        if start_line < 1:
            raise ToolError("`view_range` start_line must be >= 1")

        lines = content.splitlines()
        total = len(lines)
        if total == 0:
            return ""

        if start_line > total:
            raise ToolError(f"`view_range` start_line exceeds file length ({total})")
        if end_line == -1:
            end_line = total
        if end_line < start_line or end_line > total:
            raise ToolError(f"`view_range` end_line must be between {start_line} and {total}")

        return "\n".join(lines[start_line - 1 : end_line])

    async def execute(
        self,
        *,
        command: Command,
        scope: Scope,
        file: Optional[str] = None,
        content: Optional[str] = None,
        old_str: Optional[str] = None,
        new_str: Optional[str] = None,
        line: Optional[int] = None,
        view_range: Optional[List[int]] = None,
        **kwargs,
    ) -> str:
        if command == "list":
            scope_dir = self._scope_dir(scope)
            files = sorted(path.relative_to(scope_dir).as_posix() for path in scope_dir.rglob("*.md"))
            if not files:
                return f"No markdown memory files in scope `{scope}`."
            return "\n".join(files)

        target_file = self._resolve_file(scope, file or "")

        if command == "view":
            if not target_file.exists():
                raise ToolError(f"File does not exist: {target_file}")
            text = target_file.read_text(encoding="utf-8")
            return self._apply_view_range(text, view_range)

        if command == "write":
            if content is None:
                raise ToolError("Parameter `content` is required for command: write")
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text(content, encoding="utf-8")
            return f"Memory file written: {target_file}"

        if command == "append":
            if content is None:
                raise ToolError("Parameter `content` is required for command: append")
            target_file.parent.mkdir(parents=True, exist_ok=True)
            existing = target_file.read_text(encoding="utf-8") if target_file.exists() else ""
            payload = content
            if existing and not existing.endswith("\n") and payload and not payload.startswith("\n"):
                payload = "\n" + payload
            target_file.write_text(existing + payload, encoding="utf-8")
            return f"Memory file appended: {target_file}"

        if command == "str_replace":
            if old_str is None or new_str is None:
                raise ToolError("Parameters `old_str` and `new_str` are required for command: str_replace")
            if not target_file.exists():
                raise ToolError(f"File does not exist: {target_file}")
            existing = target_file.read_text(encoding="utf-8")
            count = existing.count(old_str)
            if count == 0:
                raise ToolError("`old_str` not found in file")
            if count > 1:
                raise ToolError("`old_str` appears multiple times; replacement must be unique")
            target_file.write_text(existing.replace(old_str, new_str), encoding="utf-8")
            return f"Memory file updated with str_replace: {target_file}"

        if command == "insert":
            if line is None or content is None:
                raise ToolError("Parameters `line` and `content` are required for command: insert")
            if line < 0:
                raise ToolError("`line` must be >= 0")

            target_file.parent.mkdir(parents=True, exist_ok=True)
            existing = target_file.read_text(encoding="utf-8") if target_file.exists() else ""
            lines = existing.splitlines()
            if line > len(lines):
                raise ToolError(f"`line` must be <= {len(lines)}")

            insert_lines = content.splitlines()
            new_lines = lines[:line] + insert_lines + lines[line:]
            final_text = "\n".join(new_lines)
            if existing.endswith("\n") or content.endswith("\n"):
                final_text += "\n"
            target_file.write_text(final_text, encoding="utf-8")
            return f"Memory file updated with insert: {target_file}"

        if command == "delete":
            if not target_file.exists():
                raise ToolError(f"File does not exist: {target_file}")
            target_file.unlink()
            return f"Memory file deleted: {target_file}"

        raise ToolError(f"Unsupported command: {command}")
