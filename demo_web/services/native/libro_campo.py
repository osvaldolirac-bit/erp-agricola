from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import pandas as pd
from flask import flash, jsonify, render_template, request, session, url_for

from demo_web.services.demo_loader import bind_user_session, get_demo_module
from demo_web.services.module_runner import pdf_download_url, redirect_module, store_pdf
from demo_web.services.native._helpers import hoy_demo, parse_date
from demo_web.services.tenant_scope import is_concepcion_tenant, tenant_slug
from demo_web.services.lc_aplicacion_service import (
    LcAplicacionError,
    guardar_aplicacion_lc,
    reabrir_aplicacion_lc,
    eliminar_aplicacion_lc,
    eliminar_linea_lc,
)
from demo_web.services.lc_bodega_desfase import (
    insertar_salida_desde_lc,
    lc_dict_desde_item_libro,
    lc_dict_desde_linea_libro,
    mensaje_error_salida_lc,
    revertir_salidas_lineas_libro,
    revertir_salida_desde_lc,
)


def _tenant_slug_lc(demo) -> str:
    return (session.get("tenant_slug") or getattr(demo, "TENANT_SLUG", "") or "").strip().lower()


def _libro_cuarteles(demo) -> list[str]:
    if _tenant_slug_lc(demo) == "espino":
        from demo_web.services.espino_scope import cuarteles_espino

        return cuarteles_espino()
    return list(demo.CENTROS_COSTO or [])


def _libro_especies(demo) -> list[str]:
    if _tenant_slug_lc(demo) == "espino":
        from demo_web.services.espino_scope import especies_libro_campo_espino

        return especies_libro_campo_espino()
    especies = getattr(demo, "LIBRO_CAMPO_ESPECIES", None) or demo.GAP_ESPECIES
    return list(especies or [])


SECCIONES_BASE = [
    ("historial", "📜 HISTORIAL AUDITABLE"),
    ("ingreso", "📥 INGRESO APLICACIÓN"),
    ("desfase", "⚠️ DESFASE BODEGA"),
    ("prog_cerezos", "🍒 PROGRAMA CEREZAS"),
    ("prog_ciruelos", "🟣 PROGRAMA CIRUELOS"),
]

FITOSANITARIO_PROGRAMAS = {
    "cerezos": {
        "titulo": "Programa Fitosanitario Cerezas",
        "temporada": "2026-2027",
        "version": "1.0",
        "emision": "Jun-26",
        "archivo": "programa_cerezos_2026-2027.pdf",
        "carpeta_paginas": "cerezos",
        "descarga": "programa_fitosanitario_cerezos_2026-2027.pdf",
        "emoji": "🍒",
        "notas": (
            "Pauta técnica Exportadora Subsole para protección de cerezos. "
            "Antes de aplicar, verifique PPPL Subsole, registro SAG, dosis de etiqueta y carencias "
            "(etiqueta + Asoex/LMR según mercado destino)."
        ),
    },
    "ciruelos": {
        "titulo": "Programa Fitosanitario Ciruelos",
        "temporada": "2026-2027",
        "version": "1.0",
        "emision": "Jun-26",
        "archivo": "programa_ciruelos_2026-2027.pdf",
        "carpeta_paginas": "ciruelos",
        "descarga": "programa_fitosanitario_ciruelos_2026-2027.pdf",
        "emoji": "🟣",
        "notas": (
            "Programa D'Agen / Exportadora Subsole para ciruelos. "
            "Productos fuera de este programa o del PPPL deben consultarse con el agrónomo "
            "de Subsole antes de aplicar."
        ),
    },
}

_SEC_PROGRAMA = {
    "prog_cerezos": "cerezos",
    "prog_ciruelos": "ciruelos",
}


def _fitosanitarios_bases() -> list[Path]:
    bases: list[Path] = []
    for raw in (
        os.environ.get("ERP_FITOSANITARIOS_DIR"),
        "/root/static/fitosanitarios",
        str(Path(__file__).resolve().parents[3] / "static" / "fitosanitarios"),
        str(Path(__file__).resolve().parents[2] / "static" / "fitosanitarios"),
    ):
        if not raw:
            continue
        p = Path(raw)
        if p not in bases:
            bases.append(p)
    return bases


def ruta_programa_pdf(especie_key: str) -> Path | None:
    meta = FITOSANITARIO_PROGRAMAS.get(especie_key) or {}
    archivo = meta.get("archivo") or ""
    if not archivo:
        return None
    for base in _fitosanitarios_bases():
        path = base / archivo
        if path.is_file():
            return path
    return None


def ruta_programa_paginas_dir(especie_key: str) -> Path | None:
    meta = FITOSANITARIO_PROGRAMAS.get(especie_key) or {}
    sub = meta.get("carpeta_paginas") or especie_key
    for base in _fitosanitarios_bases():
        path = base / sub
        if path.is_dir():
            return path
    return None


def listar_paginas_programa(especie_key: str) -> list[Path]:
    dir_path = ruta_programa_paginas_dir(especie_key)
    if not dir_path:
        return []
    return sorted(
        p
        for p in dir_path.iterdir()
        if p.is_file() and p.name.lower().startswith("pagina_") and p.suffix.lower() == ".jpg"
    )


def ruta_programa_pagina(especie_key: str, n: int) -> Path | None:
    if n < 1:
        return None
    pages = listar_paginas_programa(especie_key)
    if n > len(pages):
        return None
    return pages[n - 1]


def _programa_ctx(especie_key: str) -> dict:
    meta = FITOSANITARIO_PROGRAMAS.get(especie_key)
    if not meta:
        return {"programa": None}
    pdf_path = ruta_programa_pdf(especie_key)
    pages = listar_paginas_programa(especie_key)
    page_urls = [
        url_for("modules.fitosanitario_pagina", especie=especie_key, n=i)
        for i in range(1, len(pages) + 1)
    ]
    return {
        "programa": {
            "especie": especie_key,
            "titulo": meta["titulo"],
            "temporada": meta["temporada"],
            "version": meta["version"],
            "emision": meta["emision"],
            "emoji": meta["emoji"],
            "notas": meta["notas"],
            "archivo": meta["archivo"],
            "pdf_ok": bool(pdf_path),
            "pdf_url": url_for("modules.fitosanitario_pdf", especie=especie_key) if pdf_path else None,
            "descarga": meta["descarga"],
            "paginas": page_urls,
            "n_paginas": len(page_urls),
        }
    }

