#!/usr/bin/env python3
"""Campo Nº factura proveedor al emitir compra desde OC."""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path("/root/riomaipo/rmweb")
SRC = Path(__file__).resolve().parents[1] / "rmweb"


def main() -> int:
    for rel in (
        "ops_oc.py",
        "templates/compras/form.html",
        "templates/compras/detalle.html",
        "templates/compras/lista.html",
    ):
        src = SRC / rel
        dst = ROOT / rel
        if src.exists():
            shutil.copy2(src, dst)
            print(f"OK {dst}")

    ov = ROOT / "ops_views.py"
    text = ov.read_text(encoding="utf-8")
    orig = text

    text = text.replace(
        'sugerido_documento = f"FC-{oc[\'folio\']}"',
        'sugerido_documento = ""  # usuario anota factura real del proveedor',
    )
    text = text.replace(
        "sugerido_documento = f\"FC-{oc['folio']}\"",
        'sugerido_documento = ""  # usuario anota factura real del proveedor',
    )

    if 'tipo_documento = (request.form.get("tipo_documento")' not in text:
        needle = '            documento = (request.form.get("documento") or "").strip()\n'
        if needle not in text:
            raise SystemExit("FAIL: documento parse not found")
        text = text.replace(
            needle,
            needle
            + '            tipo_documento = (request.form.get("tipo_documento") or "factura").strip().lower() or "factura"\n',
            1,
        )

    text = text.replace(
        'flash("Proveedor y Nº documento son obligatorios", "danger")',
        'flash("Proveedor y Nº factura del proveedor son obligatorios", "danger")',
    )

    # UPDATE block
    old_upd_sql = (
        "UPDATE facturas_compra SET documento=?, proveedor_id=?, concepto=?,\n"
        "                            fecha_emision=?, fecha_vencimiento=?, neto=?, iva=?, total=?,\n"
        "                            afecta_stock=?, notas=? WHERE id=?"
    )
    new_upd_sql = (
        "UPDATE facturas_compra SET documento=?, tipo_documento=?, proveedor_id=?, concepto=?,\n"
        "                            fecha_emision=?, fecha_vencimiento=?, neto=?, iva=?, total=?,\n"
        "                            afecta_stock=?, notas=? WHERE id=?"
    )
    if old_upd_sql in text and "tipo_documento=?" not in text.split("UPDATE facturas_compra")[1][:200]:
        text = text.replace(old_upd_sql, new_upd_sql, 1)
        old_upd_params = (
            "(\n"
            "                                documento,\n"
            "                                proveedor_id,\n"
            "                                concepto,\n"
            "                                fe,\n"
            "                                fv,\n"
            "                                neto,\n"
            "                                iva,\n"
            "                                total,\n"
            "                                afecta_stock,\n"
            "                                notas,\n"
            "                                row[\"id\"],\n"
            "                            )"
        )
        new_upd_params = (
            "(\n"
            "                                documento,\n"
            "                                tipo_documento,\n"
            "                                proveedor_id,\n"
            "                                concepto,\n"
            "                                fe,\n"
            "                                fv,\n"
            "                                neto,\n"
            "                                iva,\n"
            "                                total,\n"
            "                                afecta_stock,\n"
            "                                notas,\n"
            "                                row[\"id\"],\n"
            "                            )"
        )
        if old_upd_params not in text:
            raise SystemExit("FAIL: update params not found")
        text = text.replace(old_upd_params, new_upd_params, 1)
        print("OK update tipo_documento")

    # INSERT block
    old_ins_sql = (
        "INSERT INTO facturas_compra\n"
        "                            (documento, proveedor_id, concepto, fecha_emision, fecha_vencimiento,\n"
        "                             neto, iva, total, pagado, saldo, estado, afecta_stock, notas, orden_compra_id)\n"
        "                            VALUES (?,?,?,?,?,?,?,?,0,?,'pendiente',?,?,?)"
    )
    new_ins_sql = (
        "INSERT INTO facturas_compra\n"
        "                            (documento, tipo_documento, proveedor_id, concepto, fecha_emision, fecha_vencimiento,\n"
        "                             neto, iva, total, pagado, saldo, estado, afecta_stock, notas, orden_compra_id)\n"
        "                            VALUES (?,?,?,?,?,?,?,?,?,0,?,'pendiente',?,?,?)"
    )
    if old_ins_sql in text:
        text = text.replace(old_ins_sql, new_ins_sql, 1)
        old_ins_params = (
            "(\n"
            "                                documento,\n"
            "                                proveedor_id,\n"
            "                                concepto,\n"
            "                                fe,\n"
            "                                fv,\n"
            "                                neto,\n"
            "                                iva,\n"
            "                                total,\n"
            "                                total,\n"
            "                                afecta_stock,\n"
            "                                notas,\n"
            "                                orden_compra_id,\n"
            "                            )"
        )
        new_ins_params = (
            "(\n"
            "                                documento,\n"
            "                                tipo_documento,\n"
            "                                proveedor_id,\n"
            "                                concepto,\n"
            "                                fe,\n"
            "                                fv,\n"
            "                                neto,\n"
            "                                iva,\n"
            "                                total,\n"
            "                                total,\n"
            "                                afecta_stock,\n"
            "                                notas,\n"
            "                                orden_compra_id,\n"
            "                            )"
        )
        if old_ins_params not in text:
            raise SystemExit("FAIL: insert params not found")
        text = text.replace(old_ins_params, new_ins_params, 1)
        print("OK insert tipo_documento")
    elif "tipo_documento, proveedor_id" in text:
        print("insert already has tipo_documento")
    else:
        raise SystemExit("FAIL: insert SQL not found")

    if text != orig:
        shutil.copy2(ov, ov.with_suffix(".py.bak_facprov"))
        ov.write_text(text, encoding="utf-8")
        print("OK ops_views.py")
    else:
        print("ops_views unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
