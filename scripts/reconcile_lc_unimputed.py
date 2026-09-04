#!/usr/bin/env python3
import sqlite3
import sys
from collections import Counter

conn = sqlite3.connect(sys.argv[1])
rows = conn.execute("""
SELECT f.nro_documento, f.proveedor, f.monto_total, f.tipo,
  (SELECT COALESCE(SUM(p.monto_imputado),0) FROM facturas p
   WHERE p.nro_documento = f.nro_documento || '_P' AND p.proveedor = f.proveedor) AS imp
FROM facturas f
WHERE f.monto_total > 0 AND f.nro_documento NOT LIKE '%_P'
  AND UPPER(TRIM(f.nro_documento)) NOT LIKE 'INT-%'
  AND UPPER(TRIM(f.nro_documento)) NOT GLOB 'GE-*'
  AND TRIM(COALESCE(f.razon_social, '')) != 'El Espino'
""").fetchall()
sin = sum(r[2] for r in rows if (r[4] or 0) < 0.01)
con = sum(r[2] for r in rows if (r[4] or 0) >= 0.01)
print(f"Parent compras sin _P: ${sin:,.0f} ({sum(1 for r in rows if (r[4] or 0) < 0.01)} docs)")
print(f"Parent compras con _P: ${con:,.0f} ({sum(1 for r in rows if (r[4] or 0) >= 0.01)} docs)")
c = Counter()
for r in rows:
    if (r[4] or 0) < 0.01:
        c[str(r[3] or "?")] += r[2]
print("Sin imputar por tipo:")
for k, v in c.most_common():
    print(f"  {k}: ${v:,.0f}")
