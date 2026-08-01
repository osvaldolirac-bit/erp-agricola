from __future__ import annotations

import csv
import sqlite3
from datetime import timedelta
from pathlib import Path

import pandas as pd
from flask import flash, render_template, request, url_for

from demo_web.services.demo_loader import bind_user_session, get_demo_module
from demo_web.services.module_runner import redirect_module, store_pdf
from demo_web.services.native._helpers import hoy_demo, df_to_records, parse_date

MERCADOS_PPPL = ["General", "UE", "USA", "China", "Nacional"]
DOC_TIPOS = ["Manual BPA", "Mapa fundo", "Política integrada", "Análisis agua", "Procedimiento", "Otro"]
CAP_TEMAS = ["Fitosanitarios", "SST / Seguridad", "Higiene cosecha", "Primeros auxilios", "Otro"]
EVAL_ESTADOS = ["Cumple", "No cumple", "N/A", "Pendiente"]

SECCIONES = [
    ("pppl", "📋 PPPL"),
    ("documentos", "📁 Documentos"),
    ("autoeval", "✅ Autoevaluación"),
    ("nc", "⚠️ NC / AC"),
    ("capacitaciones", "🎓 Capacitaciones"),
    ("planilla", "📋 Planilla aplicaciones"),
    ("cosecha", "🍒 Cosecha / Lotes"),
    ("agua", "💧 Agua"),
    ("calibracion", "🔧 Calibración"),
    ("planificacion", "📅 Planificación"),
]

_LC_PLANILLA_COLS = [
    ("variedad", "TEXT DEFAULT ''"),
    ("n_aplicacion_txt", "TEXT DEFAULT ''"),
    ("t_max", "REAL"),
    ("t_min", "REAL"),
    ("hr_pct", "REAL"),
    ("viento_kmh", "REAL"),
]

_UNIDADES_DOSIS_PLANILLA = [
    "Gramos (g)",
    "Centímetros Cúbicos (cc)",
    "Kilogramos (kg)",
    "Litros (L)",
]

_ESTADO_PPPL_CSS = {
    "AUTORIZADO": "success",
    "PENDIENTE": "warning",
    "DESINCronizado": "warning",
    "SIN_REFERENCIA": "danger",
    "NO_REQUIERE": "secondary",
}

_CHECKLIST_CSS = {
    "Cumple": "success",
    "No cumple": "danger",
    "Pendiente": "warning",
    "N/A": "secondary",
}


def _especie_sel(demo) -> str:
    esp = request.form.get("especie") or request.args.get("especie", "ESPECIE 1")
    if esp not in demo.GAP_ESPECIES:
        esp = demo.GAP_ESPECIES[0]
    return esp


def _redirect_gap(sec: str, especie: str, **extra) -> redirect_module:
    return redirect_module("globalgap", sec=sec, especie=especie, **extra)


def _pdf_url(demo, df, titulo: str, archivo: str, estilo_fn=None) -> str | None:
    if df is None or df.empty:
        return None
    show = df.copy()
    if "id" in show.columns:
        show = show.drop(columns=["id"])
    blob = demo.generar_pdf_blob(show, titulo, incluir_precios=False, estilo_celda_fn=estilo_fn)
    if not blob:
        return None
    token = store_pdf(blob, archivo)
    return url_for("modules.pdf_download", token=token)


def _pppl_bodega_rows(demo, conn) -> tuple[list[dict], dict]:
    df_aud = demo._auditar_bodega_pppl(conn)
    if df_aud.empty:
        return [], {}
    fito = df_aud[df_aud["ESTADO_COD"] != "NO_REQUIERE"]
    kpis = {
        "fitos": len(fito),
        "autorizados": len(fito[fito["ESTADO_COD"] == "AUTORIZADO"]),
        "pendientes": len(fito[fito["ESTADO_COD"] == "PENDIENTE"]),
    }
    rows = []
    for _, r in df_aud[df_aud["ESTADO_COD"] != "NO_REQUIERE"].iterrows():
        estado = r.get("ESTADO_COD", "")
        rows.append(
            {
                "producto": r.get("PRODUCTO", ""),
                "familia": r.get("FAMILIA", ""),
                "estado": r.get("ESTADO", ""),
                "estado_css": _ESTADO_PPPL_CSS.get(estado, "secondary"),
                "pppl": r.get("PPPL_BODEGA", ""),
                "phi": r.get("PHI_BODEGA", ""),
                "ingrediente": r.get("INGREDIENTE_SAG", ""),
            }
        )
    return rows, kpis


def _section_pppl(demo, conn, especie: str) -> dict:
    df = pd.read_sql_query(
        """SELECT id, producto AS PRODUCTO, ingrediente_activo AS [ING. ACTIVO],
                  dias_carencia AS PHI, mercado AS MERCADO,
                  COALESCE(especie,'General') AS ESPECIE, vigente AS VIGENTE
           FROM gap_pppl
           WHERE COALESCE(especie,'General') IN (?, ?)
           ORDER BY producto""",
        conn,
        params=(demo.GAP_ESPECIE_GENERAL, especie),
    )
    cols, rows = df_to_records(df, set(), demo)
    pref = "esp1" if especie == "ESPECIE 1" else "especie2"
    pdf = _pdf_url(
        demo,
        df,
        f"GLOBALGAP — {especie.upper()} — PPPL",
        f"globalgap_{pref}_pppl.pdf",
        demo._pdf_estilo_gap_vigente,
    )
    bod_rows, bod_kpis = _pppl_bodega_rows(demo, conn)
    esp_opts = [demo.GAP_ESPECIE_GENERAL] + demo.GAP_ESPECIES
    esp_default = especie if especie in demo.GAP_ESPECIES else demo.GAP_ESPECIE_GENERAL
    return {
        "pppl_cols": cols,
        "pppl_rows": rows,
        "pdf_pppl_url": pdf,
        "pppl_bod_rows": bod_rows,
        "pppl_bod_kpis": bod_kpis,
        "puede_gestionar_pppl": demo.puede_gestionar_pppl(),
        "mercados_pppl": MERCADOS_PPPL,
        "pppl_especies": esp_opts,
        "pppl_esp_default": esp_default,
    }


def _section_documentos(demo, conn, especie: str) -> dict:
    df = pd.read_sql_query(
        """SELECT tipo AS TIPO, titulo AS TITULO, version AS VER, fecha_vigencia AS VIGENTE,
                  responsable AS RESPONSABLE, notas AS NOTAS
           FROM gap_documentos
           WHERE COALESCE(especie,'ESPECIE 1')=?
           ORDER BY fecha_registro DESC""",
        conn,
        params=(especie,),
    )
    cols, rows = df_to_records(df, set(), demo)
    pref = "esp1" if especie == "ESPECIE 1" else "especie2"
    pdf = _pdf_url(
        demo, df, f"GLOBALGAP — {especie.upper()} — Documentos", f"globalgap_{pref}_documentos.pdf",
    )
    return {
        "doc_cols": cols,
        "doc_rows": rows,
        "pdf_doc_url": pdf,
        "doc_tipos": DOC_TIPOS,
        "hoy": hoy_demo(demo).isoformat(),
    }