CAR_KEY = "lc_car"
META_KEY = "lc_evento_meta"
UNDO_KEY = "lc_undo_registro"
UNIDADES_DOSIS = [
    "Gramos (g)",
    "Centímetros Cúbicos (cc)",
    "Kilogramos (kg)",
    "Litros (L)",
]


def _fmt_op_cert(val) -> str:
    if val in (1, "1", True, "Sí", "Si"):
        return "Sí"
    return "No"


def _secciones(demo) -> list[tuple[str, str]]:
    secs = list(SECCIONES_BASE)
    if demo.es_admin():
        secs.append(("modificar", "🛠️ MODIFICAR / ELIMINAR"))
    return secs


def _check_master(demo, clave: str) -> bool:
    return (clave or "").strip() == demo.CLAVE_MAESTRA


def _redirect_lc(sec: str, **extra) -> redirect_module:
    return redirect_module("libro_campo", sec=sec, **extra)


def _pop_alertas() -> dict:
    out = {}
    if "lc_alerta_bodega" in session:
        al = session.pop("lc_alerta_bodega")
        prods = []
        for p in al.get("productos", []):
            prods.append(
                {
                    "producto": p.get("producto", ""),
                    "cantidad": p.get("gasto_total", 0),
                    "um": p.get("um_gasto", "gr"),
                }
            )
        out["alerta_bodega"] = {
            "n_app": al.get("n_app"),
            "huerto": al.get("huerto", ""),
            "productos": prods,
        }
    return out


def _opciones_maquinaria(conn, tipos, permitir_vacio: bool = False) -> list[tuple[str, str]]:
    from erp_maquinaria import etiqueta_maquinaria, listar_maquinaria

    items = listar_maquinaria(conn, solo_activos=True, tipos=tipos)
    opts = [(m["codigo"], etiqueta_maquinaria(m["codigo"], m["nombre"])) for m in items]
    if permitir_vacio:
        return [("", "— Sin tractor —")] + opts
    return opts


def _productos_stock(demo, conn) -> list[dict]:
    if _tenant_slug_lc(demo) == "espino":
        from demo_web.services.espino_bodega_stock import productos_disponibles_libro_campo
        from demo_web.services.native import espino_bodega

        return productos_disponibles_libro_campo(
            conn, demo, es_bodega_fn=espino_bodega._es_producto_bodega_espino
        )

    df = pd.read_sql_query(
        "SELECT producto, stock, COALESCE(unidad_medida, ?) AS um FROM inventario WHERE stock > 0 ORDER BY producto",
        conn,
        params=(demo.DEFAULT_UNIDAD_INSUMO,),
    )
    out = []
    for _, r in df.iterrows():
        out.append(
            {
                "producto": r["producto"],
                "stock_fmt": demo.f_cantidad(r["stock"]),
                "um": r["um"],
            }
        )
    return out



def _evento_meta_defaults(demo) -> dict:
    return {
        "fecha": hoy_demo(demo).isoformat(),
        "cuartel": "",
        "especie": "",
        "vol_agua": "",
        "aplicador": "",
        "op_cert": "",
        "maquinaria": "",
        "tractor": "",
    }


def _guardar_evento_meta(demo, src=None) -> dict:
    """Guarda cabecera del evento en sesión (sobrevive a agregar producto / cambio de prod)."""
    src = src if src is not None else request.values
    meta = session.get(META_KEY) or _evento_meta_defaults(demo)
    for key in ("fecha", "cuartel", "especie", "vol_agua", "aplicador", "maquinaria", "tractor"):
        if key in src:
            meta[key] = (src.get(key) or "").strip()
    if "op_cert" in src:
        meta["op_cert"] = "1" if src.get("op_cert") in ("1", "on", "true", "True") else ""
    session[META_KEY] = meta
    return meta


def _leer_evento_meta(demo) -> dict:
    base = _evento_meta_defaults(demo)
    meta = session.get(META_KEY) or {}
    out = {**base, **{k: meta.get(k, base.get(k)) for k in base}}
    cuarteles = _libro_cuarteles(demo)
    especies = _libro_especies(demo)
    if not out.get("cuartel") and cuarteles:
        out["cuartel"] = cuarteles[0]
    if not out.get("especie") and especies:
        out["especie"] = especies[0]
    return out

# Histórico importado (planillas antiguas) vive en n_aplicacion >= 10000
# para no romper el correlativo operativo de la temporada.
_N_APP_HIST_MIN = 10000


def _siguiente_n_aplicacion(conn) -> int:
    """Siguiente N° app de temporada (ignora histórico archivado >= 10000)."""
    res = conn.execute(
        "SELECT MAX(CAST(n_aplicacion AS INTEGER)) FROM libro_campo "
        "WHERE n_aplicacion GLOB '[0-9]*' "
        "AND CAST(n_aplicacion AS INTEGER) < ?",
        (_N_APP_HIST_MIN,),
    ).fetchone()[0]
    return int(res) + 1 if res is not None else 1


def _ultima_n_aplicacion(conn) -> int | None:
    n = _siguiente_n_aplicacion(conn) - 1
    return n if n >= 1 else None


def _lineas_aplicacion(conn, n_app: int) -> list[dict]:
    cur = conn.execute(
        """SELECT id, movimiento_id, producto, lote_producto, ingrediente, dosis, unidad_dosis,
                  gasto_total, unidad_gasto, vol_total, fecha, sector, especie,
                  aplicadores, operador_certificado, maquina, tractor, car_etiqueta,
                  n_aplicacion
           FROM libro_campo WHERE n_aplicacion=? ORDER BY id""",
        (int(n_app),),
    )
    cols = [d[0] for d in cur.description or ()]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _linea_libro_por_id(conn, linea_id: int) -> dict | None:
    cur = conn.execute(
        """SELECT id, movimiento_id, n_aplicacion, producto, lote_producto, ingrediente, dosis,
                  unidad_dosis, gasto_total, unidad_gasto, vol_total, fecha, sector, especie,
                  aplicadores, operador_certificado, maquina, tractor, car_etiqueta
           FROM libro_campo WHERE id=?""",
        (int(linea_id),),
    )
    row = cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description or ()]
    return dict(zip(cols, row))


