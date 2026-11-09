"""Cosecha cerezas El Espino — registros de cosecha, embalado y MG (Mínimos Garantizados)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from flask import request

COSECHA_SECCIONES = [("cosecha_cerezas", "🍒 COSECHA CEREZAS")]

CALIBRES = ["L", "XL", "J", "2J", "3J", "4J"]
VARIEDADES = ["SA", "SANTINA", "RD"]

# ── Datos semilla del Excel 2026 ──────────────────────────────────────────────

_SEED_COSECHA = [
    {"fecha": "2026-11-06", "documento": "21", "variedad": "SA",      "totes": 202,  "kilos_netos": 1880.2},
    {"fecha": "2026-11-07", "documento": "22", "variedad": "SANTINA", "totes": 19,   "kilos_netos": 171.0},
    {"fecha": "2026-11-07", "documento": "23", "variedad": "RD",      "totes": 320,  "kilos_netos": 2845.0},
]

# embalado: {variedad: {calibre: kg}}
_SEED_EMBALADO: dict[str, dict[str, float]] = {
    "SA":      {"L": 0.0,   "XL": 17.5,  "J": 90.4,  "2J": 397.5, "3J": 460.0, "4J": 455.0},
    "RD":      {"L": 0.0,   "XL": 157.5, "J": 552.5, "2J": 1152.5,"3J": 430.0, "4J": 80.0},
    "SANTINA": {"L": 0.0,   "XL": 0.0,   "J": 0.0,   "2J": 0.0,   "3J": 0.0,   "4J": 0.0},
}

# MG precios: {variedad: {semana: {calibre: mg_usd}}}
_SEED_MG_PRECIOS: dict[str, dict[int, dict[str, float | None]]] = {
    "SA": {
        45: {"XL": None, "J": 1.5, "2J": 2.5, "3J": 3.5, "4J": 4.0},
        46: {"XL": None, "J": 1.0, "2J": 2.0, "3J": 3.0, "4J": 3.5},
    },
    "RD": {
        45: {"XL": None, "J": 2.0, "2J": 3.0, "3J": 3.5, "4J": 3.5},
        46: {"XL": None, "J": 1.5, "2J": 2.6, "3J": 3.0, "4J": 3.2},
    },
    "SANTINA": {
        45: {"XL": None, "J": 2.0, "2J": 3.0, "3J": 4.0, "4J": 5.0},
        46: {"XL": None, "J": 2.0, "2J": 2.6, "3J": 3.6, "4J": 4.8},
        47: {"XL": None, "J": 1.5, "2J": 2.4, "3J": 3.4, "4J": 3.6},
    },
}

# Ha El Espino (para kg/há)
HA_ESPINO = 7.0


# ── Migración DB ──────────────────────────────────────────────────────────────

def migrar_cosecha_cerezas(conn) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS espino_cosecha (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha         TEXT NOT NULL,
            documento     TEXT NOT NULL,
            variedad      TEXT NOT NULL,
            totes         REAL DEFAULT 0,
            kilos_netos   REAL DEFAULT 0,
            temporada     TEXT DEFAULT '2026'
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS espino_embalado (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            variedad      TEXT NOT NULL,
            semana        INTEGER NOT NULL,
            cal_L         REAL DEFAULT 0,
            cal_XL        REAL DEFAULT 0,
            cal_J         REAL DEFAULT 0,
            cal_2J        REAL DEFAULT 0,
            cal_3J        REAL DEFAULT 0,
            cal_4J        REAL DEFAULT 0,
            temporada     TEXT DEFAULT '2026',
            UNIQUE(variedad, semana, temporada)
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS espino_mg_precio (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            variedad      TEXT NOT NULL,
            semana        INTEGER NOT NULL,
            calibre       TEXT NOT NULL,
            mg_usd        REAL,
            temporada     TEXT DEFAULT '2026',
            UNIQUE(variedad, semana, calibre, temporada)
        )"""
    )
    conn.commit()
    _seed_if_empty(conn)