def _section_autoeval(demo, conn, especie: str) -> dict:
    filtro_cap = request.args.get("capitulo", "TODOS")
    if filtro_cap not in ["TODOS"] + demo.GAP_CAPITULOS:
        filtro_cap = "TODOS"

    q = """SELECT c.codigo AS CODIGO, c.capitulo AS CAPÍTULO, c.descripcion AS DESCRIPCIÓN,
                  COALESCE(e.estado,'Pendiente') AS ESTADO, e.fecha_revision AS REVISIÓN, e.responsable AS RESPONSABLE
           FROM gap_checklist c
           LEFT JOIN gap_evaluacion e ON c.id=e.checklist_id AND COALESCE(e.especie,'ESPECIE 1')=?"""
    params: list = [especie]
    if filtro_cap != "TODOS":
        q += " WHERE c.capitulo=?"
        params.append(filtro_cap)
    q += " ORDER BY c.orden"
    df = pd.read_sql_query(q, conn, params=params)

    rows = []
    for _, r in df.iterrows():
        est = str(r.get("ESTADO", "Pendiente"))
        rows.append(
            {
                "codigo": r.get("CODIGO", ""),
                "capitulo": r.get("CAPÍTULO", ""),
                "descripcion": r.get("DESCRIPCIÓN", ""),
                "estado": est,
                "estado_css": _CHECKLIST_CSS.get(est, "secondary"),
                "revision": str(r.get("REVISIÓN", "") or "")[:10],
                "responsable": r.get("RESPONSABLE", "") or "",
            }
        )

    pref = "esp1" if especie == "ESPECIE 1" else "especie2"
    pdf = _pdf_url(
        demo,
        df,
        f"GLOBALGAP — {especie.upper()} — Autoevaluación IFA ({filtro_cap})",
        f"globalgap_{pref}_checklist.pdf",
        demo._pdf_estilo_gap_checklist,
    )
    checklist_opts = [{"codigo": r.get("CODIGO", ""), "descripcion": r.get("DESCRIPCIÓN", "")} for _, r in df.iterrows()]
    return {
        "checklist_rows": rows,
        "checklist_opts": checklist_opts,
        "eval_estados": EVAL_ESTADOS,
        "filtro_capitulo": filtro_cap,
        "capitulos": ["TODOS"] + demo.GAP_CAPITULOS,
        "pdf_checklist_url": pdf,
    }


def _section_nc(demo, conn, especie: str) -> dict:
    cuarteles = demo.cuarteles_gap_especie(especie)
    placeholders = ",".join("?" * len(cuarteles))
    df = pd.read_sql_query(
        f"""SELECT codigo AS CÓDIGO, capitulo AS CAPÍTULO, descripcion AS DESCRIPCIÓN,
                   accion_correctiva AS [ACCIÓN CORRECTIVA], plazo AS PLAZO, estado AS ESTADO, cuartel AS CUARTEL
            FROM gap_nc
            WHERE COALESCE(especie,'ESPECIE 1')=? OR cuartel IN ({placeholders})
            ORDER BY fecha_apertura DESC""",
        conn,
        params=(especie, *cuarteles),
    )
    cols, rows = df_to_records(df, set(), demo)
    pref = "esp1" if especie == "ESPECIE 1" else "especie2"
    pdf = _pdf_url(
        demo,
        df,
        f"GLOBALGAP — {especie.upper()} — No conformidades",
        f"globalgap_{pref}_nc.pdf",
        demo._pdf_estilo_gap_nc,
    )
    nc_abiertas = []
    if not df.empty and "ESTADO" in df.columns:
        for _, r in df[df["ESTADO"] == "Abierta"].iterrows():
            nc_abiertas.append({"codigo": r.get("CÓDIGO", ""), "descripcion": r.get("DESCRIPCIÓN", "")})
    return {
        "nc_cols": cols,
        "nc_rows": rows,
        "pdf_nc_url": pdf,
        "nc_capitulos": demo.GAP_CAPITULOS,
        "nc_cuarteles": [""] + cuarteles,
        "nc_abiertas": nc_abiertas,
        "hoy": hoy_demo(demo).isoformat(),
        "plazo_def": (hoy_demo(demo) + timedelta(days=30)).isoformat(),
    }


def _section_capacitaciones(demo, conn, especie: str) -> dict:
    hoy = hoy_demo(demo)
    df = pd.read_sql_query(
        """SELECT p.nombre AS TRABAJADOR, c.tema AS TEMA, c.horas AS HORAS, c.instructor AS INSTRUCTOR,
                  c.fecha AS FECHA, c.vigencia_hasta AS VIGENCIA, c.evidencia AS EVIDENCIA
           FROM gap_capacitaciones c
           JOIN personal p ON c.trabajador_id=p.id
           ORDER BY c.fecha DESC""",
        conn,
    )
    rows = []
    for _, r in df.iterrows():
        vig = str(r.get("VIGENCIA", ""))[:10]
        vencida = False
        try:
            vencida = pd.to_datetime(vig).date() < hoy if vig else False
        except Exception:
            pass
        rows.append(
            {
                "trabajador": r.get("TRABAJADOR", ""),
                "tema": r.get("TEMA", ""),
                "horas": r.get("HORAS", ""),
                "instructor": r.get("INSTRUCTOR", ""),
                "fecha": str(r.get("FECHA", ""))[:10],
                "vigencia": vig,
                "evidencia": r.get("EVIDENCIA", ""),
                "row_class": "table-warning" if vencida else "",
            }
        )
    pref = "esp1" if especie == "ESPECIE 1" else "especie2"
    pdf = _pdf_url(
        demo,
        df,
        f"GLOBALGAP — {especie.upper()} — Capacitaciones (Fundo)",
        f"globalgap_{pref}_capacitaciones.pdf",
        demo._pdf_estilo_cap_vencida,
    )
    pers = pd.read_sql_query(
        "SELECT id, nombre FROM personal WHERE estado='Activo' ORDER BY nombre", conn,
    )
    trabajadores = [{"id": int(r["id"]), "nombre": r["nombre"]} for _, r in pers.iterrows()]
    return {
        "cap_rows": rows,
        "pdf_cap_url": pdf,
        "cap_trabajadores": trabajadores,
        "cap_temas": CAP_TEMAS,
        "hoy": hoy_demo(demo).isoformat(),
    }


