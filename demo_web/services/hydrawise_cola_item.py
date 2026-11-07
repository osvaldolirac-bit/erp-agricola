"""Columnas de un ítem de cola Hydrawise. fert_json es la décima."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

_SANTIAGO = ZoneInfo("America/Santiago")


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


def reloj_guardado_a_santiago(momento: datetime) -> datetime:
    """hora_chile() guarda UTC−4 fijo. En verano Santiago va una hora adelante.

    El resultado es naive, en la hora que ve el teléfono.
    """
    utc = (momento.replace(tzinfo=None) + timedelta(hours=4)).replace(tzinfo=timezone.utc)
    return utc.astimezone(_SANTIAGO).replace(tzinfo=None)


def _fmt_santiago(momento: datetime, forma: str = "%d/%m/%Y %H:%M") -> str:
    return reloj_guardado_a_santiago(momento).strftime(forma)


def fmt_reloj_guardado(valor: str | None, *, ya_es_local: bool = False) -> str:
    """Texto de un reloj guardado. Programar ya trae la hora del teléfono."""
    momento = _parse_dt(valor)
    if not momento:
        return ""
    if ya_es_local:
        return momento.strftime("%d/%m/%Y %H:%M")
    return _fmt_santiago(momento)


def horas_bitacora(
    tipo: str,
    inicio_programa: str | None,
    turnos: list[dict[str, Any]],
) -> dict[str, Any]:
    """Inicio de la cola y de cada sector, en la hora que ve el teléfono.

    El inicio de una cola programada ya está en hora local.
    run_inicio y run_fin salen de hora_chile(), fijo en UTC−4.
    """
    programado = str(tipo or "") == "programado"
    inicios: list[datetime] = []
    vistos: list[dict[str, str]] = []
    for turno in turnos:
        ri = _parse_dt(str(turno.get("run_inicio") or ""))
        rf = _parse_dt(str(turno.get("run_fin") or ""))
        if ri:
            inicios.append(ri)
        vistos.append(
            {
                "run_inicio_fmt": _fmt_santiago(ri) if ri else "",
                "run_fin_fmt": _fmt_santiago(rf) if rf else "",
            }
        )
    if inicios:
        inicio_fmt = _fmt_santiago(min(inicios))
    else:
        inicio_fmt = fmt_reloj_guardado(inicio_programa, ya_es_local=programado)
    return {
        "inicio_fmt": inicio_fmt,
        "tipo_label": "Programado" if programado else "Regar ahora",
        "turnos": vistos,
    }


def _reloj(segundos: int) -> str:
    resto = max(0, int(segundos))
    minutos, seg = divmod(resto, 60)
    if minutos >= 60:
        horas, minutos = divmod(minutos, 60)
        return f"{horas}:{minutos:02d}:{seg:02d}"
    return f"{minutos}:{seg:02d}"


def corte_al_pausar(
    minutos: float,
    run_inicio: str | None,
    ahora: datetime,
    previos: float = 0.0,
) -> dict[str, float] | None:
    """Minutos ya regados y los que quedan. None si falta menos de 15 segundos."""
    t0 = _parse_dt(run_inicio) or ahora
    elapsed = max(0.0, (ahora - t0).total_seconds())
    total = max(0.0, float(minutos or 0) * 60.0)
    rest = max(0.0, total - elapsed)
    if rest < 15:
        return None
    regado = min(elapsed, total) / 60.0
    return {
        "previos": float(previos or 0) + regado,
        "restantes_min": rest / 60.0,
        "restantes_sec": float(int(rest)),
    }


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
    minutos_total: float | None = None,
    item_id: int | None = None,
    pausado: bool = False,
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
    if inicio_prog and str(tipo or "") == "programado":
        inicio_prog_fmt = inicio_prog.strftime("%d/%m/%Y %H:%M")
    elif inicio_prog:
        inicio_prog_fmt = _fmt_santiago(inicio_prog)
    else:
        inicio_prog_fmt = ""
    fert = list(fertilizantes or [])
    return {
        "label": (label or "").strip() or "Riego en curso",
        "huerto_cc": (huerto_cc or "").strip(),
        "tipo_label": tipo_label,
        "cola_id": int(cola_id) if cola_id else None,
        "inicio_programa_fmt": inicio_prog_fmt,
        "run_inicio_fmt": _fmt_santiago(t0) if _parse_dt(run_inicio) else "—",
        "fin_estimado_fmt": "—" if pausado else _fmt_santiago(fin),
        "minutos_fmt": _fmt_minutos(
            float(minutos_total if minutos_total is not None else minutos or 0)
        ),
        "remaining_fmt": "0 min" if rest_min <= 0 else _fmt_minutos(float(rest_min)),
        "remaining_sec": rest_sec,
        "remaining_clock": _reloj(rest_sec),
        "creado_por": (creado_por or "").strip(),
        "tiene_fertirriego": bool(fert),
        "fertilizantes": fert,
        "item_id": int(item_id) if item_id else None,
        "pausado": bool(pausado),
    }
