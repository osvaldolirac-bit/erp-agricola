"""Precios mensuales de módulos Agrícola (tenant DEMO / lanzamiento).

Eje estratégico: COSTOS. El ERP nació para entender el costo de producir
por centro de costo; el resto de módulos se incorporó al resolver dolores
del campo, el patio y la oficina.

Todos los montos están en CLP con IVA incluido (19%).

Conexión de packs
-----------------
Los packs no son un listado suelto: agrupan módulos que ya se conectan
en la operación diaria.

- Pack Campo: labores (Libro / Campo B) → GlobalGAP + Maquinaria
- Pack Patio: Compra → Bodega / Petróleo / Riego → pago en Tesorería
- Pack Oficina: RRHH + Costos + Flujo + Compras + Tesorería
- Pack Agrícola: unión de Campo + Patio + Oficina
"""
from __future__ import annotations

from typing import Any

# IVA Chile — todos los fees de este módulo se publican IVA incluido.
IVA_PCT = 0.19
PRECIOS_CON_IVA = True
IVA_LABEL = "IVA incluido"


def clp(n: Any) -> str:
    try:
        v = int(round(float(n or 0)))
    except (TypeError, ValueError):
        v = 0
    return f"${v:,}".replace(",", ".")


def _fee_txt(fee: int) -> str:
    if int(fee or 0) <= 0:
        return "Incluido"
    return f"{clp(fee)}/mes · {IVA_LABEL}"


def _setup_txt(setup: int) -> str:
    return f"{clp(setup)} setup (único) · {IVA_LABEL}"


