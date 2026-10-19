"""Libro de Campo La Concepción: guardar/eliminar con bodega en una transacción.

Solo tenant ``concepcion``. No importa Espino ni GlobalGAP.
La conexión ``conn`` debe venir de ``demo.conectar_db()`` del request LC actual.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from demo_web.services.lc_bodega_desfase import (
    ensure_movimiento_id_column,
    insertar_salida_desde_lc,
    lc_dict_desde_item_libro,
    lc_dict_desde_linea_libro,
    mensaje_error_salida_lc,
    revertir_salida_desde_lc,
    revertir_salidas_lineas_libro,
    vincular_movimiento_linea_libro,
)

LC_TENANT_SLUG = "concepcion"


class LcAplicacionError(Exception):
    def __init__(self, msg: str):
        self.msg = msg
        super().__init__(msg)


def assert_tenant_lc(tenant_slug: str) -> None:
    slug = (tenant_slug or "").strip().lower()
    if slug != LC_TENANT_SLUG:
        raise LcAplicacionError(
            "Esta operación solo aplica al tenant La Concepción (concepcion)."
        )


@dataclass
class GuardarLcResult:
    n_app: int
    wx: dict | None
    rebaje_bodega: bool
    rebaje_omitido_copia: bool
    copiado_desde: int | None


@dataclass
class EliminarLcResult:
    n_app: int
    reverts: list[dict]
    omitidas_sin_mov: list[str]


def _rollback(conn) -> None:
    try:
        conn.rollback()
    except Exception:
        pass


def guardar_aplicacion_lc(
    conn,
    demo,
    *,
    tenant_slug: str,
    car: list[dict],
    fe_app,
    huerto: str,
    especie: str,
    total_agua: float,
    aplicador: str,
    op_cert: bool,
    maquinaria: str,
    tractor: str,
    n_app_fn: Callable,
    n_orden_fn: Callable,
    rebaje_bodega: bool,
    rebaje_omitido_copia: bool = False,
    copiado_desde: int | None = None,
) -> GuardarLcResult:
    """Inserta Libro + salidas bodega LC; commit único o rollback total."""
    assert_tenant_lc(tenant_slug)
    if not car:
        raise LcAplicacionError("Agregue al menos un producto al evento.")

    if rebaje_bodega:
        for item in car:
            lc = lc_dict_desde_item_libro(item, fecha=fe_app, sector=huerto)
            res = insertar_salida_desde_lc(conn, lc, dry_run=True)
            if not res.get("ok"):
                raise LcAplicacionError(mensaje_error_salida_lc(demo, res))

    n_app = int(n_app_fn(conn))
    n_orden = n_orden_fn(conn, huerto)
    ensure_movimiento_id_column(conn)

    conn.execute("BEGIN IMMEDIATE")
    try:
        pares_linea_item: list[tuple[int, dict]] = []
        for item in car:
            demo._insertar_linea_libro_campo(
                conn,
                fe_app,
                n_app,
                huerto,
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
            pares_linea_item.append((linea_id, item))

        if rebaje_bodega:
            for linea_id, item in pares_linea_item:
                lc = lc_dict_desde_item_libro(item, fecha=fe_app, sector=huerto)
                res = insertar_salida_desde_lc(conn, lc, dry_run=False)
                if not res.get("ok"):
                    raise LcAplicacionError(mensaje_error_salida_lc(demo, res))
                mov_id = res.get("mov_id")
                if mov_id:
                    vincular_movimiento_linea_libro(conn, linea_id, int(mov_id))

        from demo_web.services.libro_campo_gap import enriquecer_aplicacion_globalgap

        wx = enriquecer_aplicacion_globalgap(
            conn,
            n_app,
            fe_app,
            huerto,
            especie,
            car,
            op_cert=op_cert,
        )
        conn.commit()
    except LcAplicacionError:
        _rollback(conn)
        raise
    except Exception as exc:
        _rollback(conn)
        raise LcAplicacionError(f"No se pudo guardar la aplicación: {exc}") from exc

    return GuardarLcResult(
        n_app=n_app,
        wx=wx,
        rebaje_bodega=rebaje_bodega,
        rebaje_omitido_copia=rebaje_omitido_copia,
        copiado_desde=copiado_desde,
    )


def eliminar_aplicacion_lc(
    conn,
    demo,
    *,
    tenant_slug: str,
    n_app: int,
    lineas_fn: Callable,
) -> EliminarLcResult:
    """Borra aplicación LC y revierte bodega; commit único o rollback."""
    assert_tenant_lc(tenant_slug)
    rows = lineas_fn(conn, n_app)
    if not rows:
        raise LcAplicacionError("No hay líneas guardadas para esa aplicación.")

    conn.execute("BEGIN IMMEDIATE")
    try:
        rev_info = revertir_salidas_lineas_libro(conn, rows)
        conn.execute("DELETE FROM libro_campo WHERE n_aplicacion=?", (int(n_app),))
        conn.commit()
    except Exception as exc:
        _rollback(conn)
        raise LcAplicacionError(f"No se pudo eliminar la aplicación: {exc}") from exc

    omitidas = [
        str((r.get("lc") or {}).get("producto") or "?")
        for r in rev_info
        if r.get("skipped") and r.get("reason") == "sin_movimiento"
    ]
    return EliminarLcResult(n_app=int(n_app), reverts=rev_info, omitidas_sin_mov=omitidas)


def reabrir_aplicacion_lc(
    conn,
    demo,
    *,
    tenant_slug: str,
    n_app: int,
    lineas_fn: Callable,
) -> tuple[list[dict], list[dict], list[str]]:
    """Elimina app LC del historial, revierte bodega; devuelve filas para borrador."""
    assert_tenant_lc(tenant_slug)
    rows = lineas_fn(conn, n_app)
    if not rows:
        raise LcAplicacionError("No hay líneas guardadas para esa aplicación.")

    conn.execute("BEGIN IMMEDIATE")
    try:
        rev_info = revertir_salidas_lineas_libro(conn, rows)
        conn.execute("DELETE FROM libro_campo WHERE n_aplicacion=?", (int(n_app),))
        conn.commit()
    except Exception as exc:
        _rollback(conn)
        raise LcAplicacionError(f"No se pudo reabrir la aplicación: {exc}") from exc

    omitidas = [
        str((r.get("lc") or {}).get("producto") or "?")
        for r in rev_info
        if r.get("skipped") and r.get("reason") == "sin_movimiento"
    ]
    return rows, rev_info, omitidas


def eliminar_linea_lc(
    conn,
    demo,
    *,
    tenant_slug: str,
    linea_id: int,
    n_app: int,
    fetch_linea_fn: Callable,
) -> dict[str, Any]:
    """Elimina una línea LC y revierte su salida bodega (transacción)."""
    assert_tenant_lc(tenant_slug)
    row = fetch_linea_fn(conn, linea_id)
    if not row:
        raise LcAplicacionError("Línea no encontrada.")
    if int(row.get("n_aplicacion") or 0) != int(n_app):
        raise LcAplicacionError("La línea no pertenece a esa aplicación.")

    conn.execute("BEGIN IMMEDIATE")
    try:
        lc = lc_dict_desde_linea_libro(row)
        res = revertir_salida_desde_lc(conn, lc)
        conn.execute("DELETE FROM libro_campo WHERE id=?", (int(linea_id),))
        conn.commit()
    except Exception as exc:
        _rollback(conn)
        raise LcAplicacionError(f"No se pudo eliminar la línea: {exc}") from exc
    return {"revert": res, "linea_id": linea_id, "producto": row.get("producto")}
