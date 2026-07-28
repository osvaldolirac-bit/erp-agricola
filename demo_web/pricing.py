"""Precios mensuales de módulos Agrícola (tenant DEMO / lanzamiento).

Eje estratégico: COSTOS. El ERP nació para entender el costo de producir
por centro de costo; el resto de módulos se incorporó al resolver dolores
del campo, el patio y la oficina.
"""
from __future__ import annotations

from typing import Any

# CLP / mes — precios de lanzamiento Agrícola.
MODULOS_FEE: dict[str, dict[str, Any]] = {
    "dashboard": {
        "label": "Dashboard",
        "fee": 0,
        "fee_txt": "Incluido",
        "pitch": "Vista general de la operación",
        "funciones": [
            "Indicadores clave del fundo",
            "Acceso rápido a los módulos activos",
            "Resumen de costos, compras y campo",
        ],
    },
    "libro_campo": {
        "label": "Libro de Campo",
        "fee": 14_900,
        "fee_txt": "$14.900/mes",
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
        "fee": 12_900,
        "fee_txt": "$12.900/mes",
        "pitch": "Operación específica Campo B",
        "funciones": [
            "Seguimiento operativo del sector Campo B",
            "Registros alineados al resto del fundo",
            "Apoyo a costos y labores por centro",
        ],
    },
    "globalgap": {
        "label": "GlobalGAP",
        "fee": 14_900,
        "fee_txt": "$14.900/mes",
        "pitch": "Certificación y cumplimiento",
        "funciones": [
            "Checklist y evidencias de certificación",
            "PPPL y documentación asociada",
            "Trazabilidad para auditorías",
        ],
    },
    "maquinaria": {
        "label": "Maquinaria",
        "fee": 16_900,
        "fee_txt": "$16.900/mes",
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
        "fee": 14_900,
        "fee_txt": "$14.900/mes",
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
        "fee": 12_900,
        "fee_txt": "$12.900/mes",
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
        "fee": 14_900,
        "fee_txt": "$14.900/mes",
        "pitch": "Salidas de combustible controladas",
        "funciones": [
            "Registro de salidas de petróleo",
            "Enlaces / QR de carga personal",
            "Autorizados y trazabilidad",
            "Costo de combustible por operación",
        ],
    },
    "tesoreria": {
        "label": "Tesorería",
        "fee": 12_900,
        "fee_txt": "$12.900/mes",
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
        "fee": 16_900,
        "fee_txt": "$16.900/mes",
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
        "fee": 22_900,
        "fee_txt": "$22.900/mes",
        "pitch": "Eje del ERP: cuánto cuesta producir",
        "eje": True,
        "funciones": [
            "Centros de costo y prorrateo",
            "Consolidación de gastos del fundo",
            "Visión por cuartel / actividad",
            "Nació aquí la idea del ERP Agrícola",
            "Se nutre de RRHH, compras, petróleo y campo",
        ],
    },
    "flujo": {
        "label": "Flujo financiero",
        "fee": 14_900,
        "fee_txt": "$14.900/mes",
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


PACK_CAMPO = {
    "nombre": "Pack Campo",
    "fee": 46_900,
    "fee_txt": "$46.900/mes",
    "modulos": (
        "dashboard",
        "libro_campo",
        "campob",
        "globalgap",
        "maquinaria",
        "admin",
        "soporte",
    ),
    "ahorro_vs_suma": True,
    "setup_unico": 29_900,
    "setup_txt": "$29.900 setup (único)",
    "moneda": "CLP",
    "ciclo": "mensual",
    "incluye_extra": [
        "Respaldo de datos permanente por seguridad",
        "Labores, certificación y maquinaria en un plan",
    ],
}


PACK_PATIO = {
    "nombre": "Pack Patio",
    "fee": 44_900,
    "fee_txt": "$44.900/mes",
    "modulos": (
        "dashboard",
        "compras",
        "bodega",
        "petroleo",
        "tesoreria",
        "admin",
        "soporte",
    ),
    "ahorro_vs_suma": True,
    "setup_unico": 29_900,
    "setup_txt": "$29.900 setup (único)",
    "moneda": "CLP",
    "ciclo": "mensual",
    "incluye_extra": [
        "Respaldo de datos permanente por seguridad",
        "Flujo Compra → Bodega / Petróleo → pago en Tesorería",
    ],
}


PACK_OFICINA = {
    "nombre": "Pack Oficina",
    "fee": 49_900,
    "fee_txt": "$49.900/mes",
    "modulos": (
        "dashboard",
        "rrhh",
        "costos",
        "flujo",
        "admin",
        "soporte",
    ),
    "ahorro_vs_suma": True,
    "setup_unico": 34_900,
    "setup_txt": "$34.900 setup (único)",
    "moneda": "CLP",
    "ciclo": "mensual",
    "badge": "Eje Costos",
    "incluye_extra": [
        "Respaldo de datos permanente por seguridad",
        "Costos como eje: RRHH + Flujo alimentan el costo real",
        "Así nació este ERP; el resto se sumó con los dolores del campo",
    ],
}


PACK = {
    "nombre": "Pack Agrícola",
    "fee": 99_900,
    "fee_txt": "$99.900/mes",
    "modulos": (
        "dashboard",
        "libro_campo",
        "campob",
        "globalgap",
        "maquinaria",
        "compras",
        "bodega",
        "petroleo",
        "tesoreria",
        "rrhh",
        "costos",
        "flujo",
        "admin",
        "soporte",
    ),
    "ahorro_vs_suma": True,
    "setup_unico": 59_900,
    "setup_txt": "$59.900 setup (único)",
    "moneda": "CLP",
    "ciclo": "mensual",
    "incluye_extra": [
        "Respaldo de datos permanente por seguridad",
        "Campo + Patio + Oficina (eje Costos) en un solo plan",
    ],
}


def clp(n: Any) -> str:
    try:
        v = int(round(float(n or 0)))
    except (TypeError, ValueError):
        v = 0
    return f"${v:,}".replace(",", ".")


def suma_modulos() -> int:
    return sum(int(m["fee"]) for m in MODULOS_FEE.values())


def suma_modulos_keys(keys: tuple[str, ...] | list[str]) -> int:
    return sum(int(MODULOS_FEE[k]["fee"]) for k in keys if k in MODULOS_FEE)


def fee_for(active_key: str) -> dict[str, Any] | None:
    return MODULOS_FEE.get(active_key)


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
    }
