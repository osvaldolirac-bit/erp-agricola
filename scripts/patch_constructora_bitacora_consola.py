#!/usr/bin/env python3
"""Parchea app.py Constructora: bitácora Super Consola (accesos + movimientos)."""
from __future__ import annotations

import re
from pathlib import Path

APP = Path("/root/constructora/rmweb/app.py")
text = APP.read_text(encoding="utf-8")

if "from rmweb.master_bitacora import log_master_bitacora" not in text:
    text = text.replace(
        "from rmweb.mail_alertas import enviar_correo_alerta, enviar_correo_alerta_pago\n",
        "from rmweb.mail_alertas import enviar_correo_alerta, enviar_correo_alerta_pago\n"
        "from rmweb.master_bitacora import log_master_bitacora\n"
        "from rmweb.demo_bitacora import log_movimiento_demo\n",
    )

if "INGRESO_ERP" not in text.split("_activate_tenant_session")[1][:800]:
    text = text.replace(
        """    if from_master:
        session["from_master_console"] = True
    try:
        open(os.path.join(_status_dir(), f"{slug}.post_maint"), "w", encoding="utf-8").write("0\\n")
""",
        """    if from_master:
        session["from_master_console"] = True
    elif slug:
        try:
            log_master_bitacora(
                slug,
                user.get("usuario") or "",
                "INGRESO_ERP",
                "Ingreso al ERP Constructora",
            )
        except Exception:
            pass
    try:
        open(os.path.join(_status_dir(), f"{slug}.post_maint"), "w", encoding="utf-8").write("0\\n")
""",
    )

if 'log_master_bitacora(\n                            "constructora-demo"' not in text:
    text = text.replace(
        """                    enviar_correo_alerta(
                        secrets_path=ten.get("secrets") or "",
                        tenant_nombre=ten.get("nombre") or ten.get("slug") or "Constructora",
                        usuario=email or "desconocido",
                        exitoso=False,
                    )
            except Exception:
                pass
        elif len(matches) == 1:""",
        """                    enviar_correo_alerta(
                        secrets_path=ten.get("secrets") or "",
                        tenant_nombre=ten.get("nombre") or ten.get("slug") or "Constructora",
                        usuario=email or "desconocido",
                        exitoso=False,
                    )
                    if (ten.get("slug") or "").strip().lower() == "constructora-demo":
                        log_master_bitacora(
                            "constructora-demo",
                            email or "desconocido",
                            "INGRESO_FALLIDO",
                            "Intento de acceso rechazado",
                        )
            except Exception:
                pass
        elif len(matches) == 1:""",
    )

if "PRUEBA_INICIO" not in text:
    text = text.replace(
        """                        with open(path, "a", encoding="utf-8") as fh:
                            fh.write(json.dumps(row_lead, ensure_ascii=False) + "\\n")

                        ok = True""",
        """                        with open(path, "a", encoding="utf-8") as fh:
                            fh.write(json.dumps(row_lead, ensure_ascii=False) + "\\n")

                        try:
                            log_master_bitacora(
                                "constructora-demo",
                                email_u,
                                "PRUEBA_INICIO",
                                f"{nombre_u} · {telefono_u} · vence {exp}",
                            )
                        except Exception:
                            pass

                        ok = True""",
    )

replacements = [
    (
        '                db.commit()\n                flash("Cliente guardado", "ok")',
        '                db.commit()\n                log_movimiento_demo("CLIENTE", f"{\'Editado\' if row else \'Nuevo\'}: {data[1]}")\n                flash("Cliente guardado", "ok")',
    ),
    (
        '            flash(msg, "ok")\n            db.close()\n            return redirect(url_for("cotizaciones_detalle", cot_id=cid))',
        '            log_movimiento_demo("COTIZACION", msg)\n            flash(msg, "ok")\n            db.close()\n            return redirect(url_for("cotizaciones_detalle", cot_id=cid))',
    ),
    (
        '        db.commit()\n        flash(f"{row[\'folio\']} eliminada", "ok")',
        '        db.commit()\n        log_movimiento_demo("COTIZACION", f"Eliminada {row[\'folio\']}")\n        flash(f"{row[\'folio\']} eliminada", "ok")',
    ),
    (
        '        flash(msg, "ok")\n    else:\n        flash("Estado actualizado", "ok")\n    return redirect(url_for("cotizaciones_detalle", cot_id=cot_id))',
        '        log_movimiento_demo("COTIZACION", msg)\n        flash(msg, "ok")\n    else:\n        log_movimiento_demo("COTIZACION", f"Estado → {estado} (id {cot_id})")\n        flash("Estado actualizado", "ok")\n    return redirect(url_for("cotizaciones_detalle", cot_id=cot_id))',
    ),
    (
        '                db.commit()\n                flash("Documento actualizado", "ok")',
        '                db.commit()\n                log_movimiento_demo("CXC", f"Documento actualizado id {edit[\'id\']}")\n                flash("Documento actualizado", "ok")',
    ),
    (
        '                db.commit()\n                flash(f"Documento {doc} creado", "ok")',
        '                db.commit()\n                log_movimiento_demo("CXC", f"Documento {doc} creado")\n                flash(f"Documento {doc} creado", "ok")',
    ),
    (
        '            pagado_total = saldo_nuevo <= 0\n            if pagado_total:',
        '            pagado_total = saldo_nuevo <= 0\n            log_movimiento_demo("CXC", f"{\'Pago total\' if pagado_total else \'Abono\'} {core.clp(monto)} · doc {cuenta[\'documento\']}")\n            if pagado_total:',
    ),
    (
        '    db.commit()\n    db.close()\n    flash("Documento eliminado", "ok")',
        '    db.commit()\n    db.close()\n    log_movimiento_demo("CXC", f"Documento eliminado id {cuenta_id}")\n    flash("Documento eliminado", "ok")',
    ),
    (
        '        flash(f"Solicitud de «{nombre_plan}» enviada. Te contactaremos pronto.", "ok")',
        '        log_movimiento_demo("PLAN", f"Solicitud contratar: {nombre_plan}")\n        flash(f"Solicitud de «{nombre_plan}» enviada. Te contactaremos pronto.", "ok")',
    ),
]

for old, new in replacements:
    if old in text and new not in text:
        text = text.replace(old, new, 1)

# Fix pagado_total log order (must compute before log)
text = text.replace(
    '            pagado_total = saldo_nuevo <= 0\n            log_movimiento_demo("CXC", f"{\'Pago total\' if pagado_total else \'Abono\'} {core.clp(monto)} · doc {cuenta[\'documento\']}")\n            if pagado_total:',
    '            pagado_total = saldo_nuevo <= 0\n            log_movimiento_demo(\n                "CXC",\n                f"{\'Pago total\' if pagado_total else \'Abono\'} {core.clp(monto)} · doc {cuenta[\'documento\']}",\n            )\n            if pagado_total:',
)

APP.write_text(text, encoding="utf-8")
print("OK constructora app.py patched")