def _car_y_meta_desde_lineas(rows) -> tuple[list[dict], dict]:
    car: list[dict] = []
    for r in rows:
        try:
            dias_car = int(r["car_etiqueta"] or 0)
        except (TypeError, ValueError):
            dias_car = 0
        car.append(
            {
                "producto": r["producto"],
                "lote_producto": r["lote_producto"] or "",
                "ingrediente": r["ingrediente"] or "",
                "dosis": float(r["dosis"] or 0),
                "unidad_dosis": r["unidad_dosis"] or UNIDADES_DOSIS[0],
                "gasto_total": float(r["gasto_total"] or 0),
                "um_gasto": r["unidad_gasto"] or "",
                "dias_car": dias_car,
            }
        )
    r0 = rows[0]
    meta = {
        "fecha": str(r0["fecha"] or "")[:10],
        "cuartel": (r0["sector"] or "").strip(),
        "especie": (r0["especie"] or "").strip(),
        "vol_agua": str(float(r0["vol_total"] or 0)),
        "aplicador": (r0["aplicadores"] or "").strip(),
        "op_cert": "1" if int(r0["operador_certificado"] or 0) else "",
        "maquinaria": (r0["maquina"] or "").strip(),
        "tractor": (r0["tractor"] or "").strip(),
    }
    return car, meta


def _reabrir_n_app_ctx(demo, conn) -> int | None:
    """Última app registrada que se puede volver a borrador (ingreso vacío o undo reciente)."""
    ultima = _ultima_n_aplicacion(conn)
    if not ultima:
        return None
    rows = _lineas_aplicacion(conn, ultima)
    if not rows:
        return None
    car = session.get(CAR_KEY, [])
    if car:
        return None
    undo_n = session.get(UNDO_KEY)
    if undo_n is not None and int(undo_n) == ultima:
        return ultima
    fe = parse_date(str(rows[0]["fecha"]), hoy_demo(demo))
    if (hoy_demo(demo) - fe).days <= 14:
        return ultima
    return None


def _siguiente_n_orden(conn, sector: str) -> str:
    """Correlativo de planilla GlobalGAP por cuartel (mismo criterio que globalgap)."""
    res = conn.execute(
        "SELECT MAX(CAST(n_orden AS INTEGER)) FROM libro_campo "
        "WHERE UPPER(sector)=? AND n_orden GLOB '[0-9]*'",
        (str(sector or "").upper(),),
    ).fetchone()[0]
    return str(int(res) + 1 if res is not None else 1)


def _ingreso(demo, conn) -> dict:
    siguiente = _siguiente_n_aplicacion(conn)
    car = session.get(CAR_KEY, [])
    # Restaura / actualiza cabecera si viene en query (cambio de producto GET)
    if any(k in request.args for k in ("fecha", "cuartel", "vol_agua", "aplicador", "especie", "maquinaria", "tractor", "op_cert")):
        _guardar_evento_meta(demo, request.args)
    meta = _leer_evento_meta(demo)

    from erp_maquinaria import TIPOS_MAQUINARIA_APLICACION, TIPOS_MAQUINARIA_TRACTOR

    productos = _productos_stock(demo, conn)
    prod_sel = request.args.get("prod") or (productos[0]["producto"] if productos else "")
    phi_def = demo.dias_carencia_producto(conn, prod_sel, 0) if prod_sel else 0
    ing_def = demo._ingrediente_pppl_producto(conn, prod_sel) if prod_sel else ""
    stock_info = next((p for p in productos if p["producto"] == prod_sel), None)

    car_rows = []
    for item in car:
        car_rows.append(
            {
                "producto": item["producto"],
                "lote": item.get("lote_producto", ""),
                "ingrediente": item.get("ingrediente", ""),
                "dosis": demo.f_dosis_lc(item.get("dosis", 0)),
                "unidad_dosis": item.get("unidad_dosis", ""),
                "gasto_total": demo.f_cantidad(item.get("gasto_total", 0)),
                "um_gasto": item.get("um_gasto", ""),
                "dias_car": item.get("dias_car", 0),
            }
        )

    return {
        "siguiente_app": siguiente,
        "hoy": meta.get("fecha") or hoy_demo(demo).isoformat(),
        "form_fecha": meta.get("fecha") or hoy_demo(demo).isoformat(),
        "form_cuartel": meta.get("cuartel") or "",
        "form_especie": meta.get("especie") or "",
        "form_vol_agua": meta.get("vol_agua") or "",
        "form_aplicador": meta.get("aplicador") or "",
        "form_op_cert": bool(meta.get("op_cert")),
        "form_maquinaria": meta.get("maquinaria") or "",
        "form_tractor": meta.get("tractor") or "",
        "cuarteles": _libro_cuarteles(demo),
        "especies": _libro_especies(demo),
        "productos_stock": productos,
        "prod_sel": prod_sel,
        "stock_info": stock_info,
        "ing_def": ing_def,
        "phi_def": phi_def,
        "pppl_ok": demo.producto_pppl_aprobado(conn, prod_sel) if prod_sel else False,
        "unidades_dosis": UNIDADES_DOSIS,
        "maquinaria_opts": _opciones_maquinaria(conn, TIPOS_MAQUINARIA_APLICACION),
        "tractor_opts": _opciones_maquinaria(conn, TIPOS_MAQUINARIA_TRACTOR, permitir_vacio=True),
        "lc_car": car_rows,
        "lc_car_raw": car,
        "reabrir_n_app": _reabrir_n_app_ctx(demo, conn),
        "copiado_desde_n_app": session.get("lc_copiado_desde_n_app"),
        "rebaje_bodega_lc": is_concepcion_tenant() and _tenant_slug_lc(demo) != "espino",
    }


