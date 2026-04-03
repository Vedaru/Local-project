from __future__ import annotations

from pathlib import Path
from typing import Any

from reportlab.lib.colors import Color
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .common import (
    color_to_rgb,
    ensure_image_path,
    ensure_parent_dir,
    normalize_align,
    parse_bool,
    parse_length_inch,
    parse_length_pt,
    resolve_style,
)
from .css_parser import parse_css_block_from_spec


def _page_size(page: dict[str, Any]) -> tuple[float, float]:
    size_name = str(page.get("size", "A4")).upper()
    if size_name == "LETTER":
        return LETTER
    if size_name == "A4":
        return A4

    width_in = parse_length_inch(page.get("width"), 8.27)
    height_in = parse_length_inch(page.get("height"), 11.69)
    return (width_in * 72.0, height_in * 72.0)


def _register_fonts(fonts: list[dict[str, Any]] | None) -> None:
    if not fonts:
        return

    for font in fonts:
        if not isinstance(font, dict):
            continue

        name = font.get("name")
        path = font.get("path")
        if not isinstance(name, str) or not isinstance(path, str):
            continue

        font_path = Path(path).expanduser().resolve()
        if not font_path.exists():
            continue

        registered = set(pdfmetrics.getRegisteredFontNames())
        if name in registered:
            continue

        pdfmetrics.registerFont(TTFont(name, str(font_path)))


def _set_fill_color(pdf: canvas.Canvas, color: Any) -> None:
    r, g, b = color_to_rgb(color, (0, 0, 0))
    pdf.setFillColor(Color(r / 255.0, g / 255.0, b / 255.0))


def _set_stroke_color(pdf: canvas.Canvas, color: Any) -> None:
    r, g, b = color_to_rgb(color, (0, 0, 0))
    pdf.setStrokeColor(Color(r / 255.0, g / 255.0, b / 255.0))


def _wrap_line(pdf: canvas.Canvas, text: str, font_name: str, font_size: float, max_width: float) -> list[str]:
    words = text.split()
    if not words:
        return [""]

    lines: list[str] = []
    current = words[0]

    for word in words[1:]:
        candidate = f"{current} {word}"
        if pdf.stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word

    lines.append(current)
    return lines


def _draw_text(
    pdf: canvas.Canvas,
    item: dict[str, Any],
    style: dict[str, Any],
    page_width: float,
    page_height: float,
) -> None:
    text = str(item.get("text", ""))
    font_name = str(style.get("font_name", "Helvetica"))
    font_size = parse_length_pt(style.get("font_size"), 12.0)
    line_height_ratio = float(style.get("line_height", 1.35) or 1.35)
    line_step = font_size * line_height_ratio

    x = parse_length_inch(item.get("x"), 0.8) * 72.0
    y_top = parse_length_inch(item.get("y"), 0.8) * 72.0
    box_width = parse_length_inch(item.get("width"), (page_width / 72.0) - 1.6) * 72.0
    box_height = parse_length_inch(item.get("height"), (page_height / 72.0) - (y_top / 72.0) - 0.8) * 72.0

    align = normalize_align(style.get("align"), "left")

    try:
        pdf.setFont(font_name, font_size)
    except Exception:
        pdf.setFont("Helvetica", font_size)
        font_name = "Helvetica"

    _set_fill_color(pdf, style.get("font_color", "000000"))

    y_cursor = page_height - y_top - font_size

    paragraphs = text.split("\n") if text else [""]
    for paragraph_text in paragraphs:
        wrapped = _wrap_line(pdf, paragraph_text, font_name, font_size, box_width)
        for line in wrapped:
            if y_cursor < page_height - y_top - box_height:
                return

            line_width = pdf.stringWidth(line, font_name, font_size)
            x_draw = x
            if align == "center":
                x_draw = x + max(0.0, (box_width - line_width) / 2.0)
            elif align == "right":
                x_draw = x + max(0.0, box_width - line_width)

            pdf.drawString(x_draw, y_cursor, line)
            y_cursor -= line_step

        y_cursor -= line_step * 0.25


