#!/usr/bin/env python3
import sqlite3
import sys

DB = sys.argv[1] if len(sys.argv) > 1 else "/root/erp_concepcion_v6.db"
conn = sqlite3.connect(DB)

print("=== Arriendos en facturas ===")
rows = conn.execute("""
    SELECT nro_documento, proveedor, fecha_compra, monto_total, tipo_gasto, concepto, razon_social
    FROM facturas
    WHERE nro_documento NOT LIKE '%_P'
      AND (UPPER(COALESCE(concepto,'')) LIKE '%ARRIENDO%' OR TRIM(COALESCE(tipo_gasto,'')) = 'Arriendos')
    ORDER BY monto_total DESC
""").fetchall()
for r in rows:
    print(r)
print(f"Total parent: {sum(r[3] for r in rows):,.0f}")

print("\n=== Historial filter (incl INT-, excl GE, excl El Espino) ===")
rows2 = conn.execute("""
    SELECT nro_documento, monto_total, razon_social, fecha_compra
    FROM facturas
    WHERE monto_total > 0 AND nro_documento NOT LIKE '%_P'
      AND UPPER(TRIM(nro_documento)) NOT GLOB 'GE-*'
      AND TRIM(COALESCE(razon_social, '')) != 'El Espino'
      AND (UPPER(COALESCE(concepto,'')) LIKE '%ARRIENDO%' OR TRIM(COALESCE(tipo_gasto,'')) = 'Arriendos')
""").fetchall()
for r in rows2:
    print(r)

print("\n=== GE-* arriendo ===")
rows3 = conn.execute("""
    SELECT nro_documento, monto_total, concepto, razon_social
    FROM facturas WHERE UPPER(TRIM(nro_documento)) GLOB 'GE-*'
      AND UPPER(COALESCE(concepto,'')) LIKE '%ARRIENDO%'
""").fetchall()
for r in rows3:
    print(r)

print("\n=== gastos_espino arriendo ===")
try:
    rows4 = conn.execute("""
        SELECT fecha, documento, item, monto FROM gastos_espino
        WHERE UPPER(COALESCE(item,'')) LIKE '%ARRIENDO%' OR UPPER(COALESCE(item,'')) LIKE '%PAOLA%'
    """).fetchall()
    for r in rows4:
        print(r)
except Exception as e:
    print("N/A", e)

print("\n=== _P arriendos ===")
rows5 = conn.execute("""
    SELECT p.nro_documento, p.monto_imputado, p.centro_costo, f.monto_total, f.concepto
    FROM facturas p
    JOIN facturas f ON f.nro_documento = SUBSTR(p.nro_documento,1,LENGTH(p.nro_documento)-2) AND f.proveedor=p.proveedor
    WHERE TRIM(COALESCE(f.tipo_gasto,'')) = 'Arriendos' OR UPPER(COALESCE(f.concepto,'')) LIKE '%ARRIENDO%'
""").fetchall()
for r in rows5:
    print(r)

conn.close()
