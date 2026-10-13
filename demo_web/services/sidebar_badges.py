"""Contadores de pendientes para sidebar Flask (/agricola) y menú Streamlit."""
from __future__ import annotations

import re
from typing import Any

_BADGE_SUFFIX = re.compile(r"\s+\(\d+\)$")

MODULOS_BADGE = ("Petróleo", "Maquinaria", "Riego")


def _label_with_count(label: str, n: int) -> str:
    base = _BADGE_SUFFIX.sub("", label or "")
    if n <= 0:
        return base
    return f"{base} ({n})"


def contar_pendientes_modulo(conn, module_key: str) -> int:
    if module_key == "Petróleo":
        from demo_web.services.salida_petroleo import contar_pendientes, habilitado

        if not habilitado():
            return 0
        return int(contar_pendientes(conn) or 0)
    if module_key == "Maquinaria":
        from erp_maquinaria import contar_maquinaria_casos_abiertos

        return int(contar_maquinaria_casos_abiertos(conn) or 0)
    if module_key == "Riego":
        from demo_web.services.registro_riego import contar_pendientes, habilitado

        if not habilitado():
            return 0
        return int(contar_pendientes(conn) or 0)
    return 0


def conteos_sidebar(conn, module_keys: set[str] | None = None) -> dict[str, int]:
    """Devuelve {module_key: n} solo para módulos con n > 0."""
    keys = module_keys or set(MODULOS_BADGE)
    out: dict[str, int] = {}
    for key in MODULOS_BADGE:
        if key not in keys:
            continue
        try:
            n = contar_pendientes_modulo(conn, key)
            if n > 0:
                out[key] = n
        except Exception:
            continue
    return out


def aplicar_badges_labels_menu(opts: dict[str, Any], conn, module_keys: set[str] | None = None) -> dict[str, Any]:
    """Streamlit: añade (N) al label del menú. Flask usa badge_count en build_menu."""
    counts = conteos_sidebar(conn, module_keys)
    if not counts:
        return opts
    new_opts: dict[str, Any] = {}
    for label, key in opts.items():
        n = counts.get(str(key), 0)
        new_opts[_label_with_count(str(label), n)] = key
    return new_opts
