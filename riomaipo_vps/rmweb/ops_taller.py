"""Órdenes de trabajo — taller automotriz."""
from __future__ import annotations

import sqlite3
from typing import Any

from rmweb import core

ESTADOS_OT: tuple[tuple[str, str], ...] = (
    ("pendiente", "Pendiente"),
    ("en_proceso", "En proceso"),
    ("listo", "Listo"),
    ("entregado", "Entregado"),
    ("cancelada", "Cancelada"),
)

_ESTADOS_OT_SET = {e[0] for e in ESTADOS_OT}


def estado_ot_label(estado: str | None) -> str:
    e = (estado or "pendiente").strip().lower()
    for k, lbl in ESTADOS_OT:
        if k == e:
            return lbl
    return e or "Pendiente"


def ensure_taller_schema(db) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS taller_ordenes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folio TEXT UNIQUE NOT NULL,
            cotizacion_id INTEGER UNIQUE,
            cliente_id INTEGER,
            patente TEXT,
            vehiculo TEXT,
            mecanico TEXT,
            estado TEXT DEFAULT 'pendiente',
            fecha_apertura TEXT,
            fecha_cierre TEXT,
            notas TEXT,
            FOREIGN KEY(cotizacion_id) REFERENCES cotizaciones(id),
            FOREIGN KEY(cliente_id) REFERENCES clientes(id)
        );
        """
    )
    core._ensure_columns(db, "cotizaciones", [("patente", "TEXT")])


def _next_folio_ot(db) -> str:
    row = db.execute(
        """
        SELECT folio FROM taller_ordenes
        WHERE folio GLOB 'OT-[0-9]*'
        ORDER BY CAST(SUBSTR(folio, 4) AS INTEGER) DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
    n = 1
    if row and row["folio"]:
        try:
            n = int(str(row["folio"]).split("-", 1)[1]) + 1
        except (ValueError, IndexError):
            n = int(db.execute("SELECT COUNT(*) AS c FROM taller_ordenes").fetchone()["c"]) + 1
    return f"OT-{n:04d}"


def crear_ot_desde_cotizacion(db, cotizacion_id: int) -> tuple[bool, str]:
    """Genera OT al aprobar cotización de servicio (tenant taller)."""
    ensure_taller_schema(db)
    exist = db.execute(
        "SELECT id, folio FROM taller_ordenes WHERE cotizacion_id=? LIMIT 1",
        (cotizacion_id,),
    ).fetchone()
    if exist:
        return True, f"OT {exist['folio']} ya existe"

    cot = db.execute(
        """
        SELECT id, cliente_id, folio, patente, proyecto, asunto, notas
        FROM cotizaciones WHERE id=?
        """,
        (cotizacion_id,),
    ).fetchone()
    if not cot:
        return False, "Cotización no encontrada"

    patente = (cot["patente"] or cot["proyecto"] or "").strip() or None
    vehiculo = (cot["asunto"] or "").strip() or None
    folio = _next_folio_ot(db)
    hoy = core.hoy_chile().isoformat()
    try:
        db.execute(
            """
            INSERT INTO taller_ordenes
            (folio, cotizacion_id, cliente_id, patente, vehiculo, estado, fecha_apertura, notas)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                folio,
                cotizacion_id,
                cot["cliente_id"],
                patente,
                vehiculo,
                "pendiente",
                hoy,
                cot["notas"],
            ),
        )
    except sqlite3.IntegrityError:
        return False, "No se pudo crear la OT (folio duplicado)"
    return True, f"OT {folio} creada"


def actualizar_ot(db, ot_id: int, *, mecanico: str | None, estado: str, notas: str | None) -> tuple[bool, str]:
    ensure_taller_schema(db)
    est = (estado or "pendiente").strip().lower()
    if est not in _ESTADOS_OT_SET:
        return False, "Estado inválido"
    row = db.execute("SELECT id, estado FROM taller_ordenes WHERE id=?", (ot_id,)).fetchone()
    if not row:
        return False, "OT no encontrada"
    mec = (mecanico or "").strip() or None
    nota = (notas or "").strip() or None
    fecha_cierre = core.hoy_chile().isoformat() if est in {"entregado", "cancelada"} else None
    db.execute(
        """
        UPDATE taller_ordenes
        SET mecanico=?, estado=?, notas=?, fecha_cierre=COALESCE(?, fecha_cierre)
        WHERE id=?
        """,
        (mec, est, nota, fecha_cierre, ot_id),
    )
    return True, "OT actualizada"
