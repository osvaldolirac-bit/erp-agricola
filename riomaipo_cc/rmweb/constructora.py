"""Módulo Constructora: obras (CC), maestra APU y cotización por partidas."""
from __future__ import annotations

from typing import Any

from rmweb import core
from rmweb import ops_cc

APU_ITEM_TIPOS = ("insumo", "mano_obra", "otro")
CC_TIPO_OBRA = "obra"
CC_TIPO_GENERAL = "general"


def ensure_constructora_schema(c) -> None:
    ops_cc.ensure_cc_schema(c)
    core._ensure_columns(
        c,
        "centros_costo",
        [
            ("tipo", "TEXT DEFAULT 'general'"),
            ("cliente_id", "INTEGER"),
            ("estado_obra", "TEXT DEFAULT 'activa'"),
            ("fecha_inicio", "TEXT"),
            ("fecha_fin", "TEXT"),
            ("cotizacion_id", "INTEGER"),
        ],
    )
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS apu (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT NOT NULL UNIQUE,
            nombre TEXT NOT NULL,
            unidad TEXT DEFAULT 'un',
            activo INTEGER DEFAULT 1,
            leyes_pct REAL DEFAULT 0,
            perdidas_pct REAL DEFAULT 0,
            pu_neto REAL DEFAULT 0,
            notas TEXT,
            creado_en TEXT
        );
        CREATE TABLE IF NOT EXISTS apu_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            apu_id INTEGER NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'insumo',
            descripcion TEXT NOT NULL,
            unidad TEXT DEFAULT 'un',
            cantidad REAL DEFAULT 0,
            precio_unitario REAL DEFAULT 0,
            total REAL DEFAULT 0,
            orden INTEGER DEFAULT 0,
            FOREIGN KEY(apu_id) REFERENCES apu(id) ON DELETE CASCADE
        );
        """
    )
    core._ensure_columns(
        c,
        "cotizaciones",
        [
            ("tipo_cotizacion", "TEXT DEFAULT 'normal'"),
            ("centro_costo_id", "INTEGER"),
        ],
    )
    core._ensure_columns(
        c,
        "cotizacion_items",
        [("apu_id", "INTEGER")],
    )
    core._ensure_columns(
        c,
        "inventario_movimientos",
        [("centro_costo_id", "INTEGER")],
    )


def _f(v, default: float = 0.0) -> float:
    try:
        return float(str(v if v is not None else default).replace(",", "."))
    except (TypeError, ValueError):
        return float(default)


def next_apu_codigo(c) -> str:
    rows = c.execute("SELECT codigo FROM apu").fetchall()
    max_n = 0
    for r in rows:
        cod = str(r["codigo"] or "")
        if cod.upper().startswith("APU-"):
            try:
                max_n = max(max_n, int(cod.split("-", 1)[1]))
            except (IndexError, ValueError):
                pass
    return f"APU-{max_n + 1:02d}"


def calc_apu_desde_items(
    items: list[dict[str, Any]],
    *,
    leyes_pct: float = 0.0,
    perdidas_pct: float = 0.0,
) -> dict[str, float]:
    """Valoriza APU: insumos + MO + leyes sociales (% MO) + pérdidas (% insumos)."""
    insumos = 0.0
    mo = 0.0
    otro = 0.0
    for it in items:
        total = _f(it.get("total"))
        if total <= 0:
            total = _f(it.get("cantidad")) * _f(it.get("precio_unitario"))
        tipo = (it.get("tipo") or "insumo").strip().lower()
        if tipo == "mano_obra":
            mo += total
        elif tipo == "otro":
            otro += total
        else:
            insumos += total
    leyes = mo * (_f(leyes_pct) / 100.0)
    perdidas = insumos * (_f(perdidas_pct) / 100.0)
    pu = insumos + mo + otro + leyes + perdidas
    return {
        "insumos": round(insumos, 2),
        "mano_obra": round(mo, 2),
        "otro": round(otro, 2),
        "leyes": round(leyes, 2),
        "perdidas": round(perdidas, 2),
        "pu_neto": round(pu, 2),
    }


def list_apu(c, *, solo_activos: bool = False) -> list[Any]:
    sql = "SELECT * FROM apu"
    if solo_activos:
        sql += " WHERE COALESCE(activo,1)=1"
    sql += " ORDER BY codigo"
    return c.execute(sql).fetchall()


def get_apu(c, apu_id: int) -> Any | None:
    return c.execute("SELECT * FROM apu WHERE id=?", (int(apu_id),)).fetchone()


def list_apu_items(c, apu_id: int) -> list[Any]:
    return c.execute(
        """
        SELECT * FROM apu_items WHERE apu_id=?
        ORDER BY COALESCE(orden,0), id
        """,
        (int(apu_id),),
    ).fetchall()


def guardar_apu(
    c,
    *,
    apu_id: int | None,
    codigo: str,
    nombre: str,
    unidad: str,
    leyes_pct: float,
    perdidas_pct: float,
    notas: str,
    activo: int,
    items: list[dict[str, Any]],
) -> tuple[bool, str, int | None]:
    nom = (nombre or "").strip()
    if not nom:
        return False, "Indique el nombre del APU.", None
    und = (unidad or "un").strip() or "un"
    cod = (codigo or "").strip().upper() or next_apu_codigo(c)
    breakdown = calc_apu_desde_items(
        items, leyes_pct=leyes_pct, perdidas_pct=perdidas_pct
    )
    hoy = core.hoy_chile().isoformat()
    if apu_id:
        row = get_apu(c, apu_id)
        if not row:
            return False, "APU no encontrado.", None
        dup = c.execute(
            "SELECT id FROM apu WHERE upper(codigo)=upper(?) AND id<>?",
            (cod, int(apu_id)),
        ).fetchone()
        if dup:
            return False, "Ya existe un APU con ese código.", None
        c.execute(
            """
            UPDATE apu SET codigo=?, nombre=?, unidad=?, activo=?,
              leyes_pct=?, perdidas_pct=?, pu_neto=?, notas=?
            WHERE id=?
            """,
            (
                cod,
                nom,
                und,
                1 if activo else 0,
                _f(leyes_pct),
                _f(perdidas_pct),
                breakdown["pu_neto"],
                (notas or "").strip() or None,
                int(apu_id),
            ),
        )
        c.execute("DELETE FROM apu_items WHERE apu_id=?", (int(apu_id),))
        cid = int(apu_id)
    else:
        dup = c.execute(
            "SELECT id FROM apu WHERE upper(codigo)=upper(?)", (cod,)
        ).fetchone()
        if dup:
            return False, "Ya existe un APU con ese código.", None
        cur = c.execute(
            """
            INSERT INTO apu
            (codigo, nombre, unidad, activo, leyes_pct, perdidas_pct, pu_neto, notas, creado_en)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                cod,
                nom,
                und,
                1 if activo else 0,
                _f(leyes_pct),
                _f(perdidas_pct),
                breakdown["pu_neto"],
                (notas or "").strip() or None,
                hoy,
            ),
        )
        cid = int(cur.lastrowid)

    orden = 0
    for it in items:
        desc = (it.get("descripcion") or "").strip()
        if not desc:
            continue
        tipo = (it.get("tipo") or "insumo").strip().lower()
        if tipo not in APU_ITEM_TIPOS:
            tipo = "insumo"
        cant = _f(it.get("cantidad"))
        pu = _f(it.get("precio_unitario"))
        if cant < 0 or pu < 0:
            continue
        total = round(cant * pu, 2)
        orden += 1
        c.execute(
            """
            INSERT INTO apu_items
            (apu_id, tipo, descripcion, unidad, cantidad, precio_unitario, total, orden)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                cid,
                tipo,
                desc,
                (it.get("unidad") or "un").strip() or "un",
                cant,
                pu,
                total,
                orden,
            ),
        )
    if orden == 0:
        return False, "Agregue al menos un ítem (insumo, MO u otro).", None
    # Recalcular con ítems persistidos
    persisted = [
        {
            "tipo": r["tipo"],
            "cantidad": r["cantidad"],
            "precio_unitario": r["precio_unitario"],
            "total": r["total"],
        }
        for r in list_apu_items(c, cid)
    ]
    breakdown = calc_apu_desde_items(
        persisted, leyes_pct=leyes_pct, perdidas_pct=perdidas_pct
    )
    c.execute(
        "UPDATE apu SET pu_neto=? WHERE id=?", (breakdown["pu_neto"], cid)
    )
    pu_txt = f"{breakdown['pu_neto']:,.0f}".replace(",", ".")
    return True, f"APU {cod} guardado (PU neto ${pu_txt}).", cid


def list_obras(c, *, solo_activas: bool = False) -> list[Any]:
    sql = """
        SELECT cc.*, cl.razon_social AS cliente_nombre
        FROM centros_costo cc
        LEFT JOIN clientes cl ON cl.id = cc.cliente_id
        WHERE COALESCE(cc.tipo, 'general') = 'obra'
    """
    if solo_activas:
        sql += " AND COALESCE(cc.activo,1)=1 AND COALESCE(cc.estado_obra,'activa')='activa'"
    sql += " ORDER BY COALESCE(cc.orden,0), lower(cc.nombre), cc.id"
    return c.execute(sql).fetchall()


def crear_obra(
    c,
    *,
    nombre: str,
    cliente_id: int | None = None,
    presupuesto: float = 0.0,
    fecha_inicio: str | None = None,
    notas_estado: str = "activa",
) -> tuple[bool, str, int | None]:
    nom = (nombre or "").strip()
    if not nom:
        return False, "Indique el nombre de la obra.", None
    exists = c.execute(
        "SELECT id FROM centros_costo WHERE lower(nombre)=lower(?)", (nom,)
    ).fetchone()
    if exists:
        return False, "Ya existe un centro/obra con ese nombre.", None
    ord_row = c.execute(
        "SELECT COALESCE(MAX(orden),0)+1 AS o FROM centros_costo"
    ).fetchone()
    cur = c.execute(
        """
        INSERT INTO centros_costo
        (nombre, activo, orden, presupuesto, tipo, cliente_id, estado_obra, fecha_inicio)
        VALUES (?,1,?,?,'obra',?,?,?)
        """,
        (
            nom,
            int(ord_row["o"] or 1),
            max(0.0, _f(presupuesto)),
            int(cliente_id) if cliente_id else None,
            (notas_estado or "activa").strip() or "activa",
            (fecha_inicio or "").strip() or None,
        ),
    )
    return True, f"Obra «{nom}» creada (CC).", int(cur.lastrowid)


def actualizar_obra(
    c,
    obra_id: int,
    *,
    nombre: str | None = None,
    activo: int | None = None,
    cliente_id: int | None = None,
    estado_obra: str | None = None,
    fecha_inicio: str | None = None,
    fecha_fin: str | None = None,
    presupuesto: float | None = None,
) -> tuple[bool, str]:
    row = c.execute(
        "SELECT * FROM centros_costo WHERE id=? AND COALESCE(tipo,'general')='obra'",
        (int(obra_id),),
    ).fetchone()
    if not row:
        return False, "Obra no encontrada."
    nom = row["nombre"]
    act = int(row["activo"] or 0)
    cli = row["cliente_id"]
    est = row["estado_obra"] or "activa"
    fi = row["fecha_inicio"]
    ff = row["fecha_fin"]
    ppto = float(row["presupuesto"] or 0)
    if nombre is not None:
        nom = (nombre or "").strip()
        if not nom:
            return False, "Nombre vacío."
        dup = c.execute(
            "SELECT id FROM centros_costo WHERE lower(nombre)=lower(?) AND id<>?",
            (nom, int(obra_id)),
        ).fetchone()
        if dup:
            return False, "Ya existe otro CC/obra con ese nombre."
    if activo is not None:
        act = 1 if int(activo) else 0
    if cliente_id is not None:
        cli = int(cliente_id) if cliente_id else None
    if estado_obra is not None:
        est = (estado_obra or "activa").strip() or "activa"
    if fecha_inicio is not None:
        fi = (fecha_inicio or "").strip() or None
    if fecha_fin is not None:
        ff = (fecha_fin or "").strip() or None
    if presupuesto is not None:
        ppto = max(0.0, _f(presupuesto))
    c.execute(
        """
        UPDATE centros_costo SET
          nombre=?, activo=?, presupuesto=?, cliente_id=?,
          estado_obra=?, fecha_inicio=?, fecha_fin=?, tipo='obra'
        WHERE id=?
        """,
        (nom, act, ppto, cli, est, fi, ff, int(obra_id)),
    )
    return True, "Obra actualizada."


def sincronizar_ppto_obra_desde_cotizacion(c, cot_id: int) -> tuple[bool, str]:
    """Ppto de obra = subtotal de partidas (APU × cantidad)."""
    cot = c.execute("SELECT * FROM cotizaciones WHERE id=?", (int(cot_id),)).fetchone()
    if not cot:
        return False, "Cotización no encontrada."
    if (cot["tipo_cotizacion"] or "normal") != "obra":
        return False, "No es cotización de obra."
    cc_id = cot["centro_costo_id"]
    if not cc_id:
        return False, "Cotización de obra sin CC/obra."
    subtotal = float(cot["subtotal"] or 0)
    # Preferir suma de líneas de trabajo (sin GG/util embebidos)
    items = c.execute(
        """
        SELECT descripcion, total FROM cotizacion_items
        WHERE cotizacion_id=?
        """,
        (int(cot_id),),
    ).fetchall()
    partidas = 0.0
    for it in items:
        d = it["descripcion"] or ""
        if core._is_gg_line(d) or core._is_util_line(d):
            continue
        partidas += float(it["total"] or 0)
    ppto = partidas if partidas > 0 else subtotal
    c.execute(
        """
        UPDATE centros_costo
        SET presupuesto=?, cotizacion_id=?, tipo='obra',
            nombre=COALESCE(NULLIF(nombre,''), ?)
        WHERE id=?
        """,
        (ppto, int(cot_id), cot["proyecto"] or cot["titulo"] or "", int(cc_id)),
    )
    # Si proyecto vacío, poner nombre obra
    if cot["proyecto"]:
        c.execute(
            "UPDATE cotizaciones SET proyecto=? WHERE id=? AND (proyecto IS NULL OR trim(proyecto)='')",
            (cot["proyecto"], int(cot_id)),
        )
    return True, f"Presupuesto de obra actualizado: {ppto:,.0f}".replace(",", ".")


def obra_resumen(c, obra_id: int) -> dict[str, Any]:
    obra = c.execute(
        """
        SELECT cc.*, cl.razon_social AS cliente_nombre
        FROM centros_costo cc
        LEFT JOIN clientes cl ON cl.id=cc.cliente_id
        WHERE cc.id=?
        """,
        (int(obra_id),),
    ).fetchone()
    if not obra:
        return {}
    row = c.execute(
        """
        SELECT COALESCE(SUM(monto),0) AS t
        FROM factura_compra_cc WHERE centro_costo_id=?
        """,
        (int(obra_id),),
    ).fetchone()
    gasto_compras = float(row["t"] or 0)
    mat = c.execute(
        """
        SELECT COALESCE(SUM(cantidad * COALESCE(costo_unitario,0)),0) AS t
        FROM inventario_movimientos
        WHERE tipo='salida' AND centro_costo_id=?
        """,
        (int(obra_id),),
    ).fetchone()
    gasto_mat = float(mat["t"] or 0)
    ppto = float(obra["presupuesto"] or 0)
    gasto = gasto_compras + gasto_mat
    return {
        "obra": obra,
        "ppto": ppto,
        "gasto_compras": gasto_compras,
        "gasto_materiales": gasto_mat,
        "gasto_total": gasto,
        "avance_pct": (gasto / ppto * 100.0) if ppto > 0 else 0.0,
    }
