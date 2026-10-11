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


def status_schedule(api_key: str) -> dict[str, Any]:
    return _get(api_key, "statusschedule.php")


def set_zone_run(api_key: str, relay_id: int, seconds: int) -> dict[str, Any]:
    sec = max(1, int(seconds or 0))
    return _get(
        api_key,
        "setzone.php",
        {
            "action": "run",
            "relay_id": int(relay_id),
            "period_id": 999,
            "custom": sec,
        },
    )


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
