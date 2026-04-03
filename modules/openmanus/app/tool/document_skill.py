from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path
from typing import Any, Literal, Optional

from app.config import config
from app.exceptions import ToolError
from app.tool import BaseTool

Command = Literal["generate_css_template", "render_document"]
_SUPPORTED_FORMATS = ("pptx", "docx", "pdf")


_CSS_PRESETS: dict[str, str] = {
    "clean": """/* clean preset */
:root, body, .default {
  font-family: Segoe UI;
  font-size: 18;
  color: #1F2937;
  line-height: 1.35;
  align: left;
}
.title {
  font-family: Segoe UI Semibold;
  font-size: 34;
  color: #0F172A;
  align: left;
}
.subtitle {
  font-size: 24;
  color: #334155;
}
.caption {
  font-size: 12;
  color: #64748B;
}
""",
    "business": """/* business preset */
:root, body, .default {
  font-family: Calibri;
  font-size: 16;
  color: #1E293B;
  line-height: 1.4;
}
.title {
  font-family: Calibri;
  font-size: 36;
  font-weight: 700;
  color: #0B3B6E;
}
.highlight {
  color: #B45309;
  font-weight: 700;
}
.section {
  font-size: 22;
  color: #0F172A;
}
""",
    "poster": """/* poster preset */
:root, body, .default {
  font-family: Arial;
  font-size: 22;
  color: #111827;
  line-height: 1.25;
}
.title {
  font-family: Arial Black;
  font-size: 52;
  color: #B91C1C;
  align: center;
}
.kicker {
  font-size: 18;
  color: #374151;
  align: center;
}
""",
    "report": """/* report preset */
:root, body, .default {
  font-family: Times New Roman;
  font-size: 12;
  color: #111111;
  line-height: 1.5;
  align: justify;
}
.title {
  font-size: 26;
  font-weight: 700;
  align: center;
}
.heading {
  font-size: 16;
  font-weight: 700;
  color: #1F2937;
}
""",
}


