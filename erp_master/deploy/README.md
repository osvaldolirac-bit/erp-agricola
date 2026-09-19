# Despliegue Super Consola — reglas obligatorias

Este documento existe para que **no se repita** el incidente de agosto 2026 (consola rota, login imposible, parches en cadena).

## Regla de oro

**El repo es la fuente de verdad.** En producción solo se despliega con `deploy-consola.sh`, nunca copiando archivos sueltos ni encadenando parches a mano.

## Despliegue correcto (VPS)

```bash
cd /root/erp-agricola   # o donde esté el clone git
git pull
bash erp_master/deploy/deploy-consola.sh
```

El script:

1. Hace **backup** en `/root/backups/erp_master/<timestamp>/`
2. Sincroniza solo rutas seguras (templates, static, config, wsgi, db, bridge)
3. **No sobrescribe** `app.py` ni `tenant_admin.py` salvo `SYNC_APP=1` explícito
4. Reinicia `erp-master-web`
5. Ejecuta `scripts/verify_consola.py`
6. Si falla → **rollback automático**

## Agregar tenant nuevo (ej. GlobalGAP)

Orden fijo:

1. Bootstrap DB del tenant (`bootstrap_globalgap_tenant.py`)
2. **Merge** en consola: `patch_globalgap_consola_merge.py` (no reemplaza config entera)
3. `deploy-consola.sh`
4. `verify_consola.py`

## Parches PROHIBIDOS sin `--force`

| Script | Motivo |
|--------|--------|
| `patch_consola_restore_tenants.py` | Sobrescribe `config.py` y `tenant_admin.py` enteros |
| `patch_consola_session_reset.py` | Resetea claves y cookie sin control |

Ejecutarlos requiere `--force` o `ERP_DEPLOY_ALLOW_DESTRUCTIVE=1`.

## Verificación manual rápida

```bash
python3 /root/scripts/verify_consola.py
curl -s http://127.0.0.1:8507/health
```

Debe pasar: health, 7 tenants en config, login con Acceso cerrado, POST procesado, logout limpia cookie.

## Lo que NO hacer

- Copiar `config.py` de un solo tenant encima del VPS
- Cambiar claves master para “probar login”
- Auto-abrir el dropdown de Acceso al cargar o cerrar sesión
- Desplegar sin backup
- Saltarse `verify_consola.py`

## Rollback manual

```bash
BK=/root/backups/erp_master/<timestamp>
rsync -a "$BK/code/" /root/erp_master/
systemctl restart erp-master-web
```

## Credenciales

Las claves **no se resetean** en deploy. Usuario master en `/root/erp_master.db`. Cambios de clave solo desde consola → Usuarios consola.
