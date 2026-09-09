from __future__ import annotations

import pandas as pd
from flask import render_template, request, url_for

from demo_web.services.demo_loader import bind_user_session, get_demo_module
from demo_web.services.module_runner import store_pdf
from demo_web.services.native._helpers import (
    hoy_demo,
    avance_ppto_badge_tone,
    avance_ppto_tone,
    df_to_records,
    flujo_cell_classes,
    flujo_th_class,
    matriz_costos_to_records,
    prorrateo_rrhh,
    temporada_sel,
)
from demo_web.services.tenant_scope import cuarteles_oficiales


def _pdf_matriz_url(demo, show) -> str | None:
    if show is None or show.empty:
        return None
    fn = getattr(demo, "generar_pdf_matriz_costos", None)
    if fn:
        blob = fn(show, "MATRIZ DE COSTOS POR RUBRO Y CENTRO DE COSTO")
    else:
        blob = demo.generar_pdf_blob(
            show, "MATRIZ DE COSTOS POR RUBRO Y CENTRO DE COSTO", incluir_precios=False,
        )
    if not blob:
        return None
    token = store_pdf(blob, "costos_matriz.pdf")
    return url_for("modules.pdf_download", token=token)


def _rubros_filtro(demo) -> list[str]:
    rubros = ["Todas"]
    for r in getattr(demo, "RUBROS_MATRIZ_COSTOS", []):
        if r != "Ajustes" or demo.es_admin():
            rubros.append(r)
    return rubros


def _avance_gasto_ppto_resumen(demo, matriz: pd.DataFrame) -> dict:
    """Totales globales gasto/ppto + métricas por CC para dona en Resumen."""
    gasto = 0.0
    ppto = 0.0
    filas: list[dict] = []
    if matriz is not None and not matriz.empty:
        tg = matriz[matriz["Rubro"] == "TOTAL GASTO"]
        pp = matriz[matriz["Rubro"] == "PRESUPUESTO"]
        if "TOTAL" in matriz.columns:
            if not tg.empty:
                gasto = float(tg.iloc[0].get("TOTAL", 0) or 0)
            if not pp.empty:
                ppto = float(pp.iloc[0].get("TOTAL", 0) or 0)
        skip = {"Rubro", "TOTAL", "% Total"}
        cc_cols = [c for c in matriz.columns if c not in skip]
        # Preferir orden oficial de cuarteles si existe.
        oficiales = list(cuarteles_oficiales(demo) or [])
        if oficiales:
            ordered = [c for c in oficiales if c in cc_cols]
            ordered += [c for c in cc_cols if c not in ordered]
            cc_cols = ordered
        for cc in cc_cols:
            g = float(tg.iloc[0].get(cc, 0) or 0) if not tg.empty else 0.0
            p = float(pp.iloc[0].get(cc, 0) or 0) if not pp.empty else 0.0
            if p > 0:
                pct_cc = round(100.0 * g / p, 1)
                disponible_cc = max(0.0, p - g)
                if pct_cc >= 100:
                    estado = "over"
                elif pct_cc >= 80:
                    estado = "warn"
                else:
                    estado = "ok"
            else:
                pct_cc = 0.0
                disponible_cc = 0.0
                estado = "sin_ppto"
            filas.append(
                {
                    "nombre": cc,
                    "gasto": g,
                    "ppto": p,
                    "disponible": disponible_cc,
                    "pct": pct_cc,
                    "estado": estado,
                    "avance_tone": avance_ppto_tone(pct_cc) if p > 0 else "",
                    "badge_tone": avance_ppto_badge_tone(pct_cc) if p > 0 else "",
                    "gasto_fmt": demo.f_peso(g),
                    "ppto_fmt": demo.f_peso(p) if p > 0 else "—",
                    "disponible_fmt": demo.f_peso(disponible_cc) if p > 0 else "—",
                    "pct_fmt": f"{pct_cc:.1f}%" if p > 0 else "—",
                }
            )
        filas.sort(key=lambda x: (-x["gasto"], str(x["nombre"] or "").lower()))
    disponible = max(0.0, ppto - gasto) if ppto > 0 else 0.0
    pct = round(100.0 * gasto / ppto, 1) if ppto > 0 else 0.0
    tone = avance_ppto_tone(pct) if ppto > 0 else ""
    return {
        "gasto": gasto,
        "ppto": ppto,
        "disponible": disponible,
        "pct": pct,
        "tiene_presupuesto": ppto > 0,
        "gasto_fmt": demo.f_peso(gasto),
        "ppto_fmt": demo.f_peso(ppto) if ppto > 0 else "—",
        "disponible_fmt": demo.f_peso(disponible) if ppto > 0 else "—",
        "pct_fmt": f"{pct:.1f}%" if ppto > 0 else "—",
        "avance_tone": tone,
        "filas": filas,
    }


