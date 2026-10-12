"""Cliente mínimo Hydrawise REST API v1 (urllib, sin dependencias extra)."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API_BASE = "https://api.hydrawise.com/api/v1"
DEFAULT_TIMEOUT = 25


def _get(api_key: str, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    key = (api_key or "").strip()
    if not key:
        return {"ok": False, "error": "Sin API key Hydrawise."}
    q = {"api_key": key}
    if params:
        q.update({k: v for k, v in params.items() if v is not None})
    url = f"{API_BASE}/{path}?{urllib.parse.urlencode(q)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ERP-Agricola-Hydra/1.0"})
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
            data = json.loads(body) if body.strip() else {}
        except Exception:
            data = {}
        err = data.get("error_msg") or data.get("message") or f"HTTP {exc.code}"
        return {"ok": False, "error": str(err), "raw": data}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}

    if isinstance(data, dict) and data.get("error_msg"):
        return {"ok": False, "error": str(data["error_msg"]), "raw": data}
    return {"ok": True, "data": data}


def customer_details(api_key: str) -> dict[str, Any]:
    return _get(api_key, "customerdetails.php")


def status_schedule(api_key: str, controller_id: int | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if controller_id is not None:
        params["controller_id"] = int(controller_id)
    return _get(api_key, "statusschedule.php", params or None)


def set_zone_run(
    api_key: str,
    relay_id: int,
    seconds: int,
    *,
    controller_id: int | None = None,
) -> dict[str, Any]:
    sec = max(1, int(seconds or 0))
    params: dict[str, Any] = {
        "action": "run",
        "relay_id": int(relay_id),
        "period_id": 999,
        "custom": sec,
    }
    if controller_id is not None:
        params["controller_id"] = int(controller_id)
    return _get(api_key, "setzone.php", params)


def list_controllers(customer_payload: dict[str, Any]) -> list[dict[str, Any]]:
    root = customer_payload if isinstance(customer_payload, dict) else {}
    controllers = root.get("controllers") or []
    if isinstance(controllers, dict):
        controllers = [controllers]
    out: list[dict[str, Any]] = []
    for ctrl in controllers:
        if not isinstance(ctrl, dict):
            continue
        cid = ctrl.get("controller_id") or ctrl.get("id")
        if cid is None:
            continue
        out.append(
            {
                "controller_id": int(cid),
                "name": str(ctrl.get("name") or "Controlador"),
                "serial_number": str(ctrl.get("serial_number") or ""),
            }
        )
    if not out and root.get("controller_id"):
        out.append(
            {
                "controller_id": int(root["controller_id"]),
                "name": str(root.get("current_controller") or "Controlador"),
                "serial_number": "",
            }
        )
    return out


def flatten_relays_from_status(status_payload: dict[str, Any]) -> list[dict[str, Any]]:
    mp = relay_status_map(status_payload)
    out: list[dict[str, Any]] = []
    for rid, info in sorted(mp.items()):
        out.append(
            {
                "relay_id": rid,
                "nombre": info.get("nombre") or f"Zona {rid}",
                "raw": info.get("raw"),
            }
        )
    return out


def set_zone_stop_all(api_key: str) -> dict[str, Any]:
    return _get(api_key, "setzone.php", {"action": "stopall"})


def flatten_relays(customer_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extrae relays de la respuesta customerdetails (estructuras variables)."""
    out: list[dict[str, Any]] = []
    root = customer_payload if isinstance(customer_payload, dict) else {}
    controllers = root.get("controllers") or root.get("controller") or []
    if isinstance(controllers, dict):
        controllers = [controllers]
    for ctrl in controllers:
        if not isinstance(ctrl, dict):
            continue
        relays = ctrl.get("relays") or ctrl.get("relay") or []
        if isinstance(relays, dict):
            relays = [relays]
        for rel in relays:
            if not isinstance(rel, dict):
                continue
            rid = rel.get("relay_id") or rel.get("relay") or rel.get("id")
            if rid is None:
                continue
            name = (
                rel.get("name")
                or rel.get("relay_name")
                or rel.get("label")
                or f"Zona {rid}"
            )
            out.append(
                {
                    "relay_id": int(rid),
                    "nombre": str(name).strip(),
                    "raw": rel,
                }
            )
    return out


# Si last_contact es más viejo que esto, el equipo se considera offline (≈ app Hydrawise).
CONTROLLER_STALE_SEC = 18 * 60


