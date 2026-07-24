from __future__ import annotations

from datetime import timedelta

import pandas as pd
from flask import flash, render_template, request, url_for

from demo_web.services.demo_loader import bind_user_session, get_demo_module
from demo_web.services.erp_loader import get_erp_app
from demo_web.services.module_runner import redirect_module, store_pdf
from demo_web.services.native._helpers import parse_date

SECCIONES = [
    ("salida", "🚜 SALIDA MANUAL"),
    ("bitacora", "📱 BITÁCORA CAMPO"),
    ("historial", "📊 HISTORIAL"),
    ("planilla", "📋 PLANILLA MAESTRA"),
]


def _temporada_actual(demo):
    for t in demo.TEMPORADAS_COSTOS:
        if t[1] <= demo.hoy <= t[2]:
            return t
    return demo.TEMPORADAS_COSTOS[0]


def _saldo_estanque(conn) -> tuple[float, float, float]:
    df_c = pd.read_sql_query(
        "SELECT SUM(litros) AS l FROM petroleo "
        "WHERE tipo='Carga' OR (tipo='Ajuste Manual' AND litros > 0)",
        conn,
    )
    df_s = pd.read_sql_query(
        "SELECT SUM(litros) AS l FROM petroleo "
        "WHERE tipo='Salida' OR (tipo='Ajuste Manual' AND litros < 0)",
        conn,
    )
    tot_c = float(df_c["l"].fillna(0).iloc[0])
    tot_s = abs(float(df_s["l"].fillna(0).iloc[0]))
    return tot_c - tot_s, tot_c, tot_s


def _opciones_maquinaria(conn):
    from erp_maquinaria import TIPOS_MAQUINARIA_PETROLEO, etiqueta_maquinaria, listar_maquinaria

    items = listar_maquinaria(conn, solo_activos=True, tipos=TIPOS_MAQUINARIA_PETROLEO)
    if not items:
        items = listar_maquinaria(conn, solo_activos=True)
    return [(m["codigo"], etiqueta_maquinaria(m["codigo"], m["nombre"])) for m in items]


def _eventos_historial(demo, conn, dfp) -> list[dict]:
    eventos_raw = demo._petroleo_eventos_historial(dfp)
    out = []
    for num, (kind, data, _) in reversed(list(enumerate(eventos_raw, start=1))):
        if kind == "carga":
            row = data
            out.append(
                {
                    "num": num,
                    "kind": "carga",
                    "fecha": pd.to_datetime(row["fecha"]).strftime("%Y-%m-%d"),
                    "litros": demo.f_decimal(row.get("litros", 0)),
                    "bruto": demo.f_peso(row.get("monto_total_compra", 0) or 0),
                }
            )
        else:
            grp = data
            detalle = []
            for _, row in grp.iterrows():
                detalle.append(
                    {
                        "cuartel": row["centro_costo"],
                        "litros": demo.f_decimal(row["litros"]),
                        "neto": demo.f_peso(row.get("valor_imputado", 0) or 0),
                    }
                )
            cod_bit = ""
            if "bitacora_codigo" in grp.columns:
                for v in grp["bitacora_codigo"].fillna("").astype(str):
                    if v.strip():
                        cod_bit = v.strip()
                        break
            out.append(
                {
                    "num": num,
                    "kind": "salida",
                    "fecha": pd.to_datetime(grp["fecha"].iloc[0]).strftime("%Y-%m-%d"),
                    "vehiculo": grp["vehiculo"].iloc[0] or "—",
                    "responsable": grp["responsable"].iloc[0] or "—",
                    "litros": demo.f_decimal(float(grp["litros"].sum())),
                    "neto": demo.f_peso(float(grp["valor_imputado"].fillna(0).sum())),
                    "n_cuarteles": len(grp),
                    "bitacora_codigo": cod_bit,
                    "detalle": detalle,
                }
            )
    return out