def _filtrar_movimientos(demo, df_det: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """Filtra/ordena movimientos de CC. Fecha debe ser datetime (no string dd-mm-YYYY)."""
    q = (request.args.get("det_q") or "").strip()
    rubro = request.args.get("det_rubro") or "Todas"
    orden = request.args.get("det_ord") or "Fecha ↓"
    df_show = df_det.copy()
    if q:
        qu = q.upper()
        df_show = df_show[
            df_show["Detalle"].astype(str).str.upper().str.contains(qu, na=False)
            | df_show["Rubro"].astype(str).str.upper().str.contains(qu, na=False)
        ]
    if rubro != "Todas":
        df_show = df_show[df_show["Rubro"] == rubro]
    # Ordenar por fecha real; si viene como texto dd-mm-YYYY, parsear
    fecha_sort = pd.to_datetime(df_show["Fecha"], dayfirst=True, errors="coerce")
    df_show = df_show.assign(_fecha_sort=fecha_sort)
    if orden == "Fecha ↑":
        df_show = df_show.sort_values("_fecha_sort", ascending=True)
    elif orden == "Monto ↓":
        df_show = df_show.sort_values("Monto", ascending=False)
    elif orden == "Monto ↑":
        df_show = df_show.sort_values("Monto", ascending=True)
    else:
        df_show = df_show.sort_values("_fecha_sort", ascending=False)
    df_show = df_show.drop(columns=["_fecha_sort"])
    total_fil = float(df_show["Monto"].sum()) if not df_show.empty else 0.0
    caption = f"{len(df_show)} movimientos · Total filtrado: {demo.f_peso(total_fil)}"
    return df_show, caption


def gather_costos(user_email: str, user_rol: str) -> dict:
    demo = get_demo_module()
    bind_user_session(user_email, user_rol)
    nombre, fi, ff = temporada_sel(demo)
    hoy = hoy_demo(demo)
    es_vigente = fi <= hoy <= ff

    cuarteles = cuarteles_oficiales(demo)
    vistas = [("resumen", "📊 Resumen")] + [(c, c) for c in cuarteles]
    vista = request.args.get("vista", "resumen")
    if vista != "resumen" and vista not in cuarteles:
        vista = "resumen"

    conn = demo.conectar_db()
    try:
        prorr = prorrateo_rrhh(demo, conn)
        fi_cons, ff_cons = demo._rango_fechas_costos_consulta(conn, fi, ff, es_vigente) if es_vigente else (fi, ff)
        if es_vigente:
            matriz = demo._armar_matriz_costos_vista_b(
                conn, fi_cons, ff_cons, cuarteles, prorr, nombre,
                fi_rrhh=fi, ff_rrhh=ff,
            )
            det_fi, det_ff = fi_cons, ff_cons
        else:
            matriz = demo._armar_matriz_costos_vista_b(
                conn, fi, ff, cuarteles, prorr, nombre,
            )
            det_fi, det_ff = fi, ff

        matriz_cols, matriz_rows = [], []
        detalle_cols, detalle_rows = [], []
        mov_cols, mov_rows = [], []
        cc_meta = {}
        resumen_avance = {
            "gasto": 0.0,
            "ppto": 0.0,
            "disponible": 0.0,
            "pct": 0.0,
            "tiene_presupuesto": False,
            "gasto_fmt": "—",
            "ppto_fmt": "—",
            "disponible_fmt": "—",
            "pct_fmt": "—",
            "avance_tone": "",
            "filas": [],
        }
        pdf_matriz_url = None
        caption = ""
        mov_caption = ""
        rubros_filtro = _rubros_filtro(demo)
        det_rubro = request.args.get("det_rubro") or "Todas"
        if det_rubro not in rubros_filtro:
            det_rubro = "Todas"

        if es_vigente:
            ext_txt = ""
            if fi_cons < fi:
                ext_txt = (
                    f" Incluye movimientos desde {fi_cons.strftime('%d-%m-%Y')} "
                    f"(anteriores al inicio formal de temporada {fi.strftime('%d-%m-%Y')})."
                )
            caption = (
                "Matriz de costos — temporada vigente. Clasifique gastos históricos en "
                "Compras → Historial → Corregir (tipo de gasto). "
                f"Operativos hasta {ff_cons.strftime('%d-%m-%Y')}; RRHH desde liquidaciones."
                + ext_txt
            )
        else:
            caption = (
                f"Matriz de costos — temporada {nombre} ({fi.strftime('%d-%m-%Y')} al {ff.strftime('%d-%m-%Y')}). "
                "RRHH: suma de liquidaciones del período."
            )

        total_general = 0.0
        if matriz is not None and not matriz.empty:
            total_general = demo._total_gasto_general_matriz(matriz)

        if matriz is not None and not matriz.empty:
            if vista == "resumen":
                show = demo._preparar_matriz_costos_resumen(matriz)
                matriz_cols, matriz_rows = matriz_costos_to_records(demo, show)
                pdf_matriz_url = _pdf_matriz_url(demo, show)
                resumen_avance = _avance_gasto_ppto_resumen(demo, matriz)
            else:
                gasto = demo._total_gasto_cc_desde_matriz(matriz, vista)
                ppto = demo._obtener_ppto_temporada(conn, nombre, vista)
                kg = demo._obtener_kg_estimado_temporada(conn, nombre, vista)
                meta = demo._calc_metricas_produccion_cc(gasto, ppto, kg)
                pct_total = (gasto / total_general * 100) if total_general > 0 else 0.0
                saldo = ppto - gasto if ppto > 0 else None
                avance_ppto = meta.get("avance", 0.0) if ppto > 0 else None
                avance_tone = ""
                saldo_kpi_cls = ""
                if avance_ppto is not None:
                    avance_tone = avance_ppto_tone(avance_ppto)
                if saldo is not None:
                    saldo_kpi_cls = "costos-saldo-kpi-neg" if saldo < 0 else "costos-saldo-kpi-pos"
                cc_meta = {
                    "cuartel": vista,
                    "gasto": demo.f_peso(gasto),
                    "ppto": demo.f_peso(ppto) if ppto > 0 else "—",
                    "kg": demo.f_decimal(kg) if kg else "—",
                    "usd_kg": demo._fmt_usd(meta.get("costo_usd_kg")) if meta.get("costo_usd_kg") else "—",
                    "meta_usd_kg": demo._fmt_usd(meta.get("meta_usd_kg")) if meta.get("meta_usd_kg") else "—",
                    "avance": demo._fmt_dashboard_avance_pct(meta.get("avance")),
                    "avance_ppto": f"{avance_ppto:.1f}%" if avance_ppto is not None else "—",
                    "avance_tone": avance_tone,
                    "participacion": f"{pct_total:.1f}%",
                    "saldo": demo.f_peso(saldo) if saldo is not None else "—",
                    "saldo_negativo": saldo is not None and saldo < 0,
                    "saldo_kpi_cls": saldo_kpi_cls,
                    "sin_ppto": ppto <= 0,
                    "sin_movimientos": gasto <= 0.5,
                }
                df_cc = demo._rubros_cc_desde_matriz(matriz, vista)
                if not df_cc.empty:
                    detalle_cols, detalle_rows = df_to_records(
                        df_cc.rename(columns={"Monto": "Monto"}),
                        {"Monto"},
                        demo,
                    )
                df_mov = demo._obtener_detalle_gastos_cc(
                    conn, vista, prorr, det_fi, det_ff, fi, ff,
                )
                if not df_mov.empty:
                    df_mov = df_mov.copy()
                    df_mov["Fecha"] = pd.to_datetime(df_mov["Fecha"], errors="coerce")
                    # Filtrar/ordenar con fecha real; formatear después
                    df_show, mov_caption = _filtrar_movimientos(demo, df_mov)
                    df_show = df_show.copy()
                    df_show["Fecha"] = df_show["Fecha"].dt.strftime("%d-%m-%Y")
                    mov_cols, mov_rows = df_to_records(df_show, {"Monto"}, demo)
                elif gasto <= 0.5:
                    cc_meta["sin_movimientos"] = True

        return {
            "temporadas": demo.TEMPORADAS_COSTOS,
            "temp_sel": nombre,
            "fi": fi.strftime("%d-%m-%Y"),
            "ff": ff.strftime("%d-%m-%Y"),
            "es_vigente": es_vigente,
            "vistas": vistas,
            "vista_activa": vista,
            "matriz_cols": matriz_cols,
            "matriz_rows": matriz_rows,
            "detalle_cols": detalle_cols,
            "detalle_rows": detalle_rows,
            "mov_cols": mov_cols,
            "mov_rows": mov_rows,
            "mov_caption": mov_caption,
            "cc_meta": cc_meta,
            "resumen_avance": resumen_avance,
            "caption": caption,
            "pdf_matriz_url": pdf_matriz_url,
            "rubros_filtro": rubros_filtro,
            "det_q": request.args.get("det_q") or "",
            "det_rubro": det_rubro,
            "det_ord": request.args.get("det_ord") or "Fecha ↓",
            "sin_datos": matriz is None or (isinstance(matriz, pd.DataFrame) and matriz.empty),
        }
    finally:
        conn.close()


def view(user_email: str, user_rol: str):
    ctx = gather_costos(user_email, user_rol)
    return render_template(
        "modules/costos.html",
        page_title="Costos",
        active_key="Costos",
        title="💰 Costos consolidados",
        **ctx,
    )
