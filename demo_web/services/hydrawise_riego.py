"""Integración Hydrawise (Hydra) — solo tenant La Concepción."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from demo_web.services.demo_loader import get_demo_module
from demo_web.services.hydrawise_cola_item import partes_item
from demo_web.services.hydrawise_client import (
    customer_details,
    flatten_relays,
    flatten_relays_from_status,
    last_contact_from_customer,
    list_controllers,
    relay_status_map,
    set_zone_run,
    set_zone_stop_all,
    status_schedule,
)
from demo_web.services.tenant_scope import is_concepcion_tenant

META_KEY_API = "hydrawise_api_key_v1"
META_KEY_CONTROLLER = "hydrawise_controller_id_v1"
META_LAST_SYNC = "hydrawise_last_api_sync_v1"
META_LAST_PROBE = "hydrawise_last_probe_v1"
META_LAST_CONTACT = "hydrawise_controller_last_contact_v1"
SYNC_COOLDOWN_SEC = 90
PROBE_COOLDOWN_SEC = 90
CONTACT_REFRESH_SEC = 600


def _is_rate_limit_err(err: str | None) -> bool:
    return "429" in str(err or "")


def _fmt_api_err(err: str) -> str:
    if _is_rate_limit_err(err):
        return (
            "Hydrawise limitó las consultas (HTTP 429). Espere 1–2 minutos "
            "sin recargar HYDRA en loop; el testigo usa el último estado conocido."
        )
    return str(err)


def _probe_desde_cache(conn: sqlite3.Connection, *, nota: str = "") -> dict[str, Any] | None:
    cached = _read_probe_cache(conn)
    if not cached:
        return None
    demo = get_demo_module()
    try:
        age = demo.hora_chile().timestamp() - float(cached.get("ts") or 0)
    except (TypeError, ValueError):
        age = 0
    msg = str(cached.get("msg") or "")
    if nota:
        msg = f"{msg} · {nota}" if msg else nota
    return {
        "online": bool(cached.get("online")),
        "ok": bool(cached.get("ok", True)),
        "msg": msg,
        "title": str(cached.get("title") or ""),
        "zonas": {},
        "cached": True,
        "probe_age_sec": int(max(0, age)),
        "rate_limited": True,
    }


def hydrawise_habilitado() -> bool:
    return lc_contexto_hydra()


def lc_contexto_hydra() -> bool:
    """LC en sesión o tenant=concepcion en link público."""
    if is_concepcion_tenant():
        return True
    try:
        from flask import g

        t = getattr(g, "tenant", None) or {}
        if str(t.get("slug") or "").lower() == "concepcion":
            return True
    except Exception:
        pass
    return False


def _conn():
    return get_demo_module().conectar_db()


def migrar_hydrawise(conn: sqlite3.Connection | None = None) -> None:
    from erp_solo_lectura import conn_en_solo_lectura

    own = conn is None
    if own:
        conn = _conn()
    try:
        if conn_en_solo_lectura(conn):
            return
        conn.execute(
            """CREATE TABLE IF NOT EXISTS hydrawise_zona (
                   relay_id INTEGER PRIMARY KEY,
                   nombre_hw TEXT NOT NULL,
                   alias TEXT DEFAULT '',
                   huerto_cc TEXT DEFAULT '',
                   modo_riego TEXT DEFAULT 'horas',
                   activo INTEGER DEFAULT 1,
                   actualizado_en TEXT DEFAULT ''
               )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS hydrawise_zona_fert (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   relay_id INTEGER NOT NULL,
                   producto_id INTEGER NOT NULL,
                   cantidad REAL NOT NULL,
                   dosis_ha REAL,
                   unidad TEXT DEFAULT 'kg',
                   orden INTEGER DEFAULT 0,
                   FOREIGN KEY (relay_id) REFERENCES hydrawise_zona(relay_id)
               )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS hydrawise_cola (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   tipo TEXT NOT NULL,
                   inicio_programa TEXT NOT NULL,
                   estado TEXT DEFAULT 'programado',
                   creado_por TEXT DEFAULT '',
                   creado_en TEXT NOT NULL,
                   notas TEXT DEFAULT ''
               )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS hydrawise_cola_item (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   cola_id INTEGER NOT NULL,
                   orden INTEGER NOT NULL,
                   relay_id INTEGER NOT NULL,
                   minutos REAL NOT NULL,
                   estado TEXT DEFAULT 'pendiente',
                   run_inicio TEXT DEFAULT '',
                   run_fin TEXT DEFAULT '',
                   codigo_riego TEXT DEFAULT '',
                   error_msg TEXT DEFAULT '',
                   FOREIGN KEY (cola_id) REFERENCES hydrawise_cola(id)
               )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS hydrawise_importados (
                   event_key TEXT PRIMARY KEY,
                   codigo_riego TEXT NOT NULL,
                   importado_en TEXT NOT NULL
               )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_hw_cola_item_cola ON hydrawise_cola_item(cola_id, orden)"
        )
        item_cols = {
            r[1] for r in conn.execute("PRAGMA table_info(hydrawise_cola_item)").fetchall()
        }
        if "fert_json" not in item_cols:
            conn.execute(
                "ALTER TABLE hydrawise_cola_item ADD COLUMN fert_json TEXT DEFAULT ''"
            )
        cols = {r[1] for r in conn.execute("PRAGMA table_info(hydrawise_zona)").fetchall()}
        if "link_riego" not in cols:
            conn.execute(
                "ALTER TABLE hydrawise_zona ADD COLUMN link_riego INTEGER DEFAULT 1"
            )
        conn.commit()
    finally:
        if own:
            conn.close()


def get_api_key(conn: sqlite3.Connection) -> str:
    migrar_hydrawise(conn)
    row = conn.execute(
        "SELECT valor FROM schema_meta WHERE clave=?", (META_KEY_API,)
    ).fetchone()
    return str(row[0] or "").strip() if row else ""


def _norm_equipo_tag(value: str) -> str:
    return "".join(c for c in str(value or "").upper() if c.isalnum())


def get_equipo_ref(conn: sqlite3.Connection) -> str:
    """Serial alfanumérico del HCC o ID numérico API guardado en Admin."""
    migrar_hydrawise(conn)
    row = conn.execute(
        "SELECT valor FROM schema_meta WHERE clave=?", (META_KEY_CONTROLLER,)
    ).fetchone()
    return str(row[0] or "").strip() if row else ""


def get_controller_id(conn: sqlite3.Connection) -> str:
    """Alias legado — valor guardado por el usuario (serial o ID)."""
    return get_equipo_ref(conn)


def set_equipo_ref(conn: sqlite3.Connection, ref: str | None) -> None:
    from erp_solo_lectura import conn_en_solo_lectura

    if conn_en_solo_lectura(conn):
        return
    migrar_hydrawise(conn)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_meta (clave TEXT PRIMARY KEY, valor TEXT)"""
    )
    val = (ref or "").strip()
    if not val:
        conn.execute("DELETE FROM schema_meta WHERE clave=?", (META_KEY_CONTROLLER,))
    else:
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta (clave, valor) VALUES (?, ?)",
            (META_KEY_CONTROLLER, val),
        )
    conn.commit()


def set_controller_id(conn: sqlite3.Connection, controller_id: int | str | None) -> None:
    """Compat: acepta serial alfanumérico o ID numérico."""
    if controller_id is None:
        set_equipo_ref(conn, None)
    else:
        set_equipo_ref(conn, str(controller_id).strip())


def _api_id_desde_ref(ref: str, equipos: list[dict[str, Any]]) -> int | None:
    raw = (ref or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        api = int(raw)
        for e in equipos:
            if int(e.get("controller_id") or 0) == api:
                return api
        return api
    tag = _norm_equipo_tag(raw)
    for e in equipos:
        if _norm_equipo_tag(e.get("serial_number")) == tag:
            return int(e["controller_id"])
        if str(e.get("controller_id") or "") == raw:
            return int(e["controller_id"])
        if _norm_equipo_tag(e.get("name")) == tag:
            return int(e["controller_id"])
    return None


def listar_equipos(conn: sqlite3.Connection) -> dict[str, Any]:
    key = get_api_key(conn)
    if not key:
        return {"ok": False, "msg": "Sin API key.", "equipos": []}
    resp = customer_details(key)
    if not resp.get("ok"):
        return {
            "ok": False,
            "msg": _fmt_api_err(resp.get("error") or "Error"),
            "equipos": [],
        }
    equipos = list_controllers(resp.get("data") or {})
    return {"ok": True, "msg": f"{len(equipos)} equipo(s) en la cuenta.", "equipos": equipos}


def _resolver_controller_id(conn: sqlite3.Connection, key: str) -> tuple[int | None, str]:
    """Devuelve controller_id numérico API para statusschedule/setzone."""
    ref = get_equipo_ref(conn)
    if ref.isdigit():
        return int(ref), ""
    resp = customer_details(key)
    if not resp.get("ok"):
        return None, _fmt_api_err(resp.get("error") or "Error")
    equipos = list_controllers(resp.get("data") or {})
    if ref:
        api_id = _api_id_desde_ref(ref, equipos)
        if api_id is not None:
            return api_id, ""
        return (
            None,
            f"No se encontró equipo «{ref}» en la cuenta. "
            "Use «Listar equipos» y pegue el serial (alfanumérico) o el ID numérico.",
        )
    if len(equipos) == 1:
        e0 = equipos[0]
        serial = str(e0.get("serial_number") or "").strip()
        if serial:
            set_equipo_ref(conn, serial)
        else:
            set_equipo_ref(conn, str(e0.get("controller_id")))
        return int(e0["controller_id"]), ""
    if len(equipos) > 1:
        return (
            None,
            "Hay varios equipos: indique el **serial** (alfanumérico del sticker) "
            "en Administración → Hydrawise («Listar equipos»).",
        )
    return None, "No se encontró equipo con serial en la cuenta Hydrawise."


def _relays_para_cuenta(conn: sqlite3.Connection, key: str) -> tuple[list[dict[str, Any]], str]:
    cid, err = _resolver_controller_id(conn, key)
    if err:
        return [], err
    st = status_schedule(key, cid)
    if st.get("ok"):
        relays = flatten_relays_from_status(st.get("data") or {})
        if relays:
            return relays, ""
    resp = customer_details(key)
    if not resp.get("ok"):
        return [], _fmt_api_err(resp.get("error") or "Error")
    relays = flatten_relays(resp.get("data") or {})
    if relays:
        return relays, ""
    if not st.get("ok"):
        return [], _fmt_api_err(st.get("error") or "Sin zonas")
    return [], "No se encontraron zonas. Verifique serial del HCC en app Hydrawise."


def set_api_key(conn: sqlite3.Connection, api_key: str) -> None:
    from erp_solo_lectura import conn_en_solo_lectura

    if conn_en_solo_lectura(conn):
        return
    migrar_hydrawise(conn)
    key = (api_key or "").strip()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_meta (clave TEXT PRIMARY KEY, valor TEXT)"""
    )
    if key:
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta (clave, valor) VALUES (?, ?)",
            (META_KEY_API, key),
        )
    else:
        conn.execute("DELETE FROM schema_meta WHERE clave=?", (META_KEY_API,))
    conn.commit()


