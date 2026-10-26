"""Pagos extras de Remuneraciones: un monto con nota, del mes.

Suman en el líquido a provisionar. No rebajan el préstamo.
La liquidación del mes lee las mismas líneas.
"""
from __future__ import annotations

import sqlite3


def mes_norm(mes) -> str:
    return f"{int(str(mes).strip()):02d}"


def asegurar_tabla(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS remuneracion_extra (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trabajador_id INTEGER NOT NULL,
            mes TEXT NOT NULL,
            anio INTEGER NOT NULL,
            monto REAL NOT NULL,
            nota TEXT NOT NULL DEFAULT ''
        )"""
    )


def proyeccion(base: float, extras: float) -> float:
    """El líquido a provisionar más los pagos extras del mes."""
    return max(0.0, float(base or 0)) + max(0.0, float(extras or 0))


def listar(
    conn: sqlite3.Connection,
    mes,
    anio: int,
    trabajador_id: int | None = None,
) -> list[dict]:
    asegurar_tabla(conn)
    mes_n = mes_norm(mes)
    anio_n = int(anio)
    conn.row_factory = sqlite3.Row
    if trabajador_id is None:
        rows = conn.execute(
            """SELECT id, trabajador_id, mes, anio, monto, nota
               FROM remuneracion_extra
               WHERE mes=? AND anio=?
               ORDER BY trabajador_id, id""",
            (mes_n, anio_n),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT id, trabajador_id, mes, anio, monto, nota
               FROM remuneracion_extra
               WHERE mes=? AND anio=? AND trabajador_id=?
               ORDER BY id""",
            (mes_n, anio_n, int(trabajador_id)),
        ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "trabajador_id": int(row["trabajador_id"]),
            "mes": str(row["mes"]),
            "anio": int(row["anio"]),
            "monto": float(row["monto"] or 0),
            "nota": str(row["nota"] or "").strip(),
        }
        for row in rows
    ]


def total_trabajador(conn: sqlite3.Connection, trabajador_id: int, mes, anio: int) -> float:
    return sum(item["monto"] for item in listar(conn, mes, anio, int(trabajador_id)))


def agregar(
    conn: sqlite3.Connection,
    trabajador_id: int,
    mes,
    anio: int,
    monto: float,
    nota: str,
) -> tuple[bool, str]:
    asegurar_tabla(conn)
    monto = float(monto or 0)
    texto = (nota or "").strip()
    if int(trabajador_id) <= 0:
        return False, "Trabajador inválido."
    if monto <= 0:
        return False, "El pago extra debe ser mayor a cero."
    if not texto:
        return False, "Escriba la nota del pago extra."
    conn.execute(
        """INSERT INTO remuneracion_extra (trabajador_id, mes, anio, monto, nota)
           VALUES (?, ?, ?, ?, ?)""",
        (int(trabajador_id), mes_norm(mes), int(anio), monto, texto[:200]),
    )
    return True, "Pago extra agregado."


def eliminar(conn: sqlite3.Connection, extra_id: int, mes, anio: int) -> tuple[bool, str]:
    asegurar_tabla(conn)
    cur = conn.execute(
        "DELETE FROM remuneracion_extra WHERE id=? AND mes=? AND anio=?",
        (int(extra_id), mes_norm(mes), int(anio)),
    )
    if cur.rowcount != 1:
        return False, "Pago extra no encontrado."
    return True, "Pago extra eliminado."
