#!/usr/bin/env bash
# Restaura Super Consola al snapshot VPS 2026-08-26 ~23:56 UTC
set -euo pipefail

DEPLOY_ROOT="${DEPLOY_ROOT:-/root/erp_master}"
SNAP="${SNAP:-/root/backups/erp_master/20260826_231846/code}"
APP_BAK="${APP_BAK:-/root/backups/erp_master/app.py.bak_20260826_235651}"
STAMP="$(date +%Y%m%d_%H%M%S)"
BK="/root/backups/erp_master/restore_${STAMP}"
SERVICE="${SERVICE:-erp-master-web}"

log() { echo "[$(date -Iseconds)] $*"; }
die() { log "ERROR: $*"; exit 1; }

[[ -d "$SNAP/erp_master" ]] || die "missing snapshot $SNAP"
[[ -f "$APP_BAK" ]] || die "missing app backup $APP_BAK"

log "Backup actual → $BK"
mkdir -p "$BK"
rsync -a "$DEPLOY_ROOT/" "$BK/current/" --exclude .venv --exclude __pycache__

log "Restaurar templates + master.css desde snapshot"
rsync -a "$SNAP/erp_master/templates/" "$DEPLOY_ROOT/erp_master/templates/" \
  --exclude '*.bak*' --exclude '__pycache__'
rsync -a "$SNAP/erp_master/static/master.css" "$DEPLOY_ROOT/erp_master/static/master.css"

log "Restaurar app.py (23:56 Aug 26)"
cp -a "$APP_BAK" "$DEPLOY_ROOT/erp_master/app.py"

log "Parche login: quitar honeypots autofill + autocomplete correcto"
python3 <<'PY'
from pathlib import Path
p = Path("/root/erp_master/erp_master/templates/login.html")
text = p.read_text(encoding="utf-8")
for needle in (
    '            <input type="text" name="fake_user" value="" tabindex="-1" autocomplete="username" aria-hidden="true" style="position:absolute;left:-9999px;height:0;width:0;opacity:0;">\n',
    '            <input type="password" name="fake_pass" value="" tabindex="-1" autocomplete="current-password" aria-hidden="true" style="position:absolute;left:-9999px;height:0;width:0;opacity:0;">\n',
):
    text = text.replace(needle, "")
text = text.replace('autocomplete="off" id="loginForm"', 'id="loginForm"')
text = text.replace(
    'name="email" type="email" autocomplete="off"',
    'name="email" type="email" autocomplete="username"',
)
text = text.replace(
    'name="password" type="password" placeholder="••••" autocomplete="new-password"',
    'name="password" type="password" placeholder="••••" autocomplete="current-password"',
)
p.write_text(text, encoding="utf-8")
print("login.html patched")
PY

log "SESSION_COOKIE_PATH=/consola en config (sin cambiar resto)"
python3 <<'PY'
from pathlib import Path
p = Path("/root/erp_master/erp_master/config.py")
text = p.read_text(encoding="utf-8")
if "SESSION_COOKIE_PATH" not in text:
    text = text.replace(
        '    SESSION_COOKIE_NAME = _env("ERP_MASTER_SESSION_COOKIE", "erp_master_session_v2")\n',
        '    SESSION_COOKIE_NAME = _env("ERP_MASTER_SESSION_COOKIE", "erp_master_session_v2")\n'
        '    SESSION_COOKIE_PATH = _env("ERP_MASTER_SESSION_COOKIE_PATH", "/consola")\n',
        1,
    )
    p.write_text(text, encoding="utf-8")
    print("config.py patched")
else:
    print("config.py already has SESSION_COOKIE_PATH")
PY

log "Revert nginx redirect consola/consola → admin (no existía ayer)"
NG="/etc/nginx/sites-enabled/erpmaster.cl"
if grep -q 'consola/consola' "$NG" 2>/dev/null; then
  cp -a "$NG" "${NG}.bak_restore_${STAMP}"
  sed -i '/location ~ \^\/consola\/consola\//,/^[[:space:]]*}/d' "$NG"
  nginx -t && systemctl reload nginx
fi

log "Reset clave master"
python3 /root/scripts/reset_consola_master_password.py osvaldolirac@gmail.com Erpmaster2026

log "Restart $SERVICE"
systemctl restart "$SERVICE"
sleep 2
systemctl is-active --quiet "$SERVICE" || die "service not active"

log "Verify"
ERP_MASTER_ROOT="$DEPLOY_ROOT" \
ERP_MASTER_SEED_EMAIL=osvaldolirac@gmail.com \
ERP_MASTER_SEED_PASSWORD=Erpmaster2026 \
python3 /root/scripts/verify_consola.py

log "Restore OK — rollback: rsync -a $BK/current/ $DEPLOY_ROOT/ && systemctl restart $SERVICE"
