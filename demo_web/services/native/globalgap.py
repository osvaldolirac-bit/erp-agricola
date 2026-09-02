from __future__ import annotations

import csv
import json
import mimetypes
import os
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from flask import abort, flash, jsonify, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from demo_web.services.demo_loader import bind_user_session, get_demo_module
from demo_web.services.module_runner import redirect_module, store_pdf
from demo_web.services.native._helpers import hoy_demo, df_to_records, parse_date

MERCADOS_PPPL = ["General", "UE", "USA", "China", "Nacional"]
DOC_TIPOS = [
    "Anexo",
    "Evaluaciones Riesgo",
    "Procedimientos",
    "Instructivos",
    "Plan Gestion",
    "Registro",
    "Política",
    "Manual BPA",
    "Mapa campo",
    "Política integrada",
    "Análisis agua",
    "Otro",
]
CAP_TEMAS = ["Fitosanitarios", "SST / Seguridad", "Higiene cosecha", "Primeros auxilios", "Otro"]
EVAL_ESTADOS = ["Cumple", "No cumple", "N/A", "Pendiente"]

_DOC_EXTRA_COLS = [
    ("codigo", "TEXT DEFAULT ''"),
    ("archivo_relpath", "TEXT DEFAULT ''"),
    ("nombre_archivo", "TEXT DEFAULT ''"),
    ("mime", "TEXT DEFAULT ''"),
    ("origen", "TEXT DEFAULT ''"),
    ("formato", "TEXT DEFAULT 'Digital'"),
]

_DOC_LINK_EXTRA_COLS = [
    ("cumple", "INTEGER DEFAULT 0"),
    ("cumple_por", "TEXT DEFAULT ''"),
    ("cumple_fecha", "TEXT DEFAULT ''"),
    ("cumple_usuario", "TEXT DEFAULT ''"),
]

_ESPECIE_DOC_SLUG = {
    "Cerezos": "cerezos",
    "Ciruelos": "ciruelos",
    "EL ESPINO": "espino",
    "ESPECIE 1": "cerezos",
    "ESPECIE 2": "ciruelos",
}

# Ancla de cosecha para Gantt GlobalGAP (Planificación).
_PLANIF_COSECHA = {
    "Cerezos": date(2026, 11, 1),
    "Ciruelos": date(2027, 1, 15),
    "ESPECIE 1": date(2026, 11, 1),
    "ESPECIE 2": date(2027, 1, 15),
}
_PLANIF_COSECHA_FIN = {
    "Cerezos": date(2026, 11, 22),
    "Ciruelos": date(2027, 2, 7),
    "ESPECIE 1": date(2026, 11, 22),
    "ESPECIE 2": date(2027, 2, 7),
}
_PLANIF_CUARTEL = {
    "Cerezos": "CEREZOS CORTE 1",
    "Ciruelos": "CIRUELOS",
    "EL ESPINO": "Cerezos",
    "ESPECIE 1": "CEREZOS CORTE 1",
    "ESPECIE 2": "CIRUELOS",
}
_PLANIF_PROYECTO_PREF = "GlobalGAP Certificación"

