from __future__ import annotations

import re
from typing import Any

from .common import (
    normalize_align,
    normalize_hex_color,
    normalize_selector_name,
    parse_bool,
    parse_float,
)

_RULE_RE = re.compile(r"(?P<selector>[^{}]+)\{(?P<body>[^}]*)\}", re.DOTALL)
_PROPERTY_RE = re.compile(r"(?P<name>[\w\-]+)\s*:\s*(?P<value>[^;]+)")


def _parse_property(name: str, value: str) -> tuple[str, Any] | None:
    key = name.strip().lower()
    raw_value = value.strip()
    lowered = raw_value.lower()

    if key in {"font-family", "font"}:
        return "font_name", raw_value.strip("\"'")
    if key == "font-size":
        return "font_size", parse_float(raw_value, 12.0)
    if key == "font-weight":
        if lowered.isdigit():
            return "bold", int(lowered) >= 600
        return "bold", lowered in {"bold", "bolder"}
    if key == "font-style":
        return "italic", lowered == "italic"
    if key in {"text-decoration", "text-decoration-line"}:
        return "underline", "underline" in lowered
    if key in {"color", "font-color"}:
        return "font_color", normalize_hex_color(raw_value, "000000")
    if key in {"background", "background-color"}:
        return "background_color", normalize_hex_color(raw_value, "FFFFFF")
    if key in {"text-align", "align"}:
        return "align", normalize_align(lowered)
    if key == "line-height":
        return "line_height", parse_float(raw_value, 1.2)
    if key in {"margin-top", "space-before"}:
        return "space_before", parse_float(raw_value, 0.0)
    if key in {"margin-bottom", "space-after"}:
        return "space_after", parse_float(raw_value, 0.0)
    if key in {"letter-spacing", "tracking"}:
        return "letter_spacing", parse_float(raw_value, 0.0)
    if key in {"opacity"}:
        return "opacity", max(0.0, min(1.0, parse_float(raw_value, 1.0)))
    if key in {"bold", "italic", "underline"}:
        return key, parse_bool(raw_value)

    return None


def parse_css_styles(css_text: str | None) -> dict[str, dict[str, Any]]:
    if not css_text:
        return {}

    styles: dict[str, dict[str, Any]] = {}
    for match in _RULE_RE.finditer(css_text):
        selector_group = match.group("selector")
        body = match.group("body")

        raw_selectors = [segment.strip() for segment in selector_group.split(",") if segment.strip()]
        properties: dict[str, Any] = {}

        for property_match in _PROPERTY_RE.finditer(body):
            prop_name = property_match.group("name")
            prop_value = property_match.group("value")
            parsed = _parse_property(prop_name, prop_value)
            if parsed:
                properties[parsed[0]] = parsed[1]

        if not properties:
            continue

        for selector in raw_selectors:
            key = normalize_selector_name(selector)
            if key not in styles:
                styles[key] = {}
            styles[key].update(properties)

    return styles


def parse_css_block_from_spec(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    css_text = spec.get("css")
    if isinstance(css_text, str) and css_text.strip():
        return parse_css_styles(css_text)

    style_map = spec.get("styles")
    if isinstance(style_map, dict):
        normalized: dict[str, dict[str, Any]] = {}
        for selector, style in style_map.items():
            if isinstance(style, dict):
                key = normalize_selector_name(str(selector))
                normalized[key] = dict(style)
        return normalized

    return {}
