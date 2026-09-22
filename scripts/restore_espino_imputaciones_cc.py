#!/usr/bin/env python3
"""DEPRECATED — no usar en producción.

La redistribución correcta es en runtime vía demo_web/services/espino_costos.py
(bucket CEREZOS en matriz → prorrateo a variedades). Modificar filas _P en BD
duplica/confunde datos GE-* y no alinea Costos con Dashboard.

Script conservado solo como referencia histórica.
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

PRORRATEO: dict[str, float] = {
    "SANTINA": 64.28,
    "ROYAL DOWN": 21.43,
    "SWEET ARYANA": 14.29,
}
LEGACY_CC = frozenset({"CEREZOS", "EL ESPINO"})

INSERT_COLS = (
    "nro_documento, proveedor, fecha_compra, fecha_vencimiento, "
    "monto_neto, monto_total, estado, tipo, metodo_pago, fecha_pago, "
    "concepto, centro_costo, monto_imputado, razon_social, tipo_gasto, "
    "contratista_id, monto_pagado, banco, folio_interno, imputar_bruto"
)


def _split_monto(total: float) -> list[tuple[str, float]]:
    items = list(PRORRATEO.items())
    acc = 0.0
    out: list[tuple[str, float]] = []
    for i, (cc, pct) in enumerate(items):
        if i == len(items) - 1:
            part = round(total - acc, 2)
        else:
            part = round(total * pct / 100.0, 2)
            acc += part
        if part > 0.01:
            out.append((cc, part))
    return out


def restore(db_path: Path, *, dry_run: bool = False) -> dict[str, int]:
    if not db_path.is_file():
        raise SystemExit(f"No existe BD: {db_path}")

    if not dry_run:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = db_path.with_name(f"{db_path.name}.bak-restore-cc-{ts}")
        shutil.copy2(db_path, bak)
        print(f"Backup: {bak}")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    rows = cur.execute(
        f"""
        SELECT id, {INSERT_COLS}
        FROM facturas
        WHERE nro_documento LIKE '%_P'
          AND UPPER(TRIM(COALESCE(centro_costo, ''))) IN ('CEREZOS', 'EL ESPINO')
        """
    ).fetchall()

    inserted = deleted = 0
    if not dry_run:
        cur.execute("BEGIN IMMEDIATE")

    for row in rows:
        rid = row[0]
        vals = list(row[1:])
        monto_imp = float(vals[12] or 0)
        if monto_imp <= 0.01:
            continue
        for cc, part in _split_monto(monto_imp):
            new_vals = list(vals)
            new_vals[11] = cc
            new_vals[12] = part
            if not dry_run:
                cur.execute(
                    f"INSERT INTO facturas ({INSERT_COLS}) VALUES ({','.join('?' * 20)})",
                    new_vals,
                )
            inserted += 1
        if not dry_run:
            cur.execute("DELETE FROM facturas WHERE id=?", (rid,))
        deleted += 1

    if not dry_run:
        conn.commit()
    conn.close()
    return {"legacy_rows": len(rows), "deleted": deleted, "inserted": inserted}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default="/root/espino/erp_espino.db")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    stats = restore(Path(args.db), dry_run=args.dry_run)
    print(stats)


if __name__ == "__main__":
    main()
