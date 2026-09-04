"""Arriendos LC ya pagados que no deben quedar Pendiente en Tesorería."""
from __future__ import annotations

import sqlite3


def sql_buscar_arriendos_paola_mayo2026_pendientes() -> str:
    """Facturas Paola may-2026 (abono + saldo) aún Pendiente."""
    return """
        SELECT id, nro_documento, monto_total, fecha_compra
        FROM facturas
        WHERE nro_documento NOT LIKE '%_P'
          AND TRIM(COALESCE(estado, '')) = 'Pendiente'
          AND monto_total > 0
          AND (
            TRIM(nro_documento) = '39280236'
            OR UPPER(TRIM(nro_documento)) GLOB 'INT-20260517-*'
            OR (
              fecha_compra >= '2026-05-01' AND fecha_compra <= '2026-05-31'
              AND (
                ABS(COALESCE(monto_total, 0) - 7000000) < 1
                OR ABS(COALESCE(monto_total, 0) - 6433506) < 1
              )
              AND (
                UPPER(COALESCE(proveedor, '')) LIKE '%PAOLA%'
                OR UPPER(COALESCE(proveedor, '')) LIKE '%TORRES%'
                OR UPPER(COALESCE(concepto, '')) LIKE '%PAOLA%'
                OR UPPER(COALESCE(concepto, '')) LIKE '%TORRES%'
                OR UPPER(COALESCE(concepto, '')) LIKE '%ARRIENDO%'
                OR TRIM(COALESCE(tipo_gasto, '')) = 'Arriendos'
              )
            )
          )
    """


def marcar_arriendos_paola_mayo2026_pagados(conn, *, hora_chile_fn, ensure_abonos_fn) -> int:
    """
    Idempotente: marca Pagado abono ($7M) y saldo ($6,4M) María Paola may-2026.
    Retorna cantidad de filas corregidas.
    """
    try:
        from erp_solo_lectura import conn_en_solo_lectura

        if conn_en_solo_lectura(conn):
            return 0
    except Exception:
        pass

    ensure_abonos_fn(conn)
    cur = conn.cursor()
    rows = cur.execute(sql_buscar_arriendos_paola_mayo2026_pendientes()).fetchall()
    if not rows:
        return 0

    f_reg = hora_chile_fn().strftime("%Y-%m-%d %H:%M:%S")
    metodo = "Histórico (arriendo pagado)"
    n = 0
    for fid, nro, monto, fp in rows:
        m = float(monto or 0)
        if m <= 0:
            continue
        fp_s = str(fp or "")[:10]
        cur.execute(
            """UPDATE facturas
               SET estado='Pagado', monto_pagado=?, fecha_pago=?, metodo_pago=?
               WHERE id=? AND TRIM(COALESCE(estado, '')) = 'Pendiente'""",
            (m, fp_s, metodo, fid),
        )
        if cur.rowcount <= 0:
            continue
        n += 1
        if not cur.execute("SELECT 1 FROM facturas_abonos WHERE factura_id=?", (fid,)).fetchone():
            cur.execute(
                """INSERT INTO facturas_abonos (factura_id, fecha, monto, metodo_pago, usuario, fecha_registro)
                   VALUES (?,?,?,?,?,?)""",
                (fid, fp_s, m, metodo, "MIGRACION", f_reg),
            )
    if n:
        conn.commit()
    return n


def aplicar_fix_sqlite_directo(db_path: str) -> int:
    """Fix en VPS sin importar streamlit/app_concepcion."""
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
        from datetime import datetime, timezone, timedelta

        def _hora():
            return datetime.now(timezone(timedelta(hours=-4)))

        def _ensure_abonos(c):
            pass

        return marcar_arriendos_paola_mayo2026_pagados(
            conn, hora_chile_fn=_hora, ensure_abonos_fn=_ensure_abonos,
        )
    finally:
        conn.close()
