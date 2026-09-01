"""Precios mensuales de módulos Comercial (tenant DEMO / lanzamiento)."""
from __future__ import annotations

from typing import Any

# CLP / mes — precios de lanzamiento Comercial.
MODULOS_FEE: dict[str, dict[str, Any]] = {
    "dashboard": {
        "label": "Dashboard",
        "fee": 0,
        "fee_txt": "Incluido",
        "pitch": "Vista general del negocio",
        "funciones": [
            "Indicadores de cotizaciones, aprobadas y conversión",
            "Cartera de clientes (CxC): saldo y vencidos",
            "Deuda y vencimientos de Tesorería (CxP)",
            "Widgets de a 2 con colores ingresos / egresos",
            "Top clientes y proveedores por deuda",
            "Acceso rápido a los módulos del ERP",
        ],
    },
    "clientes": {
        "label": "Clientes",
        "fee": 12_900,
        "fee_txt": "$12.900/mes",
        "pitch": "Base de clientes y contactos",
        "funciones": [
            "Alta y edición de clientes (RUT, razón social, contacto)",
            "Teléfono, email, dirección y comuna",
            "Listado con búsqueda para seguimiento comercial",
            "Ficha lista para cotizar y cobrar",
        ],
    },
    "cotizaciones": {
        "label": "Cotizaciones",
        "fee": 19_900,
        "fee_txt": "$19.900/mes",
        "pitch": "Propuestas comerciales completas",
        "funciones": [
            "Crear cotizaciones con ítems, cantidades y precios",
            "Tipo de venta: servicio o producto",
            "Gastos generales, utilidad e IVA automáticos",
            "Estados: borrador, enviada, aprobada, rechazada",
            "PDF descargable para enviar al cliente",
            "Versiones y vínculo con cuentas por cobrar",
        ],
    },
    "cuentas": {
        "label": "Cuentas por cobrar",
        "fee": 19_900,
        "fee_txt": "$19.900/mes",
        "pitch": "Cobranza y control de pagos",
        "funciones": [
            "Documentos por cobrar (EP, facturas y saldos)",
            "Registro de abonos con medio y nota",
            "Saldo actualizado y estado de cada documento",
            "Vista 360° del cliente y PDF de cobranza",
            "Alerta por correo al registrar un pago/abono",
        ],
    },
    "ordenes": {
        "label": "Órdenes de compra",
        "fee": 9_900,
        "fee_txt": "$9.900/mes",
        "pitch": "Paso previo a la factura de proveedor",
        "funciones": [
            "Crear OC con ítems, costos y proveedor",
            "Estados: borrador, emitida, convertida, anulada",
            "Folio automático (OC-0001…)",
            "Emitir compra según OC (obligatorio vincular)",
            "Campo Nº factura proveedor al recibir el documento",
        ],
    },
    "compras": {
        "label": "Compras",
        "fee": 14_900,
        "fee_txt": "$14.900/mes",
        "pitch": "Facturas de proveedores desde OC",
        "funciones": [
            "Maestro de proveedores",
            "Emisión de compra solo vinculada a una OC",
            "Anota Nº factura / boleta / guía del proveedor",
            "Ítems servicio o material (heredados de la OC)",
            "Entrada opcional a bodega",
            "Historial de pagos en solo lectura (sin pagar aquí)",
        ],
    },
    "centros": {
        "label": "Centro de costos",
        "fee": 12_900,
        "fee_txt": "$12.900/mes",
        "pitch": "Imputa gastos y compras por área",
        "funciones": [
            "Alta y edición de centros de costo",
            "Activar o desactivar centros según la operación",
            "Imputación obligatoria al emitir compras",
            "Un centro de costo por cada compra",
            "Base para analizar gastos por área o proyecto",
        ],
    },
    "tesoreria": {
        "label": "Tesorería",
        "fee": 12_900,
        "fee_txt": "$12.900/mes",
        "pitch": "Único lugar para pagar a proveedores",
        "funciones": [
            "Cola de saldos por pagar (CxP)",
            "Registro de pagos y abonos a proveedores",
            "Historial de egresos",
            "KPI de deuda y vencidos en el Dashboard",
            "Cobros de clientes siguen en CxC",
        ],
    },
    "bodega": {
        "label": "Bodega",
        "fee": 12_900,
        "fee_txt": "$12.900/mes",
        "pitch": "Stock e inventario",
        "funciones": [
            "Maestra de productos",
            "Inventario con costo promedio",
            "Entradas desde compras",
            "Salidas al aprobar cotización de producto",
            "Movimientos manuales",
        ],
    },
    "mercadolibre": {
        "label": "Integración Mercado Libre",
        "fee": 29_900,
        "fee_txt": "$29.900/mes",
        "pitch": "Add-on premium: stock, ventas y pagos ML en tu ERP",
        "addon": True,
        "setup_unico": 49_900,
        "setup_txt": "$49.900 setup (1ª cuenta ML)",
        "funciones": [
            "Publicaciones / stock ↔ Bodega (entradas, salidas, stock)",
            "Ventas / órdenes → cotización aprobada o documento de venta",
            "Boletas / facturas ML → CxC + PDF / registro",
            "Pagos ML → abonos en Cuentas por cobrar",
            "Envíos (opcional) → estado en la venta",
            "No incluido en los packs: se suma al plan elegido",
        ],
    },
    "admin": {
        "label": "Administración",
        "fee": 0,
        "fee_txt": "Incluido",
        "pitch": "Datos de la empresa",
        "funciones": [
            "Datos de empresa (RUT, razón social, contacto)",
            "Parámetros: IVA, GG, utilidad, validez y crédito",
            "Cambio de clave personal del usuario",
        ],
    },
    "soporte": {
        "label": "Soporte",
        "fee": 0,
        "fee_txt": "Incluido",
        "pitch": "Ayuda y tickets",
        "funciones": [
            "Abrir ticket describiendo el problema",
            "Historial de mis tickets y su estado",
            "Ver respuesta del administrador",
            "Aviso por correo al crear y al responder",
            "Respaldo de datos permanente por seguridad",
        ],
    },
}