def _draw_image(pdf: canvas.Canvas, item: dict[str, Any], page_width: float, page_height: float) -> None:
    image_path = ensure_image_path(str(item["path"]))
    x = parse_length_inch(item.get("x"), 0.8) * 72.0
    y_top = parse_length_inch(item.get("y"), 0.8) * 72.0

    width = parse_length_inch(item.get("width"), 3.0) * 72.0
    height = parse_length_inch(item.get("height"), 2.0) * 72.0
    y_bottom = page_height - y_top - height

    pdf.drawImage(
        str(image_path),
        x,
        y_bottom,
        width=width,
        height=height,
        preserveAspectRatio=parse_bool(item.get("preserve_aspect"), True),
        mask="auto",
    )


def _draw_rect(pdf: canvas.Canvas, item: dict[str, Any], page_height: float, style: dict[str, Any]) -> None:
    x = parse_length_inch(item.get("x"), 0.8) * 72.0
    y_top = parse_length_inch(item.get("y"), 0.8) * 72.0
    width = parse_length_inch(item.get("width"), 2.0) * 72.0
    height = parse_length_inch(item.get("height"), 1.0) * 72.0
    y_bottom = page_height - y_top - height

    fill_color = item.get("fill_color") or style.get("background_color")
    stroke_color = item.get("stroke_color") or style.get("font_color")

    if fill_color:
        _set_fill_color(pdf, fill_color)
    if stroke_color:
        _set_stroke_color(pdf, stroke_color)

    pdf.rect(x, y_bottom, width, height, stroke=1, fill=1 if fill_color else 0)


def _page_items(page_spec: dict[str, Any], fallback_spec: dict[str, Any]) -> list[dict[str, Any]]:
    items = page_spec.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]

    if fallback_spec.get("title") or fallback_spec.get("content"):
        result: list[dict[str, Any]] = []
        if fallback_spec.get("title"):
            result.append(
                {
                    "type": "text",
                    "text": str(fallback_spec["title"]),
                    "x": 1.0,
                    "y": 1.0,
                    "width": 6.0,
                    "height": 0.8,
                    "style_ref": "title",
                }
            )
        if fallback_spec.get("content"):
            result.append(
                {
                    "type": "text",
                    "text": str(fallback_spec["content"]),
                    "x": 1.0,
                    "y": 2.0,
                    "width": 6.2,
                    "height": 8.5,
                    "style_ref": "body",
                }
            )
        return result

    return []


def create_pdf_from_spec(spec: dict[str, Any], output_path: str) -> str:
    page = spec.get("page") if isinstance(spec.get("page"), dict) else {}
    page_width, page_height = _page_size(page)

    destination = ensure_parent_dir(output_path)
    pdf = canvas.Canvas(str(destination), pagesize=(page_width, page_height))

    _register_fonts(spec.get("fonts") if isinstance(spec.get("fonts"), list) else None)

    default_style = spec.get("default_style") if isinstance(spec.get("default_style"), dict) else {}
    css_styles = parse_css_block_from_spec(spec)

    pages = spec.get("pages") if isinstance(spec.get("pages"), list) else [{"items": []}]

    for page_spec in pages:
        if not isinstance(page_spec, dict):
            continue

        page_style = resolve_style(
            default_style=default_style,
            css_styles=css_styles,
            style_ref=page_spec.get("style_ref"),
            inline_style=page_spec.get("style") if isinstance(page_spec.get("style"), dict) else None,
        )

        background = page_style.get("background_color")
        if background:
            _set_fill_color(pdf, background)
            pdf.rect(0, 0, page_width, page_height, stroke=0, fill=1)

        for item in _page_items(page_spec, spec):
            item_type = str(item.get("type", "text")).lower()
            style = resolve_style(
                default_style=page_style,
                css_styles=css_styles,
                style_ref=item.get("style_ref"),
                inline_style=item.get("style") if isinstance(item.get("style"), dict) else None,
            )

            if item_type in {"text", "paragraph", "heading"}:
                _draw_text(pdf, item, style, page_width, page_height)
                continue

            if item_type in {"image", "picture"} and item.get("path"):
                _draw_image(pdf, item, page_width, page_height)
                continue

            if item_type in {"rect", "rectangle", "shape"}:
                _draw_rect(pdf, item, page_height, style)

        pdf.showPage()

    pdf.save()
    return str(destination)
