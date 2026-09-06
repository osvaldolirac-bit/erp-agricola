"""Clima diario vía Open-Meteo (sin API key) — planilla GlobalGAP."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

# Soc. Agrícola La Concepción — La Aparición, Paine, RM (configurable por env).
_DEFAULT_LAT = -33.7810
_DEFAULT_LON = -70.6553

# Cuarteles en el mismo predio (La Aparición); leve offset por sector.
_SECTOR_COORDS: dict[str, tuple[float, float]] = {
    "CEREZOS CORTE 1": (-33.7795, -70.6520),
    "CIRUELOS": (-33.7825, -70.6580),
}


def _coords(sector: str | None = None) -> tuple[float, float]:
    key = (sector or "").strip().upper()
    if key in _SECTOR_COORDS:
        return _SECTOR_COORDS[key]
    lat = float(os.environ.get("ERP_WEATHER_LAT", _DEFAULT_LAT))
    lon = float(os.environ.get("ERP_WEATHER_LON", _DEFAULT_LON))
    return lat, lon


def _fetch_json(url: str, timeout: float = 8.0) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ERP-Agricola/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return None


def fetch_daily_weather(fecha: date, sector: str | None = None) -> dict | None:
    """T° máx/mín, HR% y viento (km/h) para una fecha y sector/campo."""
    lat, lon = _coords(sector)
    day = fecha.isoformat()
    today = date.today()
    params = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "timezone": "America/Santiago",
        "start_date": day,
        "end_date": day,
        "daily": "temperature_2m_max,temperature_2m_min,relative_humidity_2m_mean,wind_speed_10m_max",
        "windspeed_unit": "kmh",
    }
    q = urllib.parse.urlencode(params)

    if fecha >= today - timedelta(days=5):
        url = f"https://api.open-meteo.com/v1/forecast?{q}"
    else:
        url = f"https://archive-api.open-meteo.com/v1/archive?{q}"

    data = _fetch_json(url)
    if not data:
        return None

    daily = data.get("daily") or {}
    dates = daily.get("time") or []
    if day not in dates:
        return None
    idx = dates.index(day)

    def _at(key: str) -> float | None:
        arr = daily.get(key) or []
        if idx >= len(arr):
            return None
        val = arr[idx]
        if val is None:
            return None
        try:
            return round(float(val), 1)
        except (TypeError, ValueError):
            return None

    t_max = _at("temperature_2m_max")
    t_min = _at("temperature_2m_min")
    hr = _at("relative_humidity_2m_mean")
    viento = _at("wind_speed_10m_max")
    if t_max is None and t_min is None and hr is None and viento is None:
        return None

    return {
        "fecha": day,
        "t_max": t_max,
        "t_min": t_min,
        "hr_pct": round(hr) if hr is not None else None,
        "viento_kmh": viento,
        "fuente": "Open-Meteo",
        "lat": lat,
        "lon": lon,
    }
