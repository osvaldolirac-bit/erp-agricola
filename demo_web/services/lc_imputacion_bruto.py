"""En LC, un gasto imputado por el bruto no se vuelve a pasar a neto en Costos.

Repuestos, energía y agroquímicos se muestran neto (÷ 1,19) cuando la
imputación se guardó neta. Si el usuario marcó «Monto es bruto», el centro
de costo debe recibir ese mismo monto.
"""
from __future__ import annotations

import sqlite3
import threading
from typing import Any

_tls = threading.local()


def _es_lc() -> bool:
    try:
        from demo_web.services.tenant_scope import tenant_slug

        slug = tenant_slug()
        if slug == "espino":
            return False
        if slug == "concepcion":
            return True
        from demo_web.services.erp_loader import current_tenant

        slug = str((current_tenant() or {}).get("slug") or "").lower()
    except Exception:
        return False
    return slug == "concepcion"


def ensure_costo_respeta_bruto(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(facturas)")}
    if "costo_respeta_bruto" in cols:
        return
    conn.execute(
        "ALTER TABLE facturas ADD COLUMN costo_respeta_bruto INTEGER NOT NULL DEFAULT 0"
    )


def marcar_imputacion_respeta_bruto(
    conn: sqlite3.Connection,
    nro: str,
    proveedor: str,
    respeta: bool,
) -> None:
    """Marca el documento y sus filas _P. respeta=True conserva el bruto en Costos."""
    ensure_costo_respeta_bruto(conn)
    flag = 1 if respeta else 0
    conn.execute(
        """UPDATE facturas
           SET costo_respeta_bruto=?
           WHERE proveedor=? AND (nro_documento=? OR nro_documento=?)""",
        (flag, proveedor, nro, f"{nro}_P"),
    )


def claves_imputacion_bruta(conn: sqlite3.Connection) -> set[tuple[str, str]]:
    """(nro _P, proveedor) cuyo padre se imputó por el bruto."""
    try:
        ensure_costo_respeta_bruto(conn)
    except sqlite3.OperationalError:
        return set()
    rows = conn.execute(
        """SELECT p.nro_documento, p.proveedor
           FROM facturas p
           INNER JOIN facturas f
             ON f.nro_documento = SUBSTR(p.nro_documento, 1, LENGTH(p.nro_documento) - 2)
            AND f.proveedor = p.proveedor
           WHERE p.nro_documento LIKE '%_P'
             AND COALESCE(f.costo_respeta_bruto, 0) = 1"""
    ).fetchall()
    return {(str(nro or ""), str(prov or "")) for nro, prov in rows}


def instalar_imputacion_bruta_lc(erp: Any) -> None:
    """Envuelve el cálculo de Costos del módulo compartido. En Espino no cambia nada."""
    if getattr(erp, "_imputacion_bruta_lc", False):
        return
    original_factores = getattr(erp, "_factores_monto_bruto_facturas", None)
    original_imputada = getattr(erp, "_monto_costos_factura_imputada", None)
    original_matriz = getattr(erp, "_monto_costos_factura_matriz", None)
    if not all(callable(fn) for fn in (original_factores, original_imputada, original_matriz)):
        return

    class _Factores(dict):
        respeta_bruto: set[tuple[str, str]]

    def _factores_monto_bruto_facturas(conn, fi=None, ff=None):  # noqa: ANN001
        base = original_factores(conn, fi, ff) or {}
        factores = _Factores(base)
        factores.respeta_bruto = claves_imputacion_bruta(conn) if _es_lc() else set()
        return factores

    def _monto_costos_factura_imputada(factores, nro_p, prov, monto_imputado):  # noqa: ANN001
        scaled = float(original_imputada(factores, nro_p, prov, monto_imputado) or 0)
        key = (str(nro_p or ""), str(prov or ""))
        respeta = key in getattr(factores, "respeta_bruto", set())
        _tls.respeta_key = key if respeta else None
        _tls.respeta_monto = scaled if respeta else None
        return scaled

    def _monto_costos_factura_matriz(rubro, monto_bruto_escalado, neto_facturas_iva=True):  # noqa: ANN001
        monto = float(monto_bruto_escalado or 0)
        marcado = (
            _tls.respeta_key is not None
            and _tls.respeta_monto is not None
            and abs(monto - float(_tls.respeta_monto)) < 0.02
        )
        _tls.respeta_key = None
        _tls.respeta_monto = None
        if marcado and _es_lc():
            return monto
        return original_matriz(rubro, monto_bruto_escalado, neto_facturas_iva=neto_facturas_iva)

    erp._factores_monto_bruto_facturas = _factores_monto_bruto_facturas
    erp._monto_costos_factura_imputada = _monto_costos_factura_imputada
    erp._monto_costos_factura_matriz = _monto_costos_factura_matriz
    erp._imputacion_bruta_lc = True