SECCIONES = [
    ("gantt", "📊 Gantt"),
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

# Cuarteles activos para la planilla GlobalGAP (ingreso + consulta).
PLANILLA_CUARTELES_ACTIVOS = ["CEREZOS CORTE 1", "CIRUELOS"]
PLANILLA_INGRESO_FILAS = 6

_PLANILLA_ESPECIE_POR_CUARTEL = {
    "CEREZOS CORTE 1": "Cerezos",
    "CIRUELOS": "Ciruelos",
}

_PLANILLA_SECTOR_LABEL = {
    "CEREZOS CORTE 1": "Cerezos Corte 1",
    "CIRUELOS": "Ciruelas",
}

_MAQ_OPTS = [
    ("tractor", "Tractor"),
    ("pulverizadora", "Pulverizadora"),
    ("nebulizadora", "Nebulizadora"),
    ("espalda", "Máquina espalda"),
]
_MET_OPTS = [
    ("pulverizacion", "Pulverización"),
    ("via_riego", "Vía riego"),
    ("nebulizacion", "Nebulización"),
    ("drenching", "Drenching"),
]
_EPP_OPTS = [
    ("traje", "Traje"),
    ("botas", "Botas"),
    ("guantes", "Guantes"),
    ("mascarilla", "Mascarilla y filtros"),
    ("antiparras", "Antiparras"),
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


def _check_master_gap(demo, clave: str) -> bool:
    return (clave or "").strip() == getattr(demo, "CLAVE_MAESTRA", "")


def _require_admin_gap(demo, clave: str | None = None) -> dict | None:
    if not demo.es_admin():
        return {"ok": False, "msg": "Requiere perfil administrador."}
    if clave is not None and not _check_master_gap(demo, clave):
        return {"ok": False, "msg": "Clave maestra incorrecta."}
    return None


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


def _ensure_gap_documentos_schema(conn) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS gap_documentos (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               tipo TEXT, titulo TEXT, version TEXT, fecha_vigencia DATE,
               responsable TEXT, notas TEXT, fecha_registro DATE, especie TEXT
           )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS gap_doc_checklist (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               documento_id INTEGER NOT NULL,
               checklist_codigo TEXT NOT NULL,
               especie TEXT,
               UNIQUE(documento_id, checklist_codigo, especie)
           )"""
    )
    cols = {r[1] for r in conn.execute("PRAGMA table_info(gap_documentos)").fetchall()}
    for name, decl in _DOC_EXTRA_COLS:
        if name not in cols:
            try:
                conn.execute(f"ALTER TABLE gap_documentos ADD COLUMN {name} {decl}")
            except sqlite3.OperationalError:
                pass
    link_cols = {r[1] for r in conn.execute("PRAGMA table_info(gap_doc_checklist)").fetchall()}
    for name, decl in _DOC_LINK_EXTRA_COLS:
        if name not in link_cols:
            try:
                conn.execute(f"ALTER TABLE gap_doc_checklist ADD COLUMN {name} {decl}")
            except sqlite3.OperationalError:
                pass
    try:
        conn.commit()
    except Exception:
        pass


def _docs_static_root() -> Path:
    return Path(__file__).resolve().parents[2] / "static" / "globalgap" / "docs"


def _consultor_ctx(demo):
    return getattr(demo, "_gap_consultor_ctx", None)


def _docs_especie_dir(especie: str) -> Path:
    try:
        from demo_web.services.demo_loader import get_demo_module

        ctx = _consultor_ctx(get_demo_module())
        if ctx and especie == ctx.especie_key and ctx.docs_root.is_dir():
            return ctx.docs_root
    except Exception:
        pass
    slug = _ESPECIE_DOC_SLUG.get((especie or "").strip(), "cerezos")
    env_root = (os.environ.get("ERP_GAP_DOCS") or "").strip()
    candidates = []
    if env_root:
        candidates.append(Path(env_root) / slug)
    candidates.extend(
        [
            _docs_static_root() / slug,
            Path(f"/root/demo-web/demo_web/static/globalgap/docs/{slug}"),
            Path(f"/root/erp_gap_docs/{slug}"),
        ]
    )
    for p in candidates:
        if p.is_dir():
            return p
    return candidates[0]


def _catalog_path(especie: str) -> Path | None:
    ctx = None
    try:
        from demo_web.services.demo_loader import get_demo_module

        ctx = _consultor_ctx(get_demo_module())
    except Exception:
        pass
    if ctx and especie == ctx.especie_key:
        for name in (
            f"catalogo_{ctx.plantilla}.json",
            "catalogo.json",
        ):
            p = ctx.docs_root / name
            if p.is_file():
                return p
    slug = _ESPECIE_DOC_SLUG.get((especie or "").strip(), "cerezos")
    for p in (
        _docs_static_root() / f"catalogo_{slug}.json",
        Path(f"/root/demo-web/demo_web/static/globalgap/docs/catalogo_{slug}.json"),
    ):
        if p.is_file():
            return p
    return None


def _doc_map_path(especie: str) -> Path | None:
    ctx = None
    try:
        from demo_web.services.demo_loader import get_demo_module

        ctx = _consultor_ctx(get_demo_module())
    except Exception:
        pass
    if ctx and especie == ctx.especie_key:
        for name in (
            f"doc_checklist_map_{ctx.plantilla}.json",
            "doc_checklist_map.json",
        ):
            p = ctx.docs_root / name
            if p.is_file():
                return p
    slug = _ESPECIE_DOC_SLUG.get((especie or "").strip(), "cerezos")
    for p in (
        _docs_static_root() / f"doc_checklist_map_{slug}.json",
        Path(f"/root/demo-web/demo_web/static/globalgap/docs/doc_checklist_map_{slug}.json"),
    ):
        if p.is_file():
            return p
    return None


def _load_doc_checklist_map(especie: str) -> dict[str, list[str]]:
    path = _doc_map_path(especie)
    if not path:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[str, list[str]] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, list):
                out[str(k)] = [str(x) for x in v]
    return out


def _safe_doc_file(especie: str, relpath: str) -> Path | None:
    rel = (relpath or "").replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        return None
    root = _docs_especie_dir(especie).resolve()
    full = (root / rel).resolve()
    try:
        full.relative_to(root)
    except ValueError:
        return None
    return full if full.is_file() else None


def _doc_download_url(doc_id: int, especie: str) -> str:
    return url_for(
        "modules.globalgap",
        download_doc=doc_id,
        especie=especie,
        sec="documentos",
    )


def _link_doc_checklist(conn, documento_id: int, codigo_doc: str, especie: str, extra_codes: list[str] | None = None) -> int:
    mapping = _load_doc_checklist_map(especie)
    codes = list(extra_codes or [])
    codes.extend(mapping.get(codigo_doc or "", []))
    # also accept comma-separated from form
    n = 0
    seen = set()
    for cod in codes:
        cod = (cod or "").strip()
        if not cod or cod in seen:
            continue
        seen.add(cod)
        try:
            conn.execute(
                """INSERT OR IGNORE INTO gap_doc_checklist (documento_id, checklist_codigo, especie)
                   VALUES (?,?,?)""",
                (documento_id, cod, especie),
            )
            n += 1
        except sqlite3.Error:
            pass
    return n


def _docs_linked_for_checklist(conn, especie: str) -> dict[str, list[dict]]:
    _ensure_gap_documentos_schema(conn)
    rows = conn.execute(
        """SELECT l.id, l.checklist_codigo, d.id, d.codigo, d.titulo, d.archivo_relpath,
                  d.nombre_archivo, COALESCE(l.cumple,0), COALESCE(l.cumple_por,''),
                  COALESCE(l.cumple_fecha,''), COALESCE(l.cumple_usuario,'')
           FROM gap_doc_checklist l
           JOIN gap_documentos d ON d.id = l.documento_id
           WHERE COALESCE(l.especie, d.especie, 'ESPECIE 1')=?
           ORDER BY d.codigo, d.titulo""",
        (especie,),
    ).fetchall()
    out: dict[str, list[dict]] = {}
    for r in rows:
        item = {
            "link_id": int(r[0]),
            "id": r[2],
            "codigo": r[3] or "",
            "titulo": r[4] or "",
            "tiene_archivo": bool(r[5]),
            "nombre_archivo": r[6] or "",
            "url": _doc_download_url(r[2], especie) if r[5] else "",
            "cumple": bool(int(r[7] or 0)),
            "cumple_por": r[8] or "",
            "cumple_fecha": str(r[9] or "")[:10],
            "cumple_usuario": r[10] or "",
        }
        out.setdefault(r[1], []).append(item)
    return out


def _sync_checklist_cumple_from_docs(conn, demo, especie: str, checklist_codigo: str, user_email: str, responsable: str) -> bool:
    """Si todos los docs asociados están en cumple, marca el ítem como Cumple. Retorna True si quedó Cumple."""
    rows = conn.execute(
        """SELECT COALESCE(cumple,0) FROM gap_doc_checklist
           WHERE checklist_codigo=? AND COALESCE(especie,'ESPECIE 1')=?""",
        (checklist_codigo, especie),
    ).fetchall()
    if not rows:
        return False
    if not all(int(r[0] or 0) == 1 for r in rows):
        return False
    chk = conn.execute("SELECT id FROM gap_checklist WHERE codigo=?", (checklist_codigo,)).fetchone()
    if not chk:
        return False
    chk_id = chk[0]
    evidencia = f"Documentos asociados marcados cumple ({len(rows)})"
    conn.execute(
        "DELETE FROM gap_evaluacion WHERE checklist_id=? AND COALESCE(especie,'ESPECIE 1')=?",
        (chk_id, especie),
    )
    conn.execute(
        """INSERT INTO gap_evaluacion
           (checklist_id, estado, evidencia, responsable, fecha_revision, usuario, especie)
           VALUES (?,?,?,?,?,?,?)""",
        (
            chk_id,
            "Cumple",
            evidencia,
            responsable or user_email,
            str(hoy_demo(demo)),
            user_email,
            especie,
        ),
    )
    return True


def _section_documentos(demo, conn, especie: str) -> dict:
    _ensure_gap_documentos_schema(conn)
    filtro_tipo = (request.args.get("tipo") or "TODOS").strip()
    q = """SELECT id, COALESCE(codigo,'') AS codigo, tipo, titulo, version, fecha_vigencia,
                  responsable, notas, COALESCE(archivo_relpath,'') AS archivo_relpath,
                  COALESCE(nombre_archivo,'') AS nombre_archivo, COALESCE(origen,'') AS origen,
                  COALESCE(formato,'Digital') AS formato
           FROM gap_documentos
           WHERE COALESCE(especie,'ESPECIE 1')=?"""
    params: list = [especie]
    if filtro_tipo and filtro_tipo != "TODOS":
        q += " AND tipo=?"
        params.append(filtro_tipo)
    q += " ORDER BY tipo, codigo, titulo"
    df = pd.read_sql_query(q, conn, params=params)

    # links by documento
    links_by_doc: dict[int, list[str]] = {}
    if not df.empty:
        ids = [int(x) for x in df["id"].tolist()]
        ph = ",".join("?" for _ in ids)
        for r in conn.execute(
            f"SELECT documento_id, checklist_codigo FROM gap_doc_checklist WHERE documento_id IN ({ph})",
            ids,
        ).fetchall():
            links_by_doc.setdefault(int(r[0]), []).append(r[1])

    rows = []
    con_archivo = 0
    for _, r in df.iterrows():
        did = int(r["id"])
        tiene = bool(str(r.get("archivo_relpath") or "").strip())
        if tiene:
            con_archivo += 1
        rows.append(
            {
                "id": did,
                "codigo": r.get("codigo") or "",
                "tipo": r.get("tipo") or "",
                "titulo": r.get("titulo") or "",
                "version": r.get("version") or "",
                "vigente": str(r.get("fecha_vigencia") or "")[:10],
                "responsable": r.get("responsable") or "",
                "origen": r.get("origen") or "",
                "formato": r.get("formato") or "",
                "notas": r.get("notas") or "",
                "archivo": r.get("nombre_archivo") or "",
                "tiene_archivo": tiene,
                "url": _doc_download_url(did, especie) if tiene else "",
                "checklist": ", ".join(links_by_doc.get(did, [])),
            }
        )

    pdf_df = df[["tipo", "codigo", "titulo", "version", "fecha_vigencia", "responsable"]].copy() if not df.empty else df
    if not pdf_df.empty:
        pdf_df.columns = ["TIPO", "CÓDIGO", "TÍTULO", "VER", "VIGENTE", "RESPONSABLE"]
    pref = "esp1" if especie in ("ESPECIE 1", "Cerezos") else "especie2"
    pdf = _pdf_url(
        demo, pdf_df, f"GLOBALGAP — {especie.upper()} — Documentos", f"globalgap_{pref}_documentos.pdf",
    )
    checklist_all = [
        {"codigo": r[0], "descripcion": r[1]}
        for r in conn.execute("SELECT codigo, descripcion FROM gap_checklist ORDER BY orden, id").fetchall()
    ]
    return {
        "doc_rows": rows,
        "pdf_doc_url": pdf,
        "doc_tipos": ["TODOS"] + DOC_TIPOS,
        "doc_tipo_sel": filtro_tipo if filtro_tipo in (["TODOS"] + DOC_TIPOS) else "TODOS",
        "doc_tipos_form": DOC_TIPOS,
        "doc_stats": {"total": len(rows), "con_archivo": con_archivo, "sin_archivo": len(rows) - con_archivo},
        "doc_import_disponible": bool(_catalog_path(especie)),
        "doc_checklist_opts": checklist_all,
        "hoy": hoy_demo(demo).isoformat(),
    }


def _section_autoeval(demo, conn, especie: str) -> dict:
    _ensure_gap_documentos_schema(conn)
    filtro_cap = request.args.get("capitulo", "TODOS")
    if filtro_cap not in ["TODOS"] + demo.GAP_CAPITULOS:
        filtro_cap = "TODOS"

    q = """SELECT c.id AS CID, c.codigo AS CODIGO, c.capitulo AS CAPÍTULO, c.descripcion AS DESCRIPCIÓN,
                  COALESCE(e.estado,'Pendiente') AS ESTADO, e.fecha_revision AS REVISIÓN,
                  e.responsable AS RESPONSABLE, COALESCE(e.evidencia,'') AS EVIDENCIA
           FROM gap_checklist c
           LEFT JOIN gap_evaluacion e ON c.id=e.checklist_id AND COALESCE(e.especie,'ESPECIE 1')=?"""
    params: list = [especie]
    if filtro_cap != "TODOS":
        q += " WHERE c.capitulo=?"
        params.append(filtro_cap)
    q += " ORDER BY c.orden"
    df = pd.read_sql_query(q, conn, params=params)
    linked = _docs_linked_for_checklist(conn, especie)

    rows = []
    for _, r in df.iterrows():
        est = str(r.get("ESTADO", "Pendiente"))
        cod = str(r.get("CODIGO", ""))
        docs = linked.get(cod, [])
        docs_ok = sum(1 for d in docs if d.get("cumple"))
        docs_total = len(docs)
        if docs_total and docs_ok == docs_total and est != "Cumple":
            # refleja en UI aunque falte sync previo
            est = "Cumple"
        rows.append(
            {
                "codigo": cod,
                "capitulo": r.get("CAPÍTULO", ""),
                "descripcion": r.get("DESCRIPCIÓN", ""),
                "estado": est,
                "estado_css": _CHECKLIST_CSS.get(est, "secondary"),
                "revision": str(r.get("REVISIÓN", "") or "")[:10],
                "responsable": r.get("RESPONSABLE", "") or "",
                "evidencia": r.get("EVIDENCIA", "") or "",
                "docs": docs,
                "docs_ok": docs_ok,
                "docs_total": docs_total,
                "docs_txt": ", ".join(
                    f"{d['codigo'] or d['titulo']}" for d in docs
                ),
            }
        )

    pref = "esp1" if especie in ("ESPECIE 1", "Cerezos") else "especie2"
    pdf = _pdf_url(
        demo,
        df[["CODIGO", "CAPÍTULO", "DESCRIPCIÓN", "ESTADO", "REVISIÓN", "RESPONSABLE"]] if not df.empty else df,
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
        f"GLOBALGAP — {especie.upper()} — Capacitaciones (Campo)",
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
        f"GLOBALGAP — {especie.upper()} — Análisis de agua (Campo)",
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
        f"GLOBALGAP — {especie.upper()} — Calibración equipos (Campo)",
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


def _cosecha_ancla(especie: str) -> date:
    return _PLANIF_COSECHA.get((especie or "").strip(), date(2026, 11, 1))


def _cosecha_fin(especie: str) -> date:
    return _PLANIF_COSECHA_FIN.get((especie or "").strip(), date(2026, 11, 22))


def _d(base: date, days: int) -> str:
    return (base + timedelta(days=days)).isoformat()


def _planif_proyecto_nombre(especie: str) -> str:
    h = _cosecha_ancla(especie)
    return f"{_PLANIF_PROYECTO_PREF} — {especie} (cosecha {h.strftime('%b %Y')})"


def _planif_tasks_certificacion(especie: str) -> list[dict]:
    """Gantt de certificación alineada a documentos + autoevaluación, anclada a cosecha."""
    h = _cosecha_ancla(especie)
    h_fin = _cosecha_fin(especie)
    cierre = h_fin + timedelta(days=14)
    cuartel = _PLANIF_CUARTEL.get(especie, "")
    return [
        {
            "actividad": "Documentos GlobalGAP cargados (Listado Maestro / Drive)",
            "inicio": _d(h, -120),
            "fin": _d(h, -100),
            "prioridad": "Alta",
            "responsable": "Certificación",
            "notas": "SYNC:DOCS_ARCHIVO",
        },
        {
            "actividad": "Evaluaciones de riesgo (GGAR) marcadas Cumple en autoevaluación",
            "inicio": _d(h, -110),
            "fin": _d(h, -75),
            "prioridad": "Alta",
            "responsable": "Certificación",
            "notas": "SYNC:DOCS_TIPO:Evaluaciones Riesgo",
        },
        {
            "actividad": "Procedimientos e instructivos (GGPR/GGIN) con Cumple",
            "inicio": _d(h, -100),
            "fin": _d(h, -65),
            "prioridad": "Alta",
            "responsable": "Jefe de Campo",
            "notas": "SYNC:DOCS_TIPO:Procedimientos|Instructivos",
        },
        {
            "actividad": "Planes de gestión (GGPL) vigentes y asociados",
            "inicio": _d(h, -95),
            "fin": _d(h, -55),
            "prioridad": "Alta",
            "responsable": "Certificación",
            "notas": "SYNC:DOCS_TIPO:Plan Gestion",
        },
        {
            "actividad": "Registros operativos (GGRG) y Anexos con Cumple",
            "inicio": _d(h, -90),
            "fin": _d(h, -40),
            "prioridad": "Media",
            "responsable": "Administración Campo",
            "notas": "SYNC:DOCS_TIPO:Registro|Anexo",
        },
        {
            "actividad": "Autoevaluación AFB (predio, personal, trazabilidad)",
            "inicio": _d(h, -85),
            "fin": _d(h, -50),
            "prioridad": "Alta",
            "responsable": "Certificación",
            "notas": "SYNC:CAP:AFB",
        },
        {
            "actividad": "Autoevaluación CB + planilla aplicaciones / PPPL",
            "inicio": _d(h, -75),
            "fin": _d(h, -35),
            "prioridad": "Alta",
            "responsable": "Jefe de Campo",
            "notas": "SYNC:CAP:CB",
        },
        {
            "actividad": "Autoevaluación AGUA + calibración equipos",
            "inicio": _d(h, -60),
            "fin": _d(h, -25),
            "prioridad": "Alta",
            "responsable": "Riego / Taller",
            "notas": "SYNC:CAP:AGUA",
        },
        {
            "actividad": "Autoevaluación FV (PHI, higiene y liberación a cosecha)",
            "inicio": _d(h, -45),
            "fin": _d(h, -10),
            "prioridad": "Alta",
            "responsable": "Supervisor Cosecha",
            "notas": "SYNC:CAP:FV",
        },
        {
            "actividad": "Autoevaluación AUDITORIA / NC / mejora continua",
            "inicio": _d(h, -40),
            "fin": _d(h, -15),
            "prioridad": "Alta",
            "responsable": "Certificación",
            "notas": "SYNC:CAP:AUDITORIA",
        },
        {
            "actividad": f"Preparación logística cosecha — {cuartel or especie}",
            "inicio": _d(h, -20),
            "fin": _d(h, -1),
            "prioridad": "Alta",
            "responsable": "Supervisor Cosecha",
            "notas": "Pre-cosecha",
        },
        {
            "actividad": f"Cosecha {especie} ({h.isoformat()} → {h_fin.isoformat()})",
            "inicio": h.isoformat(),
            "fin": h_fin.isoformat(),
            "prioridad": "Alta",
            "responsable": "Supervisor Cosecha",
            "notas": "COSECHA",
        },
        {
            "actividad": "Cierre post-cosecha: trazabilidad, balance de masas y evidencias",
            "inicio": h.isoformat(),
            "fin": cierre.isoformat(),
            "prioridad": "Media",
            "responsable": "Certificación",
            "notas": "SYNC:CAP:AFB|FV|AUDITORIA",
        },
    ]


def _avance_sync_from_notas(conn, especie: str, notas: str) -> float | None:
    """Calcula % avance desde autoevaluación/documentos según tag SYNC: en notas."""
    tag = (notas or "").strip()
    if not tag.startswith("SYNC:"):
        return None
    _ensure_gap_documentos_schema(conn)
    kind = tag[5:]

    def _pct(ok: int, total: int) -> float:
        if total <= 0:
            return 0.0
        return round(100.0 * ok / total, 1)

    if kind == "DOCS_ARCHIVO":
        row = conn.execute(
            """SELECT COUNT(*),
                      SUM(CASE WHEN COALESCE(archivo_relpath,'')!='' THEN 1 ELSE 0 END)
               FROM gap_documentos WHERE COALESCE(especie,'')=?""",
            (especie,),
        ).fetchone()
        return _pct(int(row[1] or 0), int(row[0] or 0))

    if kind.startswith("DOCS_TIPO:"):
        tipos = [t.strip() for t in kind.split(":", 1)[1].split("|") if t.strip()]
        if not tipos:
            return 0.0
        ph = ",".join("?" for _ in tipos)
        # docs de esos tipos vinculados a checklist de la especie
        row = conn.execute(
            f"""SELECT COUNT(*),
                       SUM(CASE WHEN COALESCE(l.cumple,0)=1 THEN 1 ELSE 0 END)
                FROM gap_doc_checklist l
                JOIN gap_documentos d ON d.id=l.documento_id
                WHERE COALESCE(l.especie,d.especie,'')=?
                  AND d.tipo IN ({ph})""",
            [especie, *tipos],
        ).fetchone()
        return _pct(int(row[1] or 0), int(row[0] or 0))

    if kind.startswith("CAP:"):
        caps = [c.strip() for c in kind.split(":", 1)[1].split("|") if c.strip()]
        if not caps:
            return 0.0
        ph = ",".join("?" for _ in caps)
        # avance = docs cumple / docs asociados de ítems del capítulo
        row = conn.execute(
            f"""SELECT COUNT(*),
                       SUM(CASE WHEN COALESCE(l.cumple,0)=1 THEN 1 ELSE 0 END)
                FROM gap_doc_checklist l
                JOIN gap_checklist c ON c.codigo=l.checklist_codigo
                WHERE COALESCE(l.especie,'ESPECIE 1')=?
                  AND c.capitulo IN ({ph})""",
            [especie, *caps],
        ).fetchone()
        total, ok = int(row[0] or 0), int(row[1] or 0)
        if total == 0:
            # fallback: ítems del capítulo evaluados como Cumple
            row2 = conn.execute(
                f"""SELECT COUNT(*),
                           SUM(CASE WHEN COALESCE(e.estado,'Pendiente')='Cumple' THEN 1 ELSE 0 END)
                    FROM gap_checklist c
                    LEFT JOIN gap_evaluacion e
                      ON e.checklist_id=c.id AND COALESCE(e.especie,'ESPECIE 1')=?
                    WHERE c.capitulo IN ({ph})""",
                [especie, *caps],
            ).fetchone()
            return _pct(int(row2[1] or 0), int(row2[0] or 0))
        return _pct(ok, total)

    return None


def _sync_gantt_avances(conn, especie: str) -> int:
    """Actualiza avance_pct/estado de tareas con tags SYNC: según documentos/autoeval."""
    rows = conn.execute(
        """SELECT t.id, t.notas, t.avance_pct, t.estado
           FROM gantt_tareas t
           JOIN gantt_proyectos p ON p.id=t.proyecto_id
           WHERE p.estado='Activo' AND COALESCE(p.especie,'')=?
             AND COALESCE(t.notas,'') LIKE 'SYNC:%'""",
        (especie,),
    ).fetchall()
    n = 0
    for tid, notas, avance, estado in rows:
        pct = _avance_sync_from_notas(conn, especie, notas or "")
        if pct is None:
            continue
        nuevo_estado = "Completada" if pct >= 100 else ("En curso" if pct > 0 else "Pendiente")
        if abs(float(avance or 0) - pct) > 0.05 or (estado or "") != nuevo_estado:
            conn.execute(
                "UPDATE gantt_tareas SET avance_pct=?, estado=? WHERE id=?",
                (pct, nuevo_estado, tid),
            )
            n += 1
    if n:
        conn.commit()
    return n


def _ensure_planificacion_certificacion(conn, demo, especie: str, force: bool = False) -> dict:
    """Crea/actualiza el proyecto Gantt de certificación para la especie (anclado a cosecha)."""
    if especie not in _PLANIF_COSECHA and especie not in ("Cerezos", "Ciruelos", "ESPECIE 1", "ESPECIE 2"):
        return {"ok": False, "msg": "Especie sin ancla de cosecha.", "proyecto_id": None}

    nombre = _planif_proyecto_nombre(especie)
    h = _cosecha_ancla(especie)
    h_fin = _cosecha_fin(especie)
    inicio = h - timedelta(days=120)
    cuartel = _PLANIF_CUARTEL.get(especie, "")
    desc = (
        f"Planificación GlobalGAP alineada a documentos y autoevaluación. "
        f"Cosecha {especie}: {h.isoformat()} a {h_fin.isoformat()}."
    )

    # Buscar por nombre exacto primero (UNIQUE), luego por especie+prefijo.
    # Evita IntegrityError si el proyecto quedó con especie "General" u otra.
    row = conn.execute(
        """SELECT id FROM gantt_proyectos
           WHERE nombre=?
              OR (COALESCE(especie,'')=? AND nombre LIKE ?)
              OR (nombre LIKE ? AND nombre LIKE ?)
           ORDER BY
             CASE
               WHEN nombre=? THEN 0
               WHEN COALESCE(especie,'')=? THEN 1
               ELSE 2
             END,
             id DESC
           LIMIT 1""",
        (
            nombre,
            especie,
            f"{_PLANIF_PROYECTO_PREF}%",
            f"{_PLANIF_PROYECTO_PREF}%",
            f"% {especie} %",
            nombre,
            especie,
        ),
    ).fetchone()
    if row:
        proyecto_id = int(row[0])
    else:
        try:
            cur = conn.execute(
                """INSERT INTO gantt_proyectos
                   (nombre, descripcion, fecha_inicio, fecha_fin, centro_costo, responsable, estado, especie)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    nombre,
                    desc,
                    inicio.isoformat(),
                    (h_fin + timedelta(days=14)).isoformat(),
                    cuartel or "OTROS",
                    "Certificación",
                    "Activo",
                    especie,
                ),
            )
            proyecto_id = int(cur.lastrowid)
        except Exception:
            row2 = conn.execute(
                "SELECT id FROM gantt_proyectos WHERE nombre=? LIMIT 1",
                (nombre,),
            ).fetchone()
            if not row2:
                raise
            proyecto_id = int(row2[0])

    conn.execute(
        """UPDATE gantt_proyectos
           SET nombre=?, descripcion=?, fecha_inicio=?, fecha_fin=?,
               centro_costo=?, responsable=?, estado='Activo', especie=?
           WHERE id=?""",
        (
            nombre,
            desc,
            inicio.isoformat(),
            (h_fin + timedelta(days=14)).isoformat(),
            cuartel or "OTROS",
            "Certificación",
            especie,
            proyecto_id,
        ),
    )

    # Desactivar proyectos viejos de temporada genérica de la misma especie (si no son el de certificación)
    conn.execute(
        """UPDATE gantt_proyectos SET estado='Inactivo'
           WHERE COALESCE(especie,'')=?
             AND id!=?
             AND (nombre LIKE 'Temporada %' OR nombre LIKE 'Certificación GlobalGAP%')""",
        (especie, proyecto_id),
    )

    existing = conn.execute(
        "SELECT COUNT(*) FROM gantt_tareas WHERE proyecto_id=?",
        (proyecto_id,),
    ).fetchone()[0]
    if force or int(existing or 0) == 0:
        conn.execute("DELETE FROM gantt_tareas WHERE proyecto_id=?", (proyecto_id,))
        for t in _planif_tasks_certificacion(especie):
            pct = _avance_sync_from_notas(conn, especie, t["notas"]) or 0.0
            estado = "Completada" if pct >= 100 else ("En curso" if pct > 0 else "Pendiente")
            conn.execute(
                """INSERT INTO gantt_tareas
                   (proyecto_id, actividad, fecha_inicio, fecha_fin, avance_pct,
                    responsable, prioridad, estado, notas)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    proyecto_id,
                    t["actividad"],
                    t["inicio"],
                    t["fin"],
                    pct,
                    t["responsable"],
                    t["prioridad"],
                    estado,
                    t["notas"],
                ),
            )
    else:
        _sync_gantt_avances(conn, especie)

    conn.commit()
    return {"ok": True, "msg": f"Gantt certificación lista para {especie}.", "proyecto_id": proyecto_id}


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



def _safe_count(conn, sql: str, params=()) -> int:
    try:
        row = conn.execute(sql, params).fetchone()
        return int(row[0] or 0) if row else 0
    except Exception:
        return 0


def _pct_pair(ok: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(100.0 * ok / total, 1)


def _parse_iso_date(val) -> date | None:
    if val is None:
        return None
    try:
        if isinstance(val, float) and pd.isna(val):
            return None
    except Exception:
        pass
    if isinstance(val, date) and not isinstance(val, pd.Timestamp):
        # date yes, datetime/Timestamp handled below
        if type(val) is date:
            return val
    try:
        return pd.to_datetime(val).date()
    except Exception:
        return None


def _timeline_span(especie: str) -> tuple[date, date, date]:
    """Inicio planificación → fin cosecha(+cierre)."""
    h = _cosecha_ancla(especie)
    h_fin = _cosecha_fin(especie)
    start = h - timedelta(days=120)
    end = h_fin + timedelta(days=14)
    return start, end, h


def _bar_pct(start: date, end: date, a: date | None, b: date | None) -> tuple[float, float]:
    """Posición left% y width% de [a,b] dentro de [start,end]."""
    total = max((end - start).days, 1)
    if a is None or b is None:
        return 0.0, 0.0
    if b < a:
        a, b = b, a
    left = max(0.0, min(100.0, 100.0 * (a - start).days / total))
    right = max(0.0, min(100.0, 100.0 * (b - start).days / total))
    width = max(1.2, right - left)
    if left + width > 100:
        width = max(1.2, 100.0 - left)
    return round(left, 2), round(width, 2)


def _gather_modulos_avance(demo, conn, especie: str) -> list[dict]:
    """% de avance por pestaña GlobalGAP (unificado para tablero Gantt)."""
    hoy = hoy_demo(demo)
    _ensure_gap_documentos_schema(conn)

    # Documentos: archivo cargado
    docs_total = _safe_count(
        conn, "SELECT COUNT(*) FROM gap_documentos WHERE COALESCE(especie,'')=?", (especie,)
    )
    docs_ok = _safe_count(
        conn,
        """SELECT COUNT(*) FROM gap_documentos
           WHERE COALESCE(especie,'')=? AND COALESCE(archivo_relpath,'')!=''""",
        (especie,),
    )
    docs_cumple_total = _safe_count(
        conn,
        """SELECT COUNT(*) FROM gap_doc_checklist
           WHERE COALESCE(especie,'')=?""",
        (especie,),
    )
    docs_cumple_ok = _safe_count(
        conn,
        """SELECT COUNT(*) FROM gap_doc_checklist
           WHERE COALESCE(especie,'')=? AND COALESCE(cumple,0)=1""",
        (especie,),
    )
    docs_pct = _pct_pair(docs_ok, docs_total)
    if docs_cumple_total:
        docs_pct = round((docs_pct + _pct_pair(docs_cumple_ok, docs_cumple_total)) / 2.0, 1)

    # Autoevaluación
    eval_total = _safe_count(conn, "SELECT COUNT(*) FROM gap_checklist")
    eval_ok = _safe_count(
        conn,
        """SELECT COUNT(*) FROM gap_evaluacion
           WHERE estado='Cumple' AND COALESCE(especie,'')=?""",
        (especie,),
    )
    eval_pct = _pct_pair(eval_ok, eval_total)

    # NC: % cerradas (si no hay NC → 100)
    nc_abiertas = _safe_count(
        conn,
        """SELECT COUNT(*) FROM gap_nc
           WHERE estado='Abierta' AND COALESCE(especie,'')=?""",
        (especie,),
    )
    nc_cerradas = _safe_count(
        conn,
        """SELECT COUNT(*) FROM gap_nc
           WHERE estado!='Abierta' AND COALESCE(especie,'')=?""",
        (especie,),
    )
    nc_total = nc_abiertas + nc_cerradas
    nc_pct = 100.0 if nc_total == 0 else _pct_pair(nc_cerradas, nc_total)

    # Capacitaciones vigentes
    cap_total = _safe_count(conn, "SELECT COUNT(*) FROM gap_capacitaciones")
    cap_ok = _safe_count(
        conn,
        "SELECT COUNT(*) FROM gap_capacitaciones WHERE vigencia_hasta >= ?",
        (hoy.isoformat(),),
    )
    cap_pct = 100.0 if cap_total == 0 else _pct_pair(cap_ok, cap_total)

    # Agua < 12 meses
    agua_total = _safe_count(conn, "SELECT COUNT(*) FROM gap_agua")
    limite = (hoy - timedelta(days=365)).isoformat()
    agua_ok = _safe_count(
        conn, "SELECT COUNT(*) FROM gap_agua WHERE fecha_muestra >= ?", (limite,)
    )
    agua_pct = 100.0 if agua_total == 0 else _pct_pair(agua_ok, agua_total)

    # Calibración con próxima fecha vigente
    cal_total = _safe_count(conn, "SELECT COUNT(*) FROM gap_calibracion")
    cal_ok = _safe_count(
        conn,
        "SELECT COUNT(*) FROM gap_calibracion WHERE proxima_fecha >= ?",
        (hoy.isoformat(),),
    )
    cal_pct = 100.0 if cal_total == 0 else _pct_pair(cal_ok, cal_total)

    # PPPL vigentes
    general = getattr(demo, "GAP_ESPECIE_GENERAL", "General")
    pppl_total = _safe_count(
        conn,
        """SELECT COUNT(*) FROM gap_pppl
           WHERE COALESCE(especie,'General') IN (?, ?)""",
        (general, especie),
    )
    pppl_ok = _safe_count(
        conn,
        """SELECT COUNT(*) FROM gap_pppl
           WHERE vigente=1 AND COALESCE(especie,'General') IN (?, ?)""",
        (general, especie),
    )
    pppl_pct = _pct_pair(pppl_ok, pppl_total) if pppl_total else 0.0

    # Planilla aplicaciones (libro_campo) de la especie / cuartel
    cuartel = _PLANIF_CUARTEL.get(especie, "")
    try:
        if cuartel:
            plan_total = _safe_count(
                conn,
                """SELECT COUNT(*) FROM libro_campo
                   WHERE UPPER(COALESCE(sector,''))=UPPER(?)
                      OR COALESCE(especie,'')=?""",
                (cuartel, especie),
            )
        else:
            plan_total = _safe_count(
                conn,
                "SELECT COUNT(*) FROM libro_campo WHERE COALESCE(especie,'')=?",
                (especie,),
            )
    except Exception:
        plan_total = 0
    # Meta blanda: al menos 1 registro cuenta como avance parcial; 5+ = 100%
    if plan_total <= 0:
        plan_pct = 0.0
    else:
        plan_pct = min(100.0, round(20.0 * plan_total, 1))

    # Cosecha / lotes
    cos_total = _safe_count(
        conn,
        "SELECT COUNT(*) FROM gap_cosecha WHERE COALESCE(especie,'')=?",
        (especie,),
    )
    cos_pct = min(100.0, round(25.0 * cos_total, 1)) if cos_total else 0.0

    def card(key, label, pct, ok, total, detail, tone=""):
        if pct >= 90:
            tone = tone or "ok"
        elif pct >= 55:
            tone = tone or "mid"
        else:
            tone = tone or "low"
        if key == "nc" and nc_abiertas:
            tone = "warn"
        return {
            "key": key,
            "label": label,
            "pct": pct,
            "ok": ok,
            "total": total,
            "detail": detail,
            "tone": tone,
            "url": url_for("modules.globalgap", sec=key, especie=especie),
        }

    return [
        card(
            "documentos",
            "Documentos",
            docs_pct,
            docs_ok,
            docs_total,
            f"{docs_ok}/{docs_total} con archivo"
            + (f" · {docs_cumple_ok}/{docs_cumple_total} cumple" if docs_cumple_total else ""),
        ),
        card("autoeval", "Autoevaluación", eval_pct, eval_ok, eval_total, f"{eval_ok}/{eval_total} ítems Cumple"),
        card(
            "nc",
            "NC / AC",
            nc_pct,
            nc_cerradas,
            nc_total,
            ("Sin NC" if nc_total == 0 else f"{nc_abiertas} abiertas · {nc_cerradas} cerradas"),
            "warn" if nc_abiertas else "",
        ),
        card("capacitaciones", "Capacitaciones", cap_pct, cap_ok, cap_total, f"{cap_ok}/{cap_total} vigentes"),
        card("agua", "Agua", agua_pct, agua_ok, agua_total, f"{agua_ok}/{agua_total} < 12 meses"),
        card("calibracion", "Calibración", cal_pct, cal_ok, cal_total, f"{cal_ok}/{cal_total} vigentes"),
        card("pppl", "PPPL", pppl_pct, pppl_ok, pppl_total, f"{pppl_ok}/{pppl_total} vigentes"),
        card("planilla", "Planilla apps", plan_pct, plan_total, max(plan_total, 5), f"{plan_total} registro(s)"),
        card("cosecha", "Cosecha / Lotes", cos_pct, cos_total, max(cos_total, 4), f"{cos_total} lote(s)"),
        card(
            "planificacion",
            "Planificación",
            0.0,
            0,
            0,
            "Ver Gantt operativo",
            "mid",
        ),
    ]



def _pdf_txt_safe(demo, val) -> str:
    fn = getattr(demo, "_pdf_txt", None)
    if callable(fn):
        try:
            return fn(val)
        except Exception:
            pass
    try:
        import unicodedata
        s = str(val).replace("—", "-").replace("–", "-").replace("−", "-")
        s = unicodedata.normalize("NFKD", s)
        s = "".join(ch for ch in s if not unicodedata.combining(ch))
        return s.encode("latin-1", "replace").decode("latin-1")
    except Exception:
        return str(val)[:80]


def _pdf_output_safe(demo, pdf) -> bytes | None:
    fn = getattr(demo, "_pdf_output_bytes", None)
    if callable(fn):
        try:
            return fn(pdf)
        except Exception:
            pass
    try:
        raw = pdf.output(dest="S")
        if isinstance(raw, (bytes, bytearray)):
            return bytes(raw)
        return raw.encode("latin-1")
    except Exception:
        return None


def _pdf_draw_hbar(pdf, x, y, w, h, pct, fill=(22, 58, 95), bg=(232, 238, 245)):
    pct = max(0.0, min(100.0, float(pct or 0)))
    pdf.set_fill_color(*bg)
    pdf.rect(x, y, w, h, "F")
    fw = max(0.4, w * pct / 100.0) if pct > 0 else 0
    if fw:
        pdf.set_fill_color(*fill)
        pdf.rect(x, y, fw, h, "F")
    pdf.set_draw_color(215, 224, 234)
    pdf.rect(x, y, w, h, "D")


def _pdf_tablero_gantt_bytes(demo, data: dict, especie: str) -> bytes | None:
    """PDF del tablero Gantt informativo en UNA sola página (landscape A4)."""
    try:
        from fpdf import FPDF
    except Exception:
        return None

    C_BRAND = (22, 58, 95)
    C_CYAN = (15, 143, 168)
    C_TEXT = (26, 43, 60)
    C_MUTED = (91, 107, 124)
    C_BG = (238, 242, 247)
    C_OK = (46, 125, 50)
    C_WARN = (239, 108, 0)
    C_BAD = (198, 40, 40)
    C_WHITE = (255, 255, 255)
    C_ROW = (245, 248, 252)

    def T(v):
        return _pdf_txt_safe(demo, v)

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()

    titulo = f"GLOBALGAP — {especie.upper()} — Tablero Gantt (cosecha)"
    if hasattr(demo, "encabezado_pdf"):
        try:
            demo.encabezado_pdf(pdf, titulo)
        except Exception:
            if hasattr(demo, "_pdf_encabezado_estilo_comercial"):
                demo._pdf_encabezado_estilo_comercial(pdf, titulo)
            else:
                pdf.set_font("Helvetica", "B", 11)
                pdf.cell(0, 7, T(titulo), ln=1)
    elif hasattr(demo, "_pdf_encabezado_estilo_comercial"):
        demo._pdf_encabezado_estilo_comercial(pdf, titulo)
    else:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, T(titulo), ln=1)

    left = 10.0
    content_w = pdf.w - 20.0
    bottom = pdf.h - 6.0

    # Meta en una sola línea compacta
    pdf.set_xy(left, pdf.get_y() - 1)
    pdf.set_font("Helvetica", "", 7.5)
    pdf.set_text_color(*C_MUTED)
    sub = (
        f"{data.get('gantt_proyecto') or ''} | "
        f"Cosecha: {data.get('gantt_cosecha_label') or ''} | "
        f"{data.get('gantt_fase_label') or ''} | Hoy {data.get('gantt_hoy_label') or ''}"
    )
    pdf.cell(content_w, 4, T(sub), ln=1)

    # KPI strip
    kpis = data.get("gantt_kpis") or {}
    dias = data.get("gantt_dias_cosecha", 0)
    if dias > 0:
        dias_txt = str(dias)
    elif dias == 0:
        dias_txt = "HOY"
    else:
        dias_txt = f"{abs(int(dias))} post"
    cards = [
        ("Dias a cosecha", dias_txt, C_WARN if isinstance(dias, int) and 0 <= dias < 30 else C_BRAND),
        ("Indice prep.", f"{data.get('gantt_indice', 0)}%", C_BRAND),
        ("Avance Gantt", f"{kpis.get('avance_prom', 0)}%", C_CYAN),
        ("Esp / gap", f"{kpis.get('esperado_prom', 0)}% / {data.get('gantt_gap_ritmo', 0)}%", C_WARN if float(data.get('gantt_gap_ritmo') or 0) > 10 else C_TEXT),
        ("Alertas / desfase", f"{kpis.get('alertas', 0)} / {kpis.get('con_desfase', 0)}", C_BAD if kpis.get("alertas") else C_OK),
        ("En ritmo", f"{kpis.get('en_ritmo', 0)}/{kpis.get('actividades', 0)}", C_OK),
    ]
    gap = 2.0
    card_w = (content_w - gap * 5) / 6
    card_h = 10.5
    y0 = pdf.get_y() + 0.5
    x = left
    for label, value, color in cards:
        pdf.set_fill_color(*C_BG)
        pdf.set_draw_color(215, 224, 234)
        pdf.rect(x, y0, card_w, card_h, "DF")
        pdf.set_xy(x + 1.5, y0 + 1.1)
        pdf.set_font("Helvetica", "", 5.8)
        pdf.set_text_color(*C_MUTED)
        pdf.cell(card_w - 3, 3, T(label), ln=0)
        pdf.set_xy(x + 1.5, y0 + 4.6)
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.set_text_color(*color)
        pdf.cell(card_w - 3, 4.5, T(value), ln=0)
        x += card_w + gap
    pdf.set_y(y0 + card_h + 2.2)

    # Timeline compacta
    tl = data.get("gantt_timeline") or {}
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*C_BRAND)
    pdf.set_x(left)
    pdf.cell(70, 3.8, T("Linea de tiempo hasta cosecha"), ln=0)
    pdf.set_font("Helvetica", "", 6.5)
    pdf.set_text_color(*C_MUTED)
    pdf.cell(
        content_w - 70,
        3.8,
        T(
            f"Inicio {tl.get('start_label', '')} · Calendario {data.get('gantt_calendario_pct', 0)}% · "
            f"Cierre {tl.get('end_label', '')} · Tope {data.get('gantt_cosecha_inicio', '')}"
        ),
        ln=1,
        align="R",
    )
    y = pdf.get_y() + 0.4
    track_h = 5.2
    pdf.set_fill_color(232, 238, 245)
    pdf.rect(left, y, content_w, track_h, "F")
    cos_left = float(tl.get("cosecha_left") or 0)
    cos_w = float(tl.get("cosecha_width") or 0)
    if cos_w > 0:
        pdf.set_fill_color(180, 230, 238)
        pdf.rect(left + content_w * cos_left / 100.0, y, max(2.0, content_w * cos_w / 100.0), track_h, "F")
    today_left = float(tl.get("today_left") or 0)
    tx = left + content_w * today_left / 100.0
    pdf.set_draw_color(198, 40, 40)
    pdf.set_line_width(0.5)
    pdf.line(tx, y - 0.6, tx, y + track_h + 0.6)
    pdf.set_line_width(0.2)
    pdf.set_y(y + track_h + 2.0)

    # Avance por pestaña — 5 columnas x 2 filas
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*C_BRAND)
    pdf.set_x(left)
    pdf.cell(
        content_w,
        3.8,
        T(f"Avance por pestana (promedio {data.get('gantt_modulos_pct', 0)}%)"),
        ln=1,
    )
    modulos = data.get("gantt_modulos") or []
    cols = 5
    col_gap = 2.0
    col_w = (content_w - col_gap * (cols - 1)) / cols
    row_h = 7.2
    tone_fill = {"ok": C_OK, "mid": C_CYAN, "low": C_WARN, "warn": C_BAD}
    y_start = pdf.get_y() + 0.3
    for idx, m in enumerate(modulos):
        col = idx % cols
        row = idx // cols
        x = left + col * (col_w + col_gap)
        y = y_start + row * (row_h + 1.2)
        pdf.set_fill_color(*C_WHITE)
        pdf.set_draw_color(215, 224, 234)
        pdf.rect(x, y, col_w, row_h, "DF")
        pdf.set_xy(x + 1.2, y + 0.7)
        pdf.set_font("Helvetica", "B", 6.2)
        pdf.set_text_color(*C_TEXT)
        pdf.cell(col_w * 0.62, 2.8, T(str(m.get("label", ""))[:18]), ln=0)
        pdf.set_font("Helvetica", "B", 6.5)
        pdf.set_text_color(*C_BRAND)
        pdf.cell(col_w * 0.32, 2.8, T(f"{m.get('pct', 0)}%"), align="R", ln=0)
        _pdf_draw_hbar(
            pdf,
            x + 1.2,
            y + 4.2,
            col_w - 2.4,
            2.0,
            m.get("pct", 0),
            fill=tone_fill.get(m.get("tone"), C_BRAND),
        )
    rows_n = (len(modulos) + cols - 1) // cols if modulos else 0
    pdf.set_y(y_start + rows_n * (row_h + 1.2) + 1.5)

    # Carta Gantt — altura de fila dinámica para caber en 1 página
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*C_BRAND)
    pdf.set_x(left)
    pdf.cell(content_w, 3.8, T("Carta Gantt informativa"), ln=1)

    headers = ["Actividad", "Origen", "Ini", "Fin", "%R", "%E", "Desf", "Alerta", "Barra"]
    widths = [86, 24, 14, 14, 12, 12, 14, 20, 40]
    scale = content_w / sum(widths)
    widths = [w * scale for w in widths]

    bars = data.get("gantt_bars") or []
    hdr_h = 4.8
    avail = max(20.0, bottom - pdf.get_y() - hdr_h - 1.0)
    n = max(len(bars), 1)
    rh = min(5.6, max(3.6, avail / n))

    def header_row():
        pdf.set_x(left)
        pdf.set_fill_color(*C_BRAND)
        pdf.set_text_color(*C_WHITE)
        pdf.set_font("Helvetica", "B", 6.2)
        for htxt, w in zip(headers, widths):
            pdf.cell(w, hdr_h, T(htxt), border=1, align="C", fill=True)
        pdf.ln()

    header_row()
    if not bars:
        pdf.set_x(left)
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(*C_MUTED)
        pdf.cell(content_w, 5, T("Sin actividades Gantt."), border=1, ln=1)
    else:
        # Si aun asi no caben, compactar un poco mas (nunca 2a pagina)
        if pdf.get_y() + n * rh > bottom:
            rh = max(3.4, (bottom - pdf.get_y()) / n)
        for i, b in enumerate(bars):
            row_y = pdf.get_y()
            if row_y + rh > bottom + 0.2:
                break  # seguridad: no crear pagina 2
            pdf.set_text_color(*C_TEXT)
            pdf.set_font("Helvetica", "", 5.8)
            act = (b.get("actividad") or "")
            max_chars = max(28, int(widths[0] / 1.45))
            vals = [
                act[:max_chars],
                (b.get("origen") or "")[:14],
                b.get("inicio_label") or "",
                b.get("fin_label") or "",
                f"{b.get('real', 0):g}",
                f"{b.get('esperado', 0):g}",
                f"{b.get('desfase', 0):g}",
                (b.get("alerta") or "")[:12],
            ]
            aligns = ["L", "L", "C", "C", "R", "R", "R", "C"]
            x = left
            bg = C_ROW if i % 2 else C_WHITE
            for val, w, al in zip(vals, widths[:-1], aligns):
                pdf.set_xy(x, row_y)
                pdf.set_fill_color(*bg)
                pdf.set_draw_color(215, 224, 234)
                pdf.cell(w, rh, T(val), border=1, align=al, fill=True)
                x += w
            pdf.set_xy(x, row_y)
            pdf.set_fill_color(*bg)
            pdf.cell(widths[-1], rh, "", border=1, fill=True)
            tone = b.get("tone") or "neutral"
            fill_c = {"ok": C_OK, "warn": C_WARN, "bad": C_BAD, "neutral": C_CYAN}.get(tone, C_BRAND)
            bar_h = max(1.6, rh - 2.0)
            _pdf_draw_hbar(pdf, x + 1.5, row_y + (rh - bar_h) / 2, widths[-1] - 3, bar_h, b.get("real", 0), fill=fill_c)
            pdf.set_y(row_y + rh)

    return _pdf_output_safe(demo, pdf)


def _section_gantt(demo, conn, especie: str) -> dict:
    """Tablero Gantt informativo: unifica avances y tiempos hasta cosecha."""
    _ensure_gap_documentos_schema(conn)
    _ensure_planificacion_certificacion(conn, demo, especie, force=False)
    _sync_gantt_avances(conn, especie)

    hoy = hoy_demo(demo)
    h = _cosecha_ancla(especie)
    h_fin = _cosecha_fin(especie)
    t0, t1, _ = _timeline_span(especie)
    dias_a_cosecha = (h - hoy).days
    dias_a_fin = (h_fin - hoy).days
    if hoy < h:
        fase = "pre-cosecha"
        fase_label = "En preparación (pre-cosecha)"
    elif hoy <= h_fin:
        fase = "cosecha"
        fase_label = "Ventana de cosecha activa"
    else:
        fase = "post-cosecha"
        fase_label = "Post-cosecha / cierre"

    # Progreso calendario hacia fecha tope (inicio cosecha)
    cal_total = max((h - t0).days, 1)
    cal_elapsed = max(0, min(cal_total, (hoy - t0).days))
    calendario_pct = round(100.0 * cal_elapsed / cal_total, 1)

    modulos = _gather_modulos_avance(demo, conn, especie)
    # planificacion % = promedio gantt
    df = demo.cargar_tareas_gantt(conn, especie=especie)
    gantt_avance = 0.0
    gantt_esperado = 0.0
    gantt_bars = []
    gantt_kpis = {
        "actividades": 0,
        "en_ritmo": 0,
        "con_desfase": 0,
        "alertas": 0,
        "avance_prom": 0.0,
        "esperado_prom": 0.0,
    }
    if df is not None and not df.empty:
        gantt_avance = round(float(df["avance_pct"].mean()), 1)
        gantt_esperado = round(float(df["avance_esperado"].mean()), 1)
        gantt_kpis = {
            "actividades": int(len(df)),
            "en_ritmo": int(len(df[df["nivel_alerta"].isin(["En ritmo", "Completada"])])),
            "con_desfase": int(len(df[df["desfase_pct"] > 0])),
            "alertas": int(len(df[df["indice_alerta"] >= 50])),
            "avance_prom": gantt_avance,
            "esperado_prom": gantt_esperado,
        }
        for _, r in df.iterrows():
            fi = _parse_iso_date(r.get("fecha_inicio"))
            ff = _parse_iso_date(r.get("fecha_fin"))
            left, width = _bar_pct(t0, t1, fi, ff)
            real = float(r.get("avance_pct") or 0)
            esp = float(r.get("avance_esperado") or 0)
            alerta = str(r.get("nivel_alerta") or "")
            if alerta in ("Completada", "En ritmo"):
                tone = "ok"
            elif alerta in ("Crítico", "Vencida", "Alto"):
                tone = "bad"
            elif alerta in ("Medio",):
                tone = "warn"
            else:
                tone = "neutral"
            notas = str(r.get("notas") or "")
            gantt_bars.append(
                {
                    "actividad": str(r.get("actividad") or ""),
                    "responsable": str(r.get("responsable") or ""),
                    "inicio": fi.isoformat() if fi else "",
                    "fin": ff.isoformat() if ff else "",
                    "inicio_label": fi.strftime("%d-%m") if fi else "—",
                    "fin_label": ff.strftime("%d-%m") if ff else "—",
                    "left": left,
                    "width": width,
                    "real": round(real, 1),
                    "esperado": round(esp, 1),
                    "desfase": round(float(r.get("desfase_pct") or 0), 1),
                    "alerta": alerta,
                    "tone": tone,
                    "origen": (
                        "Autoeval/Docs"
                        if notas.startswith("SYNC:")
                        else ("Cosecha" if notas == "COSECHA" else "Operativo")
                    ),
                }
            )

    for m in modulos:
        if m["key"] == "planificacion":
            m["pct"] = gantt_avance
            m["ok"] = gantt_kpis["en_ritmo"]
            m["total"] = gantt_kpis["actividades"]
            m["detail"] = f"Avance {gantt_avance}% · esperado {gantt_esperado}%"
            if gantt_avance >= 90:
                m["tone"] = "ok"
            elif gantt_avance >= 55:
                m["tone"] = "mid"
            else:
                m["tone"] = "low"

    modulos_pct = round(sum(m["pct"] for m in modulos) / max(len(modulos), 1), 1)
    # Índice de preparación a cosecha: mezcla avance módulos + ritmo gantt
    indice = round((modulos_pct * 0.55) + (gantt_avance * 0.45), 1)
    gap_ritmo = round(gantt_esperado - gantt_avance, 1)

    # Marcadores en timeline
    today_left, _ = _bar_pct(t0, t1, hoy, hoy)
    cos_left, cos_width = _bar_pct(t0, t1, h, h_fin)

    chart_modulos = {
        "labels": [m["label"] for m in modulos if m["key"] != "planificacion"],
        "values": [m["pct"] for m in modulos if m["key"] != "planificacion"],
    }
    chart_donut = {
        "real": gantt_avance,
        "resto": max(0.0, round(100.0 - gantt_avance, 1)),
        "esperado": gantt_esperado,
    }

    payload = {
        "gantt_tablero": True,
        "gantt_hoy": hoy.isoformat(),
        "gantt_hoy_label": hoy.strftime("%d-%m-%Y"),
        "gantt_cosecha_inicio": h.isoformat(),
        "gantt_cosecha_fin": h_fin.isoformat(),
        "gantt_cosecha_label": f"{h.strftime('%d-%m-%Y')} → {h_fin.strftime('%d-%m-%Y')}",
        "gantt_cuartel": _PLANIF_CUARTEL.get(especie, ""),
        "gantt_proyecto": _planif_proyecto_nombre(especie),
        "gantt_dias_cosecha": dias_a_cosecha,
        "gantt_dias_fin": dias_a_fin,
        "gantt_fase": fase,
        "gantt_fase_label": fase_label,
        "gantt_calendario_pct": calendario_pct,
        "gantt_indice": indice,
        "gantt_gap_ritmo": gap_ritmo,
        "gantt_modulos": modulos,
        "gantt_modulos_pct": modulos_pct,
        "gantt_bars": gantt_bars,
        "gantt_kpis": gantt_kpis,
        "gantt_timeline": {
            "start": t0.isoformat(),
            "end": t1.isoformat(),
            "start_label": t0.strftime("%d-%m-%Y"),
            "end_label": t1.strftime("%d-%m-%Y"),
            "today_left": today_left,
            "cosecha_left": cos_left,
            "cosecha_width": cos_width,
        },
        "gantt_chart_modulos": chart_modulos,
        "gantt_chart_donut": chart_donut,
        "gantt_planif_url": url_for("modules.globalgap", sec="planificacion", especie=especie),
    }
    pdf_tablero_url = None
    try:
        blob = _pdf_tablero_gantt_bytes(demo, payload, especie)
        if blob:
            pref = "esp1" if especie in ("ESPECIE 1", "Cerezos") else "especie2"
            pdf_tablero_url = url_for(
                "modules.pdf_download",
                token=store_pdf(blob, f"globalgap_{pref}_tablero_gantt.pdf"),
            )
    except Exception:
        pdf_tablero_url = None
    payload["pdf_gantt_tablero_url"] = pdf_tablero_url
    return payload



def _section_planificacion(demo, conn, especie: str) -> dict:
    _ensure_gap_documentos_schema(conn)
    _ensure_planificacion_certificacion(conn, demo, especie, force=False)
    _sync_gantt_avances(conn, especie)
    df = demo.cargar_tareas_gantt(conn, especie=especie)
    form_ctx = _gantt_form_ctx(demo, conn, especie, df)

    h = _cosecha_ancla(especie)
    h_fin = _cosecha_fin(especie)
    cosecha_ctx = {
        "planif_cosecha_inicio": h.isoformat(),
        "planif_cosecha_fin": h_fin.isoformat(),
        "planif_cosecha_label": f"{h.strftime('%d-%m-%Y')} → {h_fin.strftime('%d-%m-%Y')}",
        "planif_cuartel": _PLANIF_CUARTEL.get(especie, ""),
        "planif_proyecto": _planif_proyecto_nombre(especie),
        "planif_docs_url": url_for("modules.globalgap", sec="documentos", especie=especie),
        "planif_autoeval_url": url_for("modules.globalgap", sec="autoeval", especie=especie),
        "planif_planilla_url": url_for(
            "modules.globalgap",
            sec="planilla",
            especie=especie,
            cuartel=_PLANIF_CUARTEL.get(especie, ""),
        ),
    }

    if df is None or df.empty:
        return {
            "gantt_rows": [],
            "gantt_kpis": {},
            "pdf_gantt_url": None,
            **form_ctx,
            **cosecha_ctx,
        }

    kpis = {
        "actividades": len(df),
        "en_ritmo": len(df[df["nivel_alerta"].isin(["En ritmo", "Completada"])]),
        "con_desfase": len(df[df["desfase_pct"] > 0]),
        "alertas": len(df[df["indice_alerta"] >= 50]),
        "avance_prom": round(float(df["avance_pct"].mean()), 1),
    }
    show = df[
        ["proyecto", "actividad", "fecha_inicio", "fecha_fin", "avance_pct", "avance_esperado", "desfase_pct", "nivel_alerta", "responsable", "notas"]
    ].copy()
    show.columns = ["PROYECTO", "ACTIVIDAD", "INICIO", "FIN", "% REAL", "% ESPERADO", "DESFASE", "ALERTA", "RESPONSABLE", "NOTAS"]
    rows = []
    for _, r in show.iterrows():
        alerta = str(r.get("ALERTA", ""))
        css = "table-success" if alerta in ("En ritmo", "Completada") else (
            "table-danger" if alerta in ("Crítico", "Vencida") else (
                "table-warning" if alerta in ("Alto", "Medio") else ""
            )
        )
        notas = str(r.get("NOTAS", "") or "")
        sync = notas.startswith("SYNC:")
        rows.append(
            {
                **{c: str(r[c]) for c in show.columns if c != "NOTAS"},
                "row_class": css,
                "sync": sync,
                "origen": "Autoeval/Docs" if sync else ("Cosecha" if notas == "COSECHA" else "Operativo"),
            }
        )

    pref = "esp1" if especie in ("ESPECIE 1", "Cerezos") else "especie2"
    pdf_show = show.drop(columns=["NOTAS"], errors="ignore")
    pdf = _pdf_url(
        demo,
        pdf_show,
        f"GLOBALGAP — {especie.upper()} — Carta Gantt (cosecha {h.isoformat()})",
        f"globalgap_{pref}_gantt.pdf",
        demo._pdf_estilo_gantt_alerta,
    )
    return {
        "gantt_rows": rows,
        "gantt_kpis": kpis,
        "pdf_gantt_url": pdf,
        **form_ctx,
        **cosecha_ctx,
    }


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
    _ensure_gap_documentos_schema(conn)
    tit = (request.form.get("titulo") or "").strip()
    if not tit:
        return {"ok": False, "msg": "Ingrese el título del documento."}
    codigo = (request.form.get("codigo") or "").strip()
    tipo = request.form.get("tipo") or DOC_TIPOS[0]
    version = request.form.get("version") or "1.0"
    fecha_vig = request.form.get("fecha_vigencia") or str(hoy_demo(demo))
    responsable = (request.form.get("responsable") or "").strip()
    notas = (request.form.get("notas") or "").strip()
    checklist_raw = (request.form.get("checklist_codigos") or "").strip()
    extra_codes = [c.strip() for c in re.split(r"[,;\s]+", checklist_raw) if c.strip()]

    archivo_relpath = ""
    nombre_archivo = ""
    mime = ""
    f = request.files.get("archivo")
    if f and f.filename:
        safe = secure_filename(f.filename)
        if not safe:
            return {"ok": False, "msg": "Nombre de archivo inválido."}
        dest_dir = _docs_especie_dir(especie) / "uploads"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / safe
        f.save(dest)
        archivo_relpath = f"uploads/{safe}"
        nombre_archivo = safe
        mime = mimetypes.guess_type(safe)[0] or ""

    cur = conn.execute(
        """INSERT INTO gap_documentos
           (tipo, titulo, version, fecha_vigencia, responsable, notas, fecha_registro, especie,
            codigo, archivo_relpath, nombre_archivo, mime, origen, formato)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            tipo,
            tit,
            version,
            fecha_vig,
            responsable,
            notas,
            str(hoy_demo(demo)),
            especie,
            codigo,
            archivo_relpath,
            nombre_archivo,
            mime,
            "Propio",
            "Digital",
        ),
    )
    doc_id = int(cur.lastrowid)
    linked = _link_doc_checklist(conn, doc_id, codigo, especie, extra_codes)
    conn.commit()
    demo.registrar_accion("GLOBALGAP DOC", f"{codigo or tit}")
    msg = "Documento registrado."
    if archivo_relpath:
        msg += " Archivo guardado."
    if linked:
        msg += f" Asociado a {linked} ítem(s) de autoevaluación."
    return {"ok": True, "msg": msg}


