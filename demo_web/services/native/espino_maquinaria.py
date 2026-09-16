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

    return {
        "maq_ops": MAQ_OPS,
        "maq_op_activa": op,
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
