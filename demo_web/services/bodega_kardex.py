"""Cuenta corriente bodega (kardex por producto) — tenant genérico LC."""
from __future__ import annotations

import sqlite3

from flask import url_for

from demo_web.services.espino_compras_kardex import origen_compra_ingreso
from demo_web.services.module_runner import store_pdf
from demo_web.services.tenant_scope import centros_costo

ETIQUETA_BODEGA = "BODEGA"


def _pdf_filename_producto(nombre: str, prefix: str = "KARDEX") -> str:
    safe = "".join(c if c.isalnum() else "_" for c in (nombre or "PRODUCTO").upper())
    while "__" in safe:
        safe = safe.replace("__", "_")
    return f"{prefix}_{safe.strip('_')[:48]}.pdf"


def _normalize_tipo_mov(tipo: str) -> str:
    t = (tipo or "").strip().lower()
    if t.startswith("ing") or t.startswith("entr"):
        return "Ingreso"
    if t.startswith("sal"):
        return "Salida"
    return (tipo or "").strip() or "Salida"


def _lc_lineas_producto(conn, producto: str) -> list[dict]:
    rows = conn.execute(
        """SELECT n_aplicacion, fecha, sector, gasto_total
           FROM libro_campo WHERE UPPER(TRIM(producto))=?
           ORDER BY CAST(n_aplicacion AS INTEGER), id""",
        (producto.upper().strip(),),
    ).fetchall()
    return [
        {
            "n_app": int(r[0] or 0),
            "fecha": str(r[1] or ""),
            "sector": str(r[2] or ""),
            "gasto": float(r[3] or 0),
            "_used": False,
        }
        for r in rows
    ]


def _sector_coincide(sector: str, centro_costo: str, cuarteles: set[str]) -> bool:
    sec_u = (sector or "").strip().upper()
    cc_u = (centro_costo or "").strip().upper()
    if not sec_u or not cc_u:
        return False
    if sec_u == cc_u:
        return True
    if sec_u in cuarteles and cc_u in cuarteles and sec_u == cc_u:
        return True
    return sec_u in cc_u or cc_u in sec_u


def _origen_movimiento(
    conn: sqlite3.Connection,
    producto_id: int,
    producto_nombre: str,
    tipo: str,
    cant: float,
    fecha: str,
    centro_costo: str,
    lc_lineas: list[dict],
    cuarteles: set[str],
) -> str:
    if _normalize_tipo_mov(tipo) == "Ingreso":
        origen = origen_compra_ingreso(conn, producto_id, producto_nombre, cant, fecha)
        if origen:
            return origen
        cc = (centro_costo or "").strip()
        if cc:
            return f"Ingreso manual → {cc}"
        return "Ingreso bodega"
    for lc in lc_lineas:
        if lc.get("_used"):
            continue
        if str(lc["fecha"]) != str(fecha):
            continue
        if abs(float(lc["gasto"]) - cant) > 1e-4:
            continue
        if not _sector_coincide(lc["sector"], centro_costo, cuarteles):
            continue
        lc["_used"] = True
        return f"LC App N° {lc['n_app']:05d}"
    cc = (centro_costo or "").strip() or "—"
    return f"Salida manual → {cc}"


def _kardex_row(
    demo,
    *,
    row_id: int,
    fecha: str,
    tipo: str,
    qty: float,
    cuartel: str,
    origen: str,
    saldo: float,
) -> dict:
    tipo_n = _normalize_tipo_mov(tipo)
    delta = qty if tipo_n == "Ingreso" else -qty
    return {
        "id": row_id,
        "fecha": fecha,
        "tipo": tipo_n,
        "cantidad": demo.f_cantidad(qty),
        "cant_raw": qty,
        "delta_fmt": ("+" if delta >= 0 else "−") + demo.f_cantidad(abs(delta)),
        "cuartel": cuartel,
        "origen": origen,
        "saldo": demo.f_cantidad(saldo),
        "saldo_raw": saldo,
    }


def _recalc_kardex_saldos(demo, rows: list[dict]) -> None:
    saldo = 0.0
    for r in rows:
        delta = r["cant_raw"] if r["tipo"] == "Ingreso" else -r["cant_raw"]
        saldo += delta
        r["saldo"] = demo.f_cantidad(saldo)
        r["saldo_raw"] = saldo


