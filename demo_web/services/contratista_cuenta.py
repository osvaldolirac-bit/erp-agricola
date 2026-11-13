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


def _filtro_tipo_gasto() -> str:
    try:
        from erp_contratistas import sql_filtro_tipo_gasto_contratista

        return sql_filtro_tipo_gasto_contratista("tipo_gasto")
    except Exception:
        return "UPPER(TRIM(COALESCE(tipo_gasto, ''))) = 'CONTRATISTAS'"


def documentos_con_saldo(conn: sqlite3.Connection, contratista_id: int, razon: str = "") -> list[dict]:
    """Cabeceras pendientes del contratista, de la más antigua a la más nueva."""
    filtro = _filtro_tipo_gasto()
    filas = conn.execute(
        f"""SELECT id, nro_documento, fecha_compra, monto_total, COALESCE(monto_pagado, 0)
            FROM facturas
            WHERE monto_total > 0
              AND nro_documento NOT LIKE '%_P'
              AND COALESCE(estado, 'Pendiente') = 'Pendiente'
              AND {filtro}
              AND (
                    COALESCE(contratista_id, 0)=?
                    OR (
                        COALESCE(contratista_id, 0)=0
                        AND UPPER(TRIM(proveedor))=UPPER(TRIM(?))
                    )
                  )
            ORDER BY fecha_compra ASC, id ASC""",
        (int(contratista_id), (razon or "").strip()),
    ).fetchall()
    pendientes = []
    for fid, nro, fecha, total, pagado in filas:
        saldo = round(float(total or 0) - float(pagado or 0), 2)
        if saldo <= 0.01:
            continue
        pendientes.append(
            {
                "id": int(fid),
                "nro": str(nro),
                "fecha": str(fecha or "")[:10],
                "saldo": saldo,
            }
        )
    return pendientes


def repartir_abono(documentos: list[dict], monto: float) -> tuple[list[dict], str]:
    """Aplica el abono al documento más antiguo y el resto al siguiente."""
    try:
        pesos = round(float(monto), 2)
    except (TypeError, ValueError):
        return [], "Monto de abono inválido."
    if pesos <= 0:
        return [], "El abono tiene que ser mayor a cero."
    if not documentos:
        return [], "Este contratista no tiene documentos con saldo."
    deuda = round(sum(doc["saldo"] for doc in documentos), 2)
    if pesos > deuda + 0.01:
        return [], "El abono supera la deuda pendiente."
    partes = []
    resta = pesos
    for doc in documentos:
        if resta <= 0.01:
            break
        aplicar = round(min(doc["saldo"], resta), 2)
        partes.append(
            {
                **doc,
                "aplicar": aplicar,
                "saldo_despues": round(doc["saldo"] - aplicar, 2),
            }
        )
        resta = round(resta - aplicar, 2)
    return partes, ""


def asegurar_lote_abono(conn: sqlite3.Connection) -> bool:
    """Marca los trozos de un mismo abono para mostrarlos como un solo monto."""
    try:
        from erp_solo_lectura import conn_en_solo_lectura

        if conn_en_solo_lectura(conn):
            return _tiene_lote(conn)
    except Exception:
        pass
    if _tiene_lote(conn):
        return True
    tablas = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "facturas_abonos" not in tablas:
        return False
    conn.execute("ALTER TABLE facturas_abonos ADD COLUMN abono_lote TEXT DEFAULT ''")
    return True


def _tiene_lote(conn: sqlite3.Connection) -> bool:
    return "abono_lote" in _columnas(conn, "facturas_abonos")


def marcar_abono_lote(conn: sqlite3.Connection, factura_id: int, fecha, monto: float, lote: str) -> None:
    if not lote or not asegurar_lote_abono(conn):
        return
    fecha_txt = str(fecha)[:10]
    fila = conn.execute(
        """SELECT id FROM facturas_abonos
           WHERE factura_id=? AND ABS(COALESCE(monto, 0) - ?) < 0.01
             AND substr(COALESCE(fecha, ''), 1, 10)=?
             AND COALESCE(abono_lote, '')=''
           ORDER BY id DESC LIMIT 1""",
        (int(factura_id), float(monto), fecha_txt),
    ).fetchone()
    if fila:
        conn.execute("UPDATE facturas_abonos SET abono_lote=? WHERE id=?", (lote, int(fila[0])))


