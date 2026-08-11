"""Contrato de obra: partidas (cotización), APU foto, Gantt % y EEPP $."""
from __future__ import annotations

from typing import Any

from rmweb import core

ESTADOS_COT_OBRA = ("borrador", "aprobada")


def _f(v, default: float = 0.0) -> float:
    try:
        return float(str(v if v is not None else default).replace(",", "."))
    except (TypeError, ValueError):
        return float(default)


def ensure_obra_contrato_schema(c) -> None:
    core._ensure_columns(
        c,
        "centros_costo",
        [
            ("cotizacion_obra_estado", "TEXT DEFAULT 'borrador'"),
            ("cotizacion_obra_aprobada_en", "TEXT"),
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
               a.pu_neto AS apu_pu
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


def next_partida_codigo(c, obra_id: int) -> str:
    n = c.execute(
        "SELECT COUNT(*) n FROM obra_partidas WHERE centro_costo_id=?",
        (int(obra_id),),
    ).fetchone()["n"]
    return f"P-{int(obra_id)}-{int(n) + 1:02d}"


def guardar_partida(
    c,
    *,
    obra_id: int,
    partida_id: int | None,
    codigo: str,
    detalle: str,
    unidad: str,
    cantidad: float,
    notas: str = "",
    orden: int | None = None,
) -> tuple[bool, str, int | None]:
    if obra_cotizacion_aprobada(c, obra_id):
        return False, "Cotización de obra aprobada: partidas congeladas.", None
    det = (detalle or "").strip()
    if not det:
        return False, "Indique el detalle de la partida.", None
    und = (unidad or "un").strip() or "un"
    cant = max(0.0, _f(cantidad))
    cod = (codigo or "").strip().upper() or next_partida_codigo(c, obra_id)
    hoy = core.hoy_chile().isoformat()
    if partida_id:
        row = get_partida(c, partida_id, obra_id)
        if not row:
            return False, "Partida no encontrada.", None
        pu = _f(row["pu_neto"])
        total = round(cant * pu, 2)
        c.execute(
            """
            UPDATE obra_partidas
            SET codigo=?, detalle=?, unidad=?, cantidad=?, total=?, notas=?,
                orden=COALESCE(?, orden)
            WHERE id=? AND centro_costo_id=?
            """,
            (
                cod,
                det,
                und,
                cant,
                total,
                (notas or "").strip() or None,
                orden,
                int(partida_id),
                int(obra_id),
            ),
        )
        return True, "Partida actualizada.", int(partida_id)
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
         avance_pct, orden, notas, activo, creado_en)
        VALUES (?,?,?,?,?,0,0,0,?,?,1,?)
        """,
        (
            int(obra_id),
            cod,
            det,
            und,
            cant,
            int(orden),
            (notas or "").strip() or None,
            hoy,
        ),
    )
    return True, "Partida creada.", int(cur.lastrowid)


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


def totales_cotizacion_obra(c, obra_id: int) -> dict[str, float]:
    row = c.execute(
        """
        SELECT COALESCE(SUM(total),0) AS total,
               COALESCE(SUM(cantidad * pu_neto),0) AS calc,
               COUNT(*) AS n
        FROM obra_partidas
        WHERE centro_costo_id=? AND COALESCE(activo,1)=1
        """,
        (int(obra_id),),
    ).fetchone()
    return {
        "n_partidas": int(row["n"] or 0),
        "total": _f(row["total"]),
    }


def aprobar_cotizacion_obra(c, obra_id: int) -> tuple[bool, str]:
    """Congela foto de precios APU→partidas y habilita Gantt/EEPP."""
    if obra_cotizacion_aprobada(c, obra_id):
        return False, "La cotización de obra ya está aprobada."
    parts = list_partidas(c, obra_id)
    if not parts:
        return False, "Agregue al menos una partida antes de aprobar."
    sin_apu = [p for p in parts if not p["apu_id"] or _f(p["pu_neto"]) <= 0]
    if sin_apu:
        return (
            False,
            f"Hay {len(sin_apu)} partida(s) sin APU valorizado. Complete el APU antes de aprobar.",
        )
    hoy = core.hoy_chile().isoformat()
    total = 0.0
    for p in parts:
        apu = c.execute("SELECT * FROM apu WHERE id=?", (int(p["apu_id"]),)).fetchone()
        pu = _f(apu["pu_neto"]) if apu else _f(p["pu_neto"])
        cant = _f(p["cantidad"])
        tot = round(cant * pu, 2)
        total += tot
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
    # congelar todos los APU de la obra
    c.execute(
        "UPDATE apu SET congelado=1 WHERE centro_costo_id=?",
        (int(obra_id),),
    )
    tot_txt = f"{total:,.0f}".replace(",", ".")
    return True, f"Cotización de obra aprobada. Foto congelada · ppto ${tot_txt}."


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
    parts = list_partidas(c, obra_id)
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
    return {
        "n_partidas": len(parts),
        "ppto": ppto,
        "avanzado_clp": avanzado,
        "avance_pct_pond": round(pct_pond, 1),
        "aprobada": obra_cotizacion_aprobada(c, obra_id),
    }
