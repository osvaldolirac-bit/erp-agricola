#!/usr/bin/env bash
# Ejecutar EN el VPS (como root): aplica ingrediente activo en Compras → Insumos.
set -euo pipefail
ROOT="${DEPLOY_ROOT:-/root/demo-web}"
BR="${GIT_BRANCH:-cursor/compras-insumo-ia-4ef0}"
BASE="https://raw.githubusercontent.com/osvaldolirac-bit/erp-agricola/${BR}"
SERVICE="${SERVICE:-erp-agricola-web}"

echo "=== Aplicar compras insumo IA desde ${BR} ==="
mkdir -p "${ROOT}/demo_web/templates/modules" "${ROOT}/demo_web/services/native"
curl -fsSL "${BASE}/demo_web/templates/modules/compras.html" \
  -o "${ROOT}/demo_web/templates/modules/compras.html"
curl -fsSL "${BASE}/demo_web/services/native/compras.py" \
  -o "${ROOT}/demo_web/services/native/compras.py"
grep -q 'name="ingrediente_activo"' "${ROOT}/demo_web/templates/modules/compras.html"
grep -q 'ingrediente_activo' "${ROOT}/demo_web/services/native/compras.py"
systemctl restart "${SERVICE}"
sleep 2
systemctl is-active --quiet "${SERVICE}"
echo "OK — campo ingrediente activo desplegado. Reinicie sesión en /agricola/m/compras?sec=ingreso&modo=agro"
