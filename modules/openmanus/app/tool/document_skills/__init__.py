from __future__ import annotations

from typing import Any

from .engine import SUPPORTED_FORMATS, generate_document


def create_pptx_from_spec(spec: dict[str, Any], output_path: str) -> str:
    from .ppt_skill import create_pptx_from_spec as _create

    return _create(spec, output_path)


def create_docx_from_spec(spec: dict[str, Any], output_path: str) -> str:
    from .doc_skill import create_docx_from_spec as _create

    return _create(spec, output_path)


def create_pdf_from_spec(spec: dict[str, Any], output_path: str) -> str:
    from .pdf_skill import create_pdf_from_spec as _create

    return _create(spec, output_path)

__all__ = [
    "SUPPORTED_FORMATS",
    "create_pptx_from_spec",
    "create_docx_from_spec",
    "create_pdf_from_spec",
    "generate_document",
]
