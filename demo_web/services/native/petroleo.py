from __future__ import annotations

from datetime import timedelta

import pandas as pd
from flask import flash, render_template, request, url_for

from demo_web.services.demo_loader import bind_user_session, get_demo_module
from demo_web.services.erp_loader import get_erp_app
from demo_web.services.module_runner import redirect_module, store_pdf
from demo_web.services.native._helpers import hoy_demo, parse_date
from demo_web.services.tenant_scope import centros_costo

SECCIONES = [
    ("salida", "🚜 SALIDA MANUAL"),
    ("bitacora", "🔗 SALIDA LINK"),
    ("historial", "📊 HISTORIAL"),
    ("planilla", "📋 PLANILLA MAESTRA"),
]


def _temporada_actual(demo):
    for t in demo.TEMPORADAS_COSTOS:
        if t[1] <= hoy_demo(demo) <= t[2]:
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


def _check_master(demo, clave: str) -> bool:
    return (clave or "").strip() == getattr(demo, "CLAVE_MAESTRA", "")


def _recalc_imputacion_petroleo(demo, conn) -> None:
    try:
        demo._recalcular_imputacion_salidas_petroleo(conn)
    except Exception:
        pass


def _parse_event_key(event_key: str) -> tuple[str, int] | None:
    ek = (event_key or "").strip()
    if ek.startswith("c:"):
        try:
            return "carga", int(ek[2:])
        except ValueError:
            return None
    if ek.startswith("s:"):
        try:
            return "salida", int(ek[2:])
        except ValueError:
            return None
    return None