# CLP / mes — precios de lanzamiento Agrícola (IVA incluido).
MODULOS_FEE: dict[str, dict[str, Any]] = {
    "dashboard": {
        "label": "Dashboard",
        "fee": 0,
        "fee_txt": "Incluido",
        "pitch": "Vista general de la operación",
        "funciones": [
            "Indicadores clave del campo",
            "Acceso rápido a los módulos activos",
            "Resumen de costos, compras y campo",
        ],
    },
    "libro_campo": {
        "label": "Libro de Campo",
        "fee": 17_900,
        "fee_txt": _fee_txt(17_900),
        "pitch": "Labores y registros del día a día",
        "funciones": [
            "Registro de labores por cuartel y fecha",
            "Cuadrillas, insumos y observaciones",
            "Historial listo para auditoría y GlobalGAP",
            "Exportación / respaldo de bitácora",
        ],
    },
    "campob": {
        "label": "Campo B",
        "fee": 15_900,
        "fee_txt": _fee_txt(15_900),
        "pitch": "Operación específica Campo B",
        "funciones": [
            "Seguimiento operativo del sector Campo B",
            "Registros alineados al resto del campo",
            "Apoyo a costos y labores por centro",
        ],
    },
    "globalgap": {
        "label": "GlobalGAP",
        "fee": 17_900,
        "fee_txt": _fee_txt(17_900),
        "pitch": "Certificación y cumplimiento",
        "funciones": [
            "Checklist y evidencias de certificación",
            "PPPL y documentación asociada",
            "Trazabilidad para auditorías",
        ],
    },
    "maquinaria": {
        "label": "Maquinaria",
        "fee": 20_900,
        "fee_txt": _fee_txt(20_900),
        "pitch": "Bitácora y mantención de equipos",
        "funciones": [
            "Historial por máquina / caso",
            "Estados: abierto → observación → reparación → cierre",
            "Observaciones por etapa",
            "Control de mantenciones y costos asociados",
        ],
    },
    "compras": {
        "label": "Compras",
        "fee": 17_900,
        "fee_txt": _fee_txt(17_900),
        "pitch": "Proveedores y facturas de compra",
        "funciones": [
            "Maestro de proveedores",
            "Registro de compras e ítems",
            "Vínculo con bodega y tesorería",
            "Historial de documentos",
        ],
    },
    "bodega": {
        "label": "Bodega",
        "fee": 15_900,
        "fee_txt": _fee_txt(15_900),
        "pitch": "Stock e inventario de insumos",
        "funciones": [
            "Inventario con movimientos",
            "Entradas desde compras",
            "Salidas a labores / consumo",
            "Visibilidad de existencias",
        ],
    },
    "petroleo": {
        "label": "Petróleo",
        "fee": 17_900,
        "fee_txt": _fee_txt(17_900),
        "pitch": "Salidas de combustible controladas",
        "funciones": [
            "Registro de salidas de petróleo",
            "Enlaces personales de carga (Salida Link)",
            "Autorizados y trazabilidad",
            "Costo de combustible por operación",
        ],
    },
    "riego": {
        "label": "Riego",
        "fee": 15_900,
        "fee_txt": _fee_txt(15_900),
        "pitch": "Riego y fertilización por huerto",
        "funciones": [
            "Registro manual imputado a centro de costo / huerto",
            "Modos por horas o por surcos (m³ automático)",
            "Enlaces personales del regador (Registro Link)",
            "Fertilización opcional por registro",
            "Autorización admin antes de imputar al CC",
            "Trazabilidad de agua aplicada a la operación",
        ],
    },
    "tesoreria": {
        "label": "Tesorería",
        "fee": 15_900,
        "fee_txt": _fee_txt(15_900),
        "pitch": "Pagos a proveedores (CxP)",
        "funciones": [
            "Cola de saldos por pagar",
            "Registro de pagos y abonos",
            "Medios de pago y banco cuando aplica",
            "Historial de egresos",
        ],
    },
    "rrhh": {
        "label": "RRHH",
        "fee": 20_900,
        "fee_txt": _fee_txt(20_900),
        "pitch": "Personas y sueldos al costo",
        "funciones": [
            "Trabajadores y contratos",
            "Imputación de sueldos a centros de costo",
            "Prorrateo por superficies / %",
            "Base para el módulo Costos",
        ],
    },
    "costos": {
        "label": "Costos",
        "fee": 27_900,
        "fee_txt": _fee_txt(27_900),
        "pitch": "Eje del ERP: cuánto cuesta producir",
        "eje": True,
        "funciones": [
            "Centros de costo y prorrateo",
            "Consolidación de gastos del campo",
            "Visión por cuartel / actividad",
            "Nació aquí la idea del ERP Agrícola",
            "Se nutre de RRHH, compras, petróleo, riego y campo",
        ],
    },
    "flujo": {
        "label": "Flujo financiero",
        "fee": 17_900,
        "fee_txt": _fee_txt(17_900),
        "pitch": "Entradas y salidas de caja",
        "funciones": [
            "Movimientos de flujo de caja",
            "Visión oficina de la operación",
            "Complemento natural de Costos y Tesorería",
        ],
    },
    "admin": {
        "label": "Administración",
        "fee": 0,
        "fee_txt": "Incluido",
        "pitch": "Datos de la empresa y usuarios",
        "funciones": [
            "Datos de empresa",
            "Usuarios y perfiles",
            "Configuración operativa del tenant",
        ],
    },
    "manual": {
        "label": "Manual",
        "fee": 0,
        "fee_txt": "Incluido",
        "pitch": "Guía de uso del ERP",
        "funciones": [
            "Manual operativo por módulo",
            "Referencia rápida para el equipo",
        ],
    },
    "soporte": {
        "label": "Soporte",
        "fee": 0,
        "fee_txt": "Incluido",
        "pitch": "Ayuda y tickets",
        "funciones": [
            "Tickets de soporte",
            "Seguimiento de incidencias",
            "Canal para consultar planes y activaciones",
        ],
    },
}


# Clave pricing → key de menú Streamlit / active_key Flask
PRICING_TO_MENU_KEY: dict[str, str] = {
    "dashboard": "DASHBOARD",
    "libro_campo": "Libro de Campo",
    "campob": "Campob",
    "globalgap": "GlobalGAP",
    "maquinaria": "Maquinaria",
    "compras": "Compras",
    "bodega": "Bodega",
    "petroleo": "Petróleo",
    "riego": "Riego",
    "tesoreria": "Tesoreria",
    "rrhh": "RRHH",
    "costos": "Costos",
    "flujo": "Flujo financiero",
    "admin": "Administracion",
    "manual": "Manual",
    "soporte": "Soporte",
}

# Clave pricing → slug de ruta /modules/<slug>
PRICING_TO_SLUG: dict[str, str] = {
    "dashboard": "dashboard",
    "libro_campo": "libro-campo",
    "campob": "campob",
    "globalgap": "globalgap",
    "maquinaria": "maquinaria",
    "compras": "compras",
    "bodega": "bodega",
    "petroleo": "petroleo",
    "riego": "riego",
    "tesoreria": "tesoreria",
    "rrhh": "rrhh",
    "costos": "costos",
    "flujo": "flujo",
    "admin": "admin",
    "manual": "manual",
    "soporte": "soporte",
}

