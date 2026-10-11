"""Integración Hydrawise (Hydra) — solo tenant La Concepción."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from demo_web.services.demo_loader import get_demo_module
from demo_web.services.hydrawise_client import (
    customer_details,
    flatten_relays,
    flatten_relays_from_status,
    list_controllers,
    relay_status_map,
    set_zone_run,
    status_schedule,
)
from demo_web.services.tenant_scope import is_concepcion_tenant

META_KEY_API = "hydrawise_api_key_v1"
META_KEY_CONTROLLER = "hydrawise_controller_id_v1"


def _fmt_api_err(err: str) -> str:
    if "429" in str(err):
        return (
            "Hydrawise limitó las consultas (HTTP 429). Espere 1–2 minutos "
            "y use solo «Probar conexión» o «Sincronizar» (no recargue HYDRA en loop)."
        )
    return str(err)


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
    resp = customer_details(key)
    if not resp.get("ok"):
        return None, _fmt_api_err(resp.get("error") or "Error")
    equipos = list_controllers(resp.get("data") or {})
    ref = get_equipo_ref(conn)
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


def _parse_cola_lineas(form) -> list[tuple[int, float]]:
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


def crear_cola(
    conn: sqlite3.Connection,
    *,
    tipo: str,
    inicio_programa: str,
    lineas: list[tuple[int, float]],
    usuario: str,
) -> dict[str, Any]:
    from erp_solo_lectura import conn_en_solo_lectura

    if conn_en_solo_lectura(conn):
        return {"ok": False, "msg": "Solo lectura."}
    if not lineas:
        return {"ok": False, "msg": "Agregue al menos un sector con minutos."}
    migrar_hydrawise(conn)
    for rid, _ in lineas:
        z = zona_por_relay(conn, rid)
        if not z:
            return {"ok": False, "msg": f"Zona {rid} no importada."}
        if not (z.get("huerto_cc") or "").strip():
            return {"ok": False, "msg": f"Falta CC en zona {z.get('nombre_hw')}."}

    demo = get_demo_module()
    fh = demo.hora_chile().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("BEGIN IMMEDIATE")
    cur = conn.execute(
        """INSERT INTO hydrawise_cola (tipo, inicio_programa, estado, creado_por, creado_en)
           VALUES (?,?,?,?,?)""",
        (tipo, inicio_programa, "programado", usuario, fh),
    )
    cola_id = int(cur.lastrowid)
    for orden, (rid, minutos) in enumerate(lineas, start=1):
        conn.execute(
            """INSERT INTO hydrawise_cola_item
               (cola_id, orden, relay_id, minutos, estado)
               VALUES (?,?,?,?, 'pendiente')""",
            (cola_id, orden, rid, float(minutos)),
        )
    conn.commit()
    return {"ok": True, "msg": f"Cola #{cola_id} creada ({len(lineas)} sector(es)).", "cola_id": cola_id}


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
                  codigo_riego, error_msg
           FROM hydrawise_cola_item
           WHERE cola_id=? ORDER BY orden""",
        (cola_id,),
    ).fetchall()


def _alguna_zona_corriendo(status_data: dict[str, Any]) -> bool:
    mp = relay_status_map(status_data)
    return any(v.get("running") for v in mp.values())


def _zona_corriendo(status_data: dict[str, Any], relay_id: int) -> bool:
    mp = relay_status_map(status_data)
    st = mp.get(int(relay_id))
    return bool(st and st.get("running"))


def _fert_lineas_desde_zona(conn: sqlite3.Connection, relay_id: int) -> list[dict[str, Any]]:
    z = zona_por_relay(conn, relay_id)
    if not z:
        return []
    return [
        {
            "producto_id": f["producto_id"],
            "cantidad": f["cantidad"],
            "dosis_ha": f.get("dosis_ha"),
        }
        for f in z.get("fertilizantes") or []
    ]