PACK_VENTAS = {
    "nombre": "Pack Ventas",
    "fee": 42_900,
    "fee_txt": "$42.900/mes",
    "modulos": (
        "dashboard",
        "clientes",
        "cotizaciones",
        "cuentas",
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
        "Flujo Cliente → Cotización → CxC",
    ],
}


PACK_COMPRAS = {
    "nombre": "Pack Compras",
    "fee": 52_800,
    "fee_txt": "$52.800/mes",
    "modulos": (
        "dashboard",
        "ordenes",
        "compras",
        "centros",
        "tesoreria",
        "bodega",
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
        "Flujo OC → Compra (1 centro de costo) → Tesorería",
    ],
}


PACK = {
    "nombre": "Plan Total",
    "fee": 82_800,
    "fee_txt": "$82.800/mes",
    "modulos": (
        "dashboard",
        "clientes",
        "cotizaciones",
        "cuentas",
        "ordenes",
        "compras",
        "centros",
        "tesoreria",
        "bodega",
        "admin",
        "soporte",
    ),
    "ahorro_vs_suma": True,
    "setup_unico": 49_900,
    "setup_txt": "$49.900 setup (único)",
    "moneda": "CLP",
    "ciclo": "mensual",
    "incluye_extra": [
        "Respaldo de datos permanente por seguridad",
        "Flujo OC → Compra (1 centro de costo) → Tesorería integrado",
    ],
}


def suma_modulos() -> int:
    """Suma módulos base (excluye add-ons como Mercado Libre)."""
    return sum(int(m["fee"]) for m in MODULOS_FEE.values() if not m.get("addon"))


