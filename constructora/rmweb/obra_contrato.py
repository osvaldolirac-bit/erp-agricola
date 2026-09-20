"""Contrato de obra: partidas (cotización), APU foto, Gantt % y EEPP $."""
from __future__ import annotations

import re
from typing import Any

from rmweb import core

_RE_ITEM = re.compile(r"^(\d+)\.(\d+)$")

ESTADOS_COT_OBRA = ("borrador", "aprobada")
TIPOS_LINEA = ("capitulo", "partida")
MARCAS_SIN_PRECIO = ("en_gg", "mandante", "a_definir")
MARCA_LABELS = {
    "en_gg": "En gastos generales",
    "mandante": "Por parte del mandante",
    "a_definir": "A DEFINIR IN SITU",
    "proforma": "Valor proforma",
    "subcontrato": "Sub-contrato",
}


def _f(v, default: float = 0.0) -> float:
    try:
        return float(str(v if v is not None else default).replace(",", "."))
    except (TypeError, ValueError):
        return float(default)


def linea_requiere_apu(p: Any) -> bool:
    """Capítulos y marcas especiales no exigen APU/precio."""
    try:
        tipo = (p["tipo_linea"] if "tipo_linea" in p.keys() else "partida") or "partida"
    except Exception:
        tipo = (getattr(p, "tipo_linea", None) or "partida")
    if str(tipo).lower() == "capitulo":
        return False
    try:
        marca = (p["marca"] if "marca" in p.keys() else "") or ""
    except Exception:
        marca = getattr(p, "marca", "") or ""
    return str(marca).strip().lower() not in MARCAS_SIN_PRECIO


def marca_label(marca: str | None) -> str:
    m = (marca or "").strip().lower()
    return MARCA_LABELS.get(m, marca or "")


