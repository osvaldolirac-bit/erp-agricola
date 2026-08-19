from __future__ import annotations

import pandas as pd
from flask import flash, render_template, request, url_for

from demo_web.services.demo_loader import bind_user_session, get_demo_module
from demo_web.services.module_runner import redirect_module, store_pdf
from demo_web.services.native import espino_bodega, espino_maquinaria
from demo_web.services.native._helpers import parse_date, temporada_sel

SECCIONES = [
    ("historial", "📜 HISTORIAL"),
    ("registro", "➕ REGISTRO"),
    ("maquinaria", "🚜 TRABAJOS MAQUINARIA"),
    *espino_bodega.BODEGA_SECCIONES,
]

_BODEGA_SECS = {k for k, _ in espino_bodega.BODEGA_SECCIONES}

TABLA = "gastos_espino"
ETIQUETA = "EL ESPINO"
ORDEN_OPTS = {
    "fecha_asc": ("Fecha ↑", True),
    "fecha_desc": ("Fecha ↓", False),
    "monto_asc": ("Monto ↑", True),
    "monto_desc": ("Monto ↓", False),
}


def _folio_interno(conn, fecha) -> str:
    prefijo = f"INT-{str(fecha).replace('-', '')}-"
    n = conn.execute(
        f"SELECT COUNT(*) FROM {TABLA} WHERE documento LIKE ?",
        (prefijo + "%",),
    ).fetchone()[0]
    return f"{prefijo}{int(n) + 1:02d}"


def _check_master(demo, clave: str) -> bool:
    return (clave or "").strip() == demo.CLAVE_MAESTRA


def _fecha_def(demo, fi, ff):
    hoy = demo.hoy
    if fi <= hoy <= ff:
        return hoy
    return ff if hoy > ff else fi


def _redirect_espino(sec: str, temp: str, **extra) -> redirect_module:
    return redirect_module("espino", sec=sec, temp=temp, **extra)


def _historial(demo, conn, nombre: str, fi, ff) -> dict:
    hoy = demo.hoy
    df_base = pd.read_sql_query(
        f"SELECT id, fecha, documento, item, monto FROM {TABLA} WHERE fecha BETWEEN ? AND ? ORDER BY fecha ASC",
        conn,
        params=(str(fi), str(ff)),
    )
    total_temp = float(df_base["monto"].sum()) if not df_base.empty else 0.0

    fi_f = parse_date(request.args.get("desde"), fi)
    ff_f = parse_date(request.args.get("hasta"), min(hoy, ff))
    if fi_f < fi:
        fi_f = fi
    if ff_f > ff:
        ff_f = ff
    buscar = (request.args.get("q") or "").strip()
    orden = request.args.get("orden", "fecha_asc")
    if orden not in ORDEN_OPTS:
        orden = "fecha_asc"

    rows = []
    mov_opts = []
    mov_edit = None
    pdf_url = None

    if not df_base.empty:
        df_show = df_base.copy()
        df_show["fecha"] = pd.to_datetime(df_show["fecha"])
        df_show = df_show[(df_show["fecha"].dt.date >= fi_f) & (df_show["fecha"].dt.date <= ff_f)]
        if buscar:
            q = buscar.upper()
            df_show = df_show[
                df_show["item"].astype(str).str.upper().str.contains(q, na=False)
                | df_show["documento"].astype(str).str.upper().str.contains(q, na=False)
            ]
        asc = ORDEN_OPTS[orden][1]
        sort_col = "monto" if orden.startswith("monto") else "fecha"
        df_show = df_show.sort_values(sort_col, ascending=asc)
        total_fil = float(df_show["monto"].sum()) if not df_show.empty else 0.0

        if not df_show.empty:
            df_pdf = df_show.copy()
            df_pdf["fecha"] = df_pdf["fecha"].dt.strftime("%Y-%m-%d")
            blob = demo.generar_pdf_blob(
                df_pdf.drop(columns=["id"]),
                f"{ETIQUETA} TEMPORADA {nombre} ({fi_f} a {ff_f})",
            )
            if blob:
                pdf_url = url_for("modules.pdf_download", token=store_pdf(blob, f"espino_{nombre}.pdf"))

        for _, r in df_show.iterrows():
            mid = int(r["id"])
            rows.append(
                {
                    "id": mid,
                    "fecha": pd.to_datetime(r["fecha"]).strftime("%d-%m-%Y"),
                    "documento": r["documento"],
                    "item": r["item"],
                    "monto": demo.f_peso(r["monto"]),
                    "monto_raw": float(r["monto"]),
                    "fecha_raw": pd.to_datetime(r["fecha"]).strftime("%Y-%m-%d"),
                }
            )
            mov_opts.append(
                {
                    "id": mid,
                    "label": f"ID {mid} · {pd.to_datetime(r['fecha']).strftime('%d-%m-%Y')} · {r['documento']} · {r['item']} · {demo.f_peso(r['monto'])}",
                }
            )

        if demo.es_admin() and rows:
            mov_sel = request.args.get("mov_id")
            if mov_sel and str(mov_sel).isdigit():
                mov_edit = next((x for x in rows if x["id"] == int(mov_sel)), rows[0])
            else:
                mov_edit = rows[0]
    else:
        total_fil = 0.0

    return {
        "historial_rows": rows,
        "mov_opts": mov_opts,
        "mov_edit": mov_edit,
        "total_temporada": demo.f_peso(total_temp),
        "total_filtrado": demo.f_peso(total_fil if rows else 0),
        "n_movimientos": len(rows),
        "filtro_q": buscar,
        "filtro_desde": fi_f.isoformat(),
        "filtro_hasta": ff_f.isoformat(),
        "orden_sel": orden,
        "orden_opts": [(k, v[0]) for k, v in ORDEN_OPTS.items()],
        "pdf_historial_url": pdf_url,
        "es_admin": demo.es_admin(),
    }