def _section_cosecha(demo, conn, especie: str) -> dict:
    df = pd.read_sql_query(
        """SELECT n_lote AS LOTE, cuartel AS CUARTEL, especie AS ESPECIE, fecha_cosecha AS FECHA,
                  kg AS KG, cuadrilla AS CUADRILLA, ultima_app_n AS [N° APP],
                  fecha_viable_cosecha AS [FECHA VIABLE], destino AS DESTINO
           FROM gap_cosecha
           WHERE UPPER(especie)=?
           ORDER BY fecha_cosecha DESC""",
        conn,
        params=(especie.upper(),),
    )
    cols, rows = df_to_records(df, set(), demo)
    pref = "esp1" if especie == "ESPECIE 1" else "especie2"
    pdf = _pdf_url(
        demo, df, f"GLOBALGAP — {especie.upper()} — Cosecha y lotes", f"globalgap_{pref}_cosecha.pdf",
    )
    cuarteles = demo.cuarteles_gap_especie(especie)
    cc_sel = request.args.get("cuartel") or (cuarteles[0] if cuarteles else "")
    if cc_sel not in cuarteles:
        cc_sel = cuarteles[0] if cuarteles else ""
    apps = []
    if cc_sel:
        df_apps = pd.read_sql_query(
            """SELECT n_aplicacion, fecha,
                      GROUP_CONCAT(producto, ' + ') AS productos,
                      MAX(fecha_viable) AS fecha_viable
               FROM libro_campo WHERE sector=?
               GROUP BY n_aplicacion, fecha
               ORDER BY fecha DESC LIMIT 20""",
            conn,
            params=(cc_sel.upper(),),
        )
        for _, r in df_apps.iterrows():
            apps.append(
                {
                    "n_app": int(r["n_aplicacion"]),
                    "label": f"{int(r['n_aplicacion'])} | {r['fecha']} | {r['productos']}",
                    "fecha_viable": str(r["fecha_viable"] or "")[:10],
                }
            )
    lote_def = f"LOT-{especie[:3].upper()}-{hoy_demo(demo).strftime('%Y%m%d')}"
    return {
        "cos_cols": cols,
        "cos_rows": rows,
        "pdf_cos_url": pdf,
        "cos_cuarteles": cuarteles,
        "cos_cuartel_sel": cc_sel,
        "cos_apps": apps,
        "cos_lote_def": lote_def,
        "hoy": hoy_demo(demo).isoformat(),
    }


def _section_agua(demo, conn, especie: str) -> dict:
    df = pd.read_sql_query(
        """SELECT punto_muestreo AS PUNTO, laboratorio AS LAB, fecha_muestra AS FECHA,
                  e_coli AS [E.COLI], coliformes AS COLIFORMES, ph AS PH, ce AS CE, conforme AS CONFORME
           FROM gap_agua ORDER BY fecha_muestra DESC""",
        conn,
    )
    show = df.copy()
    if not show.empty and "CONFORME" in show.columns:
        show["CONFORME"] = show["CONFORME"].apply(lambda v: "Sí" if v in (1, "1", True) else "No")
    cols, rows = df_to_records(show, set(), demo)
    pref = "esp1" if especie == "ESPECIE 1" else "especie2"
    pdf = _pdf_url(
        demo,
        show,
        f"GLOBALGAP — {especie.upper()} — Análisis de agua (Fundo)",
        f"globalgap_{pref}_agua.pdf",
        demo._pdf_estilo_gap_agua,
    )
    return {"agua_cols": cols, "agua_rows": rows, "pdf_agua_url": pdf, "hoy": hoy_demo(demo).isoformat()}


def _section_calibracion(demo, conn, especie: str) -> dict:
    df = pd.read_sql_query(
        """SELECT equipo AS EQUIPO, fecha AS FECHA, presion AS PRESION, l_ha_medido AS [L/HA],
                  desviacion_pct AS [% DESV], tecnico AS TECNICO, proxima_fecha AS [PROX. FECHA]
           FROM gap_calibracion ORDER BY fecha DESC""",
        conn,
    )
    cols, rows = df_to_records(df, set(), demo)
    pref = "esp1" if especie == "ESPECIE 1" else "especie2"
    pdf = _pdf_url(
        demo,
        df,
        f"GLOBALGAP — {especie.upper()} — Calibración equipos (Fundo)",
        f"globalgap_{pref}_calibracion.pdf",
    )
    prox_def = (hoy_demo(demo) + timedelta(days=180)).isoformat()
    return {
        "cal_cols": cols,
        "cal_rows": rows,
        "pdf_cal_url": pdf,
        "hoy": hoy_demo(demo).isoformat(),
        "cal_prox_def": prox_def,
    }


def _gantt_form_ctx(demo, conn, especie: str, df) -> dict:
    proys = pd.read_sql_query(
        """SELECT id, nombre FROM gantt_proyectos
           WHERE estado='Activo' AND (COALESCE(especie,'ESPECIE 1')=? OR COALESCE(especie,'ESPECIE 1')=?)
           ORDER BY nombre""",
        conn,
        params=(especie, demo.GAP_ESPECIE_GENERAL),
    )
    proyectos = [{"id": int(r["id"]), "nombre": r["nombre"]} for _, r in proys.iterrows()]
    actividades = []
    if df is not None and not df.empty:
        for _, r in df.iterrows():
            actividades.append(
                {
                    "id": int(r["id"]),
                    "label": f"{r['actividad']} ({r['proyecto']})",
                    "avance": float(r["avance_pct"]),
                    "estado": r.get("estado", "En curso"),
                }
            )
    return {
        "gantt_proyectos": proyectos,
        "gantt_actividades": actividades,
        "gantt_estados": demo.GANTT_ESTADOS,
        "gantt_prioridades": demo.GANTT_PRIORIDADES,
        "hoy": hoy_demo(demo).isoformat(),
        "gantt_fin_def": (hoy_demo(demo) + timedelta(days=30)).isoformat(),
    }


def _section_planificacion(demo, conn, especie: str) -> dict:
    df = demo.cargar_tareas_gantt(conn, especie=especie)
    form_ctx = _gantt_form_ctx(demo, conn, especie, df)
    if df is None or df.empty:
        return {"gantt_rows": [], "gantt_kpis": {}, "pdf_gantt_url": None, **form_ctx}

    kpis = {
        "actividades": len(df),
        "en_ritmo": len(df[df["nivel_alerta"].isin(["En ritmo", "Completada"])]),
        "con_desfase": len(df[df["desfase_pct"] > 0]),
        "alertas": len(df[df["indice_alerta"] >= 50]),
        "avance_prom": round(float(df["avance_pct"].mean()), 1),
    }
    show = df[
        ["proyecto", "actividad", "fecha_inicio", "fecha_fin", "avance_pct", "avance_esperado", "desfase_pct", "nivel_alerta", "responsable"]
    ].copy()
    show.columns = ["PROYECTO", "ACTIVIDAD", "INICIO", "FIN", "% REAL", "% ESPERADO", "DESFASE", "ALERTA", "RESPONSABLE"]
    rows = []
    for _, r in show.iterrows():
        alerta = str(r.get("ALERTA", ""))
        css = "table-success" if alerta in ("En ritmo", "Completada") else (
            "table-danger" if alerta in ("Crítico", "Vencida") else (
                "table-warning" if alerta in ("Alto", "Medio") else ""
            )
        )
        rows.append({**{c: str(r[c]) for c in show.columns}, "row_class": css})

    pref = "esp1" if especie == "ESPECIE 1" else "especie2"
    pdf = _pdf_url(
        demo,
        show,
        f"GLOBALGAP — {especie.upper()} — Carta Gantt",
        f"globalgap_{pref}_gantt.pdf",
        demo._pdf_estilo_gantt_alerta,
    )
    return {"gantt_rows": rows, "gantt_kpis": kpis, "pdf_gantt_url": pdf, **form_ctx}


