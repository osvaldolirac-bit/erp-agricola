"""Columnas de un ítem de cola Hydrawise. fert_json es la décima."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def partes_item(row: Any) -> tuple:
    """id, orden, relay_id, minutos, estado, run_inicio, run_fin, codigo, error, fert_json."""
    fert = row[9] if len(row) > 9 else ""
    return (
        int(row[0]),
        row[1],
        int(row[2]),
        float(row[3]),
        row[4],
        row[5],
        row[6],
        row[7],
        row[8],
        fert,
    )


def _parse_dt(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace(" ", "T")[:19])
    except ValueError:
        return None


def _fmt_minutos(minutos: float) -> str:
    total = int(round(float(minutos or 0)))
    if total <= 0:
        return "0 min"
    if total < 60:
        return f"{total} min"
    horas, resto = divmod(total, 60)
    if resto:
        return f"{horas} h {resto} min"
    return f"{horas} h"


def _reloj(segundos: int) -> str:
    resto = max(0, int(segundos))
    minutos, seg = divmod(resto, 60)
    if minutos >= 60:
        horas, minutos = divmod(minutos, 60)
        return f"{horas}:{minutos:02d}:{seg:02d}"
    return f"{minutos}:{seg:02d}"


def ficha_zona_corriendo(
    *,
    label: str,
    huerto_cc: str,
    cola_id: int | None,
    tipo: str,
    inicio_programa: str | None,
    creado_por: str | None,
    minutos: float,
    run_inicio: str | None,
    fertilizantes: list[dict[str, Any]] | None,
    ahora: datetime,
) -> dict[str, Any]:
    """Datos del sheet que abre el celular al tocar la zona que está regando."""
    t0 = _parse_dt(run_inicio) or ahora
    elapsed = max(0.0, (ahora - t0).total_seconds())
    total = max(0.0, float(minutos or 0) * 60.0)
    rest = max(0.0, total - elapsed)
    rest_sec = int(rest)
    if rest <= 0:
        rest_min = 0
    else:
        rest_min = int(rest // 60) + (1 if rest % 60 else 0)
    fin = t0 + timedelta(minutes=float(minutos or 0))
    inicio_prog = _parse_dt(inicio_programa)
    tipo_label = "Programado" if str(tipo or "") == "programado" else "Regar ahora"
    fert = list(fertilizantes or [])
    return {
        "label": (label or "").strip() or "Riego en curso",
        "huerto_cc": (huerto_cc or "").strip(),
        "tipo_label": tipo_label,
        "cola_id": int(cola_id) if cola_id else None,
        "inicio_programa_fmt": (
            inicio_prog.strftime("%d/%m/%Y %H:%M") if inicio_prog else ""
        ),
        "run_inicio_fmt": t0.strftime("%d/%m/%Y %H:%M") if _parse_dt(run_inicio) else "—",
        "fin_estimado_fmt": fin.strftime("%d/%m/%Y %H:%M"),
        "minutos_fmt": _fmt_minutos(float(minutos or 0)),
        "remaining_fmt": "0 min" if rest_min <= 0 else _fmt_minutos(float(rest_min)),
        "remaining_sec": rest_sec,
        "remaining_clock": _reloj(rest_sec),
        "creado_por": (creado_por or "").strip(),
        "tiene_fertirriego": bool(fert),
        "fertilizantes": fert,
    }