def _columnas(conn: sqlite3.Connection, tabla: str) -> set[str]:
    tablas = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if tabla not in tablas:
        return set()
    return {r[1] for r in conn.execute(f"PRAGMA table_info({tabla})")}


def unificar_abonos_libro(conn: sqlite3.Connection, df: pd.DataFrame) -> pd.DataFrame:
    """Un abono repartido en varios documentos se ve como un solo monto en la cuenta."""
    if df is None or df.empty or "TIPO" not in getattr(df, "columns", []):
        return df
    cols = _columnas(conn, "facturas_abonos")
    if not cols:
        return df
    documentos = []
    for doc in df["DOCUMENTO"].tolist():
        nro = str(doc or "").strip()
        if nro and nro not in documentos:
            documentos.append(nro)
    if not documentos:
        return df
    lote_sql = "COALESCE(fa.abono_lote, '')" if "abono_lote" in cols else "''"
    reg_sql = "COALESCE(fa.fecha_registro, '')" if "fecha_registro" in cols else "''"
    marcas = ",".join("?" * len(documentos))
    trozos = conn.execute(
        f"""SELECT fa.id, {lote_sql}, fa.fecha, fa.monto, COALESCE(fa.metodo_pago, ''),
                  f.nro_documento, {reg_sql}, COALESCE(f.proveedor, '')
            FROM facturas_abonos fa
            JOIN facturas f ON f.id = fa.factura_id
            WHERE f.nro_documento IN ({marcas})
            ORDER BY fa.id""",
        documentos,
    ).fetchall()
    if not trozos:
        return df
    por_registro: dict[tuple, list] = {}
    for trozo in trozos:
        if str(trozo[1] or "").strip() or not str(trozo[6] or "").strip():
            continue
        por_registro.setdefault((str(trozo[7]), str(trozo[6]), str(trozo[4])), []).append(trozo)
    lote_de: dict[int, str] = {}
    for clave, grupo in por_registro.items():
        if len({str(t[5]) for t in grupo}) < 2:
            continue
        sintetico = "mismo-abono:" + "|".join(clave)
        for trozo in grupo:
            lote_de[int(trozo[0])] = sintetico
    por_lote: dict[str, list] = {}
    for trozo in trozos:
        lote = str(trozo[1] or "").strip() or lote_de.get(int(trozo[0]), "")
        if not lote:
            continue
        por_lote.setdefault(lote, []).append(trozo)
    if not por_lote:
        return df

    def _clave(nro: str, fecha, monto: float) -> tuple:
        return (str(nro), str(fecha)[:10], round(float(monto or 0), 2))

    pendientes: dict[tuple, list[str]] = {}
    for lote, grupo in por_lote.items():
        for trozo in grupo:
            pendientes.setdefault(_clave(trozo[5], trozo[2], trozo[3]), []).append(lote)

    vistos: dict[str, dict] = {}
    ordenados = []
    junto = False
    for _, fila in df.iterrows():
        tipo = str(fila.get("TIPO") or "").strip().upper()
        if tipo != "PAGO":
            ordenados.append(fila.to_dict())
            continue
        clave = _clave(fila.get("DOCUMENTO"), fila.get("FECHA"), fila.get("HABER"))
        cola = pendientes.get(clave) or []
        if not cola:
            ordenados.append(fila.to_dict())
            continue
        lote = cola.pop(0)
        haber = round(float(fila.get("HABER") or 0), 2)
        if lote in vistos:
            junto = True
            grupo = por_lote[lote]
            metodo = next((str(t[4]).strip() for t in grupo if str(t[4]).strip()), "")
            vistos[lote]["HABER"] = round(float(vistos[lote]["HABER"]) + haber, 2)
            vistos[lote]["DOCUMENTO"] = ""
            vistos[lote]["DETALLE"] = f"Abono ({metodo})" if metodo else "Abono"
            continue
        copia = fila.to_dict()
        copia["HABER"] = haber
        vistos[lote] = copia
        ordenados.append(copia)

    if not junto:
        return df
    primera = df.iloc[0]
    saldo = float(primera.get("SALDO") or 0) - float(primera.get("DEBE") or 0) + float(primera.get("HABER") or 0)
    for fila in ordenados:
        saldo = round(saldo + float(fila.get("DEBE") or 0) - float(fila.get("HABER") or 0), 2)
        fila["SALDO"] = saldo
    return pd.DataFrame(ordenados)
