"""Trabajos maquinaria sector El Espino — gastos, debe/haber y abonos."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
from flask import request, session, url_for

from demo_web.services.module_runner import store_pdf
from demo_web.services.native._helpers import hoy_demo, parse_date

TABLA = "trabajos_maquinaria_espino"
TABLA_MOV = "trabajos_maquinaria_espino_mov"
ETIQUETA = "EL ESPINO"

MAQ_OPS = [
    ("gastos", "📋 Gastos maquinaria"),
    ("abono", "📥 Abono"),
    ("trabajo", "➕ Registrar trabajo"),
]

_MAQ_OP_ALIASES = {
    "libro": "gastos",
    "detalle": "gastos",
    "ingreso": "abono",
}

ETIQUETA_TRABAJOS = f"{ETIQUETA} — TRABAJOS MAQUINARIA"


def _folio_trabajo(conn, fecha) -> str:
    prefijo = f"INT-{str(fecha).replace('-', '')}-"
    n = conn.execute(
        f"SELECT COUNT(*) FROM {TABLA} WHERE documento LIKE ?",
        (prefijo + "%",),
    ).fetchone()[0]
    return f"{prefijo}{int(n) + 1:02d}"


def _folio_ingreso(conn, fecha) -> str:
    prefijo = f"ABO-{str(fecha).replace('-', '')}-"
    n = conn.execute(
        f"SELECT COUNT(*) FROM {TABLA_MOV} WHERE documento LIKE ?",
        (prefijo + "%",),
    ).fetchone()[0]
    return f"{prefijo}{int(n) + 1:02d}"


def _select_maquinaria(conn, tipos=None) -> list[dict]:
    from erp_maquinaria import etiqueta_maquinaria, listar_maquinaria

    items = listar_maquinaria(conn, solo_activos=True, tipos=tipos)
    return [
        {
            "codigo": m["codigo"],
            "label": etiqueta_maquinaria(m["codigo"], m["nombre"]),
            "nombre": m["nombre"],
        }
        for m in items
    ]


def _combo_maquinaria(tractor_lbl: str, implemento_lbl: str) -> str:
    if implemento_lbl:
        return f"{tractor_lbl} + {implemento_lbl}"
    return tractor_lbl


def _hectareas_efectivas(raw) -> float:
    try:
        ha = float(raw or 0)
    except (TypeError, ValueError):
        ha = 0.0
    return ha if ha > 0 else 1.0


def _horas_txt(raw) -> tuple[str, float | None]:
    if raw is None or str(raw).strip() == "":
        return "—", None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return "—", None
    return f"{val:g}", val


def _maq_op_activa() -> str:
    op = (request.args.get("op") or request.form.get("op") or "gastos").strip().lower()
    op = _MAQ_OP_ALIASES.get(op, op)
    if op not in {k for k, _ in MAQ_OPS}:
        op = "gastos"
    return op


def _admin_clave_ok(demo) -> tuple[bool, str]:
    if demo.es_solo_lectura():
        return False, "Modo solo lectura: no puede modificar ni eliminar registros."
    if not demo.es_admin():
        return False, "Requiere perfil admin."
    if (request.form.get("clave_maestra") or "").strip() != demo.CLAVE_MAESTRA:
        return False, "Clave maestra incorrecta."
    return True, ""


def _fecha_en_temporada(fecha, fi, ff) -> bool:
    return fi <= fecha <= ff


def _maq_mov_opts(demo, conn, fi_f, ff_f) -> list[dict]:
    opts: list[dict] = []
    for r in conn.execute(
        f"""SELECT id, fecha, documento, tractor, implemento, trabajo, monto
            FROM {TABLA} WHERE fecha BETWEEN ? AND ? ORDER BY fecha ASC, id ASC""",
        (str(fi_f), str(ff_f)),
    ).fetchall():
        lbl = (
            f"Trabajo ID {r[0]} · {str(r[1])[:10]} · {r[2] or '—'} · "
            f"{r[5] or '—'} · {demo.f_peso(float(r[6] or 0))}"
        )
        opts.append({"id": int(r[0]), "kind": "trabajo", "label": lbl})
    for r in conn.execute(
        f"""SELECT id, fecha, documento, detalle, haber
            FROM {TABLA_MOV}
            WHERE fecha BETWEEN ? AND ? AND COALESCE(haber, 0) > 0
            ORDER BY fecha ASC, id ASC""",
        (str(fi_f), str(ff_f)),
    ).fetchall():
        lbl = (
            f"Abono ID {r[0]} · {str(r[1])[:10]} · {r[2] or '—'} · "
            f"{r[3] or 'Abono'} · {demo.f_peso(float(r[4] or 0))}"
        )
        opts.append({"id": int(r[0]), "kind": "abono", "label": lbl})
    return opts


def _cargar_maq_edit(conn, demo, fi_f, ff_f) -> dict | None:
    sel_id = (request.args.get("maq_id") or "").strip()
    sel_kind = (request.args.get("maq_kind") or "").strip()
    if not sel_id.isdigit() or sel_kind not in ("trabajo", "abono"):
        return None
    row_id = int(sel_id)
    if sel_kind == "trabajo":
        r = conn.execute(
            f"""SELECT id, fecha, documento, tractor_codigo, tractor, implemento_codigo,
                       implemento, trabajo, horas, hectareas, monto_tractor, monto_implemento, monto
                FROM {TABLA} WHERE id=?""",
            (row_id,),
        ).fetchone()
        if not r:
            return None
        fecha = parse_date(str(r[1])[:10], hoy_demo(demo))
        if not _fecha_en_temporada(fecha, fi_f, ff_f):
            return None
        ha_raw = r[9]
        try:
            ha_val = float(ha_raw) if ha_raw is not None else 0.0
        except (TypeError, ValueError):
            ha_val = 0.0
        horas_raw = r[8]
        return {
            "maq_id": int(r[0]),
            "maq_kind": "trabajo",
            "fecha_raw": str(r[1])[:10],
            "documento": r[2] or "",
            "sin_doc": bool(str(r[2] or "").startswith("INT-")),
            "tractor_codigo": (r[3] or "").strip(),
            "implemento_codigo": (r[5] or "").strip(),
            "trabajo": r[7] or "",
            "horas": "" if horas_raw is None else f"{float(horas_raw):g}",
            "hectareas": ha_val,
            "monto_tractor": float(r[10] or 0),
            "monto_implemento": float(r[11] or 0),
            "monto_raw": float(r[12] or 0),
            "detalle": "",
            "haber_raw": 0.0,
        }
    r = conn.execute(
        f"SELECT id, fecha, documento, detalle, haber FROM {TABLA_MOV} WHERE id=?",
        (row_id,),
    ).fetchone()
    if not r:
        return None
    fecha = parse_date(str(r[1])[:10], hoy_demo(demo))
    if not _fecha_en_temporada(fecha, fi_f, ff_f):
        return None
    return {
        "maq_id": int(r[0]),
        "maq_kind": "abono",
        "fecha_raw": str(r[1])[:10],
        "documento": r[2] or "",
        "sin_doc": bool(str(r[2] or "").startswith("ABO-")),
        "detalle": r[3] or "",
        "haber_raw": float(r[4] or 0),
        "tractor_codigo": "",
        "implemento_codigo": "",
        "trabajo": "",
        "horas": "",
        "hectareas": 0.0,
        "monto_tractor": 0.0,
        "monto_implemento": 0.0,
        "monto_raw": 0.0,
    }


def _tabla_gastos_unificada(
    demo, conn, nombre: str, fi_f, ff_f
) -> tuple[list[dict], float, float, float, int, str | None]:
    """Tabla única: detalle faenas + filas abono, columnas Haber y Saldo."""
    buscar = (request.args.get("q") or "").strip().upper()
    raw: list[dict] = []

    trabajos = conn.execute(
        f"""SELECT id, fecha, documento,
                   tractor, implemento, trabajo, horas, hectareas,
                   monto_tractor, monto_implemento, monto
            FROM {TABLA}
            WHERE fecha BETWEEN ? AND ?
            ORDER BY fecha ASC, id ASC""",
        (str(fi_f), str(ff_f)),
    ).fetchall()
    for r in trabajos:
        ha = _hectareas_efectivas(r[7])
        mt = float(r[8] or 0)
        mi = float(r[9] or 0)
        tot_tr = mt * ha
        tot_imp = mi * ha
        monto = float(r[10] or (tot_tr + tot_imp))
        raw.append(
            {
                "row_id": int(r[0]),
                "sort": (str(r[1])[:10], 0, int(r[0])),
                "kind": "trabajo",
                "fecha": str(r[1])[:10],
                "documento": r[2] or "",
                "tractor": r[3] or "—",
                "implemento": r[4] or "—",
                "trabajo": r[5] or "",
                "horas_raw": r[6],
                "ha": ha,
                "monto_tr": mt,
                "monto_imp": mi,
                "tot_tr": tot_tr,
                "tot_imp": tot_imp,
                "debe": monto,
                "haber": 0.0,
            }
        )

    movs = conn.execute(
        f"""SELECT id, fecha, documento, detalle, tipo_mov, haber
            FROM {TABLA_MOV}
            WHERE fecha BETWEEN ? AND ?
            ORDER BY fecha ASC, id ASC""",
        (str(fi_f), str(ff_f)),
    ).fetchall()
    for r in movs:
        haber = float(r[5] or 0)
        if haber <= 0:
            continue
        raw.append(
            {
                "row_id": int(r[0]),
                "sort": (str(r[1])[:10], 1, int(r[0])),
                "kind": "abono",
                "fecha": str(r[1])[:10],
                "documento": r[2] or "",
                "tractor": "—",
                "implemento": "—",
                "trabajo": r[3] or "Abono",
                "horas_raw": None,
                "ha": None,
                "monto_tr": 0.0,
                "monto_imp": 0.0,
                "tot_tr": 0.0,
                "tot_imp": 0.0,
                "debe": 0.0,
                "haber": haber,
            }
        )

    raw.sort(key=lambda x: x["sort"])
    rows: list[dict] = []
    pdf_rows: list[dict] = []
    saldo = 0.0
    tot_debe = tot_haber = 0.0
    n_trabajos = 0

    for item in raw:
        if buscar:
            blob = " ".join(
                str(x or "")
                for x in (
                    item["documento"],
                    item["tractor"],
                    item["implemento"],
                    item["trabajo"],
                )
            ).upper()
            if buscar not in blob:
                continue

        debe = item["debe"]
        haber = item["haber"]
        saldo += debe - haber
        tot_debe += debe
        tot_haber += haber
        if item["kind"] == "trabajo":
            n_trabajos += 1

        horas_txt, _ = _horas_txt(item["horas_raw"])
        fecha_fmt = pd.to_datetime(item["fecha"]).strftime("%d-%m-%Y")
        es_abono = item["kind"] == "abono"

        if es_abono:
            row = {
                "maq_id": item["row_id"],
                "maq_kind": "abono",
                "fecha": fecha_fmt,
                "documento": item["documento"],
                "tractor": "—",
                "implemento": "—",
                "trabajo": item["trabajo"],
                "horas": "—",
                "hectareas": "—",
                "monto_tractor": "",
                "monto_implemento": "",
                "total_tractor": "",
                "total_implemento": "",
                "monto": "",
                "haber": demo.f_peso(haber),
                "saldo": demo.f_peso(saldo),
                "es_abono": True,
            }
        else:
            ha = item["ha"]
            row = {
                "maq_id": item["row_id"],
                "maq_kind": "trabajo",
                "fecha": fecha_fmt,
                "documento": item["documento"],
                "tractor": item["tractor"],
                "implemento": item["implemento"],
                "trabajo": item["trabajo"],
                "horas": horas_txt,
                "hectareas": f"{ha:g}",
                "monto_tractor": demo.f_peso(item["monto_tr"]),
                "monto_implemento": demo.f_peso(item["monto_imp"]),
                "total_tractor": demo.f_peso(item["tot_tr"]),
                "total_implemento": demo.f_peso(item["tot_imp"]),
                "monto": demo.f_peso(debe),
                "haber": "",
                "saldo": demo.f_peso(saldo),
                "es_abono": False,
            }

        rows.append(row)
        pdf_rows.append(
            {
                "fecha": pd.to_datetime(item["fecha"]).strftime("%Y-%m-%d"),
                "Documento": item["documento"],
                "Tractor": row["tractor"],
                "Implemento": row["implemento"],
                "Trabajo": row["trabajo"],
                "Horas": row["horas"] if row["horas"] != "—" else "",
                "Ha": row["hectareas"] if row["hectareas"] != "—" else "",
                "Valor tractor $/ha": row["monto_tractor"],
                "Valor implemento $/ha": row["monto_implemento"],
                "Total tractor": row["total_tractor"],
                "Total implemento": row["total_implemento"],
                "Total": row["monto"],
                "Haber": row["haber"],
                "Saldo": row["saldo"],
            }
        )

    pdf_url = None
    if pdf_rows:
        cols_pdf = [
            "fecha",
            "Documento",
            "Tractor",
            "Implemento",
            "Trabajo",
            "Horas",
            "Ha",
            "Valor tractor $/ha",
            "Valor implemento $/ha",
            "Total tractor",
            "Total implemento",
            "Total",
            "Haber",
            "Saldo",
        ]
        df_pdf = pd.DataFrame(pdf_rows)[cols_pdf]
        blob = demo.generar_pdf_blob(
            df_pdf,
            f"{ETIQUETA_TRABAJOS} TEMPORADA {nombre} ({fi_f} a {ff_f})",
        )
        if blob:
            pdf_url = url_for(
                "modules.pdf_download",
                token=store_pdf(blob, f"espino_trabajos_{nombre}.pdf"),
            )

    return rows, tot_debe, tot_haber, saldo, n_trabajos, pdf_url


def gather_maquinaria(demo, conn, fi, ff, nombre: str = "") -> dict:
    hoy = hoy_demo(demo)
    fi_f = parse_date(request.args.get("desde"), fi)
    ff_f = parse_date(request.args.get("hasta"), min(hoy, ff))
    if fi_f < fi:
        fi_f = fi
    if ff_f > ff:
        ff_f = ff

    op = _maq_op_activa()
    gastos_rows, tot_debe, tot_haber, saldo, n_trabajos, pdf_gastos = _tabla_gastos_unificada(
        demo, conn, nombre or "temp", fi_f, ff_f
    )

    from erp_maquinaria import TIPOS_MAQUINARIA_TRACTOR, TIPOS_MAQUINARIA_APLICACION

    maq_mov_opts = _maq_mov_opts(demo, conn, fi_f, ff_f) if demo.es_admin() else []
    maq_edit = None
    if demo.es_admin() and (request.args.get("maq_id") or "").strip().isdigit():
        maq_edit = _cargar_maq_edit(conn, demo, fi_f, ff_f)

    return {
        "maq_ops": MAQ_OPS,
        "maq_op_activa": op,
        "es_admin": demo.es_admin(),
        "maq_mov_opts": maq_mov_opts,
        "maq_edit": maq_edit,
        "trabajos_rows": gastos_rows,
        "trabajos_n": n_trabajos,
        "trabajos_total": demo.f_peso(tot_debe),
        "libro_n": len(gastos_rows),
        "libro_tot_debe": demo.f_peso(tot_debe),
        "libro_tot_haber": demo.f_peso(tot_haber),
        "libro_saldo": demo.f_peso(saldo),
        "pdf_trabajos_url": pdf_gastos,
        "filtro_q": (request.args.get("q") or "").strip(),
        "filtro_desde": fi_f.isoformat(),
        "filtro_hasta": ff_f.isoformat(),
        "tractores": _select_maquinaria(conn, TIPOS_MAQUINARIA_TRACTOR),
        "implementos": _select_maquinaria(conn, TIPOS_MAQUINARIA_APLICACION),
        "fecha_def": (hoy if fi <= hoy <= ff else (ff if hoy > ff else fi)).isoformat(),
    }


def _parse_trabajo_form(demo, conn, fi, ff) -> tuple[dict | None, str]:
    from erp_maquinaria import etiqueta_maquinaria

    fecha = parse_date(request.form.get("fecha"), hoy_demo(demo))
    trabajo = (request.form.get("trabajo") or "").strip()
    sin_doc = request.form.get("sin_doc") == "1"
    tr_cod = (request.form.get("tractor_codigo") or "").strip()
    imp_cod = (request.form.get("implemento_codigo") or "").strip()

    try:
        hectareas = float(request.form.get("hectareas") or 0)
        monto_tr = float(request.form.get("monto_tractor") or 0)
        monto_imp = float(request.form.get("monto_implemento") or 0)
        horas = request.form.get("horas")
        horas_f = float(horas) if horas not in (None, "") else None
    except (TypeError, ValueError):
        return None, "Datos numéricos inválidos."

    if not tr_cod:
        return None, "Seleccione el tractor."
    if not trabajo:
        return None, "Indique el detalle del trabajo."
    if not _fecha_en_temporada(fecha, fi, ff):
        return None, (
            f"La fecha debe estar dentro de la temporada "
            f"({fi.strftime('%d-%m-%Y')} al {ff.strftime('%d-%m-%Y')})."
        )

    tr_row = conn.execute(
        "SELECT nombre FROM maestra_maquinaria WHERE UPPER(TRIM(codigo))=?",
        (tr_cod.upper(),),
    ).fetchone()
    if not tr_row:
        return None, "Tractor no encontrado en maestra."
    tr_lbl = etiqueta_maquinaria(tr_cod, tr_row[0])

    imp_lbl = ""
    if imp_cod:
        imp_row = conn.execute(
            "SELECT nombre FROM maestra_maquinaria WHERE UPPER(TRIM(codigo))=?",
            (imp_cod.upper(),),
        ).fetchone()
        if not imp_row:
            return None, "Implemento no encontrado en maestra."
        imp_lbl = etiqueta_maquinaria(imp_cod, imp_row[0])

    ha_eff = _hectareas_efectivas(hectareas)
    monto = (monto_tr + monto_imp) * ha_eff
    if monto <= 0:
        return None, "Indique valores $/ha de tractor y/o implemento."

    return {
        "fecha": fecha,
        "trabajo": trabajo,
        "sin_doc": sin_doc,
        "tr_cod": tr_cod,
        "imp_cod": imp_cod,
        "tr_lbl": tr_lbl,
        "imp_lbl": imp_lbl,
        "horas_f": horas_f,
        "monto": monto,
        "monto_tr": monto_tr,
        "monto_imp": monto_imp,
        "hectareas": hectareas,
        "combo": _combo_maquinaria(tr_lbl, imp_lbl),
    }, ""


def _documento_trabajo(conn, fecha, sin_doc: bool, doc_form: str, doc_actual: str = "") -> tuple[str | None, str]:
    if sin_doc:
        doc_ini = str(doc_actual or "").strip()
        if doc_ini.startswith("INT-"):
            return doc_ini, ""
        return _folio_trabajo(conn, fecha), ""
    doc = (doc_form or "").strip()
    if not doc:
        return None, "Ingrese N° documento o marque folio interno."
    return doc, ""


def post_registrar(demo, conn, fi, ff) -> dict:
    if demo.es_solo_lectura():
        return {"ok": False, "msg": "Modo solo lectura: no puede registrar trabajos."}

    data, err = _parse_trabajo_form(demo, conn, fi, ff)
    if err:
        return {"ok": False, "msg": err}

    doc, err = _documento_trabajo(
        conn, data["fecha"], data["sin_doc"], request.form.get("documento") or ""
    )
    if err:
        return {"ok": False, "msg": err}

    conn.execute(
        f"""INSERT INTO {TABLA}
            (fecha, documento, maquinaria_codigo, maquinaria, trabajo, horas, monto,
             tractor_codigo, tractor, implemento_codigo, implemento,
             monto_tractor, monto_implemento, hectareas)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            str(data["fecha"]),
            doc,
            data["tr_cod"],
            data["combo"],
            data["trabajo"],
            data["horas_f"],
            data["monto"],
            data["tr_cod"],
            data["tr_lbl"],
            data["imp_cod"],
            data["imp_lbl"],
            data["monto_tr"],
            data["monto_imp"],
            data["hectareas"] if data["hectareas"] > 0 else None,
        ),
    )
    conn.commit()
    demo.registrar_accion(ETIQUETA, f"Trabajo maquinaria {doc} — {data['trabajo']}")
    return {
        "ok": True,
        "msg": f"Trabajo registrado ({demo.f_peso(data['monto'])}). Imputado al Debe.",
        "extra": {"op": "gastos"},
    }


