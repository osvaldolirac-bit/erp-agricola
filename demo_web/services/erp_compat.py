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