def ensure_obra_contrato_schema(c) -> None:
    core._ensure_columns(
        c,
        "centros_costo",
        [
            ("cotizacion_obra_estado", "TEXT DEFAULT 'borrador'"),
            ("cotizacion_obra_aprobada_en", "TEXT"),
            ("ubicacion", "TEXT"),
            ("propietario", "TEXT"),
            ("documento_cot", "TEXT"),
            ("duracion_meses", "REAL DEFAULT 0"),
            ("gg_pct", "REAL DEFAULT 0"),
            ("utilidades_pct", "REAL DEFAULT 0"),
            ("descuento_clp", "REAL DEFAULT 0"),
            ("iva_pct", "REAL DEFAULT 19"),
            ("valor_uf", "REAL DEFAULT 0"),
        ],
    )
    core._ensure_columns(
        c,
        "apu",
        [
            ("partida_id", "INTEGER"),
            ("congelado", "INTEGER DEFAULT 0"),
        ],
    )
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS obra_partidas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            centro_costo_id INTEGER NOT NULL,
            codigo TEXT,
            detalle TEXT NOT NULL,
            unidad TEXT DEFAULT 'un',
            cantidad REAL DEFAULT 0,
            apu_id INTEGER,
            pu_neto REAL DEFAULT 0,
            total REAL DEFAULT 0,
            avance_pct REAL DEFAULT 0,
            orden INTEGER DEFAULT 0,
            notas TEXT,
            activo INTEGER DEFAULT 1,
            creado_en TEXT
        );
        CREATE TABLE IF NOT EXISTS obra_eepp (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            centro_costo_id INTEGER NOT NULL,
            numero INTEGER NOT NULL,
            fecha TEXT,
            estado TEXT DEFAULT 'borrador',
            notas TEXT,
            monto_total REAL DEFAULT 0,
            creado_en TEXT
        );
        CREATE TABLE IF NOT EXISTS obra_eepp_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            eepp_id INTEGER NOT NULL,
            partida_id INTEGER NOT NULL,
            avance_pct REAL DEFAULT 0,
            monto REAL DEFAULT 0,
            FOREIGN KEY(eepp_id) REFERENCES obra_eepp(id) ON DELETE CASCADE
        );
        """
    )
    _ensure_partida_columns(c)


def _ensure_partida_columns(c) -> None:
    core._ensure_columns(
        c,
        "obra_partidas",
        [
            ("tipo_linea", "TEXT DEFAULT 'partida'"),
            ("marca", "TEXT"),
        ],
    )


def obra_cotizacion_aprobada(c, obra_id: int) -> bool:
    row = c.execute(
        "SELECT cotizacion_obra_estado FROM centros_costo WHERE id=?",
        (int(obra_id),),
    ).fetchone()
    if not row:
        return False
    return (row["cotizacion_obra_estado"] or "borrador") == "aprobada"


def list_partidas(c, obra_id: int) -> list[Any]:
    return c.execute(
        """
        SELECT p.*, a.codigo AS apu_codigo, a.congelado AS apu_congelado,
               a.pu_neto AS apu_pu,
               COALESCE(a.pu_neto, p.pu_neto, 0) AS pu_precio,
               CASE
                 WHEN COALESCE(p.tipo_linea,'partida')='capitulo' THEN 0
                 WHEN COALESCE(p.marca,'') IN ('en_gg','mandante','a_definir') THEN 0
                 ELSE ROUND(COALESCE(p.cantidad,0) * COALESCE(a.pu_neto, p.pu_neto, 0), 2)
               END AS total_calc
        FROM obra_partidas p
        LEFT JOIN apu a ON a.id = p.apu_id
        WHERE p.centro_costo_id=? AND COALESCE(p.activo,1)=1
        ORDER BY COALESCE(p.orden,0), p.id
        """,
        (int(obra_id),),
    ).fetchall()


def get_partida(c, partida_id: int, obra_id: int | None = None) -> Any | None:
    if obra_id is not None:
        return c.execute(
            "SELECT * FROM obra_partidas WHERE id=? AND centro_costo_id=?",
            (int(partida_id), int(obra_id)),
        ).fetchone()
    return c.execute(
        "SELECT * FROM obra_partidas WHERE id=?", (int(partida_id),)
    ).fetchone()


def _lineas_activas_ordenadas(c, obra_id: int):
    return c.execute(
        """
        SELECT id, codigo, tipo_linea, orden
        FROM obra_partidas
        WHERE centro_costo_id=? AND COALESCE(activo,1)=1
        ORDER BY COALESCE(orden,0), id
        """,
        (int(obra_id),),
    ).fetchall()


def next_partida_codigo(c, obra_id: int, tipo_linea: str = "partida") -> str:
    """Correlativo ítemizado: títulos 1.0, 2.0…; partidas 1.1, 1.2… / 2.1, 2.2…"""
    tipo = (tipo_linea or "partida").strip().lower()
    if tipo not in TIPOS_LINEA:
        tipo = "partida"
    cap_n = 0
    part_n = 0
    for r in _lineas_activas_ordenadas(c, obra_id):
        es_cap = ((r["tipo_linea"] or "partida").strip().lower() == "capitulo")
        cod = (r["codigo"] or "").strip()
        m = _RE_ITEM.match(cod)
        if m:
            major, minor = int(m.group(1)), int(m.group(2))
            if es_cap or minor == 0:
                if major >= cap_n:
                    cap_n = major
                    part_n = 0
            elif major == cap_n:
                part_n = max(part_n, minor)
            elif major > cap_n:
                cap_n = major
                part_n = minor
            continue
        m2 = re.match(r"^(\d+)$", cod)
        if m2 and es_cap:
            major = int(m2.group(1))
            if major >= cap_n:
                cap_n = major
                part_n = 0
    if tipo == "capitulo":
        return f"{cap_n + 1}.0"
    if cap_n <= 0:
        # Partida sin título previo: asume capítulo 1
        return "1.1"
    return f"{cap_n}.{part_n + 1}"


def renumerar_codigos_itemizados(c, obra_id: int) -> tuple[bool, str, int]:
    """Reasigna ITEM según orden: capítulos N.0 y partidas N.1, N.2…"""
    if obra_cotizacion_aprobada(c, obra_id):
        return False, "Presupuesto aprobado: no se renumeran ítems.", 0
    rows = _lineas_activas_ordenadas(c, obra_id)
    if not rows:
        return True, "Sin líneas para renumerar.", 0
    cap_n = 0
    part_n = 0
    n = 0
    for r in rows:
        es_cap = ((r["tipo_linea"] or "partida").strip().lower() == "capitulo")
        if es_cap:
            cap_n += 1
            part_n = 0
            cod = f"{cap_n}.0"
        else:
            if cap_n <= 0:
                cap_n = 1
            part_n += 1
            cod = f"{cap_n}.{part_n}"
        if (r["codigo"] or "").strip() != cod:
            c.execute(
                "UPDATE obra_partidas SET codigo=? WHERE id=? AND centro_costo_id=?",
                (cod, int(r["id"]), int(obra_id)),
            )
            n += 1
    return True, f"Ítems renumerados ({len(rows)} líneas).", n


def guardar_partida(
    c,
    *,
    obra_id: int,
    partida_id: int | None,
    codigo: str,
    detalle: str,
    unidad: str = "gl",
    cantidad: float = 1.0,
    notas: str = "",
    orden: int | None = None,
    tipo_linea: str = "partida",
    marca: str = "",
) -> tuple[bool, str, int | None]:
    if obra_cotizacion_aprobada(c, obra_id):
        return False, "Cotización de obra aprobada: partidas congeladas.", None
    det = (detalle or "").strip()
    if not det:
        return False, "Indique el detalle / nombre de la partida.", None
    tipo = (tipo_linea or "partida").strip().lower()
    if tipo not in TIPOS_LINEA:
        tipo = "partida"
    marca_v = (marca or "").strip().lower() or None
    if marca_v and marca_v not in MARCA_LABELS:
        marca_v = marca_v  # allow free text stored lower
    und = (unidad or "gl").strip() or "gl"
    cant = max(0.0, _f(cantidad))
    if tipo == "capitulo":
        und = und if und else ""
        cant = 0.0
        marca_v = None
    cod_in = (codigo or "").strip()
    # Autocorrelativo: vacío o formato viejo P-obra-nn → sugerido
    if (not cod_in) or re.match(r"^P-\d+-\d+$", cod_in, re.I):
        cod = next_partida_codigo(c, obra_id, tipo)
    else:
        cod = cod_in
    hoy = core.hoy_chile().isoformat()
    if partida_id:
        row = get_partida(c, partida_id, obra_id)
        if not row:
            return False, "Partida no encontrada.", None
        pu = _f(row["pu_neto"])
        if tipo == "capitulo" or (marca_v in MARCAS_SIN_PRECIO):
            pu, total = 0.0, 0.0
        else:
            total = round(cant * pu, 2)
        c.execute(
            """
            UPDATE obra_partidas
            SET codigo=?, detalle=?, unidad=?, cantidad=?, total=?, notas=?,
                orden=COALESCE(?, orden), tipo_linea=?, marca=?
            WHERE id=? AND centro_costo_id=?
            """,
            (
                cod, det, und, cant, total, (notas or "").strip() or None,
                orden, tipo, marca_v, int(partida_id), int(obra_id),
            ),
        )
        renumerar_codigos_itemizados(c, obra_id)
        return True, "Línea actualizada.", int(partida_id)
    if orden is None:
        orden = int(
            c.execute(
                "SELECT COALESCE(MAX(orden),0)+1 n FROM obra_partidas WHERE centro_costo_id=?",
                (int(obra_id),),
            ).fetchone()["n"]
        )
    cur = c.execute(
        """
        INSERT INTO obra_partidas
        (centro_costo_id, codigo, detalle, unidad, cantidad, pu_neto, total,
         avance_pct, orden, notas, activo, creado_en, tipo_linea, marca)
        VALUES (?,?,?,?,?,0,0,0,?,?,1,?,?,?)
        """,
        (
            int(obra_id), cod, det, und, cant, int(orden),
            (notas or "").strip() or None, hoy, tipo, marca_v,
        ),
    )
    new_id = int(cur.lastrowid)
    renumerar_codigos_itemizados(c, obra_id)
    return True, ("Capítulo creado." if tipo == "capitulo" else "Partida creada."), new_id


def eliminar_partida(c, obra_id: int, partida_id: int) -> tuple[bool, str]:
    if obra_cotizacion_aprobada(c, obra_id):
        return False, "Cotización de obra aprobada: no se pueden eliminar partidas."
    row = get_partida(c, partida_id, obra_id)
    if not row:
        return False, "Partida no encontrada."
    if row["apu_id"]:
        c.execute(
            "UPDATE apu SET partida_id=NULL WHERE id=? AND centro_costo_id=?",
            (int(row["apu_id"]), int(obra_id)),
        )
    c.execute(
        "UPDATE obra_partidas SET activo=0 WHERE id=? AND centro_costo_id=?",
        (int(partida_id), int(obra_id)),
    )
    renumerar_codigos_itemizados(c, obra_id)
    return True, "Partida eliminada."


def vincular_apu_a_partida(c, obra_id: int, partida_id: int, apu_id: int) -> tuple[bool, str]:
    if obra_cotizacion_aprobada(c, obra_id):
        return False, "Cotización aprobada: APU congelado."
    part = get_partida(c, partida_id, obra_id)
    apu = c.execute(
        "SELECT * FROM apu WHERE id=? AND centro_costo_id=?",
        (int(apu_id), int(obra_id)),
    ).fetchone()
    if not part or not apu:
        return False, "Partida o APU no encontrado."
    pu = _f(apu["pu_neto"])
    cant = _f(part["cantidad"])
    total = round(cant * pu, 2)
    c.execute(
        """
        UPDATE obra_partidas SET apu_id=?, pu_neto=?, total=?
        WHERE id=? AND centro_costo_id=?
        """,
        (int(apu_id), pu, total, int(partida_id), int(obra_id)),
    )
    c.execute(
        "UPDATE apu SET partida_id=? WHERE id=? AND centro_costo_id=?",
        (int(partida_id), int(apu_id), int(obra_id)),
    )
    return True, "APU vinculado a la partida."


def sync_partida_desde_apu(c, apu_id: int) -> None:
    """Tras guardar APU (si no congelado), refresca PU/total de la partida."""
    apu = c.execute("SELECT * FROM apu WHERE id=?", (int(apu_id),)).fetchone()
    if not apu or int(apu["congelado"] or 0):
        return
    pid = apu["partida_id"]
    if not pid:
        # buscar partida que apunta a este apu
        part = c.execute(
            "SELECT * FROM obra_partidas WHERE apu_id=? AND COALESCE(activo,1)=1",
            (int(apu_id),),
        ).fetchone()
    else:
        part = c.execute(
            "SELECT * FROM obra_partidas WHERE id=?", (int(pid),)
        ).fetchone()
    if not part:
        return
    pu = _f(apu["pu_neto"])
    total = round(_f(part["cantidad"]) * pu, 2)
    c.execute(
        "UPDATE obra_partidas SET pu_neto=?, total=?, apu_id=? WHERE id=?",
        (pu, total, int(apu_id), int(part["id"])),
    )


def totales_cotizacion_obra(c, obra_id: int) -> dict[str, Any]:
    """Subtotal de partidas valorizadas + GG / utilidades / IVA (estilo presupuesto)."""
    ensure_obra_contrato_schema(c)
    parts = list_partidas(c, obra_id)
    n_part = 0
    subtotal = 0.0
    for p in parts:
        if not linea_requiere_apu(p) and (p["tipo_linea"] or "partida") == "capitulo":
            continue
        if not linea_requiere_apu(p):
            continue
        n_part += 1
        # Preferir PU del APU linkeado
        pu = _f(p["apu_pu"] if p["apu_pu"] is not None else p["pu_neto"])
        cant = _f(p["cantidad"])
        subtotal += round(cant * pu, 2) if pu > 0 else _f(p["total"])
    obra = c.execute(
        "SELECT * FROM centros_costo WHERE id=?", (int(obra_id),)
    ).fetchone()
    gg_pct = _f(obra["gg_pct"] if obra and "gg_pct" in obra.keys() else 0)
    util_pct = _f(obra["utilidades_pct"] if obra and "utilidades_pct" in obra.keys() else 0)
    desc = _f(obra["descuento_clp"] if obra and "descuento_clp" in obra.keys() else 0)
    iva_pct = _f(obra["iva_pct"] if obra and "iva_pct" in obra.keys() else 19)
    valor_uf = _f(obra["valor_uf"] if obra and "valor_uf" in obra.keys() else 0)
    gg = round(subtotal * gg_pct / 100.0, 0)
    util = round(subtotal * util_pct / 100.0, 0)
    neto = round(subtotal + gg + util, 0)
    total_neto = round(neto - desc, 0)
    iva = round(total_neto * iva_pct / 100.0, 0)
    total = round(total_neto + iva, 0)
    monto_uf = round(total_neto / valor_uf, 2) if valor_uf > 0 else 0.0
    return {
        "n_partidas": n_part,
        "n_lineas": len(parts),
        "subtotal": subtotal,
        "gg_pct": gg_pct,
        "gg": gg,
        "utilidades_pct": util_pct,
        "utilidades": util,
        "neto": neto,
        "descuento_clp": desc,
        "total_neto": total_neto,
        "iva_pct": iva_pct,
        "iva": iva,
        "total": total,
        "valor_uf": valor_uf,
        "monto_uf": monto_uf,
        # compat
        "total_directo": subtotal,
    }


def guardar_parametros_presupuesto(
    c,
    obra_id: int,
    *,
    ubicacion: str = "",
    propietario: str = "",
    documento_cot: str = "",
    duracion_meses: float = 0,
    gg_pct: float = 0,
    utilidades_pct: float = 0,
    descuento_clp: float = 0,
    iva_pct: float = 19,
    valor_uf: float = 0,
) -> tuple[bool, str]:
    ensure_obra_contrato_schema(c)
    row = c.execute(
        "SELECT id FROM centros_costo WHERE id=? AND COALESCE(tipo,'general')='obra'",
        (int(obra_id),),
    ).fetchone()
    if not row:
        return False, "Obra no encontrada."
    if obra_cotizacion_aprobada(c, obra_id):
        # permitir editar cabecera informativa, no % si aprobada? permitir todo cabecera
        pass
    c.execute(
        """
        UPDATE centros_costo SET
          ubicacion=?, propietario=?, documento_cot=?, duracion_meses=?,
          gg_pct=?, utilidades_pct=?, descuento_clp=?, iva_pct=?, valor_uf=?
        WHERE id=?
        """,
        (
            (ubicacion or "").strip() or None,
            (propietario or "").strip() or None,
            (documento_cot or "").strip() or None,
            max(0.0, _f(duracion_meses)),
            max(0.0, _f(gg_pct)),
            max(0.0, _f(utilidades_pct)),
            max(0.0, _f(descuento_clp)),
            max(0.0, _f(iva_pct)),
            max(0.0, _f(valor_uf)),
            int(obra_id),
        ),
    )
    return True, "Parámetros del presupuesto actualizados."


def aprobar_cotizacion_obra(c, obra_id: int) -> tuple[bool, str]:
    """Congela foto de precios APU→partidas y habilita Gantt/EEPP."""
    if obra_cotizacion_aprobada(c, obra_id):
        return False, "La cotización de obra ya está aprobada."
    parts = list_partidas(c, obra_id)
    valorizables = [p for p in parts if linea_requiere_apu(p)]
    if not valorizables:
        return False, "Agregue al menos una partida valorizable (con APU) antes de aprobar."
    sin_apu = [p for p in valorizables if not p["apu_id"] or _f(p["apu_pu"] or p["pu_neto"]) <= 0]
    if sin_apu:
        return (
            False,
            f"Hay {len(sin_apu)} partida(s) sin APU valorizado. El precio unitario debe venir del APU.",
        )
    hoy = core.hoy_chile().isoformat()
    for p in parts:
        if not linea_requiere_apu(p):
            c.execute(
                "UPDATE obra_partidas SET pu_neto=0, total=0 WHERE id=?",
                (int(p["id"]),),
            )
            continue
        apu = c.execute("SELECT * FROM apu WHERE id=?", (int(p["apu_id"]),)).fetchone()
        pu = _f(apu["pu_neto"]) if apu else _f(p["pu_neto"])
        cant = _f(p["cantidad"])
        tot = round(cant * pu, 2)
        c.execute(
            """
            UPDATE obra_partidas SET pu_neto=?, total=?, avance_pct=COALESCE(avance_pct,0)
            WHERE id=?
            """,
            (pu, tot, int(p["id"])),
        )
        if apu:
            c.execute(
                "UPDATE apu SET congelado=1, partida_id=?, pu_neto=? WHERE id=?",
                (int(p["id"]), pu, int(apu["id"])),
            )
    tot_p = totales_cotizacion_obra(c, obra_id)
    total = _f(tot_p["total_neto"] or tot_p["subtotal"])
    c.execute(
        """
        UPDATE centros_costo
        SET cotizacion_obra_estado='aprobada',
            cotizacion_obra_aprobada_en=?,
            presupuesto=?,
            tipo='obra'
        WHERE id=?
        """,
        (hoy, total, int(obra_id)),
    )
    c.execute(
        "UPDATE apu SET congelado=1 WHERE centro_costo_id=?",
        (int(obra_id),),
    )
    tot_txt = f"{total:,.0f}".replace(",", ".")
    return True, f"Presupuesto de obra aprobado. Foto congelada · neto ${tot_txt}."



def reabrir_cotizacion_obra(c, obra_id: int) -> tuple[bool, str]:
    """Vuelve el presupuesto a borrador para editar líneas y APU."""
    ensure_obra_contrato_schema(c)
    row = c.execute(
        """
        SELECT id, cotizacion_obra_estado FROM centros_costo
        WHERE id=? AND COALESCE(tipo,'general')='obra'
        """,
        (int(obra_id),),
    ).fetchone()
    if not row:
        return False, "Obra no encontrada."
    if (row["cotizacion_obra_estado"] or "borrador") != "aprobada":
        return False, "El presupuesto ya está en borrador."
    c.execute(
        """
        UPDATE centros_costo
        SET cotizacion_obra_estado='borrador',
            cotizacion_obra_aprobada_en=NULL
        WHERE id=?
        """,
        (int(obra_id),),
    )
    c.execute(
        "UPDATE apu SET congelado=0 WHERE centro_costo_id=?",
        (int(obra_id),),
    )
    return True, "Presupuesto reabierto en borrador. Ya puede agregar o editar líneas y APU."


def guardar_avances_gantt(
    c, obra_id: int, avances: list[dict[str, Any]]
) -> tuple[bool, str]:
    if not obra_cotizacion_aprobada(c, obra_id):
        return False, "Apruebe la cotización de obra para registrar avance (Gantt)."
    n = 0
    for a in avances:
        try:
            pid = int(a.get("partida_id") or 0)
        except (TypeError, ValueError):
            continue
        if pid <= 0:
            continue
        pct = max(0.0, min(100.0, _f(a.get("avance_pct"))))
        cur = c.execute(
            """
            UPDATE obra_partidas SET avance_pct=?
            WHERE id=? AND centro_costo_id=? AND COALESCE(activo,1)=1
              AND COALESCE(tipo_linea,'partida')='partida'
            """,
            (pct, pid, int(obra_id)),
        )
        n += cur.rowcount
    return True, f"Gantt actualizado ({n} partida(s))."


def monto_eepp_partida(partida: Any) -> float:
    """Monto EEPP acumulado teórico = % avance × total foto."""
    return round(_f(partida["total"]) * (_f(partida["avance_pct"]) / 100.0), 2)


def list_eepp(c, obra_id: int) -> list[Any]:
    return c.execute(
        """
        SELECT * FROM obra_eepp
        WHERE centro_costo_id=?
        ORDER BY numero DESC, id DESC
        """,
        (int(obra_id),),
    ).fetchall()


def generar_eepp_desde_gantt(c, obra_id: int, notas: str = "") -> tuple[bool, str, int | None]:
    """Crea un EEPP con el avance actual (foto CLP por partida según Gantt)."""
    if not obra_cotizacion_aprobada(c, obra_id):
        return False, "Apruebe la cotización de obra antes de emitir EEPP.", None
    parts = list_partidas(c, obra_id)
    if not parts:
        return False, "Sin partidas.", None
    items = []
    monto_total = 0.0
    for p in parts:
        pct = _f(p["avance_pct"])
        if pct <= 0:
            continue
        monto = monto_eepp_partida(p)
        if monto <= 0:
            continue
        items.append({"partida_id": int(p["id"]), "avance_pct": pct, "monto": monto})
        monto_total += monto
    if not items:
        return False, "No hay avance en Gantt para generar EEPP.", None
    num = int(
        c.execute(
            "SELECT COALESCE(MAX(numero),0)+1 n FROM obra_eepp WHERE centro_costo_id=?",
            (int(obra_id),),
        ).fetchone()["n"]
    )
    hoy = core.hoy_chile().isoformat()
    cur = c.execute(
        """
        INSERT INTO obra_eepp
        (centro_costo_id, numero, fecha, estado, notas, monto_total, creado_en)
        VALUES (?,?,?,'emitido',?,?,?)
        """,
        (
            int(obra_id),
            num,
            hoy,
            (notas or "").strip() or None,
            monto_total,
            hoy,
        ),
    )
    eid = int(cur.lastrowid)
    for it in items:
        c.execute(
            """
            INSERT INTO obra_eepp_items (eepp_id, partida_id, avance_pct, monto)
            VALUES (?,?,?,?)
            """,
            (eid, it["partida_id"], it["avance_pct"], it["monto"]),
        )
    tot_txt = f"{monto_total:,.0f}".replace(",", ".")
    return True, f"EEPP N° {num} emitido por ${tot_txt}.", eid


def eepp_detalle(c, eepp_id: int, obra_id: int) -> dict[str, Any] | None:
    head = c.execute(
        "SELECT * FROM obra_eepp WHERE id=? AND centro_costo_id=?",
        (int(eepp_id), int(obra_id)),
    ).fetchone()
    if not head:
        return None
    items = c.execute(
        """
        SELECT i.*, p.codigo, p.detalle, p.unidad, p.cantidad, p.total AS partida_total
        FROM obra_eepp_items i
        JOIN obra_partidas p ON p.id = i.partida_id
        WHERE i.eepp_id=?
        ORDER BY p.orden, p.id
        """,
        (int(eepp_id),),
    ).fetchall()
    return {"eepp": head, "items": items}


def resumen_avance_obra(c, obra_id: int) -> dict[str, Any]:
    parts_all = list_partidas(c, obra_id)
    parts = [p for p in parts_all if linea_requiere_apu(p) and _f(p["total"]) > 0]
    if not parts:
        parts = [p for p in parts_all if linea_requiere_apu(p)]
    ppto = sum(_f(p["total"]) for p in parts)
    avanzado = sum(monto_eepp_partida(p) for p in parts)
    if parts:
        pct_pond = (
            sum(_f(p["total"]) * _f(p["avance_pct"]) for p in parts) / ppto
            if ppto > 0
            else 0.0
        )
    else:
        pct_pond = 0.0
    tot = totales_cotizacion_obra(c, obra_id)
    return {
        "n_partidas": len(parts),
        "ppto": ppto,
        "ppto_neto": tot.get("total_neto", ppto),
        "avanzado_clp": avanzado,
        "avance_pct_pond": round(pct_pond, 1),
        "aprobada": obra_cotizacion_aprobada(c, obra_id),
        "presupuesto": tot,
    }