def fee_for(active_key: str) -> dict[str, Any] | None:
    return MODULOS_FEE.get(active_key)


MODULOS_FEE_TALLER: dict[str, dict[str, Any]] = {
    **{k: v for k, v in MODULOS_FEE.items() if k != "mercadolibre"},
    "cotizaciones": {
        **MODULOS_FEE["cotizaciones"],
        "pitch": "Presupuestos de servicio con patente y mano de obra",
        "funciones": [
            "Cotizaciones de servicio y repuestos",
            "Patente del vehículo en cada presupuesto",
            "Gastos generales, utilidad e IVA automáticos",
            "Al aprobar servicio → genera orden de trabajo (OT)",
            "PDF para el cliente y vínculo con CxC",
        ],
    },
    "taller_ot": {
        "label": "Órdenes de trabajo",
        "fee": 19_900,
        "fee_txt": "$19.900/mes",
        "pitch": "OT desde cotización aprobada",
        "funciones": [
            "Folio OT automático (OT-NNNN)",
            "Se crea al aprobar cotización tipo servicio",
            "Patente, mecánico y estado de la OT",
            "Seguimiento por vehículo en el taller",
        ],
    },
    "rrhh": {
        "label": "RRHH · Sueldos",
        "fee": 12_900,
        "fee_txt": "$12.900/mes",
        "pitch": "Sueldos imputados a centros de costo",
        "funciones": [
            "Trabajadores del taller",
            "Imputación líquido + leyes por persona",
            "Reparto automático entre CC activos",
            "Impacto en matriz de centros de costo",
        ],
    },
}

PACK_TALLER_VENTAS = {
    "nombre": "Pack Taller Ventas",
    "fee": 59_900,
    "fee_txt": "$59.900/mes",
    "modulos": (
        "dashboard",
        "clientes",
        "cotizaciones",
        "cuentas",
        "taller_ot",
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
        "Flujo Cliente → Cotización → OT → CxC",
    ],
}

PACK_TALLER_OPERACIONES = {
    "nombre": "Pack Operaciones",
    "fee": 62_900,
    "fee_txt": "$62.900/mes",
    "modulos": (
        "dashboard",
        "ordenes",
        "compras",
        "centros",
        "tesoreria",
        "bodega",
        "rrhh",
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
        "Flujo OC → Compra → CC → Tesorería + RRHH",
    ],
}

PACK_TALLER = {
    "nombre": "Plan Taller Total",
    "fee": 99_900,
    "fee_txt": "$99.900/mes",
    "modulos": (
        "dashboard",
        "clientes",
        "cotizaciones",
        "cuentas",
        "taller_ot",
        "ordenes",
        "compras",
        "centros",
        "tesoreria",
        "bodega",
        "rrhh",
        "admin",
        "soporte",
    ),
    "ahorro_vs_suma": True,
    "setup_unico": 49_900,
    "setup_txt": "$49.900 setup (único)",
    "moneda": "CLP",
    "ciclo": "mensual",
    "incluye_extra": [
        "Respaldo de datos permanente por seguridad",
        "Recepción, OT, repuestos, sueldos y cobranza integrados",
    ],
}


def es_demo_pricing(slug: str | None) -> bool:
    try:
        from rmweb.tenants import es_demo

        return es_demo(slug)
    except Exception:
        s = (slug or "").strip().lower()
        return s in {"comercial-demo", "taller-demo"}


def rubro_pricing(slug: str | None) -> str:
    try:
        from rmweb.tenants import rubro

        return rubro(slug)
    except Exception:
        return "comercial"


