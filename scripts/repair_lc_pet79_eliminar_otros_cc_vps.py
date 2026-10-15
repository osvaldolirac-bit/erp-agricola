#!/usr/bin/env python3
"""LC: PET-79 → CIRUELOS; redistribuye imputaciones OTROS (prorrateo 5 CC); quita OTROS del maestro en app_concepcion."""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB = Path(os.environ.get("ERP_LC_DB", "/root/erp_concepcion_v6.db"))
APP = Path(os.environ.get("LC_APP_CONCEPCION", "/root/demo-web/app_concepcion.py"))
TARGET_CCS = [
    "CEREZOS CORTE 1",
    "CEREZOS CORTE 2",
    "CIRUELOS",
    "NOGALES APARICION",
    "NOGALES CRUZ DEL SUR",
]


def load_weights(conn: sqlite3.Connection) -> dict[str, float]:
    rows = conn.execute(
        "SELECT centro_costo, porcentaje FROM prorrateo_cc ORDER BY centro_costo"
    ).fetchall()
    raw = {str(r[0]).upper(): float(r[1] or 0) for r in rows if r[0]}
    raw = {k: v for k, v in raw.items() if k in TARGET_CCS and v > 0}
    if not raw:
        raw = {
            "CEREZOS CORTE 1": 7.94,
            "CEREZOS CORTE 2": 7.94,
            "CIRUELOS": 32.71,
            "NOGALES APARICION": 32.71,
            "NOGALES CRUZ DEL SUR": 18.70,
        }
    total = sum(raw.values())
    return {k: v / total for k, v in raw.items()}


def split_proportional(total: float, weights: dict[str, float]) -> list[tuple[str, float]]:
    if total <= 0:
        return [(cc, 0.0) for cc in TARGET_CCS]
    keys = [c for c in TARGET_CCS if weights.get(c, 0) > 0]
    parts: list[tuple[str, float]] = []
    allocated = 0.0
    for i, cc in enumerate(keys):
        w = weights[cc]
        if i == len(keys) - 1:
            parte = round(total - allocated, 6)
        else:
            parte = round(total * w, 6)
            allocated += parte
        parts.append((cc, parte))
    return parts


def backup_db() -> Path:
    dest_dir = DB.parent / "backups"
    dest_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = dest_dir / f"erp_concepcion_v6_pre_otros_repair_{stamp}.db"
    shutil.copy2(DB, dest)
    return dest


