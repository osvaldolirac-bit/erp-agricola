from __future__ import annotations

import pandas as pd

from demo_web.services.demo_loader import bind_user_session, get_demo_module
from demo_web.services.native._helpers import prorrateo_rrhh
from demo_web.services.tenant_scope import cuarteles_oficiales


def _conn():
    demo = get_demo_module()
    return demo, demo.conectar_db()


def table_from_sql(sql: str, params=()) -> list[dict]:
    demo, conn = _conn()
    try:
        df = pd.read_sql_query(sql, conn, params=params)
        if df.empty:
            return []
        df = df.fillna("")
        return df.to_dict(orient="records")
    finally:
        conn.close()


def compras_historial() -> tuple[list[dict], list[str]]:
    rows = table_from_sql(
        """SELECT fecha_emision, nro_documento, proveedor, monto_total, estado, concepto
           FROM facturas ORDER BY fecha_emision DESC LIMIT 500"""
    )
    cols = ["fecha_emision", "nro_documento", "proveedor", "monto_total", "estado", "concepto"]
    return rows, cols


def tesoreria_pendientes() -> tuple[list[dict], list[str]]:
    demo, conn = _conn()
    try:
        df = demo._cargar_facturas_pendientes_saldo(conn)
        if df.empty:
            return [], []
        show = df[
            [
                "nro_documento",
                "proveedor",
                "fecha_vencimiento",
                "saldo",
                "dias_vencido",
                "estado",
            ]
        ].copy()
        show["saldo"] = show["saldo"].apply(lambda v: demo.f_peso(v))
        return show.fillna("").to_dict(orient="records"), list(show.columns)
    finally:
        conn.close()


def petroleo_historial() -> tuple[list[dict], list[str]]:
    rows = table_from_sql(
        """SELECT fecha, tipo, litros, vehiculo, responsable, centro_costo, valor_imputado
           FROM petroleo ORDER BY fecha DESC LIMIT 500"""
    )
    cols = ["fecha", "tipo", "litros", "vehiculo", "responsable", "centro_costo", "valor_imputado"]
    return rows, cols


def bodega_inventario() -> tuple[list[dict], list[str]]:
    rows = table_from_sql(
        """SELECT producto, familia, stock, unidad_medida, pmp
           FROM inventario ORDER BY producto"""
    )
    cols = ["producto", "familia", "stock", "unidad_medida", "pmp"]
    return rows, cols


def rrhh_personal() -> tuple[list[dict], list[str]]:
    rows = table_from_sql(
        """SELECT nombre, rut, cargo, estado, fecha_contrato
           FROM personal ORDER BY nombre"""
    )
    cols = ["nombre", "rut", "cargo", "estado", "fecha_contrato"]
    return rows, cols


def maquinaria_listado() -> tuple[list[dict], list[str]]:
    rows = table_from_sql(
        """SELECT codigo, nombre, tipo, activo, notas
           FROM maestra_maquinaria ORDER BY codigo"""
    )
    cols = ["codigo", "nombre", "tipo", "activo", "notas"]
    return rows, cols


def campob_movimientos() -> tuple[list[dict], list[str]]:
    rows = table_from_sql(
        """SELECT fecha, documento, item, monto
           FROM gastos_campob ORDER BY fecha DESC LIMIT 300"""
    )
    cols = ["fecha", "documento", "item", "monto"]
    return rows, cols


def libro_campo_registros() -> tuple[list[dict], list[str]]:
    rows = table_from_sql(
        """SELECT fecha, sector, producto, ingrediente, dosis, aplicadores, gasto_total
           FROM libro_campo ORDER BY fecha DESC LIMIT 300"""
    )
    cols = ["fecha", "sector", "producto", "ingrediente", "dosis", "aplicadores", "gasto_total"]
    return rows, cols


def globalgap_checklist() -> tuple[list[dict], list[str]]:
    rows = table_from_sql(
        """SELECT capitulo, codigo, descripcion, orden
           FROM gap_checklist ORDER BY capitulo, orden LIMIT 500"""
    )
    cols = ["capitulo", "codigo", "descripcion", "orden"]
    return rows, cols


def soporte_tickets() -> tuple[list[dict], list[str]]:
    rows = table_from_sql(
        """SELECT codigo_ticket, usuario, descripcion, status, fecha_creacion
           FROM tickets_soporte ORDER BY fecha_creacion DESC LIMIT 200"""
    )
    cols = ["codigo_ticket", "usuario", "descripcion", "status", "fecha_creacion"]
    return rows, cols


def costos_resumen(email: str, rol: str) -> tuple[list[dict], list[str]]:
    demo, conn = _conn()
    bind_user_session(email, rol)
    try:
        dfr, _ = demo._armar_dataframe_costos_dashboard(
            conn, cuarteles_oficiales(demo), prorrateo_rrhh(demo, conn)
        )
        if dfr.empty:
            return [], []
        show = dfr.copy()
        if "Total" in show.columns:
            show["Total"] = show["Total"].apply(lambda v: demo.f_peso(v))
        return show.fillna("").to_dict(orient="records"), list(show.columns)
    finally:
        conn.close()


def flujo_matriz(email: str, rol: str) -> tuple[list[dict], list[str]]:
    demo, conn = _conn()
    bind_user_session(email, rol)
    try:
        from erp_flujo_financiero import armar_flujo_financiero, df_flujo_para_pdf

        matriz = armar_flujo_financiero(conn, cuarteles_oficiales(demo))
        df = df_flujo_para_pdf(matriz)
        if df is None or df.empty:
            return [], []
        return df.fillna("").to_dict(orient="records"), list(df.columns)
    except Exception:
        return [], []
    finally:
        conn.close()


def admin_usuarios() -> tuple[list[dict], list[str]]:
    demo, conn = _conn()
    try:
        rows = conn.execute(
            """SELECT email, COALESCE(rol,'operador') as rol, fecha_expira, modulos
               FROM usuarios ORDER BY email"""
        ).fetchall()
        items = []
        for em, rol, exp, mods in rows:
            items.append(
                {
                    "email": em,
                    "rol": demo.etiqueta_perfil_demo(rol, em),
                    "fecha_expira": exp or "",
                    "modulos": mods or "",
                }
            )
        cols = ["email", "rol", "fecha_expira", "modulos"]
        return items, cols
    finally:
        conn.close()


def manual_html(email: str, rol: str) -> tuple[str, str, str]:
    demo = get_demo_module()
    bind_user_session(email, rol)
    import manual_contenido

    if demo.es_certificacion():
        guia = manual_contenido.GUIA_RAPIDA_CERT_HTML
        completo = manual_contenido.MANUAL_COMPLETO_CERT_HTML
        aviso = "Perfil certificación: GlobalGAP, Libro de Campo y Bodega."
    else:
        guia = manual_contenido.GUIA_RAPIDA_HTML
        completo = manual_contenido.MANUAL_COMPLETO_HTML
        aviso = "Documento demo — solo visualización dentro del sistema."
    return guia, completo, aviso