class DocumentSkillTool(BaseTool):
    name: str = "document_skill"
    description: str = (
        "Generate PPTX, DOCX, or PDF from a structured spec with CSS-first styling. "
        "Use command='generate_css_template' to draft local CSS, then command='render_document' "
        "to map styles into the target binary format with precise control over fonts, layout, and images."
    )

    parameters: dict = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": ["generate_css_template", "render_document"],
                "description": "Operation to perform.",
            },
            "format": {
                "type": "string",
                "enum": ["pptx", "docx", "pdf"],
                "description": "Target output format.",
            },
            "output_path": {
                "type": "string",
                "description": "Absolute or workspace-relative output file path."
            },
            "spec": {
                "type": "string",
                "description": (
                    "JSON object string describing pages/slides/sections/items. "
                    "Include fields like css, default_style, and content blocks."
                ),
            },
            "css_text": {
                "type": "string",
                "description": "Optional CSS text to inject into spec['css'] before rendering.",
            },
            "preset": {
                "type": "string",
                "enum": ["clean", "business", "poster", "report"],
                "description": "CSS preset used by generate_css_template.",
            },
        },
        "required": ["command"],
    }

    @staticmethod
    def _allowed_roots() -> tuple[Path, ...]:
        return tuple(root.resolve(strict=False) for root in config.workspace_roots)

    @staticmethod
    def _load_document_engine() -> tuple[set[str], Any]:
        module_candidates = ("app.tool.document_skills",)

        for module_name in module_candidates:
            try:
                engine = import_module(module_name)
                supported = getattr(engine, "SUPPORTED_FORMATS", None)
                generator = getattr(engine, "generate_document", None)
                if isinstance(supported, set) and callable(generator):
                    return supported, generator
            except Exception:
                continue

        raise ToolError(
            "Document skill engine is unavailable. Ensure app.tool.document_skills is importable."
        )

    def _resolve_local_path(self, path_value: str, *, field_name: str) -> Path:
        raw = Path(path_value).expanduser()
        resolved = (
            (config.workspace_root / raw).resolve(strict=False)
            if not raw.is_absolute()
            else raw.resolve(strict=False)
        )

        for root in self._allowed_roots():
            try:
                resolved.relative_to(root)
                return resolved
            except ValueError:
                continue

        allowed_roots = ", ".join(str(path) for path in self._allowed_roots())
        raise ToolError(
            f"{field_name} must be inside allowed local directories: {allowed_roots}. Received: {resolved}"
        )

    def _normalize_asset_paths(self, payload: Any, *, base_dir: Path) -> Any:
        if isinstance(payload, list):
            return [self._normalize_asset_paths(item, base_dir=base_dir) for item in payload]

        if isinstance(payload, dict):
            normalized: dict[str, Any] = {}
            kind = str(payload.get("type", "")).lower()

            for key, value in payload.items():
                if key == "path" and isinstance(value, str):
                    suffix = Path(value).suffix.lower()
                    is_asset = suffix in {
                        ".png",
                        ".jpg",
                        ".jpeg",
                        ".gif",
                        ".webp",
                        ".bmp",
                        ".svg",
                        ".ttf",
                        ".otf",
                        ".woff",
                        ".woff2",
                    }
                    if kind in {"image", "picture"} or is_asset:
                        candidate = Path(value).expanduser()
                        resolved_candidate = (
                            (base_dir / candidate).resolve(strict=False)
                            if not candidate.is_absolute()
                            else candidate.resolve(strict=False)
                        )
                        normalized[key] = str(
                            self._resolve_local_path(str(resolved_candidate), field_name="asset path")
                        )
                        continue

                normalized[key] = self._normalize_asset_paths(value, base_dir=base_dir)

            return normalized

        return payload

    async def execute(
        self,
        *,
        command: Command,
        format: Optional[str] = None,
        output_path: Optional[str] = None,
        spec: Optional[str] = None,
        css_text: Optional[str] = None,
        preset: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        if command == "generate_css_template":
            selected_preset = (preset or "clean").strip().lower()
            if selected_preset not in _CSS_PRESETS:
                raise ToolError(
                    f"Unsupported preset: {selected_preset}. Available: {', '.join(sorted(_CSS_PRESETS))}"
                )

            target_format = (format or "pptx").strip().lower()
            if target_format not in _SUPPORTED_FORMATS:
                raise ToolError(
                    f"Unsupported format: {target_format}. Available: {', '.join(sorted(_SUPPORTED_FORMATS))}"
                )

            return (
                f"# CSS template ({selected_preset}) for {target_format}\n"
                f"{_CSS_PRESETS[selected_preset]}"
            )

        if command != "render_document":
            raise ToolError(f"Unsupported command: {command}")

        if not output_path:
            raise ToolError("Parameter `output_path` is required for command: render_document")
        if not spec:
            raise ToolError("Parameter `spec` is required for command: render_document")

        supported_formats, generate_document_fn = self._load_document_engine()

        target_format = format.strip().lower() if isinstance(format, str) and format.strip() else None
        if target_format and target_format not in supported_formats:
            raise ToolError(
                f"Unsupported format: {target_format}. Available: {', '.join(sorted(supported_formats))}"
            )

        resolved_output = self._resolve_local_path(output_path, field_name="output_path")

        try:
            parsed_spec = json.loads(spec)
        except json.JSONDecodeError as exc:
            raise ToolError(f"`spec` must be a valid JSON object string: {exc}") from exc

        if not isinstance(parsed_spec, dict):
            raise ToolError("`spec` must be a JSON object")

        if css_text and isinstance(css_text, str) and css_text.strip():
            parsed_spec["css"] = css_text

        normalized_spec = self._normalize_asset_paths(
            parsed_spec,
            base_dir=resolved_output.parent,
        )
        result = generate_document_fn(
            normalized_spec,
            output_path=str(resolved_output),
            output_format=target_format,
        )

        return json.dumps(
            {
                "success": True,
                "message": "Document generated successfully",
                **result,
            },
            ensure_ascii=False,
            indent=2,
        )
