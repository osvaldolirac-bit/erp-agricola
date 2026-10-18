#!/usr/bin/env python3
"""Corrige App 14 El Espino: fecha real 2026-09-26 (libro + salidas bodega + PHI)."""
from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import date, datetime
from pathlib import Path

DB_DEFAULT = "/root/espino/erp_espino.db"
N_APP = 14
FECHA_CORRECTA = "2026-09-26"
MOV_IDS = (101, 102, 103, 104, 105)


def _shift_viable(fecha_app_old: str, fecha_viable: str, fecha_app_new: str) -> str:
    try:
        d0 = date.fromisoformat(str(fecha_app_old)[:10])
        dv = date.fromisoformat(str(fecha_viable)[:10])
        dn = date.fromisoformat(str(fecha_app_new)[:10])
        delta = (dn - d0).days
        return (dv.fromordinal(dv.toordinal() + delta)).isoformat()
    except ValueError:
        return str(fecha_viable or "")[:10]


def run(db_path: str, *, apply: bool) -> None:
    path = Path(db_path)
    if not path.is_file():
        raise SystemExit(f"No existe DB: {path}")

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        lc = conn.execute(
            "SELECT id, n_aplicacion, fecha, sector, producto, gasto_total, fecha_viable "
            "FROM libro_campo WHERE n_aplicacion=? ORDER BY id",
            (N_APP,),
        ).fetchall()
        if len(lc) != 5:
            raise SystemExit(f"Se esperaban 5 líneas App {N_APP}, hay {len(lc)}")

        movs = conn.execute(
            f"""SELECT m.id, m.fecha, m.centro_costo, i.producto, m.cantidad
                FROM movimientos m JOIN inventario i ON i.id=m.producto_id
                WHERE m.id IN ({",".join("?" * len(MOV_IDS))})
                ORDER BY m.id""",
            MOV_IDS,
        ).fetchall()
        if len(movs) != 5:
            raise SystemExit(f"Se esperaban 5 movimientos {MOV_IDS}, hay {len(movs)}")

        by_prod = {str(r["producto"]).upper(): r for r in lc}
        for m in movs:
            prod = str(m["producto"]).upper()
            line = by_prod.get(prod)
            if not line:
                raise SystemExit(f"Mov {m['id']} producto {m['producto']} sin línea LC")
            if abs(float(m["cantidad"]) - float(line["gasto_total"])) > 1e-4:
                raise SystemExit(
                    f"Cantidad distinta mov {m['id']} vs LC {line['id']}: "
                    f"{m['cantidad']} vs {line['gasto_total']}"
                )
            sector = str(line["sector"] or "").strip().upper()
            cc = str(m["centro_costo"] or "").strip().upper()
            if sector != cc:
                print(f"  Ajuste CC mov {m['id']}: {m['centro_costo']} → {line['sector']}")

        print(f"App {N_APP}: fecha {lc[0]['fecha']} → {FECHA_CORRECTA}, sector {lc[0]['sector']}")
        for r in lc:
            nv = _shift_viable(str(r["fecha"]), str(r["fecha_viable"]), FECHA_CORRECTA)
            print(f"  LC id={r['id']} {r['producto']}: viable {r['fecha_viable']} → {nv}")
        for m in movs:
            print(f"  Mov {m['id']} {m['producto']}: {m['fecha']} → {FECHA_CORRECTA}, CC={m['centro_costo']}")

        if not apply:
            print("\nSimulación (--apply para escribir).")
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = path.with_suffix(path.suffix + f".bak_app14_{ts}")
        shutil.copy2(path, backup)
        print(f"Backup: {backup}")

        for r in lc:
            nv = _shift_viable(str(r["fecha"]), str(r["fecha_viable"]), FECHA_CORRECTA)
            conn.execute(
                "UPDATE libro_campo SET fecha=?, fecha_viable=? WHERE id=?",
                (FECHA_CORRECTA, nv, int(r["id"])),
            )

        for m in movs:
            line = by_prod[str(m["producto"]).upper()]
            conn.execute(
                "UPDATE movimientos SET fecha=?, centro_costo=? WHERE id=?",
                (FECHA_CORRECTA, str(line["sector"]).strip(), int(m["id"])),
            )

        conn.execute(
            "INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)",
            (
                "repair_script",
                "REPARACION APP14 FECHA",
                f"App N°{N_APP} libro+bodega → {FECHA_CORRECTA} (sector SANTINA)",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        conn.commit()
        print("OK — cambios aplicados.")
    finally:
        conn.close()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=DB_DEFAULT)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    run(args.db, apply=args.apply)


if __name__ == "__main__":
    main()
