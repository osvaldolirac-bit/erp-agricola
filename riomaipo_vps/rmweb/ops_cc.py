"""Centros de costo y rubros de gasto (Comercial / Compras)."""
from __future__ import annotations

from typing import Any

from rmweb import core

RUBROS_DEFAULT = (
    "Bienes y mercadería",
    "Servicios profesionales",
    "Marketing y publicidad",
    "Arriendos y locales",
    "Transporte y logística",
    "Tecnología y software",
    "Gastos de oficina",
    "Otros / sin clasificar",
)

CC_DEFAULT = (
    "Administración",
    "Operaciones",
    "Comercial / Ventas",
    "Logística",
)


def ensure_cc_schema(c) -> None:
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS centros_costo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            activo INTEGER DEFAULT 1,
            orden INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS rubros_gasto (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            activo INTEGER DEFAULT 1,
            orden INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS factura_compra_cc (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            factura_id INTEGER NOT NULL,
            centro_costo_id INTEGER NOT NULL,
            monto REAL DEFAULT 0,
            FOREIGN KEY(factura_id) REFERENCES facturas_compra(id) ON DELETE CASCADE,
            FOREIGN KEY(centro_costo_id) REFERENCES centros_costo(id)
        );
        """
    )
    core._ensure_columns(
        c,
        "facturas_compra",
        [
            ("rubro_id", "INTEGER"),
            ("cc_base", "TEXT DEFAULT 'neto'"),
        ],
    )
    core._ensure_columns(
        c,
        "centros_costo",
        [
            ("presupuesto", "REAL DEFAULT 0"),
        ],
    )
    _seed_rubros(c)
    _seed_cc(c)


def _seed_rubros(c) -> None:
    n = c.execute("SELECT COUNT(*) AS n FROM rubros_gasto").fetchone()["n"]
    if int(n or 0) > 0:
        return
    for i, nombre in enumerate(RUBROS_DEFAULT, start=1):
        c.execute(
            "INSERT INTO rubros_gasto (nombre, activo, orden) VALUES (?,1,?)",
            (nombre, i),
        )


def _seed_cc(c) -> None:
    n = c.execute("SELECT COUNT(*) AS n FROM centros_costo").fetchone()["n"]
    if int(n or 0) > 0:
        return
    for i, nombre in enumerate(CC_DEFAULT, start=1):
        c.execute(
            "INSERT INTO centros_costo (nombre, activo, orden) VALUES (?,1,?)",
            (nombre, i),
        )


def list_centros(c, *, solo_activos: bool = False) -> list[Any]:
    sql = "SELECT * FROM centros_costo"
    if solo_activos:
        sql += " WHERE activo=1"
    sql += " ORDER BY orden, lower(nombre), id"
    return c.execute(sql).fetchall()


def list_rubros(c, *, solo_activos: bool = True) -> list[Any]:
    sql = "SELECT * FROM rubros_gasto"
    if solo_activos:
        sql += " WHERE activo=1"
    sql += " ORDER BY orden, lower(nombre), id"
    return c.execute(sql).fetchall()


def _parse_presupuesto(valor) -> float:
    try:
        return max(0.0, float(str(valor or "0").replace(",", ".")))
    except (TypeError, ValueError):
        return 0.0


def crear_centro(c, nombre: str, presupuesto=None) -> tuple[bool, str]:
    nom = (nombre or "").strip()
    if not nom:
        return False, "Indique el nombre del centro de costo."
    if len(nom) > 80:
        return False, "Nombre demasiado largo (máx. 80)."
    exists = c.execute(
        "SELECT id FROM centros_costo WHERE lower(nombre)=lower(?)", (nom,)
    ).fetchone()
    if exists:
        return False, "Ya existe un centro de costo con ese nombre."
    ord_row = c.execute(
        "SELECT COALESCE(MAX(orden),0)+1 AS o FROM centros_costo"
    ).fetchone()
    ppto = _parse_presupuesto(presupuesto) if presupuesto is not None else 0.0
    c.execute(
        "INSERT INTO centros_costo (nombre, activo, orden, presupuesto) VALUES (?,1,?,?)",
        (nom, int(ord_row["o"] or 1), ppto),
    )
    return True, f"Centro de costo «{nom}» creado."


def actualizar_centro(
    c,
    cc_id: int,
    *,
    nombre: str | None = None,
    activo: int | None = None,
    presupuesto=None,
) -> tuple[bool, str]:
    row = c.execute("SELECT * FROM centros_costo WHERE id=?", (int(cc_id),)).fetchone()
    if not row:
        return False, "Centro de costo no encontrado."
    nom = row["nombre"]
    act = int(row["activo"] or 0)
    keys = row.keys() if hasattr(row, "keys") else []
    ppto = float(row["presupuesto"] or 0) if "presupuesto" in keys else 0.0
    if nombre is not None:
        nom = (nombre or "").strip()
        if not nom:
            return False, "Nombre vacío."
        dup = c.execute(
            "SELECT id FROM centros_costo WHERE lower(nombre)=lower(?) AND id<>?",
            (nom, int(cc_id)),
        ).fetchone()
        if dup:
            return False, "Ya existe otro centro con ese nombre."
    if activo is not None:
        act = 1 if int(activo) else 0
    if presupuesto is not None:
        ppto = _parse_presupuesto(presupuesto)
    c.execute(
        "UPDATE centros_costo SET nombre=?, activo=?, presupuesto=? WHERE id=?",
        (nom, act, ppto, int(cc_id)),
    )
    return True, "Centro de costo actualizado."


def rubro_en_uso(c, rubro_id: int) -> int:
    row = c.execute(
        "SELECT COUNT(*) AS n FROM facturas_compra WHERE rubro_id=?",
        (int(rubro_id),),
    ).fetchone()
    return int(row["n"] or 0)


def crear_rubro(c, nombre: str) -> tuple[bool, str]:
    nom = (nombre or "").strip()
    if not nom:
        return False, "Indique el nombre del rubro."
    if len(nom) > 80:
        return False, "Nombre demasiado largo (máx. 80)."
    exists = c.execute(
        "SELECT id FROM rubros_gasto WHERE lower(nombre)=lower(?)", (nom,)
    ).fetchone()
    if exists:
        return False, "Ya existe un rubro con ese nombre."
    ord_row = c.execute(
        "SELECT COALESCE(MAX(orden),0)+1 AS o FROM rubros_gasto"
    ).fetchone()
    c.execute(
        "INSERT INTO rubros_gasto (nombre, activo, orden) VALUES (?,1,?)",
        (nom, int(ord_row["o"] or 1)),
    )
    return True, f"Rubro «{nom}» creado."


def actualizar_rubro(
    c,
    rubro_id: int,
    *,
    nombre: str | None = None,
    activo: int | None = None,
) -> tuple[bool, str]:
    row = c.execute("SELECT * FROM rubros_gasto WHERE id=?", (int(rubro_id),)).fetchone()
    if not row:
        return False, "Rubro no encontrado."
    nom = row["nombre"]
    act = int(row["activo"] or 0)
    if nombre is not None:
        nom = (nombre or "").strip()
        if not nom:
            return False, "Nombre vacío."
        dup = c.execute(
            "SELECT id FROM rubros_gasto WHERE lower(nombre)=lower(?) AND id<>?",
            (nom, int(rubro_id)),
        ).fetchone()
        if dup:
            return False, "Ya existe otro rubro con ese nombre."
    if activo is not None:
        act = 1 if int(activo) else 0
    c.execute(
        "UPDATE rubros_gasto SET nombre=?, activo=? WHERE id=?",
        (nom, act, int(rubro_id)),
    )
    return True, "Rubro actualizado."


def eliminar_rubro(c, rubro_id: int) -> tuple[bool, str]:
    row = c.execute("SELECT * FROM rubros_gasto WHERE id=?", (int(rubro_id),)).fetchone()
    if not row:
        return False, "Rubro no encontrado."
    usos = rubro_en_uso(c, int(rubro_id))
    if usos > 0:
        return (
            False,
            f"No se puede eliminar «{row['nombre']}»: está imputado en {usos} compra(s).",
        )
    c.execute("DELETE FROM rubros_gasto WHERE id=?", (int(rubro_id),))
    return True, f"Rubro «{row['nombre']}» eliminado."


def normalizar_cc_base(valor: str | None) -> str:
    v = (valor or "").strip().lower()
    return "bruto" if v == "bruto" else "neto"


def monto_base_imputacion(neto: float, total: float, cc_base: str | None) -> float:
    if normalizar_cc_base(cc_base) == "bruto":
        return max(0.0, float(total or 0))
    return max(0.0, float(neto or 0))


def imputaciones_factura(c, factura_id: int) -> list[Any]:
    return c.execute(
        """
        SELECT i.*, cc.nombre AS centro_costo
        FROM factura_compra_cc i
        LEFT JOIN centros_costo cc ON cc.id = i.centro_costo_id
        WHERE i.factura_id=?
        ORDER BY cc.orden, cc.nombre, i.id
        """,
        (int(factura_id),),
    ).fetchall()


def guardar_imputacion_cc(
    c,
    factura_id: int,
    centro_ids: list[int],
    neto: float,
    montos: dict[int, float] | None = None,
) -> tuple[bool, str]:
    """Reemplaza imputación multi-CC. Por defecto reparte el neto en partes iguales."""
    ids = []
    for x in centro_ids:
        try:
            cid = int(x)
        except (TypeError, ValueError):
            continue
        if cid > 0 and cid not in ids:
            ids.append(cid)
    if len(ids) > 1:
        ids = ids[:1]
    if not ids:
        return False, "Seleccione un centro de costo."
    activos = {
        int(r["id"])
        for r in c.execute(
            f"SELECT id FROM centros_costo WHERE activo=1 AND id IN ({','.join('?'*len(ids))})",
            ids,
        ).fetchall()
    }
    ids = [i for i in ids if i in activos]
    if not ids:
        return False, "El centro de costo seleccionado no está activo."

    neto_i = max(0.0, float(neto or 0))
    montos = montos or {}
    partes: list[tuple[int, float]] = []
    if any(cid in montos and float(montos[cid] or 0) > 0 for cid in ids):
        for cid in ids:
            m = float(montos.get(cid) or 0)
            if m > 0:
                partes.append((cid, round(m)))
        if not partes:
            return False, "Indique montos de imputación válidos."
    else:
        base = int(round(neto_i)) // len(ids)
        resto = int(round(neto_i)) - base * len(ids)
        for i, cid in enumerate(ids):
            m = base + (1 if i < resto else 0)
            partes.append((cid, float(m)))

    c.execute("DELETE FROM factura_compra_cc WHERE factura_id=?", (int(factura_id),))
    for cid, monto in partes:
        c.execute(
            """
            INSERT INTO factura_compra_cc (factura_id, centro_costo_id, monto)
            VALUES (?,?,?)
            """,
            (int(factura_id), cid, monto),
        )
    return True, "Imputación a centro de costo guardada."


def resumen_cc_factura(c, factura_id: int) -> str:
    rows = imputaciones_factura(c, factura_id)
    if not rows:
        return "—"
    return ", ".join(
        f"{r['centro_costo'] or 'CC'}" for r in rows
    )


def rubro_nombre(c, rubro_id: int | None) -> str:
    if not rubro_id:
        return "—"
    row = c.execute(
        "SELECT nombre FROM rubros_gasto WHERE id=?", (int(rubro_id),)
    ).fetchone()
    return str(row["nombre"]) if row else "—"


def _fecha_filtro_sql(
    *,
    desde: str | None = None,
    hasta: str | None = None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    d = (desde or "").strip()
    h = (hasta or "").strip()
    if d:
        clauses.append("AND f.fecha_emision >= ?")
        params.append(d)
    if h:
        clauses.append("AND f.fecha_emision <= ?")
        params.append(h)
    return (" ".join(clauses), params)


def _fecha_filtro_mov_sql(
    *,
    desde: str | None = None,
    hasta: str | None = None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    d = (desde or "").strip()
    h = (hasta or "").strip()
    if d:
        clauses.append("AND m.fecha >= ?")
        params.append(d)
    if h:
        clauses.append("AND m.fecha <= ?")
        params.append(h)
    return (" ".join(clauses), params)


def _sql_monto_salida_bodega() -> str:
    """Valor imputado: cantidad × costo del movimiento o PMP si costo u. es 0."""
    return """
        m.cantidad * (
            CASE
                WHEN COALESCE(m.costo_unitario, 0) > 0 THEN m.costo_unitario
                ELSE COALESCE(i.costo_pmp, 0)
            END
        )
    """


def totales_salida_bodega_por_cc(
    c,
    *,
    desde: str | None = None,
    hasta: str | None = None,
) -> dict[int, float]:
    extra, params = _fecha_filtro_mov_sql(desde=desde, hasta=hasta)
    monto_sql = _sql_monto_salida_bodega()
    rows = c.execute(
        f"""
        SELECT m.centro_costo_id AS cc_id, COALESCE(SUM({monto_sql}), 0) AS monto
        FROM inventario_movimientos m
        JOIN inventario i ON i.id = m.inventario_id
        WHERE m.tipo = 'salida'
          AND m.centro_costo_id IS NOT NULL
          {extra}
        GROUP BY m.centro_costo_id
        """,
        params,
    ).fetchall()
    return {int(r["cc_id"]): float(r["monto"] or 0) for r in rows if r["cc_id"]}


def matriz_cc_rubros(
    c,
    *,
    desde: str | None = None,
    hasta: str | None = None,
) -> dict[str, Any]:
    """Matriz rubro × centro de costo con totales de fila/columna (monto imputado)."""
    centros = list_centros(c, solo_activos=True)
    rubros_all = list_rubros(c, solo_activos=False)
    extra, params = _fecha_filtro_sql(desde=desde, hasta=hasta)
    rows = c.execute(
        f"""
        SELECT
            COALESCE(f.rubro_id, 0) AS rubro_id,
            fcc.centro_costo_id AS cc_id,
            COALESCE(SUM(fcc.monto), 0) AS monto
        FROM factura_compra_cc fcc
        JOIN facturas_compra f ON f.id = fcc.factura_id
        WHERE 1=1 {extra}
        GROUP BY COALESCE(f.rubro_id, 0), fcc.centro_costo_id
        """,
        params,
    ).fetchall()

    cc_ids = [int(x["id"]) for x in centros]
    montos_por_rubro: dict[int, dict[int, float]] = {}
    for r in rows:
        rid = int(r["rubro_id"] or 0)
        cid = int(r["cc_id"] or 0)
        monto = float(r["monto"] or 0)
        if cid not in cc_ids:
            continue
        montos_por_rubro.setdefault(rid, {})[cid] = (
            montos_por_rubro.setdefault(rid, {}).get(cid, 0.0) + monto
        )

    # Filas: rubros activos + inactivos/ausentes que tengan monto en el período.
    rubros = []
    seen: set[int] = set()
    for r in rubros_all:
        rid = int(r["id"])
        tiene = sum(montos_por_rubro.get(rid, {}).values()) > 0
        if int(r["activo"] or 0) or tiene:
            rubros.append(r)
            seen.add(rid)

    rubro_ids = [int(x["id"]) for x in rubros]
    matrix: dict[int, dict[int, float]] = {
        rid: {cid: float(montos_por_rubro.get(rid, {}).get(cid, 0.0)) for cid in cc_ids}
        for rid in rubro_ids
    }
    sin_rubro: dict[int, float] = {cid: 0.0 for cid in cc_ids}
    for rid, by_cc in montos_por_rubro.items():
        if rid in seen:
            continue
        for cid, monto in by_cc.items():
            sin_rubro[cid] = sin_rubro.get(cid, 0.0) + float(monto or 0)

    bodega_por_cc = {cid: 0.0 for cid in cc_ids}
    for cid, monto in totales_salida_bodega_por_cc(c, desde=desde, hasta=hasta).items():
        if cid in bodega_por_cc:
            bodega_por_cc[cid] = float(monto or 0)

    rrhh_por_cc = {cid: 0.0 for cid in cc_ids}
    try:
        from rmweb import ops_rrhh

        ops_rrhh.ensure_rrhh_schema(c)
        for cid, monto in ops_rrhh.totales_por_cc(c, desde=desde, hasta=hasta).items():
            if cid in rrhh_por_cc:
                rrhh_por_cc[cid] = float(monto or 0)
    except Exception:
        pass

    row_totals = {rid: sum(matrix[rid].values()) for rid in rubro_ids}
    col_totals = {
        cid: (
            sum(matrix[rid][cid] for rid in rubro_ids)
            + float(sin_rubro.get(cid) or 0)
            + float(bodega_por_cc.get(cid) or 0)
            + float(rrhh_por_cc.get(cid) or 0)
        )
        for cid in cc_ids
    }
    sin_rubro_total = sum(sin_rubro.values())
    bodega_total = sum(bodega_por_cc.values())
    rrhh_total = sum(rrhh_por_cc.values())
    grand = sum(col_totals.values())

    # Filas de mayor a menor gasto.
    rubros = sorted(
        rubros,
        key=lambda r: (
            -float(row_totals.get(int(r["id"]), 0.0)),
            int(r["orden"] or 0),
            str(r["nombre"] or "").lower(),
        ),
    )
    rubro_ids = [int(x["id"]) for x in rubros]

    def _pct(monto: float) -> float:
        if grand <= 0:
            return 0.0
        return round(100.0 * float(monto or 0) / grand, 1)

    row_pcts = {rid: _pct(row_totals.get(rid, 0.0)) for rid in rubro_ids}
    sin_rubro_pct = _pct(sin_rubro_total)
    bodega_pct = _pct(bodega_total)
    rrhh_pct = _pct(rrhh_total)
    avance = avance_gasto_presupuesto(centros, col_totals)
    return {
        "centros": centros,
        "rubros": rubros,
        "matrix": matrix,
        "row_totals": row_totals,
        "row_pcts": row_pcts,
        "col_totals": col_totals,
        "sin_rubro": sin_rubro,
        "sin_rubro_total": sin_rubro_total,
        "sin_rubro_pct": sin_rubro_pct,
        "bodega": bodega_por_cc,
        "bodega_total": bodega_total,
        "bodega_pct": bodega_pct,
        "rrhh": rrhh_por_cc,
        "rrhh_total": rrhh_total,
        "rrhh_pct": rrhh_pct,
        "grand_total": grand,
        "tiene_sin_rubro": sin_rubro_total > 0,
        "tiene_bodega": bodega_total > 0,
        "tiene_rrhh": rrhh_total > 0,
        "avance": avance,
    }


def avance_gasto_presupuesto(centros, col_totals: dict[int, float]) -> dict[str, Any]:
    """Avance gasto vs presupuesto por CC + totales para dona."""
    filas: list[dict[str, Any]] = []
    ppto_total = 0.0
    gasto_total = 0.0
    for cc in centros:
        cid = int(cc["id"])
        keys = cc.keys() if hasattr(cc, "keys") else []
        ppto = float(cc["presupuesto"] or 0) if "presupuesto" in keys else 0.0
        gasto = float(col_totals.get(cid, 0.0) or 0.0)
        ppto_total += ppto
        gasto_total += gasto
        if ppto > 0:
            pct = round(100.0 * gasto / ppto, 1)
            disponible = max(0.0, ppto - gasto)
            estado = "ok"
            if pct >= 100:
                estado = "over"
            elif pct >= 80:
                estado = "warn"
        else:
            pct = 0.0
            disponible = 0.0
            estado = "sin_ppto"
        filas.append(
            {
                "id": cid,
                "nombre": cc["nombre"],
                "presupuesto": ppto,
                "gasto": gasto,
                "disponible": disponible,
                "pct": pct,
                "estado": estado,
            }
        )
    filas.sort(key=lambda x: (-x["gasto"], str(x["nombre"] or "").lower()))
    disponible_total = max(0.0, ppto_total - gasto_total)
    pct_global = round(100.0 * gasto_total / ppto_total, 1) if ppto_total > 0 else 0.0
    return {
        "filas": filas,
        "presupuesto_total": ppto_total,
        "gasto_total": gasto_total,
        "disponible_total": disponible_total,
        "pct_global": pct_global,
        "tiene_presupuesto": ppto_total > 0,
    }


def detalle_por_centro(
    c,
    cc_id: int,
    *,
    desde: str | None = None,
    hasta: str | None = None,
) -> list[Any]:
    """Compras y salidas de bodega imputadas a un centro de costo."""
    extra, params = _fecha_filtro_sql(desde=desde, hasta=hasta)
    extra_mov, params_mov = _fecha_filtro_mov_sql(desde=desde, hasta=hasta)
    monto_sql = _sql_monto_salida_bodega()
    compras = c.execute(
        f"""
        SELECT
            f.id,
            f.documento,
            f.fecha_emision,
            f.fecha_vencimiento,
            f.neto,
            f.total,
            f.pagado,
            f.saldo,
            f.estado,
            f.orden_compra_id,
            p.razon_social AS proveedor,
            COALESCE(r.nombre, '—') AS rubro_nombre,
            fcc.monto AS monto_cc,
            oc.folio AS oc_folio,
            'compra' AS fuente,
            NULL AS producto_nombre,
            NULL AS cantidad
        FROM factura_compra_cc fcc
        JOIN facturas_compra f ON f.id = fcc.factura_id
        LEFT JOIN proveedores p ON p.id = f.proveedor_id
        LEFT JOIN rubros_gasto r ON r.id = f.rubro_id
        LEFT JOIN ordenes_compra oc ON oc.id = f.orden_compra_id
        WHERE fcc.centro_costo_id = ? {extra}
        """,
        [int(cc_id), *params],
    ).fetchall()
    bodega = c.execute(
        f"""
        SELECT
            m.id,
            CASE
                WHEN COALESCE(m.nota, '') != '' THEN m.nota
                ELSE i.nombre || ' · ' || printf('%.4g', m.cantidad) || ' ' || COALESCE(i.unidad, 'un')
            END AS documento,
            m.fecha AS fecha_emision,
            NULL AS fecha_vencimiento,
            0 AS neto,
            ({monto_sql}) AS total,
            0 AS pagado,
            0 AS saldo,
            'imputado' AS estado,
            NULL AS orden_compra_id,
            'Bodega' AS proveedor,
            'Salida bodega' AS rubro_nombre,
            ({monto_sql}) AS monto_cc,
            NULL AS oc_folio,
            'bodega' AS fuente,
            i.nombre AS producto_nombre,
            m.cantidad AS cantidad
        FROM inventario_movimientos m
        JOIN inventario i ON i.id = m.inventario_id
        WHERE m.tipo = 'salida'
          AND m.centro_costo_id = ?
          {extra_mov}
        """,
        [int(cc_id), *params_mov],
    ).fetchall()
    rrhh: list[Any] = []
    try:
        from rmweb import ops_rrhh

        ops_rrhh.ensure_rrhh_schema(c)
        rrhh = ops_rrhh.list_imputaciones_por_centro(
            c, int(cc_id), desde=desde, hasta=hasta
        )
    except Exception:
        pass
    rows = list(compras) + list(bodega) + list(rrhh)
    rows.sort(
        key=lambda r: (
            str(r["fecha_emision"] or ""),
            int(r["id"] or 0),
        ),
        reverse=True,
    )
    return rows
