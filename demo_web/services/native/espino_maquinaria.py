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


def _detalle_trabajo(trabajo: str, tractor: str, implemento: str, monto_tr: float, monto_imp: float, demo) -> str:
    parts = [trabajo.strip()]
    if tractor:
        parts.append(str(tractor).split(" — ", 1)[-1][:40])
    if monto_tr or monto_imp:
        parts.append(f"Tr: {demo.f_peso(monto_tr)}")
        if monto_imp:
            parts.append(f"Imp: {demo.f_peso(monto_imp)}")
    return " · ".join(p for p in parts if p)


def _maq_op_activa() -> str:
    op = (request.args.get("op") or request.form.get("op") or "gastos").strip().lower()
    op = _MAQ_OP_ALIASES.get(op, op)
    if op not in {k for k, _ in MAQ_OPS}:
        op = "gastos"
    return op


def _libro_mayor(demo, conn, fi_f, ff_f) -> tuple[list[dict], float, float, str | None]:
    raw = []

    trabajos = conn.execute(
        f"""SELECT id, fecha, documento, trabajo, tractor, implemento,
                   monto, monto_tractor, monto_implemento
            FROM {TABLA}
            WHERE fecha BETWEEN ? AND ?
            ORDER BY fecha ASC, id ASC""",
        (str(fi_f), str(ff_f)),
    ).fetchall()
    for r in trabajos:
        monto = float(r[6] or 0)
        monto_tr = float(r[7] or 0)
        monto_imp = float(r[8] or 0)
        raw.append(
            {
                "sort": (str(r[1]), 0, int(r[0])),
                "fecha": str(r[1])[:10],
                "tipo": "Trabajo",
                "documento": r[2] or "",
                "detalle": _detalle_trabajo(r[3] or "", r[4] or "", r[5] or "", monto_tr, monto_imp, demo),
                "debe": monto,
                "haber": 0.0,
            }
        )

    movs = conn.execute(
        f"""SELECT id, fecha, documento, detalle, tipo_mov, debe, haber
            FROM {TABLA_MOV}
            WHERE fecha BETWEEN ? AND ?
            ORDER BY fecha ASC, id ASC""",
        (str(fi_f), str(ff_f)),
    ).fetchall()
    for r in movs:
        raw.append(
            {
                "sort": (str(r[1]), 1, int(r[0])),
                "fecha": str(r[1])[:10],
                "tipo": "Abono" if (r[4] or "").strip().lower() == "ingreso" else (r[4] or "Movimiento"),
                "documento": r[2] or "",
                "detalle": r[3] or "",
                "debe": float(r[5] or 0),
                "haber": float(r[6] or 0),
            }
        )

    raw.sort(key=lambda x: x["sort"])
    rows = []
    saldo = 0.0
    tot_debe = tot_haber = 0.0
    for item in raw:
        debe = item["debe"]
        haber = item["haber"]
        saldo += debe - haber
        tot_debe += debe
        tot_haber += haber
        rows.append(
            {
                "fecha": pd.to_datetime(item["fecha"]).strftime("%d-%m-%Y"),
                "tipo": item["tipo"],
                "documento": item["documento"],
                "detalle": item["detalle"],
                "debe": demo.f_peso(debe) if debe else "",
                "haber": demo.f_peso(haber) if haber else "",
                "saldo": demo.f_peso(saldo),
            }
        )

    pdf_url = None
    if rows:
        df_pdf = pd.DataFrame(
            [
                {
                    "FECHA": r["fecha"],
                    "TIPO": r["tipo"],
                    "DOCUMENTO": r["documento"],
                    "DETALLE": r["detalle"],
                    "DEBE": r["debe"],
                    "HABER": r["haber"],
                    "SALDO": r["saldo"],
                }
                for r in rows
            ]
        )
        blob = demo.generar_pdf_blob(
            df_pdf,
            f"GASTOS MAQUINARIA DEBE/HABER {ETIQUETA} ({fi_f} a {ff_f})",
        )
        if blob:
            pdf_url = url_for("modules.pdf_download", token=store_pdf(blob, "espino_maquinaria_libro.pdf"))

    return rows, tot_debe, tot_haber, pdf_url


