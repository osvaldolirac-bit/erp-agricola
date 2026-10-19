#!/usr/bin/env python3
"""Restaura App N° 20 en libro_campo si fue eliminada del historial."""
from __future__ import annotations

import sqlite3

DB = "/root/erp_concepcion_v6.db"
N_APP = 20

COLS = (
    "id, fecha, n_orden, sector, est_fenologico, especie, motivo, producto, n_aplicacion,"
    " ingrediente, dosis, unidad_dosis, vol_total, gasto_total, unidad_gasto, tractor, maquina,"
    " aplicadores, car_etiqueta, car_agenda, car_mayor, fecha_viable, lote_producto,"
    " operador_certificado, variedad, n_aplicacion_txt, t_max, t_min, hr_pct, viento_kmh"
)

ROWS = [
    (
        149,
        "2026-09-17",
        "50",
        "CIRUELOS",
        None,
        "Ciruelos",
        "Control fitosanitario",
        "BRASSTEC",
        20,
        "Bioestimulante brassinosteroide",
        80.0,
        "Centímetros Cúbicos (cc)",
        1500.0,
        8.4,
        "lt",
        "TRAC-MF",
        "NEB-02",
        "JUAN SALAS",
        1,
        None,
        1,
        "2026-09-18",
        "",
        0,
        "D'Agen",
        "1 de 2",
        25.9,
        13.7,
        51.0,
        10.2,
    ),
    (
        150,
        "2026-09-17",
        "50",
        "CIRUELOS",
        None,
        "Ciruelos",
        "Control fitosanitario",
        "EVOLUTION FIFTY",
        20,
        "Bioestimulante Ascophillium",
        100.0,
        "Centímetros Cúbicos (cc)",
        1500.0,
        10.5,
        "lt",
        "TRAC-MF",
        "NEB-02",
        "JUAN SALAS",
        7,
        None,
        7,
        "2026-09-24",
        "",
        0,
        "D'Agen",
        "2 de 2",
        25.9,
        13.7,
        51.0,
        10.2,
    ),
]


def main() -> None:
    conn = sqlite3.connect(DB)
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM libro_campo WHERE n_aplicacion=?", (N_APP,)
        ).fetchone()[0]
        if n:
            print(f"OK — App N° {N_APP} ya tiene {n} línea(s).")
            return
        ph = ",".join("?" * len(ROWS[0]))
        sql = f"INSERT INTO libro_campo ({COLS}) VALUES ({ph})"
        for row in ROWS:
            rid = row[0]
            if conn.execute("SELECT 1 FROM libro_campo WHERE id=?", (rid,)).fetchone():
                row_no_id = row[1:]
                sql2 = (
                    "INSERT INTO libro_campo (fecha, n_orden, sector, est_fenologico, especie, "
                    "motivo, producto, n_aplicacion, ingrediente, dosis, unidad_dosis, vol_total, "
                    "gasto_total, unidad_gasto, tractor, maquina, aplicadores, car_etiqueta, "
                    "car_agenda, car_mayor, fecha_viable, lote_producto, operador_certificado, "
                    "variedad, n_aplicacion_txt, t_max, t_min, hr_pct, viento_kmh) "
                    f"VALUES ({','.join('?' * len(row_no_id))})"
                )
                conn.execute(sql2, row_no_id)
            else:
                conn.execute(sql, row)
        conn.commit()
        print(f"Restauradas {len(ROWS)} líneas — App N° {N_APP}.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