def _post_pppl_add(demo, conn) -> dict:
    nom = (request.form.get("producto") or "").strip()
    if not nom:
        return {"ok": False, "msg": "Ingrese el nombre del producto."}
    try:
        dias = int(request.form.get("dias_carencia") or 0)
    except ValueError:
        return {"ok": False, "msg": "PHI inválido."}
    try:
        conn.execute(
            "INSERT INTO gap_pppl (producto, ingrediente_activo, dias_carencia, mercado, notas, especie) VALUES (?,?,?,?,?,?)",
            (
                nom,
                (request.form.get("ingrediente") or "").strip(),
                dias,
                request.form.get("mercado") or "General",
                (request.form.get("notas") or "").strip(),
                request.form.get("pppl_especie") or demo.GAP_ESPECIE_GENERAL,
            ),
        )
        conn.commit()
        demo.registrar_accion("GLOBALGAP PPPL", nom)
        return {"ok": True, "msg": "Producto agregado a PPPL."}
    except sqlite3.IntegrityError:
        return {"ok": False, "msg": "El producto ya existe en PPPL."}


def _post_pppl_sync(demo, conn, incluir_baja: bool = False) -> dict:
    if not demo.puede_gestionar_pppl():
        return {"ok": False, "msg": "Sin permiso para gestionar PPPL."}
    especie = request.form.get("especie") or demo.GAP_ESPECIES[0]
    df_aud = demo._auditar_bodega_pppl(conn)
    ok, omit, err = demo._sincronizar_pppl_bodega(conn, df_aud, incluir_baja=incluir_baja, especie=especie)
    if ok:
        return {"ok": True, "msg": f"PPPL sincronizado para {len(ok)} producto(s)."}
    if err:
        return {"ok": False, "msg": "; ".join(err[:3])}
    return {"ok": True, "msg": "No hay productos pendientes para sincronizar."}


def _post_doc_add(demo, conn, especie: str) -> dict:
    tit = (request.form.get("titulo") or "").strip()
    if not tit:
        return {"ok": False, "msg": "Ingrese el título del documento."}
    conn.execute(
        "INSERT INTO gap_documentos (tipo, titulo, version, fecha_vigencia, responsable, notas, fecha_registro, especie) VALUES (?,?,?,?,?,?,?,?)",
        (
            request.form.get("tipo") or DOC_TIPOS[0],
            tit,
            request.form.get("version") or "1.0",
            request.form.get("fecha_vigencia") or str(hoy_demo(demo)),
            (request.form.get("responsable") or "").strip(),
            (request.form.get("notas") or "").strip(),
            str(hoy_demo(demo)),
            especie,
        ),
    )
    conn.commit()
    demo.registrar_accion("GLOBALGAP DOC", tit)
    return {"ok": True, "msg": "Documento registrado."}


def _post_eval_save(demo, conn, especie: str, user_email: str) -> dict:
    cod = (request.form.get("codigo") or "").strip()
    if not cod:
        return {"ok": False, "msg": "Seleccione un ítem del checklist."}
    row = conn.execute("SELECT id FROM gap_checklist WHERE codigo=?", (cod,)).fetchone()
    if not row:
        return {"ok": False, "msg": "Ítem no encontrado."}
    chk_id = row[0]
    conn.execute(
        "DELETE FROM gap_evaluacion WHERE checklist_id=? AND COALESCE(especie,'ESPECIE 1')=?",
        (chk_id, especie),
    )
    conn.execute(
        "INSERT INTO gap_evaluacion (checklist_id, estado, evidencia, responsable, fecha_revision, usuario, especie) VALUES (?,?,?,?,?,?,?)",
        (
            chk_id,
            request.form.get("estado") or "Pendiente",
            (request.form.get("evidencia") or "").strip(),
            (request.form.get("responsable") or "").strip(),
            str(hoy_demo(demo)),
            user_email,
            especie,
        ),
    )
    conn.commit()
    return {"ok": True, "msg": "Evaluación guardada."}


def _post_nc_open(demo, conn, especie: str) -> dict:
    desc = (request.form.get("descripcion") or "").strip()
    if not desc:
        return {"ok": False, "msg": "Ingrese la descripción del hallazgo."}
    n = conn.execute("SELECT COUNT(*) FROM gap_nc").fetchone()[0] + 1
    cod = f"NC-{n:04d}"
    conn.execute(
        "INSERT INTO gap_nc (codigo, capitulo, descripcion, causa, accion_correctiva, plazo, cuartel, fecha_apertura, especie) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            cod,
            request.form.get("capitulo") or demo.GAP_CAPITULOS[0],
            desc,
            (request.form.get("causa") or "").strip(),
            (request.form.get("accion_correctiva") or "").strip(),
            request.form.get("plazo") or str(hoy_demo(demo)),
            request.form.get("cuartel") or "",
            str(hoy_demo(demo)),
            especie,
        ),
    )
    conn.commit()
    demo.registrar_accion("GLOBALGAP NC", cod)
    return {"ok": True, "msg": f"No conformidad {cod} registrada."}


def _post_nc_close(demo, conn) -> dict:
    cod = (request.form.get("codigo") or "").strip()
    if not cod:
        return {"ok": False, "msg": "Seleccione una NC abierta."}
    conn.execute(
        "UPDATE gap_nc SET estado='Cerrada', fecha_cierre=? WHERE codigo=?",
        (str(hoy_demo(demo)), cod),
    )
    conn.commit()
    return {"ok": True, "msg": f"{cod} cerrada."}