def sincronizar_hydrawise(conn: sqlite3.Connection, usuario: str) -> dict[str, Any]:
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

    cid, cid_err = _resolver_controller_id(conn, key)
    if cid_err:
        return {"ok": False, "msg": cid_err}
    st_resp = status_schedule(key, cid)
    status_data = st_resp.get("data") if st_resp.get("ok") else {}
    if not st_resp.get("ok") and st_resp.get("error"):
        return {"ok": False, "msg": _fmt_api_err(st_resp.get("error"))}

    cola = _cola_activa(conn)
    if cola:
        cola_id = int(cola[0])
        inicio_prog = str(cola[2] or "")
        try:
            inicio_dt = datetime.fromisoformat(inicio_prog.replace(" ", "T")[:19])
        except ValueError:
            inicio_dt = ahora
        if cola[3] == "programado" and ahora < inicio_dt:
            return {
                "ok": True,
                "msg": f"Programa #{cola_id} arranca a las {inicio_prog[:16]}.",
            }

        items = _items_cola(conn, cola_id)
        running_item = next((it for it in items if it[4] == "corriendo"), None)
        if running_item:
            item_id, _, relay_id, minutos, _, run_inicio, _, _, _ = running_item
            if st_resp.get("ok") and not _zona_corriendo(status_data, int(relay_id)):
                try:
                    t0 = datetime.fromisoformat(str(run_inicio).replace(" ", "T")[:19])
                    elapsed = (ahora - t0).total_seconds()
                except ValueError:
                    elapsed = float(minutos) * 60
                if elapsed >= float(minutos) * 60 - 15:
                    fh = ahora.strftime("%Y-%m-%d %H:%M:%S")
                    conn.execute(
                        """UPDATE hydrawise_cola_item
                           SET estado='terminado', run_fin=?
                           WHERE id=?""",
                        (fh, item_id),
                    )
                    conn.commit()
                    msgs.append(f"Zona {relay_id} terminó.")
                else:
                    return {"ok": True, "msg": "Riego en curso… espere y sincronice de nuevo."}
            else:
                return {"ok": True, "msg": "Riego en curso en Hydrawise…"}

        items = _items_cola(conn, cola_id)
        for it in items:
            if it[4] != "terminado" or it[7]:
                continue
            item_id, _, relay_id, minutos, _, run_inicio, run_fin, _, _ = it
            event_key = f"cola{item_id}"
            if conn.execute(
                "SELECT 1 FROM hydrawise_importados WHERE event_key=?", (event_key,)
            ).fetchone():
                continue
            z = zona_por_relay(conn, int(relay_id))
            if not z:
                continue
            huerto = (z.get("huerto_cc") or "").strip()
            horas = float(minutos) / 60.0
            fecha = (run_fin or run_inicio or str(ahora.date()))[:10]
            regador = f"Hydrawise — {z.get('alias') or z.get('nombre_hw')}"
            fert = _fert_lineas_desde_zona(conn, int(relay_id))
            from demo_web.services.registro_riego import registrar_desde_hydrawise

            res = registrar_desde_hydrawise(
                fecha,
                huerto,
                horas,
                regador,
                usuario,
                fertilizantes=fert if fert else None,
                modo_riego=z.get("modo_riego") or "horas",
                hydrawise_event_key=event_key,
            )
            if not res.get("ok"):
                conn.execute(
                    "UPDATE hydrawise_cola_item SET error_msg=? WHERE id=?",
                    (str(res.get("msg") or "")[:500], item_id),
                )
                conn.commit()
                return {"ok": False, "msg": res.get("msg") or "Error al imputar."}
            cod = str(res.get("codigo") or "")
            fh = ahora.strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                """INSERT INTO hydrawise_importados (event_key, codigo_riego, importado_en)
                   VALUES (?,?,?)""",
                (event_key, cod, fh),
            )
            conn.execute(
                "UPDATE hydrawise_cola_item SET codigo_riego=?, estado='importado' WHERE id=?",
                (cod, item_id),
            )
            conn.commit()
            importados += 1
            msgs.append(f"{cod} imputado ({huerto}).")

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
            if st_resp.get("ok") and _alguna_zona_corriendo(status_data):
                return {
                    "ok": True,
                    "msg": "Hay otra zona corriendo en Hydrawise; espere a que termine.",
                }
            item_id, _, relay_id, minutos, _, _, _, _, _ = pending
            sec = int(float(minutos) * 60)
            run = set_zone_run(key, int(relay_id), sec, controller_id=cid)
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
                "msg": f"Zona {relay_id} en riego ({minutos} min). Al terminar, sincronice de nuevo."
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
                "items": [
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
                "fertilizantes": [
                    {
                        "producto_id": f["producto_id"],
                        "cantidad": f["cantidad"],
                        "dosis_ha": f.get("dosis_ha"),
                    }
                    for f in z.get("fertilizantes") or []
                ],
            }
        )
    out.sort(key=lambda x: x["label"].casefold())
    return out


def resolver_sector_link(conn: sqlite3.Connection, relay_id: int) -> dict[str, Any] | None:
    for s in sectores_para_link_riego(conn):
        if s["relay_id"] == int(relay_id):
            return s
    return None


def crear_cola_desde_form(form, *, tipo: str, usuario: str, inicio_programa: str) -> dict[str, Any]:
    lineas = _parse_cola_lineas(form)
    conn = _conn()
    try:
        return crear_cola(
            conn,
            tipo=tipo,
            inicio_programa=inicio_programa,
            lineas=lineas,
            usuario=usuario,
        )
    finally:
        conn.close()