def probar_conexion(conn: sqlite3.Connection) -> dict[str, Any]:
    key = get_api_key(conn)
    if not key:
        return {"ok": False, "msg": "Configure la API key en Administración → Hydrawise."}
    equipos = listar_equipos(conn)
    if not equipos.get("ok"):
        return {"ok": False, "msg": equipos.get("msg")}
    relays, err = _relays_para_cuenta(conn, key)
    if err:
        return {"ok": False, "msg": err}
    ref = get_equipo_ref(conn)
    extra = f" Equipo: {ref}." if ref else ""
    return {
        "ok": True,
        "msg": f"Conexión OK — {len(relays)} zona(s).{extra}",
        "equipos": equipos.get("equipos") or [],
    }


def importar_zonas_desde_api(conn: sqlite3.Connection) -> dict[str, Any]:
    from erp_solo_lectura import conn_en_solo_lectura

    if conn_en_solo_lectura(conn):
        return {"ok": False, "msg": "Solo lectura."}
    key = get_api_key(conn)
    if not key:
        return {"ok": False, "msg": "Sin API key."}
    relays, err = _relays_para_cuenta(conn, key)
    if err:
        return {"ok": False, "msg": err}
    if not relays:
        return {"ok": False, "msg": "No se encontraron zonas en Hydrawise."}
    fh = get_demo_module().hora_chile().strftime("%Y-%m-%d %H:%M:%S")
    n = 0
    for rel in relays:
        rid = int(rel["relay_id"])
        nom = str(rel.get("nombre") or f"Zona {rid}")
        conn.execute(
            """INSERT INTO hydrawise_zona
               (relay_id, nombre_hw, alias, actualizado_en, activo, link_riego)
               VALUES (?, ?, COALESCE((SELECT alias FROM hydrawise_zona WHERE relay_id=?), ''), ?, 1, 1)
               ON CONFLICT(relay_id) DO UPDATE SET
                 nombre_hw=excluded.nombre_hw,
                 actualizado_en=excluded.actualizado_en,
                 link_riego=1""",
            (rid, nom, rid, fh),
        )
        n += 1
    conn.commit()
    return {"ok": True, "msg": f"Importadas/actualizadas {n} zona(s)."}


def listar_zonas(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    migrar_hydrawise(conn)
    rows = conn.execute(
        """SELECT relay_id, nombre_hw, alias, huerto_cc, modo_riego, activo,
                  COALESCE(link_riego, 1)
           FROM hydrawise_zona ORDER BY relay_id"""
    ).fetchall()
    out = []
    for r in rows:
        rid = int(r[0])
        ferts = conn.execute(
            """SELECT id, producto_id, cantidad, dosis_ha, unidad, orden
               FROM hydrawise_zona_fert WHERE relay_id=? ORDER BY orden, id""",
            (rid,),
        ).fetchall()
        out.append(
            {
                "relay_id": rid,
                "nombre_hw": r[1],
                "alias": r[2] or "",
                "huerto_cc": r[3] or "",
                "modo_riego": r[4] or "horas",
                "activo": int(r[5] or 0),
                "link_riego": int(r[6] or 0),
                "fertilizantes": [
                    {
                        "id": int(f[0]),
                        "producto_id": int(f[1]),
                        "cantidad": float(f[2]),
                        "dosis_ha": f[3],
                        "unidad": f[4] or "kg",
                        "orden": int(f[5] or 0),
                    }
                    for f in ferts
                ],
            }
        )
    return out


def zona_por_relay(conn: sqlite3.Connection, relay_id: int) -> dict[str, Any] | None:
    for z in listar_zonas(conn):
        if z["relay_id"] == int(relay_id):
            return z
    return None


def guardar_mapeo_zona(
    conn: sqlite3.Connection,
    relay_id: int,
    *,
    alias: str,
    huerto_cc: str,
    modo_riego: str,
    activo: bool,
    link_riego: bool,
    fert_json: str,
) -> dict[str, Any]:
    from erp_solo_lectura import conn_en_solo_lectura

    if conn_en_solo_lectura(conn):
        return {"ok": False, "msg": "Solo lectura."}
    migrar_hydrawise(conn)
    rid = int(relay_id)
    if not conn.execute("SELECT 1 FROM hydrawise_zona WHERE relay_id=?", (rid,)).fetchone():
        return {"ok": False, "msg": "Zona no importada."}
    fh = get_demo_module().hora_chile().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """UPDATE hydrawise_zona
           SET alias=?, huerto_cc=?, modo_riego=?, activo=?, link_riego=?, actualizado_en=?
           WHERE relay_id=?""",
        (
            (alias or "").strip(),
            (huerto_cc or "").strip().upper(),
            (modo_riego or "horas").strip().lower(),
            1 if activo else 0,
            1 if link_riego else 0,
            fh,
            rid,
        ),
    )
    try:
        lineas = json.loads(fert_json or "[]")
        if not isinstance(lineas, list):
            lineas = []
    except json.JSONDecodeError:
        lineas = []
    conn.execute("DELETE FROM hydrawise_zona_fert WHERE relay_id=?", (rid,))
    for i, ln in enumerate(lineas):
        if not isinstance(ln, dict):
            continue
        pid = int(ln.get("producto_id") or 0)
        cant = float(ln.get("cantidad") or 0)
        if pid <= 0 or cant <= 0:
            continue
        dosis = ln.get("dosis_ha")
        dosis_f = float(dosis) if dosis not in (None, "") else None
        conn.execute(
            """INSERT INTO hydrawise_zona_fert
               (relay_id, producto_id, cantidad, dosis_ha, unidad, orden)
               VALUES (?,?,?,?,?,?)""",
            (rid, pid, cant, dosis_f, str(ln.get("unidad") or "kg"), i),
        )
    conn.commit()
    cc_u = (huerto_cc or "").strip().upper()
    if cc_u:
        demo = get_demo_module()
        valid = {(str(c) or "").strip().upper() for c in (getattr(demo, "CENTROS_COSTO", []) or [])}
        if valid and cc_u not in valid:
            return {
                "ok": True,
                "msg": f"Mapeo guardado. Advertencia: {cc_u} no está en la maestra CENTROS_COSTO.",
            }
    return {"ok": True, "msg": "Mapeo guardado."}


def parse_cola_lineas(form) -> list[tuple[int, float]]:
    relays = form.getlist("hw_relay_id")
    mins = form.getlist("hw_minutos")
    out: list[tuple[int, float]] = []
    for i, rid_raw in enumerate(relays):
        rid = str(rid_raw or "").strip()
        if not rid:
            continue
        try:
            minutos = float(str(mins[i] if i < len(mins) else "0").replace(",", "."))
        except ValueError:
            minutos = 0.0
        if minutos <= 0:
            continue
        out.append((int(rid), minutos))
    return out