def _post_doc_import_catalog(demo, conn, especie: str) -> dict:
    _ensure_gap_documentos_schema(conn)
    path = _catalog_path(especie)
    if not path:
        return {"ok": False, "msg": f"No hay catálogo de documentos para {especie}."}
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "msg": f"No se pudo leer el catálogo: {exc}"}
    if not isinstance(catalog, list):
        return {"ok": False, "msg": "Catálogo inválido."}

    inserted = 0
    updated = 0
    linked_total = 0
    for item in catalog:
        if not isinstance(item, dict):
            continue
        codigo = str(item.get("codigo") or "").strip()
        titulo = str(item.get("titulo") or "").strip()
        if not titulo and not codigo:
            continue
        tipo = str(item.get("tipo") or "Otro").strip() or "Otro"
        version = str(item.get("version") or "00").strip()
        fecha_vig = item.get("fecha_vigencia") or None
        origen = str(item.get("origen") or "Propio").strip()
        formato = str(item.get("formato") or "Digital").strip()
        rel = str(item.get("archivo_relpath") or "").replace("\\", "/").lstrip("/")
        nombre = str(item.get("nombre_archivo") or "").strip()
        if rel and not nombre:
            nombre = Path(rel).name
        mime = mimetypes.guess_type(nombre)[0] or "" if nombre else ""
        esp = str(item.get("especie") or especie).strip() or especie

        existing = None
        if codigo:
            existing = conn.execute(
                """SELECT id FROM gap_documentos
                   WHERE COALESCE(especie,'')=? AND COALESCE(codigo,'')=?
                   LIMIT 1""",
                (esp, codigo),
            ).fetchone()
        if not existing and titulo:
            existing = conn.execute(
                """SELECT id FROM gap_documentos
                   WHERE COALESCE(especie,'')=? AND UPPER(TRIM(titulo))=UPPER(TRIM(?))
                   LIMIT 1""",
                (esp, titulo),
            ).fetchone()

        if existing:
            doc_id = int(existing[0])
            conn.execute(
                """UPDATE gap_documentos SET
                       tipo=?, titulo=?, version=?,
                       fecha_vigencia=COALESCE(?, fecha_vigencia),
                       origen=?, formato=?,
                       archivo_relpath=CASE WHEN ?!='' THEN ? ELSE archivo_relpath END,
                       nombre_archivo=CASE WHEN ?!='' THEN ? ELSE nombre_archivo END,
                       mime=CASE WHEN ?!='' THEN ? ELSE mime END,
                       codigo=CASE WHEN ?!='' THEN ? ELSE codigo END
                   WHERE id=?""",
                (
                    tipo,
                    titulo or codigo,
                    version,
                    fecha_vig,
                    origen,
                    formato,
                    rel,
                    rel,
                    nombre,
                    nombre,
                    mime,
                    mime,
                    codigo,
                    codigo,
                    doc_id,
                ),
            )
            updated += 1
        else:
            cur = conn.execute(
                """INSERT INTO gap_documentos
                   (tipo, titulo, version, fecha_vigencia, responsable, notas, fecha_registro, especie,
                    codigo, archivo_relpath, nombre_archivo, mime, origen, formato)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    tipo,
                    titulo or codigo,
                    version,
                    fecha_vig,
                    "",
                    "Importado desde Listado Maestro / Drive",
                    str(hoy_demo(demo)),
                    esp,
                    codigo,
                    rel,
                    nombre,
                    mime,
                    origen,
                    formato,
                ),
            )
            doc_id = int(cur.lastrowid)
            inserted += 1
        linked_total += _link_doc_checklist(conn, doc_id, codigo, esp)

    conn.commit()
    demo.registrar_accion(
        "GLOBALGAP DOC IMPORT",
        f"{especie}: +{inserted} / ~{updated} / links {linked_total}",
    )
    return {
        "ok": True,
        "msg": (
            f"Catálogo {especie}: {inserted} nuevos, {updated} actualizados, "
            f"{linked_total} vínculos a autoevaluación."
        ),
    }


def _download_gap_documento(demo, conn, especie: str):
    _ensure_gap_documentos_schema(conn)
    try:
        doc_id = int(request.args.get("download_doc") or 0)
    except (TypeError, ValueError):
        abort(404)
    if doc_id <= 0:
        abort(404)
    row = conn.execute(
        """SELECT archivo_relpath, nombre_archivo, mime, COALESCE(especie,'')
           FROM gap_documentos WHERE id=?""",
        (doc_id,),
    ).fetchone()
    if not row or not row[0]:
        abort(404)
    esp = row[3] or especie
    path = _safe_doc_file(esp, row[0])
    if not path:
        # try current especie folder as fallback
        path = _safe_doc_file(especie, row[0])
    if not path:
        abort(404)
    download_name = row[1] or path.name
    mime = row[2] or mimetypes.guess_type(download_name)[0] or "application/octet-stream"
    return send_file(path, mimetype=mime, as_attachment=True, download_name=download_name)


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


def _post_doc_cumple(demo, conn, especie: str, user_email: str) -> dict:
    """Marca un documento asociado como Cumple (irreversible). Si todos cumplen, el ítem pasa a Cumple."""
    _ensure_gap_documentos_schema(conn)
    try:
        link_id = int(request.form.get("link_id") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Documento inválido."}
    if link_id <= 0:
        return {"ok": False, "msg": "Documento inválido."}

    row = conn.execute(
        """SELECT id, checklist_codigo, documento_id, COALESCE(cumple,0), COALESCE(especie,'')
           FROM gap_doc_checklist WHERE id=?""",
        (link_id,),
    ).fetchone()
    if not row:
        return {"ok": False, "msg": "Vínculo documento/checklist no encontrado."}
    if int(row[3] or 0) == 1:
        return {"ok": False, "msg": "Este documento ya está marcado como Cumple y no se puede desmarcar."}

    checklist_codigo = row[1]
    esp = (row[4] or especie or "").strip() or especie
    responsable = (request.form.get("responsable") or "").strip()
    if not responsable:
        # preferir nombre legible del correo
        responsable = (user_email or "").split("@")[0].replace(".", " ").strip() or user_email

    conn.execute(
        """UPDATE gap_doc_checklist
           SET cumple=1, cumple_por=?, cumple_fecha=?, cumple_usuario=?
           WHERE id=? AND COALESCE(cumple,0)=0""",
        (responsable, str(hoy_demo(demo)), user_email or "", link_id),
    )
    item_ok = _sync_checklist_cumple_from_docs(
        conn, demo, esp, checklist_codigo, user_email or "", responsable
    )
    conn.commit()

    doc = conn.execute(
        """SELECT COALESCE(d.codigo,''), COALESCE(d.titulo,'')
           FROM gap_doc_checklist l JOIN gap_documentos d ON d.id=l.documento_id
           WHERE l.id=?""",
        (link_id,),
    ).fetchone()
    doc_label = ((doc[0] if doc else "") or (doc[1] if doc else "") or f"#{link_id}").strip()
    demo.registrar_accion("GLOBALGAP DOC CUMPLE", f"{checklist_codigo} · {doc_label}")
    if item_ok:
        return {
            "ok": True,
            "msg": f"{doc_label}: Cumple registrado por {responsable}. Ítem {checklist_codigo} pasó a CUMPLE.",
        }
    # progreso
    tot = conn.execute(
        """SELECT COUNT(*), SUM(CASE WHEN COALESCE(cumple,0)=1 THEN 1 ELSE 0 END)
           FROM gap_doc_checklist WHERE checklist_codigo=? AND COALESCE(especie,'ESPECIE 1')=?""",
        (checklist_codigo, esp),
    ).fetchone()
    return {
        "ok": True,
        "msg": f"{doc_label}: Cumple registrado por {responsable}. Avance {int(tot[1] or 0)}/{int(tot[0] or 0)} en {checklist_codigo}.",
    }


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


def _post_gantt_rebuild(demo, conn, especie: str) -> dict:
    res = _ensure_planificacion_certificacion(conn, demo, especie, force=True)
    if res.get("ok"):
        n = conn.execute(
            "SELECT COUNT(*) FROM gantt_tareas WHERE proyecto_id=?",
            (res["proyecto_id"],),
        ).fetchone()[0]
        demo.registrar_accion("GLOBALGAP GANTT REBUILD", f"{especie}: {n} actividades")
        return {
            "ok": True,
            "msg": f"Gantt {especie} reconstruida ({n} actividades) anclada a cosecha {_cosecha_ancla(especie).isoformat()}.",
        }
    return {"ok": False, "msg": res.get("msg") or "No se pudo reconstruir la Gantt."}


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
    # % avance 0–100: Completada exige 100; 100% implica Completada.
    av = max(0.0, min(100.0, av))
    if estado == "Completada":
        av = 100.0
    elif av >= 100.0:
        estado = "Completada"
        av = 100.0
    conn.execute(
        "UPDATE gantt_tareas SET avance_pct=?, estado=? WHERE id=?",
        (av, estado, tid),
    )
    conn.commit()
    return {"ok": True, "msg": f"Avance actualizado: {av:.0f}% · {estado}."}



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


_PLANILLA_CSV_BY_CUARTEL = {
    "CEREZOS CORTE 1": "planilla_cerezos_corte1.csv",
    "CIRUELOS": "planilla_ciruelos.csv",
}


def _planilla_csv_paths(cuartel: str | None = None) -> list[Path]:
    here = Path(__file__).resolve()
    bases = [
        here.parents[2] / "static" / "globalgap",
        Path("/root/demo-web/demo_web/static/globalgap"),
        Path("/root/static/globalgap"),
    ]
    cu = (cuartel or "").strip().upper()
    filenames = (
        [_PLANILLA_CSV_BY_CUARTEL[cu]]
        if cu in _PLANILLA_CSV_BY_CUARTEL
        else list(_PLANILLA_CSV_BY_CUARTEL.values())
    )
    out: list[Path] = []
    seen: set[str] = set()
    for base in bases:
        for name in filenames:
            p = base / name
            key = str(p.resolve()) if p.is_file() else ""
            if p.is_file() and key not in seen:
                seen.add(key)
                out.append(p)
    return out


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


def _planilla_cuarteles_activos() -> list[str]:
    return list(PLANILLA_CUARTELES_ACTIVOS)


def _especie_desde_cuartel(cuartel: str, fallback: str = "Cerezos") -> str:
    return _PLANILLA_ESPECIE_POR_CUARTEL.get((cuartel or "").strip().upper(), fallback)


def _cuartel_default_planilla(especie: str) -> str:
    esp = (especie or "").strip().lower()
    if esp.startswith("ciruel"):
        return "CIRUELOS"
    if esp.startswith("cerez"):
        return "CEREZOS CORTE 1"
    return "TODOS"


def _section_planilla(demo, conn, especie: str) -> dict:
    _ensure_libro_campo_planilla(conn)
    _ensure_gap_orden_aplicacion(conn)
    cuarteles = _planilla_cuarteles_activos()
    cc_arg = (request.args.get("cuartel") or "").strip().upper()
    if not cc_arg:
        cc_sel = _cuartel_default_planilla(especie)
    elif cc_arg == "TODOS":
        cc_sel = "TODOS"
    elif cc_arg in [c.upper() for c in cuarteles]:
        cc_sel = cc_arg
    else:
        cc_sel = _cuartel_default_planilla(especie)

    filtros = []
    params: list = []
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
    plan_lineas = []
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
        for _, r in df.iterrows():
            plan_lineas.append(
                {
                    "id": int(r["id"]),
                    "n_app": int(r["n_aplicacion"] or 0),
                    "fecha": str(r["fecha"] or "")[:10],
                    "n_orden": "" if r["n_orden"] in (None, "") else str(r["n_orden"]),
                    "cuartel": r["sector"] or "",
                    "especie": r["especie"] or "",
                    "variedad": r["variedad"] or "",
                    "motivo": r["motivo"] or "",
                    "producto": r["producto"] or "",
                    "n_app_txt": r["n_app_txt"] or "",
                    "ingrediente": r["ingrediente"] or "",
                    "dosis": _fmt_num(r["dosis"], 4),
                    "unidad_dosis": r["unidad_dosis"] or "",
                    "vol_agua": _fmt_num(r["vol_total"], 1),
                    "gasto_total": _fmt_num(r["gasto_total"], 4),
                    "unidad_gasto": r["unidad_gasto"] or "",
                    "tractor": r["tractor"] or "",
                    "maquina": r["maquina"] or "",
                    "aplicador": r["aplicadores"] or "",
                    "car_etiqueta": _fmt_num(r["car_etiqueta"], 0),
                    "car_agenda": _fmt_num(r["car_agenda"], 0),
                    "car_mayor": _fmt_num(r["car_mayor"], 0),
                    "fecha_viable": str(r["fecha_viable"] or "")[:10].replace("None", ""),
                    "t_max": _fmt_num(r["t_max"], 1),
                    "t_min": _fmt_num(r["t_min"], 1),
                    "hr_pct": _fmt_num(r["hr_pct"], 0),
                    "viento_kmh": _fmt_num(r["viento_kmh"], 1),
                }
            )

    cols, rows = df_to_records(show, set(), demo) if not show.empty else ([], [])

    plan_edit = None
    plan_mod_eventos = []
    plan_mod_lineas = []
    plan_app_sel = None
    if demo.es_admin() and not df.empty:
        ev = (
            df.groupby(["n_aplicacion", "fecha", "sector"], dropna=False)
            .agg(productos=("producto", lambda s: " + ".join(str(x) for x in s)), n_prod=("producto", "count"))
            .reset_index()
            .sort_values(["fecha", "n_aplicacion"], ascending=[False, False])
        )
        for _, r in ev.iterrows():
            n_app = int(r["n_aplicacion"] or 0)
            plan_mod_eventos.append(
                {
                    "n_app": n_app,
                    "label": (
                        f"{n_app:05d} | {str(r['fecha'])[:10]} | {r['sector']} | "
                        f"{r['productos']} ({int(r['n_prod'])} prod.)"
                    ),
                }
            )
        if plan_mod_eventos:
            app_raw = request.args.get("n_app") or request.args.get("edit_n_app")
            if app_raw and str(app_raw).isdigit():
                plan_app_sel = int(app_raw)
            else:
                plan_app_sel = plan_mod_eventos[0]["n_app"]
            # keep selection even if filtered out of current df view
            if plan_app_sel not in {e["n_app"] for e in plan_mod_eventos}:
                plan_app_sel = plan_mod_eventos[0]["n_app"]

            lineas_df = pd.read_sql_query(
                """SELECT id, producto FROM libro_campo
                   WHERE n_aplicacion=? ORDER BY id""",
                conn,
                params=(plan_app_sel,),
            )
            for _, r in lineas_df.iterrows():
                plan_mod_lineas.append(
                    {"id": int(r["id"]), "label": f"ID {int(r['id'])} | {r['producto']}"}
                )

            lid = None
            linea_raw = request.args.get("linea_id") or request.args.get("edit_id")
            if linea_raw and str(linea_raw).isdigit():
                lid = int(linea_raw)
            elif plan_mod_lineas:
                lid = plan_mod_lineas[0]["id"]

            if lid is not None:
                edf = pd.read_sql_query(
                    """SELECT id, n_aplicacion, fecha, n_orden, sector, especie, variedad, motivo,
                              producto, n_aplicacion_txt, ingrediente, dosis, unidad_dosis, vol_total,
                              gasto_total, unidad_gasto, tractor, maquina, aplicadores,
                              car_etiqueta, car_agenda, car_mayor, fecha_viable,
                              t_max, t_min, hr_pct, viento_kmh
                       FROM libro_campo WHERE id=?""",
                    conn,
                    params=(lid,),
                )
                if not edf.empty:
                    data = edf.iloc[0]
                    u_d = str(data.get("unidad_dosis") or "")
                    plan_edit = {
                        "id": int(data["id"]),
                        "n_app": int(data.get("n_aplicacion") or 0),
                        "fecha": str(data.get("fecha") or "")[:10],
                        "n_orden": "" if data.get("n_orden") in (None, "") else str(data.get("n_orden")),
                        "cuartel": str(data.get("sector") or "").upper(),
                        "especie": data.get("especie") or "",
                        "variedad": data.get("variedad") or "",
                        "motivo": data.get("motivo") or "",
                        "producto": data.get("producto") or "",
                        "n_app_txt": data.get("n_aplicacion_txt") or "",
                        "ingrediente": data.get("ingrediente") or "",
                        "dosis": float(data.get("dosis") or 0),
                        "unidad_dosis": u_d if u_d in _UNIDADES_DOSIS_PLANILLA else _UNIDADES_DOSIS_PLANILLA[0],
                        "vol_agua": float(data.get("vol_total") or 0),
                        "gasto_total": float(data.get("gasto_total") or 0),
                        "unidad_gasto": data.get("unidad_gasto") or "",
                        "tractor": data.get("tractor") or "",
                        "maquina": data.get("maquina") or "",
                        "aplicador": data.get("aplicadores") or "",
                        "car_etiqueta": int(data.get("car_etiqueta") or 0),
                        "car_agenda": int(data.get("car_agenda") or 0),
                        "car_mayor": int(data.get("car_mayor") or 0),
                        "fecha_viable": str(data.get("fecha_viable") or data.get("fecha") or "")[:10],
                        "t_max": "" if pd.isna(data.get("t_max")) else data.get("t_max"),
                        "t_min": "" if pd.isna(data.get("t_min")) else data.get("t_min"),
                        "hr_pct": "" if pd.isna(data.get("hr_pct")) else data.get("hr_pct"),
                        "viento_kmh": "" if pd.isna(data.get("viento_kmh")) else data.get("viento_kmh"),
                    }
    pref = (cc_sel if cc_sel != "TODOS" else "activos").lower().replace(" ", "_")[:18]
    pdf = _pdf_url(
        demo,
        show,
        f"GLOBALGAP — Planilla aplicaciones — {cc_sel if cc_sel != 'TODOS' else 'CEREZOS CORTE 1 / CIRUELOS'}",
        f"globalgap_{pref}_planilla.pdf",
    )
    cuartel_ingreso = cc_sel if cc_sel != "TODOS" else _cuartel_default_planilla(especie)
    if cuartel_ingreso == "TODOS":
        cuartel_ingreso = cuarteles[0]
    ingreso_filas = [
        {
            "idx": i,
            "fecha": hoy_demo(demo).isoformat(),
            "cuartel": cuartel_ingreso,
            "especie": _especie_desde_cuartel(cuartel_ingreso, especie),
            "variedad": "Santina" if "CEREZOS" in cuartel_ingreso else "",
            "n_app_txt": "No aplica",
            "unidad_dosis": "Litros (L)",
            "maquina": "Pulverizadora",
        }
        for i in range(PLANILLA_INGRESO_FILAS)
    ]

    return {
        "plan_cols": cols,
        "plan_rows": rows,
        "plan_lineas": plan_lineas,
        "plan_admin": bool(demo.es_admin()),
        "plan_edit": plan_edit,
        "plan_mod_eventos": plan_mod_eventos,
        "plan_mod_lineas": plan_mod_lineas,
        "plan_app_sel": plan_app_sel,
        "pdf_plan_url": pdf,
        "plan_cuarteles": ["TODOS"] + cuarteles,
        "plan_cuarteles_activos": cuarteles,
        "plan_cuartel_sel": cc_sel,
        "plan_cuartel_ingreso": cuartel_ingreso,
        "plan_stats": {
            "lineas": len(df),
            "ordenes": int(df["n_orden"].astype(str).nunique()) if not df.empty else 0,
            "productos": int(df["producto"].nunique()) if not df.empty else 0,
        },
        "plan_unidades": _UNIDADES_DOSIS_PLANILLA,
        "plan_import_disponible": bool(
            _planilla_csv_paths(None if cc_sel == "TODOS" else cc_sel)
        ) and (cc_sel in ("TODOS", "CEREZOS CORTE 1", "CIRUELOS")),
        "plan_import_cuartel": (
            "CEREZOS CORTE 1"
            if cc_sel in ("TODOS", "CEREZOS CORTE 1")
            else "CIRUELOS"
            if cc_sel == "CIRUELOS"
            else cc_sel
        ),
        "plan_ingreso_filas": ingreso_filas,
        "plan_maq_opts": _MAQ_OPTS,
        "plan_met_opts": _MET_OPTS,
        "plan_epp_opts": _EPP_OPTS,
        "plan_sector_labels": _PLANILLA_SECTOR_LABEL,
        "plan_para_def": "Jefe de Campo",
        "hoy": hoy_demo(demo).isoformat(),
        "lc_url": url_for("modules.libro_campo", sec="historial"),
    }

_N_APP_HIST_MIN = 10000


def _siguiente_n_aplicacion(conn) -> int:
    """Correlativo operativo compartido con Libro de Campo (ignora histórico >= 10000)."""
    res = conn.execute(
        "SELECT MAX(CAST(n_aplicacion AS INTEGER)) FROM libro_campo "
        "WHERE n_aplicacion GLOB '[0-9]*' "
        "AND CAST(n_aplicacion AS INTEGER) < ?",
        (_N_APP_HIST_MIN,),
    ).fetchone()[0]
    return int(res) + 1 if res is not None else 1


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


def _form_float_idx(idx: int, name: str, default=0.0):
    raw = (request.form.get(f"r{idx}_{name}") or "").strip().replace(",", ".")
    if raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _form_opt_float_idx(idx: int, name: str):
    raw = (request.form.get(f"r{idx}_{name}") or "").strip().replace(",", ".")
    if raw == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _form_int_idx(idx: int, name: str, default=0) -> int:
    raw = (request.form.get(f"r{idx}_{name}") or "").strip().replace(",", ".")
    if raw == "":
        return default
    try:
        return int(float(raw))
    except ValueError:
        return default


def _siguiente_n_orden(conn, cuartel: str) -> str:
    """Correlativo de planilla por cuartel (debe avanzar también con altas desde Libro de Campo)."""
    res = conn.execute(
        "SELECT MAX(CAST(n_orden AS INTEGER)) FROM libro_campo "
        "WHERE UPPER(sector)=? AND n_orden GLOB '[0-9]*'",
        (str(cuartel or "").upper(),),
    ).fetchone()[0]
    return str(int(res) + 1 if res is not None else 1)


def _guardar_fila_planilla(demo, conn, especie: str, payload: dict) -> tuple[bool, str, str]:
    producto = (payload.get("producto") or "").strip()
    cuartel = (payload.get("cuartel") or "").strip().upper()
    aplicador = (payload.get("aplicador") or "").strip()
    maquina = (payload.get("maquina") or "").strip()
    if not producto:
        return False, "Producto vacío.", cuartel
    if cuartel not in [c.upper() for c in PLANILLA_CUARTELES_ACTIVOS]:
        return False, f"Cuartel no activo: {cuartel or '—'}.", cuartel
    if not aplicador:
        return False, f"{producto}: falta aplicador.", cuartel
    if not maquina:
        return False, f"{producto}: falta máquina.", cuartel

    fe = parse_date(payload.get("fecha"), hoy_demo(demo))
    car_e = int(payload.get("car_etiqueta") or 0)
    car_a = int(payload.get("car_agenda") or 0)
    car_m = payload.get("car_mayor")
    if car_m in (None, ""):
        car_m = max(car_e, car_a)
    else:
        car_m = int(car_m)
    fv_raw = payload.get("fecha_viable")
    fv = parse_date(fv_raw, fe + timedelta(days=car_m)) if fv_raw else fe + timedelta(days=car_m)
    n_orden = str(payload.get("n_orden") or "").strip() or _siguiente_n_orden(conn, cuartel)
    n_app = _siguiente_n_aplicacion(conn)
    row = {
        "fecha": fe.isoformat(),
        "n_orden": n_orden,
        "sector": cuartel,
        "especie": (payload.get("especie") or _especie_desde_cuartel(cuartel, especie)).strip(),
        "variedad": (payload.get("variedad") or "").strip(),
        "motivo": (payload.get("motivo") or "").strip(),
        "producto": producto,
        "n_app_txt": (payload.get("n_app_txt") or "").strip() or "No aplica",
        "ingrediente": (payload.get("ingrediente") or "").strip(),
        "dosis": float(payload.get("dosis") or 0),
        "unidad_dosis": payload.get("unidad_dosis") or _UNIDADES_DOSIS_PLANILLA[0],
        "vol_total": float(payload.get("vol_agua") or 0),
        "gasto_total": float(payload.get("gasto_total") or 0),
        "unidad_gasto": (payload.get("unidad_gasto") or "").strip(),
        "tractor": (payload.get("tractor") or "").strip(),
        "maquina": maquina,
        "aplicadores": aplicador,
        "car_etiqueta": car_e,
        "car_agenda": car_a,
        "car_mayor": car_m,
        "fecha_viable": fv.isoformat(),
        "t_max": payload.get("t_max"),
        "t_min": payload.get("t_min"),
        "hr_pct": payload.get("hr_pct"),
        "viento_kmh": payload.get("viento_kmh"),
        "lote_producto": (payload.get("lote") or "").strip(),
        "operador_certificado": bool(payload.get("op_cert")),
    }
    _insert_planilla_row(conn, row, n_app)
    return True, f"N°{n_app:05d} {producto}", cuartel


def _post_planilla_add(demo, conn, especie: str) -> dict:
    """Compatibilidad: una sola línea (formulario clásico)."""
    _ensure_libro_campo_planilla(conn)
    car_m_raw = request.form.get("car_mayor")
    ok, msg, cuartel = _guardar_fila_planilla(
        demo,
        conn,
        especie,
        {
            "fecha": request.form.get("fecha"),
            "n_orden": request.form.get("n_orden"),
            "cuartel": request.form.get("cuartel"),
            "especie": request.form.get("especie_cultivo") or especie,
            "variedad": request.form.get("variedad"),
            "motivo": request.form.get("motivo"),
            "producto": request.form.get("producto"),
            "n_app_txt": request.form.get("n_app_txt"),
            "ingrediente": request.form.get("ingrediente"),
            "dosis": _parse_float_form("dosis"),
            "unidad_dosis": request.form.get("unidad_dosis"),
            "vol_agua": _parse_float_form("vol_agua"),
            "gasto_total": _parse_float_form("gasto_total"),
            "unidad_gasto": request.form.get("unidad_gasto"),
            "tractor": request.form.get("tractor"),
            "maquina": request.form.get("maquina"),
            "aplicador": request.form.get("aplicador"),
            "car_etiqueta": _parse_int_form("car_etiqueta"),
            "car_agenda": _parse_int_form("car_agenda"),
            "car_mayor": None if car_m_raw in (None, "") else _parse_int_form("car_mayor"),
            "fecha_viable": request.form.get("fecha_viable"),
            "t_max": _parse_optional_float_form("t_max"),
            "t_min": _parse_optional_float_form("t_min"),
            "hr_pct": _parse_optional_float_form("hr_pct"),
            "viento_kmh": _parse_optional_float_form("viento_kmh"),
            "lote": request.form.get("lote"),
            "op_cert": request.form.get("op_cert") == "1",
        },
    )
    if not ok:
        return {"ok": False, "msg": msg, "extra": {"cuartel": cuartel}}
    conn.commit()
    demo.registrar_accion("GLOBALGAP PLANILLA", msg)
    return {"ok": True, "msg": f"Aplicación registrada en planilla y Libro de Campo ({msg}).", "extra": {"cuartel": cuartel}}


def _post_planilla_matriz(demo, conn, especie: str) -> dict:
    """Guarda varias líneas desde la matriz de ingreso de la misma pestaña."""
    _ensure_libro_campo_planilla(conn)
    try:
        n_rows = int(request.form.get("n_rows") or PLANILLA_INGRESO_FILAS)
    except ValueError:
        n_rows = PLANILLA_INGRESO_FILAS
    n_rows = max(1, min(n_rows, 40))

    guardadas = []
    errores = []
    last_cc = ""
    for i in range(n_rows):
        producto = (request.form.get(f"r{i}_producto") or "").strip()
        if not producto:
            continue
        car_m_raw = request.form.get(f"r{i}_car_mayor")
        ok, msg, cuartel = _guardar_fila_planilla(
            demo,
            conn,
            especie,
            {
                "fecha": request.form.get(f"r{i}_fecha"),
                "n_orden": request.form.get(f"r{i}_n_orden"),
                "cuartel": request.form.get(f"r{i}_cuartel"),
                "especie": request.form.get(f"r{i}_especie") or especie,
                "variedad": request.form.get(f"r{i}_variedad"),
                "motivo": request.form.get(f"r{i}_motivo"),
                "producto": producto,
                "n_app_txt": request.form.get(f"r{i}_n_app_txt"),
                "ingrediente": request.form.get(f"r{i}_ingrediente"),
                "dosis": _form_float_idx(i, "dosis"),
                "unidad_dosis": request.form.get(f"r{i}_unidad_dosis"),
                "vol_agua": _form_float_idx(i, "vol_agua"),
                "gasto_total": _form_float_idx(i, "gasto_total"),
                "unidad_gasto": request.form.get(f"r{i}_unidad_gasto"),
                "tractor": request.form.get(f"r{i}_tractor"),
                "maquina": request.form.get(f"r{i}_maquina"),
                "aplicador": request.form.get(f"r{i}_aplicador"),
                "car_etiqueta": _form_int_idx(i, "car_etiqueta"),
                "car_agenda": _form_int_idx(i, "car_agenda"),
                "car_mayor": None if car_m_raw in (None, "") else _form_int_idx(i, "car_mayor"),
                "fecha_viable": request.form.get(f"r{i}_fecha_viable"),
                "t_max": _form_opt_float_idx(i, "t_max"),
                "t_min": _form_opt_float_idx(i, "t_min"),
                "hr_pct": _form_opt_float_idx(i, "hr_pct"),
                "viento_kmh": _form_opt_float_idx(i, "viento_kmh"),
                "lote": request.form.get(f"r{i}_lote"),
                "op_cert": request.form.get(f"r{i}_op_cert") == "1",
            },
        )
        if ok:
            guardadas.append(msg)
            last_cc = cuartel or last_cc
        else:
            errores.append(msg)

    if not guardadas and not errores:
        return {"ok": False, "msg": "Complete al menos una fila con producto, aplicador y máquina."}
    if not guardadas and errores:
        return {"ok": False, "msg": "No se guardó ninguna fila. " + " · ".join(errores[:3])}

    conn.commit()
    demo.registrar_accion("GLOBALGAP PLANILLA MATRIZ", f"{len(guardadas)} línea(s)")
    msg = f"Se guardaron {len(guardadas)} aplicación(es) en planilla / Libro de Campo."
    if errores:
        msg += " Omitidas: " + " · ".join(errores[:3])
    return {"ok": True, "msg": msg, "extra": {"cuartel": last_cc or "TODOS"}}



def _ensure_gap_orden_aplicacion(conn) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS gap_orden_aplicacion (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            n_aplicacion INTEGER,
            para TEXT,
            fecha DATE,
            sector TEXT,
            especie TEXT,
            maq_tractor INTEGER DEFAULT 0,
            maq_pulverizadora INTEGER DEFAULT 0,
            maq_nebulizadora INTEGER DEFAULT 0,
            maq_espalda INTEGER DEFAULT 0,
            met_pulverizacion INTEGER DEFAULT 0,
            met_via_riego INTEGER DEFAULT 0,
            met_nebulizacion INTEGER DEFAULT 0,
            met_drenching INTEGER DEFAULT 0,
            epp_traje INTEGER DEFAULT 0,
            epp_botas INTEGER DEFAULT 0,
            epp_guantes INTEGER DEFAULT 0,
            epp_mascarilla INTEGER DEFAULT 0,
            epp_antiparras INTEGER DEFAULT 0,
            observaciones TEXT,
            mojamiento_l_ha REAL,
            reingreso_hrs REAL,
            emite TEXT,
            conf_fecha DATE,
            conf_hr_inicio TEXT,
            conf_hr_termino TEXT,
            conf_firma TEXT,
            t_c REAL,
            hr_pct REAL,
            viento_kmh REAL,
            lavado_maquinaria TEXT,
            lavado_volumen REAL,
            lavado_responsable TEXT,
            creado_en TEXT
        )"""
    )
    try:
        conn.commit()
    except Exception:
        pass