def _build_kardex_rows(
    demo,
    conn: sqlite3.Connection,
    producto_id: int,
    producto_nombre: str,
    movs: list[tuple],
    lc_lineas: list[dict],
    cuarteles: set[str],
    *,
    stock_objetivo: float | None = None,
) -> list[dict]:
    rows: list[dict] = []
    for mid, tipo, cant, fecha, cc in movs:
        tipo_n = _normalize_tipo_mov(str(tipo))
        qty = float(cant or 0)
        rows.append(
            _kardex_row(
                demo,
                row_id=int(mid),
                fecha=str(fecha or ""),
                tipo=tipo_n,
                qty=qty,
                cuartel=(cc or "").strip() or "—",
                origen=_origen_movimiento(
                    conn,
                    producto_id,
                    producto_nombre,
                    str(tipo),
                    qty,
                    str(fecha or ""),
                    str(cc or ""),
                    lc_lineas,
                    cuarteles,
                ),
                saldo=0.0,
            )
        )

    if stock_objetivo is not None:
        ing = sum(r["cant_raw"] for r in rows if r["tipo"] == "Ingreso")
        sal = sum(r["cant_raw"] for r in rows if r["tipo"] == "Salida")
        apertura = float(stock_objetivo) - ing + sal
        if apertura > 1e-6:
            rows.insert(
                0,
                _kardex_row(
                    demo,
                    row_id=0,
                    fecha="—",
                    tipo="Ingreso",
                    qty=apertura,
                    cuartel=ETIQUETA_BODEGA,
                    origen="Stock inicial / apertura",
                    saldo=0.0,
                ),
            )

    _recalc_kardex_saldos(demo, rows)
    return rows


def _pdf_kardex_producto(demo, prod: dict, rows: list[dict]) -> tuple[str | None, str | None]:
    import pandas as pd

    um = prod["um"]
    titulo = (
        f"CUENTA CORRIENTE BODEGA — {prod['nombre']} | "
        f"Stock {prod['stock']} {um} | Ing {prod['ing_total']} {um} | Sal {prod['sal_total']} {um}"
    )
    if rows:
        df = pd.DataFrame(
            [
                {
                    "FECHA": r["fecha"],
                    "TIPO": r["tipo"],
                    "CANTIDAD": r["cant_raw"] if r["tipo"] == "Ingreso" else -r["cant_raw"],
                    "UM": um,
                    "CUARTEL": r["cuartel"],
                    "ORIGEN": r["origen"],
                    "SALDO": r["saldo_raw"],
                }
                for r in rows
            ]
        )
    else:
        df = pd.DataFrame(
            [{"DETALLE": f"Sin movimientos. Stock actual: {prod['stock']} {um}"}]
        )
    fname = _pdf_filename_producto(prod["nombre"])
    blob = demo.generar_pdf_blob(df, titulo, incluir_precios=False)
    if not blob:
        return None, None
    return url_for("modules.pdf_download", token=store_pdf(blob, fname)), fname


def gather_kardex_producto(demo, conn, producto_id: int) -> dict:
    """Libro mayor bodega LC: movimientos + saldo acumulado + enlace LC."""
    row = conn.execute(
        """SELECT id, producto, familia, COALESCE(unidad_medida, ?), COALESCE(stock, 0),
                  COALESCE(ingrediente_activo, '')
           FROM inventario WHERE id=?""",
        (demo.DEFAULT_UNIDAD_INSUMO, producto_id),
    ).fetchone()
    if not row:
        return {"kardex_error": "Producto no encontrado."}

    pid, nombre, familia, um, stock_inv, ing_act = (
        int(row[0]),
        row[1],
        row[2],
        row[3],
        float(row[4] or 0),
        row[5],
    )
    cuarteles = {c.upper() for c in centros_costo(demo)}
    lc_lineas = _lc_lineas_producto(conn, nombre)
    movs = conn.execute(
        """SELECT id, tipo, cantidad, fecha, centro_costo
           FROM movimientos WHERE producto_id=?
           ORDER BY fecha, id""",
        (pid,),
    ).fetchall()

    stock_ui = max(float(stock_inv or 0), 0.0)
    kardex_rows = _build_kardex_rows(
        demo, conn, pid, nombre, movs, lc_lineas, cuarteles, stock_objetivo=stock_ui
    )
    lc_sin_par = [lc for lc in lc_lineas if not lc.get("_used")]

    ing_total = sum(r["cant_raw"] for r in kardex_rows if r["tipo"] == "Ingreso")
    sal_total = sum(r["cant_raw"] for r in kardex_rows if r["tipo"] == "Salida")

    kardex_producto = {
        "id": pid,
        "nombre": nombre,
        "familia": familia,
        "um": um,
        "ing_activo": ing_act,
        "stock": demo.f_cantidad(stock_ui),
        "ing_total": demo.f_cantidad(ing_total),
        "sal_total": demo.f_cantidad(sal_total),
    }
    pdf_kardex_url, pdf_kardex_filename = _pdf_kardex_producto(demo, kardex_producto, kardex_rows)

    return {
        "kardex_producto": kardex_producto,
        "kardex_rows": kardex_rows,
        "pdf_kardex_url": pdf_kardex_url,
        "pdf_kardex_filename": pdf_kardex_filename,
        "kardex_lc_pendientes": [
            {
                "n_app": lc["n_app"],
                "fecha": lc["fecha"],
                "sector": lc["sector"],
                "gasto": demo.f_cantidad(lc["gasto"]),
            }
            for lc in lc_sin_par
        ],
    }
