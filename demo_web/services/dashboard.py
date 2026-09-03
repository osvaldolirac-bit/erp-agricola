from __future__ import annotations

from dateutil.relativedelta import relativedelta

import pandas as pd

from demo_web.services.demo_loader import bind_user_session, get_demo_module
from demo_web.services.erp_loader import current_tenant, get_erp_app
from demo_web.services.native._helpers import avance_ppto_badge_tone, prorrateo_rrhh
from demo_web.services.tenant_scope import cuarteles_oficiales


def _dashboard_title() -> str:
    t = current_tenant() or {}
    slug = str(t.get("slug") or "").strip().lower()
    if slug == "espino":
        return "ERP EL ESPINO"
    nombre_erp = (t.get("nombre_erp") or "").strip()
    if nombre_erp:
        return nombre_erp.upper()
    if get_erp_app() == "concepcion":
        return "ERP AGRÍCOLA LA CONCEPCIÓN"
    return "ERP DEMO AGRÍCOLA"


def _demo():
    return get_demo_module()


def gather_dashboard(email: str, rol: str) -> dict:
    demo = _demo()
    bind_user_session(email, rol)
    conn = demo.conectar_db()
    try:
        alerta_rrhh = None
        fecha_sistema = demo.hora_chile()
        mes_act = fecha_sistema.strftime("%m")
        anio_act = fecha_sistema.year
        try:
            t_activos = pd.read_sql_query(
                "SELECT id FROM personal WHERE estado='Activo'", conn
            )
            imputados = pd.read_sql_query(
                f"""SELECT DISTINCT trabajador_id FROM pagos_rrhh
                    WHERE printf('%02d', CAST(mes AS INTEGER))='{mes_act}' AND anio={anio_act}""",
                conn,
            )
            faltan = len(t_activos) - len(imputados)
            if faltan > 0 and demo.hora_chile().day >= 28:
                alerta_rrhh = f"Faltan {faltan} trabajadores por imputar sueldos este mes."
        except Exception:
            pass

        ind = demo.obtener_indicadores()
        df_f = demo._cargar_facturas_pendientes_saldo(conn)
        df_p_c = pd.read_sql_query(
            "SELECT SUM(litros) as l FROM petroleo WHERE tipo='Carga' OR (tipo='Ajuste Manual' AND litros > 0)",
            conn,
        )
        df_p_s = pd.read_sql_query(
            "SELECT SUM(litros) as l FROM petroleo WHERE tipo='Salida' OR (tipo='Ajuste Manual' AND litros < 0)",
            conn,
        )
        saldo_pet = float(df_p_c["l"].fillna(0).iloc[0]) - abs(
            float(df_p_s["l"].fillna(0).iloc[0])
        )

        hoy = demo.hoy
        pdia = hoy.replace(day=1)
        dcrit = float(
            df_f[pd.to_datetime(df_f["fecha_vencimiento"]).dt.date < pdia]["saldo"].sum()
            if not df_f.empty
            else 0
        )
        vcount = len(df_f[pd.to_datetime(df_f["fecha_vencimiento"]).dt.date < hoy]) if not df_f.empty else 0

        kpis = {
            "deuda_total": demo.f_peso(df_f["saldo"].sum() if not df_f.empty else 0),
            "meses_anteriores": demo.f_peso(dcrit),
            "vencidas": f"{vcount} docs",
            "pendientes": len(df_f),
            "petroleo": f"{demo.f_decimal(saldo_pet)} L",
        }

        gastos_cc = []
        pagos_mes = []
        dfr_base, _ = demo._armar_dataframe_costos_dashboard(
            conn, cuarteles_oficiales(demo), prorrateo_rrhh(demo, conn)
        )
        if not dfr_base.empty:
            df_gastos = demo._build_dashboard_gastos_cc_df(conn, dfr_base)
            for _, row in df_gastos.iterrows():
                avance_raw = row.get("Avance %")
                avance = demo._fmt_dashboard_avance_pct(avance_raw)
                avance_tone = avance_ppto_badge_tone(
                    float(avance_raw) if avance_raw is not None else None
                )
                usd_raw = row.get("USD/kg")
                usd_tone = avance_ppto_badge_tone(
                    float(avance_raw) if usd_raw is not None and avance_raw is not None else None
                )
                cuartel = str(row["Cuartel"])
                gastos_cc.append(
                    {
                        "cuartel": cuartel,
                        "total": demo.f_peso(row["Total Acumulado"]),
                        "avance": avance,
                        "avance_tone": avance_tone,
                        "usd_kg": demo._fmt_usd(usd_raw) if usd_raw is not None else "—",
                        "usd_tone": usd_tone,
                        "total_row": cuartel.upper() == "TOTAL GENERAL",
                    }
                )

        base_mes = hoy.replace(day=1)
        n_meses = 6
        if not df_f.empty:
            fv_max = pd.to_datetime(df_f["fecha_vencimiento"], errors="coerce").max()
            if pd.notna(fv_max):
                ultimo = fv_max.to_pydatetime().replace(day=1)
                diff = (ultimo.year - base_mes.year) * 12 + (ultimo.month - base_mes.month) + 1
                n_meses = max(n_meses, diff)
        for i in range(n_meses):
            fp = base_mes + relativedelta(months=i)
            if df_f.empty:
                totalm = 0
            else:
                fv = pd.to_datetime(df_f["fecha_vencimiento"])
                totalm = df_f[(fv.dt.month == fp.month) & (fv.dt.year == fp.year)][
                    "saldo"
                ].sum()
            pagos_mes.append(
                {
                    "mes": fp.strftime("%B %Y").upper(),
                    "monto": demo.f_peso(totalm),
                    "vacio": float(totalm or 0) <= 0,
                }
            )

        dash_title = _dashboard_title()

        return {
            "alerta_rrhh": alerta_rrhh,
            "indicadores": ind,
            "kpis": kpis,
            "gastos_cc": gastos_cc,
            "pagos_mes": pagos_mes,
            "dash_title": dash_title,
        }
    finally:
        conn.close()
