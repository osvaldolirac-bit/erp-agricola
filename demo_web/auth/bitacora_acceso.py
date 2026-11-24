"""Conexión de escritura para anotar un acceso en la bitácora del tenant."""
from __future__ import annotations

import os
import sqlite3


def conn_para_bitacora(demo):
    """conectar_db() de un lector abre la base en solo lectura y pierde el ACCESO."""
    path = getattr(demo, "NOMBRE_DB", None) or os.environ.get("ERP_DB") or os.environ.get("ERP_DEMO_DB")
    if not path:
        return demo.conectar_db()
    conn = sqlite3.connect(path, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
    except sqlite3.Error:
        pass
    return conn