def _fert_json_serializa(lineas: list[dict[str, Any]] | None) -> str:
    if lineas is None:
        return ""
    out: list[dict[str, Any]] = []
    for ln in lineas:
        if not isinstance(ln, dict):
            continue
        pid = int(ln.get("producto_id") or 0)
        cant = float(ln.get("cantidad") or 0)
        if pid <= 0 or cant <= 0:
            continue
        row: dict[str, Any] = {"producto_id": pid, "cantidad": cant}
        dosis = ln.get("dosis_ha")
        if dosis not in (None, ""):
            try:
                row["dosis_ha"] = float(dosis)
            except (TypeError, ValueError):
                pass
        out.append(row)
    return json.dumps(out, ensure_ascii=False)


def _fert_lineas_desde_json(raw: str | None) -> list[dict[str, Any]] | None:
    """None = sin columna / legacy (usar receta zona); [] = sin fertirriego explícito."""
    if raw is None:
        return None
    s = str(raw or "").strip()
    if not s:
        return None
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list):
        return []
    return [
        {
            "producto_id": int(x.get("producto_id") or 0),
            "cantidad": float(x.get("cantidad") or 0),
            "dosis_ha": x.get("dosis_ha"),
        }
        for x in data
        if isinstance(x, dict)
    ]


def parse_cola_lineas_form(form) -> list[dict[str, Any]]:
    """Líneas de cola con fertirriego opcional (JSON del link o arrays legacy)."""
    raw = (form.get("hw_lineas_json") or "").strip()
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, list):
            out: list[dict[str, Any]] = []
            for row in data:
                if not isinstance(row, dict):
                    continue
                try:
                    rid = int(row.get("relay_id") or 0)
                    minutos = float(str(row.get("minutos") or "0").replace(",", "."))
                except (TypeError, ValueError):
                    continue
                if rid <= 0 or minutos <= 0:
                    continue
                con = bool(row.get("con_fertilizacion"))
                fert_raw = row.get("fertilizantes")
                fert: list[dict[str, Any]] | None
                if not con:
                    fert = []
                elif isinstance(fert_raw, list):
                    fert = [
                        {
                            "producto_id": int(x.get("producto_id") or 0),
                            "cantidad": float(x.get("cantidad") or 0),
                            "dosis_ha": x.get("dosis_ha"),
                        }
                        for x in fert_raw
                        if isinstance(x, dict)
                    ]
                else:
                    fert = []
                out.append(
                    {"relay_id": rid, "minutos": minutos, "fertilizantes": fert}
                )
            if out:
                return out
    legacy = parse_cola_lineas(form)
    return [
        {"relay_id": rid, "minutos": mins, "fertilizantes": None} for rid, mins in legacy
    ]


def crear_cola(
    conn: sqlite3.Connection,
    *,
    tipo: str,
    inicio_programa: str,
    lineas: list[dict[str, Any]] | list[tuple[int, float]],
    usuario: str,
    regador_nombre: str = "",
) -> dict[str, Any]:
    from erp_solo_lectura import conn_en_solo_lectura

    if conn_en_solo_lectura(conn):
        return {"ok": False, "msg": "Solo lectura."}
    detalle: list[dict[str, Any]] = []
    for ln in lineas:
        if isinstance(ln, tuple):
            detalle.append(
                {"relay_id": int(ln[0]), "minutos": float(ln[1]), "fertilizantes": None}
            )
        else:
            detalle.append(ln)
    if not detalle:
        return {"ok": False, "msg": "Agregue al menos un sector con minutos."}
    vistos: set[int] = set()
    for ln in detalle:
        rid = int(ln["relay_id"])
        if rid in vistos:
            return {
                "ok": False,
                "msg": "No repita el mismo sector en una sola acción (regar ahora o programar).",
            }
        vistos.add(rid)
    migrar_hydrawise(conn)
    from demo_web.services.registro_riego import _validar_lineas_fertilizantes

    for ln in detalle:
        rid = int(ln["relay_id"])
        z = zona_por_relay(conn, rid)
        if not z:
            return {"ok": False, "msg": f"Zona {rid} no importada."}
        if not (z.get("huerto_cc") or "").strip():
            return {"ok": False, "msg": f"Falta CC en zona {z.get('nombre_hw')}."}
        fert_in = ln.get("fertilizantes")
        if fert_in is not None and fert_in:
            ok_f, msg_f, _ = _validar_lineas_fertilizantes(conn, fert_in)
            if not ok_f:
                return {"ok": False, "msg": msg_f}

    demo = get_demo_module()
    fh = demo.hora_chile().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("BEGIN IMMEDIATE")
    cur = conn.execute(
        """INSERT INTO hydrawise_cola (tipo, inicio_programa, estado, creado_por, creado_en)
           VALUES (?,?,?,?,?)""",
        (tipo, inicio_programa, "programado", usuario, fh),
    )
    cola_id = int(cur.lastrowid)
    for orden, ln in enumerate(detalle, start=1):
        rid = int(ln["relay_id"])
        minutos = float(ln["minutos"])
        fert_in = ln.get("fertilizantes")
        if fert_in is None:
            fert_save = _fert_json_serializa(_fert_lineas_desde_zona(conn, rid))
        else:
            fert_save = _fert_json_serializa(fert_in)
        conn.execute(
            """INSERT INTO hydrawise_cola_item
               (cola_id, orden, relay_id, minutos, estado, fert_json)
               VALUES (?,?,?,?, 'pendiente', ?)""",
            (cola_id, orden, rid, minutos, fert_save),
        )
    conn.commit()
    from demo_web.services.registro_riego import enviar_alerta_hydra_cola_inicio

    enviar_alerta_hydra_cola_inicio(
        cola_id=cola_id,
        tipo=tipo,
        inicio_programa=inicio_programa,
        regador=(regador_nombre or usuario or "Regador").strip(),
        items=_resumen_items_cola_mail(conn, cola_id),
    )
    return {"ok": True, "msg": f"Cola #{cola_id} creada ({len(detalle)} sector(es)).", "cola_id": cola_id}


def _cola_activa(conn: sqlite3.Connection) -> sqlite3.Row | None:
    migrar_hydrawise(conn)
    return conn.execute(
        """SELECT id, tipo, inicio_programa, estado, creado_por, creado_en
           FROM hydrawise_cola
           WHERE estado IN ('programado', 'en_ejecucion')
           ORDER BY id DESC LIMIT 1"""
    ).fetchone()


