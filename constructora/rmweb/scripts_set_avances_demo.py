#!/usr/bin/env python3
"""Aprueba obras demo y asigna avances Gantt con % distintos."""
from __future__ import annotations

import sqlite3

from rmweb import constructora as cst
from rmweb import obra_contrato as obractx

DB = "/root/constructora/data/constructora_demo.db"

PERFILES = {
    # Los Arrayanes — avanzada
    33: {"base": 72.0, "inicio": 100.0, "fin": 35.0, "jitter": (5, -8, 12, -3, 0)},
    # El Mirador — temprana
    34: {"base": 28.0, "inicio": 55.0, "fin": 5.0, "jitter": (8, -5, 3, -10, 0)},
}


def pct_for(i: int, n: int, perfil: dict) -> float:
    t = 0.0 if n <= 1 else i / (n - 1)
    curva = perfil["inicio"] * (1 - t) + perfil["fin"] * t
    val = 0.55 * curva + 0.45 * perfil["base"]
    val += perfil["jitter"][i % len(perfil["jitter"])]
    return max(0.0, min(100.0, round(val, 1)))


def fix_sin_apu(c, oid: int) -> int:
    """Partidas valorizables sin PU → marca a_definir para poder aprobar."""
    n = 0
    for p in obractx.list_partidas(c, oid):
        if not obractx.linea_requiere_apu(p):
            continue
        pu = float(p["apu_pu"] or p["pu_neto"] or 0)
        if p["apu_id"] and pu > 0:
            continue
        if pu > 0 and p["apu_id"]:
            continue
        # sin precio real en ppto
        c.execute(
            """
            UPDATE obra_partidas
            SET marca='a_definir', pu_neto=0, total=0
            WHERE id=? AND centro_costo_id=?
            """,
            (int(p["id"]), oid),
        )
        n += 1
    return n


def main():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    cst.ensure_constructora_schema(c)
    obractx.ensure_obra_contrato_schema(c)

    obras = c.execute(
        "SELECT id, nombre FROM centros_costo WHERE COALESCE(tipo,'')='obra' ORDER BY id"
    ).fetchall()
    for ob in obras:
        oid = int(ob["id"])
        perfil = PERFILES.get(oid) or (
            PERFILES[33] if oid % 2 else PERFILES[34]
        )

        fixed = fix_sin_apu(c, oid)
        if fixed:
            print(f"[{oid}] marcadas a_definir (sin PU): {fixed}")

        if not obractx.obra_cotizacion_aprobada(c, oid):
            ok, msg = obractx.aprobar_cotizacion_obra(c, oid)
            print(f"[{oid}] aprobar:", ok, msg)
            if not ok:
                c.rollback()
                continue
        else:
            print(f"[{oid}] ya aprobada")

        parts = [
            p
            for p in obractx.list_partidas(c, oid)
            if obractx.linea_requiere_apu(p) and float(p["total"] or 0) > 0
        ]
        avances = [
            {"partida_id": int(p["id"]), "avance_pct": pct_for(i, len(parts), perfil)}
            for i, p in enumerate(parts)
        ]
        ok, msg = obractx.guardar_avances_gantt(c, oid, avances)
        print(f"[{oid}] {ob['nombre'][:48]}: {msg}")

        # evitar EEPP duplicados si se re-ejecuta
        already = c.execute(
            "SELECT COUNT(*) n FROM obra_eepp WHERE centro_costo_id=?", (oid,)
        ).fetchone()["n"]
        if int(already or 0) == 0:
            ok, msg, eid = obractx.generar_eepp_desde_gantt(
                c, oid, notas="EEPP demo automático según Gantt"
            )
            print(f"[{oid}] eepp:", ok, msg)
        else:
            print(f"[{oid}] eepp: ya existe ({already})")

        res = obractx.resumen_avance_obra(c, oid)
        print(
            f"[{oid}] avance ponderado {res['avance_pct_pond']}% · "
            f"avanzado ${res['avanzado_clp']:,.0f}".replace(",", ".")
        )
        c.commit()

    c.close()


if __name__ == "__main__":
    main()
