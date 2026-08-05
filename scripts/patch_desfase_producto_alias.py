#!/usr/bin/env python3
"""Mejora cruce desfase LC↔Bodega: equivalencia de nombres + match sin filtrar LC PPPL."""
from __future__ import annotations

import re
from pathlib import Path

TARGETS = [
    Path("/root/demo-web/app_concepcion.py"),
    Path("/root/demo-web/app_demo.py"),
]

OLD_CANT = '''def _cantidades_equivalentes_lc_bodega(q_lc, q_mov, um_lc, um_mov, tol_rel=0.02, tol_abs=0.05):
    """Compara cantidades LC vs bodega en la misma UM (con conversión si difieren)."""
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
    if str(lc_row["producto"]).strip().upper() != str(mov_row["producto_u"]).strip().upper():
        return False
    if str(lc_row["sector"]).strip().upper() != str(mov_row["cuartel_u"]).strip().upper():
        return False
    um_lc = lc_row.get("unidad_gasto") or DEFAULT_UNIDAD_INSUMO
    um_mov = mov_row.get("um") or mov_row.get("um_inv") or DEFAULT_UNIDAD_INSUMO
    if not _cantidades_equivalentes_lc_bodega(
        lc_row["gasto_total"], mov_row["cantidad"], um_lc, um_mov, tol_rel=0.02, tol_abs=tol_cant,
    ):
        return False
    d_lc = pd.to_datetime(lc_row["fecha"]).date()
    d_mov = mov_row["fecha_d"] if isinstance(mov_row["fecha_d"], date) else pd.to_datetime(mov_row["fecha_d"]).date()
    return abs((d_lc - d_mov).days) <= dias_ventana
'''

NEW_CANT = '''def _normalizar_um_lc_bodega(um):
    """Normaliza etiquetas de UM (L/litro/Kg/etc.) al catálogo interno."""
    u = str(um or DEFAULT_UNIDAD_INSUMO).strip().lower().replace(".", "")
    aliases = {
        "kilo": "kg", "kilos": "kg", "kilogramo": "kg", "kilogramos": "kg",
        "gr": "gr", "g": "gr", "gramo": "gr", "gramos": "gr",
        "l": "lt", "lt": "lt", "litro": "lt", "litros": "lt",
        "ml": "ml", "mililitro": "ml", "mililitros": "ml",
        "cc": "ml",
    }
    return aliases.get(u, u or DEFAULT_UNIDAD_INSUMO)


def _tokens_producto_match(nombre):
    """Tokens significativos del nombre comercial (ignora dosis/formulaciones)."""
    raw = str(nombre or "").strip().upper()
    raw = re.sub(r"[^A-Z0-9ÁÉÍÓÚÑÜ\\s]", " ", raw)
    stop = {
        "WG", "WP", "SC", "EC", "SL", "CS", "OD", "EW", "SE", "GR", "SG",
        "KG", "LT", "L", "ML", "GRS", "G", "X", "DE", "DEL", "LA", "EL",
        "PARA", "CON", "Y", "EN",
    }
    toks = []
    for t in raw.split():
        if t in stop:
            continue
        if re.fullmatch(r"\\d+([.,]\\d+)?", t):
            continue
        if len(t) < 3:
            continue
        toks.append(t)
    return toks


def _productos_equivalentes_lc_bodega(p_lc, p_bod):
    """True si es el mismo producto comercial con nombre distinto (alias/dosis)."""
    a = str(p_lc or "").strip().upper()
    b = str(p_bod or "").strip().upper()
    if not a or not b:
        return False
    if a == b:
        return True
    # Contención limpia (ej. BIOLIFE PSYCHRO ⊂ BIOLIFE PSYCHRO 250)
    if a in b or b in a:
        return True
    ta, tb = set(_tokens_producto_match(a)), set(_tokens_producto_match(b))
    if not ta or not tb:
        return False
    # Todos los tokens del más corto están en el más largo (NORDOX ⊂ COBRE NORDOX)
    short, long = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if short <= long:
        return True
    # Intersección fuerte: al menos 2 tokens o 1 token largo (>=6) compartido
    inter = ta & tb
    if len(inter) >= 2:
        return True
    if any(len(t) >= 6 for t in inter):
        return True
    return False


def _cantidades_equivalentes_lc_bodega(q_lc, q_mov, um_lc, um_mov, tol_rel=0.02, tol_abs=0.05):
    """Compara cantidades LC vs bodega en la misma UM (con conversión si difieren)."""
    q_lc = float(q_lc)
    q_mov = float(q_mov)
    um_lc = _normalizar_um_lc_bodega(um_lc or DEFAULT_UNIDAD_INSUMO)
    um_mov = _normalizar_um_lc_bodega(um_mov or DEFAULT_UNIDAD_INSUMO)
    if um_lc == um_mov:
        ref = max(abs(q_lc), abs(q_mov), tol_abs)
        return abs(q_lc - q_mov) <= max(tol_abs, ref * tol_rel)
    q_mov_en_lc = _convertir_um(q_mov, um_mov, um_lc)
    ref = max(abs(q_lc), abs(q_mov_en_lc), tol_abs)
    return abs(q_lc - q_mov_en_lc) <= max(tol_abs, ref * tol_rel)


def _lc_mov_coinciden(lc_row, mov_row, dias_ventana, tol_cant=0.05):
    if not _productos_equivalentes_lc_bodega(lc_row["producto"], mov_row["producto_u"]):
        return False
    if str(lc_row["sector"]).strip().upper() != str(mov_row["cuartel_u"]).strip().upper():
        return False
    um_lc = lc_row.get("unidad_gasto") or DEFAULT_UNIDAD_INSUMO
    um_mov = mov_row.get("um") or mov_row.get("um_inv") or DEFAULT_UNIDAD_INSUMO
    if not _cantidades_equivalentes_lc_bodega(
        lc_row["gasto_total"], mov_row["cantidad"], um_lc, um_mov, tol_rel=0.02, tol_abs=tol_cant,
    ):
        return False
    d_lc = pd.to_datetime(lc_row["fecha"]).date()
    d_mov = mov_row["fecha_d"] if isinstance(mov_row["fecha_d"], date) else pd.to_datetime(mov_row["fecha_d"]).date()
    return abs((d_lc - d_mov).days) <= dias_ventana
'''

