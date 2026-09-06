#!/usr/bin/env python3
import sqlite3
import sys

conn = sqlite3.connect(sys.argv[1])
orphan = conn.execute("""
SELECT COUNT(*), COALESCE(SUM(monto_imputado),0)
FROM facturas p
WHERE p.nro_documento LIKE '%_P' AND p.nro_documento NOT LIKE '%_RRHH'
AND NOT EXISTS (
  SELECT 1 FROM facturas f
  WHERE f.nro_documento = SUBSTR(p.nro_documento, 1, LENGTH(p.nro_documento)-2)
    AND f.proveedor = p.proveedor
)
""").fetchone()
print(f"_P huerfanos (sin parent): n={orphan[0]} sum=${orphan[1]:,.0f}")
