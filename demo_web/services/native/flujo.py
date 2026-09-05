from __future__ import annotations

import pandas as pd
from flask import render_template, send_file, url_for

from demo_web.services.demo_loader import bind_user_session, get_demo_module
from demo_web.services.flujo_excel import build_flujo_mensual_xlsx, filename_flujo_excel
from demo_web.services.module_runner import store_pdf
from demo_web.services.lc_excluir_espino import cuarteles_costos_lc, resumen_costos_para_flujo_lc
from demo_web.services.native._helpers import (
    hoy_demo,
    df_to_records,
    flujo_cell_classes,
    flujo_th_class,
    temporada_sel,
)
from demo_web.services.tenant_scope import cuarteles_oficiales, is_espino_tenant


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

        resumen_costos = resumen_costos_para_flujo_lc(conn, demo, nombre, fi, ff)
        cuarteles = cuarteles_costos_lc(cuarteles_oficiales(demo))
        df_flujo, df_cc, df_eg_cc, meta = armar_flujo_financiero(
            conn, nombre, fi, ff, hoy, cuarteles, resumen_costos,
            imputar_gastado_contable=is_espino_tenant(),
        )

        flujo_rows = []
        flujo_cols = []
        kpis = {}
        cuadre = {}
        gastado_flujo_info = ""
        pdf_flujo_url = None
        excel_flujo_url = None
        flujo_detalle_rows = []
        flujo_detalle_cols = ["MES", "Teso. real", "Teso. proy. (EERR)", "RRHH real", "RRHH proy."]
        meta_info = ""
        caja_info = ""

        if df_flujo is not None and not df_flujo.empty:
            tot_ing = float(df_flujo["INGRESOS"].sum())
            tot_eg_real = float(df_flujo["EGRESOS_REAL"].sum())
            tot_eg_proy = float(df_flujo["EGRESOS_PROY"].sum())
            tot_eg_total = float(df_flujo["EGRESOS_REAL"].sum() + df_flujo["EGRESOS_PROY"].sum())
            tot_res = tot_ing - tot_eg_total
            if "EN_EERR" in df_flujo.columns:
                df_eerr = df_flujo[df_flujo["EN_EERR"].astype(bool)]
                if not df_eerr.empty:
                    ing_eerr = float(df_eerr["INGRESOS"].sum())
                    eg_eerr = float(df_eerr["EGRESOS_TOTAL"].sum())
                    eerr_final = float(df_eerr["EERR_ACUM"].iloc[-1])
                    margen_eerr = ing_eerr - eg_eerr
                else:
                    ing_eerr = tot_ing
                    eg_eerr = tot_eg_total
                    eerr_final = float(df_flujo["EERR_ACUM"].iloc[-1])
                    margen_eerr = tot_res
            else:
                ing_eerr = tot_ing
                eg_eerr = tot_eg_total
                eerr_final = float(df_flujo["EERR_ACUM"].iloc[-1])
                margen_eerr = tot_res
            total_gastado = float(meta.get("total_gastado", 0) or 0)
            total_ppto = float(meta.get("total_ppto", 0) or 0)
            saldo_ppto = float(meta.get("saldo_por_gastar_ppto", 0) or 0)
            cxp_val = float(meta.get("teso_cxp_bruto") or meta.get("teso_cxp_total") or 0)
            disponible_ppto = tot_ing - total_ppto
            kpis = {
                "ingresos": demo.f_peso(tot_ing),
                "egresos_total": demo.f_peso(tot_eg_total),
                "egresos_real": demo.f_peso(tot_eg_real),
                "gastado": demo.f_peso(total_gastado),
                "presupuesto": demo.f_peso(total_ppto),
                "saldo_ppto": demo.f_peso(saldo_ppto),
                "cxp": demo.f_peso(cxp_val),
                "egresos_proy": demo.f_peso(tot_eg_proy),
                "margen": demo.f_peso(margen_eerr),
                "disponible_ppto": demo.f_peso(disponible_ppto),
                "eerr": demo.f_peso(eerr_final),
            }
            cuadre = {
                "flujo_ok": abs(margen_eerr - eerr_final) < 1.0,
                "ppto_ok": abs(total_ppto - total_gastado - saldo_ppto) < 1.0,
            }
            gastado_flujo_info = ""
            if meta.get("gastado_contable_en_flujo", 0) > 0.01 and meta.get("mes_gastado_contable"):
                gastado_flujo_info = (
                    f"Presup. consumido ({demo.f_peso(meta['gastado_contable_en_flujo'])}) "
                    f"imputado como egreso real en {meta['mes_gastado_contable']}."
                )

            display_cols = [
                "MES", "INGRESOS", "RRHH SUELDOS", "TESO REAL", "TESO PROY",
                "EGRESOS REAL", "EGRESOS PROY", "EGRESOS TOTAL", "RESULTADO MES", "EERR ACUM",
            ]
            base_cols = [
                "MES", "INGRESOS", "RRHH", "TESO_REAL", "TESO_PROY",
                "EGRESOS_REAL", "EGRESOS_PROY", "EGRESOS_TOTAL", "RESULTADO_MES", "EERR_ACUM",
            ]
            if "CAJA_INICIAL" in df_flujo.columns and float(df_flujo["CAJA_INICIAL"].sum() or 0) > 0.01:
                display_cols = [
                    "MES", "INGRESOS", "CAJA INICIAL", "RRHH SUELDOS", "TESO REAL", "TESO PROY",
                    "EGRESOS REAL", "EGRESOS PROY", "EGRESOS TOTAL", "RESULTADO MES", "EERR ACUM",
                ]
                base_cols = [
                    "MES", "INGRESOS", "CAJA_INICIAL", "RRHH", "TESO_REAL", "TESO_PROY",
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
            excel_flujo_url = url_for("modules.flujo_excel", temp=nombre)

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
                    f"Saldo caja inicial ({demo.f_peso(meta['saldo_caja_inicial'])}) "
                    f"en columna aparte en {meta['mes_caja_aplicada']} "
                    f"(ingresos operacionales del mes: "
                    f"{demo.f_peso(meta.get('ingresos_flujo_mes_caja', 0))}). "
                    f"Cargado en Administración → Ingresos flujo."
                )
                caja_info = f"{caja_info} {_extra}".strip() if caja_info else _extra

            meta_info = (
                f"Presupuesto (Costos): {demo.f_peso(total_ppto)} = "
                f"consumido {demo.f_peso(total_gastado)} + por gastar {demo.f_peso(saldo_ppto)} · "
                f"CxP: {demo.f_peso(cxp_val)} · Egresos proy.: {demo.f_peso(tot_eg_proy)}."
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
            "cuadre": cuadre,
            "gastado_flujo_info": gastado_flujo_info if kpis else "",
            "pdf_flujo_url": pdf_flujo_url,
            "excel_flujo_url": excel_flujo_url,
            "sin_datos": df_flujo is None or df_flujo.empty,
        }
    finally:
        conn.close()