def post_ingreso(demo, conn, fi, ff) -> dict:
    if demo.es_solo_lectura():
        return {"ok": False, "msg": "Modo solo lectura: no puede registrar abonos."}

    fecha = parse_date(request.form.get("fecha"), hoy_demo(demo))
    detalle = (request.form.get("detalle") or "").strip()
    sin_doc = request.form.get("sin_doc") == "1"
    try:
        monto = float(request.form.get("monto") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Monto inválido."}

    if monto <= 0:
        return {"ok": False, "msg": "Indique un monto de abono mayor a cero."}
    if not detalle:
        return {"ok": False, "msg": "Indique el detalle del abono."}
    if not (fi <= fecha <= ff):
        return {"ok": False, "msg": "La fecha debe estar dentro de la temporada."}

    if sin_doc:
        doc = _folio_ingreso(conn, fecha)
    else:
        doc = (request.form.get("documento") or "").strip()
        if not doc:
            return {"ok": False, "msg": "Ingrese N° documento o marque folio interno."}

    usuario = (session.get("email") or session.get("user_email") or "").strip()
    f_reg = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        f"""INSERT INTO {TABLA_MOV}
            (fecha, documento, detalle, tipo_mov, debe, haber, usuario, fecha_registro)
            VALUES (?,?,?,?,?,?,?,?)""",
        (str(fecha), doc, detalle, "Ingreso", 0.0, monto, usuario, f_reg),
    )
    conn.commit()
    demo.registrar_accion(ETIQUETA, f"Abono maquinaria {doc} — {detalle}")
    return {"ok": True, "msg": f"Abono registrado ({demo.f_peso(monto)}).", "extra": {"op": "gastos"}}