def catalog_for_tenant(slug: str | None) -> dict[str, Any]:
    """Catálogo de módulos y packs según tenant demo."""
    r = rubro_pricing(slug)
    if r == "taller":
        modulos = MODULOS_FEE_TALLER
        pack = PACK_TALLER
        pack_ventas = PACK_TALLER_VENTAS
        pack_compras = PACK_TALLER_OPERACIONES
        pack_compras_label = "Pack Operaciones"
        pack_total_label = "Plan Taller Total"
        titulo = "ERP Taller Automotriz"
        intro = (
            "Packs para taller: ventas con OT, operaciones con RRHH, "
            "o plan total del taller."
        )
        show_ml = False
    else:
        modulos = MODULOS_FEE
        pack = PACK
        pack_ventas = PACK_VENTAS
        pack_compras = PACK_COMPRAS
        pack_compras_label = "Pack Compras"
        pack_total_label = "Plan Total"
        titulo = "ERP Comercial"
        intro = (
            "Packs de ventas o compras. Plan Total = todos los módulos comerciales."
        )
        show_ml = True

    suma = sum(int(m["fee"]) for m in modulos.values() if not m.get("addon"))
    suma_ventas = suma_modulos_keys(pack_ventas["modulos"], modulos)
    suma_compras = suma_modulos_keys(pack_compras["modulos"], modulos)
    pagos = [int(m["fee"]) for m in modulos.values() if int(m["fee"]) > 0 and not m.get("addon")]
    return {
        "demo_rubro": r,
        "titulo": titulo,
        "intro": intro,
        "modulos": modulos,
        "pack": pack,
        "pack_ventas": pack_ventas,
        "pack_compras": pack_compras,
        "pack_compras_label": pack_compras_label,
        "pack_total_label": pack_total_label,
        "suma": suma,
        "suma_ventas": suma_ventas,
        "suma_compras": suma_compras,
        "ahorro": max(0, suma - int(pack["fee"])),
        "ahorro_ventas": max(0, suma_ventas - int(pack_ventas["fee"])),
        "ahorro_compras": max(0, suma_compras - int(pack_compras["fee"])),
        "modulos_pago_min": min(pagos) if pagos else 0,
        "show_ml": show_ml,
        "addon_mercadolibre": modulos.get("mercadolibre") if show_ml else None,
    }


def suma_modulos_keys(
    keys: tuple[str, ...] | list[str],
    modulos: dict[str, dict[str, Any]] | None = None,
) -> int:
    src = modulos or MODULOS_FEE
    return sum(int(src[k]["fee"]) for k in keys if k in src)


def pricing_context(tenant_slug: str | None) -> dict[str, Any]:
    """Fees visibles en tenants DEMO (Comercial o Taller)."""
    slug = (tenant_slug or "").strip().lower()
    show = es_demo_pricing(slug)
    if not show:
        return {
            "show_module_fees": False,
            "dias_prueba": None,
            "module_fees": {},
            "pricing_pack": None,
            "pricing_pack_ventas": None,
            "pricing_pack_compras": None,
            "pricing_suma": 0,
            "pricing_suma_ventas": 0,
            "pricing_suma_compras": 0,
            "pricing_ahorro": 0,
            "pricing_ahorro_ventas": 0,
            "pricing_ahorro_compras": 0,
            "addon_mercadolibre": None,
            "demo_rubro": rubro_pricing(slug),
        }
    cat = catalog_for_tenant(slug)
    return {
        "show_module_fees": True,
        "dias_prueba": 30,
        "module_fees": cat["modulos"],
        "pricing_pack": cat["pack"],
        "pricing_pack_ventas": cat["pack_ventas"],
        "pricing_pack_compras": cat["pack_compras"],
        "pricing_suma": cat["suma"],
        "pricing_suma_ventas": cat["suma_ventas"],
        "pricing_suma_compras": cat["suma_compras"],
        "pricing_ahorro": cat["ahorro"],
        "pricing_ahorro_ventas": cat["ahorro_ventas"],
        "pricing_ahorro_compras": cat["ahorro_compras"],
        "addon_mercadolibre": cat["addon_mercadolibre"],
        "demo_rubro": cat["demo_rubro"],
    }