def _procesar_salida(demo, conn) -> dict:
    if demo.es_solo_lectura():
        return {"ok": False, "msg": "Modo solo lectura: no puede registrar despachos."}
    try:
        ls = float(request.form.get("litros") or 0)
    except ValueError:
        ls = 0.0
    fs = parse_date(request.form.get("fecha"), demo.hoy)
    vehiculo = (request.form.get("vehiculo") or "").strip()
    responsable = (request.form.get("responsable") or "").strip()
    ccs = [c.upper() for c in request.form.getlist("cuarteles") if c in demo.CENTROS_COSTO]

    if not vehiculo:
        return {"ok": False, "msg": "Seleccione el equipo o vehículo desde la maestra de maquinaria."}
    if not responsable:
        return {"ok": False, "msg": "Ingrese el responsable de la operación."}
    if not ccs or ls <= 0:
        return {"ok": False, "msg": "Indique litros de salida y al menos un cuartel."}

    try:
        pmp = demo._petroleo_pmp_neto(conn)
    except Exception:
        pmp = 0.0

    litros_cc = ls / len(ccs)
    for c in ccs:
        conn.execute(
            "INSERT INTO petroleo (tipo, litros, vehiculo, responsable, centro_costo, fecha, valor_imputado) "
            "VALUES (?,?,?,?,?,?,?)",
            ("Salida", litros_cc, vehiculo, responsable, c, str(fs), litros_cc * pmp),
        )
    conn.commit()
    demo.registrar_accion("PETROLEO", f"Salida {ls}L")
    return {"ok": True, "msg": f"Despacho registrado. PMP neto aplicado: ${demo.f_puntos(pmp)}/L"}


def _historial(demo, conn, saldo_actual: float) -> dict:
    from erp_maquinaria import enriquecer_columna_maquinaria

    hoy = demo.hoy
    try:
        f_min_q = conn.execute("SELECT MIN(fecha) FROM petroleo").fetchone()[0]
        f_min_p = pd.to_datetime(f_min_q).date() if f_min_q else hoy - timedelta(days=365)
    except Exception:
        f_min_p = hoy - timedelta(days=365)

    fi = parse_date(request.args.get("desde"), f_min_p)
    ff = parse_date(request.args.get("hasta"), hoy)

    # bitacora_codigo puede no existir en DBs antiguas
    cols = {r[1] for r in conn.execute("PRAGMA table_info(petroleo)").fetchall()}
    extra = ", bitacora_codigo" if "bitacora_codigo" in cols else ""
    dfp = pd.read_sql_query(
        f"""SELECT id, fecha, tipo, litros, vehiculo, responsable, centro_costo,
                  monto_total_compra, valor_imputado{extra}
           FROM petroleo WHERE fecha BETWEEN ? AND ?
           ORDER BY fecha ASC, id ASC""",
        conn,
        params=(str(fi), str(ff)),
    )
    if dfp.empty:
        return {
            "historial_eventos": [],
            "historial_stats": {"total": 0, "entradas": 0, "salidas": 0},
            "filtro_desde": fi.isoformat(),
            "filtro_hasta": ff.isoformat(),
            "pdf_historial_url": None,
        }

    dfp = enriquecer_columna_maquinaria(conn, dfp, "vehiculo")
    eventos_raw = demo._petroleo_eventos_historial(dfp)
    n_sal = sum(1 for k, _, _ in eventos_raw if k == "salida")
    n_car = sum(1 for k, _, _ in eventos_raw if k == "carga")

    pdf_url = None
    blob = demo.generar_pdf_petroleo_historial(dfp, saldo_petroleo=saldo_actual)
    if blob:
        token = store_pdf(blob, "petroleo.pdf")
        pdf_url = url_for("modules.pdf_download", token=token)

    return {
        "historial_eventos": _eventos_historial(demo, conn, dfp),
        "historial_stats": {"total": len(eventos_raw), "entradas": n_car, "salidas": n_sal},
        "filtro_desde": fi.isoformat(),
        "filtro_hasta": ff.isoformat(),
        "pdf_historial_url": pdf_url,
    }