def _historial(demo, conn) -> dict:
    from erp_maquinaria import enriquecer_columna_maquinaria

    hoy = hoy_demo(demo)
    fi = parse_date(request.args.get("desde"), hoy - timedelta(days=180))
    ff = parse_date(request.args.get("hasta"), hoy)
    cuartel = request.args.get("cuartel", "TODOS")
    q_prod = (request.args.get("q") or "").strip()
    q_app = (request.args.get("n_app") or "").strip()

    filtros = ["fecha BETWEEN ? AND ?"]
    params: list = [str(fi), str(ff)]
    if cuartel and cuartel != "TODOS":
        filtros.append("sector = ?")
        params.append(cuartel.upper())
    if q_prod:
        # Busca por nombre comercial o ingrediente activo (ej. "cobre" → Nordox, Agrocup, etc.)
        filtros.append(
            "(UPPER(COALESCE(producto,'')) LIKE ? OR UPPER(COALESCE(ingrediente,'')) LIKE ?)"
        )
        like = f"%{q_prod.upper()}%"
        params.extend([like, like])
    if q_app.isdigit():
        filtros.append("n_aplicacion = ?")
        params.append(int(q_app))
    else:
        # Por defecto oculta histórico archivado (planillas antiguas >= 10000)
        filtros.append("CAST(n_aplicacion AS INTEGER) < ?")
        params.append(_N_APP_HIST_MIN)

    where_sql = " AND ".join(filtros)
    query = f"""SELECT n_aplicacion, fecha, sector, especie, producto, lote_producto, ingrediente,
                       dosis, unidad_dosis, vol_total, gasto_total, aplicadores,
                       operador_certificado, maquina, tractor, fecha_viable
                FROM libro_campo WHERE {where_sql}
                ORDER BY CAST(n_aplicacion AS INTEGER) DESC, id ASC"""
    df = pd.read_sql_query(query, conn, params=params)
    pdf_url = None
    pdf_filename = "LIBRO_DE_CAMPO_LA_CONCEPCION.pdf"
    if df.empty:
        return {
            "historial_grupos": [],
            "historial_stats": {"eventos": 0, "productos": 0},
            "filtro_desde": fi.isoformat(),
            "filtro_hasta": ff.isoformat(),
            "filtro_cuartel": cuartel,
            "filtro_q": q_prod,
            "filtro_n_app": q_app,
            "cuarteles": ["TODOS"] + _libro_cuarteles(demo),
            "pdf_historial_url": pdf_url,
            "pdf_historial_filename": pdf_filename,
        }

    df = df.rename(columns={
        "n_aplicacion": "N° APP",
        "fecha": "FECHA",
        "sector": "CUARTEL",
        "especie": "ESPECIE",
        "producto": "PRODUCTO",
        "lote_producto": "LOTE",
        "ingrediente": "ING ACTIVO",
        "dosis": "DOSIS 100L",
        "unidad_dosis": "UNIDAD",
        "vol_total": "VOL AGUA LT",
        "gasto_total": "TOTAL PROD",
        "aplicadores": "APLICADOR",
        "operador_certificado": "OP. CERT.",
        "maquina": "MAQUINARIA",
        "tractor": "TRACTOR",
        "fecha_viable": "FECHA VIABLE PHI",
    })
    df = enriquecer_columna_maquinaria(conn, df, "MAQUINARIA")
    df = enriquecer_columna_maquinaria(conn, df, "TRACTOR")
    if "OP. CERT." in df.columns:
        df["OP. CERT."] = df["OP. CERT."].apply(_fmt_op_cert)

    blob = demo.generar_pdf_libro_campo(df)
    if blob:
        pdf_url = pdf_download_url(store_pdf(blob, pdf_filename), pdf_filename)

    col_app = "N° APP"
    grupos = []
    for n_app, grp in df.groupby(col_app, sort=False):
        grp = grp.reset_index(drop=True)
        base = grp.iloc[0]
        productos = []
        for _, row in grp.iterrows():
            ing = str(row.get("ING ACTIVO", "") or "").strip()
            if not ing:
                try:
                    from erp_inventario_ia import resolver_ingrediente_activo

                    ing = resolver_ingrediente_activo(conn, row["PRODUCTO"]) or ""
                except Exception:
                    ing = ""
            productos.append(
                {
                    "producto": row["PRODUCTO"],
                    "lote": row.get("LOTE", ""),
                    "ing_activo": ing,
                    "dosis": demo.f_dosis_lc(row.get("DOSIS 100L", 0)),
                    "unidad": row.get("UNIDAD", ""),
                    "total": demo.f_cantidad(row.get("TOTAL PROD", 0)),
                    "phi": str(row.get("FECHA VIABLE PHI", ""))[:10],
                }
            )
        grupos.append(
            {
                "num": int(n_app),
                "fecha": str(base.get("FECHA", ""))[:10],
                "cuartel": base.get("CUARTEL", ""),
                "especie": base.get("ESPECIE", ""),
                "vol_agua": demo.f_decimal(base.get("VOL AGUA LT", 0)),
                "maquinaria": base.get("MAQUINARIA", ""),
                "tractor": base.get("TRACTOR", ""),
                "aplicador": base.get("APLICADOR", ""),
                "op_cert": base.get("OP. CERT.", "No"),
                "productos": productos,
            }
        )

    return {
        "historial_grupos": grupos,
        "historial_stats": {"eventos": df[col_app].nunique(), "productos": len(df)},
        "filtro_desde": fi.isoformat(),
        "filtro_hasta": ff.isoformat(),
        "filtro_cuartel": cuartel,
        "filtro_q": q_prod,
        "filtro_n_app": q_app,
        "cuarteles": ["TODOS"] + _libro_cuarteles(demo),
        "pdf_historial_url": pdf_url,
        "pdf_historial_filename": pdf_filename,
    }


