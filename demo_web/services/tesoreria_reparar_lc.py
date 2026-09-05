"""Repara mezcla LC/Espino: facturas de gastos_espino mal etiquetadas como La Concepción."""
from __future__ import annotations

import sqlite3
from typing import Callable

from demo_web.services.tenant_scope import RAZON_SOCIAL_ESPINO


def sql_buscar_facturas_gastos_espino_mal_clasificadas() -> str:
    """Facturas parent copiadas desde gastos_espino pero con razón social distinta de El Espino."""
    return f"""
        SELECT f.id, f.nro_documento, f.proveedor, f.monto_total, f.fecha_compra
        FROM facturas f
        INNER JOIN gastos_espino g
          ON ABS(COALESCE(g.monto, 0) - COALESCE(f.monto_total, 0)) < 1
         AND substr(COALESCE(g.fecha, ''), 1, 10) = substr(COALESCE(f.fecha_compra, ''), 1, 10)
         AND (
           TRIM(COALESCE(g.item, '')) = TRIM(COALESCE(f.concepto, ''))
           OR TRIM(COALESCE(g.documento, '')) = TRIM(COALESCE(f.nro_documento, ''))
           OR (
             TRIM(COALESCE(g.documento, '')) IN ('S/N', 'SN', '')
             AND UPPER(TRIM(COALESCE(g.item, ''))) = UPPER(TRIM(COALESCE(f.concepto, '')))
           )
         )
        WHERE f.nro_documento NOT LIKE '%_P'
          AND TRIM(COALESCE(f.razon_social, '')) != '{RAZON_SOCIAL_ESPINO}'
          AND f.monto_total > 0
    """


# Compat scripts/diagnóstico (ya no marcan Pagado: reclasifican a El Espino)
sql_buscar_facturas_gastos_espino_pendientes = sql_buscar_facturas_gastos_espino_mal_clasificadas


def sql_buscar_arriendos_paola_pendientes() -> str:
    """Paola mal clasificada: debe coincidir con gastos_espino (El Espino)."""
    return f"""
        SELECT f.id, f.nro_documento, f.proveedor, f.monto_total, f.fecha_compra
        FROM facturas f
        INNER JOIN gastos_espino g
          ON ABS(COALESCE(g.monto, 0) - COALESCE(f.monto_total, 0)) < 1
         AND substr(COALESCE(g.fecha, ''), 1, 10) = substr(COALESCE(f.fecha_compra, ''), 1, 10)
         AND (
           UPPER(COALESCE(g.item, '')) LIKE '%PAOLA%'
           OR UPPER(COALESCE(g.item, '')) LIKE '%ARRIENDO%PAOLA%'
         )
        WHERE f.nro_documento NOT LIKE '%_P'
          AND TRIM(COALESCE(f.razon_social, '')) != '{RAZON_SOCIAL_ESPINO}'
          AND f.monto_total > 0
    """


sql_buscar_arriendos_paola_mayo2026_pendientes = sql_buscar_arriendos_paola_pendientes


def sql_buscar_aplicacion_tracto_historica_pendiente() -> str:
    """Tracto/aplicación Espino mal clasificado en LC."""
    return f"""
        SELECT f.id, f.nro_documento, f.proveedor, f.monto_total, f.fecha_compra
        FROM facturas f
        INNER JOIN gastos_espino g
          ON ABS(COALESCE(g.monto, 0) - COALESCE(f.monto_total, 0)) < 1
         AND substr(COALESCE(g.fecha, ''), 1, 10) = substr(COALESCE(f.fecha_compra, ''), 1, 10)
         AND (
           UPPER(COALESCE(g.item, '')) LIKE '%TRACTO%APLIC%'
           OR UPPER(COALESCE(g.item, '')) LIKE '%APLICACI%'
           OR UPPER(COALESCE(f.concepto, '')) LIKE '%TRACTO%APLIC%'
         )
        WHERE f.nro_documento NOT LIKE '%_P'
          AND TRIM(COALESCE(f.razon_social, '')) != '{RAZON_SOCIAL_ESPINO}'
          AND f.monto_total > 0
    """