def _documento_abono(conn, fecha, sin_doc: bool, doc_form: str, doc_actual: str = "") -> tuple[str | None, str]:
    if sin_doc:
        doc_ini = str(doc_actual or "").strip()
        if doc_ini.startswith("ABO-"):
            return doc_ini, ""
        return _folio_ingreso(conn, fecha), ""
    doc = (doc_form or "").strip()
    if not doc:
        return None, "Ingrese N° documento o marque folio interno."
    return doc, ""


def _extra_gastos_redirect(row_id: int | None = None, kind: str | None = None) -> dict:
    extra: dict = {"op": "gastos"}
    if row_id is not None:
        extra["maq_id"] = str(row_id)
    if kind:
        extra["maq_kind"] = kind
    return extra


def post_modificar(demo, conn, fi, ff) -> dict:
    ok, msg = _admin_clave_ok(demo)
    if not ok:
        return {"ok": False, "msg": msg}

    kind = (request.form.get("maq_kind") or "").strip()
    try:
        row_id = int(request.form.get("maq_id") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Registro inválido."}
    if not row_id or kind not in ("trabajo", "abono"):
        return {"ok": False, "msg": "Seleccione un registro válido."}

    if kind == "trabajo":
        exists = conn.execute(f"SELECT documento FROM {TABLA} WHERE id=?", (row_id,)).fetchone()
        if not exists:
            return {"ok": False, "msg": "Trabajo no encontrado."}
        data, err = _parse_trabajo_form(demo, conn, fi, ff)
        if err:
            return {"ok": False, "msg": err}
        doc, err = _documento_trabajo(
            conn,
            data["fecha"],
            data["sin_doc"],
            request.form.get("documento") or "",
            str(exists[0] or ""),
        )
        if err:
            return {"ok": False, "msg": err}
        conn.execute(
            f"""UPDATE {TABLA}
                SET fecha=?, documento=?, maquinaria_codigo=?, maquinaria=?, trabajo=?,
                    horas=?, monto=?, tractor_codigo=?, tractor=?,
                    implemento_codigo=?, implemento=?,
                    monto_tractor=?, monto_implemento=?, hectareas=?
                WHERE id=?""",
            (
                str(data["fecha"]),
                doc,
                data["tr_cod"],
                data["combo"],
                data["trabajo"],
                data["horas_f"],
                data["monto"],
                data["tr_cod"],
                data["tr_lbl"],
                data["imp_cod"],
                data["imp_lbl"],
                data["monto_tr"],
                data["monto_imp"],
                data["hectareas"] if data["hectareas"] > 0 else None,
                row_id,
            ),
        )
        conn.commit()
        demo.registrar_accion(ETIQUETA, f"Corrección trabajo maquinaria ID {row_id} — {doc}")
        return {
            "ok": True,
            "msg": "Trabajo corregido.",
            "extra": _extra_gastos_redirect(row_id, "trabajo"),
        }

    exists = conn.execute(
        f"SELECT documento FROM {TABLA_MOV} WHERE id=? AND COALESCE(haber, 0) > 0",
        (row_id,),
    ).fetchone()
    if not exists:
        return {"ok": False, "msg": "Abono no encontrado."}

    fecha = parse_date(request.form.get("fecha"), hoy_demo(demo))
    detalle = (request.form.get("detalle") or "").strip()
    sin_doc = request.form.get("sin_doc") == "1"
    try:
        monto = float(request.form.get("monto") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Monto inválido."}
    if monto <= 0:
        return {"ok": False, "msg": "Indique un monto de abono mayor a cero."}
    if not detalle:
        return {"ok": False, "msg": "Indique el detalle del abono."}
    if not _fecha_en_temporada(fecha, fi, ff):
        return {"ok": False, "msg": "La fecha debe estar dentro de la temporada."}

    doc, err = _documento_abono(
        conn,
        fecha,
        sin_doc,
        request.form.get("documento") or "",
        str(exists[0] or ""),
    )
    if err:
        return {"ok": False, "msg": err}

    conn.execute(
        f"""UPDATE {TABLA_MOV}
            SET fecha=?, documento=?, detalle=?, haber=?
            WHERE id=?""",
        (str(fecha), doc, detalle, monto, row_id),
    )
    conn.commit()
    demo.registrar_accion(ETIQUETA, f"Corrección abono maquinaria ID {row_id} — {doc}")
    return {
        "ok": True,
        "msg": "Abono corregido.",
        "extra": _extra_gastos_redirect(row_id, "abono"),
    }


def post_eliminar(demo, conn, fi, ff) -> dict:
    ok, msg = _admin_clave_ok(demo)
    if not ok:
        return {"ok": False, "msg": msg}

    kind = (request.form.get("maq_kind") or "").strip()
    try:
        row_id = int(request.form.get("maq_id") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Registro inválido."}
    if not row_id or kind not in ("trabajo", "abono"):
        return {"ok": False, "msg": "Seleccione un registro a eliminar."}

    if kind == "trabajo":
        row = conn.execute(
            f"SELECT fecha, documento, trabajo FROM {TABLA} WHERE id=?",
            (row_id,),
        ).fetchone()
        if not row:
            return {"ok": False, "msg": "Trabajo no encontrado."}
        fecha = parse_date(str(row[0])[:10], hoy_demo(demo))
        if not _fecha_en_temporada(fecha, fi, ff):
            return {"ok": False, "msg": "El registro no pertenece a la temporada seleccionada."}
        conn.execute(f"DELETE FROM {TABLA} WHERE id=?", (row_id,))
        conn.commit()
        demo.registrar_accion(ETIQUETA, f"Eliminado trabajo maquinaria ID {row_id} — {row[1]}")
        return {"ok": True, "msg": "Trabajo eliminado.", "extra": {"op": "gastos"}}

    row = conn.execute(
        f"SELECT fecha, documento, detalle FROM {TABLA_MOV} WHERE id=? AND COALESCE(haber, 0) > 0",
        (row_id,),
    ).fetchone()
    if not row:
        return {"ok": False, "msg": "Abono no encontrado."}
    fecha = parse_date(str(row[0])[:10], hoy_demo(demo))
    if not _fecha_en_temporada(fecha, fi, ff):
        return {"ok": False, "msg": "El registro no pertenece a la temporada seleccionada."}
    conn.execute(f"DELETE FROM {TABLA_MOV} WHERE id=?", (row_id,))
    conn.commit()
    demo.registrar_accion(ETIQUETA, f"Eliminado abono maquinaria ID {row_id} — {row[1]}")
    return {"ok": True, "msg": "Abono eliminado.", "extra": {"op": "gastos"}}
