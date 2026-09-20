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

    _patch_matriz_costos_cc_canon(erp)


def _patch_matriz_costos_cc_canon(erp) -> None:
    """Mapeo case-insensitive CC en matriz + prorrateo legacy bodega Espino."""
    orig = getattr(erp, "_armar_matriz_costos_vista_b", None)
    if not callable(orig) or getattr(orig, "_cc_canon_wrapped", False):
        return

    import inspect

    try:
        src = inspect.getsource(orig)
    except (OSError, TypeError):
        src = ""
    needs_cc_canon = "cc_canon" not in src

    def _armar_matriz_costos_vista_b(
        conn, fi, ff, cuarteles, prorrateo_rrhh, temporada, fi_rrhh=None, ff_rrhh=None, **kwargs,
    ):
        if not needs_cc_canon:
            matriz = orig(
                conn, fi, ff, cuarteles, prorrateo_rrhh, temporada,
                fi_rrhh=fi_rrhh, ff_rrhh=ff_rrhh, **kwargs,
            )
        else:
            matriz = _armar_matriz_con_cc_canon(
                erp, orig, conn, fi, ff, cuarteles, prorrateo_rrhh, temporada,
                fi_rrhh=fi_rrhh, ff_rrhh=ff_rrhh, **kwargs,
            )
        try:
            from demo_web.services.tenant_scope import is_espino_tenant
            from demo_web.services.costos_espino_matriz import inyectar_prorrateo_legacy_cc

            if is_espino_tenant():
                matriz = inyectar_prorrateo_legacy_cc(
                    conn, erp, matriz, list(cuarteles or []), fi, ff,
                )
        except Exception:
            pass
        return matriz

    _armar_matriz_costos_vista_b._cc_canon_wrapped = True
    erp._armar_matriz_costos_vista_b = _armar_matriz_costos_vista_b


