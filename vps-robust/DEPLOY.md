# ERP Agrícola VPS — Despliegue industrial (anti-regresión)

**Fuente de verdad:** `/root/demo-web` + git local. **GitHub no gobierna producción.**

## Comando único obligatorio

```bash
/root/scripts/deploy-demo-web.sh
```

Flujo: **backup → sync scripts → regression guard → compileall → restart 3 servicios → verify → regression → alerta si falla + rollback**

## Respaldos automáticos (cron)

| Componente | Rol |
|------------|-----|
| `demo_web/tenants.py` | Registro tenants agrícola |
| `demo_web/services/respaldo_cron_clientes.py` | Deriva CLIENTES del cron desde tenants |
| `/root/scripts/erp_respaldo_cron.py` | Cron diario DATOS + código (03:00 Chile) |
| `verify_agricola.py` | Falla si un tenant agrícola no está en el cron |

**Regla:** nuevo tenant agrícola = entrada en `tenants.py` → queda automáticamente en el cron tras deploy.

Crontab sugerido:

```bash
0 3 * * * /usr/bin/python3 /root/scripts/erp_respaldo_cron.py >> /root/logs/erp_respaldo.log 2>&1
```

Forzar envío manual: `python3 /root/scripts/erp_respaldo_cron.py --forzar`

## Capas anti-regresión (Libro de Campo y agrícola)

| Capa | Qué hace |
|------|----------|
| `.erp_regression_manifest.json` | Marcadores obligatorios en código (cabecera LC, especies, imports) |
| `regression_guard_agricola.py` | Falla si falta `_guardar_evento_meta`, `form_fecha`, etc. |
| `verify_agricola.py` | HTTP + session meta roundtrip + manifest |
| `git pre-commit` | Bloquea commit que borra fixes LC |
| `agricola_health_watch.sh` | Cron cada 30 min — alerta en log si algo se rompe solo |
| Alertas | `/root/erp_status/agricola_alerts.log` |

## Prohibido

- `scp` suelto de `libro_campo.py` sin deploy script
- `patch_lc_globalgap_nombres.py` sin `--force`
- Reiniciar servicios agrícola sin verify

## Si verify falla

1. Ver `/root/erp_status/agricola_alerts.log`
2. Rollback automático ya corrió; si no: `rsync -a /root/backups/demo-web/ULTIMO/code/ /root/demo-web/`
3. `systemctl restart erp-agricola-web erp-lc-web erp-demo-web`

## Constantes (no mezclar)

- `LIBRO_CAMPO_ESPECIES` → cultivos (Cerezos, Ciruelos, Nogales)
- `GAP_ESPECIES` / `GAP_AMBITOS` → ámbitos GlobalGAP (razones sociales)

## Vigilancia

```bash
# Manual
/root/demo-web/.venv/bin/python3 /root/scripts/verify_agricola.py

# Log alertas
tail -f /root/erp_status/agricola_alerts.log
```

Cron: `*/30 * * * * /root/scripts/agricola_health_watch.sh`
