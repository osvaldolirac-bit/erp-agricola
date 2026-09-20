#!/usr/bin/env bash
# deploy-demo-web.sh — despliegue seguro IN-PLACE rubro agrícola (VPS producción)
# Fuente de verdad: /root/demo-web (git local). No usa GitHub.
set -euo pipefail

DEPLOY_ROOT="${DEPLOY_ROOT:-/root/demo-web}"
BACKUP_ROOT="${BACKUP_ROOT:-/root/backups/demo-web}"
STAMP="$(date +%Y%m%d_%H%M%S)"
BK="${BACKUP_ROOT}/${STAMP}"
VERIFY_SCRIPT="${VERIFY_SCRIPT:-/root/scripts/verify_agricola.py}"
REGRESSION_GUARD="${REGRESSION_GUARD:-/root/scripts/regression_guard_agricola.py}"
ALERT_LOG="${ERP_ALERT_LOG:-/root/erp_status/agricola_alerts.log}"
SERVICES=(
  erp-agricola-web
  erp-lc-web
  erp-demo-web
)

log() { echo "[$(date -Iseconds)] $*"; }
die() { log "ERROR: $*"; _alert_critical "$*"; exit 1; }

_alert_critical() {
  local msg="$1"
  mkdir -p "$(dirname "$ALERT_LOG")"
  echo "$(date -Iseconds) [DEPLOY_FAILED] $msg" >> "$ALERT_LOG"
}

rollback() {
  if [[ ! -d "$BK/code" ]]; then
    log "No backup at $BK — cannot rollback"
    return 1
  fi
  log "ROLLBACK from $BK"
  rsync -a "$BK/code/" "$DEPLOY_ROOT/" --exclude '.venv' --exclude '.git'
  for svc in "${SERVICES[@]}"; do
    systemctl restart "$svc" 2>/dev/null || true
  done
  sleep 2
}

trap 'if [[ $? -ne 0 ]]; then log "Deploy failed — attempting rollback"; rollback; fi' EXIT

log "=== Demo-web VPS deploy (in-place) ==="
log "Target: $DEPLOY_ROOT"

[[ -d "$DEPLOY_ROOT/demo_web" ]] || die "missing $DEPLOY_ROOT/demo_web"
[[ -d "$DEPLOY_ROOT/.venv" ]] || die "missing venv at $DEPLOY_ROOT/.venv"
command -v rsync >/dev/null || die "rsync required"

# 1. Backup completo (código + app modules)
log "Backup → $BK"
mkdir -p "$BK"
rsync -a "$DEPLOY_ROOT/" "$BK/code/" \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '*.db' \
  --exclude '*.db-journal' \
  --exclude '.git/objects'
for svc in "${SERVICES[@]}"; do
  if [[ -f "/etc/systemd/system/${svc}.service" ]]; then
    cp -a "/etc/systemd/system/${svc}.service" "$BK/" 2>/dev/null || true
  fi
done
log "Backup OK: $BK"

# 2. Sincronizar scripts operativos → /root/scripts (verify, cron respaldo, health watch)
SCRIPTS_SRC="${DEPLOY_ROOT}/vps-robust/scripts"
if [[ -d "$SCRIPTS_SRC" ]]; then
  log "Sync /root/scripts from $SCRIPTS_SRC"
  mkdir -p /root/scripts
  for f in \
    verify_agricola.py \
    regression_guard_agricola.py \
    erp_respaldo_cron.py \
    agricola_health_watch.sh \
    deploy-demo-web.sh; do
    if [[ -f "$SCRIPTS_SRC/$f" ]]; then
      cp -a "$SCRIPTS_SRC/$f" "/root/scripts/$f"
      chmod +x "/root/scripts/$f" 2>/dev/null || true
    fi
  done
else
  log "WARN: missing $SCRIPTS_SRC — scripts not synced"
fi

# 3. Anti-regresión ANTES de reiniciar (bloquea archivos parciales / fixes perdidos)
if [[ -f "$REGRESSION_GUARD" ]]; then
  log "Regression guard (pre-restart)"
  APP_ROOT="$DEPLOY_ROOT" "$DEPLOY_ROOT/.venv/bin/python3" "$REGRESSION_GUARD" \
    || die "regression guard failed — posible archivo parcial (ej. libro_campo sin cabecera)"
else
  die "regression guard missing at $REGRESSION_GUARD"
fi

# 4. Sintaxis Python (falla antes de reiniciar servicios)
log "compileall demo_web + app_*.py"
cd "$DEPLOY_ROOT"
"$DEPLOY_ROOT/.venv/bin/python3" -m compileall -q demo_web app_concepcion.py app_demo.py 2>/dev/null \
  || "$DEPLOY_ROOT/.venv/bin/python3" -m compileall -q demo_web app_concepcion.py \
  || die "Python syntax error — fix before deploy"

# 5. Restart todos los servicios que comparten demo-web
log "Restart services: ${SERVICES[*]}"
for svc in "${SERVICES[@]}"; do
  if systemctl is-enabled --quiet "$svc" 2>/dev/null; then
    systemctl restart "$svc" || die "failed to restart $svc"
  fi
done
sleep 3
for svc in "${SERVICES[@]}"; do
  if systemctl is-enabled --quiet "$svc" 2>/dev/null; then
    systemctl is-active --quiet "$svc" || die "$svc not active after restart"
  fi
done

# 6. Verify obligatorio (+ alertas internas)
if [[ -f "$VERIFY_SCRIPT" ]]; then
  log "Verify agricola (obligatorio)"
  DEMO_WEB_ROOT="$DEPLOY_ROOT/demo_web" \
  APP_ROOT="$DEPLOY_ROOT" \
  REGRESSION_GUARD="$REGRESSION_GUARD" \
  BASE_URL=http://127.0.0.1:8508 \
  PREFIX="" \
  "$DEPLOY_ROOT/.venv/bin/python3" "$VERIFY_SCRIPT" || die "verification failed — rollback triggered"
  APP_ROOT="$DEPLOY_ROOT" "$DEPLOY_ROOT/.venv/bin/python3" "$REGRESSION_GUARD" \
    || die "regression guard post-verify failed"
else
  die "verify script missing at $VERIFY_SCRIPT"
fi

trap - EXIT
log "Deploy OK — backup: $BK"
log "Rollback manual: rsync -a $BK/code/ $DEPLOY_ROOT/ && systemctl restart ${SERVICES[*]}"