def _flag(name: str) -> int:
    return 1 if request.form.get(name) in ("1", "on", "true", "x", "X") else 0


def _parse_dosis_txt(raw: str, unidad_default: str = "Litros (L)") -> tuple[float, str]:
    raw = (raw or "").strip().replace(",", ".")
    if not raw:
        return 0.0, unidad_default
    unidad = unidad_default
    low = raw.lower()
    if "kg" in low:
        unidad = "Kilogramos (kg)"
    elif "g/" in low or low.endswith("g") or " gr" in low:
        unidad = "Gramos (g)"
    elif "lt" in low or "l/" in low or low.endswith("l"):
        unidad = "Litros (L)"
    nums = "".join(ch if (ch.isdigit() or ch == ".") else " " for ch in raw).split()
    try:
        return float(nums[0]), unidad
    except (ValueError, IndexError):
        return 0.0, unidad


def _post_planilla_orden(demo, conn, especie: str) -> dict:
    """Matriz de ingreso GlobalGAP (orden de aplicación) → Libro de Campo + cabecera."""
    from datetime import datetime as _dt

    _ensure_libro_campo_planilla(conn)
    _ensure_gap_orden_aplicacion(conn)

    sector = (request.form.get("sector") or "").strip().upper()
    if sector not in [c.upper() for c in PLANILLA_CUARTELES_ACTIVOS]:
        return {"ok": False, "msg": "Seleccione un cuartel activo (Cerezos Corte 1 o Ciruelos)."}
    fecha = parse_date(request.form.get("fecha"), hoy_demo(demo))
    especie_ord = (request.form.get("especie_cultivo") or _especie_desde_cuartel(sector, especie)).strip()
    para = (request.form.get("para") or "Jefe de Campo").strip()
    aplicador = (request.form.get("lavado_responsable") or request.form.get("aplicador") or "").strip()
    if not aplicador:
        return {"ok": False, "msg": "Indique el responsable de aplicación / lavado."}

    maqs = [label for key, label in _MAQ_OPTS if _flag(f"maq_{key}")]
    maquina = " / ".join(maqs) if maqs else (request.form.get("maquina_texto") or "").strip()
    if not maquina:
        return {"ok": False, "msg": "Marque al menos una maquinaria."}
    tractor = "SI" if _flag("maq_tractor") else ""

    def _fnum(name, default=None):
        raw = (request.form.get(name) or "").strip().replace(",", ".")
        if raw == "":
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    vol_agua = _fnum("lavado_volumen", 0.0) or 0.0
    mojamiento = _fnum("mojamiento_l_ha")
    if vol_agua <= 0 and mojamiento:
        vol_agua = float(mojamiento)
    t_max = _fnum("t_max")
    if t_max is None:
        t_max = _fnum("t_c")
    t_min = _fnum("t_min")
    hr = _fnum("hr_pct")
    viento = _fnum("viento_kmh")
    if any(v is None for v in (t_max, t_min, hr, viento)):
        from demo_web.services.weather import fetch_daily_weather

        wx = fetch_daily_weather(fecha, sector)
        if wx:
            if t_max is None:
                t_max = wx.get("t_max")
            if t_min is None:
                t_min = wx.get("t_min")
            if hr is None:
                hr = wx.get("hr_pct")
            if viento is None:
                viento = wx.get("viento_kmh")
    reingreso = _fnum("reingreso_hrs")

    try:
        n_rows = int(request.form.get("n_rows") or PLANILLA_INGRESO_FILAS)
    except ValueError:
        n_rows = PLANILLA_INGRESO_FILAS
    n_rows = max(1, min(n_rows, 20))

    variedad = (request.form.get("variedad") or "").strip()
    productos = []
    for i in range(n_rows):
        prod = (request.form.get(f"r{i}_producto") or "").strip()
        if not prod:
            continue
        car_e = _form_int_idx(i, "car_etiqueta")
        car_a = _form_int_idx(i, "car_agenda")
        car_o = _form_int_idx(i, "car_otro")
        car_m = max(car_e, car_a, car_o)
        dosis, unidad = _parse_dosis_txt(request.form.get(f"r{i}_dosis") or "")
        if request.form.get(f"r{i}_unidad_dosis"):
            unidad = request.form.get(f"r{i}_unidad_dosis")
        gasto = _form_float_idx(i, "gasto_total")
        if gasto <= 0 and vol_agua > 0 and dosis > 0:
            gasto = round(dosis * (vol_agua / 100.0), 4)
        productos.append(
            {
                "producto": prod,
                "ingrediente": (request.form.get(f"r{i}_ingrediente") or "").strip(),
                "motivo": (request.form.get(f"r{i}_objetivo") or "").strip(),
                "dosis": dosis,
                "unidad_dosis": unidad,
                "gasto_total": gasto,
                "unidad_gasto": "L" if "Litros" in unidad else ("kg" if "Kilogramos" in unidad else ""),
                "car_etiqueta": car_e,
                "car_agenda": car_a,
                "car_mayor": car_m,
                "n_app_txt": (request.form.get(f"r{i}_n_app_txt") or "").strip() or "1 de 1",
                "variedad": variedad,
            }
        )

    if not productos:
        return {"ok": False, "msg": "Ingrese al menos un producto en la matriz."}

    n_app = _siguiente_n_aplicacion(conn)
    n_orden = _siguiente_n_orden(conn, sector)
    conf_fecha = parse_date(request.form.get("conf_fecha"), fecha)

    for p in productos:
        car_m = int(p["car_mayor"])
        fv = (fecha + timedelta(days=car_m)).isoformat()
        _insert_planilla_row(
            conn,
            {
                "fecha": fecha.isoformat(),
                "n_orden": n_orden,
                "sector": sector,
                "especie": especie_ord,
                "variedad": p.get("variedad") or "",
                "motivo": p["motivo"],
                "producto": p["producto"],
                "n_app_txt": p["n_app_txt"],
                "ingrediente": p["ingrediente"],
                "dosis": p["dosis"],
                "unidad_dosis": p["unidad_dosis"],
                "vol_total": vol_agua,
                "gasto_total": p["gasto_total"],
                "unidad_gasto": p["unidad_gasto"],
                "tractor": tractor,
                "maquina": maquina,
                "aplicadores": aplicador,
                "car_etiqueta": p["car_etiqueta"],
                "car_agenda": p["car_agenda"],
                "car_mayor": car_m,
                "fecha_viable": fv,
                "t_max": t_max,
                "t_min": t_min,
                "hr_pct": hr,
                "viento_kmh": viento,
                "lote_producto": "",
                "operador_certificado": 0,
            },
            n_app,
        )

    obs = (request.form.get("observaciones") or "").strip()
    if not obs:
        obs = "Lea la etiqueta del producto | Use su Equipo de Protección Personal"

    conn.execute(
        """INSERT INTO gap_orden_aplicacion
           (n_aplicacion, para, fecha, sector, especie,
            maq_tractor, maq_pulverizadora, maq_nebulizadora, maq_espalda,
            met_pulverizacion, met_via_riego, met_nebulizacion, met_drenching,
            epp_traje, epp_botas, epp_guantes, epp_mascarilla, epp_antiparras,
            observaciones, mojamiento_l_ha, reingreso_hrs, emite,
            conf_fecha, conf_hr_inicio, conf_hr_termino, conf_firma,
            t_c, hr_pct, viento_kmh, lavado_maquinaria, lavado_volumen, lavado_responsable,
            creado_en)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            n_app, para, fecha.isoformat(), sector, especie_ord,
            _flag("maq_tractor"), _flag("maq_pulverizadora"), _flag("maq_nebulizadora"), _flag("maq_espalda"),
            _flag("met_pulverizacion"), _flag("met_via_riego"), _flag("met_nebulizacion"), _flag("met_drenching"),
            _flag("epp_traje"), _flag("epp_botas"), _flag("epp_guantes"), _flag("epp_mascarilla"), _flag("epp_antiparras"),
            obs, mojamiento, reingreso, (request.form.get("emite") or "").strip(),
            conf_fecha.isoformat(),
            (request.form.get("conf_hr_inicio") or "").strip(),
            (request.form.get("conf_hr_termino") or "").strip(),
            (request.form.get("conf_firma") or "").strip(),
            t_max, hr, viento,
            (request.form.get("lavado_maquinaria") or "").strip(),
            vol_agua if vol_agua else None,
            aplicador,
            _dt.utcnow().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    prods = ", ".join(p["producto"] for p in productos)
    demo.registrar_accion("GLOBALGAP ORDEN APP", f"N°{n_app} {sector} · {prods}")
    return {
        "ok": True,
        "msg": f"Orden de aplicación N° {n_app:05d} guardada ({len(productos)} producto(s)) en planilla y Libro de Campo.",
        "extra": {"cuartel": sector},
    }



def _post_planilla_edit(demo, conn, especie: str) -> dict:
    denied = _require_admin_gap(demo, request.form.get("clave_maestra"))
    if denied:
        return denied
    _ensure_libro_campo_planilla(conn)
    try:
        lid = int(request.form.get("linea_id") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Línea inválida."}
    row = conn.execute("SELECT id, n_aplicacion, sector FROM libro_campo WHERE id=?", (lid,)).fetchone()
    if not row:
        return {"ok": False, "msg": "Línea no encontrada."}
    n_app = int(row[1] or 0)
    sector = (request.form.get("cuartel") or request.form.get("sector") or row[2] or "").strip().upper()
    if sector and sector not in [c.upper() for c in PLANILLA_CUARTELES_ACTIVOS]:
        return {"ok": False, "msg": "Cuartel no activo para planilla."}

    car_e = _parse_int_form("car_etiqueta")
    car_a = _parse_int_form("car_agenda")
    car_m_raw = request.form.get("car_mayor")
    car_m = max(car_e, car_a) if car_m_raw in (None, "") else _parse_int_form("car_mayor", max(car_e, car_a))
    fe = parse_date(request.form.get("fecha"), hoy_demo(demo))
    fv = parse_date(request.form.get("fecha_viable"), fe + timedelta(days=car_m))

    conn.execute(
        """UPDATE libro_campo SET
           fecha=?, n_orden=?, sector=?, especie=?, variedad=?, motivo=?, producto=?,
           n_aplicacion_txt=?, ingrediente=?, dosis=?, unidad_dosis=?, vol_total=?,
           gasto_total=?, unidad_gasto=?, tractor=?, maquina=?, aplicadores=?,
           car_etiqueta=?, car_agenda=?, car_mayor=?, fecha_viable=?,
           t_max=?, t_min=?, hr_pct=?, viento_kmh=?
           WHERE id=?""",
        (
            fe.isoformat(),
            (request.form.get("n_orden") or "").strip(),
            sector,
            (request.form.get("especie_cultivo") or request.form.get("especie") or especie).strip(),
            (request.form.get("variedad") or "").strip(),
            (request.form.get("motivo") or "").strip(),
            (request.form.get("producto") or "").strip(),
            (request.form.get("n_app_txt") or "").strip(),
            (request.form.get("ingrediente") or "").strip(),
            _parse_float_form("dosis"),
            request.form.get("unidad_dosis") or _UNIDADES_DOSIS_PLANILLA[0],
            _parse_float_form("vol_agua"),
            _parse_float_form("gasto_total"),
            (request.form.get("unidad_gasto") or "").strip(),
            (request.form.get("tractor") or "").strip(),
            (request.form.get("maquina") or "").strip(),
            (request.form.get("aplicador") or "").strip(),
            car_e,
            car_a,
            car_m,
            fv.isoformat(),
            _parse_optional_float_form("t_max"),
            _parse_optional_float_form("t_min"),
            _parse_optional_float_form("hr_pct"),
            _parse_optional_float_form("viento_kmh"),
            lid,
        ),
    )
    conn.commit()
    demo.registrar_accion("GLOBALGAP PLANILLA EDIT", f"App N°{n_app} línea {lid}")
    return {
        "ok": True,
        "msg": f"Línea {lid} actualizada (App N° {n_app:05d}).",
        "extra": {"cuartel": sector, "n_app": n_app, "linea_id": lid},
    }


def _post_planilla_delete(demo, conn, especie: str) -> dict:
    denied = _require_admin_gap(demo, request.form.get("clave_maestra"))
    if denied:
        return denied
    try:
        lid = int(request.form.get("linea_id") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Línea inválida."}
    row = conn.execute(
        "SELECT id, n_aplicacion, sector, producto FROM libro_campo WHERE id=?",
        (lid,),
    ).fetchone()
    if not row:
        return {"ok": False, "msg": "Línea no encontrada."}
    n_app = int(row[1] or 0)
    sector = (row[2] or "").upper()
    producto = row[3] or ""
    conn.execute("DELETE FROM libro_campo WHERE id=?", (lid,))
    # si no quedan líneas del evento, limpia cabecera de orden
    left = conn.execute(
        "SELECT COUNT(*) FROM libro_campo WHERE n_aplicacion=?",
        (n_app,),
    ).fetchone()[0]
    if left == 0:
        try:
            conn.execute("DELETE FROM gap_orden_aplicacion WHERE n_aplicacion=?", (n_app,))
        except sqlite3.OperationalError:
            pass
    conn.commit()
    demo.registrar_accion("GLOBALGAP PLANILLA DEL", f"App N°{n_app} línea {lid} · {producto}")
    return {
        "ok": True,
        "msg": f"Línea eliminada (App N° {n_app:05d} · {producto}).",
        "extra": {"cuartel": sector},
    }



def _post_planilla_delete_evento(demo, conn, especie: str) -> dict:
    denied = _require_admin_gap(demo, request.form.get("clave_maestra"))
    if denied:
        return denied
    try:
        n_app = int(request.form.get("n_app") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Aplicación inválida."}
    if n_app <= 0:
        return {"ok": False, "msg": "Aplicación inválida."}
    row = conn.execute(
        "SELECT sector FROM libro_campo WHERE n_aplicacion=? LIMIT 1",
        (n_app,),
    ).fetchone()
    sector = (row[0] if row else request.form.get("cuartel") or "").upper()
    conn.execute("DELETE FROM libro_campo WHERE n_aplicacion=?", (n_app,))
    try:
        conn.execute("DELETE FROM gap_orden_aplicacion WHERE n_aplicacion=?", (n_app,))
    except sqlite3.OperationalError:
        pass
    conn.commit()
    demo.registrar_accion("GLOBALGAP PLANILLA DEL APP", f"App N°{n_app} completa")
    return {
        "ok": True,
        "msg": f"Aplicación N° {n_app:05d} eliminada por completo.",
        "extra": {"cuartel": sector or "TODOS"},
    }


def _post_planilla_import(demo, conn, especie: str) -> dict:
    _ensure_libro_campo_planilla(conn)
    cuartel = (request.form.get("cuartel") or "").strip().upper()
    if cuartel not in _PLANILLA_CSV_BY_CUARTEL:
        cuartel = _cuartel_default_planilla(especie)
        if cuartel not in _PLANILLA_CSV_BY_CUARTEL:
            cuartel = "CEREZOS CORTE 1"
    paths = _planilla_csv_paths(cuartel)
    if not paths:
        return {"ok": False, "msg": f"No se encontró el archivo de planilla para {cuartel}."}
    path = paths[0]
    inserted = 0
    skipped = 0
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            sector = (raw.get("sector") or cuartel).strip().upper()
            if sector != cuartel:
                skipped += 1
                continue
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
            n_orden = (raw.get("n_orden") or "").strip()
            if n_orden != "":
                exists_ord = conn.execute(
                    """SELECT id FROM libro_campo
                       WHERE UPPER(sector)=? AND TRIM(COALESCE(n_orden,''))=?
                         AND UPPER(TRIM(producto))=UPPER(TRIM(?))
                       LIMIT 1""",
                    (sector, n_orden, producto),
                ).fetchone()
                if exists_ord:
                    skipped += 1
                    continue
            n_app = _siguiente_n_aplicacion(conn)
            row = dict(raw)
            row["sector"] = sector
            row["producto"] = producto
            row["fecha"] = fecha
            row["especie"] = (
                raw.get("especie") or _especie_desde_cuartel(cuartel, especie) or especie or "Cerezos"
            ).strip()
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
        "msg": f"Importación {cuartel}: {inserted} nuevas · {skipped} omitidas (ya existían o inválidas).",
        "extra": {"cuartel": cuartel},
    }


def gather_globalgap(user_email: str, user_rol: str) -> dict:
    from demo_web.services.gap_scope import (
        ensure_demo_especies,
        is_globalgap_tenant,
        load_scope,
        session_ambito_id,
    )

    demo = get_demo_module()
    bind_user_session(user_email, user_rol)
    consultor_label = ""
    scope = None
    if is_globalgap_tenant():
        conn_pre = demo.conectar_db()
        try:
            if session_ambito_id():
                scope = load_scope(conn_pre)
            if scope:
                ensure_demo_especies(demo, scope)
                consultor_label = getattr(demo, "_gap_ambito_label", "")
                especie = scope.especie_key
            else:
                especie = demo.GAP_ESPECIES[0] if getattr(demo, "GAP_ESPECIES", None) else "ESPECIE 1"
        finally:
            conn_pre.close()
    else:
        especie = _especie_sel(demo)

    sec = request.args.get("sec", "gantt")
    if sec not in {k for k, _ in SECCIONES}:
        sec = "gantt"

    conn = demo.conectar_db()
    try:
        if scope:
            cuarteles = [scope.huerto]
        else:
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
            "consultor_label": consultor_label,
            "is_consultor_tenant": bool(scope),
            "panel_url": "",
            "kpis": res,
            "alertas": {
                "nc": res["nc_abiertas"] > 0,
                "cap": res["cap_venc"] > 0,
                "agua": res["agua_venc"] > 0,
            },
            "pdf_resumen_url": pdf_resumen,
        }
        if scope:
            from flask import url_for

            ctx["panel_url"] = url_for("globalgap_portal.panel")

        loaders = {
            "gantt": _section_gantt,
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
    from flask import redirect, url_for

    from demo_web.services.gap_scope import is_globalgap_tenant, session_ambito_id

    demo = get_demo_module()
    bind_user_session(user_email, user_rol)

    if is_globalgap_tenant() and not session_ambito_id():
        return redirect(url_for("globalgap_portal.panel"))

    if request.method == "GET" and request.args.get("clima") == "1":
        from demo_web.services.weather import fetch_daily_weather

        fecha = parse_date(request.args.get("fecha"), hoy_demo(demo))
        sector = (request.args.get("sector") or "").strip() or None
        wx = fetch_daily_weather(fecha, sector)
        if not wx:
            return jsonify({"ok": False, "msg": "No se pudo obtener clima para la fecha indicada."}), 502
        return jsonify({"ok": True, **wx})

    if request.method == "GET" and request.args.get("download_doc"):
        especie = _especie_sel(demo)
        conn = demo.conectar_db()
        try:
            return _download_gap_documento(demo, conn, especie)
        finally:
            conn.close()

    if request.method == "POST":
        action = request.form.get("action", "")
        sec = request.form.get("sec") or request.args.get("sec", "gantt")
        especie = _especie_sel(demo)
        conn = demo.conectar_db()
        try:
            handlers = {
                "pppl_add": _post_pppl_add,
                "pppl_sync_ok": lambda d, c: _post_pppl_sync(d, c, incluir_baja=False),
                "pppl_sync_all": lambda d, c: _post_pppl_sync(d, c, incluir_baja=True),
                "doc_add": lambda d, c: _post_doc_add(d, c, especie),
                "doc_import_catalog": lambda d, c: _post_doc_import_catalog(d, c, especie),
                "doc_cumple": lambda d, c: _post_doc_cumple(d, c, especie, user_email),
                "eval_save": lambda d, c: _post_eval_save(d, c, especie, user_email),
                "nc_open": lambda d, c: _post_nc_open(d, c, especie),
                "nc_close": _post_nc_close,
                "cap_add": _post_cap_add,
                "cosecha_add": lambda d, c: _post_cosecha_add(d, c, especie),
                "planilla_add": lambda d, c: _post_planilla_add(d, c, especie),
                "planilla_matriz": lambda d, c: _post_planilla_orden(d, c, especie),
                "planilla_orden": lambda d, c: _post_planilla_orden(d, c, especie),
                "planilla_import": lambda d, c: _post_planilla_import(d, c, especie),
                "planilla_edit": lambda d, c: _post_planilla_edit(d, c, especie),
                "planilla_delete": lambda d, c: _post_planilla_delete(d, c, especie),
                "planilla_delete_evento": lambda d, c: _post_planilla_delete_evento(d, c, especie),
                "agua_add": _post_agua_add,
                "cal_add": _post_cal_add,
                "gantt_rebuild": lambda d, c: _post_gantt_rebuild(d, c, especie),
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
                if sec == "documentos" and request.form.get("tipo"):
                    extra["tipo"] = request.form.get("tipo")
                if sec == "cosecha" and request.form.get("cuartel"):
                    extra["cuartel"] = request.form.get("cuartel")
                if sec == "planilla":
                    cu = (result.get("extra") or {}).get("cuartel") or request.form.get("cuartel") or request.form.get("sector")
                    if cu and cu != "TODOS":
                        extra["cuartel"] = cu
                    if action == "planilla_edit" and request.form.get("n_app"):
                        extra["n_app"] = request.form.get("n_app")
                        if request.form.get("linea_id"):
                            extra["linea_id"] = request.form.get("linea_id")
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
