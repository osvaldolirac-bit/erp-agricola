"""Campos planilla GlobalGAP en registros del Libro de Campo."""
from __future__ import annotations

import sqlite3
from datetime import date

from demo_web.services.weather import fetch_daily_weather

_PLANILLA_COLS = [
    ("variedad", "TEXT DEFAULT ''"),
    ("n_aplicacion_txt", "TEXT DEFAULT ''"),
    ("t_max", "REAL"),
    ("t_min", "REAL"),
    ("hr_pct", "REAL"),
    ("viento_kmh", "REAL"),
]

_VARIEDAD_POR_SECTOR = {
    "CEREZOS CORTE 1": "Santina",
    "CIRUELOS": "D'Agen",
}

_MOTIVO_DEF = "Control fitosanitario"


def ensure_planilla_columns(conn) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(libro_campo)").fetchall()}
    for name, decl in _PLANILLA_COLS:
        if name not in cols:
            try:
                conn.execute(f"ALTER TABLE libro_campo ADD COLUMN {name} {decl}")
            except sqlite3.OperationalError:
                pass
    for name, decl in (
        ("motivo", "TEXT DEFAULT ''"),
        ("car_etiqueta", "INTEGER DEFAULT 0"),
        ("car_agenda", "INTEGER DEFAULT 0"),
        ("car_mayor", "INTEGER DEFAULT 0"),
        ("unidad_gasto", "TEXT DEFAULT ''"),
        ("n_orden", "TEXT DEFAULT ''"),
    ):
        if name not in cols:
            try:
                conn.execute(f"ALTER TABLE libro_campo ADD COLUMN {name} {decl}")
            except sqlite3.OperationalError:
                pass


def default_variedad(sector: str, especie: str) -> str:
    sec = (sector or "").strip().upper()
    if sec in _VARIEDAD_POR_SECTOR:
        return _VARIEDAD_POR_SECTOR[sec]
    esp = (especie or "").strip().lower()
    if esp.startswith("ciruel"):
        return "D'Agen"
    if esp.startswith("cerez"):
        return "Santina"
    return ""


def enriquecer_aplicacion_globalgap(
    conn,
    n_app: int,
    fecha: date,
    sector: str,
    especie: str,
    items: list[dict],
    *,
    op_cert: bool = False,
) -> dict | None:
    """Completa columnas GlobalGAP (clima, variedad, carencias, etc.) tras guardar Libro de Campo."""
    ensure_planilla_columns(conn)
    sector_u = (sector or "").strip().upper()
    wx = fetch_daily_weather(fecha, sector_u)
    t_max = wx.get("t_max") if wx else None
    t_min = wx.get("t_min") if wx else None
    hr = wx.get("hr_pct") if wx else None
    viento = wx.get("viento_kmh") if wx else None
    variedad = default_variedad(sector_u, especie)
    n_prod = max(len(items), 1)

    rows = conn.execute(
        "SELECT id FROM libro_campo WHERE n_aplicacion=? ORDER BY id",
        (n_app,),
    ).fetchall()

    for idx, (row_id,) in enumerate(rows):
        item = items[idx] if idx < len(items) else {}
        try:
            dias_car = int(item.get("dias_car") or 0)
        except (TypeError, ValueError):
            dias_car = 0
        n_txt = f"{idx + 1} de {n_prod}" if n_prod > 1 else "1 de 1"
        um_gasto = (item.get("um_gasto") or "").strip()

        conn.execute(
            """UPDATE libro_campo SET
               variedad = CASE WHEN COALESCE(TRIM(variedad), '') = '' THEN ? ELSE variedad END,
               motivo = CASE WHEN COALESCE(TRIM(motivo), '') = '' THEN ? ELSE motivo END,
               n_aplicacion_txt = CASE WHEN COALESCE(TRIM(n_aplicacion_txt), '') = '' THEN ? ELSE n_aplicacion_txt END,
               car_etiqueta = CASE WHEN COALESCE(car_etiqueta, 0) = 0 THEN ? ELSE car_etiqueta END,
               car_mayor = CASE WHEN COALESCE(car_mayor, 0) = 0 THEN ? ELSE car_mayor END,
               t_max = COALESCE(t_max, ?),
               t_min = COALESCE(t_min, ?),
               hr_pct = COALESCE(hr_pct, ?),
               viento_kmh = COALESCE(viento_kmh, ?),
               operador_certificado = CASE WHEN operador_certificado IS NULL THEN ? ELSE operador_certificado END,
               unidad_gasto = CASE WHEN COALESCE(TRIM(unidad_gasto), '') = '' AND ? != '' THEN ? ELSE unidad_gasto END
               WHERE id=?""",
            (
                variedad,
                _MOTIVO_DEF,
                n_txt,
                dias_car,
                dias_car,
                t_max,
                t_min,
                hr,
                viento,
                1 if op_cert else 0,
                um_gasto,
                um_gasto,
                row_id,
            ),
        )

    return wx
