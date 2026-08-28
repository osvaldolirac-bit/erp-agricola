"""Parches de compatibilidad para app_concepcion en el shell Flask."""
from __future__ import annotations

import pandas as pd


def patch_erp_module(erp, app_name: str) -> None:
    if app_name != "concepcion":
        return

    if not hasattr(erp, "puede_administracion"):
        erp.puede_administracion = erp.es_admin

    if not hasattr(erp, "es_super_admin"):
        erp.es_super_admin = erp.es_admin

    if not hasattr(erp, "es_admin_cliente"):
        erp.es_admin_cliente = erp.es_admin

    if not hasattr(erp, "DEMO_URL"):
        erp.DEMO_URL = getattr(erp, "PROD_URL_ALT", getattr(erp, "PROD_URL", ""))

    if not hasattr(erp, "normalizar_rol_usuario"):

        def normalizar_rol_usuario(rol, email=None):
            r = (rol or "operador").strip()
            return r if r in erp.ROLES_USUARIO else "operador"

        erp.normalizar_rol_usuario = normalizar_rol_usuario

    if not hasattr(erp, "usuario_prueba_vigente"):

        def usuario_prueba_vigente(fecha_expira):
            if not fecha_expira:
                return True
            try:
                return pd.to_datetime(fecha_expira).date() >= erp.hora_chile().date()
            except Exception:
                return True

        erp.usuario_prueba_vigente = usuario_prueba_vigente

    if not hasattr(erp, "usuario_gestionable_demo"):

        def usuario_gestionable_demo(conn, email_objetivo):
            return bool(email_objetivo)

        erp.usuario_gestionable_demo = usuario_gestionable_demo

    if not hasattr(erp, "etiqueta_perfil_demo"):

        def etiqueta_perfil_demo(rol, email=None):
            r = erp.normalizar_rol_usuario(rol, email)
            return erp.PERFILES_USUARIO_TXT.get(r, str(r or ""))

        erp.etiqueta_perfil_demo = etiqueta_perfil_demo

    if not hasattr(erp, "DEMO_DIAS_PRUEBA"):
        erp.DEMO_DIAS_PRUEBA = 0

    if not hasattr(erp, "perfiles_asignables_demo"):

        def perfiles_asignables_demo():
            return erp.ROLES_USUARIO

        erp.perfiles_asignables_demo = perfiles_asignables_demo

    if not hasattr(erp, "contar_roles_admin_demo"):

        def contar_roles_admin_demo(conn):
            rows = conn.execute(
                "SELECT email, COALESCE(rol, 'operador') FROM usuarios",
            ).fetchall()
            n_admin = 0
            for em, rol in rows:
                r = erp.normalizar_rol_usuario(rol, em)
                if r == "admin":
                    n_admin += 1
            return 0, n_admin

        erp.contar_roles_admin_demo = contar_roles_admin_demo

    _patch_factores_monto_bruto_facturas(erp)


def _patch_factores_monto_bruto_facturas(erp) -> None:
    """Costos no debe re-escalar a bruto cuando la compra imputó neto al CC."""
    if getattr(erp, "_factores_bruto_patched", False):
        return
    if not hasattr(erp, "_factores_monto_bruto_facturas"):
        return

    def _factores_monto_bruto_facturas(conn, fi=None, ff=None):
        filtro = ""
        params: list = []
        if fi and ff:
            filtro = " AND p.fecha_compra BETWEEN ? AND ? "
            params = [str(fi), str(ff)]

        cols = {r[1] for r in conn.execute("PRAGMA table_info(facturas)").fetchall()}
        has_flag = "imputar_bruto" in cols
        flag_sql = ", MAX(COALESCE(par.imputar_bruto, 1)) AS imputar_bruto" if has_flag else ""

        rows = conn.execute(
            f"""
            SELECT p.nro_documento, p.proveedor,
                   MAX(par.monto_total) AS bruto,
                   SUM(COALESCE(p.monto_imputado, 0)) AS imp
                   {flag_sql}
            FROM facturas p
            INNER JOIN facturas par
              ON par.nro_documento = REPLACE(p.nro_documento, '_P', '')
             AND par.proveedor = p.proveedor
             AND par.nro_documento NOT LIKE '%_P'
            WHERE p.nro_documento LIKE '%_P'
              AND p.nro_documento NOT LIKE '%_RRHH'
              AND ABS(COALESCE(p.monto_imputado, 0)) > 0.01
              {filtro}
            GROUP BY p.nro_documento, p.proveedor
            """,
            params,
        ).fetchall()

        out: dict[tuple[str, str], float] = {}
        for row in rows:
            nro_p, prov, bruto, imp = row[0], row[1], row[2], row[3]
            imputar_bruto = int(row[4]) if has_flag and len(row) > 4 else 1
            imp_f = float(imp or 0)
            bruto_f = float(bruto or 0)
            key = (str(nro_p or ""), str(prov or ""))

            if imp_f <= 0.01 or bruto_f <= 0.01:
                out[key] = 1.0
                continue

            ratio = bruto_f / imp_f
            if not imputar_bruto or 1.17 <= ratio <= 1.21:
                out[key] = 1.0
            elif ratio > 1.05:
                out[key] = ratio
            else:
                out[key] = 1.0
        return out

    erp._factores_monto_bruto_facturas = _factores_monto_bruto_facturas
    erp._factores_bruto_patched = True
