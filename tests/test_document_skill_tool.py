"""Unit tests for DocumentSkillTool orchestration and safety checks."""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
from pathlib import Path

import pytest

# Ensure imports for openmanus app and project modules are resolvable.
sys.path.insert(0, str(Path(__file__).parent.parent / "modules" / "openmanus"))


def _load_tool_types():
    tool_error = importlib.import_module("app.exceptions").ToolError
    document_skill_tool = importlib.import_module("app.tool.document_skill").DocumentSkillTool
    return tool_error, document_skill_tool


@pytest.mark.unit
def test_document_skill_generate_css_template():
    _, DocumentSkillTool = _load_tool_types()
    tool = DocumentSkillTool()

    result = asyncio.run(tool.execute(command="generate_css_template", format="pptx", preset="business"))

    assert "CSS template" in result
    assert "font-family" in result


@pytest.mark.unit
def test_document_skill_render_document_uses_engine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _, DocumentSkillTool = _load_tool_types()
    tool = DocumentSkillTool()

    captured: dict = {}

    def fake_generate_document(spec_input, *, output_path: str, output_format: str | None = None):
        captured["spec"] = spec_input
        captured["output_path"] = output_path
        captured["output_format"] = output_format
        return {"format": output_format or "docx", "output_path": output_path}

    monkeypatch.setattr(
        DocumentSkillTool,
        "_load_document_engine",
        staticmethod(lambda: ({"pptx", "docx", "pdf"}, fake_generate_document)),
    )
    monkeypatch.setattr(
        DocumentSkillTool,
        "_allowed_roots",
        staticmethod(lambda: (tmp_path.resolve(),)),
    )

    output = tmp_path / "reports" / "weekly.docx"
    spec = {
        "title": "Weekly Report",
        "sections": [{"type": "paragraph", "text": "Summary"}],
    }

    raw_result = asyncio.run(
        tool.execute(
            command="render_document",
            format="docx",
            output_path=str(output),
            spec=json.dumps(spec),
            css_text=".title { font-size: 28; }",
        )
    )

    result = json.loads(raw_result)

    assert result["success"] is True
    assert Path(result["output_path"]).resolve() == output.resolve()
    assert captured["output_format"] == "docx"
    assert captured["spec"]["css"] == ".title { font-size: 28; }"


@pytest.mark.unit
def test_document_skill_blocks_output_outside_allowed_roots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    ToolError, DocumentSkillTool = _load_tool_types()
    tool = DocumentSkillTool()

    monkeypatch.setattr(
        DocumentSkillTool,
        "_allowed_roots",
        staticmethod(lambda: (tmp_path.resolve(),)),
    )
    monkeypatch.setattr(
        DocumentSkillTool,
        "_load_document_engine",
        staticmethod(lambda: ({"pptx", "docx", "pdf"}, lambda *args, **kwargs: {})),
    )

    forbidden = tmp_path.parent / "outside.docx"

    with pytest.raises(ToolError):
        asyncio.run(
            tool.execute(
                command="render_document",
                format="docx",
                output_path=str(forbidden),
                spec=json.dumps({"title": "x"}),
            )
        )