# In calcular: stop filtering LC by PPPL before match; filter only when reporting lc_sin
OLD_FILTER = '''    if not df_lc.empty:
        df_lc = df_lc[df_lc["producto"].apply(lambda p: producto_pppl_aprobado(conn, p))].copy()
    if not df_mov.empty:
        df_mov = df_mov[df_mov["producto"].apply(lambda p: producto_pppl_aprobado(conn, p))].copy()
    df_lc_disp = df_lc[(pd.to_datetime(df_lc["fecha"]).dt.date >= f_desde) & (pd.to_datetime(df_lc["fecha"]).dt.date <= f_hasta)] if not df_lc.empty else df_lc.copy()
    df_mov_disp = df_mov[(pd.to_datetime(df_mov["fecha"]).dt.date >= f_desde) & (pd.to_datetime(df_mov["fecha"]).dt.date <= f_hasta)] if not df_mov.empty else df_mov.copy()
'''

NEW_FILTER = '''    # Bodega: solo PPPL (es el catálogo que se controla).
    # LC: se mantiene completo para poder empatar alias (ej. "Nordox 75 WG" ↔ "COBRE NORDOX");
    #     al reportar desfase LC solo se listan filas PPPL.
    if not df_mov.empty:
        df_mov = df_mov[df_mov["producto"].apply(lambda p: producto_pppl_aprobado(conn, p))].copy()
    df_lc_disp = df_lc[(pd.to_datetime(df_lc["fecha"]).dt.date >= f_desde) & (pd.to_datetime(df_lc["fecha"]).dt.date <= f_hasta)] if not df_lc.empty else df_lc.copy()
    df_mov_disp = df_mov[(pd.to_datetime(df_mov["fecha"]).dt.date >= f_desde) & (pd.to_datetime(df_mov["fecha"]).dt.date <= f_hasta)] if not df_mov.empty else df_mov.copy()
'''

OLD_LC_SIN = '''    df_lc_sin = df_lc_disp[df_lc_disp["id"].isin(lc_sin_ids)].copy() if lc_sin_ids else df_lc_disp.iloc[0:0].copy()
'''

