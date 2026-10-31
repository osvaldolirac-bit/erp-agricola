"""Contadores de pendientes para sidebar Flask (/agricola) y menú Streamlit."""
from __future__ import annotations

import re
import sqlite3
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


def _n_autorizar_riego(conn) -> int:
    try:
        from demo_web.services.registro_riego import contar_pendientes, habilitado

        if not habilitado():
            return 0
        return int(contar_pendientes(conn) or 0)
    except Exception:
        return 0


def avisos_riego_sidebar(conn) -> list[dict[str, str]]:
    """Pastillas de Riego en el menú de La Concepción.

    Azul: sectores regando o en pausa. Naranja: en cola. Amarillo: por autorizar.
    El Espino sigue con el número único de pendientes.
    """
    from demo_web.services.tenant_scope import is_concepcion_tenant

    if not is_concepcion_tenant():
        return []
    n_run = n_pausa = n_cola = 0
    try:
        rows = conn.execute(
            """SELECT i.estado, COUNT(*)
               FROM hydrawise_cola_item i
               JOIN hydrawise_cola c ON c.id = i.cola_id
               WHERE c.estado IN ('programado', 'en_ejecucion')
                 AND i.estado IN ('corriendo', 'pausado', 'pendiente')
               GROUP BY i.estado"""
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    for estado, n in rows:
        est = str(estado or "")
        if est == "corriendo":
            n_run = int(n or 0)
        elif est == "pausado":
            n_pausa = int(n or 0)
        elif est == "pendiente":
            n_cola = int(n or 0)
    n_auth = _n_autorizar_riego(conn)
    out: list[dict[str, str]] = []
    if n_run > 0:
        out.append(
            {
                "tipo": "regando",
                "clase": "nav-riego-run",
                "texto": f"{n_run} S regando",
                "title": "Sectores regando",
            }
        )
    if n_pausa > 0:
        out.append(
            {
                "tipo": "pausa",
                "clase": "nav-riego-run",
                "texto": f"{n_pausa} S en pausa",
                "title": "Sectores en pausa",
            }
        )
    if n_cola > 0:
        out.append(
            {
                "tipo": "cola",
                "clase": "nav-riego-cola",
                "texto": f"{n_cola} S en cola",
                "title": "Sectores en cola",
            }
        )
    if n_auth > 0:
        out.append(
            {
                "tipo": "autorizar",
                "clase": "nav-riego-auth",
                "texto": f"{n_auth} autorizar",
                "title": "Riegos por autorizar",
            }
        )
    return out


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