def _items_cola(conn: sqlite3.Connection, cola_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT id, orden, relay_id, minutos, estado, run_inicio, run_fin,
                  codigo_riego, error_msg, COALESCE(fert_json, '')
           FROM hydrawise_cola_item
           WHERE cola_id=? ORDER BY orden""",
        (cola_id,),
    ).fetchall()


def _fert_lineas_item_cola(
    conn: sqlite3.Connection, fert_json: str | None, relay_id: int
) -> list[dict[str, Any]]:
    from demo_web.services.registro_riego import filtrar_fert_lineas_bodega

    parsed = _fert_lineas_desde_json(fert_json)
    if parsed is not None:
        return filtrar_fert_lineas_bodega(conn, parsed)
    return _fert_lineas_desde_zona(conn, relay_id)


def editar_fert_item_cola(
    conn: sqlite3.Connection,
    item_id: int,
    *,
    con_fertilizacion: bool,
    fertilizantes: list[dict[str, Any]] | None,
    usuario: str,
) -> dict[str, Any]:
    from erp_solo_lectura import conn_en_solo_lectura

    if conn_en_solo_lectura(conn):
        return {"ok": False, "msg": "Solo lectura."}
    migrar_hydrawise(conn)
    row = conn.execute(
        """SELECT i.id, i.estado, i.relay_id, c.estado
           FROM hydrawise_cola_item i
           JOIN hydrawise_cola c ON c.id = i.cola_id
           WHERE i.id=?""",
        (int(item_id),),
    ).fetchone()
    if not row:
        return {"ok": False, "msg": "Ítem de cola no encontrado."}
    if str(row[1] or "") != "pendiente":
        return {"ok": False, "msg": "Solo puede editar fertirriego en sectores pendientes."}
    if str(row[3] or "") not in ("programado", "en_ejecucion"):
        return {"ok": False, "msg": "La cola ya no está activa."}
    if not con_fertilizacion:
        fert_save = "[]"
    else:
        from demo_web.services.registro_riego import _validar_lineas_fertilizantes

        lineas = fertilizantes or []
        ok_f, msg_f, val = _validar_lineas_fertilizantes(conn, lineas)
        if not ok_f:
            return {"ok": False, "msg": msg_f}
        fert_save = _fert_json_serializa(val)
    conn.execute(
        "UPDATE hydrawise_cola_item SET fert_json=? WHERE id=?",
        (fert_save, int(item_id)),
    )
    conn.commit()
    return {"ok": True, "msg": "Fertirriego actualizado para el sector en cola."}


def _resumen_items_cola_mail(conn: sqlite3.Connection, cola_id: int) -> list[dict[str, str]]:
    labels = {
        int(s["relay_id"]): s["label"]
        for s in sectores_para_link_riego(conn)
    }
    nombres = _map_nombres_fertilizante(conn)
    out: list[dict[str, str]] = []
    for it in _items_cola(conn, cola_id):
        rid = int(it[2])
        fert_lines = _fert_lineas_item_cola(conn, str(it[9] or ""), rid)
        fert_txt = "Sin fertirriego"
        if fert_lines:
            parts = []
            for f in fert_lines:
                pid = int(f.get("producto_id") or 0)
                cant = float(f.get("cantidad") or 0)
                parts.append(f"{nombres.get(pid, pid)} {cant:g}")
            fert_txt = "; ".join(parts)
        out.append(
            {
                "label": labels.get(rid) or f"Zona {rid}",
                "minutos": _fmt_minutos_riego(float(it[3])),
                "fert_txt": fert_txt,
            }
        )
    return out


def _alguna_zona_corriendo(status_data: dict[str, Any]) -> bool:
    mp = relay_status_map(status_data)
    return any(v.get("running") for v in mp.values())


def _zona_corriendo(status_data: dict[str, Any], relay_id: int) -> bool:
    mp = relay_status_map(status_data)
    st = mp.get(int(relay_id))
    return bool(st and st.get("running"))


def _fert_lineas_desde_zona(conn: sqlite3.Connection, relay_id: int) -> list[dict[str, Any]]:
    from demo_web.services.registro_riego import filtrar_fert_lineas_bodega

    z = zona_por_relay(conn, relay_id)
    if not z:
        return []
    raw = [
        {
            "producto_id": f["producto_id"],
            "cantidad": f["cantidad"],
            "dosis_ha": f.get("dosis_ha"),
        }
        for f in z.get("fertilizantes") or []
    ]
    return filtrar_fert_lineas_bodega(conn, raw)


def _last_api_sync_ts(conn: sqlite3.Connection) -> float:
    migrar_hydrawise(conn)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_meta (clave TEXT PRIMARY KEY, valor TEXT)"""
    )
    row = conn.execute(
        "SELECT valor FROM schema_meta WHERE clave=?", (META_LAST_SYNC,)
    ).fetchone()
    if not row:
        return 0.0
    try:
        return float(row[0])
    except (TypeError, ValueError):
        return 0.0


def _mark_api_sync(conn: sqlite3.Connection, ahora: datetime) -> None:
    from erp_solo_lectura import conn_en_solo_lectura

    if conn_en_solo_lectura(conn):
        return
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta (clave, valor) VALUES (?, ?)",
        (META_LAST_SYNC, str(ahora.timestamp())),
    )
    conn.commit()


def cooldown_restante_segundos(conn: sqlite3.Connection, ahora: datetime | None = None) -> int:
    demo = get_demo_module()
    t = ahora or demo.hora_chile()
    rem = SYNC_COOLDOWN_SEC - (t.timestamp() - _last_api_sync_ts(conn))
    return max(0, int(rem + 0.999))


def _label_zona(conn: sqlite3.Connection, relay_id: int) -> str:
    z = zona_por_relay(conn, int(relay_id))
    if not z:
        return f"Zona {relay_id}"
    nom = (z.get("nombre_hw") or f"Zona {relay_id}").strip()
    alias = (z.get("alias") or "").strip()
    if alias and alias.casefold() != nom.casefold():
        return f"{nom} — {alias}"
    return nom


def _horas_reales_desde_run(
    run_inicio: str,
    run_fin: str | None,
    minutos_prog: float,
    ahora: datetime,
) -> float:
    t0 = _parse_dt_chile(run_inicio)
    t1 = _parse_dt_chile(run_fin) if run_fin else ahora
    if not t0:
        return 0.0
    elapsed_h = max(0.0, (t1 - t0).total_seconds()) / 3600.0
    cap = float(minutos_prog) / 60.0
    if cap > 0:
        return min(elapsed_h, cap)
    return elapsed_h


def _imputar_item_cola(
    conn: sqlite3.Connection,
    ahora: datetime,
    *,
    item_id: int,
    relay_id: int,
    minutos: float,
    run_inicio: str,
    run_fin: str,
    usuario: str,
    cola_id: int,
    horas_override: float | None = None,
    event_key: str | None = None,
    notificar_ok: bool = True,
) -> dict[str, Any]:
    from demo_web.services.registro_riego import (
        enviar_alerta_hydra_sector_ok,
        registrar_desde_hydrawise,
        resolver_m3_registro,
    )

    key = event_key or f"cola{item_id}"
    if conn.execute(
        "SELECT 1 FROM hydrawise_importados WHERE event_key=?", (key,)
    ).fetchone():
        row = conn.execute(
            "SELECT codigo_riego FROM hydrawise_importados WHERE event_key=?", (key,)
        ).fetchone()
        cod = str(row[0]) if row else ""
        return {"ok": True, "msg": "Ya imputado.", "codigo": cod}

    z = zona_por_relay(conn, int(relay_id))
    if not z:
        return {"ok": False, "msg": f"Zona {relay_id} sin mapeo."}
    huerto = (z.get("huerto_cc") or "").strip()
    horas = (
        float(horas_override)
        if horas_override is not None
        else float(minutos) / 60.0
    )
    if horas <= 0:
        return {"ok": False, "msg": "Sin tiempo de riego para imputar.", "codigo": ""}
    fecha = (run_fin or run_inicio or str(ahora.date()))[:10]
    cola_row = conn.execute(
        "SELECT creado_por FROM hydrawise_cola WHERE id=?", (int(cola_id),)
    ).fetchone()
    regador = (
        str(cola_row[0] or "").strip()
        if cola_row and str(cola_row[0] or "").strip()
        else (usuario or "Regador")
    )
    item_row = conn.execute(
        "SELECT COALESCE(fert_json, '') FROM hydrawise_cola_item WHERE id=?",
        (int(item_id),),
    ).fetchone()
    fert_json = str(item_row[0] or "") if item_row else ""
    fert = _fert_lineas_item_cola(conn, fert_json, int(relay_id))
    res = registrar_desde_hydrawise(
        fecha,
        huerto,
        horas,
        regador,
        usuario,
        fertilizantes=fert if fert else None,
        modo_riego=z.get("modo_riego") or "horas",
        hydrawise_event_key=key,
        defer_bodega_fert=bool(fert),
    )
    if not res.get("ok"):
        return res
    cod = str(res.get("codigo") or "")
    fh = ahora.strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """INSERT INTO hydrawise_importados (event_key, codigo_riego, importado_en)
           VALUES (?,?,?)""",
        (key, cod, fh),
    )
    conn.execute(
        "UPDATE hydrawise_cola_item SET codigo_riego=?, estado='importado' WHERE id=?",
        (cod, item_id),
    )
    conn.commit()
    if notificar_ok:
        demo = get_demo_module()
        m3_val, _ = resolver_m3_registro(
            conn,
            huerto,
            horas,
            0.0,
            modo=z.get("modo_riego") or "horas",
        )
        from demo_web.services.registro_riego import _fmt_fertilizantes

        fert_txt = _fmt_fertilizantes(conn, cod, demo, None, None)
        enviar_alerta_hydra_sector_ok(
            codigo=cod,
            huerto=huerto,
            horas_fmt=demo.f_decimal(horas),
            m3_fmt=demo.f_decimal(m3_val or 0),
            fert_txt=fert_txt,
            sector_label=_label_zona(conn, int(relay_id)),
            cola_id=cola_id,
            fert_pendiente_confirmacion=bool(fert),
        )
    return {"ok": True, "msg": f"{cod} imputado ({huerto}).", "codigo": cod}