def _seed_if_empty(conn) -> None:
    n = conn.execute("SELECT COUNT(*) FROM espino_cosecha WHERE temporada='2026'").fetchone()[0]
    if n:
        return
    for r in _SEED_COSECHA:
        conn.execute(
            "INSERT OR IGNORE INTO espino_cosecha (fecha,documento,variedad,totes,kilos_netos,temporada)"
            " VALUES (?,?,?,?,?,'2026')",
            (r["fecha"], r["documento"], r["variedad"], r["totes"], r["kilos_netos"]),
        )
    for var, calibres in _SEED_EMBALADO.items():
        conn.execute(
            "INSERT OR IGNORE INTO espino_embalado"
            " (variedad,semana,cal_L,cal_XL,cal_J,cal_2J,cal_3J,cal_4J,temporada)"
            " VALUES (?,45,?,?,?,?,?,?,'2026')",
            (var, calibres["L"], calibres["XL"], calibres["J"],
             calibres["2J"], calibres["3J"], calibres["4J"]),
        )
    for var, semanas in _SEED_MG_PRECIOS.items():
        for sem, calibres in semanas.items():
            for cal, precio in calibres.items():
                conn.execute(
                    "INSERT OR IGNORE INTO espino_mg_precio"
                    " (variedad,semana,calibre,mg_usd,temporada)"
                    " VALUES (?,?,?,?,'2026')",
                    (var, sem, cal, precio),
                )
    conn.commit()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_kg(v: float | None) -> str:
    if v is None or v == 0:
        return "—"
    return f"{v:,.1f}"


def _fmt_usd(v: float | None) -> str:
    if v is None:
        return "—"
    return f"USD {v:,.2f}"


def _mg_badge_class(mg: float | None) -> str:
    """Color badge según precio MG."""
    if mg is None:
        return "mg-badge-none"
    if mg >= 4.0:
        return "mg-badge-alto"
    if mg >= 2.5:
        return "mg-badge-medio"
    return "mg-badge-bajo"


# ── Gather ────────────────────────────────────────────────────────────────────

