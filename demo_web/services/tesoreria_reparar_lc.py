"""Reparación Tesorería LC: históricos ya pagados que no deben quedar Pendiente."""
from __future__ import annotations

import sqlite3
from typing import Callable


def _marcar_pagado(
    cur,
    fid: int,
    monto: float,
    fp: str,
    metodo: str,
    f_reg: str,
) -> bool:
    fp_s = str(fp or "")[:10]
    cur.execute(
        """UPDATE facturas
           SET estado='Pagado', monto_pagado=?, fecha_pago=?, metodo_pago=?
           WHERE id=? AND UPPER(TRIM(COALESCE(estado, ''))) IN ('PENDIENTE', '')""",
        (monto, fp_s, metodo, fid),
    )
    if cur.rowcount <= 0:
        return False
    if not cur.execute("SELECT 1 FROM facturas_abonos WHERE factura_id=?", (fid,)).fetchone():
        cur.execute(
            """INSERT INTO facturas_abonos (factura_id, fecha, monto, metodo_pago, usuario, fecha_registro)
               VALUES (?,?,?,?,?,?)""",
            (fid, fp_s, monto, metodo, "MIGRACION", f_reg),
        )
    return True


def _sql_estado_pendiente(col: str = "estado") -> str:
    return f"UPPER(TRIM(COALESCE({col}, ''))) IN ('PENDIENTE', '')"


def sql_buscar_arriendos_paola_pendientes() -> str:
    """Cualquier arriendo María Paola aún Pendiente."""
    return f"""
        SELECT id, nro_documento, monto_total, fecha_compra
        FROM facturas
        WHERE nro_documento NOT LIKE '%_P'
          AND {_sql_estado_pendiente()}
          AND monto_total > 0
          AND (
            TRIM(nro_documento) = '39280236'
            OR UPPER(TRIM(nro_documento)) GLOB 'INT-20260517-*'
            OR (
              (
                UPPER(COALESCE(proveedor, '')) LIKE '%PAOLA%'
                OR UPPER(COALESCE(proveedor, '')) LIKE '%TORRES%ORTIZ%'
                OR UPPER(COALESCE(concepto, '')) LIKE '%PAOLA%'
                OR UPPER(COALESCE(concepto, '')) LIKE '%TORRES%ORTIZ%'
              )
              AND (
                TRIM(COALESCE(tipo_gasto, '')) = 'Arriendos'
                OR UPPER(COALESCE(concepto, '')) LIKE '%ARRIENDO%'
              )
            )
          )
    """


def sql_buscar_aplicacion_tracto_historica_pendiente() -> str:
    """Servicios aplicación / tracto ya cancelados (p. ej. Danixa arañita)."""
    return f"""
        SELECT id, nro_documento, monto_total, fecha_compra
        FROM facturas
        WHERE nro_documento NOT LIKE '%_P'
          AND {_sql_estado_pendiente()}
          AND monto_total > 0
          AND (
            UPPER(COALESCE(concepto, '')) LIKE '%DANIXA%APLIC%'
            OR UPPER(COALESCE(concepto, '')) LIKE '%APLICACI%ARAÑ%'
            OR UPPER(COALESCE(concepto, '')) LIKE '%APLICACI%ARAN%'
            OR UPPER(COALESCE(concepto, '')) LIKE '%TRACTO%APLIC%'
            OR (
              UPPER(COALESCE(proveedor, '')) LIKE '%DANIXA%'
              AND UPPER(COALESCE(concepto, '')) LIKE '%APLIC%'
            )
          )
    """


def sql_buscar_facturas_gastos_espino_pendientes() -> str:
    """Facturas parent que replican filas de gastos_espino (histórico ya pagado)."""
    est = _sql_estado_pendiente("f.estado")
    return f"""
        SELECT f.id, f.nro_documento, f.monto_total, f.fecha_compra
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
          AND {est}
          AND f.monto_total > 0
    """