def _as_controller_list(root: dict[str, Any]) -> list[dict[str, Any]]:
    controllers = root.get("controllers") or root.get("controller") or []
    if isinstance(controllers, dict):
        return [controllers]
    return [c for c in controllers if isinstance(c, dict)]


def parse_last_contact_ts(raw: Any) -> float | None:
    """Unix segundos desde last_contact Hydrawise (string o número)."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        ts = float(raw)
        if ts > 1e12:
            ts /= 1000.0
        return ts if ts > 1e8 else None
    s = str(raw).strip()
    if not s:
        return None
    try:
        ts = float(s)
        if ts > 1e12:
            ts /= 1000.0
        return ts if ts > 1e8 else None
    except ValueError:
        return None


def fmt_edad_contacto(seg: int | None) -> str:
    if seg is None:
        return "sin dato"
    s = max(0, int(seg))
    if s < 90:
        return f"hace {s} s"
    if s < 3600:
        return f"hace {s // 60} min"
    if s < 86400:
        h = s // 3600
        m = (s % 3600) // 60
        return f"hace {h} h {m} min" if m else f"hace {h} h"
    d = s // 86400
    return f"hace {d} día(s)"


def assess_field_connectivity(
    status_payload: dict[str, Any],
    *,
    controller_id: int | None = None,
    now_ts: float,
    stale_sec: int = CONTROLLER_STALE_SEC,
) -> dict[str, Any]:
    """¿El controlador en campo está en línea según last_contact / status?"""
    root = status_payload if isinstance(status_payload, dict) else {}
    last_ts = parse_last_contact_ts(root.get("last_contact"))
    status_txt = str(root.get("status") or "").strip()
    ctrl_name = str(root.get("name") or root.get("current_controller") or "").strip()

    for ctrl in _as_controller_list(root):
        cid = int(ctrl.get("controller_id") or ctrl.get("id") or 0)
        if controller_id and cid and cid != int(controller_id):
            continue
        if last_ts is None:
            last_ts = parse_last_contact_ts(ctrl.get("last_contact"))
        st = str(ctrl.get("status") or "").strip()
        if st:
            status_txt = st
        if not ctrl_name:
            ctrl_name = str(ctrl.get("name") or "").strip()

    age_sec: int | None = None
    if last_ts is not None:
        age_sec = int(max(0, now_ts - last_ts))

    status_low = status_txt.lower()
    status_offline = bool(
        status_txt
        and any(
            k in status_low
            for k in ("offline", "disconnected", "no contact", "not connected", "sin contact")
        )
    )

    if last_ts is None:
        equipment_online = None
    elif status_offline or (age_sec is not None and age_sec > stale_sec):
        equipment_online = False
    else:
        equipment_online = True

    return {
        "equipment_online": equipment_online,
        "last_contact_ts": last_ts,
        "last_contact_age_sec": age_sec,
        "status_text": status_txt,
        "controller_name": ctrl_name,
    }


def last_contact_from_customer(
    customer_payload: dict[str, Any],
    controller_id: int,
) -> float | None:
    root = customer_payload if isinstance(customer_payload, dict) else {}
    for ctrl in _as_controller_list(root):
        cid = int(ctrl.get("controller_id") or ctrl.get("id") or 0)
        if cid == int(controller_id):
            return parse_last_contact_ts(ctrl.get("last_contact"))
    return None


def relay_status_map(status_payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """relay_id → {running, name, ...} desde statusschedule."""
    mp: dict[int, dict[str, Any]] = {}
    root = status_payload if isinstance(status_payload, dict) else {}

    def _ingest(rel: dict[str, Any]) -> None:
        rid = rel.get("relay_id") or rel.get("relay") or rel.get("id")
        if rid is None:
            return
        running = rel.get("running")
        if running is None:
            running = rel.get("status") in (1, "1", "running", "Running", True)
        mp[int(rid)] = {
            "running": bool(running),
            "nombre": rel.get("name") or rel.get("relay_name") or "",
            "raw": rel,
        }

    relays = root.get("relays") or root.get("relay") or []
    if isinstance(relays, dict):
        relays = [relays]
    for rel in relays:
        if isinstance(rel, dict):
            _ingest(rel)

    controllers = root.get("controllers") or []
    if isinstance(controllers, dict):
        controllers = [controllers]
    for ctrl in controllers:
        if not isinstance(ctrl, dict):
            continue
        for rel in ctrl.get("relays") or []:
            if isinstance(rel, dict):
                _ingest(rel)
    return mp
