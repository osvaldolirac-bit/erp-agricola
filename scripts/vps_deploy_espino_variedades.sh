#!/usr/bin/env bash
# Ejecutar EN EL VPS (como root), tras git fetch de la rama del PR.
set -euo pipefail

BRANCH="${BRANCH:-cursor/espino-variedades-lc-4ef0}"

find_repo() {
  for d in /root/demo-web /root/erp-agricola; do
    if [[ -d "$d/.git" ]]; then
      echo "$d"
      return 0
    fi
  done
  return 1
}

REPO="$(find_repo)" || { echo "No se encontró clone git en /root/demo-web ni /root/erp-agricola"; exit 1; }
echo "Repo: $REPO"

cd "$REPO"
git fetch origin "$BRANCH"
if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  git checkout "$BRANCH"
  git pull origin "$BRANCH"
else
  git checkout -B "$BRANCH" "origin/$BRANCH"
fi

DEMO="${ERP_DEMO_WEB_ROOT:-/root/demo-web}"
if [[ "$REPO" != "$DEMO" && -d "$DEMO" ]]; then
  echo "Sync demo_web → $DEMO"
  rsync -a "$REPO/demo_web/" "$DEMO/demo_web/"
fi

echo "Deploy Super Consola (tenant_admin + config)"
export SYNC_APP=1
export SOURCE_ROOT="$REPO"
bash "$REPO/erp_master/deploy/deploy-consola.sh"

echo "Restart ERP agrícola"
systemctl restart erp-agricola-web
systemctl is-active erp-agricola-web erp-master-web

echo ""
echo "OK. Super Consola → El Espino → Prorrateo CC: cargue % y ha por variedad."
