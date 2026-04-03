from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

_HEX_COLOR_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def ensure_parent_dir(path: str | Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def load_spec(spec: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(spec, dict):
        return spec
    if isinstance(spec, str):
        parsed = json.loads(spec)
        if not isinstance(parsed, dict):
            raise ValueError("spec must be a JSON object")
        return parsed
    raise ValueError("spec must be a dict or JSON string")


def parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on", "bold", "italic", "underline"}:
            return True
        if lowered in {"0", "false", "no", "off", "normal", "none"}:
            return False
    return default


def parse_float(value: Any, default: float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        matched = _NUMBER_RE.search(value)
        if matched:
            return float(matched.group(0))
    return default


def parse_length_inch(value: Any, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return default

    lowered = value.strip().lower()
    number = parse_float(lowered, default)
    if lowered.endswith("cm"):
        return number / 2.54
    if lowered.endswith("mm"):
        return number / 25.4
    if lowered.endswith("pt"):
        return number / 72.0
    if lowered.endswith("px"):
        return number / 96.0
    return number


def parse_length_pt(value: Any, default: float) -> float:
    return parse_length_inch(value, default / 72.0) * 72.0


def parse_length_cm(value: Any, default: float) -> float:
    return parse_length_inch(value, default / 2.54) * 2.54


def normalize_hex_color(value: Any, default: str = "000000") -> str:
    if not isinstance(value, str):
        return default
    matched = _HEX_COLOR_RE.match(value.strip())
    if not matched:
        return default
    return matched.group(1).upper()


def color_to_rgb(value: Any, default: tuple[int, int, int] = (0, 0, 0)) -> tuple[int, int, int]:
    color = normalize_hex_color(value, "")
    if not color:
        return default
    return (int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16))


def normalize_align(value: Any, default: str = "left") -> str:
    if not isinstance(value, str):
        return default
    lowered = value.strip().lower()
    if lowered in {"left", "center", "right", "justify"}:
        return lowered
    return default


def normalize_selector_name(selector: str) -> str:
    normalized = (selector or "").strip().lower()
    if normalized.startswith(".") or normalized.startswith("#"):
        normalized = normalized[1:]
    if normalized in {":root", "root", "default", "body"}:
        return "default"
    return normalized


def merge_style_dicts(*styles: Mapping[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for style in styles:
        if style:
            merged.update(style)
    return merged


def _iter_style_refs(style_ref: Any) -> Iterable[str]:
    if style_ref is None:
        return []
    if isinstance(style_ref, str):
        return [style_ref]
    if isinstance(style_ref, list):
        return [str(item) for item in style_ref if item is not None]
    return [str(style_ref)]


def resolve_style(
    *,
    default_style: Mapping[str, Any] | None,
    css_styles: Mapping[str, Mapping[str, Any]] | None,
    style_ref: Any = None,
    inline_style: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if default_style:
        merged.update(default_style)

    style_map = css_styles or {}
    for ref in _iter_style_refs(style_ref):
        key = normalize_selector_name(ref)
        style_entry = style_map.get(key)
        if style_entry:
            merged.update(style_entry)

    if inline_style:
        merged.update(inline_style)

    return merged


def ensure_image_path(path_like: str | Path) -> Path:
    path = Path(path_like).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")
    return path
