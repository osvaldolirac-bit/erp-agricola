# Paridad tenants agrícola LC vs El Espino

Misma app Flask (`app_concepcion`), distinta DB y **distintas reglas**. Esta tabla es la fuente de verdad operativa.

## Matriz de reglas

| Regla | La Concepción | El Espino |
|-------|---------------|-----------|
| CxP Tesorería | Saldo **neto** (resta imputación Costos) | Saldo **bruto** hasta pago |
| Documentos `INT-*` en CxP | Excluidos | Incluidos |
| Razón social en queries | Excluye "El Espino" | No excluye (solo El Espino) |
| Flujo financiero | No imputa gastado contable lump-sum | Imputa gastado contable |
| Logo ERP Master fijo | Sí | Sí |
| Pago Tesorería | Proveedor desde **doc_ids** en BD | Igual |

Implementación central: `demo_web/services/tenant_rules.py`

## Procedimiento único de deploy (VPS)

```bash
cd /root/demo-web-src && git pull
bash vps-robust/scripts/deploy-demo-web.sh
```

El script **aborta y hace rollback** si falla cualquiera de:

1. `verify_tenant_parity.py` — reglas LC/Espino en código + tests unitarios
2. `verify_agricola.py` — LC no regresó (Libro de Campo, CSS, manifest)
3. `verify_espino.py` — bitácora, cron, CxP en BD Espino, paridad Compras↔Tesorería

**No usar scp suelto.** No desplegar sin este script.

## Antes de commit (local o VPS)

```bash
APP_ROOT=/ruta/al/repo python3 scripts/verify_tenant_parity.py
```

Hook opcional en VPS:

```bash
cp vps-robust/scripts/git-pre-commit-tenant-parity.sh .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

## Bootstrap tenant Espino nuevo

```bash
python3 scripts/bootstrap_espino_tenant.py
python3 scripts/ensure_espino_operativo.py
APP_ROOT=/root/demo-web python3 scripts/verify_espino.py
```

## Si agregas un tercer tenant LC

1. Añadir entrada en `tenant_rules.py` (`TenantRuleSet` + `_BY_SLUG`)
2. Añadir en `tenants.py`
3. Extender `verify_tenant_parity.py` y `verify_espino.py` (o crear `verify_<slug>.py`)
4. Documentar fila en esta matriz

## Por qué falló Espino antes

- Reglas LC aplicadas por error (`is_concepcion_tenant()` como default)
- Config VPS fuera del código (bitácora, cron, secrets)
- Verify solo miraba LC, no Espino
- Reglas dispersas en 15 archivos sin fuente única

Con `tenant_rules.py` + verify obligatorio, un deploy roto **no entra** a producción.
