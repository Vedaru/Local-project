"""Unit tests for CSS-style parsing used by document skills."""

import importlib
import sys
from pathlib import Path

import pytest

# Ensure `import app` resolves to modules/openmanus/app
sys.path.insert(0, str(Path(__file__).parent.parent / "modules" / "openmanus"))


def _parse_css_styles(css: str):
    parser_module = importlib.import_module("app.tool.document_skills.css_parser")
    return parser_module.parse_css_styles(css)


@pytest.mark.unit
def test_parse_css_styles_basic_mapping():
    css = """
    .title {
      font-family: Calibri;
      font-size: 36;
      color: #1a2b3c;
      text-align: center;
      font-weight: 700;
    }

    body {
      line-height: 1.5;
      font-style: italic;
      text-decoration: underline;
    }
    """

    styles = _parse_css_styles(css)

    assert "title" in styles
    assert styles["title"]["font_name"] == "Calibri"
    assert styles["title"]["font_size"] == pytest.approx(36.0)
    assert styles["title"]["font_color"] == "1A2B3C"
    assert styles["title"]["align"] == "center"
    assert styles["title"]["bold"] is True

    assert "default" in styles
    assert styles["default"]["line_height"] == pytest.approx(1.5)
    assert styles["default"]["italic"] is True
    assert styles["default"]["underline"] is True


@pytest.mark.unit
def test_parse_css_styles_supports_multiple_selectors():
    css = ".title, .hero { color: #445566; font-size: 30; }"

    styles = _parse_css_styles(css)

    assert styles["title"]["font_color"] == "445566"
    assert styles["hero"]["font_color"] == "445566"
    assert styles["title"]["font_size"] == pytest.approx(30.0)
    assert styles["hero"]["font_size"] == pytest.approx(30.0)
