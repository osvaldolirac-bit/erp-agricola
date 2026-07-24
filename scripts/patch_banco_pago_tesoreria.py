#!/usr/bin/env python3
"""Patch app_*.py: columna banco en abonos/facturas + param en _registrar_abono_factura."""
from __future__ import annotations

import sys
from pathlib import Path


def patch_file(path: Path) -> bool:
    text = path.read_text()
    if "def _ensure_banco_pago_cols" in text and "banco=banco" in text:
        print(f"already patched {path}")
        return False

    ensure_fn = '''
def _ensure_banco_pago_cols(conn):
    """Agrega columna banco a facturas_abonos / facturas (idempotente)."""
    for table in ("facturas_abonos", "facturas"):
        try:
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        except Exception:
            continue
        if "banco" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN banco TEXT DEFAULT ''")


'''

    old_sig = "def _registrar_abono_factura(conn, factura_id, fecha, monto, metodo, usuario):"
    new_sig = "def _registrar_abono_factura(conn, factura_id, fecha, monto, metodo, usuario, banco=\"\"):"
    if old_sig not in text:
        raise SystemExit(f"signature not found in {path}")
    text = text.replace(old_sig, new_sig, 1)

    # Insert ensure helper before _registrar_abono_factura
    text = text.replace(new_sig, ensure_fn + new_sig, 1)

    old_insert = '''    conn.execute(
        """INSERT INTO facturas_abonos (factura_id, fecha, monto, metodo_pago, usuario, fecha_registro)
           VALUES (?,?,?,?,?,?)""",
        (factura_id, str(fecha), monto, metodo, usuario, f_reg),
    )
    conn.execute(
        """UPDATE facturas SET monto_pagado=?, fecha_pago=?, metodo_pago=?, estado=? WHERE id=?""",
        (nuevo_pagado, str(fecha), metodo, nuevo_estado, factura_id),
    )'''

    new_insert = '''    _ensure_banco_pago_cols(conn)
    banco = (banco or "").strip()
    conn.execute(
        """INSERT INTO facturas_abonos (factura_id, fecha, monto, metodo_pago, banco, usuario, fecha_registro)
           VALUES (?,?,?,?,?,?,?)""",
        (factura_id, str(fecha), monto, metodo, banco, usuario, f_reg),
    )
    conn.execute(
        """UPDATE facturas SET monto_pagado=?, fecha_pago=?, metodo_pago=?, banco=?, estado=? WHERE id=?""",
        (nuevo_pagado, str(fecha), metodo, banco, nuevo_estado, factura_id),
    )'''

    if old_insert not in text:
        raise SystemExit(f"insert block not found in {path}")
    text = text.replace(old_insert, new_insert, 1)

    # Historial SQL: include banco
    old_hist = '''        f"""SELECT f.nro_documento, f.proveedor,
                   IFNULL(f.razon_social, 'La Concepción') AS razon_social,
                   a.monto AS monto_total, a.metodo_pago, a.fecha AS fecha_pago
            FROM facturas_abonos a
            JOIN facturas f ON f.id = a.factura_id
            WHERE {where_abono}
            UNION ALL
            SELECT f.nro_documento, f.proveedor,
                   IFNULL(f.razon_social, 'La Concepción') AS razon_social,
                   COALESCE(NULLIF(f.monto_pagado, 0), f.monto_total) AS monto_total,
                   f.metodo_pago, f.fecha_pago AS fecha_pago
            FROM facturas f
            WHERE {where_legacy}
            ORDER BY fecha_pago DESC, proveedor ASC, metodo_pago ASC, nro_documento ASC"""'''

    new_hist = '''        f"""SELECT f.nro_documento, f.proveedor,
                   IFNULL(f.razon_social, 'La Concepción') AS razon_social,
                   a.monto AS monto_total, a.metodo_pago,
                   IFNULL(a.banco, '') AS banco, a.fecha AS fecha_pago
            FROM facturas_abonos a
            JOIN facturas f ON f.id = a.factura_id
            WHERE {where_abono}
            UNION ALL
            SELECT f.nro_documento, f.proveedor,
                   IFNULL(f.razon_social, 'La Concepción') AS razon_social,
                   COALESCE(NULLIF(f.monto_pagado, 0), f.monto_total) AS monto_total,
                   f.metodo_pago, IFNULL(f.banco, '') AS banco, f.fecha_pago AS fecha_pago
            FROM facturas f
            WHERE {where_legacy}
            ORDER BY fecha_pago DESC, proveedor ASC, metodo_pago ASC, nro_documento ASC"""'''

    if old_hist in text:
        text = text.replace(old_hist, new_hist, 1)
        print(f"historial SQL patched in {path.name}")
    else:
        print(f"WARN: historial SQL not matched in {path.name}")

    path.write_text(text)
    print(f"OK {path}")
    return True


def main() -> int:
    roots = [Path("/root/demo-web")]
    changed = False
    for root in roots:
        for name in ("app_concepcion.py", "app_demo.py"):
            p = root / name
            if p.exists():
                changed = patch_file(p) or changed
    return 0 if changed or True else 1


if __name__ == "__main__":
    raise SystemExit(main())
