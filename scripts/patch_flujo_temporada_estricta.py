#!/usr/bin/env python3
"""Flujo: usar solo fi–ff de temporada en resumen de costos (sin pre-temporada)."""
from pathlib import Path

OLD = '''def _resumen_costos_para_flujo(conn, temporada, fi, ff):
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

NEW = '''def _resumen_costos_para_flujo(conn, temporada, fi, ff):
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


def main() -> None:
    for path in ("/root/demo-web/app_concepcion.py", "/root/demo-web/app_demo.py"):
        p = Path(path)
        t = p.read_text()
        if OLD not in t:
            print(path, "BLOCK NOT FOUND")
            idx = t.find("def _resumen_costos_para_flujo")
            print(repr(t[idx : idx + 450]))
            continue
        p.write_text(t.replace(OLD, NEW))
        print(path, "OK")


if __name__ == "__main__":
    main()