def sql_buscar_montos_canonicos_lc_pendientes() -> str:
    """Montos/fechas históricos LC ya cancelados (fallback si falla join gastos_espino)."""
    est = _sql_estado_pendiente()
    return f"""
        SELECT id, nro_documento, monto_total, fecha_compra
        FROM facturas
        WHERE nro_documento NOT LIKE '%_P'
          AND {est}
          AND monto_total > 0
          AND (
            (substr(COALESCE(fecha_compra, ''), 1, 10) = '2026-05-17'
             AND ABS(COALESCE(monto_total, 0) - 7000000) < 1
             AND (
               UPPER(COALESCE(concepto, '')) LIKE '%PAOLA%'
               OR UPPER(COALESCE(concepto, '')) LIKE '%ARRIENDO%'
               OR UPPER(COALESCE(proveedor, '')) LIKE '%PAOLA%'
             ))
            OR (substr(COALESCE(fecha_compra, ''), 1, 10) = '2026-05-17'
                AND ABS(COALESCE(monto_total, 0) - 6433506) < 1)
            OR (substr(COALESCE(fecha_compra, ''), 1, 10) = '2026-01-25'
                AND ABS(COALESCE(monto_total, 0) - 50000) < 1
                AND (
                  UPPER(COALESCE(concepto, '')) LIKE '%DANIXA%'
                  OR UPPER(COALESCE(concepto, '')) LIKE '%APLIC%'
                  OR UPPER(COALESCE(proveedor, '')) LIKE '%DANIXA%'
                ))
          )
    """


def _aplicar_sql_pendientes(
    conn,
    sql: str,
    *,
    hora_chile_fn: Callable,
    ensure_abonos_fn: Callable,
    metodo: str,
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
    for fid, _nro, monto, fp in rows:
        fid = int(fid)
        if fid in vistos:
            continue
        vistos.add(fid)
        if _marcar_pagado(cur, fid, float(monto or 0), fp, metodo, f_reg):
            n += 1
    if n:
        conn.commit()
    return n


def marcar_arriendos_paola_mayo2026_pagados(conn, *, hora_chile_fn, ensure_abonos_fn) -> int:
    """Compat: arriendos Paola pendientes → Pagado."""
    return _aplicar_sql_pendientes(
        conn,
        sql_buscar_arriendos_paola_pendientes(),
        hora_chile_fn=hora_chile_fn,
        ensure_abonos_fn=ensure_abonos_fn,
        metodo="Histórico (arriendo pagado)",
    )


def reparar_tesoreria_lc_pendientes(conn, *, hora_chile_fn, ensure_abonos_fn) -> int:
    """Quita de Pendiente históricos mal sincronizados (Paola, aplicación tracto, gastos_espino)."""
    total = 0
    total += _aplicar_sql_pendientes(
        conn,
        sql_buscar_facturas_gastos_espino_pendientes(),
        hora_chile_fn=hora_chile_fn,
        ensure_abonos_fn=ensure_abonos_fn,
        metodo="Histórico (gastos_espino)",
    )
    total += _aplicar_sql_pendientes(
        conn,
        sql_buscar_arriendos_paola_pendientes(),
        hora_chile_fn=hora_chile_fn,
        ensure_abonos_fn=ensure_abonos_fn,
        metodo="Histórico (arriendo pagado)",
    )
    total += _aplicar_sql_pendientes(
        conn,
        sql_buscar_aplicacion_tracto_historica_pendiente(),
        hora_chile_fn=hora_chile_fn,
        ensure_abonos_fn=ensure_abonos_fn,
        metodo="Histórico (servicio aplicación pagado)",
    )
    total += _aplicar_sql_pendientes(
        conn,
        sql_buscar_montos_canonicos_lc_pendientes(),
        hora_chile_fn=hora_chile_fn,
        ensure_abonos_fn=ensure_abonos_fn,
        metodo="Histórico (canónico LC)",
    )
    return total


# Alias retrocompat scripts
sql_buscar_arriendos_paola_mayo2026_pendientes = sql_buscar_arriendos_paola_pendientes


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
