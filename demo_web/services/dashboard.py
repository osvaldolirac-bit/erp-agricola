from __future__ import annotations

import sqlite3
from datetime import datetime

from dateutil.relativedelta import relativedelta

import pandas as pd

from demo_web.services.demo_loader import bind_user_session, get_demo_module
from demo_web.services.erp_loader import current_tenant, get_erp_app
from demo_web.tenants import tenant_nombre_erp
from demo_web.services.lc_query_scope import (
    ajustar_gastos_dashboard_excluir_espino_lc,
    cuarteles_operativos_lc,
    filtrar_df_facturas_espino_lc,
)
from demo_web.services.native._helpers import avance_ppto_badge_tone, prorrateo_rrhh
from demo_web.services.tenant_scope import cuarteles_oficiales


def _demo():
    return get_demo_module()


def _fmt_minutos_aviso(minutos: float) -> str:
    m = float(minutos or 0)
    if m <= 0:
        return ""
    total = int(round(m))
    if total < 60:
        return f"{total} min"
    horas, resto = divmod(total, 60)
    if resto:
        return f"{horas} h {resto} min"
    return f"{horas} h"


def _etiqueta_sector(nombre: str, alias: str, huerto: str, minutos: float) -> str:
    nom = (nombre or "Sector").strip()
    alias_n = (alias or "").strip()
    if alias_n and alias_n.casefold() != nom.casefold():
        etiqueta = f"{nom} — {alias_n}"
    else:
        etiqueta = nom
    partes = [etiqueta]
    cc = (huerto or "").strip()
    if cc:
        partes.append(cc)
    tiempo = _fmt_minutos_aviso(minutos)
    if tiempo:
        partes.append(tiempo)
    return " · ".join(partes)


def _inicio_programa(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace(" ", "T")[:19])
    except ValueError:
        return None


def alertas_riego_dashboard(conn) -> list[dict]:
    """Avisos de riego en el Dashboard de La Concepción.

    Ejecución, cola y pendientes de autorizar. El Espino no usa cola Hydra.
    """
    from demo_web.services.tenant_scope import is_concepcion_tenant

    if not is_concepcion_tenant():
        return []
    alertas: list[dict] = []
    try:
        alertas.extend(_alertas_cola_hydra(conn))
    except sqlite3.OperationalError:
        pass
    n_auth = _pendientes_autorizar(conn)
    if n_auth == 1:
        texto = "Hay 1 riego pendiente de autorizar."
    elif n_auth > 1:
        texto = f"Hay {n_auth} riegos pendientes de autorizar."
    else:
        texto = ""
    if texto:
        alertas.append(
            {"tipo": "autorizar", "clase": "dash-alerta-riego-auth", "texto": texto}
        )
    return alertas


def _pendientes_autorizar(conn) -> int:
    try:
        from demo_web.services.registro_riego import contar_pendientes

        return int(contar_pendientes(conn) or 0)
    except Exception:
        return 0


def _alertas_cola_hydra(conn) -> list[dict]:
    cola = conn.execute(
        """SELECT id, tipo, inicio_programa, estado
           FROM hydrawise_cola
           WHERE estado IN ('programado', 'en_ejecucion')
           ORDER BY id DESC LIMIT 1"""
    ).fetchone()
    if not cola:
        return []
    cola_id, tipo, inicio, _estado = cola
    items = conn.execute(
        """SELECT i.estado, i.minutos, z.nombre_hw, z.alias, z.huerto_cc, i.orden
           FROM hydrawise_cola_item i
           LEFT JOIN hydrawise_zona z ON z.relay_id = i.relay_id
           WHERE i.cola_id=?
           ORDER BY i.orden""",
        (int(cola_id),),
    ).fetchall()
    alertas: list[dict] = []
    en_vivo = [r for r in items if str(r[0] or "") in ("corriendo", "pausado")]
    en_vivo.sort(key=lambda r: (0 if str(r[0]) == "corriendo" else 1, int(r[5] or 0)))
    for estado, minutos, nombre, alias, huerto, _orden in en_vivo:
        pausa = str(estado) == "pausado"
        titulo = "Riego en pausa" if pausa else "Riego en ejecución"
        alertas.append(
            {
                "tipo": "pausa" if pausa else "ejecucion",
                "clase": "dash-alerta-riego-run",
                "texto": f"{titulo}: {_etiqueta_sector(nombre, alias, huerto, minutos)}.",
            }
        )
    espera = [r for r in items if str(r[0] or "") == "pendiente"]
    if espera:
        detalle = "; ".join(
            _etiqueta_sector(nombre, alias, huerto, minutos)
            for _estado, minutos, nombre, alias, huerto, _orden in espera
        )
        prefijo = "En cola"
        if str(tipo or "") == "programado" and not en_vivo:
            cuando = _inicio_programa(inicio)
            if cuando:
                prefijo = f"En cola, programa {cuando.strftime('%d/%m/%Y %H:%M')}"
        alertas.append(
            {
                "tipo": "cola",
                "clase": "dash-alerta-riego-cola",
                "texto": f"{prefijo}: {detalle}.",
            }
        )
    return alertas


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
        df_f = filtrar_df_facturas_espino_lc(df_f)
        if df_f is None:
            df_f = pd.DataFrame()
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
        cuarteles_full = list(cuarteles_oficiales(demo) or [])
        cuarteles_dash = cuarteles_operativos_lc(demo)
        dfr_base, _ = demo._armar_dataframe_costos_dashboard(
            conn, cuarteles_full, prorrateo_rrhh(demo, conn)
        )
        dfr_base = ajustar_gastos_dashboard_excluir_espino_lc(
            conn, demo, dfr_base, cuarteles_full
        )
        if dfr_base is not None and not dfr_base.empty and cuarteles_dash:
            dfr_base = dfr_base[
                dfr_base["Cuartel"].astype(str).isin(cuarteles_dash)
                | (dfr_base["Cuartel"].astype(str).str.upper() == "TOTAL GENERAL")
            ].copy()
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

        t = current_tenant()
        erp_nombre = tenant_nombre_erp(t, getattr(demo, "NOMBRE_ERP", None))
        if erp_nombre:
            dash_title = erp_nombre.upper()
        elif get_erp_app() == "concepcion":
            dash_title = "ERP AGRÍCOLA LA CONCEPCIÓN"
        else:
            dash_title = "ERP DEMO AGRÍCOLA"

        return {
            "alerta_rrhh": alerta_rrhh,
            "alertas_riego": alertas_riego_dashboard(conn),
            "indicadores": ind,
            "kpis": kpis,
            "gastos_cc": gastos_cc,
            "pagos_mes": pagos_mes,
            "dash_title": dash_title,
        }
    finally:
        conn.close()
