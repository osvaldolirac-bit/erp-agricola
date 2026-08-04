#!/usr/bin/env python3
"""Revertir resumen Flujo al rango de Costos vigente (incluye pre-temporada)."""
from pathlib import Path

NEW_CONCEPCION = '''def _resumen_costos_para_flujo(conn, temporada, fi, ff):
    """Resumen para Flujo financiero: solo gastos de la temporada (fi–ff).

    El módulo Costos vigente puede incluir movimientos pre-temporada; el Flujo
    no debe cargar esos egresos contra el presupuesto ni el EERR de la temporada.
    """
    prorrateo = cargar_prorrateo_cc(conn)
    matriz = _armar_matriz_costos_vista_b(
        conn, fi, ff, CUARTELES_OFICIALES, prorrateo, temporada,
    )
    return resumen_desde_matriz_costos(matriz, CUARTELES_OFICIALES)
'''

OLD_CONCEPCION = '''def _resumen_costos_para_flujo(conn, temporada, fi, ff):
    """Misma matriz y rango de consulta que el módulo Costos (temporada vigente incluida)."""
    prorrateo = cargar_prorrateo_cc(conn)
    es_vigente = fi <= hoy <= ff
    fi_cons, ff_cons = _rango_fechas_costos_consulta(conn, fi, ff, es_vigente)
    if es_vigente:
        matriz = _armar_matriz_costos_vista_b(
            conn, fi_cons, ff_cons, CUARTELES_OFICIALES, prorrateo, temporada,
            fi_rrhh=fi, ff_rrhh=ff,
        )
    else:
        matriz = _armar_matriz_costos_vista_b(
            conn, fi, ff, CUARTELES_OFICIALES, prorrateo, temporada,
        )
    return resumen_desde_matriz_costos(matriz, CUARTELES_OFICIALES)
'''

NEW_DEMO = '''def _resumen_costos_para_flujo(conn, temporada, fi, ff):
    """Resumen para Flujo financiero: solo gastos de la temporada (fi–ff).

    El módulo Costos vigente puede incluir movimientos pre-temporada; el Flujo
    no debe cargar esos egresos contra el presupuesto ni el EERR de la temporada.
    """
    prorrateo = PRORRATEO_RRHH
    matriz = _armar_matriz_costos_vista_b(
        conn, fi, ff, CUARTELES_OFICIALES, prorrateo, temporada,
    )
    return resumen_desde_matriz_costos(matriz, CUARTELES_OFICIALES)
'''

OLD_DEMO = '''def _resumen_costos_para_flujo(conn, temporada, fi, ff):
    """Misma matriz y rango de consulta que el módulo Costos (temporada vigente incluida)."""
    prorrateo = PRORRATEO_RRHH
    es_vigente = fi <= hoy <= ff
    fi_cons, ff_cons = _rango_fechas_costos_consulta(conn, fi, ff, es_vigente)
    if es_vigente:
        matriz = _armar_matriz_costos_vista_b(
            conn, fi_cons, ff_cons, CUARTELES_OFICIALES, prorrateo, temporada,
            fi_rrhh=fi, ff_rrhh=ff,
        )
    else:
        matriz = _armar_matriz_costos_vista_b(
            conn, fi, ff, CUARTELES_OFICIALES, prorrateo, temporada,
        )
    return resumen_desde_matriz_costos(matriz, CUARTELES_OFICIALES)
'''


def patch(path: str, new: str, old: str) -> None:
    p = Path(path)
    t = p.read_text()
    if new not in t:
        print(path, "CURRENT BLOCK NOT FOUND")
        idx = t.find("def _resumen_costos_para_flujo")
        print(repr(t[idx : idx + 400]))
        return
    p.write_text(t.replace(new, old))
    print(path, "REVERTED")


if __name__ == "__main__":
    patch("/root/demo-web/app_concepcion.py", NEW_CONCEPCION, OLD_CONCEPCION)
    patch("/root/demo-web/app_demo.py", NEW_DEMO, OLD_DEMO)
