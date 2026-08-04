#!/usr/bin/env python3
from pathlib import Path

OLD = '''def _resumen_costos_para_flujo(conn, temporada, fi, ff):
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

NEW = '''def _resumen_costos_para_flujo(conn, temporada, fi, ff):
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

p = Path("/root/demo-web/app_demo.py")
t = p.read_text()
if OLD not in t:
    idx = t.find("def _resumen_costos_para_flujo")
    print("NOT FOUND")
    print(repr(t[idx : idx + 600]))
else:
    p.write_text(t.replace(OLD, NEW))
    print("OK demo")