def gather_cosecha_cerezas(demo, conn) -> dict:
    migrar_cosecha_cerezas(conn)

    # ── Tabla de cosecha ──────────────────────────────────────────────────────
    cosecha_rows_raw = conn.execute(
        "SELECT id,fecha,documento,variedad,totes,kilos_netos FROM espino_cosecha"
        " WHERE temporada='2026' ORDER BY fecha ASC, id ASC"
    ).fetchall()

    cosecha_rows = []
    total_totes = 0.0
    total_kg = 0.0
    for r in cosecha_rows_raw:
        cosecha_rows.append({
            "id":          r[0],
            "fecha":       r[1],
            "documento":   r[2],
            "variedad":    r[3],
            "totes":       _fmt_kg(r[4]),
            "kilos_netos": _fmt_kg(r[5]),
        })
        total_totes += float(r[4] or 0)
        total_kg    += float(r[5] or 0)

    kg_por_ha = total_kg / HA_ESPINO if total_kg else 0.0

    # ── Tabla de embalado ─────────────────────────────────────────────────────
    emb_rows_raw = conn.execute(
        "SELECT variedad,cal_L,cal_XL,cal_J,cal_2J,cal_3J,cal_4J"
        " FROM espino_embalado WHERE temporada='2026' ORDER BY variedad"
    ).fetchall()

    embalado_data: dict[str, dict[str, float]] = {}
    for r in emb_rows_raw:
        embalado_data[r[0]] = {
            "L": float(r[1] or 0), "XL": float(r[2] or 0), "J": float(r[3] or 0),
            "2J": float(r[4] or 0), "3J": float(r[5] or 0), "4J": float(r[6] or 0),
        }

    # Totales por calibre
    totales_calibre: dict[str, float] = {c: 0.0 for c in CALIBRES}
    embalado_rows = []
    for var in VARIEDADES:
        d = embalado_data.get(var, {c: 0.0 for c in CALIBRES})
        row_total = sum(d.get(c, 0.0) for c in CALIBRES)
        for c in CALIBRES:
            totales_calibre[c] += d.get(c, 0.0)
        embalado_rows.append({
            "variedad": var,
            **{c: _fmt_kg(d.get(c, 0.0)) for c in CALIBRES},
            "total": _fmt_kg(row_total),
        })

    total_embalado = sum(totales_calibre.values())
    pct_exportado  = (total_embalado / total_kg * 100) if total_kg else 0.0

    pct_calibre = {}
    for c in CALIBRES:
        pct_calibre[c] = (totales_calibre[c] / total_embalado * 100) if total_embalado else 0.0

    # ── Tabla MG ──────────────────────────────────────────────────────────────
    mg_raw = conn.execute(
        "SELECT variedad,semana,calibre,mg_usd FROM espino_mg_precio"
        " WHERE temporada='2026' ORDER BY variedad,semana,calibre"
    ).fetchall()

    # Estructura: {variedad: {semana: {calibre: mg_usd}}}
    mg_data: dict[str, dict[int, dict[str, float | None]]] = {}
    for r in mg_raw:
        var, sem, cal, precio = r[0], int(r[1]), r[2], r[3]
        mg_data.setdefault(var, {}).setdefault(sem, {})[cal] = precio

    # Variedad display names
    var_labels = {"SA": "Sweet Aryana", "SANTINA": "Santina", "RD": "Royal Down"}

    # Determine the "base" week per variety (smallest semana = actual harvest week).
    # Subsequent weeks are price-only scenarios — quantities are zero until more
    # fruit is packed.  USD is computed from embalado kg × that week's MG prices.
    mg_bloques = []
    usd_total_global = 0.0
    kg_total_mg = 0.0

    for var in VARIEDADES:
        semanas_var = sorted(mg_data.get(var, {}).keys())
        emb_var = embalado_data.get(var, {c: 0.0 for c in CALIBRES})
        semanas_rows = []
        # Only the base week contributes to the aggregate USD total (Excel behaviour).
        base_sem = semanas_var[0] if semanas_var else None
        var_usd_total = 0.0

        for sem in semanas_var:
            precios_sem = mg_data[var].get(sem, {})
            calibres_row = []
            usd_sem = 0.0
            for cal in CALIBRES:
                if cal == "L":
                    continue
                mg = precios_sem.get(cal)
                # Quantities apply only for the base (actual harvest) week
                kg_emb = emb_var.get(cal, 0.0) if sem == base_sem else 0.0
                usd_cal = (kg_emb * mg) if (mg is not None and kg_emb > 0) else 0.0
                usd_sem += usd_cal
                calibres_row.append({
                    "calibre":  cal,
                    "kg":       kg_emb,
                    "kg_fmt":   _fmt_kg(kg_emb) if kg_emb else "—",
                    "mg":       mg,
                    "mg_fmt":   f"${mg:.2f}" if mg is not None else "—",
                    "usd":      usd_cal,
                    "usd_fmt":  f"${usd_cal:,.2f}" if usd_cal else "—",
                    "badge":    _mg_badge_class(mg),
                    "has_data": kg_emb > 0,
                    "is_base":  sem == base_sem,
                })
            if sem == base_sem:
                var_usd_total += usd_sem
            semanas_rows.append({
                "semana":        sem,
                "calibres":      calibres_row,
                "usd_total":     usd_sem,
                "usd_total_fmt": f"${usd_sem:,.2f}" if usd_sem else "—",
                "is_base":       sem == base_sem,
            })

        var_kg = sum(emb_var.get(c, 0.0) for c in CALIBRES if c != "L")
        kg_total_mg += var_kg
        usd_total_global += var_usd_total

        mg_bloques.append({
            "variedad":      var,
            "label":         var_labels.get(var, var),
            "semanas":       semanas_rows,
            "usd_total":     var_usd_total,
            "usd_total_fmt": f"${var_usd_total:,.2f}" if var_usd_total else "—",
        })

    mg_prom = usd_total_global / kg_total_mg if kg_total_mg else 0.0

    return {
        # cosecha
        "cosecha_rows":       cosecha_rows,
        "cosecha_total_totes": _fmt_kg(total_totes),
        "cosecha_total_kg":   _fmt_kg(total_kg),
        "cosecha_kg_ha":      f"{kg_por_ha:,.1f}",
        # embalado
        "embalado_rows":      embalado_rows,
        "embalado_calibres":  CALIBRES,
        "embalado_totales":   {c: _fmt_kg(totales_calibre[c]) for c in CALIBRES},
        "embalado_total_kg":  _fmt_kg(total_embalado),
        "embalado_pct_exp":   f"{pct_exportado:.1f}",
        "embalado_pct_cal":   {c: f"{pct_calibre[c]:.1f}" for c in CALIBRES},
        # MG
        "mg_bloques":         mg_bloques,
        "mg_calibres":        [c for c in CALIBRES if c != "L"],
        "mg_usd_total":       f"${usd_total_global:,.2f}" if usd_total_global else "—",
        "mg_prom":            f"${mg_prom:.2f}" if mg_prom else "—",
        "mg_prom_raw":        mg_prom,
    }
