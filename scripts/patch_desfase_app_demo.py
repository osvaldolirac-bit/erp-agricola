#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

path = Path("/root/demo-web/app_demo.py")
t = path.read_text(encoding="utf-8")
bak = Path(str(path) + ".bak_desfase_alias")
if not bak.exists():
    bak.write_bytes(path.read_bytes())

if "_productos_equivalentes_lc_bodega" in t:
    print("SKIP already", path)
    raise SystemExit(0)

OLD_CANT = """def _cantidades_equivalentes_lc_bodega(q_lc, q_mov, um_lc, um_mov, tol_rel=0.02, tol_abs=0.05):
    q_lc = float(q_lc)
    q_mov = float(q_mov)
    um_lc = (um_lc or DEFAULT_UNIDAD_INSUMO).strip() or DEFAULT_UNIDAD_INSUMO
    um_mov = um_mov or DEFAULT_UNIDAD_INSUMO
    if um_lc == um_mov:
        ref = max(abs(q_lc), abs(q_mov), tol_abs)
        return abs(q_lc - q_mov) <= max(tol_abs, ref * tol_rel)
    q_mov_en_lc = _convertir_um(q_mov, um_mov, um_lc)
    ref = max(abs(q_lc), abs(q_mov_en_lc), tol_abs)
    return abs(q_lc - q_mov_en_lc) <= max(tol_abs, ref * tol_rel)


def _lc_mov_coinciden(lc_row, mov_row, dias_ventana, tol_cant=0.05):
    if str(lc_row[\"producto\"]).strip().upper() != str(mov_row[\"producto_u\"]).strip().upper():
        return False
    if str(lc_row[\"sector\"]).strip().upper() != str(mov_row[\"cuartel_u\"]).strip().upper():
        return False
    um_lc = lc_row.get(\"unidad_gasto\") or DEFAULT_UNIDAD_INSUMO
    um_mov = mov_row.get(\"um\") or mov_row.get(\"um_inv\") or DEFAULT_UNIDAD_INSUMO
    if not _cantidades_equivalentes_lc_bodega(
        lc_row[\"gasto_total\"], mov_row[\"cantidad\"], um_lc, um_mov, tol_rel=0.02, tol_abs=tol_cant,
    ):
        return False
    d_lc = pd.to_datetime(lc_row[\"fecha\"]).date()
    d_mov = mov_row[\"fecha_d\"] if isinstance(mov_row[\"fecha_d\"], date) else pd.to_datetime(mov_row[\"fecha_d\"]).date()
    return abs((d_lc - d_mov).days) <= dias_ventana
"""

c = Path("/root/demo-web/app_concepcion.py").read_text(encoding="utf-8")
m = re.search(
    r"(def _fmt_cantidad_desfase\(v\):.*?return abs\(\(d_lc - d_mov\)\.days\) <= dias_ventana\n)",
    c,
    re.S,
)
if not m:
    m = re.search(
        r"(def _normalizar_um_lc_bodega\(um\):.*?return abs\(\(d_lc - d_mov\)\.days\) <= dias_ventana\n)",
        c,
        re.S,
    )
if not m:
    raise SystemExit("helpers not found in concepcion")
NEW = m.group(1)
if "_fmt_cantidad_desfase" not in NEW:
    m2 = re.search(r"(def _fmt_cantidad_desfase\(v\):.*?\n\n)", c, re.S)
    if m2:
        NEW = m2.group(1) + NEW

if OLD_CANT not in t:
    raise SystemExit("OLD_CANT demo not found")
t = t.replace(OLD_CANT, NEW, 1)

OLD_FILTER = """    if not df_lc.empty:
        df_lc = df_lc[df_lc[\"producto\"].apply(lambda p: producto_pppl_aprobado(conn, p))].copy()
    if not df_mov.empty:
        df_mov = df_mov[df_mov[\"producto\"].apply(lambda p: producto_pppl_aprobado(conn, p))].copy()
    df_lc_disp = df_lc[(pd.to_datetime(df_lc[\"fecha\"]).dt.date >= f_desde) & (pd.to_datetime(df_lc[\"fecha\"]).dt.date <= f_hasta)] if not df_lc.empty else df_lc.copy()
    df_mov_disp = df_mov[(pd.to_datetime(df_mov[\"fecha\"]).dt.date >= f_desde) & (pd.to_datetime(df_mov[\"fecha\"]).dt.date <= f_hasta)] if not df_mov.empty else df_mov.copy()
"""
NEW_FILTER = """    # Bodega: solo PPPL. LC completo para empatar alias; desfase LC solo reporta PPPL.
    if not df_mov.empty:
        df_mov = df_mov[df_mov[\"producto\"].apply(lambda p: producto_pppl_aprobado(conn, p))].copy()
    df_lc_disp = df_lc[(pd.to_datetime(df_lc[\"fecha\"]).dt.date >= f_desde) & (pd.to_datetime(df_lc[\"fecha\"]).dt.date <= f_hasta)] if not df_lc.empty else df_lc.copy()
    df_mov_disp = df_mov[(pd.to_datetime(df_mov[\"fecha\"]).dt.date >= f_desde) & (pd.to_datetime(df_mov[\"fecha\"]).dt.date <= f_hasta)] if not df_mov.empty else df_mov.copy()
"""
if OLD_FILTER not in t:
    raise SystemExit("OLD_FILTER demo not found")
t = t.replace(OLD_FILTER, NEW_FILTER, 1)

OLD_LC_SIN = """    df_lc_sin = df_lc_disp[df_lc_disp[\"id\"].isin(lc_sin_ids)].copy() if lc_sin_ids else df_lc_disp.iloc[0:0].copy()
"""
NEW_LC_SIN = """    df_lc_sin = df_lc_disp[df_lc_disp[\"id\"].isin(lc_sin_ids)].copy() if lc_sin_ids else df_lc_disp.iloc[0:0].copy()
    if not df_lc_sin.empty:
        df_lc_sin = df_lc_sin[df_lc_sin[\"producto\"].apply(lambda p: producto_pppl_aprobado(conn, p))].copy()
"""
if OLD_LC_SIN not in t:
    raise SystemExit("OLD_LC_SIN demo not found")
t = t.replace(OLD_LC_SIN, NEW_LC_SIN, 1)

t = t.replace(
    'df_lc_sin["CANTIDAD"] = df_lc_sin["CANTIDAD"].apply(f_cantidad)',
    'df_lc_sin["CANTIDAD"] = df_lc_sin["CANTIDAD"].apply(_fmt_cantidad_desfase)',
    1,
)
t = t.replace(
    'df_bod_sin["CANTIDAD"] = df_bod_sin["CANTIDAD"].apply(f_cantidad)',
    'df_bod_sin["CANTIDAD"] = df_bod_sin["CANTIDAD"].apply(_fmt_cantidad_desfase)',
    1,
)
path.write_text(t, encoding="utf-8")
print("OK", path)