# Dependencias blandas: al armar un pack o contratar por módulo,
# estos vínculos ya existen en la operación (no bloquean, orientan).
MODULO_DEPS: dict[str, tuple[str, ...]] = {
    "globalgap": ("libro_campo",),
    "bodega": ("compras",),
    "tesoreria": ("compras",),
    "costos": ("rrhh",),
}

# Incluidos en todo plan (no se cobran aparte).
MODULOS_BASE: tuple[str, ...] = ("dashboard", "admin", "manual", "soporte")

# Núcleos operativos por pack (sin base).
NUCLEO_CAMPO: tuple[str, ...] = (
    "libro_campo",
    "campob",
    "globalgap",
    "maquinaria",
)
NUCLEO_PATIO: tuple[str, ...] = (
    "compras",
    "bodega",
    "petroleo",
    "riego",
    "tesoreria",
)
# Oficina: eje Costos + compras/pagos para cerrar el ciclo administrativo.
NUCLEO_OFICINA: tuple[str, ...] = (
    "rrhh",
    "costos",
    "flujo",
    "compras",
    "tesoreria",
)


def _pack_modulos(*nucleos: tuple[str, ...]) -> tuple[str, ...]:
    seen: list[str] = []
    for key in MODULOS_BASE:
        if key not in seen:
            seen.append(key)
    for nucleo in nucleos:
        for key in nucleo:
            if key not in seen:
                seen.append(key)
    return tuple(seen)


PACK_CAMPO = {
    "nombre": "Pack Campo",
    "fee": 55_900,
    "fee_txt": _fee_txt(55_900),
    "modulos": _pack_modulos(NUCLEO_CAMPO),
    "nucleo": NUCLEO_CAMPO,
    "flujo": "Labores (Libro de Campo / Campo B) → GlobalGAP + Maquinaria",
    "ahorro_vs_suma": True,
    "setup_unico": 35_900,
    "setup_txt": _setup_txt(35_900),
    "moneda": "CLP",
    "ciclo": "mensual",
    "iva_incluido": True,
    "incluye_extra": [
        "Respaldo de datos permanente por seguridad",
        "Labores, certificación y maquinaria en un plan",
        IVA_LABEL,
    ],
}


PACK_PATIO = {
    "nombre": "Pack Patio",
    "fee": 65_900,
    "fee_txt": _fee_txt(65_900),
    "modulos": _pack_modulos(NUCLEO_PATIO),
    "nucleo": NUCLEO_PATIO,
    "flujo": "Compra → Bodega / Petróleo / Riego → pago en Tesorería",
    "ahorro_vs_suma": True,
    "setup_unico": 35_900,
    "setup_txt": _setup_txt(35_900),
    "moneda": "CLP",
    "ciclo": "mensual",
    "iva_incluido": True,
    "incluye_extra": [
        "Respaldo de datos permanente por seguridad",
        "Flujo Compra → Bodega / Petróleo / Riego → pago en Tesorería",
        IVA_LABEL,
    ],
}


PACK_OFICINA = {
    "nombre": "Pack Oficina",
    "fee": 84_900,
    "fee_txt": _fee_txt(84_900),
    "modulos": _pack_modulos(NUCLEO_OFICINA),
    "nucleo": NUCLEO_OFICINA,
    "flujo": "RRHH → Costos + Flujo; Compras → Tesorería (pago proveedores)",
    "ahorro_vs_suma": True,
    "setup_unico": 41_900,
    "setup_txt": _setup_txt(41_900),
    "moneda": "CLP",
    "ciclo": "mensual",
    "badge": "Eje Costos",
    "iva_incluido": True,
    "incluye_extra": [
        "Respaldo de datos permanente por seguridad",
        "Costos como eje: RRHH + Flujo + Compras + Tesorería",
        "Así nació este ERP; el resto se sumó con los dolores del campo",
        IVA_LABEL,
    ],
}


PACK = {
    "nombre": "Pack Agrícola",
    "fee": 129_990,
    "fee_txt": _fee_txt(129_990),
    "modulos": _pack_modulos(NUCLEO_CAMPO, NUCLEO_PATIO, NUCLEO_OFICINA),
    "nucleo": NUCLEO_CAMPO + NUCLEO_PATIO + NUCLEO_OFICINA,
    "flujo": "Campo + Patio + Oficina (eje Costos) en un solo plan",
    "ahorro_vs_suma": True,
    "setup_unico": 71_900,
    "setup_txt": _setup_txt(71_900),
    "moneda": "CLP",
    "ciclo": "mensual",
    "iva_incluido": True,
    "incluye_extra": [
        "Respaldo de datos permanente por seguridad",
        "Campo + Patio + Oficina (eje Costos) en un solo plan",
        IVA_LABEL,
    ],
}