def _trabajos_detalle(demo, conn, nombre: str, fi_f, ff_f) -> tuple[list[dict], float, str | None]:
    rows_raw = conn.execute(
        f"""SELECT id, fecha, documento,
                   tractor, implemento, trabajo, horas, hectareas,
                   monto_tractor, monto_implemento, monto
            FROM {TABLA}
            WHERE fecha BETWEEN ? AND ?
            ORDER BY fecha ASC, id ASC""",
        (str(fi_f), str(ff_f)),
    ).fetchall()

    buscar = (request.args.get("q") or "").strip().upper()
    rows = []
    total = 0.0
    pdf_rows = []

    for r in rows_raw:
        ha = _hectareas_efectivas(r[7])
        mt = float(r[8] or 0)
        mi = float(r[9] or 0)
        tot_tr = mt * ha
        tot_imp = mi * ha
        monto = float(r[10] or (tot_tr + tot_imp))
        tractor = r[3] or "—"
        implemento = r[4] or "—"
        trabajo = r[5] or ""
        horas_txt, _ = _horas_txt(r[6])

        if buscar:
            blob = " ".join(
                str(x or "")
                for x in (r[2], tractor, implemento, trabajo)
            ).upper()
            if buscar not in blob:
                continue

        total += monto
        fecha_fmt = pd.to_datetime(str(r[1])[:10]).strftime("%d-%m-%Y")
        rows.append(
            {
                "fecha": fecha_fmt,
                "documento": r[2] or "",
                "tractor": tractor,
                "implemento": implemento,
                "trabajo": trabajo,
                "horas": horas_txt,
                "hectareas": f"{ha:g}" if ha else "—",
                "monto_tractor": demo.f_peso(mt),
                "monto_implemento": demo.f_peso(mi),
                "total_tractor": demo.f_peso(tot_tr),
                "total_implemento": demo.f_peso(tot_imp),
                "monto": demo.f_peso(monto),
            }
        )
        pdf_rows.append(
            {
                "fecha": pd.to_datetime(str(r[1])[:10]).strftime("%Y-%m-%d"),
                "Documento": r[2] or "",
                "Tractor": tractor,
                "Implemento": implemento,
                "Trabajo": trabajo,
                "Horas": horas_txt if horas_txt != "—" else "",
                "Ha": ha,
                "Valor tractor $/ha": demo.f_peso(mt),
                "Valor implemento $/ha": demo.f_peso(mi),
                "Total tractor": demo.f_peso(tot_tr),
                "Total implemento": demo.f_peso(tot_imp),
                "Total": demo.f_peso(monto),
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

    return rows, total, pdf_url


def gather_maquinaria(demo, conn, fi, ff, nombre: str = "") -> dict:
    hoy = hoy_demo(demo)
    fi_f = parse_date(request.args.get("desde"), fi)
    ff_f = parse_date(request.args.get("hasta"), min(hoy, ff))
    if fi_f < fi:
        fi_f = fi
    if ff_f > ff:
        ff_f = ff

    op = _maq_op_activa()
    libro_rows, tot_debe, tot_haber, pdf_libro = _libro_mayor(demo, conn, fi_f, ff_f)
    saldo = tot_debe - tot_haber
    detalle_rows, detalle_total, pdf_detalle = _trabajos_detalle(
        demo, conn, nombre or "temp", fi_f, ff_f
    )

    from erp_maquinaria import TIPOS_MAQUINARIA_TRACTOR, TIPOS_MAQUINARIA_APLICACION

    return {
        "maq_ops": MAQ_OPS,
        "maq_op_activa": op,
        "libro_rows": libro_rows,
        "libro_n": len(libro_rows),
        "libro_tot_debe": demo.f_peso(tot_debe),
        "libro_tot_haber": demo.f_peso(tot_haber),
        "libro_saldo": demo.f_peso(saldo),
        "pdf_maquinaria_url": pdf_libro,
        "trabajos_rows": detalle_rows,
        "trabajos_n": len(detalle_rows),
        "trabajos_total": demo.f_peso(detalle_total),
        "pdf_trabajos_url": pdf_detalle,
        "filtro_q": (request.args.get("q") or "").strip(),
        "filtro_desde": fi_f.isoformat(),
        "filtro_hasta": ff_f.isoformat(),
        "tractores": _select_maquinaria(conn, TIPOS_MAQUINARIA_TRACTOR),
        "implementos": _select_maquinaria(conn, TIPOS_MAQUINARIA_APLICACION),
        "fecha_def": (hoy if fi <= hoy <= ff else (ff if hoy > ff else fi)).isoformat(),
    }


def post_registrar(demo, conn, fi, ff) -> dict:
    from erp_maquinaria import etiqueta_maquinaria

    if demo.es_solo_lectura():
        return {"ok": False, "msg": "Modo solo lectura: no puede registrar trabajos."}

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
        return {"ok": False, "msg": "Datos numéricos inválidos."}

    if not tr_cod:
        return {"ok": False, "msg": "Seleccione el tractor."}
    if not trabajo:
        return {"ok": False, "msg": "Indique el detalle del trabajo."}
    if not (fi <= fecha <= ff):
        return {
            "ok": False,
            "msg": f"La fecha debe estar dentro de la temporada ({fi.strftime('%d-%m-%Y')} al {ff.strftime('%d-%m-%Y')}).",
        }

    tr_row = conn.execute(
        "SELECT nombre FROM maestra_maquinaria WHERE UPPER(TRIM(codigo))=?",
        (tr_cod.upper(),),
    ).fetchone()
    if not tr_row:
        return {"ok": False, "msg": "Tractor no encontrado en maestra."}
    tr_lbl = etiqueta_maquinaria(tr_cod, tr_row[0])

    imp_lbl = ""
    if imp_cod:
        imp_row = conn.execute(
            "SELECT nombre FROM maestra_maquinaria WHERE UPPER(TRIM(codigo))=?",
            (imp_cod.upper(),),
        ).fetchone()
        if not imp_row:
            return {"ok": False, "msg": "Implemento no encontrado en maestra."}
        imp_lbl = etiqueta_maquinaria(imp_cod, imp_row[0])

    ha_eff = _hectareas_efectivas(hectareas)
    monto = (monto_tr + monto_imp) * ha_eff
    if monto <= 0:
        return {"ok": False, "msg": "Indique valores $/ha de tractor y/o implemento."}

    if sin_doc:
        doc = _folio_trabajo(conn, fecha)
    else:
        doc = (request.form.get("documento") or "").strip()
        if not doc:
            return {"ok": False, "msg": "Ingrese N° documento o marque folio interno."}

    combo = _combo_maquinaria(tr_lbl, imp_lbl)
    conn.execute(
        f"""INSERT INTO {TABLA}
            (fecha, documento, maquinaria_codigo, maquinaria, trabajo, horas, monto,
             tractor_codigo, tractor, implemento_codigo, implemento,
             monto_tractor, monto_implemento, hectareas)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            str(fecha),
            doc,
            tr_cod,
            combo,
            trabajo,
            horas_f,
            monto,
            tr_cod,
            tr_lbl,
            imp_cod,
            imp_lbl,
            monto_tr,
            monto_imp,
            hectareas if hectareas > 0 else None,
        ),
    )
    conn.commit()
    demo.registrar_accion(ETIQUETA, f"Trabajo maquinaria {doc} — {trabajo}")
    return {"ok": True, "msg": f"Trabajo registrado ({demo.f_peso(monto)}). Imputado al Debe.", "extra": {"op": "gastos"}}


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
