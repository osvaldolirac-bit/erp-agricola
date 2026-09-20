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

PACK = {
    "nombre": "Pack Comercial",
    "fee": 69_900,
    "fee_txt": "$69.900/mes",
    "modulos": (
        "dashboard",
        "clientes",
        "cotizaciones",
        "cuentas",
        "ordenes",
        "compras",
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
        "Flujo OC → Compra → Tesorería integrado",
    ],
}


def suma_modulos() -> int:
    return sum(int(m["fee"]) for m in MODULOS_FEE.values())


def fee_for(active_key: str) -> dict[str, Any] | None:
    return MODULOS_FEE.get(active_key)


def pricing_context(tenant_slug: str | None) -> dict[str, Any]:
    """Fees visibles en el ERP del tenant DEMO Comercial."""
    slug = (tenant_slug or "").strip().lower()
    show = slug == "comercial-demo"
    suma = suma_modulos()
    return {
        "show_module_fees": show,
        "module_fees": MODULOS_FEE if show else {},
        "pricing_pack": PACK if show else None,
        "pricing_suma": suma if show else 0,
        "pricing_ahorro": max(0, suma - int(PACK["fee"])) if show else 0,
    }