def _post_cap_add(demo, conn) -> dict:
    try:
        tid = int(request.form.get("trabajador_id") or 0)
        horas = float(request.form.get("horas") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Datos inválidos."}
    if not tid:
        return {"ok": False, "msg": "Seleccione un trabajador."}
    f_cap = parse_date(request.form.get("fecha"), hoy_demo(demo))
    vig = f_cap + timedelta(days=365)
    conn.execute(
        "INSERT INTO gap_capacitaciones (trabajador_id, tema, horas, instructor, fecha, vigencia_hasta, evidencia) VALUES (?,?,?,?,?,?,?)",
        (
            tid,
            request.form.get("tema") or CAP_TEMAS[0],
            horas,
            (request.form.get("instructor") or "").strip(),
            str(f_cap),
            str(vig),
            (request.form.get("evidencia") or "").strip(),
        ),
    )
    conn.commit()
    demo.registrar_accion("GLOBALGAP CAP", request.form.get("tema") or "")
    return {"ok": True, "msg": "Capacitación registrada."}


def _post_cosecha_add(demo, conn, especie: str) -> dict:
    n_lote = (request.form.get("n_lote") or "").strip()
    cc = (request.form.get("cuartel") or "").upper()
    if not n_lote or not cc:
        return {"ok": False, "msg": "Lote y cuartel son obligatorios."}
    try:
        kg = float(request.form.get("kg") or 0)
    except ValueError:
        kg = 0.0
    f_cos = parse_date(request.form.get("fecha_cosecha"), hoy_demo(demo))
    ua_raw = request.form.get("ultima_app") or ""
    ua_n = None
    fv = None
    if ua_raw and ua_raw != "—":
        try:
            ua_n = int(ua_raw.split("|")[0].strip())
        except ValueError:
            ua_n = int(ua_raw) if ua_raw.isdigit() else None
        if ua_n:
            fv_row = conn.execute(
                "SELECT MAX(fecha_viable) FROM libro_campo WHERE n_aplicacion=? AND sector=?",
                (ua_n, cc),
            ).fetchone()
            if fv_row and fv_row[0]:
                fv = str(fv_row[0])[:10]
    if fv:
        fv_date = parse_date(fv, f_cos)
        if f_cos < fv_date:
            return {"ok": False, "msg": f"No se puede registrar: cosecha antes de fecha viable PHI ({fv})."}
    conn.execute(
        "INSERT INTO gap_cosecha (n_lote, cuartel, especie, variedad, fecha_cosecha, kg, cuadrilla, ultima_app_n, fecha_viable_cosecha, destino) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            n_lote,
            cc,
            especie.strip(),
            (request.form.get("variedad") or "").strip(),
            str(f_cos),
            kg,
            (request.form.get("cuadrilla") or "").strip(),
            ua_n,
            fv,
            (request.form.get("destino") or "").strip(),
        ),
    )
    conn.commit()
    demo.registrar_accion("GLOBALGAP COSECHA", n_lote)
    return {"ok": True, "msg": "Lote de cosecha registrado."}


def _post_agua_add(demo, conn) -> dict:
    punto = (request.form.get("punto") or "").strip()
    if not punto:
        return {"ok": False, "msg": "Ingrese el punto de muestreo."}
    try:
        ph = float(request.form.get("ph") or 7)
        ce = float(request.form.get("ce") or 0)
    except ValueError:
        return {"ok": False, "msg": "pH o CE inválido."}
    conn.execute(
        "INSERT INTO gap_agua (punto_muestreo, laboratorio, fecha_muestra, e_coli, coliformes, ph, ce, conforme, accion) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            punto,
            (request.form.get("laboratorio") or "").strip(),
            request.form.get("fecha_muestra") or str(hoy_demo(demo)),
            request.form.get("e_coli") or "",
            request.form.get("coliformes") or "",
            ph,
            ce,
            1 if request.form.get("conforme") == "1" else 0,
            (request.form.get("accion") or "").strip(),
        ),
    )
    conn.commit()
    demo.registrar_accion("GLOBALGAP AGUA", punto)
    return {"ok": True, "msg": "Análisis de agua registrado."}


def _post_cal_add(demo, conn) -> dict:
    eq = (request.form.get("equipo") or "").strip()
    if not eq:
        return {"ok": False, "msg": "Ingrese el equipo / nebulizador."}
    try:
        pres = float(request.form.get("presion") or 0)
        lha = float(request.form.get("l_ha") or 0)
        desv = float(request.form.get("desviacion") or 0)
    except ValueError:
        return {"ok": False, "msg": "Valores numéricos inválidos."}
    conn.execute(
        "INSERT INTO gap_calibracion (equipo, fecha, presion, l_ha_medido, desviacion_pct, tecnico, proxima_fecha, notas) VALUES (?,?,?,?,?,?,?,?)",
        (
            eq.upper(),
            request.form.get("fecha") or str(hoy_demo(demo)),
            pres,
            lha,
            desv,
            (request.form.get("tecnico") or "").strip(),
            request.form.get("proxima_fecha") or str(hoy_demo(demo)),
            (request.form.get("notas") or "").strip(),
        ),
    )
    conn.commit()
    demo.registrar_accion("GLOBALGAP CAL", eq)
    return {"ok": True, "msg": "Calibración registrada."}


