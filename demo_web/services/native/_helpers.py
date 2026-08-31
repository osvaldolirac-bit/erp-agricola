"""Utilidades compartidas para módulos nativos Flask."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any


def hoy_demo(demo) -> date:
    """Fecha actual Chile; no usar demo.hoy (queda fija al importar el módulo)."""
    return demo.hora_chile().date()


def parse_date(val: str | None, default: date) -> date:
    if not val:
        return default
    try:
        return datetime.strptime(val, "%Y-%m-%d").date()
    except ValueError:
        return default


def parse_decimal_cl(raw: str | None, default: float | None = 0.0) -> float | None:
    """Parsea cantidad/monto con decimal chileno: solo coma decimal (1,5).

    Miles opcionales con punto (1.250 o 1.250,5). Rechaza punto como decimal (1.5).
    """
    import re

    s = (raw or "").strip().replace(" ", "").replace("$", "")
    if not s:
        return default
    # Entero, decimal con coma, o miles chilenos (punto de miles + coma decimal).
    # El punto nunca actúa como decimal (rechaza 1.5).
    if not re.fullmatch(r"\d+(,\d+)?|\d{1,3}(\.\d{3})+(,\d+)?", s):
        return default
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return default


def temporada_sel(demo, param: str = "temp", temporadas=None) -> tuple[str, date, date]:
    from flask import request

    temps = temporadas if temporadas is not None else demo.TEMPORADAS_COSTOS
    sel = request.args.get(param)
    if sel:
        for t in temps:
            if t[0] == sel:
                return t
    hoy = hoy_demo(demo)
    for t in temps:
        if t[1] <= hoy <= t[2]:
            return t
    return temps[0]


def prorrateo_rrhh(demo, conn) -> dict:
    """Pesos 0–1 para imputación. Prefiere tabla prorrateo_cc si existe."""
    if hasattr(demo, "cargar_prorrateo_cc"):
        try:
            pesos = demo.cargar_prorrateo_cc(conn)
            if pesos:
                return pesos
        except Exception:
            pass
    if getattr(demo, "PRORRATEO_RRHH", None) is not None:
        return demo.PRORRATEO_RRHH
    return {}


def reparto_imputacion_cc(demo, conn, total, seleccionados) -> tuple[list[tuple[str, float]] | None, str | None]:
    """Reparte monto neto entre CC según prorrateo Consola (LC) o partes iguales (fallback).

    Prefiere demo._reparto_por_cc (app_concepcion). Si no existe, replica la misma lógica
    usando prorrateo_cc / PRORRATEO_CC_DEFAULT del tenant.
    """
    if hasattr(demo, "_reparto_por_cc"):
        try:
            reparto, err = demo._reparto_por_cc(conn, total, seleccionados)
            if err:
                return None, err
            return reparto, None
        except Exception as exc:
            return None, str(exc)

    try:
        total_f = float(total)
    except (TypeError, ValueError):
        return None, "Total inválido."
    if total_f <= 0:
        return None, "El total debe ser mayor a cero."

    sel = [str(c).strip().upper() for c in seleccionados if c]
    if not sel:
        return None, "Seleccione al menos un centro de costo."

    prorr = [str(c).strip().upper() for c in getattr(demo, "CUARTELES_PRORRATEO", [])]
    directos = [str(c).strip().upper() for c in getattr(demo, "CUARTELES_IMPUTACION_DIRECTA", [])]
    invalid = [c for c in sel if c not in prorr and c not in directos]
    if invalid:
        return None, f"Centro de costo no válido: {invalid[0]}"

    dir_sel = [c for c in sel if c in directos]
    pr_sel = [c for c in sel if c in prorr]
    if dir_sel and pr_sel:
        return None, (
            "No mezcle cuarteles del fundo (Corte 1, Corte 2, Ciruelos, Nogales) "
            "con El Espino u Otros en el mismo movimiento."
        )
    if dir_sel:
        parte = total_f / len(dir_sel)
        return [(c, parte) for c in dir_sel], None

    pesos = prorrateo_rrhh(demo, conn)
    sub = {c: float(pesos.get(c, 0.0) or 0.0) for c in pr_sel}
    suma = sum(sub.values())
    if suma <= 0:
        parte = total_f / len(pr_sel)
        return [(c, parte) for c in pr_sel], None
    return [(c, total_f * sub[c] / suma) for c in pr_sel], None


def avance_ppto_tone(pct: float) -> str:
    """Clase CSS para tono de avance presupuesto (igual que Streamlit)."""
    p = min(float(pct), 100.0) if pct <= 100 else 101.0
    if p <= 33:
        return "costos-tone-verde"
    if p <= 66:
        return "costos-tone-amarillo"
    if p <= 100:
        return "costos-tone-naranja"
    return "costos-tone-rojo"


def avance_ppto_badge_tone(pct: float | None) -> str:
    """Badge dashboard gastos por cuartel (fondo + texto, igual Streamlit)."""
    if pct is None:
        return ""
    p = float(pct)
    if p <= 33:
        return "costos-badge-verde"
    if p <= 66:
        return "costos-badge-amarillo"
    if p <= 100:
        return "costos-badge-naranja"
    return "costos-badge-rojo"


def matriz_costos_to_records(demo, df) -> tuple[list[str], list[dict]]:
    """Matriz costos con % Total (2 dec.), filas TOTAL GASTO / PRESUPUESTO / SALDO."""
    import pandas as pd

    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
        return [], []
    show = df.copy().fillna("")
    cols = [str(c) for c in show.columns]
    money = {c for c in cols if c not in ("Rubro", "% Total")}
    footer_map = {
        "TOTAL GASTO": "costos-row-gasto",
        "PRESUPUESTO": "costos-row-ppto",
        "SALDO": "costos-row-saldo",
    }
    rows = []
    for _, r in show.iterrows():
        rubro = str(r.get("Rubro", ""))
        rubro_u = rubro.upper()
        item: dict[str, Any] = {"_row_class": footer_map.get(rubro_u, "")}
        for c in cols:
            v = r[c]
            if c == "% Total":
                try:
                    item[c] = f"{float(v):.2f}%" if v != "" else ""
                except (TypeError, ValueError):
                    item[c] = ""
            elif c in money:
                try:
                    m = float(v or 0)
                    item[c] = demo.f_peso(m)
                    if rubro_u == "SALDO":
                        if m < -0.5:
                            item[f"__cls_{c}"] = "costos-saldo-neg"
                        elif m > 0.5:
                            item[f"__cls_{c}"] = "costos-saldo-pos"
                        else:
                            item[f"__cls_{c}"] = "costos-saldo-neutro"
                except (TypeError, ValueError):
                    item[c] = str(v)
            else:
                item[c] = str(v) if v != "" else ""
        rows.append(item)
    return cols, rows


def flujo_cell_classes(
    row_idx: int,
    col: str,
    n_meses: int,
    df_base,
    raw_val,
) -> str:
    """Clases CSS equivalentes a Streamlit (_style_col_flujo_proy, etc.)."""
    is_total = row_idx >= n_meses
    if is_total:
        cls = "flujo-cell-total"
        try:
            if float(raw_val or 0) < -0.01:
                cls += " flujo-cell-neg"
        except (TypeError, ValueError):
            pass
        return cls

    col_map = {
        "RRHH SUELDOS": ("RRHH", "RRHH_PROY"),
    }
    try:
        monto = float(raw_val or 0)
    except (TypeError, ValueError):
        monto = 0.0

    if col in ("RESULTADO MES", "EERR ACUM"):
        base_col = "RESULTADO_MES" if col == "RESULTADO MES" else "EERR_ACUM"
        try:
            m = float(df_base.iloc[row_idx][base_col] or 0)
            return "flujo-cell-neg" if m < -0.01 else ""
        except (IndexError, KeyError, TypeError, ValueError):
            return ""

    if col in ("EGRESOS PROY", "TESO PROY"):
        return "flujo-cell-proy" if monto > 0.01 else ""

    if col == "TESO REAL":
        return "flujo-cell-neg" if monto < -0.01 else ""

    if col in col_map:
        val_col, proy_col = col_map[col]
        try:
            proy = float(df_base.iloc[row_idx][proy_col] or 0)
            m = float(df_base.iloc[row_idx][val_col] or 0)
        except (IndexError, KeyError, TypeError, ValueError):
            proy, m = 0.0, 0.0
        parts = []
        if proy > 0.01 and m > 0.01:
            parts.append("flujo-cell-proy")
        if m < -0.01:
            parts.append("flujo-cell-neg")
        return " ".join(parts)

    return ""


def flujo_th_class(col: str) -> str:
    if col == "INGRESOS":
        return "flujo-th-ing"
    if col in (
        "RRHH SUELDOS", "TESO REAL", "TESO PROY",
        "EGRESOS REAL", "EGRESOS PROY", "EGRESOS TOTAL",
    ):
        return "flujo-th-eg"
    if col in ("RESULTADO MES", "EERR ACUM"):
        return "flujo-th-res"
    return "flujo-th-mes"


def df_to_records(df, money_cols: set[str] | None = None, demo=None) -> tuple[list[str], list[dict]]:
    import pandas as pd

    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
        return [], []
    show = df.copy().fillna("")
    cols = [str(c) for c in show.columns]
    rows = []
    for _, r in show.iterrows():
        item = {}
        for c in cols:
            v = r[c]
            if money_cols and c in money_cols and demo and v != "":
                try:
                    item[c] = demo.f_peso(float(v))
                except (TypeError, ValueError):
                    item[c] = str(v)
            else:
                item[c] = str(v) if v != "" else ""
        rows.append(item)
    return cols, rows
