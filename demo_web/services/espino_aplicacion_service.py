"""Libro de Campo El Espino: guardar con bodega CC EL ESPINO en una transacción."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from demo_web.services.espino_bodega_desfase import revertir_salida_linea_espino, revertir_salidas_lineas_espino
from demo_web.services.lc_bodega_desfase import ensure_movimiento_id_column, vincular_movimiento_linea_libro
from demo_web.services.native import espino_bodega

ESPINO_TENANT_SLUG = "espino"
CC_ESPINO = espino_bodega.CC_ESPINO


class EspinoAplicacionError(Exception):
    def __init__(self, msg: str):
        self.msg = msg
        super().__init__(msg)


def assert_tenant_espino(tenant_slug: str) -> None:
    slug = (tenant_slug or "").strip().lower()
    if slug != ESPINO_TENANT_SLUG:
        raise EspinoAplicacionError(
            "Esta operación solo aplica al tenant El Espino (espino)."
        )


@dataclass
class GuardarEspinoResult:
    n_app: int


@dataclass
class EliminarEspinoResult:
    n_app: int
    reverts: list[dict]
    omitidas_sin_mov: list[str]


def _rollback(conn) -> None:
    try:
        conn.rollback()
    except Exception:
        pass


def guardar_aplicacion_espino(
    conn,
    demo,
    *,
    tenant_slug: str,
    car: list[dict],
    fe_app,
    especie: str,
    total_agua: float,
    aplicador: str,
    op_cert: bool,
    maquinaria: str,
    tractor: str,
    n_app_fn: Callable,
    n_orden_fn: Callable,
) -> GuardarEspinoResult:
    assert_tenant_espino(tenant_slug)
    if not car:
        raise EspinoAplicacionError("Agregue al menos un producto al evento.")

    for item in car:
        ok, msg, _, _, _ = espino_bodega.validar_salida_bodega(
            demo,
            conn,
            float(item.get("gasto_total") or 0),
            producto=str(item.get("producto") or ""),
        )
        if not ok:
            raise EspinoAplicacionError(msg)

    n_app = int(n_app_fn(conn))
    n_orden = n_orden_fn(conn)
    ensure_movimiento_id_column(conn)

    conn.execute("BEGIN IMMEDIATE")
    try:
        pares: list[tuple[int, dict]] = []
        for item in car:
            demo._insertar_linea_libro_campo(
                conn,
                fe_app,
                n_app,
                CC_ESPINO,
                especie,
                item,
                total_agua,
                aplicador,
                op_cert,
                maquinaria,
                tractor,
                n_orden=n_orden,
            )
            linea_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            pares.append((linea_id, item))

        for linea_id, item in pares:
            ok, msg, mov_id = espino_bodega.registrar_salida_bodega(
                demo,
                conn,
                float(item.get("gasto_total") or 0),
                producto=str(item.get("producto") or ""),
                fecha=fe_app,
            )
            if not ok:
                raise EspinoAplicacionError(msg)
            if mov_id:
                vincular_movimiento_linea_libro(conn, linea_id, int(mov_id))

        conn.commit()
    except EspinoAplicacionError:
        _rollback(conn)
        raise
    except Exception as exc:
        _rollback(conn)
        raise EspinoAplicacionError(f"No se pudo guardar la aplicación: {exc}") from exc

    return GuardarEspinoResult(n_app=n_app)


def eliminar_aplicacion_espino(
    conn,
    demo,
    *,
    tenant_slug: str,
    n_app: int,
    lineas_fn: Callable,
) -> EliminarEspinoResult:
    assert_tenant_espino(tenant_slug)
    rows = lineas_fn(conn, n_app)
    if not rows:
        raise EspinoAplicacionError("No hay líneas guardadas para esa aplicación.")

    conn.execute("BEGIN IMMEDIATE")
    try:
        rev_info = revertir_salidas_lineas_espino(conn, rows)
        conn.execute(
            "DELETE FROM libro_campo WHERE n_aplicacion=? AND UPPER(sector)=?",
            (int(n_app), CC_ESPINO.upper()),
        )
        conn.commit()
    except Exception as exc:
        _rollback(conn)
        raise EspinoAplicacionError(f"No se pudo eliminar la aplicación: {exc}") from exc

    omitidas = [
        str(r.get("producto") or "?")
        for r in rev_info
        if r.get("skipped") and r.get("reason") == "sin_movimiento"
    ]
    return EliminarEspinoResult(n_app=int(n_app), reverts=rev_info, omitidas_sin_mov=omitidas)


def reabrir_aplicacion_espino(
    conn,
    demo,
    *,
    tenant_slug: str,
    n_app: int,
    lineas_fn: Callable,
) -> tuple[list[dict], list[dict], list[str]]:
    assert_tenant_espino(tenant_slug)
    rows = lineas_fn(conn, n_app)
    if not rows:
        raise EspinoAplicacionError("No hay líneas guardadas para esa aplicación.")

    conn.execute("BEGIN IMMEDIATE")
    try:
        rev_info = revertir_salidas_lineas_espino(conn, rows)
        conn.execute(
            "DELETE FROM libro_campo WHERE n_aplicacion=? AND UPPER(sector)=?",
            (int(n_app), CC_ESPINO.upper()),
        )
        conn.commit()
    except Exception as exc:
        _rollback(conn)
        raise EspinoAplicacionError(f"No se pudo reabrir la aplicación: {exc}") from exc

    omitidas = [
        str(r.get("producto") or "?")
        for r in rev_info
        if r.get("skipped") and r.get("reason") == "sin_movimiento"
    ]
    return rows, rev_info, omitidas


def eliminar_linea_espino(
    conn,
    demo,
    *,
    tenant_slug: str,
    linea_id: int,
    n_app: int,
    fetch_linea_fn: Callable,
) -> dict[str, Any]:
    assert_tenant_espino(tenant_slug)
    row = fetch_linea_fn(conn, linea_id)
    if not row:
        raise EspinoAplicacionError("Línea no encontrada.")
    if int(row.get("n_aplicacion") or 0) != int(n_app):
        raise EspinoAplicacionError("La línea no pertenece a esa aplicación.")
    if str(row.get("sector") or "").strip().upper() != CC_ESPINO.upper():
        raise EspinoAplicacionError("La línea no es del sector El Espino.")

    conn.execute("BEGIN IMMEDIATE")
    try:
        res = revertir_salida_linea_espino(conn, row)
        conn.execute("DELETE FROM libro_campo WHERE id=?", (int(linea_id),))
        conn.commit()
    except Exception as exc:
        _rollback(conn)
        raise EspinoAplicacionError(f"No se pudo eliminar la línea: {exc}") from exc
    return {"revert": res, "linea_id": linea_id, "producto": row.get("producto")}