def _planilla(demo, conn) -> dict:
    from erp_petroleo_planilla import defaults_planilla_petroleo, generar_pdf_planilla_maestra_petroleo

    f_def, l_def = defaults_planilla_petroleo(conn, demo.hoy)
    f_plan = parse_date(request.form.get("fecha") if request.method == "POST" else request.args.get("fecha"), f_def)
    try:
        l_raw = request.form.get("litros") if request.method == "POST" else request.args.get("litros")
        l_plan = float(l_raw) if l_raw not in (None, "") else float(l_def)
    except ValueError:
        l_plan = float(l_def)

    pdf_url = None
    if request.method == "POST" and request.form.get("action") == "planilla_pdf":
        blob = generar_pdf_planilla_maestra_petroleo(
            f_plan, l_plan, logo_path=None, empresa="ERP DEMO AGRICOLA",
        )
        if blob:
            token = store_pdf(blob, "planilla_maestra_petroleo.pdf")
            pdf_url = url_for("modules.pdf_download", token=token)

    return {
        "plan_fecha": f_plan.isoformat(),
        "plan_litros": l_plan,
        "pdf_planilla_url": pdf_url,
    }


def _bitacora_campo_ctx(demo, conn) -> dict:
    from demo_web.services.salida_petroleo import habilitado as bitacora_habilitada

    if not bitacora_habilitada():
        return {}
    from urllib.parse import quote

    from demo_web.services.salida_petroleo import (
        contar_pendientes,
        datos_compartir,
        listar_registros,
    )

    registros = listar_registros(conn)
    n_pend = contar_pendientes(conn)
    ctx: dict = {
        "bitacora_habilitada": True,
        "bitacora_admin_qr": demo.es_super_admin(),
        "bitacora_puede_autorizar": demo.es_admin() and not demo.es_solo_lectura(),
        "bitacora_registros": registros,
        "bitacora_total": len(registros),
        "bitacora_pendientes": n_pend,
        "bitacora_desfase": n_pend > 0,
    }
    if ctx["bitacora_admin_qr"]:
        url = datos_compartir()["url"]
        ctx.update(
            {
                "bitacora_url": url,
                "bitacora_qr_src": (
                    "https://api.qrserver.com/v1/create-qr-code/?size=280x280&margin=10&data="
                    + quote(url, safe="")
                ),
                "bitacora_wa_url": "https://wa.me/?text=" + quote(
                    "Registro salida petróleo (bitácora campo):\n" + url, safe=""
                ),
            }
        )
    return ctx