def _eventos_historial(demo, conn, dfp) -> list[dict]:
    eventos_raw = demo._petroleo_eventos_historial(dfp)
    out = []
    for num, (kind, data, _) in reversed(list(enumerate(eventos_raw, start=1))):
        if kind == "carga":
            row = data
            eid = int(row["id"])
            out.append(
                {
                    "num": num,
                    "kind": "carga",
                    "event_key": f"c:{eid}",
                    "ids": [eid],
                    "fecha": pd.to_datetime(row["fecha"]).strftime("%Y-%m-%d"),
                    "fecha_raw": pd.to_datetime(row["fecha"]).strftime("%Y-%m-%d"),
                    "litros": demo.f_decimal(row.get("litros", 0)),
                    "litros_raw": float(row.get("litros", 0) or 0),
                    "bruto": demo.f_peso(row.get("monto_total_compra", 0) or 0),
                    "monto_bruto_raw": float(row.get("monto_total_compra", 0) or 0),
                    "tipo_raw": str(row.get("tipo") or "Carga"),
                }
            )
        else:
            grp = data
            ids = [int(x) for x in grp["id"].tolist()]
            detalle = []
            cuarteles_raw = []
            for _, row in grp.iterrows():
                cc = str(row["centro_costo"] or "").strip()
                cuarteles_raw.append(cc)
                detalle.append(
                    {
                        "cuartel": cc,
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
            litros_total = float(grp["litros"].sum())
            out.append(
                {
                    "num": num,
                    "kind": "salida",
                    "event_key": f"s:{min(ids)}",
                    "ids": ids,
                    "fecha": pd.to_datetime(grp["fecha"].iloc[0]).strftime("%Y-%m-%d"),
                    "fecha_raw": pd.to_datetime(grp["fecha"].iloc[0]).strftime("%Y-%m-%d"),
                    "vehiculo": grp["vehiculo"].iloc[0] or "—",
                    "vehiculo_raw": str(grp["vehiculo"].iloc[0] or "").strip(),
                    "responsable": grp["responsable"].iloc[0] or "—",
                    "responsable_raw": str(grp["responsable"].iloc[0] or "").strip(),
                    "litros": demo.f_decimal(litros_total),
                    "litros_raw": litros_total,
                    "neto": demo.f_peso(float(grp["valor_imputado"].fillna(0).sum())),
                    "n_cuarteles": len(grp),
                    "cuarteles_raw": cuarteles_raw,
                    "bitacora_codigo": cod_bit,
                    "detalle": detalle,
                }
            )
    return out


def _fingerprint_salida(ls: float, vehiculo: str, responsable: str, ccs: list[str]) -> str:
    ccs_norm = ",".join(sorted({c.strip().upper() for c in ccs if c}))
    return (
        f"Salida|{ls:.2f}L|{vehiculo.strip().upper()}|"
        f"{responsable.strip().upper()}|{ccs_norm}"
    )


def _salida_duplicada_reciente(demo, conn, fingerprint: str, minutos: int = 1) -> bool:
    """Evita doble despacho manual (misma config) en menos de N minutos vía bitácora."""
    desde = (demo.hora_chile() - timedelta(minutes=minutos)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        row = conn.execute(
            """SELECT id FROM bitacora
               WHERE fecha_hora >= ?
                 AND accion = 'PETROLEO'
                 AND detalle = ?
               ORDER BY id DESC LIMIT 1""",
            (desde, fingerprint),
        ).fetchone()
        return bool(row)
    except Exception:
        return False


def _procesar_salida(demo, conn) -> dict:
    if demo.es_solo_lectura():
        return {"ok": False, "msg": "Modo solo lectura: no puede registrar despachos."}
    try:
        ls = float(request.form.get("litros") or 0)
    except ValueError:
        ls = 0.0
    fs = parse_date(request.form.get("fecha"), hoy_demo(demo))
    vehiculo = (request.form.get("vehiculo") or "").strip()
    responsable = (request.form.get("responsable") or "").strip()
    ccs = [c.upper() for c in request.form.getlist("cuarteles") if c in centros_costo(demo)]

    if not vehiculo:
        return {"ok": False, "msg": "Seleccione el equipo o vehículo desde la maestra de maquinaria."}
    if not responsable:
        return {"ok": False, "msg": "Ingrese el responsable de la operación."}
    if not ccs or ls <= 0:
        return {"ok": False, "msg": "Indique litros de salida y al menos un cuartel."}

    fp = _fingerprint_salida(ls, vehiculo, responsable, ccs)
    try:
        try:
            conn.commit()
        except Exception:
            pass
        conn.execute("BEGIN IMMEDIATE")
        if _salida_duplicada_reciente(demo, conn, fp, minutos=1):
            conn.rollback()
            return {
                "ok": False,
                "msg": (
                    "Ya registró la misma salida (litros + equipo + cuartel + responsable) "
                    "hace menos de 1 minuto. Espere un momento."
                ),
            }

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
        try:
            from flask import g
            user_bit = (getattr(g, "user", None) or {}).get("email") or "web"
        except Exception:
            user_bit = "web"
        conn.execute(
            "INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)",
            (
                user_bit,
                "PETROLEO",
                fp,
                demo.hora_chile().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    return {"ok": True, "msg": f"Despacho registrado. PMP neto aplicado: ${demo.f_puntos(pmp)}/L"}


def _historial(demo, conn, saldo_actual: float) -> dict:
    from erp_maquinaria import enriquecer_columna_maquinaria

    hoy = hoy_demo(demo)
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
            "es_admin_hist": False,
            "mov_edit": None,
            "mov_opts": [],
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

    eventos = _eventos_historial(demo, conn, dfp)
    es_admin = bool(demo.es_admin()) and not bool(demo.es_solo_lectura())
    mov_edit = None
    mov_opts = []
    if es_admin and eventos:
        for ev in eventos:
            if ev["kind"] == "carga":
                lbl = (
                    f"Mov {ev['num']:03d} — ENTRADA — {ev['fecha']} — "
                    f"{ev['litros']} L — {ev['bruto']}"
                )
            else:
                lbl = (
                    f"Mov {ev['num']:03d} — SALIDA — {ev['fecha']} — "
                    f"{ev['vehiculo']} — {ev['litros']} L"
                )
            mov_opts.append({"event_key": ev["event_key"], "label": lbl})
        ek = (request.args.get("event_key") or eventos[0]["event_key"]).strip()
        mov_edit = next((e for e in eventos if e["event_key"] == ek), eventos[0])

    return {
        "historial_eventos": eventos,
        "historial_stats": {"total": len(eventos_raw), "entradas": n_car, "salidas": n_sal},
        "filtro_desde": fi.isoformat(),
        "filtro_hasta": ff.isoformat(),
        "pdf_historial_url": pdf_url,
        "es_admin_hist": es_admin,
        "mov_edit": mov_edit,
        "mov_opts": mov_opts,
        "maquinaria_opts_hist": _opciones_maquinaria(conn),
    }


def _post_corregir_petroleo_hist(demo, conn) -> dict:
    if demo.es_solo_lectura():
        return {"ok": False, "msg": "Modo solo lectura: no puede corregir movimientos."}
    if not demo.es_admin():
        return {"ok": False, "msg": "Solo administradores pueden corregir movimientos."}
    if not _check_master(demo, request.form.get("clave_maestra")):
        return {"ok": False, "msg": "Clave maestra incorrecta."}

    parsed = _parse_event_key(request.form.get("event_key") or "")
    if not parsed:
        return {"ok": False, "msg": "Movimiento no válido."}
    kind, ref_id = parsed
    fi = parse_date(request.form.get("desde"), hoy_demo(demo))
    ff = parse_date(request.form.get("hasta"), hoy_demo(demo))
    fecha = parse_date(request.form.get("fecha"), hoy_demo(demo))
    if fecha < fi or fecha > ff:
        return {"ok": False, "msg": "La fecha debe estar dentro del rango filtrado."}

    cols = {r[1] for r in conn.execute("PRAGMA table_info(petroleo)").fetchall()}
    has_bit = "bitacora_codigo" in cols

    if kind == "carga":
        row = conn.execute(
            "SELECT id, tipo FROM petroleo WHERE id=? AND lower(tipo) != 'salida'",
            (ref_id,),
        ).fetchone()
        if not row:
            return {"ok": False, "msg": "Entrada no encontrada."}
        try:
            litros = float(request.form.get("litros") or 0)
            monto = float(request.form.get("monto_bruto") or 0)
        except ValueError:
            return {"ok": False, "msg": "Litros o monto inválidos."}
        if litros <= 0:
            return {"ok": False, "msg": "Los litros deben ser mayores a cero."}
        conn.execute(
            "UPDATE petroleo SET fecha=?, litros=?, monto_total_compra=? WHERE id=?",
            (str(fecha), litros, monto, ref_id),
        )
        _recalc_imputacion_petroleo(demo, conn)
        conn.commit()
        demo.registrar_accion("PETROLEO", f"Corrección entrada ID {ref_id} — {litros} L")
        return {"ok": True, "msg": "Entrada corregida. Imputaciones de salida recalculadas.", "event_key": f"c:{ref_id}"}

    # salida — reemplazar filas del grupo
    ids_raw = (request.form.get("ids") or "").strip()
    ids = [int(x) for x in ids_raw.split(",") if x.strip().isdigit()]
    if not ids:
        ids = [ref_id]
    placeholders = ",".join("?" * len(ids))
    grp_rows = conn.execute(
        f"SELECT id, bitacora_codigo FROM petroleo WHERE id IN ({placeholders}) AND tipo='Salida'",
        ids,
    ).fetchall()
    if not grp_rows:
        return {"ok": False, "msg": "Salida no encontrada."}
    cod_bit = ""
    for _, cb in grp_rows:
        if cb and str(cb).strip():
            cod_bit = str(cb).strip()
            break

    try:
        ls = float(request.form.get("litros") or 0)
    except ValueError:
        return {"ok": False, "msg": "Litros inválidos."}
    vehiculo = (request.form.get("vehiculo") or "").strip()
    responsable = (request.form.get("responsable") or "").strip()
    ccs = [c.upper() for c in request.form.getlist("cuarteles") if c in centros_costo(demo)]
    if not vehiculo:
        return {"ok": False, "msg": "Seleccione el equipo."}
    if not responsable:
        return {"ok": False, "msg": "Ingrese el responsable."}
    if not ccs or ls <= 0:
        return {"ok": False, "msg": "Indique litros y al menos un cuartel."}

    conn.execute(f"DELETE FROM petroleo WHERE id IN ({placeholders})", ids)
    litros_cc = ls / len(ccs)
    pmp = demo._petroleo_pmp_neto(conn)
    for c in ccs:
        vals = ("Salida", litros_cc, vehiculo, responsable, c, str(fecha), litros_cc * pmp)
        if has_bit:
            conn.execute(
                "INSERT INTO petroleo (tipo, litros, vehiculo, responsable, centro_costo, fecha, "
                "valor_imputado, bitacora_codigo) VALUES (?,?,?,?,?,?,?,?)",
                (*vals, cod_bit or None),
            )
        else:
            conn.execute(
                "INSERT INTO petroleo (tipo, litros, vehiculo, responsable, centro_costo, fecha, "
                "valor_imputado) VALUES (?,?,?,?,?,?,?)",
                vals,
            )
    _recalc_imputacion_petroleo(demo, conn)
    conn.commit()
    demo.registrar_accion("PETROLEO", f"Corrección salida IDs {ids} — {ls} L — {vehiculo}")
    return {"ok": True, "msg": "Salida corregida. Imputaciones recalculadas."}


def _post_eliminar_petroleo_hist(demo, conn) -> dict:
    if demo.es_solo_lectura():
        return {"ok": False, "msg": "Modo solo lectura: no puede eliminar movimientos."}
    if not demo.es_admin():
        return {"ok": False, "msg": "Solo administradores pueden eliminar movimientos."}
    if not _check_master(demo, request.form.get("clave_maestra")):
        return {"ok": False, "msg": "Clave maestra incorrecta."}

    parsed = _parse_event_key(request.form.get("event_key") or "")
    if not parsed:
        return {"ok": False, "msg": "Movimiento no válido."}
    kind, ref_id = parsed
    ids_raw = (request.form.get("ids") or "").strip()
    ids = [int(x) for x in ids_raw.split(",") if x.strip().isdigit()]
    if not ids:
        ids = [ref_id]
    placeholders = ",".join("?" * len(ids))

    if kind == "carga":
        row = conn.execute(
            f"SELECT id, litros FROM petroleo WHERE id IN ({placeholders}) AND lower(tipo) != 'salida'",
            ids,
        ).fetchone()
    else:
        row = conn.execute(
            f"SELECT id, litros FROM petroleo WHERE id IN ({placeholders}) AND tipo='Salida'",
            ids,
        ).fetchone()
    if not row:
        return {"ok": False, "msg": "Movimiento no encontrado."}

    conn.execute(f"DELETE FROM petroleo WHERE id IN ({placeholders})", ids)
    _recalc_imputacion_petroleo(demo, conn)
    conn.commit()
    demo.registrar_accion("PETROLEO", f"Eliminado historial IDs {ids}")
    return {"ok": True, "msg": "Movimiento eliminado. Estanque e imputaciones recalculados."}


def _planilla(demo, conn) -> dict:
    from erp_petroleo_planilla import defaults_planilla_petroleo, generar_pdf_planilla_maestra_petroleo

    f_def, l_def = defaults_planilla_petroleo(conn, hoy_demo(demo))
    f_plan = parse_date(request.form.get("fecha") if request.method == "POST" else request.args.get("fecha"), f_def)
    try:
        l_raw = request.form.get("litros") if request.method == "POST" else request.args.get("litros")
        l_plan = float(l_raw) if l_raw not in (None, "") else float(l_def)
    except ValueError:
        l_plan = float(l_def)

    pdf_url = None
    if request.method == "POST" and request.form.get("action") == "planilla_pdf":
        blob = generar_pdf_planilla_maestra_petroleo(
            f_plan, l_plan,
            logo_path=demo.ruta_logo_pdf(),
            empresa=getattr(demo, "NOMBRE_ERP", None) or "ERP Agrícola",
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
    from demo_web.services.salida_petroleo import (
        contar_pendientes,
        links_personales_operadores,
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
        "bitacora_links_personales": [],
    }
    if ctx["bitacora_admin_qr"]:
        # Solo links personales: sin enlace genérico del estanque.
        ctx["bitacora_links_personales"] = links_personales_operadores()
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
            conn, temp[0], str(temp[1]), str(temp[2]), ref_fecha=hoy_demo(demo),
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
            "cuarteles": centros_costo(demo),
            "maquinaria_opts": _opciones_maquinaria(conn),
        }
        ctx.update(_bitacora_campo_ctx(demo, conn))
        # Alerta de desfase también visible fuera de Salida Link
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
            ctx["form_fecha"] = hoy_demo(demo).isoformat()

        return ctx
    finally:
        conn.close()


def _autorizar_bitacora(demo, user_email: str) -> dict:
    if not demo.es_admin():
        return {"ok": False, "msg": "Solo un administrador puede autorizar salidas por link."}
    from demo_web.services.salida_petroleo import autorizar_salida

    codigo = (request.form.get("codigo") or "").strip()
    result = autorizar_salida(codigo, user_email)
    if result.get("ok") and result.get("mail_ok") is False:
        result["msg"] = result["msg"] + " (aviso por correo no pudo enviarse)."
    return result


def _rechazar_bitacora(demo, user_email: str) -> dict:
    if not demo.es_admin():
        return {"ok": False, "msg": "Solo un administrador puede rechazar salidas por link."}
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
            if action == "corregir_petroleo_hist":
                result = _post_corregir_petroleo_hist(demo, conn)
                flash(result["msg"], "success" if result["ok"] else "danger")
                extra = {"sec": "historial"}
                for k in ("desde", "hasta"):
                    v = (request.form.get(k) or "").strip()
                    if v:
                        extra[k] = v
                if result.get("ok") and result.get("event_key"):
                    extra["event_key"] = result["event_key"]
                elif result.get("ok"):
                    ek = (request.form.get("event_key") or "").strip()
                    if ek:
                        extra["event_key"] = ek
                return redirect_module("petroleo", **extra)
            if action == "eliminar_petroleo_hist":
                result = _post_eliminar_petroleo_hist(demo, conn)
                flash(result["msg"], "success" if result["ok"] else "danger")
                extra = {"sec": "historial"}
                for k in ("desde", "hasta"):
                    v = (request.form.get(k) or "").strip()
                    if v:
                        extra[k] = v
                return redirect_module("petroleo", **extra)
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
