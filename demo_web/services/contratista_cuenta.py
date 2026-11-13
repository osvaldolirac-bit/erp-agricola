"""Cuenta corriente de contratistas: centro de costo y tipo de trabajo.

El libro mayor marca cada cargo como TRABAJO. El tipo se escribe a mano
y el PDF muestra el centro de costo de la imputación _P.
"""
from __future__ import annotations

import sqlite3

import pandas as pd

COLUMNA = "tipo_trabajo"
LARGO = 80


def asegurar_tipo_trabajo(conn: sqlite3.Connection) -> bool:
    """Agrega facturas.tipo_trabajo si falta. En solo lectura no altera."""
    try:
        from erp_solo_lectura import conn_en_solo_lectura

        if conn_en_solo_lectura(conn):
            return _tiene_columna(conn)
    except Exception:
        pass
    if _tiene_columna(conn):
        return True
    conn.execute(f"ALTER TABLE facturas ADD COLUMN {COLUMNA} TEXT DEFAULT ''")
    return True


def _tiene_columna(conn: sqlite3.Connection) -> bool:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(facturas)")}
    return COLUMNA in cols


def _limpiar(texto: str) -> str:
    return " ".join((texto or "").split())[:LARGO]


def guardar_tipo_trabajo(
    conn: sqlite3.Connection,
    nro_documento: str,
    contratista_id: int,
    texto: str,
    razon: str = "",
) -> bool:
    """Guarda el tipo en la cabecera del trabajo, no en la fila _P."""
    nro = (nro_documento or "").strip()
    if not nro or nro.endswith("_P") or int(contratista_id) <= 0:
        return False
    if not asegurar_tipo_trabajo(conn):
        return False
    cur = conn.execute(
        f"""UPDATE facturas SET {COLUMNA}=?
            WHERE nro_documento=?
              AND nro_documento NOT LIKE '%_P'
              AND monto_total > 0
              AND (
                    COALESCE(contratista_id, 0)=?
                    OR UPPER(TRIM(proveedor))=UPPER(TRIM(?))
                  )""",
        (_limpiar(texto), nro, int(contratista_id), (razon or "").strip()),
    )
    return cur.rowcount > 0


def centros_imputados(conn: sqlite3.Connection, documentos: list[str]) -> dict[str, str]:
    """Documento padre -> centros de costo de sus imputaciones, en orden de alta."""
    padres = []
    for doc in documentos:
        nro = str(doc or "").strip()
        if nro and not nro.endswith("_P") and nro not in padres:
            padres.append(nro)
    if not padres:
        return {}
    hijos = [f"{nro}_P" for nro in padres]
    marcas = ",".join("?" * len(hijos))
    filas = conn.execute(
        f"""SELECT nro_documento, centro_costo
            FROM facturas
            WHERE nro_documento IN ({marcas})
            ORDER BY id""",
        hijos,
    ).fetchall()
    grupos: dict[str, list[str]] = {}
    for nro, cc in filas:
        base = str(nro)[:-2] if str(nro).endswith("_P") else str(nro)
        nombre = (cc or "").strip()
        if not nombre or nombre in grupos.get(base, []):
            continue
        grupos.setdefault(base, []).append(nombre)
    return {base: ", ".join(nombres) for base, nombres in grupos.items()}


def leer_tipos(conn: sqlite3.Connection, documentos: list[str]) -> dict[str, str]:
    if not _tiene_columna(conn):
        return {}
    padres = []
    for doc in documentos:
        nro = str(doc or "").strip()
        if nro and not nro.endswith("_P") and nro not in padres:
            padres.append(nro)
    if not padres:
        return {}
    marcas = ",".join("?" * len(padres))
    filas = conn.execute(
        f"""SELECT nro_documento, COALESCE({COLUMNA}, '')
            FROM facturas
            WHERE nro_documento IN ({marcas})
              AND nro_documento NOT LIKE '%_P'""",
        padres,
    ).fetchall()
    return {str(nro): _limpiar(str(tipo or "")) for nro, tipo in filas}


def presentar_cuenta(conn: sqlite3.Connection, df: pd.DataFrame, f_peso) -> tuple[list[dict], pd.DataFrame]:
    """Filas de pantalla y el marco que va al PDF, con CC y tipo escrito."""
    if df is None or df.empty:
        return [], pd.DataFrame()
    asegurar_tipo_trabajo(conn)
    docs = [str(r.get("DOCUMENTO") or "") for _, r in df.iterrows()]
    ccs = centros_imputados(conn, docs)
    tipos = leer_tipos(conn, docs)
    filas = []
    pdf = []
    for _, r in df.iterrows():
        doc = str(r.get("DOCUMENTO") or "")
        tipo = str(r.get("TIPO") or "")
        es_trabajo = tipo.strip().upper() == "TRABAJO"
        escrito = tipos.get(doc, "") if es_trabajo else ""
        cc = ccs.get(doc, "")
        debe = float(r.get("DEBE") or 0)
        haber = float(r.get("HABER") or 0)
        saldo = float(r.get("SALDO") or 0)
        fecha = str(r.get("FECHA", ""))[:10]
        detalle = r.get("DETALLE", "") or ""
        filas.append(
            {
                "fecha": fecha,
                "tipo": tipo,
                "es_trabajo": es_trabajo,
                "tipo_trabajo": escrito,
                "cc": cc,
                "documento": doc,
                "detalle": detalle,
                "debe": f_peso(debe) if debe else "",
                "haber": f_peso(haber) if haber else "",
                "saldo": f_peso(saldo),
            }
        )
        pdf.append(
            {
                "FECHA": fecha,
                "TIPO DE TRABAJO": escrito if es_trabajo else tipo,
                "CC": cc,
                "DOCUMENTO": doc,
                "DETALLE": detalle,
                "DEBE": debe,
                "HABER": haber,
                "SALDO": saldo,
            }
        )
    return filas, pd.DataFrame(pdf)