def export_flujo_excel(user_email: str, user_rol: str):
    """Descarga planilla Excel del flujo mensual (fórmulas en totales y columnas derivadas)."""
    from io import BytesIO

    demo = get_demo_module()
    bind_user_session(user_email, user_rol)
    nombre, fi, ff = temporada_sel(demo)
    hoy = hoy_demo(demo)
    conn = demo.conectar_db()
    try:
        from erp_flujo_financiero import armar_flujo_financiero

        resumen_costos = resumen_costos_para_flujo_lc(conn, demo, nombre, fi, ff)
        cuarteles = cuarteles_costos_lc(cuarteles_oficiales(demo))
        df_flujo, _, _, _ = armar_flujo_financiero(
            conn, nombre, fi, ff, hoy, cuarteles, resumen_costos,
            imputar_gastado_contable=is_espino_tenant(),
        )
    finally:
        conn.close()

    if df_flujo is None or df_flujo.empty:
        from flask import abort

        abort(404)

    blob = build_flujo_mensual_xlsx(df_flujo, temporada=nombre, fi=fi, ff=ff)
    fname = filename_flujo_excel(nombre)
    return send_file(
        BytesIO(blob),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=fname,
    )


def view(user_email: str, user_rol: str):
    ctx = gather_flujo(user_email, user_rol)
    return render_template(
        "modules/flujo.html",
        page_title="Flujo financiero",
        active_key="Flujo financiero",
        title="📈 Flujo financiero",
        **ctx,
    )