def _registro(demo, fi, ff) -> dict:
    return {
        "fecha_def": _fecha_def(demo, fi, ff).isoformat(),
        "fi_iso": fi.isoformat(),
        "ff_iso": ff.isoformat(),
    }


def _post_registrar(demo, conn, fi, ff) -> dict:
    if demo.es_solo_lectura():
        return {"ok": False, "msg": "Modo solo lectura: no puede registrar gastos."}
    item = (request.form.get("item") or "").strip()
    try:
        monto = float(request.form.get("monto") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Monto inválido."}
    fecha = parse_date(request.form.get("fecha"), demo.hoy)
    sin_doc = request.form.get("sin_doc") == "1"

    if not item or monto <= 0:
        return {"ok": False, "msg": "Detalle y monto son obligatorios."}
    if not (fi <= fecha <= ff):
        return {
            "ok": False,
            "msg": f"La fecha debe estar dentro de la temporada ({fi.strftime('%d-%m-%Y')} al {ff.strftime('%d-%m-%Y')}).",
        }

    if sin_doc:
        doc = _folio_interno(conn, fecha)
    else:
        doc = (request.form.get("documento") or "").strip()
        if not doc:
            return {"ok": False, "msg": "Ingrese N° documento o marque folio interno."}

    conn.execute(
        f"INSERT INTO {TABLA} (fecha, documento, item, monto) VALUES (?,?,?,?)",
        (str(fecha), doc, item, monto),
    )
    conn.commit()
    demo.registrar_accion(ETIQUETA, f"{doc} — {item}")
    msg = f"Gasto guardado bajo folio interno: {doc}." if sin_doc else "Gasto registrado correctamente."
    return {"ok": True, "msg": msg}


def _post_corregir(demo, conn, fi, ff) -> dict:
    if demo.es_solo_lectura():
        return {"ok": False, "msg": "Modo solo lectura: no puede corregir gastos."}
    if not demo.es_admin():
        return {"ok": False, "msg": "Requiere perfil admin."}
    if not _check_master(demo, request.form.get("clave_maestra")):
        return {"ok": False, "msg": "Clave maestra incorrecta."}
    try:
        mid = int(request.form.get("mov_id") or 0)
        monto = float(request.form.get("monto") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Datos inválidos."}
    item = (request.form.get("item") or "").strip()
    fecha = parse_date(request.form.get("fecha"), demo.hoy)
    sin_doc = request.form.get("sin_doc") == "1"

    if not mid or not item or monto <= 0:
        return {"ok": False, "msg": "Detalle y monto son obligatorios."}
    if not (fi <= fecha <= ff):
        return {"ok": False, "msg": "La fecha debe estar dentro de la temporada."}

    row = conn.execute(f"SELECT documento FROM {TABLA} WHERE id=?", (mid,)).fetchone()
    if not row:
        return {"ok": False, "msg": "Movimiento no encontrado."}
    doc_ini = str(row[0] or "").strip()

    if sin_doc:
        doc = doc_ini if doc_ini.startswith("INT-") else _folio_interno(conn, fecha)
    else:
        doc = (request.form.get("documento") or "").strip()
        if not doc:
            return {"ok": False, "msg": "Ingrese N° documento o marque folio interno."}

    conn.execute(
        f"UPDATE {TABLA} SET fecha=?, documento=?, item=?, monto=? WHERE id=?",
        (str(fecha), doc, item, monto, mid),
    )
    conn.commit()
    demo.registrar_accion(ETIQUETA, f"Corrección ID {mid} — {doc}")
    return {"ok": True, "msg": "Movimiento corregido.", "extra": {"mov_id": mid}}


def _post_eliminar(demo, conn, fi, ff) -> dict:
    if demo.es_solo_lectura():
        return {"ok": False, "msg": "Modo solo lectura: no puede eliminar gastos."}
    if not demo.es_admin():
        return {"ok": False, "msg": "Requiere perfil admin."}
    if not _check_master(demo, request.form.get("clave_maestra")):
        return {"ok": False, "msg": "Clave maestra incorrecta."}
    try:
        mid = int(request.form.get("mov_id") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Registro inválido."}
    if not mid:
        return {"ok": False, "msg": "Seleccione un registro a eliminar."}

    row = conn.execute(
        f"SELECT fecha, documento, item, monto FROM {TABLA} WHERE id=?",
        (mid,),
    ).fetchone()
    if not row:
        return {"ok": False, "msg": "Movimiento no encontrado."}

    try:
        fecha_row = parse_date(str(row[0]), demo.hoy)
    except Exception:
        fecha_row = None
    if fecha_row is not None and not (fi <= fecha_row <= ff):
        return {"ok": False, "msg": "El registro no pertenece a la temporada seleccionada."}

    conn.execute(f"DELETE FROM {TABLA} WHERE id=?", (mid,))
    conn.commit()
    detalle = f"Eliminado ID {mid} — {row[1]} — {row[2]} — {demo.f_peso(row[3])}"
    demo.registrar_accion(ETIQUETA, detalle)
    return {"ok": True, "msg": "Registro eliminado."}


def gather_espino(user_email: str, user_rol: str) -> dict:
    demo = get_demo_module()
    bind_user_session(user_email, user_rol)
    nombre, fi, ff = temporada_sel(demo, temporadas=demo.TEMPORADAS_ESPINO)
    sec = request.args.get("sec", "historial")
    bodega_op_override = None
    if sec == "bodega_mov":
        sec = "bodega"
    elif sec == "bodega_stock":
        sec = "bodega"
        bodega_op_override = "stock"
    if sec not in {k for k, _ in SECCIONES}:
        sec = "historial"

    conn = demo.conectar_db()
    try:
        ctx = {
            "secciones": SECCIONES,
            "sec_activa": sec,
            "temporadas": demo.TEMPORADAS_ESPINO,
            "temp_sel": nombre,
            "fi": fi.strftime("%d-%m-%Y"),
            "ff": ff.strftime("%d-%m-%Y"),
            "fi_iso": fi.isoformat(),
            "ff_iso": ff.isoformat(),
            "solo_lectura": demo.es_solo_lectura(),
        }
        if sec == "historial":
            ctx.update(_historial(demo, conn, nombre, fi, ff))
        elif sec == "registro":
            ctx.update(_registro(demo, fi, ff))
        elif sec == "maquinaria":
            ctx.update(espino_maquinaria.gather_maquinaria(demo, conn, fi, ff))
        elif sec == "bodega":
            ctx.update(espino_bodega.gather_bodega(demo, conn, op_override=bodega_op_override))
        return ctx
    finally:
        conn.close()


def view(user_email: str, user_rol: str):
    demo = get_demo_module()
    bind_user_session(user_email, user_rol)
    nombre, fi, ff = temporada_sel(demo, temporadas=demo.TEMPORADAS_ESPINO)

    if request.method == "POST":
        action = request.form.get("action", "")
        sec = request.form.get("sec") or request.args.get("sec", "registro")
        if sec in ("bodega_mov", "bodega_stock"):
            sec = "bodega"
        temp = request.form.get("temp") or nombre
        conn = demo.conectar_db()
        try:
            handlers = {
                "registrar": _post_registrar,
                "corregir": _post_corregir,
                "eliminar": _post_eliminar,
                "maquinaria_registrar": espino_maquinaria.post_registrar,
                "maquinaria_ingreso": espino_maquinaria.post_ingreso,
                "bodega_salida": espino_bodega.post_salida,
                "bodega_ingreso": espino_bodega.post_ingreso,
            }
            fn = handlers.get(action)
            if fn:
                if action.startswith("bodega_"):
                    result = fn(demo, conn)
                else:
                    result = fn(demo, conn, fi, ff)
                flash(result["msg"], "success" if result["ok"] else "danger")
                extra = {"sec": sec, "temp": temp}
                extra.update(result.get("extra") or {})
                for k in ("q", "desde", "hasta", "orden", "op"):
                    if request.form.get(k):
                        extra[k] = request.form.get(k)
                if action.startswith("bodega_"):
                    extra["sec"] = "bodega"
                    if action == "bodega_ingreso":
                        extra["op"] = request.form.get("op") or request.form.get("modo") or "ingreso"
                        if extra["op"] == "existente":
                            extra["op"] = "ingreso"
                    elif action == "bodega_salida":
                        extra["op"] = "salida"
                if action.startswith("maquinaria_"):
                    extra["sec"] = "maquinaria"
                    if "op" not in extra:
                        extra["op"] = request.form.get("op") or "libro"
                if action == "corregir" and "mov_id" not in extra:
                    extra["mov_id"] = request.form.get("mov_id", "")
                return _redirect_espino(**extra)
        finally:
            conn.close()

    ctx = gather_espino(user_email, user_rol)
    return render_template(
        "modules/espino.html",
        page_title="El Espino",
        active_key="Espino",
        title="🏡 El Espino",
        **ctx,
    )
