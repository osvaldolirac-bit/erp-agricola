"""Almacén de PDFs en disco (compatible con varios workers gunicorn)."""
from __future__ import annotations

import os
import re
import secrets
import time
from pathlib import Path

_TOKEN_RE = re.compile(r"^[a-f0-9]{20}$")
_TTL_SEC = int(os.environ.get("ERP_PDF_CACHE_TTL", "7200"))


def _cache_dir() -> Path:
    root = Path(os.environ.get("ERP_PDF_CACHE", "/tmp/erp_pdf_cache"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def store_pdf(blob: bytes, filename: str) -> str:
    token = secrets.token_hex(10)
    base = _cache_dir()
    (base / token).write_bytes(blob)
    (base / f"{token}.meta").write_text(filename or "documento.pdf", encoding="utf-8")
    return token


def get_pdf(token: str) -> tuple[bytes, str] | None:
    if not token or not _TOKEN_RE.match(token):
        return None
    base = _cache_dir()
    path = base / token
    meta = base / f"{token}.meta"
    if not path.is_file():
        return None
    if time.time() - path.stat().st_mtime > _TTL_SEC:
        path.unlink(missing_ok=True)
        meta.unlink(missing_ok=True)
        return None
    name = meta.read_text(encoding="utf-8").strip() if meta.is_file() else "documento.pdf"
    return path.read_bytes(), name or "documento.pdf"