def _abortar_cola_activa(
    conn: sqlite3.Connection,
    usuario: str,
    operador: str,
    *,
    detener_hydrawise: bool,
    motivo: str,
) -> dict[str, Any]:
    from erp_solo_lectura import conn_en_solo_lectura

    if conn_en_solo_lectura(conn):
        return {"ok": False, "msg": "Solo lectura."}
    cola = _cola_activa(conn)
    if not cola:
        return {"ok": False, "msg": "No hay cola activa."}
    cola_id = int(cola[0])
    demo = get_demo_module()
    ahora = demo.hora_chile()
    fh = ahora.strftime("%Y-%m-%d %H:%M:%S")
    items = _items_cola(conn, cola_id)
    running = next((it for it in items if it[4] == "corriendo"), None)
    cod_parcial = ""
    sector_label = "— (programa no iniciado)"
    huerto = ""
    horas_fmt = "—"
    m3_fmt = "—"
    fert_txt = "—"

    if detener_hydrawise:
        key = get_api_key(conn)
        if not key:
            return {"ok": False, "msg": "Sin API key Hydrawise."}
        stop = set_zone_stop_all(key)
        _mark_api_sync(conn, ahora)
        if not stop.get("ok"):
            return {"ok": False, "msg": stop.get("error") or "No se pudo detener Hydrawise."}

    if running:
        item_id, _, relay_id, minutos, _, run_inicio, _, _, _, _ = partes_item(running)
        sector_label = _label_zona(conn, int(relay_id))
        z = zona_por_relay(conn, int(relay_id))
        huerto = (z.get("huerto_cc") or "").strip() if z else ""
        horas_real = _horas_reales_desde_run(str(run_inicio), fh, float(minutos), ahora)
        if horas_real > 0:
            imp = _imputar_item_cola(
                conn,
                ahora,
                item_id=int(item_id),
                relay_id=int(relay_id),
                minutos=float(minutos),
                run_inicio=str(run_inicio),
                run_fin=fh,
                usuario=usuario,
                cola_id=cola_id,
                horas_override=horas_real,
                event_key=f"cola{item_id}",
                notificar_ok=False,
            )
            if imp.get("ok") and imp.get("codigo"):
                cod_parcial = str(imp["codigo"])
                demo = get_demo_module()
                from demo_web.services.registro_riego import (
                    _fmt_fertilizantes,
                    resolver_m3_registro,
                )

                m3_val, _ = resolver_m3_registro(
                    conn,
                    huerto,
                    horas_real,
                    0.0,
                    modo=(z or {}).get("modo_riego") or "horas",
                )
                horas_fmt = demo.f_decimal(horas_real)
                m3_fmt = demo.f_decimal(m3_val or 0)
                fert_txt = _fmt_fertilizantes(conn, cod_parcial, demo, None, None)
            else:
                conn.execute(
                    "UPDATE hydrawise_cola_item SET estado='cancelado', run_fin=?, error_msg=? WHERE id=?",
                    (fh, str(imp.get("msg") or "")[:500], int(item_id)),
                )
        else:
            conn.execute(
                "UPDATE hydrawise_cola_item SET estado='cancelado', run_fin=? WHERE id=?",
                (fh, int(item_id)),
            )

    for it in _items_cola(conn, cola_id):
        if it[4] == "pendiente":
            conn.execute(
                "UPDATE hydrawise_cola_item SET estado='cancelado' WHERE id=?",
                (int(it[0]),),
            )
    conn.execute(
        "UPDATE hydrawise_cola SET estado='cancelada' WHERE id=?", (cola_id,)
    )
    conn.commit()

    from demo_web.services.registro_riego import enviar_alerta_hydra_interrupcion

    enviar_alerta_hydra_interrupcion(
        operador=operador or usuario,
        cola_id=cola_id,
        sector_label=sector_label,
        huerto=huerto,
        horas_fmt=horas_fmt,
        m3_fmt=m3_fmt,
        fert_txt=fert_txt,
        codigo=cod_parcial,
        motivo=motivo,
    )
    msg = f"Cola #{cola_id} cancelada."
    if cod_parcial:
        msg += f" Imputado parcial {cod_parcial} ({horas_fmt} h)."
    return {"ok": True, "msg": msg}