def _post_gantt_actividad(demo, conn) -> dict:
    act = (request.form.get("actividad") or "").strip()
    try:
        pid = int(request.form.get("proyecto_id") or 0)
        av = float(request.form.get("avance") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Datos inválidos."}
    fi = parse_date(request.form.get("fecha_inicio"), hoy_demo(demo))
    ff = parse_date(request.form.get("fecha_fin"), hoy_demo(demo) + timedelta(days=30))
    if not act or not pid:
        return {"ok": False, "msg": "Complete actividad y proyecto."}
    if ff < fi:
        return {"ok": False, "msg": "La fecha fin debe ser posterior al inicio."}
    conn.execute(
        "INSERT INTO gantt_tareas (proyecto_id, actividad, fecha_inicio, fecha_fin, avance_pct, responsable, prioridad, notas) VALUES (?,?,?,?,?,?,?,?)",
        (
            pid,
            act,
            str(fi),
            str(ff),
            av,
            (request.form.get("responsable") or "").strip(),
            request.form.get("prioridad") or demo.GANTT_PRIORIDADES[1],
            (request.form.get("notas") or "").strip(),
        ),
    )
    conn.commit()
    demo.registrar_accion("GANTT", act)
    return {"ok": True, "msg": "Actividad Gantt registrada."}


def _post_gantt_avance(demo, conn) -> dict:
    try:
        tid = int(request.form.get("tarea_id") or 0)
        av = float(request.form.get("avance") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Datos inválidos."}
    if not tid:
        return {"ok": False, "msg": "Seleccione una actividad."}
    estado = request.form.get("estado") or "En curso"
    if estado not in demo.GANTT_ESTADOS:
        estado = "En curso"
    conn.execute(
        "UPDATE gantt_tareas SET avance_pct=?, estado=? WHERE id=?",
        (av, estado, tid),
    )
    conn.commit()
    return {"ok": True, "msg": "Avance actualizado."}



def _ensure_libro_campo_planilla(conn) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(libro_campo)").fetchall()}
    for name, decl in _LC_PLANILLA_COLS:
        if name not in cols:
            try:
                conn.execute(f"ALTER TABLE libro_campo ADD COLUMN {name} {decl}")
            except sqlite3.OperationalError:
                pass
    try:
        conn.commit()
    except Exception:
        pass


def _planilla_csv_paths() -> list[Path]:
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "static" / "globalgap" / "planilla_cerezos_corte1.csv",
        Path("/root/demo-web/demo_web/static/globalgap/planilla_cerezos_corte1.csv"),
        Path("/root/static/globalgap/planilla_cerezos_corte1.csv"),
    ]
    return [p for p in candidates if p.is_file()]


def _fmt_num(val, decimals=3):
    if val is None or val == "" or (isinstance(val, float) and pd.isna(val)):
        return ""
    try:
        f = float(val)
    except (TypeError, ValueError):
        return str(val)
    if abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    return f"{f:.{decimals}f}".rstrip("0").rstrip(".")


def _section_planilla(demo, conn, especie: str) -> dict:
    _ensure_libro_campo_planilla(conn)
    cuarteles = demo.cuarteles_gap_especie(especie)
    cc_sel = (request.args.get("cuartel") or "").strip().upper()
    if not cc_sel or cc_sel == "TODOS":
        cc_sel = "TODOS"
    elif cc_sel not in [c.upper() for c in cuarteles]:
        cc_sel = cuarteles[0].upper() if cuarteles else "TODOS"

    filtros = ["UPPER(TRIM(COALESCE(especie,''))) LIKE ?"]
    params: list = [f"%{(especie or '').upper()}%"]
    if cuarteles:
        placeholders = ",".join("?" for _ in cuarteles)
        filtros.append(f"UPPER(sector) IN ({placeholders})")
        params.extend(c.upper() for c in cuarteles)
    if cc_sel != "TODOS":
        filtros.append("UPPER(sector) = ?")
        params.append(cc_sel)

    where_sql = " AND ".join(filtros)
    df = pd.read_sql_query(
        f"""SELECT id, fecha, COALESCE(n_orden,'') AS n_orden, sector, especie,
                   COALESCE(variedad,'') AS variedad, COALESCE(motivo,'') AS motivo,
                   producto, COALESCE(n_aplicacion_txt, CAST(n_aplicacion AS TEXT)) AS n_app_txt,
                   n_aplicacion, COALESCE(ingrediente,'') AS ingrediente,
                   dosis, COALESCE(unidad_dosis,'') AS unidad_dosis,
                   vol_total, gasto_total, COALESCE(unidad_gasto,'') AS unidad_gasto,
                   COALESCE(tractor,'') AS tractor, COALESCE(maquina,'') AS maquina,
                   COALESCE(aplicadores,'') AS aplicadores,
                   COALESCE(car_etiqueta,0) AS car_etiqueta,
                   COALESCE(car_agenda,0) AS car_agenda,
                   COALESCE(car_mayor,0) AS car_mayor,
                   fecha_viable,
                   t_max, t_min, hr_pct, viento_kmh
            FROM libro_campo
            WHERE {where_sql}
            ORDER BY fecha ASC, CAST(COALESCE(n_orden,'0') AS INTEGER) ASC, id ASC""",
        conn,
        params=params,
    )

    show = pd.DataFrame()
    if not df.empty:
        show = pd.DataFrame({
            "FECHA": df["fecha"].astype(str).str[:10],
            "N° ORDEN": df["n_orden"].apply(lambda v: "" if v in (None, "") else str(v)),
            "CUARTEL": df["sector"],
            "ESPECIE": df["especie"],
            "VARIEDAD": df["variedad"],
            "MOTIVO": df["motivo"],
            "PRODUCTO": df["producto"],
            "N° APLICACIÓN": df["n_app_txt"],
            "ING. ACTIVO": df["ingrediente"],
            "DOSIS/100": df["dosis"].apply(lambda v: _fmt_num(v, 4)),
            "U.DOSIS": df["unidad_dosis"],
            "VOL AGUA": df["vol_total"].apply(lambda v: _fmt_num(v, 1)),
            "GASTO PROD": df["gasto_total"].apply(lambda v: _fmt_num(v, 4)),
            "U.GASTO": df["unidad_gasto"],
            "TRACTOR": df["tractor"],
            "MÁQUINA": df["maquina"],
            "APLICADOR": df["aplicadores"],
            "CAR.ETIQ": df["car_etiqueta"].apply(lambda v: _fmt_num(v, 0)),
            "CAR.AGENDA": df["car_agenda"].apply(lambda v: _fmt_num(v, 0)),
            "CAR.MAYOR": df["car_mayor"].apply(lambda v: _fmt_num(v, 0)),
            "FECHA VIABLE": df["fecha_viable"].astype(str).str[:10].replace({"None": "", "NaT": ""}),
            "T°MÁX": df["t_max"].apply(lambda v: _fmt_num(v, 1)),
            "T°MÍN": df["t_min"].apply(lambda v: _fmt_num(v, 1)),
            "HR%": df["hr_pct"].apply(lambda v: _fmt_num(v, 0)),
            "V km/h": df["viento_kmh"].apply(lambda v: _fmt_num(v, 1)),
        })

    cols, rows = df_to_records(show, set(), demo) if not show.empty else ([], [])
    pref = especie.lower().replace(" ", "_")[:12] or "gap"
    pdf = _pdf_url(
        demo,
        show,
        f"GLOBALGAP — {especie.upper()} — Planilla de aplicaciones",
        f"globalgap_{pref}_planilla.pdf",
    )
    csv_ok = bool(_planilla_csv_paths())
    import_disponible = csv_ok and any("CORTE 1" in c.upper() for c in cuarteles)

    return {
        "plan_cols": cols,
        "plan_rows": rows,
        "pdf_plan_url": pdf,
        "plan_cuarteles": ["TODOS"] + cuarteles,
        "plan_cuartel_sel": cc_sel if cc_sel != "TODOS" else "TODOS",
        "plan_stats": {
            "lineas": len(df),
            "ordenes": int(df["n_orden"].astype(str).nunique()) if not df.empty else 0,
            "productos": int(df["producto"].nunique()) if not df.empty else 0,
        },
        "plan_unidades": _UNIDADES_DOSIS_PLANILLA,
        "plan_import_disponible": import_disponible,
        "hoy": hoy_demo(demo).isoformat(),
        "lc_url": url_for("modules.libro_campo", sec="historial"),
    }


def _siguiente_n_aplicacion(conn) -> int:
    res = conn.execute("SELECT MAX(n_aplicacion) FROM libro_campo").fetchone()[0]
    return int(res) + 1 if res else 1


def _parse_float_form(name: str, default=0.0):
    raw = (request.form.get(name) or "").strip().replace(",", ".")
    if raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _parse_optional_float_form(name: str):
    raw = (request.form.get(name) or "").strip().replace(",", ".")
    if raw == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_int_form(name: str, default=0) -> int:
    try:
        return int(float((request.form.get(name) or str(default)).replace(",", ".")))
    except (TypeError, ValueError):
        return default


def _insert_planilla_row(conn, row: dict, n_app: int) -> None:
    fe = str(row["fecha"])[:10]
    car_e = int(row.get("car_etiqueta") or 0)
    car_a = int(row.get("car_agenda") or 0)
    car_m = int(row.get("car_mayor") or max(car_e, car_a))
    fv = str(row.get("fecha_viable") or "")[:10]
    if not fv:
        try:
            from datetime import date as _date
            base = _date.fromisoformat(fe)
            fv = (base + timedelta(days=car_m)).isoformat()
        except Exception:
            fv = fe
    conn.execute(
        """INSERT INTO libro_campo
           (fecha, n_orden, sector, especie, variedad, motivo, producto, n_aplicacion,
            n_aplicacion_txt, ingrediente, dosis, unidad_dosis, vol_total, gasto_total,
            unidad_gasto, tractor, maquina, aplicadores, car_etiqueta, car_agenda,
            car_mayor, fecha_viable, t_max, t_min, hr_pct, viento_kmh,
            lote_producto, operador_certificado)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            fe,
            str(row.get("n_orden") or ""),
            str(row.get("sector") or "").upper(),
            str(row.get("especie") or "").strip(),
            str(row.get("variedad") or "").strip(),
            str(row.get("motivo") or "").strip(),
            str(row.get("producto") or "").strip(),
            n_app,
            str(row.get("n_app_txt") or row.get("n_aplicacion_txt") or "").strip(),
            str(row.get("ingrediente") or "").strip(),
            float(row.get("dosis") or 0),
            str(row.get("unidad_dosis") or ""),
            float(row.get("vol_total") or 0),
            float(row.get("gasto_total") or 0),
            str(row.get("unidad_gasto") or ""),
            str(row.get("tractor") or "").strip(),
            str(row.get("maquina") or "").strip(),
            str(row.get("aplicadores") or "").strip(),
            car_e,
            car_a,
            car_m,
            fv,
            row.get("t_max") if row.get("t_max") not in ("", None) else None,
            row.get("t_min") if row.get("t_min") not in ("", None) else None,
            row.get("hr") if row.get("hr") not in ("", None) else (
                row.get("hr_pct") if row.get("hr_pct") not in ("", None) else None
            ),
            row.get("viento") if row.get("viento") not in ("", None) else (
                row.get("viento_kmh") if row.get("viento_kmh") not in ("", None) else None
            ),
            str(row.get("lote_producto") or ""),
            1 if row.get("operador_certificado") in (1, "1", True) else 0,
        ),
    )


def _post_planilla_add(demo, conn, especie: str) -> dict:
    _ensure_libro_campo_planilla(conn)
    producto = (request.form.get("producto") or "").strip()
    cuartel = (request.form.get("cuartel") or "").strip().upper()
    aplicador = (request.form.get("aplicador") or "").strip()
    maquina = (request.form.get("maquina") or "").strip()
    if not producto:
        return {"ok": False, "msg": "Ingrese el producto utilizado."}
    if not cuartel:
        return {"ok": False, "msg": "Seleccione el cuartel."}
    if not aplicador:
        return {"ok": False, "msg": "Ingrese el aplicador."}
    if not maquina:
        return {"ok": False, "msg": "Ingrese la máquina / pulverizadora."}

    fe = parse_date(request.form.get("fecha"), hoy_demo(demo))
    car_e = _parse_int_form("car_etiqueta")
    car_a = _parse_int_form("car_agenda")
    car_m = _parse_int_form("car_mayor", max(car_e, car_a))
    if request.form.get("car_mayor") in (None, ""):
        car_m = max(car_e, car_a)
    fv = parse_date(request.form.get("fecha_viable"), fe + timedelta(days=car_m))
    n_orden = (request.form.get("n_orden") or "").strip()
    if not n_orden:
        res = conn.execute(
            "SELECT MAX(CAST(n_orden AS INTEGER)) FROM libro_campo WHERE UPPER(sector)=? AND n_orden GLOB '[0-9]*'",
            (cuartel,),
        ).fetchone()[0]
        n_orden = str(int(res) + 1 if res is not None else 0)

    n_app = _siguiente_n_aplicacion(conn)
    row = {
        "fecha": fe.isoformat(),
        "n_orden": n_orden,
        "sector": cuartel,
        "especie": (request.form.get("especie_cultivo") or especie).strip(),
        "variedad": (request.form.get("variedad") or "").strip(),
        "motivo": (request.form.get("motivo") or "").strip(),
        "producto": producto,
        "n_app_txt": (request.form.get("n_app_txt") or "").strip() or "No aplica",
        "ingrediente": (request.form.get("ingrediente") or "").strip(),
        "dosis": _parse_float_form("dosis"),
        "unidad_dosis": request.form.get("unidad_dosis") or _UNIDADES_DOSIS_PLANILLA[0],
        "vol_total": _parse_float_form("vol_agua"),
        "gasto_total": _parse_float_form("gasto_total"),
        "unidad_gasto": (request.form.get("unidad_gasto") or "").strip(),
        "tractor": (request.form.get("tractor") or "").strip(),
        "maquina": maquina,
        "aplicadores": aplicador,
        "car_etiqueta": car_e,
        "car_agenda": car_a,
        "car_mayor": car_m,
        "fecha_viable": fv.isoformat(),
        "t_max": _parse_optional_float_form("t_max"),
        "t_min": _parse_optional_float_form("t_min"),
        "hr_pct": _parse_optional_float_form("hr_pct"),
        "viento_kmh": _parse_optional_float_form("viento_kmh"),
        "lote_producto": (request.form.get("lote") or "").strip(),
        "operador_certificado": request.form.get("op_cert") == "1",
    }
    _insert_planilla_row(conn, row, n_app)
    conn.commit()
    demo.registrar_accion("GLOBALGAP PLANILLA", f"App N°{n_app} {producto} · {cuartel}")
    return {
        "ok": True,
        "msg": f"Aplicación registrada en planilla y Libro de Campo (N° {n_app:05d}).",
        "extra": {"cuartel": cuartel},
    }


def _post_planilla_import(demo, conn, especie: str) -> dict:
    _ensure_libro_campo_planilla(conn)
    paths = _planilla_csv_paths()
    if not paths:
        return {"ok": False, "msg": "No se encontró el archivo de planilla para importar."}
    path = paths[0]
    inserted = 0
    skipped = 0
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            sector = (raw.get("sector") or "CEREZOS CORTE 1").strip().upper()
            producto = (raw.get("producto") or "").strip()
            fecha = (raw.get("fecha") or "").strip()[:10]
            if not producto or not fecha:
                skipped += 1
                continue
            try:
                dosis = float(raw.get("dosis") or 0)
                gasto = float(raw.get("gasto_total") or 0)
            except ValueError:
                dosis, gasto = 0.0, 0.0
            exists = conn.execute(
                """SELECT id FROM libro_campo
                   WHERE fecha=? AND UPPER(sector)=? AND UPPER(TRIM(producto))=UPPER(TRIM(?))
                   LIMIT 1""",
                (fecha, sector, producto),
            ).fetchone()
            if exists:
                skipped += 1
                continue
            n_app = _siguiente_n_aplicacion(conn)
            row = dict(raw)
            row["sector"] = sector
            row["producto"] = producto
            row["fecha"] = fecha
            row["especie"] = (raw.get("especie") or especie or "Cerezos").strip()
            try:
                row["dosis"] = dosis
                row["gasto_total"] = gasto
                row["vol_total"] = float(raw.get("vol_total") or 0)
            except ValueError:
                row["vol_total"] = 0
            for k in ("t_max", "t_min", "hr", "viento", "car_etiqueta", "car_agenda", "car_mayor"):
                v = (raw.get(k) or "").strip()
                if v == "":
                    row[k] = None if k.startswith(("t_", "hr", "viento")) else 0
                else:
                    try:
                        row[k] = float(v) if k.startswith(("t_", "hr", "viento")) else int(float(v))
                    except ValueError:
                        row[k] = None if k.startswith(("t_", "hr", "viento")) else 0
            _insert_planilla_row(conn, row, n_app)
            inserted += 1
    conn.commit()
    if inserted:
        demo.registrar_accion("GLOBALGAP PLANILLA IMPORT", f"{inserted} líneas desde {path.name}")
    return {
        "ok": True,
        "msg": f"Importación listada: {inserted} nuevas · {skipped} omitidas (ya existían o inválidas).",
        "extra": {"cuartel": "CEREZOS CORTE 1"},
    }


def gather_globalgap(user_email: str, user_rol: str) -> dict:
    demo = get_demo_module()
    bind_user_session(user_email, user_rol)
    especie = _especie_sel(demo)
    sec = request.args.get("sec", "pppl")
    if sec not in {k for k, _ in SECCIONES}:
        sec = "pppl"

    conn = demo.conectar_db()
    try:
        cuarteles = demo.cuarteles_gap_especie(especie)
        res = demo.resumen_globalgap(conn, especie)

        df_res = pd.DataFrame([
            {"Indicador": "Cumplimiento checklist", "Valor": f"{res['pct']}%"},
            {"Indicador": "Ítems cumpliendo", "Valor": f"{res['cumple']}/{res['total_chk']}"},
            {"Indicador": "NC abiertas", "Valor": res["nc_abiertas"]},
            {"Indicador": "Productos PPPL", "Valor": res["pppl"]},
            {"Indicador": "Alertas capacitación / agua", "Valor": res["cap_venc"] + res["agua_venc"]},
            {"Indicador": "Cuarteles", "Valor": ", ".join(cuarteles)},
            {"Indicador": "Fecha informe", "Valor": str(hoy_demo(demo))},
        ])
        pref = "esp1" if especie == "ESPECIE 1" else "especie2"
        pdf_resumen = _pdf_url(
            demo,
            df_res,
            f"GLOBALGAP — {especie.upper()} — Resumen certificación",
            f"globalgap_{pref}_resumen.pdf",
        )

        ctx: dict = {
            "secciones": SECCIONES,
            "sec_activa": sec,
            "especie_sel": especie,
            "especies": demo.GAP_ESPECIES,
            "cuarteles_esp": cuarteles,
            "kpis": res,
            "alertas": {
                "nc": res["nc_abiertas"] > 0,
                "cap": res["cap_venc"] > 0,
                "agua": res["agua_venc"] > 0,
            },
            "pdf_resumen_url": pdf_resumen,
        }

        loaders = {
            "pppl": _section_pppl,
            "documentos": _section_documentos,
            "autoeval": _section_autoeval,
            "nc": _section_nc,
            "capacitaciones": _section_capacitaciones,
            "planilla": _section_planilla,
            "cosecha": _section_cosecha,
            "agua": _section_agua,
            "calibracion": _section_calibracion,
            "planificacion": _section_planificacion,
        }
        ctx.update(loaders[sec](demo, conn, especie))
        return ctx
    finally:
        conn.close()


def view(user_email: str, user_rol: str):
    demo = get_demo_module()
    bind_user_session(user_email, user_rol)

    if request.method == "POST":
        action = request.form.get("action", "")
        sec = request.form.get("sec") or request.args.get("sec", "pppl")
        especie = _especie_sel(demo)
        conn = demo.conectar_db()
        try:
            handlers = {
                "pppl_add": _post_pppl_add,
                "pppl_sync_ok": lambda d, c: _post_pppl_sync(d, c, incluir_baja=False),
                "pppl_sync_all": lambda d, c: _post_pppl_sync(d, c, incluir_baja=True),
                "doc_add": lambda d, c: _post_doc_add(d, c, especie),
                "eval_save": lambda d, c: _post_eval_save(d, c, especie, user_email),
                "nc_open": lambda d, c: _post_nc_open(d, c, especie),
                "nc_close": _post_nc_close,
                "cap_add": _post_cap_add,
                "cosecha_add": lambda d, c: _post_cosecha_add(d, c, especie),
                "planilla_add": lambda d, c: _post_planilla_add(d, c, especie),
                "planilla_import": lambda d, c: _post_planilla_import(d, c, especie),
                "agua_add": _post_agua_add,
                "cal_add": _post_cal_add,
                "gantt_actividad": _post_gantt_actividad,
                "gantt_avance": _post_gantt_avance,
            }
            fn = handlers.get(action)
            if fn:
                result = fn(demo, conn)
                flash(result["msg"], "success" if result["ok"] else "danger")
                extra = {"sec": sec, "especie": especie}
                if sec == "autoeval" and request.form.get("capitulo"):
                    extra["capitulo"] = request.form.get("capitulo")
                if sec == "cosecha" and request.form.get("cuartel"):
                    extra["cuartel"] = request.form.get("cuartel")
                if sec == "planilla":
                    cu = (result.get("extra") or {}).get("cuartel") or request.form.get("cuartel")
                    if cu and cu != "TODOS":
                        extra["cuartel"] = cu
                return _redirect_gap(**extra)
        finally:
            conn.close()

    ctx = gather_globalgap(user_email, user_rol)
    return render_template(
        "modules/globalgap.html",
        page_title="GlobalGAP",
        active_key="GlobalGAP",
        title="🌿 GlobalGAP",
        **ctx,
    )