def patch_app_concepcion() -> bool:
    if not APP.is_file():
        print(f"SKIP app patch: no {APP}")
        return False
    text = APP.read_text(encoding="utf-8")
    orig = text
    text = text.replace(
        'CENTROS_COSTO = ["CEREZOS CORTE 1", "CEREZOS CORTE 2", "CIRUELOS", "NOGALES APARICION", "NOGALES CRUZ DEL SUR", "EL ESPINO", "OTROS"]',
        'CENTROS_COSTO = ["CEREZOS CORTE 1", "CEREZOS CORTE 2", "CIRUELOS", "NOGALES APARICION", "NOGALES CRUZ DEL SUR", "EL ESPINO"]',
    )
    text = text.replace(
        'CUARTELES_IMPUTACION_DIRECTA = ["EL ESPINO", "OTROS"]',
        'CUARTELES_IMPUTACION_DIRECTA = ["EL ESPINO"]',
    )
    text = text.replace(
        '"NOGALES APARICION", "NOGALES CRUZ DEL SUR", "OTROS",\n]',
        '"NOGALES APARICION", "NOGALES CRUZ DEL SUR",\n]',
    )
    text = text.replace('"cc": "OTROS",\n            "resp": "Certificación"', '"cc": "CIRUELOS",\n            "resp": "Certificación"')
    text = text.replace('"cc": "OTROS",\n            "resp": "Taller"', '"cc": "CEREZOS CORTE 1",\n            "resp": "Taller"')
    text = re.sub(
        r"return GAP_ESPECIE_CUARTELES\.get\(especie, \[\]\) \+ \[\"OTROS\"\]",
        "return GAP_ESPECIE_CUARTELES.get(especie, [])",
        text,
    )
    if text == orig:
        print("app_concepcion: sin cambios (ya parcheado?)")
        return False
    bak = APP.with_suffix(f".py.bak_otros_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(APP, bak)
    APP.write_text(text, encoding="utf-8")
    print(f"app_concepcion parcheado; backup {bak}")
    return True


def repair_db(conn: sqlite3.Connection) -> None:
    weights = load_weights(conn)
    huerto_cinco = ", ".join(TARGET_CCS)

    # --- PET-79 → CIRUELOS ---
    conn.execute(
        "UPDATE petroleo_bitacora SET huerto=? WHERE codigo='PET-79'",
        ("CIRUELOS",),
    )
    conn.execute(
        "UPDATE petroleo SET centro_costo='CIRUELOS' WHERE bitacora_codigo='PET-79' OR id=290"
    )

    # --- PET-37: reparto 5 CC ---
    conn.row_factory = sqlite3.Row
    row37 = conn.execute(
        "SELECT * FROM petroleo WHERE id=213 OR bitacora_codigo='PET-37' LIMIT 1"
    ).fetchone()
    if row37:
        base = dict(row37)
        conn.execute("DELETE FROM petroleo WHERE id=?", (base["id"],))
        litros_tot = float(base.get("litros") or 0)
        valor_tot = float(base.get("valor_imputado") or 0)
        for cc, lit in split_proportional(litros_tot, weights):
            val = round(valor_tot * (lit / litros_tot), 6) if litros_tot else 0.0
            conn.execute(
                """INSERT INTO petroleo
                   (tipo, litros, proveedor, monto_total_compra, vehiculo, responsable,
                    centro_costo, fecha, valor_imputado, bitacora_codigo)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    base.get("tipo"),
                    lit,
                    base.get("proveedor"),
                    base.get("monto_total_compra"),
                    base.get("vehiculo"),
                    base.get("responsable"),
                    cc,
                    base.get("fecha"),
                    val,
                    base.get("bitacora_codigo"),
                ),
            )
    conn.execute(
        "UPDATE petroleo_bitacora SET huerto=? WHERE codigo='PET-37'",
        (huerto_cinco,),
    )

    # --- Facturas _P con OTROS ---
    otros_fact = conn.execute(
        """SELECT * FROM facturas
           WHERE UPPER(TRIM(centro_costo))='OTROS' AND nro_documento LIKE '%_P'"""
    ).fetchall()
    for row in otros_fact:
        f = dict(row)
        fid = f["id"]
        doc_p = f["nro_documento"]
        doc_base = doc_p.replace("_P", "")
        siblings = conn.execute(
            "SELECT id, centro_costo, monto_imputado FROM facturas WHERE nro_documento=?",
            (doc_p,),
        ).fetchall()
        if len(siblings) > 1:
            total_net = sum(float(s[2] or 0) for s in siblings)
            conn.execute(
                "DELETE FROM facturas WHERE nro_documento=? AND UPPER(TRIM(centro_costo))!='OTROS'",
                (doc_p,),
            )
        else:
            total_net = float(f.get("monto_imputado") or 0)
        conn.execute("DELETE FROM facturas WHERE id=?", (fid,))
        for cc, parte in split_proportional(total_net, weights):
            conn.execute(
                """INSERT INTO facturas
                   (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo,
                    concepto, razon_social, tipo_gasto, centro_costo, monto_imputado,
                    monto_pagado, banco, folio_interno, imputar_bruto, estado)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    doc_p,
                    f.get("proveedor"),
                    f.get("fecha_compra"),
                    f.get("fecha_vencimiento"),
                    0,
                    f.get("tipo"),
                    f.get("concepto"),
                    f.get("razon_social"),
                    f.get("tipo_gasto"),
                    cc,
                    parte,
                    f.get("monto_pagado") or 0,
                    f.get("banco") or "",
                    f.get("folio_interno") or "",
                    f.get("imputar_bruto", 1),
                    f.get("estado") or "Pendiente",
                ),
            )
        print(f"factura {doc_base}: {total_net:.2f} → 5 CC")

    # --- Maestras costos / flujo (OTROS vacíos) ---
    conn.execute("DELETE FROM costos_kg_estimado_temporada WHERE UPPER(centro_costo)='OTROS'")
    conn.execute("DELETE FROM costos_ppto_temporada WHERE UPPER(centro_costo)='OTROS'")
    conn.execute("DELETE FROM flujo_ingresos_cc WHERE UPPER(centro_costo)='OTROS'")

    # --- Gantt en BD ---
    conn.execute(
        "UPDATE gantt_proyectos SET centro_costo='CIRUELOS' WHERE nombre='Certificación GlobalGAP' AND UPPER(centro_costo)='OTROS'"
    )
    conn.execute(
        "UPDATE gantt_proyectos SET centro_costo='CEREZOS CORTE 1' WHERE nombre='Mantención Maquinaria' AND UPPER(centro_costo)='OTROS'"
    )

    # --- Bitácora petróleo: limpiar OTROS en rechazados / listas ---
    for rid, huerto in conn.execute(
        "SELECT id, huerto FROM petroleo_bitacora WHERE UPPER(huerto) LIKE '%OTROS%'"
    ):
        h = str(huerto or "")
        parts = [p.strip() for p in h.split(",") if p.strip()]
        parts = [p for p in parts if p.upper() != "OTROS"]
        if not parts and h.strip().upper() == "OTROS":
            parts = ["CIRUELOS"]
        new_h = ", ".join(parts) if parts else h
        conn.execute("UPDATE petroleo_bitacora SET huerto=? WHERE id=?", (new_h, rid))


def verify(conn: sqlite3.Connection) -> None:
    n = conn.execute(
        "SELECT COUNT(*) FROM petroleo WHERE UPPER(TRIM(centro_costo))='OTROS'"
    ).fetchone()[0]
    nf = conn.execute(
        "SELECT COUNT(*) FROM facturas WHERE UPPER(TRIM(centro_costo))='OTROS'"
    ).fetchone()[0]
    p79 = conn.execute(
        "SELECT huerto FROM petroleo_bitacora WHERE codigo='PET-79'"
    ).fetchone()
    p79p = conn.execute(
        "SELECT centro_costo, litros FROM petroleo WHERE bitacora_codigo='PET-79'"
    ).fetchall()
    print("verify petroleo OTROS:", n, "facturas OTROS:", nf, "PET-79 bitácora:", p79, "petroleo:", p79p)


def main() -> int:
    if not DB.is_file():
        print(f"No existe DB {DB}", file=sys.stderr)
        return 1
    bak = backup_db()
    print("backup:", bak)
    conn = sqlite3.connect(DB)
    try:
        conn.execute("BEGIN")
        repair_db(conn)
        conn.commit()
        verify(conn)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    patch_app_concepcion()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
