from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import ensure_parent_dir, load_spec

SUPPORTED_FORMATS = {"pptx", "docx", "pdf"}


def _resolve_format(spec: dict[str, Any], output_path: str | None, output_format: str | None) -> str:
    if output_format:
        fmt = output_format.strip().lower().lstrip(".")
        if fmt in SUPPORTED_FORMATS:
            return fmt

    if output_path:
        suffix = Path(output_path).suffix.lower().lstrip(".")
        if suffix in SUPPORTED_FORMATS:
            return suffix

    inferred = str(spec.get("format", "")).strip().lower().lstrip(".")
    if inferred in SUPPORTED_FORMATS:
        return inferred

    raise ValueError("Unable to determine output format. Provide output_format or output_path with .pptx/.docx/.pdf")


def generate_document(
    spec_input: dict[str, Any] | str,
    *,
    output_path: str,
    output_format: str | None = None,
) -> dict[str, str]:
    spec = load_spec(spec_input)
    fmt = _resolve_format(spec, output_path, output_format)

    destination = ensure_parent_dir(output_path)

    if fmt == "pptx":
        from .ppt_skill import create_pptx_from_spec

        final_path = create_pptx_from_spec(spec, str(destination))
    elif fmt == "docx":
        from .doc_skill import create_docx_from_spec

        final_path = create_docx_from_spec(spec, str(destination))
    elif fmt == "pdf":
        from .pdf_skill import create_pdf_from_spec

        final_path = create_pdf_from_spec(spec, str(destination))
    else:
        raise ValueError(f"Unsupported format: {fmt}")

    return {
        "format": fmt,
        "output_path": final_path,
    }