def _modificar(demo, conn) -> dict:
    from erp_maquinaria import TIPOS_MAQUINARIA_APLICACION, TIPOS_MAQUINARIA_TRACTOR

    df_mod = pd.read_sql_query(
        """SELECT n_aplicacion, fecha, sector,
                  GROUP_CONCAT(producto, ' + ') AS productos,
                  COUNT(*) AS n_prod
           FROM libro_campo
           GROUP BY n_aplicacion, fecha, sector
           ORDER BY n_aplicacion DESC""",
        conn,
    )
    eventos = []
    for _, r in df_mod.iterrows():
        eventos.append(
            {
                "n_app": int(r["n_aplicacion"]),
                "label": (
                    f"{int(r['n_aplicacion']):05d} | {r['fecha']} | {r['sector']} | "
                    f"{r['productos']} ({int(r['n_prod'])} prod.)"
                ),
            }
        )

    edit_app = None
    edit_linea = None
    lineas: list = []
    if eventos:
        app_sel = request.args.get("n_app")
        if app_sel and str(app_sel).isdigit():
            edit_app = int(app_sel)
        else:
            edit_app = eventos[0]["n_app"]

        df_lineas = pd.read_sql_query(
            "SELECT * FROM libro_campo WHERE n_aplicacion = ? ORDER BY id",
            conn,
            params=(edit_app,),
        )
        lineas = []
        for _, r in df_lineas.iterrows():
            lineas.append({"id": int(r["id"]), "producto": r["producto"], "label": f"ID {int(r['id'])} | {r['producto']}"})

        linea_sel = request.args.get("linea_id")
        if linea_sel and str(linea_sel).isdigit():
            lid = int(linea_sel)
        elif lineas:
            lid = lineas[0]["id"]
        else:
            lid = None

        if lid is not None:
            row = df_lineas[df_lineas["id"] == lid].iloc[0]
            u_d = str(row.get("unidad_dosis") or "")
            edit_linea = {
                "id": int(row["id"]),
                "n_app": edit_app,
                "fecha": str(row["fecha"])[:10],
                "sector": row["sector"],
                "especie": row["especie"],
                "producto": row["producto"],
                "lote": row.get("lote_producto") or "",
                "ingrediente": row.get("ingrediente") or "",
                "dosis": float(row.get("dosis") or 0),
                "unidad_dosis": u_d if u_d in UNIDADES_DOSIS else UNIDADES_DOSIS[0],
                "vol_total": float(row.get("vol_total") or 0),
                "gasto_total": float(row.get("gasto_total") or 0),
                "fecha_viable": str(row.get("fecha_viable") or row["fecha"])[:10],
                "aplicadores": row.get("aplicadores") or "",
                "maquina": row.get("maquina") or "",
                "tractor": row.get("tractor") or "",
            }

    return {
        "mod_eventos": eventos,
        "mod_lineas": lineas,
        "mod_edit": edit_linea,
        "mod_app_sel": edit_app,
        "cuarteles": _libro_cuarteles(demo),
        "especies": _libro_especies(demo),
        "unidades_dosis": UNIDADES_DOSIS,
        "maquinaria_opts": _opciones_maquinaria(conn, TIPOS_MAQUINARIA_APLICACION),
        "tractor_opts": _opciones_maquinaria(conn, TIPOS_MAQUINARIA_TRACTOR, permitir_vacio=True),
    }


def _desfase(demo, conn) -> dict:
    hoy = hoy_demo(demo)
    fi = parse_date(request.args.get("desde"), hoy - timedelta(days=90))
    ff = parse_date(request.args.get("hasta"), hoy)
    try:
        dias_v = int(request.args.get("ventana", "14"))
    except ValueError:
        dias_v = 14
    dias_v = max(1, min(60, dias_v))

    df_lc_sin, df_bod_sin = demo._calcular_desfaces_lc_bodega(conn, fi, ff, dias_v)
    lc_rows = df_lc_sin.fillna("").to_dict(orient="records") if not df_lc_sin.empty else []
    bod_rows = df_bod_sin.fillna("").to_dict(orient="records") if not df_bod_sin.empty else []

    return {
        "desfase_lc_rows": lc_rows,
        "desfase_bod_rows": bod_rows,
        "desfase_ok": len(lc_rows) == 0 and len(bod_rows) == 0,
        "filtro_desde": fi.isoformat(),
        "filtro_hasta": ff.isoformat(),
        "ventana_dias": dias_v,
    }