def _cola_turnos(cola: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Lista de ítems de cola (evita clave 'items' en plantillas Jinja)."""
    if not cola:
        return []
    turnos = cola.get("turnos")
    if turnos is not None:
        return list(turnos)
    legacy = cola.get("items")
    if isinstance(legacy, list):
        return legacy
    return []


def cola_permite_apagar(cola: dict[str, Any] | None) -> bool:
    """True si hay cola viva (no solo un programa futuro sin arrancar)."""
    if not cola:
        return False
    est = str(cola.get("estado") or "")
    if est == "en_ejecucion":
        return True
    items = _cola_turnos(cola)
    if any(str(it.get("estado") or "") == "corriendo" for it in items):
        return True
    activos = ("pendiente", "corriendo")
    if str(cola.get("tipo") or "") == "run_now":
        return any(str(it.get("estado") or "") in activos for it in items)
    if est == "programado":
        inicio = _parse_dt_chile(str(cola.get("inicio_programa") or ""))
        demo = get_demo_module()
        ahora = demo.hora_chile()
        if inicio and ahora >= inicio:
            return any(str(it.get("estado") or "") in activos for it in items)
    return False


def parar_riego_manual(conn: sqlite3.Connection, usuario: str, operador: str) -> dict[str, Any]:
    cola = _cola_activa(conn)
    if not cola:
        return {"ok": False, "msg": "No hay cola activa."}
    cola_id = int(cola[0])
    items = _items_cola(conn, cola_id)
    if not cola_permite_apagar(
        {
            "estado": cola[3],
            "tipo": cola[1],
            "inicio_programa": cola[2],
            "turnos": [
                {"estado": it[4]} for it in items
            ],
        }
    ):
        return {"ok": False, "msg": "No hay riego en curso. Use «Cancelar programa» si aún no arrancó."}
    return _abortar_cola_activa(
        conn,
        usuario,
        operador,
        detener_hydrawise=True,
        motivo="Apagar riego (link regador)",
    )


def cancelar_cola_manual(conn: sqlite3.Connection, usuario: str, operador: str) -> dict[str, Any]:
    cola = _cola_activa(conn)
    if not cola:
        return {"ok": False, "msg": "No hay cola activa."}
    en_curso = any(
        it[4] in ("corriendo", "pendiente") for it in _items_cola(conn, int(cola[0]))
    )
    if not en_curso and cola[3] == "programado":
        return _abortar_cola_activa(
            conn,
            usuario,
            operador,
            detener_hydrawise=False,
            motivo="Cancelar programa (link regador)",
        )
    return _abortar_cola_activa(
        conn,
        usuario,
        operador,
        detener_hydrawise=any(
            it[4] == "corriendo" for it in _items_cola(conn, int(cola[0]))
        ),
        motivo="Cancelar cola (link regador)",
    )


def _msg_riego_en_curso(minutos: float, run_inicio: str, ahora: datetime) -> str:
    t0 = _parse_dt_chile(run_inicio) or ahora
    elapsed = max(0.0, (ahora - t0).total_seconds())
    total = float(minutos) * 60.0
    rest = max(0.0, total - elapsed)
    rest_min = int(rest // 60) + (1 if rest % 60 else 0)
    return f"Riego en curso (~{rest_min} min restantes). Se actualiza solo al volver a esta pantalla."


def sincronizar_hydrawise(
    conn: sqlite3.Connection,
    usuario: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    from erp_solo_lectura import conn_en_solo_lectura

    if conn_en_solo_lectura(conn):
        return {"ok": False, "msg": "Solo lectura."}
    key = get_api_key(conn)
    if not key:
        return {"ok": False, "msg": "Configure API key en Administración."}

    migrar_hydrawise(conn)
    demo = get_demo_module()
    ahora = demo.hora_chile()
    msgs: list[str] = []
    importados = 0
    cooldown = cooldown_restante_segundos(conn, ahora)
    running_item = None

    cola = _cola_activa(conn)
    if not cola:
        return {"ok": True, "msg": ""}

    if cola:
        cola_id = int(cola[0])
        inicio_prog = str(cola[2] or "")
        inicio_dt = _parse_dt_chile(inicio_prog) or ahora
        if cola[3] == "programado" and ahora < inicio_dt:
            return {
                "ok": True,
                "msg": f"Cola #{cola_id} programada — arranca {inicio_prog[:16]}.",
            }

        items = _items_cola(conn, cola_id)
        running_item = next((it for it in items if it[4] == "corriendo"), None)
        if running_item:
            item_id, _, relay_id, minutos, _, run_inicio, _, _, _, _ = partes_item(running_item)
            t0 = _parse_dt_chile(str(run_inicio)) or ahora
            elapsed = (ahora - t0).total_seconds()
            dur = float(minutos) * 60.0
            if elapsed >= dur - 15:
                fh = ahora.strftime("%Y-%m-%d %H:%M:%S")
                conn.execute(
                    """UPDATE hydrawise_cola_item
                       SET estado='terminado', run_fin=?
                       WHERE id=?""",
                    (fh, item_id),
                )
                conn.commit()
                msgs.append(f"Zona {relay_id} terminó.")
            elif not force and cooldown > 0:
                return {
                    "ok": True,
                    "msg": _msg_riego_en_curso(float(minutos), str(run_inicio), ahora),
                }

    items_precheck = _items_cola(conn, int(cola[0])) if cola else []
    hay_terminados = any(it[4] == "terminado" and not it[7] for it in items_precheck)
    hay_pendiente_sin_correr = any(it[4] == "pendiente" for it in items_precheck) and not any(
        it[4] == "corriendo" for it in items_precheck
    )
    need_status_api = force or cooldown <= 0 or bool(msgs) or hay_pendiente_sin_correr

    status_data: dict[str, Any] = {}
    cid: int | None = None
    if need_status_api and (cola or force):
        cid, cid_err = _resolver_controller_id(conn, key)
        if cid_err:
            if _is_rate_limit_err(cid_err):
                return {"ok": True, "msg": ""}
            _write_probe_cache(
                conn, {"online": False, "ok": False, "msg": cid_err, "zonas": {}}
            )
            return {"ok": False, "msg": cid_err}
        st_resp = status_schedule(key, cid)
        status_data = st_resp.get("data") if st_resp.get("ok") else {}
        probe_out = _probe_resultado_desde_status(conn, st_resp, cid)
        if not probe_out.get("rate_limited"):
            _write_probe_cache(conn, probe_out)
        if not st_resp.get("ok") and st_resp.get("error"):
            if _is_rate_limit_err(str(st_resp.get("error"))):
                return {"ok": True, "msg": ""}
            return {"ok": False, "msg": _fmt_api_err(st_resp.get("error"))}
        _mark_api_sync(conn, ahora)
    elif cola and running_item and cooldown > 0 and not force:
        return {
            "ok": True,
            "msg": _msg_riego_en_curso(
                float(running_item[3]), str(running_item[5]), ahora
            ),
        }
    elif cola and cooldown > 0 and not force and not hay_terminados:
        return {
            "ok": True,
            "msg": f"Cola activa — próxima consulta a Hydrawise en ~{cooldown} s.",
        }

    if cola and running_item and status_data:
        item_id, _, relay_id, minutos, _, run_inicio, _, _, _, _ = partes_item(running_item)
        items = _items_cola(conn, int(cola[0]))
        running_item = next((it for it in items if it[4] == "corriendo"), None)
        if running_item:
            item_id, _, relay_id, minutos, _, run_inicio, _, _, _, _ = partes_item(running_item)
            if status_data and not _zona_corriendo(status_data, int(relay_id)):
                t0 = _parse_dt_chile(str(run_inicio)) or ahora
                elapsed = (ahora - t0).total_seconds()
                if elapsed >= float(minutos) * 60 - 15:
                    fh = ahora.strftime("%Y-%m-%d %H:%M:%S")
                    conn.execute(
                        """UPDATE hydrawise_cola_item
                           SET estado='terminado', run_fin=?
                           WHERE id=?""",
                        (fh, item_id),
                    )
                    conn.commit()
                    if f"Zona {relay_id} terminó." not in msgs:
                        msgs.append(f"Zona {relay_id} terminó.")
                else:
                    return {
                        "ok": True,
                        "msg": _msg_riego_en_curso(float(minutos), str(run_inicio), ahora),
                    }
            elif status_data:
                return {
                    "ok": True,
                    "msg": _msg_riego_en_curso(float(minutos), str(run_inicio), ahora),
                }

    if cola:
        cola_id = int(cola[0])
        items = _items_cola(conn, cola_id)
        for it in items:
            if it[4] != "terminado" or it[7]:
                continue
            item_id, _, relay_id, minutos, _, run_inicio, run_fin, _, _, _ = partes_item(it)
            res = _imputar_item_cola(
                conn,
                ahora,
                item_id=int(item_id),
                relay_id=int(relay_id),
                minutos=float(minutos),
                run_inicio=str(run_inicio),
                run_fin=str(
                    run_fin
                    or run_inicio
                    or ahora.strftime("%Y-%m-%d %H:%M:%S")
                ),
                usuario=usuario,
                cola_id=cola_id,
                notificar_ok=True,
            )
            if not res.get("ok"):
                conn.execute(
                    "UPDATE hydrawise_cola_item SET error_msg=? WHERE id=?",
                    (str(res.get("msg") or "")[:500], item_id),
                )
                conn.commit()
                return {"ok": False, "msg": res.get("msg") or "Error al imputar."}
            cod = str(res.get("codigo") or "")
            importados += 1
            msgs.append(res.get("msg") or f"{cod} imputado.")

        items = _items_cola(conn, cola_id)
        if all(it[4] in ("importado", "error") for it in items):
            conn.execute(
                "UPDATE hydrawise_cola SET estado='completado' WHERE id=?", (cola_id,)
            )
            conn.commit()
            return {
                "ok": True,
                "msg": "Cola completada. " + " ".join(msgs) if msgs else "Cola completada.",
            }

        hay_corriendo = any(it[4] == "corriendo" for it in items)
        pending = next((it for it in items if it[4] == "pendiente"), None)
        if pending and not hay_corriendo:
            if status_data and _alguna_zona_corriendo(status_data):
                return {
                    "ok": True,
                    "msg": "Hay otra zona corriendo en Hydrawise; espere a que termine.",
                }
            if cid is None:
                cid, cid_err = _resolver_controller_id(conn, key)
                if cid_err:
                    return {"ok": False, "msg": cid_err}
            item_id, _, relay_id, minutos, _, _, _, _, _, _ = partes_item(pending)
            sec = int(float(minutos) * 60)
            run = set_zone_run(key, int(relay_id), sec, controller_id=cid)
            _mark_api_sync(conn, ahora)
            if not run.get("ok"):
                conn.execute(
                    "UPDATE hydrawise_cola_item SET estado='error', error_msg=? WHERE id=?",
                    (str(run.get("error") or "")[:500], item_id),
                )
                conn.commit()
                return {"ok": False, "msg": run.get("error") or "No se pudo encender zona."}
            fh = ahora.strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                """UPDATE hydrawise_cola SET estado='en_ejecucion' WHERE id=?""",
                (cola_id,),
            )
            conn.execute(
                """UPDATE hydrawise_cola_item SET estado='corriendo', run_inicio=? WHERE id=?""",
                (fh, item_id),
            )
            conn.commit()
            return {
                "ok": True,
                "msg": f"Zona {relay_id} en riego ({minutos} min)."
                + (" " + " ".join(msgs) if msgs else ""),
            }

    if importados:
        return {"ok": True, "msg": " ".join(msgs)}
    return {"ok": True, "msg": "Nada pendiente por sincronizar."}


def listar_colas_recientes(conn: sqlite3.Connection, limite: int = 5) -> list[dict[str, Any]]:
    migrar_hydrawise(conn)
    rows = conn.execute(
        """SELECT id, tipo, inicio_programa, estado, creado_por, creado_en
           FROM hydrawise_cola ORDER BY id DESC LIMIT ?""",
        (limite,),
    ).fetchall()
    out = []
    for r in rows:
        cid = int(r[0])
        items = _items_cola(conn, cid)
        out.append(
            {
                "id": cid,
                "tipo": r[1],
                "inicio_programa": r[2],
                "estado": r[3],
                "creado_por": r[4],
                "creado_en": r[5],
                "turnos": [
                    {
                        "orden": it[1],
                        "relay_id": it[2],
                        "minutos": it[3],
                        "estado": it[4],
                        "codigo_riego": it[7],
                        "error_msg": it[8],
                    }
                    for it in items
                ],
            }
        )
    return out


def listar_bitacora_operativa(
    conn: sqlite3.Connection, limite: int = 40
) -> list[dict[str, Any]]:
    """Colas cerradas (cancelada, completada, etc.) — bitácora operativa HYDRA, no libro de riego."""
    migrar_hydrawise(conn)
    labels = {
        int(s["relay_id"]): s["label"] for s in sectores_para_link_riego(conn)
    }
    rows = conn.execute(
        """SELECT id, tipo, inicio_programa, estado, creado_por, creado_en
           FROM hydrawise_cola
           WHERE estado NOT IN ('programado', 'en_ejecucion')
           ORDER BY id DESC LIMIT ?""",
        (limite,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        cid = int(r[0])
        turnos: list[dict[str, Any]] = []
        importados = cancelados = 0
        for it in _items_cola(conn, cid):
            est = str(it[4])
            if est == "importado":
                importados += 1
            elif est == "cancelado":
                cancelados += 1
            rid = int(it[2])
            turnos.append(
                {
                    "orden": int(it[1]),
                    "relay_id": rid,
                    "label": labels.get(rid) or f"Zona {rid}",
                    "minutos": float(it[3]),
                    "estado": est,
                    "codigo_riego": it[7],
                    "error_msg": it[8],
                    "run_fin": it[6],
                }
            )
        n = len(turnos)
        partes: list[str] = [f"{n} sector(es)"]
        if importados:
            partes.append(f"{importados} al historial")
        if cancelados:
            partes.append(f"{cancelados} cancelado(s)")
        out.append(
            {
                "id": cid,
                "tipo": r[1],
                "inicio_programa": r[2],
                "estado": r[3],
                "creado_por": r[4],
                "creado_en": r[5],
                "resumen": " · ".join(partes),
                "turnos": turnos,
            }
        )
    return out


def sectores_para_link_riego(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Sectores importados de Hydrawise para Link riego (misma lista que HYDRA, con CC)."""
    if not lc_contexto_hydra():
        return []
    out: list[dict[str, Any]] = []
    for z in listar_zonas(conn):
        if not z.get("activo"):
            continue
        if not z.get("link_riego", 1):
            continue
        cc = (z.get("huerto_cc") or "").strip()
        if not cc:
            continue
        nom = (z.get("nombre_hw") or f"Zona {z['relay_id']}").strip()
        alias = (z.get("alias") or "").strip()
        label = nom
        if alias and alias.casefold() != nom.casefold():
            label = f"{nom} — {alias}"
        out.append(
            {
                "relay_id": int(z["relay_id"]),
                "label": label,
                "huerto_cc": cc,
                "modo_riego": z.get("modo_riego") or "horas",
                "fertilizantes": _fert_lineas_desde_zona(conn, int(z["relay_id"])),
            }
        )
    out.sort(key=lambda x: x["label"].casefold())
    return out


def resolver_sector_link(conn: sqlite3.Connection, relay_id: int) -> dict[str, Any] | None:
    for s in sectores_para_link_riego(conn):
        if s["relay_id"] == int(relay_id):
            return s
    return None


def _read_contact_cache(conn: sqlite3.Connection) -> dict[str, Any] | None:
    migrar_hydrawise(conn)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_meta (clave TEXT PRIMARY KEY, valor TEXT)"""
    )
    row = conn.execute(
        "SELECT valor FROM schema_meta WHERE clave=?", (META_LAST_CONTACT,)
    ).fetchone()
    if not row:
        return None
    try:
        data = json.loads(str(row[0] or ""))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _write_contact_cache(
    conn: sqlite3.Connection,
    controller_id: int,
    last_contact_ts: float,
) -> None:
    from erp_solo_lectura import conn_en_solo_lectura

    if conn_en_solo_lectura(conn):
        return
    demo = get_demo_module()
    payload = {
        "controller_id": int(controller_id),
        "last_contact_ts": float(last_contact_ts),
        "fetched_ts": demo.hora_chile().timestamp(),
    }
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta (clave, valor) VALUES (?, ?)",
        (META_LAST_CONTACT, json.dumps(payload, ensure_ascii=False)),
    )
    conn.commit()


def _ultimo_contacto_controlador(
    conn: sqlite3.Connection,
    key: str,
    controller_id: int,
    *,
    now_ts: float,
    allow_fetch: bool = True,
) -> float | None:
    """last_contact vía customerdetails (cache 5 min) — statusschedule LC no lo trae."""
    cached = _read_contact_cache(conn)
    cid = int(controller_id)
    if cached and int(cached.get("controller_id") or 0) == cid:
        lc = float(cached.get("last_contact_ts") or 0)
        fetched = float(cached.get("fetched_ts") or 0)
        if lc > 0 and (now_ts - fetched) < CONTACT_REFRESH_SEC:
            return lc

    if not allow_fetch:
        if cached and int(cached.get("controller_id") or 0) == cid:
            lc = float(cached.get("last_contact_ts") or 0)
            return lc if lc > 0 else None
        return None

    cd = customer_details(key)
    if cd.get("ok"):
        lc = last_contact_from_customer(cd.get("data") or {}, cid)
        if lc is not None:
            _write_contact_cache(conn, cid, lc)
            return lc
    if cached and int(cached.get("controller_id") or 0) == cid:
        lc = float(cached.get("last_contact_ts") or 0)
        return lc if lc > 0 else None
    return None


def _read_probe_cache(conn: sqlite3.Connection) -> dict[str, Any] | None:
    migrar_hydrawise(conn)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_meta (clave TEXT PRIMARY KEY, valor TEXT)"""
    )
    row = conn.execute(
        "SELECT valor FROM schema_meta WHERE clave=?", (META_LAST_PROBE,)
    ).fetchone()
    if not row:
        return None
    try:
        data = json.loads(str(row[0] or ""))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _probe_resultado_desde_status(
    conn: sqlite3.Connection,
    st_resp: dict[str, Any],
    cid: int | None,
) -> dict[str, Any]:
    if not st_resp.get("ok"):
        err = st_resp.get("error") or "Sin respuesta del controlador"
        if _is_rate_limit_err(str(err)):
            fallback = _probe_desde_cache(
                conn,
                nota="consulta en pausa (límite Hydrawise)",
            )
            if fallback:
                return fallback
        msg = _fmt_api_err(str(err))
        return {
            "online": False,
            "ok": False,
            "api_ok": False,
            "msg": msg,
            "title": "Sin conexión a Hydrawise",
            "zonas": {},
        }
    data = st_resp.get("data") or {}
    mp = relay_status_map(data)
    ref = get_equipo_ref(conn) or str(cid or "")
    n_z = len(mp)
    n_run = sum(1 for v in mp.values() if v.get("running"))
    extra = f" · {n_run} regando" if n_run else ""
    return {
        "online": True,
        "ok": True,
        "api_ok": True,
        "title": "Controlador en línea",
        "msg": f"En línea · {ref} · {n_z} zona(s){extra}",
        "zonas": mp,
    }


