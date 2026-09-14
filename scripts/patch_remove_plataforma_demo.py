#!/usr/bin/env python3
"""Quita Plataforma DEMO del admin ERP y actualiza DEMO_URL."""
from __future__ import annotations

import re
from pathlib import Path

ADMIN = Path("/root/demo-web/demo_web/services/native/administracion.py")
TPL = Path("/root/demo-web/demo_web/templates/modules/administracion.html")
APP_DEMO = Path("/root/demo-web/app_demo.py")


def main() -> None:
    text = ADMIN.read_text(encoding="utf-8")
    text2 = text.replace(
        '    ("flujo", "💰 INGRESOS FLUJO", "all"),\n'
        '    ("plataforma", "🔧 PLATAFORMA DEMO", "super"),\n]',
        '    ("flujo", "💰 INGRESOS FLUJO", "all"),\n]',
    )
    text2 = text2.replace(
        '        if key == "plataforma" and get_erp_app() == "concepcion":\n'
        "            continue\n",
        "",
    )
    text2 = text2.replace(
        '        elif sec == "plataforma":\n'
        "            ctx.update(_gather_plataforma(demo, conn))\n",
        "",
    )
    if "reseed" not in text2.split("ACCIONES_MOVIDAS_A_MASTER", 1)[-1][:500]:
        text2 = text2.replace(
            'ACCIONES_MOVIDAS_A_MASTER = frozenset({\n    "crear_usuario",',
            'ACCIONES_MOVIDAS_A_MASTER = frozenset({\n    "reseed",\n    "crear_usuario",',
        )
    ADMIN.write_text(text2, encoding="utf-8")
    print("administracion.py ok")

    html = TPL.read_text(encoding="utf-8")
    html = html.replace(
        "Aquí: bitácora, maestras y plataforma demo.",
        "Aquí: bitácora y maestras. Plataforma demo / invitaciones: Super Consola.",
    )
    html2, n = re.subn(
        r"\n  \{% elif sec_activa == 'plataforma' %\}.*?(?=\n  \{% endif %\}\n</div>\n\{% endblock %\})",
        "",
        html,
        count=1,
        flags=re.S,
    )
    TPL.write_text(html2 if n else html, encoding="utf-8")
    print("template ok" if n else "template: no plataforma block matched")

    ad = APP_DEMO.read_text(encoding="utf-8")
    ad2 = ad.replace(
        'DEMO_URL = "https://erpmaster.cl/demo"',
        'DEMO_URL = "https://erpmaster.cl/agricola/login"',
    )
    APP_DEMO.write_text(ad2, encoding="utf-8")
    print("DEMO_URL", "updated" if ad2 != ad else "unchanged")


if __name__ == "__main__":
    main()