sql_buscar_montos_canonicos_lc_pendientes = sql_buscar_facturas_gastos_espino_mal_clasificadas


def _reclasificar_fila_espino(cur, fid: int, nro: str, prov: str, monto: float, fp: str, f_reg: str) -> bool:
    fp_s = str(fp or "")[:10]
    cur.execute(
        f"""UPDATE facturas
           SET razon_social=?,
               estado='Pagado',
               monto_pagado=?,
               fecha_pago=COALESCE(NULLIF(TRIM(fecha_pago), ''), ?),
               metodo_pago=COALESCE(NULLIF(TRIM(metodo_pago), ''), 'Transferencia')
           WHERE id=?
             AND TRIM(COALESCE(razon_social, '')) != ?""",
        (RAZON_SOCIAL_ESPINO, monto, fp_s, fid, RAZON_SOCIAL_ESPINO),
    )
    if cur.rowcount <= 0:
        return False
    cur.execute(
        f"""UPDATE facturas SET razon_social=?
           WHERE nro_documento=? AND proveedor=?""",
        (RAZON_SOCIAL_ESPINO, f"{nro}_P", prov),
    )
    cur.execute(
        "DELETE FROM facturas_abonos WHERE factura_id=? AND UPPER(COALESCE(usuario,'')) = 'MIGRACION'",
        (fid,),
    )
    return True


def _aplicar_reclasificacion_espino(
    conn,
    sql: str,
    *,
    hora_chile_fn: Callable,
    ensure_abonos_fn: Callable,
) -> int:
    try:
        from erp_solo_lectura import conn_en_solo_lectura

        if conn_en_solo_lectura(conn):
            return 0
    except Exception:
        pass
    ensure_abonos_fn(conn)
    cur = conn.cursor()
    try:
        rows = cur.execute(sql).fetchall()
    except sqlite3.OperationalError:
        return 0
    if not rows:
        return 0
    f_reg = hora_chile_fn().strftime("%Y-%m-%d %H:%M:%S")
    vistos: set[int] = set()
    n = 0
    for fid, nro, prov, monto, fp in rows:
        fid = int(fid)
        if fid in vistos:
            continue
        vistos.add(fid)
        if _reclasificar_fila_espino(cur, fid, str(nro), str(prov or ""), float(monto or 0), fp, f_reg):
            n += 1
    if n:
        conn.commit()
    return n


def marcar_arriendos_paola_mayo2026_pagados(conn, *, hora_chile_fn, ensure_abonos_fn) -> int:
    """Compat: reclasifica arriendos Paola (gastos_espino) → El Espino."""
    return _aplicar_reclasificacion_espino(
        conn,
        sql_buscar_arriendos_paola_pendientes(),
        hora_chile_fn=hora_chile_fn,
        ensure_abonos_fn=ensure_abonos_fn,
    )


def reparar_tesoreria_lc_pendientes(conn, *, hora_chile_fn, ensure_abonos_fn) -> int:
    """Quita de Tesorería LC facturas Espino mal sincronizadas (gastos_espino → razon El Espino)."""
    return _aplicar_reclasificacion_espino(
        conn,
        sql_buscar_facturas_gastos_espino_mal_clasificadas(),
        hora_chile_fn=hora_chile_fn,
        ensure_abonos_fn=ensure_abonos_fn,
    )


def aplicar_fix_sqlite_directo(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(facturas)").fetchall()}
        if "monto_pagado" not in cols:
            conn.execute("ALTER TABLE facturas ADD COLUMN monto_pagado REAL DEFAULT 0")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS facturas_abonos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                factura_id INTEGER NOT NULL,
                fecha TEXT,
                monto REAL,
                metodo_pago TEXT,
                usuario TEXT,
                fecha_registro TEXT
            )"""
        )
        conn.commit()
        from datetime import datetime, timezone, timedelta

        def _hora():
            return datetime.now(timezone(timedelta(hours=-4)))

        return reparar_tesoreria_lc_pendientes(
            conn, hora_chile_fn=_hora, ensure_abonos_fn=lambda _c: None,
        )
    finally:
        conn.close()
