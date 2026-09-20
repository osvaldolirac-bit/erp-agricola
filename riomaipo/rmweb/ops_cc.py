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
    core._ensure_columns(c, "facturas_compra", [("rubro_id", "INTEGER")])
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


def crear_centro(c, nombre: str) -> tuple[bool, str]:
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
    c.execute(
        "INSERT INTO centros_costo (nombre, activo, orden) VALUES (?,1,?)",
        (nom, int(ord_row["o"] or 1)),
    )
    return True, f"Centro de costo «{nom}» creado."


def actualizar_centro(c, cc_id: int, *, nombre: str | None = None, activo: int | None = None) -> tuple[bool, str]:
    row = c.execute("SELECT * FROM centros_costo WHERE id=?", (int(cc_id),)).fetchone()
    if not row:
        return False, "Centro de costo no encontrado."
    nom = row["nombre"]
    act = int(row["activo"] or 0)
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
    c.execute(
        "UPDATE centros_costo SET nombre=?, activo=? WHERE id=?",
        (nom, act, int(cc_id)),
    )
    return True, "Centro de costo actualizado."


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
    if not ids:
        return False, "Seleccione al menos un centro de costo."
    activos = {
        int(r["id"])
        for r in c.execute(
            f"SELECT id FROM centros_costo WHERE activo=1 AND id IN ({','.join('?'*len(ids))})",
            ids,
        ).fetchall()
    }
    ids = [i for i in ids if i in activos]
    if not ids:
        return False, "Los centros seleccionados no están activos."

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
    return True, "Imputación a centros de costo guardada."


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
