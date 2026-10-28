#!/usr/bin/env python3
"""Deploy único LC+Espino robustez ~8/10 (py + templates alineados).

Uso:
  python3 scripts/deploy_robustez_lc_espino_vps.py          # sube y reinicia
  python3 scripts/deploy_robustez_lc_espino_vps.py --check  # solo valida manifest local

Requiere SSH al VPS (SSHPASS opcional).

Política del repo: `.cursor/rules/erp-agricola-vps-deploy.mdc`
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

HOST = "root@45.7.230.70"
PORT = "40484"
REMOTE = "/root/demo-web"

# Orden estable; rutas remotas = locales (bajo REMOTE).
ROBUSTEZ_LC_ESPINO_FILES: tuple[str, ...] = (
    "demo_web/tenants.py",
    "demo_web/services/erp_loader.py",
    "demo_web/services/tenant_rules.py",
    "demo_web/services/tenant_scope.py",
    "demo_web/services/espino_scope.py",
    "demo_web/services/lc_query_scope.py",
    "demo_web/services/lc_aplicacion_service.py",
    "demo_web/services/lc_bodega_desfase.py",
    "demo_web/services/lc_imputacion_bruto.py",
    "demo_web/services/espino_aplicacion_service.py",
    "demo_web/services/espino_bodega_desfase.py",
    "demo_web/services/espino_compras_guards.py",
    "demo_web/services/espino_compras_kardex.py",
    "demo_web/services/bodega_kardex.py",
    "demo_web/services/flujo_espino.py",
    "demo_web/services/dashboard.py",
    "demo_web/services/tesoreria_alerta.py",
    "demo_web/services/prestamo_rrhh.py",
    "demo_web/services/remuneracion_extra.py",
    "demo_web/services/cosecha.py",
    "demo_web/services/hydrawise_cola_item.py",
    "demo_web/services/hydrawise_riego.py",
    "demo_web/templates/registro_riego/_hydra_panel_control.html",
    "demo_web/templates/registro_riego/_hydra_control_ui.html",
    "demo_web/services/qrcodegen.py",
    "demo_web/services/public_link_tenant.py",
    "demo_web/services/sidebar_badges.py",
    "demo_web/auth/decorators.py",
    "demo_web/auth/login_next.py",
    "demo_web/auth/tenant_access.py",
    "demo_web/auth/routes.py",
    "demo_web/services/native/_helpers.py",
    "demo_web/services/native/libro_campo.py",
    "demo_web/services/native/compras.py",
    "demo_web/services/native/costos.py",
    "demo_web/services/native/tesoreria.py",
    "demo_web/services/native/flujo.py",
    "demo_web/services/native/administracion.py",
    "demo_web/services/native/bodega.py",
    "demo_web/services/native/rrhh.py",
    "demo_web/services/native/espino.py",
    "demo_web/services/native/espino_bodega.py",
    "demo_web/services/native/espino_libro_campo.py",
    "demo_web/templates/modules/rrhh.html",
    "demo_web/templates/cosecha_anotadora.html",
    "demo_web/templates/cosecha_fundas_print.html",
    "demo_web/templates/modules/bodega.html",
    "demo_web/templates/modules/compras.html",
    "demo_web/templates/modules/administracion.html",
    "demo_web/templates/modules/flujo.html",
    "demo_web/templates/modules/tesoreria.html",
    "demo_web/static/css/erp.css",
    "demo_web/templates/dashboard/index.html",
    "demo_web/templates/select_tenant.html",
    "demo_web/templates/partials/espino_libro_campo.html",
    "erp_flujo_financiero.py",
    "scripts/migrate_espino_libro_movimiento_id_vps.py",
    "scripts/migrate_prestamo_rrhh_vps.py",
    "scripts/migrate_remuneracion_extra_vps.py",
    "scripts/migrate_cosecha_vps.py",
    "scripts/alerta_tesoreria_vencimiento.py",
    "scripts/smoke_robustez.py",
    "scripts/verify_agricola_release.py",
    "erp_maquinaria.py",
)


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def check_manifest(root: Path) -> None:
    missing = [rel for rel in ROBUSTEZ_LC_ESPINO_FILES if not (root / rel).is_file()]
    if missing:
        print("Faltan archivos en el manifest:", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        raise SystemExit(1)
    print(f"OK — manifest {len(ROBUSTEZ_LC_ESPINO_FILES)} archivos presentes.")


def deploy(root: Path) -> None:
    check_manifest(root)
    scp_base = ["scp", "-o", "StrictHostKeyChecking=no", "-P", PORT]
    if os.environ.get("SSHPASS"):
        scp_base = ["sshpass", "-e", *scp_base]
    for rel in ROBUSTEZ_LC_ESPINO_FILES:
        local = root / rel
        run([*scp_base, str(local), f"{HOST}:{REMOTE}/{rel}"])
    ssh_base = ["ssh", "-o", "StrictHostKeyChecking=no", "-p", PORT, HOST]
    if os.environ.get("SSHPASS"):
        ssh_base = ["sshpass", "-e", *ssh_base]
    post = (
        f"cd {REMOTE} && PYTHONPATH={REMOTE} "
        f"{REMOTE}/.venv/bin/python3 scripts/migrate_espino_libro_movimiento_id_vps.py "
        f"&& PYTHONPATH={REMOTE} {REMOTE}/.venv/bin/python3 scripts/migrate_prestamo_rrhh_vps.py "
        f"&& PYTHONPATH={REMOTE} {REMOTE}/.venv/bin/python3 scripts/migrate_remuneracion_extra_vps.py "
        f"&& PYTHONPATH={REMOTE} {REMOTE}/.venv/bin/python3 scripts/migrate_cosecha_vps.py "
        f"&& PYTHONPATH={REMOTE} {REMOTE}/.venv/bin/python3 scripts/smoke_robustez.py "
        f"&& systemctl restart erp-agricola-web && systemctl is-active erp-agricola-web"
    )
    run([*ssh_base, post])
    print("OK — robustez LC+Espino desplegada (smoke en VPS pasó).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Solo verifica que existan todos los archivos del manifest.",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.check:
        check_manifest(root)
        subprocess.run(
            [sys.executable, str(root / "scripts/smoke_robustez.py")],
            check=True,
            cwd=str(root),
            env={**os.environ, "PYTHONPATH": str(root)},
        )
        return
    deploy(root)


if __name__ == "__main__":
    main()