def _write_probe_cache(conn: sqlite3.Connection, payload: dict[str, Any]) -> None:
    from erp_solo_lectura import conn_en_solo_lectura

    if conn_en_solo_lectura(conn):
        return
    demo = get_demo_module()
    ts = demo.hora_chile().timestamp()
    slim = {
        "online": bool(payload.get("online")),
        "ok": bool(payload.get("ok")),
        "msg": str(payload.get("msg") or ""),
        "title": str(payload.get("title") or ""),
        "ts": ts,
    }
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta (clave, valor) VALUES (?, ?)",
        (META_LAST_PROBE, json.dumps(slim, ensure_ascii=False)),
    )
    conn.commit()


def estado_conexion_controlador(
    conn: sqlite3.Connection,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Testigo link móvil: statusschedule con cache (~90 s) anti-429."""
    key = get_api_key(conn)
    if not key:
        return {
            "online": False,
            "ok": False,
            "msg": "Sin API Hydrawise — avise a administración.",
            "zonas": {},
        }

    demo = get_demo_module()
    ahora = demo.hora_chile()
    cached = _read_probe_cache(conn)
    if cached and not force:
        try:
            age = ahora.timestamp() - float(cached.get("ts") or 0)
        except (TypeError, ValueError):
            age = PROBE_COOLDOWN_SEC + 1
        if age < PROBE_COOLDOWN_SEC:
            return {
                "online": bool(cached.get("online")),
                "ok": bool(cached.get("ok")),
                "msg": str(cached.get("msg") or ""),
                "title": str(cached.get("title") or ""),
                "zonas": {},
                "cached": True,
                "probe_age_sec": int(age),
            }

    cid, err = _resolver_controller_id(conn, key)
    if err:
        if _is_rate_limit_err(err):
            fallback = _probe_desde_cache(
                conn,
                nota="consulta en pausa (límite Hydrawise)",
            )
            if fallback:
                return fallback
        out = {"online": False, "ok": False, "msg": err, "zonas": {}}
        if not _is_rate_limit_err(err):
            _write_probe_cache(conn, out)
        return out

    st_resp = status_schedule(key, cid)
    out = _probe_resultado_desde_status(conn, st_resp, cid)
    if not out.get("rate_limited"):
        _write_probe_cache(conn, out)
    out["cached"] = False
    out["probe_age_sec"] = 0
    if not out.get("title"):
        out["title"] = (
            "Controlador en línea" if out.get("online") else "Sin conexión a Hydrawise"
        )
    return out


def snapshot_live_zonas(conn: sqlite3.Connection) -> dict[str, Any]:
    """Consulta statusschedule (p. ej. acciones legacy); actualiza testigo."""
    probe = estado_conexion_controlador(conn, force=True)
    return {
        "ok": probe.get("ok", False),
        "msg": probe.get("msg") or ("Conexión verificada." if probe.get("online") else "Sin conexión."),
        "zonas": probe.get("zonas") or {},
    }


def _parse_dt_chile(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace(" ", "T")[:19])
    except ValueError:
        return None


def _fmt_minutos_riego(minutos: float) -> str:
    m = float(minutos or 0)
    if m <= 0:
        return "—"
    total = int(round(m))
    if total < 60:
        return f"{total} min"
    h, r = divmod(total, 60)
    if r:
        return f"{h} h {r} min"
    return f"{h} h"


def _map_nombres_fertilizante(conn: sqlite3.Connection) -> dict[int, str]:
    rows = conn.execute(
        """SELECT id, producto FROM inventario
           WHERE UPPER(TRIM(COALESCE(familia, ''))) IN ('FERTILIZANTE')
           ORDER BY producto COLLATE NOCASE"""
    ).fetchall()
    return {int(r[0]): str(r[1] or "").strip() or f"#{r[0]}" for r in rows}


def _inicio_estimado_pendiente(
    cola: dict[str, Any],
    items: list[dict[str, Any]],
    item: dict[str, Any],
    ahora: datetime,
) -> datetime:
    ordenados = sorted(items, key=lambda x: int(x["orden"]))
    inicio_prog = _parse_dt_chile(cola.get("inicio_programa")) or ahora
    cola_est = str(cola.get("estado") or "")
    if cola_est == "programado" and inicio_prog > ahora:
        prev = sum(
            float(it["minutos"])
            for it in ordenados
            if int(it["orden"]) < int(item["orden"])
        )
        return inicio_prog + timedelta(minutes=prev)

    t = ahora
    for it in ordenados:
        if int(it["orden"]) >= int(item["orden"]):
            break
        est = str(it.get("estado") or "")
        if est == "corriendo":
            t0 = _parse_dt_chile(it.get("run_inicio")) or ahora
            rem = max(0.0, float(it["minutos"]) - (ahora - t0).total_seconds() / 60.0)
            t = ahora + timedelta(minutes=rem)
        elif est == "pendiente":
            t = t + timedelta(minutes=float(it["minutos"]))
        else:
            fin = _parse_dt_chile(it.get("run_fin"))
            if fin and fin > t:
                t = fin
    return t


def programa_por_relay_en_cola(
    conn: sqlite3.Connection,
    cola: dict[str, Any] | None,
) -> dict[int, dict[str, Any]]:
    """Detalle de programación (inicio, minutos, fertirriego) por relay en cola activa."""
    if not cola:
        return {}
    demo = get_demo_module()
    ahora = demo.hora_chile()
    items = _cola_turnos(cola)
    nombres = _map_nombres_fertilizante(conn)
    inicio_prog = _parse_dt_chile(cola.get("inicio_programa"))
    inicio_prog_fmt = inicio_prog.strftime("%d/%m/%Y %H:%M") if inicio_prog else "—"
    tipo = str(cola.get("tipo") or "")
    tipo_label = "Programado" if tipo == "programado" else "Regar ahora"

    out: dict[int, dict[str, Any]] = {}
    for it in items:
        if str(it.get("estado") or "") != "pendiente":
            continue
        rid = int(it["relay_id"])
        fert_src = _fert_lineas_item_cola(
            conn, str(it.get("fert_json") or ""), rid
        )
        fert_lines: list[dict[str, Any]] = []
        for f in fert_src:
            pid = int(f.get("producto_id") or 0)
            cant = float(f.get("cantidad") or 0)
            if pid <= 0 or cant <= 0:
                continue
            um = str(f.get("unidad") or "kg")
            dosis = f.get("dosis_ha")
            line = {
                "nombre": nombres.get(pid) or f"Producto #{pid}",
                "cantidad": cant,
                "cantidad_fmt": f"{cant:g} {um}",
                "dosis_ha": dosis,
            }
            if dosis not in (None, ""):
                try:
                    line["dosis_fmt"] = f"{float(dosis):g} / ha"
                except (TypeError, ValueError):
                    line["dosis_fmt"] = ""
            fert_lines.append(line)
        est_dt = _inicio_estimado_pendiente(cola, items, it, ahora)
        out[rid] = {
            "orden": int(it["orden"]),
            "minutos": float(it["minutos"]),
            "minutos_fmt": _fmt_minutos_riego(float(it["minutos"])),
            "inicio_programa_fmt": inicio_prog_fmt,
            "inicio_estimado_fmt": est_dt.strftime("%d/%m %H:%M"),
            "tipo_label": tipo_label,
            "tiene_fertirriego": bool(fert_lines),
            "fertilizantes": fert_lines,
        }
    return out


def contexto_control_hydra_ui(
    conn: sqlite3.Connection,
    usuario: str,
    *,
    auto_sync: bool = False,
) -> dict[str, Any]:
    """Contexto compartido link regador y módulo Riego → Registro manual (LC)."""
    hydra_sectores = sectores_para_link_riego(conn)
    hydra_cola = cola_activa_en_link(conn)
    programa_por_relay = programa_por_relay_en_cola(conn, hydra_cola)
    hydra_mostrar_apagar = cola_permite_apagar(hydra_cola)
    hydra_sync_cooldown = cooldown_restante_segundos(conn)

    hydra_msg = ""
    hydra_ok = True
    if auto_sync and hydra_sectores and hydra_cola and hydra_sync_cooldown <= 0:
            auto = sincronizar_hydrawise(conn, usuario, force=False)
            msg = str(auto.get("msg") or "").strip()
            if msg and "429" not in msg and not msg.startswith("Cola activa — próxima"):
                hydra_msg = msg
                hydra_ok = bool(auto.get("ok", True))

    probe = estado_conexion_controlador(conn, force=False)
    live_zonas = probe.get("zonas") or {}
    hydra_conn_online = bool(probe.get("online"))
    hydra_conn_msg = str(probe.get("msg") or "")
    hydra_conn_title = str(probe.get("title") or "")
    hydra_conn_cached = bool(probe.get("cached"))
    hydra_probe_age_sec = int(probe.get("probe_age_sec") or 0)

    running_relay_ids: set[int] = set()
    queued_relay_ids: set[int] = set()
    if hydra_cola:
        cola_est = str(hydra_cola.get("estado") or "")
        cola_viva = cola_est in ("programado", "en_ejecucion")
        for it in _cola_turnos(hydra_cola):
            rid = int(it["relay_id"])
            item_est = str(it.get("estado") or "")
            if item_est == "corriendo":
                running_relay_ids.add(rid)
            elif cola_viva and item_est == "pendiente":
                queued_relay_ids.add(rid)
    queued_relay_ids -= running_relay_ids
    for rid, st in live_zonas.items():
        if isinstance(st, dict) and st.get("running"):
            rid_i = int(rid)
            running_relay_ids.add(rid_i)
            queued_relay_ids.discard(rid_i)

    return {
        "hydra_control_activo": bool(hydra_sectores),
        "hydra_sectores": hydra_sectores,
        "hydra_cola": hydra_cola,
        "programa_por_relay": programa_por_relay,
        "hydra_mostrar_apagar": hydra_mostrar_apagar,
        "hydra_cola_programada": bool(
            hydra_cola
            and str(hydra_cola.get("estado") or "") == "programado"
            and not hydra_mostrar_apagar
        ),
        "hydra_sync_cooldown": hydra_sync_cooldown,
        "hydra_msg": hydra_msg,
        "hydra_ok": hydra_ok,
        "hydra_conn_online": hydra_conn_online,
        "hydra_conn_msg": hydra_conn_msg,
        "hydra_conn_title": hydra_conn_title,
        "hydra_conn_cached": hydra_conn_cached,
        "hydra_probe_age_sec": hydra_probe_age_sec,
        "running_relay_ids": sorted(running_relay_ids),
        "queued_relay_ids": sorted(queued_relay_ids),
    }


def cola_activa_en_link(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Cola programada o en ejecución, con ítems enriquecidos para el link regador."""
    row = _cola_activa(conn)
    if not row:
        return None
    cola_id = int(row[0])
    labels = {
        int(s["relay_id"]): s["label"]
        for s in sectores_para_link_riego(conn)
    }
    items = []
    for it in _items_cola(conn, cola_id):
        rid = int(it[2])
        fert_json = str(it[9] or "")
        fert_lineas = _fert_lineas_item_cola(conn, fert_json, rid)
        items.append(
            {
                "id": int(it[0]),
                "orden": int(it[1]),
                "relay_id": rid,
                "label": labels.get(rid) or f"Zona {rid}",
                "minutos": float(it[3]),
                "estado": str(it[4]),
                "run_inicio": it[5],
                "run_fin": it[6],
                "codigo_riego": it[7],
                "error_msg": it[8],
                "fert_json": fert_json,
                "con_fertilizacion": bool(fert_lineas),
                "fertilizantes": fert_lineas,
            }
        )
    return {
        "id": cola_id,
        "tipo": row[1],
        "inicio_programa": row[2],
        "estado": row[3],
        "creado_por": row[4],
        "creado_en": row[5],
        "turnos": items,
    }


def api_lista_para_link(conn: sqlite3.Connection) -> tuple[bool, str]:
    """Solo indica que administración configuró API/equipo (no es estado de riego en campo)."""
    key = get_api_key(conn)
    if not key:
        return False, "HYDRA sin configurar — avise a administración (API Hydrawise)."
    ref = get_equipo_ref(conn)
    if ref:
        return True, f"Conexión HYDRA OK · controlador {ref}"
    return True, "Conexión HYDRA OK · falta serial del controlador en Administración."


def crear_cola_desde_form(form, *, tipo: str, usuario: str, inicio_programa: str) -> dict[str, Any]:
    lineas = parse_cola_lineas_form(form)
    conn = _conn()
    try:
        return crear_cola(
            conn,
            tipo=tipo,
            inicio_programa=inicio_programa,
            lineas=lineas,
            usuario=usuario,
            regador_nombre=usuario,
        )
    finally:
        conn.close()