def suma_modulos() -> int:
    return sum(int(m["fee"]) for m in MODULOS_FEE.values())


def suma_modulos_keys(keys: tuple[str, ...] | list[str]) -> int:
    return sum(int(MODULOS_FEE[k]["fee"]) for k in keys if k in MODULOS_FEE)


def fee_for(active_key: str) -> dict[str, Any] | None:
    return MODULOS_FEE.get(active_key)


def labels_for_keys(keys: tuple[str, ...] | list[str]) -> list[str]:
    out: list[str] = []
    for k in keys:
        m = MODULOS_FEE.get(k)
        if m:
            out.append(str(m["label"]))
    return out


def deps_faltantes(keys: tuple[str, ...] | list[str]) -> dict[str, tuple[str, ...]]:
    """Deps recomendadas ausentes en el conjunto elegido."""
    chosen = set(keys)
    missing: dict[str, tuple[str, ...]] = {}
    for key in keys:
        need = tuple(d for d in MODULO_DEPS.get(key, ()) if d not in chosen)
        if need:
            missing[key] = need
    return missing


def validar_conexion_packs() -> list[str]:
    """Chequeos de armado: packs coherentes con deps y unión = Pack Agrícola."""
    issues: list[str] = []
    for pack in (PACK_CAMPO, PACK_PATIO, PACK_OFICINA, PACK):
        miss = deps_faltantes(pack["modulos"])
        for mod, deps in miss.items():
            issues.append(
                f"{pack['nombre']}: {mod} recomienda {', '.join(deps)}"
            )
    union = set(PACK_CAMPO["modulos"]) | set(PACK_PATIO["modulos"]) | set(PACK_OFICINA["modulos"])
    if union != set(PACK["modulos"]):
        issues.append(
            "Pack Agrícola no coincide con la unión Campo+Patio+Oficina: "
            f"extra={sorted(set(PACK['modulos']) - union)} "
            f"faltan={sorted(union - set(PACK['modulos']))}"
        )
    for key in PACK["modulos"]:
        if key not in MODULOS_FEE:
            issues.append(f"Pack Agrícola referencia módulo sin fee: {key}")
        if key not in PRICING_TO_MENU_KEY or key not in PRICING_TO_SLUG:
            issues.append(f"Pack Agrícola sin mapa menú/slug: {key}")
    return issues


def pricing_context(tenant_slug: str | None) -> dict[str, Any]:
    """Fees visibles en el ERP del tenant DEMO Agrícola."""
    slug = (tenant_slug or "").strip().lower()
    show = slug == "demo"
    suma = suma_modulos()
    suma_campo = suma_modulos_keys(PACK_CAMPO["modulos"])
    suma_patio = suma_modulos_keys(PACK_PATIO["modulos"])
    suma_oficina = suma_modulos_keys(PACK_OFICINA["modulos"])
    return {
        "show_module_fees": show,
        "show_planes": show,
        "module_fees": MODULOS_FEE if show else {},
        "pricing_pack": PACK if show else None,
        "pricing_pack_campo": PACK_CAMPO if show else None,
        "pricing_pack_patio": PACK_PATIO if show else None,
        "pricing_pack_oficina": PACK_OFICINA if show else None,
        "pricing_suma": suma if show else 0,
        "pricing_suma_campo": suma_campo if show else 0,
        "pricing_suma_patio": suma_patio if show else 0,
        "pricing_suma_oficina": suma_oficina if show else 0,
        "pricing_ahorro": max(0, suma - int(PACK["fee"])) if show else 0,
        "pricing_ahorro_campo": max(0, suma_campo - int(PACK_CAMPO["fee"])) if show else 0,
        "pricing_ahorro_patio": max(0, suma_patio - int(PACK_PATIO["fee"])) if show else 0,
        "pricing_ahorro_oficina": max(0, suma_oficina - int(PACK_OFICINA["fee"])) if show else 0,
        "pricing_iva_incluido": PRECIOS_CON_IVA if show else False,
        "pricing_iva_pct": IVA_PCT if show else 0,
        "pricing_iva_label": IVA_LABEL if show else "",
    }
