"""Metadatos PDF — título interno para que iOS use el nombre al guardar."""
from __future__ import annotations

import re

# El Espino comparte el generador de La Concepción. Estos textos salen en el
# nombre del archivo y en la barra del visor; no se toca el contenido del PDF.
_MARCA_LC_A_ESPINO = (
    ("LA_CONCEPCIÓN", "EL_ESPINO"),
    ("LA_CONCEPCION", "EL_ESPINO"),
    ("LA CONCEPCIÓN", "EL ESPINO"),
    ("LA CONCEPCION", "EL ESPINO"),
    ("La Concepción", "El Espino"),
    ("La Concepcion", "El Espino"),
    ("AGRICOLA LA CONCEPCIÓN", "AGRICOLA EL ESPINO"),
    ("AGRICOLA LA CONCEPCION", "AGRICOLA EL ESPINO"),
    ("Agrícola La Concepción", "Agrícola El Espino"),
)


def marca_corta_pdf() -> str:
    """Nombre corto del predio para el título y el archivo del PDF."""
    try:
        from demo_web.services.tenant_scope import is_espino_tenant
    except Exception:
        return "LA CONCEPCION"
    if is_espino_tenant():
        return "EL ESPINO"
    return "LA CONCEPCION"


def nombre_archivo_segun_tenant(nombre: str) -> str:
    """En El Espino, un nombre que todavía dice La Concepción pasa a El Espino."""
    text = nombre or ""
    if not text or marca_corta_pdf() != "EL ESPINO":
        return text
    for src, dst in _MARCA_LC_A_ESPINO:
        text = text.replace(src, dst)
    return text


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
