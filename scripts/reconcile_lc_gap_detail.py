#!/usr/bin/env python3
import sqlite3
import sys

DB = sys.argv[1] if len(sys.argv) > 1 else "/root/erp_concepcion_v6.db"
conn = sqlite3.connect(DB)

def s(sql, params=()):
    return float(conn.execute(sql, params).fetchone()[0] or 0)

print("=== COMPRAS (Flask historial, all-time) ===")
compras = s("""
    SELECT SUM(monto_total) FROM facturas
    WHERE monto_total > 0 AND nro_documento NOT LIKE '%_P'
      AND UPPER(TRIM(nro_documento)) NOT LIKE 'INT-%'
      AND UPPER(TRIM(nro_documento)) NOT LIKE 'INT/%'
      AND UPPER(TRIM(nro_documento)) NOT GLOB 'GE-*'
      AND TRIM(COALESCE(razon_social, '')) != 'El Espino'
""")
print(f"Total: ${compras:,.0f}")

fi_ext = "2026-03-06"
FF = "2027-04-30"

p_all = s("""
    SELECT SUM(monto_imputado) FROM facturas
    WHERE nro_documento LIKE '%_P' AND nro_documento NOT LIKE '%_RRHH'
      AND fecha_compra BETWEEN ? AND ?
""", (fi_ext, FF))

int_p = s("""
    SELECT SUM(p.monto_imputado) FROM facturas p
    WHERE p.nro_documento LIKE '%_P'
      AND EXISTS (
        SELECT 1 FROM facturas f
        WHERE f.nro_documento = SUBSTR(p.nro_documento, 1, LENGTH(p.nro_documento)-2)
          AND f.proveedor = p.proveedor
          AND (UPPER(TRIM(f.nro_documento)) LIKE 'INT-%' OR UPPER(TRIM(f.nro_documento)) LIKE 'INT/%')
      )
      AND p.fecha_compra BETWEEN ? AND ?
""", (fi_ext, FF))

bodega = s("SELECT SUM(valor_imputado) FROM movimientos WHERE fecha BETWEEN ? AND ?", (fi_ext, FF))
pet = s("SELECT SUM(valor_imputado) FROM petroleo WHERE tipo='Salida' AND fecha BETWEEN ? AND ?", (fi_ext, FF))
rrhh = s("""
    SELECT SUM(COALESCE(liquido,0)+COALESCE(leyes_sociales,0)) FROM pagos_rrhh
    WHERE (anio=2026 AND CAST(mes AS INTEGER)>=5) OR (anio=2027 AND CAST(mes AS INTEGER)<=4)
""")
esp = s("""
    SELECT SUM(p.monto_imputado) FROM facturas p
    JOIN facturas f ON f.nro_documento=SUBSTR(p.nro_documento,1,LENGTH(p.nro_documento)-2) AND f.proveedor=p.proveedor
    WHERE p.nro_documento LIKE '%_P' AND TRIM(COALESCE(f.razon_social,''))='El Espino'
      AND p.fecha_compra BETWEEN ? AND ?
""", (fi_ext, FF))

print("\n=== COSTOS componentes (rango extendido LC) ===")
for label, val in [
    ("Imputaciones _P (total)", p_all),
    ("  └ de documentos INT- (no en Compras)", int_p),
    ("  └ de facturas reales", p_all - int_p),
    ("Bodega salidas", bodega),
    ("Petróleo salidas", pet),
    ("RRHH temporada", rrhh),
    ("Menos imput. El Espino", -esp),
]:
    print(f"{label}: ${val:,.0f}")

costos_est = p_all + bodega + pet + rrhh - esp
print(f"\nEstimado TOTAL COSTOS: ${costos_est:,.0f}")
print(f"GAP vs Compras: ${costos_est - compras:,.0f}")

print("\n=== Qué explica el gap ===")
print(f"RRHH (solo Costos):           ${rrhh:,.0f}")
print(f"INT- imputados (solo Costos): ${int_p:,.0f}")
print(f"Bodega consumos:              ${bodega:,.0f}")
print(f"Petróleo salidas imputadas:   ${pet:,.0f}")
print(f"Suma explicativa:             ${rrhh + int_p + bodega + pet:,.0f}")

# Insumos: compras parent vs bodega overlap?
insumos_compras = s("""
    SELECT SUM(monto_total) FROM facturas
    WHERE monto_total > 0 AND nro_documento NOT LIKE '%_P'
      AND TRIM(COALESCE(razon_social,'')) != 'El Espino'
      AND (UPPER(TRIM(COALESCE(tipo,''))) LIKE '%INSUMO%' OR TRIM(COALESCE(concepto,'')) LIKE '[%')
""")
print(f"\nInsumos en Compras (parent): ${insumos_compras:,.0f}")
print(f"Agroquímicos vía bodega Costos: ${bodega:,.0f} (costo al salir, no al comprar)")

conn.close()