def _post_agregar_producto(demo, conn) -> dict:
    _guardar_evento_meta(demo, request.form)
    prod = (request.form.get("producto") or "").strip()
    if not prod:
        return {"ok": False, "msg": "Seleccione un producto con stock en bodega."}
    if not demo.producto_pppl_aprobado(conn, prod):
        return {"ok": False, "msg": "Producto no autorizado en PPPL. Regístrelo en GlobalGAP o Bodega."}
    try:
        dos_base = float(request.form.get("dosis") or 0)
        total_prod = float(request.form.get("gasto_total") or 0)
        dias_car = int(request.form.get("dias_car") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Valores numéricos inválidos."}

    from erp_inventario_ia import resolver_ingrediente_activo

    um_prod = demo._um_producto_inventario(conn, prod)
    car = session.get(CAR_KEY, [])
    car.append(
        {
            "producto": prod,
            "lote_producto": (request.form.get("lote") or "").strip(),
            "ingrediente": resolver_ingrediente_activo(conn, prod) or (request.form.get("ingrediente") or "").strip(),
            "dosis": dos_base,
            "unidad_dosis": request.form.get("unidad_dosis") or UNIDADES_DOSIS[0],
            "gasto_total": total_prod,
            "um_gasto": um_prod,
            "dias_car": dias_car,
        }
    )
    session[CAR_KEY] = car
    return {"ok": True, "msg": f"Producto {prod} agregado al evento."}


def _post_guardar_evento(demo, conn) -> dict:
    car = session.get(CAR_KEY, [])
    if not car:
        return {"ok": False, "msg": "Agregue al menos un producto al evento."}
    maquinaria = (request.form.get("maquinaria") or "").strip()
    aplicador = (request.form.get("aplicador") or "").strip()
    try:
        total_agua = float(request.form.get("vol_agua") or 0)
    except (TypeError, ValueError):
        total_agua = 0
    if not maquinaria:
        return {"ok": False, "msg": "Seleccione la maquinaria / nebulizador."}
    if not aplicador:
        return {"ok": False, "msg": "Ingrese el nombre del aplicador."}
    if total_agua <= 0:
        return {"ok": False, "msg": "Ingrese el volumen total de agua aplicada."}

    fe_app = parse_date(request.form.get("fecha"), hoy_demo(demo))
    cuarteles = _libro_cuarteles(demo)
    especies = _libro_especies(demo)
    huerto = (request.form.get("cuartel") or "").strip() or (cuarteles[0] if cuarteles else "")
    if _tenant_slug_lc(demo) == "espino":
        allowed = {c.upper() for c in cuarteles}
        if huerto.upper() not in allowed:
            return {"ok": False, "msg": "Seleccione una variedad válida (sector)."}
    especie = request.form.get("especie") or (especies[0] if especies else "")
    op_cert = request.form.get("op_cert") == "1"
    tractor = (request.form.get("tractor") or "").strip()

    rebaje_espino = _tenant_slug_lc(demo) == "espino"
    rebaje_lc = is_concepcion_tenant() and not rebaje_espino
    rebaje_lc_omitido_copia = False
    copiado_desde = session.get("lc_copiado_desde_n_app")
    if rebaje_lc and copiado_desde:
        try:
            n_src = int(copiado_desde)
        except (TypeError, ValueError):
            n_src = 0
        if n_src and _lineas_aplicacion(conn, n_src):
            rebaje_lc = False
            rebaje_lc_omitido_copia = True
    if rebaje_espino:
        from demo_web.services.native import espino_bodega

        for item in car:
            ok_bod, msg_bod, _, _, _ = espino_bodega.validar_salida_bodega(
                demo,
                conn,
                float(item.get("gasto_total") or 0),
                producto=str(item.get("producto") or ""),
            )
            if not ok_bod:
                return {"ok": False, "msg": msg_bod}
    slug = tenant_slug() or _tenant_slug_lc(demo)

    if rebaje_lc and slug == "concepcion":
        try:
            saved = guardar_aplicacion_lc(
                conn,
                demo,
                tenant_slug=slug,
                car=car,
                fe_app=fe_app,
                huerto=huerto,
                especie=especie,
                total_agua=total_agua,
                aplicador=aplicador,
                op_cert=op_cert,
                maquinaria=maquinaria,
                tractor=tractor,
                n_app_fn=_siguiente_n_aplicacion,
                n_orden_fn=_siguiente_n_orden,
                rebaje_bodega=rebaje_lc,
                rebaje_omitido_copia=rebaje_lc_omitido_copia,
                copiado_desde=int(copiado_desde) if copiado_desde else None,
            )
        except LcAplicacionError as exc:
            return {"ok": False, "msg": exc.msg}
        n_app = saved.n_app
        wx = saved.wx
        prods_txt = ", ".join(i["producto"] for i in car)
        demo.registrar_accion("LIBRO CAMPO", f"App N°{n_app} · {huerto} · {prods_txt}")
        session[UNDO_KEY] = n_app
        session[CAR_KEY] = []
        session.pop(META_KEY, None)
        session.pop("lc_copiado_desde_n_app", None)
        msg = f"Aplicación N° {n_app:05d} guardada en Libro de Campo"
        if saved.rebaje_bodega:
            msg += ". Bodega rebajada automáticamente."
        elif saved.rebaje_omitido_copia and saved.copiado_desde:
            msg += (
                f". Bodega no se rebajó de nuevo (copia desde App N° {saved.copiado_desde:05d}; "
                "la salida original sigue vigente)."
            )
        if wx:
            msg += f" (clima {fe_app.isoformat()}: T° {wx.get('t_max')} / {wx.get('t_min')} · HR {wx.get('hr_pct')}% · viento {wx.get('viento_kmh')} km/h)"
        msg += " — visible en planilla GlobalGAP."
        return {"ok": True, "msg": msg}

    if rebaje_espino:
        slug = tenant_slug() or "espino"
        try:
            from demo_web.services.espino_aplicacion_service import (
                EspinoAplicacionError,
                guardar_aplicacion_espino,
            )

            saved = guardar_aplicacion_espino(
                conn,
                demo,
                tenant_slug=slug,
                car=car,
                fe_app=fe_app,
                especie=especie,
                total_agua=total_agua,
                aplicador=aplicador,
                op_cert=op_cert,
                maquinaria=maquinaria,
                tractor=tractor,
                n_app_fn=_siguiente_n_aplicacion,
                n_orden_fn=lambda c: _siguiente_n_orden(c, huerto),
            )
            n_app = saved.n_app
        except EspinoAplicacionError as exc:
            return {"ok": False, "msg": exc.msg}
    else:
        n_app = _siguiente_n_aplicacion(conn)
        n_orden = _siguiente_n_orden(conn, huerto)

        for item in car:
            demo._insertar_linea_libro_campo(
                conn,
                fe_app,
                n_app,
                huerto,
                especie,
                item,
                total_agua,
                aplicador,
                op_cert,
                maquinaria,
                tractor,
                n_orden=n_orden,
            )

    from demo_web.services.libro_campo_gap import enriquecer_aplicacion_globalgap

    wx = enriquecer_aplicacion_globalgap(
        conn,
        n_app,
        fe_app,
        huerto,
        especie,
        car,
        op_cert=op_cert,
    )
    conn.commit()
    prods_txt = ", ".join(i["producto"] for i in car)
    if rebaje_espino:
        demo.registrar_accion("LIBRO CAMPO ESPINO", f"App N°{n_app} · {huerto} · {prods_txt}")
    else:
        demo.registrar_accion("LIBRO CAMPO", f"App N°{n_app} · {huerto} · {prods_txt}")
        session["lc_alerta_bodega"] = {
            "n_app": n_app,
            "huerto": huerto,
            "productos": list(car),
        }
    session[UNDO_KEY] = n_app
    session[CAR_KEY] = []
    session.pop(META_KEY, None)
    session.pop("lc_copiado_desde_n_app", None)
    msg = f"Aplicación N° {n_app:05d} guardada en Libro de Campo"
    if rebaje_espino:
        msg += ". Bodega rebajada automáticamente."
    if wx:
        msg += f" (clima {fe_app.isoformat()}: T° {wx.get('t_max')} / {wx.get('t_min')} · HR {wx.get('hr_pct')}% · viento {wx.get('viento_kmh')} km/h)"
    if not rebaje_espino:
        msg += " — visible en planilla GlobalGAP."
    return {"ok": True, "msg": msg}


def _copiar_aplicacion_a_ingreso(demo, conn, n_app: int) -> dict:
    rows = _lineas_aplicacion(conn, n_app)
    if not rows:
        return {"ok": False, "msg": "No hay líneas guardadas para esa aplicación."}
    car, meta = _car_y_meta_desde_lineas(rows)
    session[CAR_KEY] = car
    session[META_KEY] = meta
    session.pop(UNDO_KEY, None)
    session["lc_copiado_desde_n_app"] = int(n_app)
    siguiente = _siguiente_n_aplicacion(conn)
    demo.registrar_accion("LIBRO CAMPO", f"Copiar ingreso desde App N°{n_app}")
    return {
        "ok": True,
        "msg": (
            f"Aplicación N° {n_app:05d} copiada al ingreso "
            f"(al guardar obtendrá N° {siguiente:05d}). "
            "El registro original permanece en el historial; bodega no se descontará otra vez."
        ),
        "extra": {"sec": "ingreso"},
    }


def _post_copiar_aplicacion_ingreso(demo, conn) -> dict:
    try:
        n_app = int(request.form.get("n_app") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "N° de aplicación inválido."}
    if n_app < 1:
        return {"ok": False, "msg": "Indique el N° de aplicación a copiar."}
    return _copiar_aplicacion_a_ingreso(demo, conn, n_app)


def _post_descartar_borrador(demo, conn) -> dict:
    session.pop(CAR_KEY, None)
    session.pop(META_KEY, None)
    session.pop("lc_copiado_desde_n_app", None)
    session.pop(UNDO_KEY, None)
    demo.registrar_accion("LIBRO CAMPO", "Descartar borrador ingreso")
    return {
        "ok": True,
        "msg": "Borrador descartado. Las aplicaciones guardadas en historial no cambiaron.",
        "extra": {"sec": "historial"},
    }


def _post_reabrir_aplicacion(demo, conn) -> dict:
    try:
        n_app = int(request.form.get("n_app") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "N° de aplicación inválido."}
    ultima = _ultima_n_aplicacion(conn)
    if not ultima or n_app != ultima:
        return {
            "ok": False,
            "msg": "Solo puede reabrir la última aplicación registrada (mayor N° de orden).",
        }
    slug = tenant_slug() or _tenant_slug_lc(demo)
    if slug == "concepcion" and is_concepcion_tenant() and _tenant_slug_lc(demo) != "espino":
        try:
            rows, rev_info, omitidas_prods = reabrir_aplicacion_lc(
                conn,
                demo,
                tenant_slug=slug,
                n_app=n_app,
                lineas_fn=_lineas_aplicacion,
            )
        except LcAplicacionError as exc:
            return {"ok": False, "msg": exc.msg}
        car, meta = _car_y_meta_desde_lineas(rows)
        omitidas = [{"lc": {"producto": p}, "skipped": True, "reason": "sin_movimiento"} for p in omitidas_prods]
    else:
        rows = _lineas_aplicacion(conn, n_app)
        if not rows:
            return {"ok": False, "msg": "No hay líneas guardadas para esa aplicación."}
        car, meta = _car_y_meta_desde_lineas(rows)
        rev_info = []
        if is_concepcion_tenant() and _tenant_slug_lc(demo) != "espino":
            rev_info = revertir_salidas_lineas_libro(conn, rows)
        conn.execute("DELETE FROM libro_campo WHERE n_aplicacion=?", (n_app,))
        conn.commit()
        omitidas = []
    session[CAR_KEY] = car
    session[META_KEY] = meta
    session.pop(UNDO_KEY, None)
    demo.registrar_accion("LIBRO CAMPO", f"Reabrir borrador App N°{n_app}")
    if not omitidas:
        omitidas = [r for r in rev_info if r.get("skipped") and r.get("reason") == "sin_movimiento"]
    msg = (
        f"Aplicación N° {n_app:05d} reabierta en ingreso. "
        "Revise productos y use «Validar y guardar» solo cuando termine."
    )
    if omitidas:
        prods = ", ".join(
            str((r.get("lc") or {}).get("producto") or "?") for r in omitidas
        )
        msg += (
            f" Atención: no se encontró salida bodega para revertir ({prods}); "
            "revise stock en Bodega si corresponde."
        )
    return {"ok": True, "msg": msg, "extra": {"sec": "ingreso"}}


def _post_editar_linea(demo, conn) -> dict:
    if not demo.es_admin():
        return {"ok": False, "msg": "Requiere perfil admin."}
    if not _check_master(demo, request.form.get("clave_maestra")):
        return {"ok": False, "msg": "Clave maestra incorrecta."}
    try:
        lid = int(request.form.get("linea_id") or 0)
        n_app = int(request.form.get("n_app") or 0)
        e_dosis = float(request.form.get("dosis") or 0)
        e_agua = float(request.form.get("vol_agua") or 0)
        e_total = float(request.form.get("gasto_total") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Datos inválidos."}
    e_maq = (request.form.get("maquinaria") or "").strip()
    if not e_maq:
        return {"ok": False, "msg": "Seleccione maquinaria desde la maestra."}
    conn.execute(
        """UPDATE libro_campo SET
           fecha=?, sector=?, especie=?, producto=?, lote_producto=?, ingrediente=?,
           dosis=?, unidad_dosis=?, vol_total=?, gasto_total=?, aplicadores=?,
           maquina=?, tractor=?, fecha_viable=?
           WHERE id=?""",
        (
            request.form.get("fecha") or str(hoy_demo(demo)),
            (request.form.get("cuartel") or "").upper(),
            (request.form.get("especie") or "").strip(),
            (request.form.get("producto") or "").strip(),
            (request.form.get("lote") or "").strip(),
            (request.form.get("ingrediente") or "").strip(),
            e_dosis,
            request.form.get("unidad_dosis") or UNIDADES_DOSIS[0],
            e_agua,
            e_total,
            (request.form.get("aplicador") or "").strip(),
            e_maq,
            (request.form.get("tractor") or "").strip(),
            request.form.get("fecha_viable") or str(hoy_demo(demo)),
            lid,
        ),
    )
    conn.commit()
    demo.registrar_accion("UPDATE LIBRO", f"App N°{n_app} línea {lid}")
    return {"ok": True, "msg": "Línea actualizada.", "extra": {"n_app": n_app, "linea_id": lid}}


def _post_eliminar_linea(demo, conn) -> dict:
    if not demo.es_admin():
        return {"ok": False, "msg": "Requiere perfil admin."}
    if not _check_master(demo, request.form.get("clave_maestra")):
        return {"ok": False, "msg": "Clave maestra incorrecta."}
    try:
        lid = int(request.form.get("linea_id") or 0)
        n_app = int(request.form.get("n_app") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Línea inválida."}
    slug = tenant_slug() or _tenant_slug_lc(demo)
    rev_msg = ""
    if slug == "concepcion" and is_concepcion_tenant() and _tenant_slug_lc(demo) != "espino":
        try:
            out = eliminar_linea_lc(
                conn,
                demo,
                tenant_slug=slug,
                linea_id=lid,
                n_app=n_app,
                fetch_linea_fn=_linea_libro_por_id,
            )
            res = out.get("revert") or {}
            if res.get("mov_id"):
                rev_msg = " Salida bodega revertida."
            elif res.get("skipped") and res.get("reason") == "sin_movimiento":
                rev_msg = f" Atención: no se encontró salida bodega para «{out.get('producto')}»."
        except LcAplicacionError as exc:
            return {"ok": False, "msg": exc.msg, "extra": {"n_app": n_app}}
    else:
        conn.execute("DELETE FROM libro_campo WHERE id = ?", (lid,))
        conn.commit()
    demo.registrar_accion("DELETE LIBRO LINEA", f"App N°{n_app} id {lid}")
    return {"ok": True, "msg": f"Línea eliminada.{rev_msg}", "extra": {"n_app": n_app}}


def _post_eliminar_evento(demo, conn) -> dict:
    if not demo.es_admin():
        return {"ok": False, "msg": "Requiere perfil admin."}
    if not _check_master(demo, request.form.get("clave_maestra")):
        return {"ok": False, "msg": "Clave maestra incorrecta."}
    try:
        n_app = int(request.form.get("n_app") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Evento inválido."}
    slug = tenant_slug() or _tenant_slug_lc(demo)
    if slug == "concepcion" and is_concepcion_tenant() and _tenant_slug_lc(demo) != "espino":
        try:
            result = eliminar_aplicacion_lc(
                conn,
                demo,
                tenant_slug=slug,
                n_app=n_app,
                lineas_fn=_lineas_aplicacion,
            )
        except LcAplicacionError as exc:
            return {"ok": False, "msg": exc.msg}
        demo.registrar_accion("DELETE LIBRO", f"App N°{n_app} completo")
        msg = f"Evento N° {n_app:05d} eliminado."
        if result.reverts and not result.omitidas_sin_mov:
            msg += " Salidas de bodega revertidas."
        elif result.omitidas_sin_mov:
            msg += f" Atención: salida bodega no revertida para: {', '.join(result.omitidas_sin_mov)}."
        return {"ok": True, "msg": msg}

    rows = _lineas_aplicacion(conn, n_app)
    rev_info: list[dict] = []
    if is_concepcion_tenant() and _tenant_slug_lc(demo) != "espino" and rows:
        rev_info = revertir_salidas_lineas_libro(conn, rows)
    conn.execute("DELETE FROM libro_campo WHERE n_aplicacion = ?", (n_app,))
    conn.commit()
    demo.registrar_accion("DELETE LIBRO", f"App N°{n_app} completo")
    msg = f"Evento N° {n_app:05d} eliminado."
    omitidas = [r for r in rev_info if r.get("skipped") and r.get("reason") == "sin_movimiento"]
    if rev_info and not omitidas:
        msg += " Salidas de bodega revertidas."
    elif omitidas:
        prods = ", ".join(str((r.get("lc") or {}).get("producto") or "?") for r in omitidas)
        msg += f" Atención: salida bodega no revertida para: {prods}."
    return {"ok": True, "msg": msg}


def gather_libro_campo(user_email: str, user_rol: str) -> dict:
    demo = get_demo_module()
    bind_user_session(user_email, user_rol)
    secciones = _secciones(demo)
    sec = request.args.get("sec", "historial")
    if sec not in {k for k, _ in secciones}:
        sec = "historial"

    conn = demo.conectar_db()
    try:
        ctx: dict = {
            "secciones": secciones,
            "sec_activa": sec,
            "es_admin": demo.es_admin(),
            **_pop_alertas(),
        }
        if sec == "historial":
            ctx.update(_historial(demo, conn))
        elif sec == "ingreso":
            ctx.update(_ingreso(demo, conn))
        elif sec == "desfase":
            ctx.update(_desfase(demo, conn))
        elif sec in _SEC_PROGRAMA:
            ctx.update(_programa_ctx(_SEC_PROGRAMA[sec]))
        elif sec == "modificar":
            ctx.update(_modificar(demo, conn))
        return ctx
    finally:
        conn.close()


def view(user_email: str, user_rol: str):
    demo = get_demo_module()
    bind_user_session(user_email, user_rol)

    if request.method == "GET" and request.args.get("clima") == "1":
        from demo_web.services.weather import fetch_daily_weather

        fecha = parse_date(request.args.get("fecha"), hoy_demo(demo))
        sector = (request.args.get("cuartel") or request.args.get("sector") or "").strip() or None
        wx = fetch_daily_weather(fecha, sector)
        if not wx:
            return jsonify({"ok": False, "msg": "No se pudo obtener clima para la fecha indicada."}), 502
        return jsonify({"ok": True, **wx})

    if request.method == "POST":
        action = request.form.get("action", "")
        sec = request.form.get("sec") or request.args.get("sec", "ingreso")
        conn = demo.conectar_db()
        try:
            if action == "pop_producto":
                _guardar_evento_meta(demo, request.form)
                car = session.get(CAR_KEY, [])
                if car:
                    car.pop()
                    session[CAR_KEY] = car
                    flash("Último producto removido del evento.", "info")
                return _redirect_lc(sec="ingreso")
            handlers = {
                "agregar_producto": _post_agregar_producto,
                "guardar_evento": _post_guardar_evento,
                "copiar_aplicacion_ingreso": _post_copiar_aplicacion_ingreso,
                "descartar_borrador": _post_descartar_borrador,
                "reabrir_aplicacion": _post_reabrir_aplicacion,
                "editar_linea": _post_editar_linea,
                "eliminar_linea": _post_eliminar_linea,
                "eliminar_evento": _post_eliminar_evento,
            }
            fn = handlers.get(action)
            if fn:
                result = fn(demo, conn)
                flash(result["msg"], "success" if result["ok"] else "danger")
                extra = {"sec": sec}
                extra.update(result.get("extra") or {})
                if action == "agregar_producto" and request.form.get("producto"):
                    extra["prod"] = request.form.get("producto")
                return _redirect_lc(**extra)
        finally:
            conn.close()

    if request.method == "GET":
        copiar_raw = (request.args.get("copiar_app") or "").strip()
        if copiar_raw and request.args.get("sec", "historial") == "ingreso":
            try:
                n_copiar = int(copiar_raw)
            except (TypeError, ValueError):
                flash("N° de aplicación inválido.", "danger")
            else:
                conn = demo.conectar_db()
                try:
                    result = _copiar_aplicacion_a_ingreso(demo, conn, n_copiar)
                    flash(result["msg"], "success" if result["ok"] else "danger")
                finally:
                    conn.close()
                if result.get("ok"):
                    return _redirect_lc(sec="ingreso")

    ctx = gather_libro_campo(user_email, user_rol)
    return render_template(
        "modules/libro_campo.html",
        page_title="Libro de Campo",
        active_key="Libro de Campo",
        title="📒 Libro de Campo",
        **ctx,
    )
