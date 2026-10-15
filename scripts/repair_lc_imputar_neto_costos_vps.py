#!/usr/bin/env python3
"""LC: respeta imputación neto en Costos (imputar_bruto) y corrige históricos mal escalados."""
from __future__ import annotations

import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB = Path("/root/erp_concepcion_v6.db")
APP = Path("/root/demo-web/app_concepcion.py")
IVA = 1.19


def backup_db() -> Path:
    dest_dir = DB.parent / "backups"
    dest_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = dest_dir / f"erp_concepcion_v6_pre_imputar_neto_{stamp}.db"
    shutil.copy2(DB, dest)
    return dest


def _es_neto(bruto: float, sum_imp: float) -> bool:
    if bruto <= 0 or sum_imp <= 0:
        return False
    net = bruto / IVA
    tol = max(3.0, bruto * 0.003)
    return abs(sum_imp - net) <= tol and abs(sum_imp - bruto) > tol


def repair_imputar_bruto_flags(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT f.id, f.nro_documento, f.proveedor, f.monto_total,
               SUM(p.monto_imputado) AS sum_imp
        FROM facturas f
        JOIN facturas p
          ON p.nro_documento = f.nro_documento || '_P'
         AND p.proveedor = f.proveedor
        WHERE f.monto_total > 0
          AND f.nro_documento NOT LIKE '%_P'
        GROUP BY f.id
        HAVING sum_imp > 0.01
        """
    ).fetchall()
    n = 0
    for fid, doc, prov, bruto, sum_imp in rows:
        bruto_f = float(bruto or 0)
        sum_f = float(sum_imp or 0)
        if not _es_neto(bruto_f, sum_f):
            continue
        conn.execute("UPDATE facturas SET imputar_bruto=0 WHERE id=?", (fid,))
        conn.execute(
            """
            UPDATE facturas SET imputar_bruto=0
            WHERE nro_documento=? AND proveedor=?
            """,
            (str(doc) + "_P", prov),
        )
        n += 1
    return n


def patch_app_concepcion() -> bool:
    if not APP.is_file():
        print("SKIP: no app_concepcion.py")
        return False
    text = APP.read_text(encoding="utf-8")
    old = '''        SELECT p.nro_documento, p.proveedor,
               MAX(f.monto_total) AS bruto,
               SUM(COALESCE(p.monto_imputado, 0)) AS imp
        FROM facturas p
        {sql_join_parent_imputacion('p', 'f')}
        WHERE 1=1
          {sql_filtro_imputacion_en_historial('p', 'f')}
          {filtro}
        GROUP BY p.nro_documento, p.proveedor
        """,
        params,
    ).fetchall()
    out = {}
    for nro_p, prov, bruto, imp in rows:
        imp_f = float(imp or 0)
        bruto_f = float(bruto or 0)
        out[(str(nro_p or ""), str(prov or ""))] = (bruto_f / imp_f) if imp_f > 0.01 and bruto_f > 0.01 else 1.0
    return out'''
    new = '''        SELECT p.nro_documento, p.proveedor,
               MAX(f.monto_total) AS bruto,
               SUM(COALESCE(p.monto_imputado, 0)) AS imp,
               MAX(COALESCE(f.imputar_bruto, 1)) AS imputar_bruto
        FROM facturas p
        {sql_join_parent_imputacion('p', 'f')}
        WHERE 1=1
          {sql_filtro_imputacion_en_historial('p', 'f')}
          {filtro}
        GROUP BY p.nro_documento, p.proveedor
        """,
        params,
    ).fetchall()
    out = {}
    for nro_p, prov, bruto, imp, imputar_bruto in rows:
        imp_f = float(imp or 0)
        bruto_f = float(bruto or 0)
        key = (str(nro_p or ""), str(prov or ""))
        if int(imputar_bruto or 0) == 0:
            out[key] = 1.0
            continue
        out[key] = (bruto_f / imp_f) if imp_f > 0.01 and bruto_f > 0.01 else 1.0
    return out'''
    if old not in text:
        if "imputar_bruto in rows" in text or "MAX(COALESCE(f.imputar_bruto" in text:
            print("app_concepcion: factor neto ya parcheado")
            return False
        print("app_concepcion: bloque _factores no encontrado", file=sys.stderr)
        return False
    bak = APP.with_suffix(f".py.bak_imputar_neto_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(APP, bak)
    APP.write_text(text.replace(old, new), encoding="utf-8")
    print("app_concepcion parcheado; backup", bak)
    return True


def patch_streamlit_gasto_insert() -> bool:
    """Persistir imputar_bruto en formulario Streamlit legacy (gv_form)."""
    text = APP.read_text(encoding="utf-8")
    if "imputar_bruto_gv" in text:
        return False
    old = "                        imp = mt if iva == \"SI\" else mt / 1.19\n                        reparto, err_cc = _reparto_por_cc(conn, imp, selcc)"
    new = (
        "                        imp = mt if iva == \"SI\" else mt / 1.19\n"
        "                        imputar_bruto_gv = 1 if iva == \"SI\" else 0\n"
        "                        reparto, err_cc = _reparto_por_cc(conn, imp, selcc)"
    )
    if old not in text:
        print("streamlit gv_form: bloque imp no encontrado")
        return False
    text = text.replace(old, new)
    old_ins_f = (
        '                                "INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, concepto, razon_social, tipo_gasto) VALUES (?,?,?,?,?,?,?,?,?)",\n'
        '                                (ng_final, pg, str(fg1), str(fg2), mt, tipo_gv, concepto_det.strip(), razon_gv, tg_gv),\n'
    )
    new_ins_f = (
        '                                "INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, concepto, razon_social, tipo_gasto, imputar_bruto) VALUES (?,?,?,?,?,?,?,?,?,?)",\n'
        '                                (ng_final, pg, str(fg1), str(fg2), mt, tipo_gv, concepto_det.strip(), razon_gv, tg_gv, imputar_bruto_gv),\n'
    )
    if old_ins_f not in text:
        print("streamlit gv_form: INSERT parent no encontrado")
        return False
    text = text.replace(old_ins_f, new_ins_f)
    old_ins_p = (
        '                                    "INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, centro_costo, monto_imputado, concepto, razon_social, tipo_gasto) VALUES (?,?,?,?,?,?,?,?,?,?,?)",\n'
        '                                    (ng_final + "_P", pg, str(fg1), str(fg2), 0, tipo_gv, c.upper(), parte, concepto_det.strip(), razon_gv, tg_gv),\n'
    )
    new_ins_p = (
        '                                    "INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, centro_costo, monto_imputado, concepto, razon_social, tipo_gasto, imputar_bruto) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",\n'
        '                                    (ng_final + "_P", pg, str(fg1), str(fg2), 0, tipo_gv, c.upper(), parte, concepto_det.strip(), razon_gv, tg_gv, imputar_bruto_gv),\n'
    )
    if old_ins_p not in text:
        print("streamlit gv_form: INSERT _P no encontrado")
        return False
    APP.write_text(text.replace(old_ins_p, new_ins_p), encoding="utf-8")
    print("streamlit gv_form: imputar_bruto persistido")
    return True


def verify_lechera(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        """
        SELECT f.imputar_bruto, p.monto_imputado, f.monto_total
        FROM facturas f
        JOIN facturas p ON p.nro_documento=f.nro_documento||'_P' AND p.proveedor=f.proveedor
        WHERE f.nro_documento='2686007' AND p.centro_costo LIKE '%CORTE 2%'
        """
    ).fetchone()
    print("2686007 LECHERA:", row)


def main() -> int:
    if not DB.is_file():
        print("No DB", file=sys.stderr)
        return 1
    print("backup:", backup_db())
    conn = sqlite3.connect(DB)
    try:
        conn.execute("BEGIN")
        n = repair_imputar_bruto_flags(conn)
        conn.commit()
        print("documentos marcados imputar_bruto=0 (neto):", n)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    patch_app_concepcion()
    patch_streamlit_gasto_insert()
    conn = sqlite3.connect(DB)
    verify_lechera(conn)
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