def gather_petroleo(user_email: str, user_rol: str) -> dict:
    demo = get_demo_module()
    bind_user_session(user_email, user_rol)
    from demo_web.services.salida_petroleo import habilitado as bitacora_habilitada

    sec = request.values.get("sec") or request.args.get("sec", "salida")
    secciones = list(SECCIONES)
    if not bitacora_habilitada():
        secciones = [s for s in secciones if s[0] != "bitacora"]
    if sec not in {k for k, _ in secciones}:
        sec = "salida"

    temp = _temporada_actual(demo)
    conn = demo.conectar_db()
    try:
        try:
            saldo, tot_c, tot_s = _saldo_estanque(conn)
        except Exception:
            saldo, tot_c, tot_s = 0.0, 0.0, 0.0

        from erp_maquinaria import html_widget_petroleo_maquinaria

        widget_html = html_widget_petroleo_maquinaria(
            conn, temp[0], str(temp[1]), str(temp[2]), ref_fecha=demo.hoy,
        )

        try:
            pmp = demo._petroleo_pmp_neto(conn)
        except Exception:
            pmp = 0.0

        ctx: dict = {
            "secciones": secciones,
            "sec_activa": sec,
            "solo_lectura": demo.es_solo_lectura(),
            "saldo_actual": demo.f_decimal(saldo),
            "tot_cargas": demo.f_decimal(tot_c),
            "tot_salidas": demo.f_decimal(tot_s),
            "temp_nombre": temp[0],
            "widget_html": widget_html,
            "pmp_neto": demo.f_puntos(pmp),
            "impuesto_litro": demo.IMPUESTO_ESPECIFICO_LITRO,
            "cuarteles": demo.CENTROS_COSTO,
            "maquinaria_opts": _opciones_maquinaria(conn),
        }
        ctx.update(_bitacora_campo_ctx(demo, conn))
        # Alerta de desfase también visible fuera de Bitácora
        if bitacora_habilitada() and "bitacora_desfase" not in ctx:
            from demo_web.services.salida_petroleo import contar_pendientes

            n_pend = contar_pendientes(conn)
            ctx["bitacora_pendientes"] = n_pend
            ctx["bitacora_desfase"] = n_pend > 0

        if sec == "historial":
            ctx.update(_historial(demo, conn, saldo))
        elif sec == "planilla":
            ctx.update(_planilla(demo, conn))
        elif sec == "salida":
            ctx["form_fecha"] = demo.hoy.isoformat()

        return ctx
    finally:
        conn.close()


def _autorizar_bitacora(demo, user_email: str) -> dict:
    if not demo.es_admin():
        return {"ok": False, "msg": "Solo un administrador puede autorizar salidas de bitácora."}
    from demo_web.services.salida_petroleo import autorizar_salida

    codigo = (request.form.get("codigo") or "").strip()
    result = autorizar_salida(codigo, user_email)
    if result.get("ok") and result.get("mail_ok") is False:
        result["msg"] = result["msg"] + " (aviso por correo no pudo enviarse)."
    return result


def _rechazar_bitacora(demo, user_email: str) -> dict:
    if not demo.es_admin():
        return {"ok": False, "msg": "Solo un administrador puede rechazar salidas de bitácora."}
    from demo_web.services.salida_petroleo import rechazar_salida

    codigo = (request.form.get("codigo") or "").strip()
    motivo = (request.form.get("motivo") or "").strip()
    return rechazar_salida(codigo, user_email, motivo=motivo)


def view(user_email: str, user_rol: str):
    demo = get_demo_module()
    bind_user_session(user_email, user_rol)

    if request.method == "POST":
        action = request.form.get("action", "")
        if demo.es_solo_lectura() and action != "planilla_pdf":
            flash("Modo solo lectura: no puede modificar datos.", "warning")
            sec = request.form.get("sec") or "salida"
            return redirect_module("petroleo", sec=sec)
        conn = demo.conectar_db()
        try:
            if action == "despachar":
                result = _procesar_salida(demo, conn)
                flash(result["msg"], "success" if result["ok"] else "danger")
                return redirect_module("petroleo", sec="salida")
            if action == "autorizar_bitacora":
                result = _autorizar_bitacora(demo, user_email)
                flash(result["msg"], "success" if result["ok"] else "danger")
                return redirect_module("petroleo", sec="bitacora")
            if action == "rechazar_bitacora":
                result = _rechazar_bitacora(demo, user_email)
                flash(result["msg"], "success" if result["ok"] else "danger")
                return redirect_module("petroleo", sec="bitacora")
            if action == "planilla_pdf":
                ctx = gather_petroleo(user_email, user_rol)
                return render_template(
                    "modules/petroleo.html",
                    page_title="Petróleo",
                    active_key="Petróleo",
                    title="⛽ Petróleo",
                    **ctx,
                )
        finally:
            conn.close()

    ctx = gather_petroleo(user_email, user_rol)
    return render_template(
        "modules/petroleo.html",
        page_title="Petróleo",
        active_key="Petróleo",
        title="⛽ Petróleo",
        **ctx,
    )
