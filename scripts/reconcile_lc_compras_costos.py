#!/usr/bin/env python3
"""Reconcilia Compras historial vs Costos para tenant LC."""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "demo-web/erp_concepcion_v6.db")
FI, FF = "2026-05-01", "2027-04-30"
TEMPORADA = "2026-2027"


def q(conn, sql, params=()):
    row = conn.execute(sql, params).fetchone()
    return float(row[0] or 0), int(row[1] or 0) if len(row) > 1 else (float(row[0] or 0), 0)


def main():
    conn = sqlite3.connect(DB)
    print(f"DB: {DB}\n")

    sql_compras = """
        SELECT COALESCE(SUM(monto_total),0), COUNT(*)
        FROM facturas
        WHERE monto_total > 0
          AND nro_documento NOT LIKE '%_P'
          AND UPPER(TRIM(nro_documento)) NOT LIKE 'INT-%'
          AND UPPER(TRIM(nro_documento)) NOT LIKE 'INT/%'
          AND UPPER(TRIM(nro_documento)) NOT GLOB 'GE-*'
          AND TRIM(COALESCE(razon_social, '')) != 'El Espino'
          AND fecha_compra BETWEEN ? AND ?
    """
    total, n = q(conn, sql_compras, (FI, FF))
    print("=== COMPRAS historial (temporada, filtros Flask) ===")
    print(f"Total: ${total:,.0f}  ({n} docs)")

    sql_compras_all = sql_compras.replace("AND fecha_compra BETWEEN ? AND ?", "")
    total_all, n_all = q(conn, sql_compras_all)
    print(f"Total all-time (mismos filtros): ${total_all:,.0f}  ({n_all} docs)")

    rr = conn.execute(
        "SELECT MIN(fecha_compra), MAX(fecha_compra) FROM facturas WHERE monto_total>0 AND nro_documento NOT LIKE '%_P'"
    ).fetchone()
    print(f"Rango fechas parent facturas: {rr[0]} → {rr[1]}")

    print("\n=== COSTOS componentes (temporada) ===")
    b, _ = q(conn, "SELECT COALESCE(SUM(valor_imputado),0),0 FROM movimientos WHERE ABS(COALESCE(valor_imputado,0))>0.01 AND fecha BETWEEN ? AND ?", (FI, FF))
    f, _ = q(conn, """
        SELECT COALESCE(SUM(monto_imputado),0),0 FROM facturas
        WHERE nro_documento LIKE '%_P' AND nro_documento NOT LIKE '%_RRHH'
          AND ABS(COALESCE(monto_imputado,0))>0.01 AND fecha_compra BETWEEN ? AND ?
    """, (FI, FF))
    p, _ = q(conn, "SELECT COALESCE(SUM(valor_imputado),0),0 FROM petroleo WHERE tipo='Salida' AND fecha BETWEEN ? AND ?", (FI, FF))
    a, _ = q(conn, "SELECT COALESCE(SUM(monto),0),0 FROM ajustes_costos WHERE fecha BETWEEN ? AND ?", (FI, FF))
    rrhh, _ = q(conn, """
        SELECT COALESCE(SUM(COALESCE(liquido,0)+COALESCE(leyes_sociales,0)),0),0
        FROM pagos_rrhh
    """)
    for label, val in [
        ("Bodega movimientos", b),
        ("Facturas _P imputado", f),
        ("Petróleo salidas", p),
        ("Ajustes", a),
        ("RRHH liquidaciones", rrhh),
    ]:
        print(f"  {label}: ${val:,.0f}")
    print(f"  Suma (sin prorrateo RRHH aplicado): ${b+f+p+a+rrhh:,.0f}")

    fmin = conn.execute("""
        SELECT MIN(f) FROM (
          SELECT MIN(fecha) f FROM movimientos WHERE ABS(COALESCE(valor_imputado,0))>0.01
          UNION SELECT MIN(fecha_compra) f FROM facturas WHERE nro_documento LIKE '%_P'
          UNION SELECT MIN(fecha) f FROM petroleo WHERE tipo='Salida'
          UNION SELECT MIN(fecha) f FROM ajustes_costos
        ) WHERE f IS NOT NULL
    """).fetchone()[0]
    fi_ext = fmin if fmin and fmin < FI else FI
    print(f"\nRango extendido costos vigente: {fi_ext} → {FF}")

    b2, _ = q(conn, "SELECT COALESCE(SUM(valor_imputado),0),0 FROM movimientos WHERE ABS(COALESCE(valor_imputado,0))>0.01 AND fecha BETWEEN ? AND ?", (fi_ext, FF))
    f2, _ = q(conn, """
        SELECT COALESCE(SUM(monto_imputado),0),0 FROM facturas
        WHERE nro_documento LIKE '%_P' AND nro_documento NOT LIKE '%_RRHH'
          AND ABS(COALESCE(monto_imputado,0))>0.01 AND fecha_compra BETWEEN ? AND ?
    """, (fi_ext, FF))
    p2, _ = q(conn, "SELECT COALESCE(SUM(valor_imputado),0),0 FROM petroleo WHERE tipo='Salida' AND fecha BETWEEN ? AND ?", (fi_ext, FF))
    a2, _ = q(conn, "SELECT COALESCE(SUM(monto),0),0 FROM ajustes_costos WHERE fecha BETWEEN ? AND ?", (fi_ext, FF))
    print(f"Suma componentes extendido + RRHH: ${b2+f2+p2+a2+rrhh:,.0f}")

    esp, _ = q(conn, """
        SELECT COALESCE(SUM(p.monto_imputado),0),0 FROM facturas p
        INNER JOIN facturas f
          ON f.nro_documento = SUBSTR(p.nro_documento,1,LENGTH(p.nro_documento)-2)
         AND f.proveedor = p.proveedor
        WHERE p.nro_documento LIKE '%_P'
          AND TRIM(COALESCE(f.razon_social,''))='El Espino'
          AND p.fecha_compra BETWEEN ? AND ?
    """, (fi_ext, FF))
    print(f"Imputaciones El Espino (restar en LC): ${esp:,.0f}")

    int_docs, _ = q(conn, """
        SELECT COALESCE(SUM(monto_total),0),0 FROM facturas
        WHERE (UPPER(TRIM(nro_documento)) LIKE 'INT-%' OR UPPER(TRIM(nro_documento)) LIKE 'INT/%')
          AND nro_documento NOT LIKE '%_P' AND fecha_compra BETWEEN ? AND ?
    """, (FI, FF))
    print(f"INT- excluidos de Compras (temporada): ${int_docs:,.0f}")

    ge, _ = q(conn, "SELECT COALESCE(SUM(monto_total),0),0 FROM facturas WHERE UPPER(TRIM(nro_documento)) GLOB 'GE-*'")
    print(f"GE-* imputaciones históricas (all time): ${ge:,.0f}")

    # Matriz real via app
    sys.path.insert(0, str(ROOT / "demo-web"))
    import app_concepcion as app  # noqa: E402

    conn2 = app.conectar_db()
    try:
        cuarteles = list(app.CUARTELES_OFICIALES)
        prorr = app._prorrateo_rrhh_desde_conn(conn2)
        fi_d = datetime.strptime(FI, "%Y-%m-%d").date()
        ff_d = datetime.strptime(FF, "%Y-%m-%d").date()
        rrhh = app._calcular_rrhh_temporada(conn2, fi_d, ff_d)
        print(f"RRHH temporada (app): ${rrhh:,.0f}")

        fi_cons, ff_cons = app._rango_fechas_costos_consulta(conn2, fi_d, ff_d, True)
        matriz = app._armar_matriz_costos_vista_b(
            conn2, fi_cons, ff_cons, cuarteles, prorr, TEMPORADA, fi_rrhh=fi_d, ff_rrhh=ff_d,
        )
        tg_raw = float(matriz[matriz["Rubro"] == "TOTAL GASTO"].iloc[0]["TOTAL"])
        print(f"\n=== MATRIZ bruta (sin exclusiones LC): ${tg_raw:,.0f} ===")
        body = matriz[~matriz["Rubro"].isin(["TOTAL GASTO", "PRESUPUESTO", "SALDO"])]
        for _, r in body.sort_values("TOTAL", ascending=False).iterrows():
            if abs(float(r["TOTAL"])) > 500_000:
                print(f"  {r['Rubro']}: ${float(r['TOTAL']):,.0f}")

        try:
            from demo_web.services.lc_excluir_espino import (  # noqa: E402
                ajustar_matriz_costos_excluir_espino_lc,
                ocultar_cuartel_espino_en_matriz_lc,
            )
            matriz_lc = ajustar_matriz_costos_excluir_espino_lc(
                conn2, app, matriz, cuarteles, fi_cons, ff_cons,
            )
            matriz_lc = ocultar_cuartel_espino_en_matriz_lc(matriz_lc)
        except ImportError:
            matriz_lc = matriz
        tg_lc = float(matriz_lc[matriz_lc["Rubro"] == "TOTAL GASTO"].iloc[0]["TOTAL"])
        print(f"\n=== MATRIZ LC (Flask Costos): ${tg_lc:,.0f} ===")
        body = matriz_lc[~matriz_lc["Rubro"].isin(["TOTAL GASTO", "PRESUPUESTO", "SALDO"])]
        for _, r in body.sort_values("TOTAL", ascending=False).iterrows():
            if abs(float(r["TOTAL"])) > 500_000:
                print(f"  {r['Rubro']}: ${float(r['TOTAL']):,.0f}")

        print(f"\n=== GAP Compras (all-time) vs Costos LC: ${tg_lc - total_all:,.0f} ===")
        print("Desglose rubros Costos (explica el gap vs solo facturas compra):")
        rubros = {r["Rubro"]: float(r["TOTAL"]) for _, r in body.iterrows()}
        for label, key in [
            ("RRHH", "RRHH de la casa"),
            ("Agroquímicos (bodega+facturas)", "Agroquímicos"),
            ("Petróleo (salidas imputadas)", "Petróleo"),
            ("Contratistas", "Contratistas"),
            ("Repuestos y talleres", "Repuestos y talleres"),
            ("Energía eléctrica", "Energía eléctrica"),
            ("Ajustes", "Ajustes"),
        ]:
            print(f"  {label}: ${rubros.get(key, 0):,.0f}")
    finally:
        conn2.close()
    conn.close()


if __name__ == "__main__":
    main()
