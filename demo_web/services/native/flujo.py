from __future__ import annotations

import pandas as pd
from flask import render_template, url_for

from demo_web.services.demo_loader import bind_user_session, get_demo_module
from demo_web.services.module_runner import store_pdf
from demo_web.services.native._helpers import (
    hoy_demo,
    df_to_records,
    flujo_cell_classes,
    flujo_th_class,
    temporada_sel,
)


def gather_flujo(user_email: str, user_rol: str) -> dict:
    demo = get_demo_module()
    bind_user_session(user_email, user_rol)
    nombre, fi, ff = temporada_sel(demo)
    hoy = hoy_demo(demo)
    es_vigente = fi <= hoy <= ff

    conn = demo.conectar_db()
    try:
        from erp_flujo_financiero import (
            armar_flujo_financiero,
            cargar_ingresos_cc,
            cargar_notas_ingresos_cc,
            df_flujo_para_pdf,
            fila_total_flujo_mensual,
        )
        from erp_flujo_financiero import _mes_label

        resumen_costos = demo._resumen_costos_para_flujo(conn, nombre, fi, ff)
        df_flujo, df_cc, df_eg_cc, meta = armar_flujo_financiero(
            conn, nombre, fi, ff, hoy, demo.CUARTELES_OFICIALES, resumen_costos,
        )

        flujo_rows = []
        flujo_cols = []
        kpis = {}
        pdf_flujo_url = None
        flujo_detalle_rows = []
        flujo_detalle_cols = ["MES", "Teso. real", "Teso. proy. (EERR)", "RRHH real", "RRHH proy."]
        meta_info = ""
        caja_info = ""

        if df_flujo is not None and not df_flujo.empty:
            tot_ing = float(df_flujo["INGRESOS"].sum())
            tot_eg_real = float(df_flujo["EGRESOS_REAL"].sum())
            tot_eg_proy = float(df_flujo["EGRESOS_PROY"].sum())
            eerr_final = float(df_flujo["EERR_ACUM"].iloc[-1])
            kpis = {
                "ingresos": demo.f_peso(tot_ing),
                "gastado": demo.f_peso(meta.get("total_gastado", 0)),
                "cxp": demo.f_peso(meta.get("teso_cxp_total", tot_eg_real)),
                "egresos_proy": demo.f_peso(tot_eg_proy),
                "eerr": demo.f_peso(eerr_final),
            }

            display_cols = [
                "MES", "INGRESOS", "RRHH SUELDOS", "TESO REAL", "TESO PROY",
                "EGRESOS REAL", "EGRESOS PROY", "EGRESOS TOTAL", "RESULTADO MES", "EERR ACUM",
            ]
            base_cols = [
                "MES", "INGRESOS", "RRHH", "TESO_REAL", "TESO_PROY",
                "EGRESOS_REAL", "EGRESOS_PROY", "EGRESOS_TOTAL", "RESULTADO_MES", "EERR_ACUM",
            ]
            n_meses = len(df_flujo)
            df_show = df_flujo[base_cols].copy()
            df_show = pd.concat(
                [df_show, pd.DataFrame([fila_total_flujo_mensual(df_flujo)])],
                ignore_index=True,
            )
            flujo_cols = display_cols

            for i, row in df_show.iterrows():
                cells = {}
                classes = {}
                is_total = i >= n_meses
                for disp, base in zip(display_cols, base_cols):
                    raw = row[base]
                    if base == "MES":
                        cells[disp] = str(raw)
                    else:
                        cells[disp] = demo.f_peso(float(raw or 0))
                    classes[disp] = flujo_cell_classes(i, disp, n_meses, df_flujo, raw)
                flujo_rows.append({"cells": cells, "classes": classes, "is_total": is_total})

            for _, row in df_flujo.iterrows():
                flujo_detalle_rows.append({
                    "MES": row["MES"],
                    "Teso. real": demo.f_peso(row["TESO_REAL"]),
                    "Teso. proy. (EERR)": demo.f_peso(row["TESO_PROY"]),
                    "RRHH real": demo.f_peso(row["RRHH_REAL"]),
                    "RRHH proy.": demo.f_peso(row["RRHH_PROY"]),
                    "_cls_teso_proy": "flujo-cell-proy" if float(row["TESO_PROY"] or 0) > 0.01 else "",
                    "_cls_rrhh_proy": "flujo-cell-proy" if float(row["RRHH_PROY"] or 0) > 0.01 else "",
                })

            blob = demo.generar_pdf_blob(
                df_flujo_para_pdf(df_flujo),
                f"FLUJO FINANCIERO - {nombre}",
                incluir_precios=False,
            )
            if blob:
                token = store_pdf(blob, f"flujo_financiero_{nombre}.pdf")
                pdf_flujo_url = url_for("modules.pdf_download", token=token)

            if meta.get("meses_historial") or meta.get("mes_inicio_eerr"):
                ini = meta.get("mes_inicio_eerr") or meta.get("mes_inicio_proyeccion") or "el primer mes con ingresos"
                caja_info = (
                    f"EERR acumulado parte en {ini} (primer mes con ingresos), "
                    "para cuadrar con la vista que tenías ese mes. "
                    "Los meses previos se muestran como referencia (RRHH) sin arrastrar ese déficit al EERR. "
                    f"Proyección desde {meta.get('mes_inicio_proyeccion') or 'el mes en curso'}."
                )
            if meta.get("saldo_caja_inicial", 0) > 0.01 and meta.get("mes_caja_aplicada"):
                _extra = (
                    f"El ingreso de {meta['mes_caja_aplicada']} incluye flujo proyectado "
                    f"({demo.f_peso(meta.get('ingresos_flujo_mes_caja', 0))}) + saldo caja inicial "
                    f"({demo.f_peso(meta['saldo_caja_inicial'])}), cargado en Administración → Ingresos flujo."
                )
                caja_info = f"{caja_info} {_extra}".strip() if caja_info else _extra

            meta_info = (
                f"Presupuesto (Costos): {demo.f_peso(meta.get('total_ppto', 0))} · "
                f"Gastado imputado: {demo.f_peso(meta.get('total_gastado', 0))} · "
                f"Saldo por gastar (suma CC): {demo.f_peso(meta.get('saldo_por_gastar_ppto', 0))} · "
                f"RRHH proy: {demo.f_peso(meta.get('rrhh_proy_asignado', 0))} · "
                f"TESO PROY (resto del saldo, desde {meta.get('mes_inicio_teso_proy_auto', 'hoy+2')}): "
                f"{demo.f_peso(meta.get('saldo_a_proyectar_teso_bruto', 0))} · "
                f"CxP (TESO REAL): {demo.f_peso(meta.get('teso_cxp_total', 0))}."
            )

        eg_cc_cols, eg_cc_rows = [], []
        if df_eg_cc is not None and not df_eg_cc.empty:
            money_eg = {c for c in df_eg_cc.columns if c != "CENTRO_COSTO"}
            eg_cc_cols, eg_cc_rows = df_to_records(df_eg_cc, money_eg, demo)

        ing_cc_cols, ing_cc_rows = [], []
        if df_cc is not None and not df_cc.empty:
            money_ing = {c for c in df_cc.columns if c != "CENTRO_COSTO"}
            ing_cc_cols, ing_cc_rows = df_to_records(df_cc, money_ing, demo)

        notas_rows = []
        notas_map = cargar_notas_ingresos_cc(conn, nombre)
        ing_map = cargar_ingresos_cc(conn, nombre)
        for (cc, anio, mes), nota in sorted(notas_map.items()):
            txt = str(nota or "").strip()
            if txt:
                notas_rows.append(
                    {
                        "centro_costo": cc,
                        "mes": _mes_label(anio, mes),
                        "ingreso": demo.f_peso(ing_map.get((cc, anio, mes), 0.0)),
                        "nota": txt,
                    }
                )

        return {
            "temporadas": demo.TEMPORADAS_COSTOS,
            "temp_sel": nombre,
            "fi": fi.strftime("%d-%m-%Y"),
            "ff": ff.strftime("%d-%m-%Y"),
            "es_vigente": es_vigente,
            "kpis": kpis,
            "flujo_cols": flujo_cols,
            "flujo_rows": flujo_rows,
            "flujo_th_class": flujo_th_class,
            "flujo_detalle_cols": flujo_detalle_cols,
            "flujo_detalle_rows": flujo_detalle_rows,
            "eg_cc_cols": eg_cc_cols,
            "eg_cc_rows": eg_cc_rows,
            "ing_cc_cols": ing_cc_cols,
            "ing_cc_rows": ing_cc_rows,
            "notas_rows": notas_rows,
            "meta_caption": meta_info,
            "caja_info": caja_info,
            "pdf_flujo_url": pdf_flujo_url,
            "sin_datos": df_flujo is None or df_flujo.empty,
        }
    finally:
        conn.close()


def view(user_email: str, user_rol: str):
    ctx = gather_flujo(user_email, user_rol)
    return render_template(
        "modules/flujo.html",
        page_title="Flujo financiero",
        active_key="Flujo financiero",
        title="📈 Flujo financiero",
        **ctx,
    )