def _armar_matriz_con_cc_canon(
    erp, orig, conn, fi, ff, cuarteles, prorrateo_rrhh, temporada, fi_rrhh=None, ff_rrhh=None, **kwargs,
):
    """Fallback cuando app_concepcion no tiene cc_canon en add()."""
    cols_cc = list(cuarteles)
    cols = cols_cc + ["TOTAL"]
    rubros = list(getattr(erp, "RUBROS_MATRIZ_COSTOS", []) or [])
    matriz = {rubro: {c: 0.0 for c in cols} for rubro in rubros}
    cc_canon = {str(c).upper().strip(): c for c in cuarteles}

    def add(cc, rubro, monto):
        cc_key = cc_canon.get(str(cc or "").upper().strip())
        if not cc_key or not rubro:
            return
        m = float(monto or 0)
        if abs(m) < 0.01:
            return
        if rubro not in matriz:
            return
        matriz[rubro][cc_key] += m
        matriz[rubro]["TOTAL"] += m

    filtro_f = ""
    params_f = ()
    if fi and ff:
        filtro_f = " AND fecha_compra BETWEEN ? AND ? "
        params_f = (str(fi), str(ff))
    filtro_m = " AND fecha BETWEEN ? AND ? " if fi and ff else ""
    params_m = (str(fi), str(ff)) if fi and ff else ()

    fn_rubro_prod = getattr(erp, "_rubro_costo_desde_producto", None)
    q_mov = f"""SELECT UPPER(TRIM(m.centro_costo)) as cc,
                       m.valor_imputado as m,
                       COALESCE(i.producto, '') as producto,
                       i.familia as familia
                FROM movimientos m
                LEFT JOIN inventario i ON m.producto_id = i.id
                WHERE ABS(COALESCE(m.valor_imputado,0))>0.01
                  AND TRIM(COALESCE(m.centro_costo,'')) != '' {filtro_m}"""
    for row in conn.execute(q_mov, params_m):
        rubro = "Insumos"
        if callable(fn_rubro_prod):
            try:
                rubro = fn_rubro_prod(conn, row[2], row[3]) or rubro
            except Exception:
                pass
        add(row[0], rubro, row[1])

    sin_clasificar = getattr(erp, "TIPO_GASTO_SIN_CLASIFICAR", "Sin clasificar")
    fn_fact = getattr(erp, "_factores_monto_bruto_facturas", None)
    fn_monto_imp = getattr(erp, "_monto_costos_factura_imputada", None)
    fn_monto_matriz = getattr(erp, "_monto_costos_factura_matriz", None)
    fn_rubro = getattr(erp, "_rubro_valido_matriz", None) or getattr(
        erp, "_rubro_matriz_desde_tipo_gasto", None,
    )
    factores = fn_fact(conn, fi, ff) if callable(fn_fact) else {}
    neto_espino = kwargs.get("neto_facturas_espino", True)

    q_fac = f"""SELECT nro_documento, proveedor,
                       UPPER(TRIM(centro_costo)) as cc,
                       COALESCE(NULLIF(TRIM(tipo_gasto), ''), ?) as tg,
                       monto_imputado as m
                FROM facturas
                WHERE nro_documento LIKE '%_P' AND nro_documento NOT LIKE '%_RRHH'
                  AND ABS(COALESCE(monto_imputado,0))>0.01 {filtro_f}"""
    for row in conn.execute(q_fac, (sin_clasificar, *params_f)):
        rubro = fn_rubro(row[3]) if callable(fn_rubro) else row[3]
        if not rubro:
            continue
        monto = float(row[4] or 0)
        if callable(fn_monto_imp):
            try:
                monto = float(fn_monto_imp(factores, row[0], row[1], monto) or 0)
            except Exception:
                pass
        if callable(fn_monto_matriz):
            try:
                monto = float(fn_monto_matriz(rubro, monto, neto_facturas_espino=neto_espino) or 0)
            except Exception:
                pass
        add(row[2], rubro, monto)

    q_pet = f"""SELECT UPPER(TRIM(centro_costo)) as cc, SUM(valor_imputado) as m
                FROM petroleo WHERE tipo='Salida'
                  AND ABS(COALESCE(valor_imputado,0))>0.01 {filtro_m}
                GROUP BY UPPER(TRIM(centro_costo))"""
    for row in conn.execute(q_pet, params_m):
        add(row[0], "Petróleo", row[1])

    q_aj = f"""SELECT UPPER(TRIM(centro_costo)) as cc, SUM(monto) as m
               FROM ajustes_costos WHERE ABS(COALESCE(monto,0))>0.01 {filtro_m}
               GROUP BY UPPER(TRIM(centro_costo))"""
    for row in conn.execute(q_aj, params_m):
        add(row[0], "Ajustes", row[1])

    fn_rrhh = getattr(erp, "_calcular_rrhh_temporada", None)
    monto_rrhh = fn_rrhh(conn, fi_rrhh or fi, ff_rrhh or ff) if callable(fn_rrhh) else 0.0
    for cc in cuarteles:
        pct = prorrateo_rrhh.get(cc, 0) if isinstance(prorrateo_rrhh, dict) else 0
        add(cc, "RRHH de la casa", monto_rrhh * pct)

    rows = []
    for rubro in rubros:
        row = {"Rubro": rubro}
        for c in cols:
            row[c] = matriz[rubro].get(c, 0.0)
        rows.append(row)
    df = pd.DataFrame(rows)
    total_gasto = {c: float(df[c].sum()) for c in cols}
    fn_ppto = getattr(erp, "_obtener_ppto_temporada", None)
    ppto = {c: 0.0 for c in cols}
    for cc in cuarteles:
        ppto[cc] = float(fn_ppto(conn, temporada, cc) or 0) if callable(fn_ppto) else 0.0
    ppto["TOTAL"] = sum(ppto[c] for c in cuarteles)
    saldo = {c: ppto[c] - total_gasto[c] for c in cols}
    footer = pd.DataFrame([
        {"Rubro": "TOTAL GASTO", **total_gasto},
        {"Rubro": "PRESUPUESTO", **ppto},
        {"Rubro": "SALDO", **saldo},
    ])
    return pd.concat([df, footer], ignore_index=True)
