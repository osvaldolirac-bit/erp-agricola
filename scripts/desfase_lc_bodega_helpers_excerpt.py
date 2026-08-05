
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

def _normalizar_um_lc_bodega(um):
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
    raw = re.sub(r"[^A-Z0-9ÁÉÍÓÚÑÜ\s]", " ", raw)
    stop = {
        "WG", "WP", "SC", "EC", "SL", "CS", "OD", "EW", "SE", "GR", "SG",
        "KG", "LT", "L", "ML", "GRS", "G", "X", "DE", "DEL", "LA", "EL",
        "PARA", "CON", "Y", "EN",
    }
    toks = []
    for t in raw.split():
        if t in stop:
            continue
        if re.fullmatch(r"\d+([.,]\d+)?", t):
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

def _calcular_desfaces_lc_bodega(conn, f_desde, f_hasta, dias_ventana=14):
    ext_desde = str(f_desde - timedelta(days=dias_ventana))
    ext_hasta = str(f_hasta + timedelta(days=dias_ventana))
    df_lc = pd.read_sql_query(
        """SELECT id, fecha, n_aplicacion, sector, producto, gasto_total,
                  COALESCE(NULLIF(TRIM(unidad_gasto), ''), ?) as unidad_gasto
           FROM libro_campo WHERE date(fecha) BETWEEN ? AND ?""",
        conn,
        params=(DEFAULT_UNIDAD_INSUMO, ext_desde, ext_hasta),
    )
    df_mov = pd.read_sql_query(
        f"""SELECT m.id, m.fecha, m.cantidad, m.centro_costo, i.producto,
                  {_sql_um_movimiento()} as um
           FROM movimientos m JOIN inventario i ON i.id = m.producto_id
           WHERE m.tipo = 'Salida' AND date(m.fecha) BETWEEN ? AND ?""",
        conn,
        params=(ext_desde, ext_hasta),
    )
    # Bodega: solo PPPL (es el catálogo que se controla).
    # LC: se mantiene completo para poder empatar alias (ej. "Nordox 75 WG" ↔ "COBRE NORDOX");
    #     al reportar desfase LC solo se listan filas PPPL.
    if not df_mov.empty:
        df_mov = df_mov[df_mov["producto"].apply(lambda p: producto_pppl_aprobado(conn, p))].copy()
    df_lc_disp = df_lc[(pd.to_datetime(df_lc["fecha"]).dt.date >= f_desde) & (pd.to_datetime(df_lc["fecha"]).dt.date <= f_hasta)] if not df_lc.empty else df_lc.copy()
    df_mov_disp = df_mov[(pd.to_datetime(df_mov["fecha"]).dt.date >= f_desde) & (pd.to_datetime(df_mov["fecha"]).dt.date <= f_hasta)] if not df_mov.empty else df_mov.copy()
    if df_mov.empty:
        df_mov_agg = pd.DataFrame(columns=["fecha_d", "producto_u", "cuartel_u", "cantidad", "producto"])
    else:
        df_mov = df_mov.copy()
        df_mov["producto_u"] = df_mov["producto"].str.strip().str.upper()
        df_mov["cuartel_u"] = df_mov["centro_costo"].str.strip().str.upper()
        df_mov["fecha_d"] = pd.to_datetime(df_mov["fecha"]).dt.date
        df_mov_agg = df_mov.groupby(["fecha_d", "producto_u", "cuartel_u"], as_index=False).agg(
            cantidad=("cantidad", "sum"),
            producto=("producto", "first"),
            um=("um", "first"),
        )
    used_mov_keys = set()
    lc_sin_ids = []
    if not df_lc_disp.empty:
        for _, lc in df_lc_disp.iterrows():
            matched = False
            for idx, mov in df_mov_agg.iterrows():
                key = (mov["fecha_d"], mov["producto_u"], mov["cuartel_u"])
                if key in used_mov_keys:
                    continue
                if _lc_mov_coinciden(lc, mov, dias_ventana):
                    used_mov_keys.add(key)
                    matched = True
                    break
            if not matched:
                lc_sin_ids.append(lc["id"])
    df_lc_sin = df_lc_disp[df_lc_disp["id"].isin(lc_sin_ids)].copy() if lc_sin_ids else df_lc_disp.iloc[0:0].copy()
    if not df_lc_sin.empty:
        df_lc_sin = df_lc_sin[df_lc_sin["producto"].apply(lambda p: producto_pppl_aprobado(conn, p))].copy()
    bod_sin_rows = []
    if not df_mov_disp.empty and not df_mov_agg.empty:
        df_mov_disp = df_mov_disp.copy()
        df_mov_disp["producto_u"] = df_mov_disp["producto"].str.strip().str.upper()
        df_mov_disp["cuartel_u"] = df_mov_disp["centro_costo"].str.strip().str.upper()
        df_mov_disp["fecha_d"] = pd.to_datetime(df_mov_disp["fecha"]).dt.date
        for _, grp in df_mov_disp.groupby(["fecha_d", "producto_u", "cuartel_u"]):
            key = (grp["fecha_d"].iloc[0], grp["producto_u"].iloc[0], grp["cuartel_u"].iloc[0])
            if key in used_mov_keys:
                continue
            cant = grp["cantidad"].sum()
            mov_probe = {
                "producto_u": key[1],
                "cuartel_u": key[2],
                "cantidad": cant,
                "fecha_d": key[0],
                "um": grp["um"].iloc[0],
            }
            tiene_lc = False
            if not df_lc.empty:
                for _, lc in df_lc.iterrows():
                    if _lc_mov_coinciden(lc, mov_probe, dias_ventana):
                        tiene_lc = True
                        break
            if not tiene_lc:
                bod_sin_rows.append({
                    "fecha": str(key[0]),
                    "centro_costo": grp["centro_costo"].iloc[0],
                    "producto": grp["producto"].iloc[0],
                    "cantidad": cant,
                    "um": grp["um"].iloc[0],
                })
    df_bod_sin = pd.DataFrame(bod_sin_rows)
    if not df_lc_sin.empty:
        df_lc_sin = df_lc_sin.rename(columns={
            "fecha": "FECHA", "n_aplicacion": "N° APP", "sector": "CUARTEL",
            "producto": "PRODUCTO", "gasto_total": "CANTIDAD", "unidad_gasto": "UM",
        })[["FECHA", "N° APP", "CUARTEL", "PRODUCTO", "CANTIDAD", "UM"]]
        df_lc_sin["CANTIDAD"] = df_lc_sin["CANTIDAD"].apply(_fmt_cantidad_desfase)