NEW_LC_SIN = '''    df_lc_sin = df_lc_disp[df_lc_disp["id"].isin(lc_sin_ids)].copy() if lc_sin_ids else df_lc_disp.iloc[0:0].copy()
    if not df_lc_sin.empty:
        df_lc_sin = df_lc_sin[df_lc_sin["producto"].apply(lambda p: producto_pppl_aprobado(conn, p))].copy()
'''

# Better quantity display in desfase tables (avoid 0.125 → 0,12)
OLD_FMT = '''        df_lc_sin["CANTIDAD"] = df_lc_sin["CANTIDAD"].apply(f_cantidad)
    if not df_bod_sin.empty:
        df_bod_sin = df_bod_sin.rename(columns={
            "fecha": "FECHA", "centro_costo": "CUARTEL", "producto": "PRODUCTO",
            "cantidad": "CANTIDAD", "um": "UM",
        })[["FECHA", "CUARTEL", "PRODUCTO", "CANTIDAD", "UM"]]
        df_bod_sin["CANTIDAD"] = df_bod_sin["CANTIDAD"].apply(f_cantidad)
'''

NEW_FMT = '''        df_lc_sin["CANTIDAD"] = df_lc_sin["CANTIDAD"].apply(_fmt_cantidad_desfase)
    if not df_bod_sin.empty:
        df_bod_sin = df_bod_sin.rename(columns={
            "fecha": "FECHA", "centro_costo": "CUARTEL", "producto": "PRODUCTO",
            "cantidad": "CANTIDAD", "um": "UM",
        })[["FECHA", "CUARTEL", "PRODUCTO", "CANTIDAD", "UM"]]
        df_bod_sin["CANTIDAD"] = df_bod_sin["CANTIDAD"].apply(_fmt_cantidad_desfase)
'''

FMT_HELPER = '''
def _fmt_cantidad_desfase(v):
    """Muestra hasta 3 decimales útiles (0.125 no debe verse como 0,12)."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return v
    if abs(x - round(x)) < 1e-9:
        return f"{int(round(x))}"
    s = f"{x:.3f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")

'''


def patch_file(path: Path) -> None:
    t = path.read_text(encoding="utf-8")
    if "_productos_equivalentes_lc_bodega" in t:
        print("SKIP already patched", path)
        return
    if OLD_CANT not in t:
        raise SystemExit(f"OLD_CANT not found in {path}")
    if OLD_FILTER not in t:
        raise SystemExit(f"OLD_FILTER not found in {path}")
    if OLD_LC_SIN not in t:
        raise SystemExit(f"OLD_LC_SIN not found in {path}")
    if OLD_FMT not in t:
        raise SystemExit(f"OLD_FMT not found in {path}")
    # ensure `re` imported
    if "\nimport re\n" not in t and not re.search(r"^import re\s*$", t, re.M):
        t = t.replace("from __future__ import annotations\n", "from __future__ import annotations\nimport re\n", 1)
        if "import re\n" not in t:
            # fallback after first import
            t = re.sub(r"(^import .+?\n)", r"\1import re\n", t, count=1, flags=re.M)
    t = t.replace(OLD_CANT, NEW_CANT, 1)
    t = t.replace(OLD_FILTER, NEW_FILTER, 1)
    t = t.replace(OLD_LC_SIN, NEW_LC_SIN, 1)
    t = t.replace(OLD_FMT, NEW_FMT, 1)
    # insert helper near cantidades function (already includes tokens helpers in NEW_CANT)
    # add _fmt_cantidad_desfase before _cantidades if missing
    if "_fmt_cantidad_desfase" not in t:
        t = t.replace(
            "def _normalizar_um_lc_bodega(um):",
            FMT_HELPER + "def _normalizar_um_lc_bodega(um):",
            1,
        )
    path.write_text(t, encoding="utf-8")
    print("OK", path)


def main() -> int:
    for p in TARGETS:
        if not p.exists():
            print("MISS", p)
            continue
        bak = Path(str(p) + ".bak_desfase_alias")
        if not bak.exists():
            bak.write_bytes(p.read_bytes())
        patch_file(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
