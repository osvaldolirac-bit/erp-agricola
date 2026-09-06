"""Metadatos PDF — título interno para que iOS use el nombre al guardar."""
from __future__ import annotations

import re


def _pdf_literal(value: str) -> bytes:
    text = (value or "documento").strip() or "documento"
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return f"({escaped})".encode("latin-1", "replace")


def stamp_pdf_title(blob: bytes, title: str) -> bytes:
    """Inserta /Title en el diccionario Info si falta (Safari iOS → 'unknown')."""
    if not blob.startswith(b"%PDF") or not title:
        return blob
    if b"/Title" in blob:
        return blob

    title_token = b"/Title " + _pdf_literal(title.replace(".pdf", "").replace("_", " "))

    # FPDF y similares: diccionario con /Producer
    m = re.search(rb"<<(\s*/Producer\b)", blob)
    if m:
        pos = m.start(1)
        return blob[:pos] + title_token + b" " + blob[pos:]

    m = re.search(rb"/Producer\b", blob)
    if m:
        return blob[: m.start()] + title_token + b"\n" + blob[m.start() :]

    return blob
