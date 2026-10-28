from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)

from demo_web.auth.decorators import login_required
from demo_web.services.demo_loader import get_demo_module
from demo_web.services.erp_loader import bind_tenant_context
from demo_web.services.public_link_tenant import tenant_slug_from_query
from demo_web.services.hydrawise_riego import _cola_turnos, lc_contexto_hydra
from demo_web.services.registro_riego import (
    aplicar_cookie_operador,
    config_riego_cc_para_formulario,
    fertilizantes_bodega_para_formulario,
    habilitado,
    huerto_tiene_calculo_auto,
    huertos_para_formulario,
    _norm_cc,
    leer_operador_cookie,
    parse_fertilizantes_request,
    registrar_link,
    regadores_autorizados_para_formulario,
    resolver_regador_por_id,
    token_valido,
)

bp = Blueprint("registro_riego", __name__)

_HONEYPOT_FIELD = "sr_hp_x9f2"
_HYDRA_TABS = frozenset({"control", "regar", "programar", "bitacora"})


def _tab_despues_hydra_action(action: str) -> str:
    if action == "hydra_regar_ahora":
        return "regar"
    if action == "hydra_programar":
        return "programar"
    raw = (request.form.get("tab") or "control").strip().lower()
    if raw in _HYDRA_TABS:
        return raw
    return "control"


def _token_request() -> str | None:
    return (request.args.get("t") or request.form.get("t") or "").strip() or None


def _bind_tenant_from_request() -> None:
    q = tenant_slug_from_query()
    slug = "demo" if q == "demo" else "concepcion"
    bind_tenant_context(slug)


def _usuario_operador(operador: dict | None) -> str:
    return str((operador or {}).get("nombre") or "Regador link").strip()


def _cargar_hydra_sectores(demo) -> list[dict]:
    if not lc_contexto_hydra():
        return []
    conn = demo.conectar_db()
    try:
        from demo_web.services.hydrawise_riego import sectores_para_link_riego

        return sectores_para_link_riego(conn)
    finally:
        conn.close()


def _handle_hydra_action(
    demo,
    conn,
    operador: dict,
    action: str,
) -> dict:
    from demo_web.services import hydrawise_riego as hw

    usuario = _usuario_operador(operador)
    operador_nombre = str(operador.get("nombre") or usuario)
    if action == "hydra_refresh_estado":
        return hw.snapshot_live_zonas(conn)
    if action == "hydra_editar_fert_item":
        item_id = int(request.form.get("cola_item_id") or 0)
        con_fert = request.form.get("con_fertilizacion") == "1"
        fert = parse_fertilizantes_request(request.form) if con_fert else []
        return hw.editar_fert_item_cola(
            conn,
            item_id,
            con_fertilizacion=con_fert,
            fertilizantes=fert,
            usuario=usuario,
        )
    if action == "hydra_regar_ahora":
        inicio = demo.hora_chile().strftime("%Y-%m-%d %H:%M:%S")
        lineas = hw.parse_cola_lineas_form(request.form)
        result = hw.crear_cola(
            conn,
            tipo="run_now",
            inicio_programa=inicio,
            lineas=lineas,
            usuario=usuario,
            regador_nombre=operador_nombre,
        )
        if result.get("ok"):
            sync = hw.sincronizar_hydrawise(conn, usuario, force=True)
            result = {
                "ok": sync.get("ok", True),
                "msg": (result.get("msg") or "") + " " + (sync.get("msg") or ""),
            }
        return result
    if action == "hydra_programar":
        inicio = (request.form.get("inicio_programa") or "").strip().replace("T", " ")
        if len(inicio) == 16:
            inicio += ":00"
        lineas = hw.parse_cola_lineas_form(request.form)
        result = hw.crear_cola(
            conn,
            tipo="programado",
            inicio_programa=inicio,
            lineas=lineas,
            usuario=usuario,
            regador_nombre=operador_nombre,
        )
        if result.get("ok"):
            sync = hw.sincronizar_hydrawise(conn, usuario, force=True)
            result = {
                "ok": sync.get("ok", True),
                "msg": (result.get("msg") or "") + " " + (sync.get("msg") or ""),
            }
        return result
    if action == "hydra_parar":
        return hw.parar_riego_manual(conn, usuario, operador_nombre)
    if action == "hydra_cancelar_cola":
        return hw.cancelar_cola_manual(conn, usuario, operador_nombre)
    return {"ok": False, "msg": "Acción Hydra no reconocida."}


def _procesar_registro_legacy(
    *,
    demo,
    hydra_sectores: list[dict],
    huertos: list,
    fertilizantes_opts: list,
    regadores_opts: list,
    operador: dict | None,
    acceso_personal: bool,
) -> dict:
    """Devuelve estado del formulario legacy (registro pendiente)."""
    hp = (request.form.get(_HONEYPOT_FIELD) or "").strip()
    form_fecha = request.form.get("fecha") or ""
    form_huerto = request.form.get("huerto") or ""
    form_horas = request.form.get("horas") or ""
    form_m3 = request.form.get("m3") or ""
    form_con_fert = request.form.get("con_fertilizacion") == "1"
    form_fert_lineas = parse_fertilizantes_request(request.form)
    form_modo_riego = (request.form.get("modo_riego") or "horas").strip().lower()
    form_hydra_sector = (request.form.get("hydra_sector") or "").strip()
    hydra_relay_id: int | None = None
    error = None
    ok = False
    mail_ok = None
    codigo = None

    if hydra_sectores:
        if not form_hydra_sector:
            error = "Seleccione el sector Hydrawise."
        else:
            try:
                hydra_relay_id = int(form_hydra_sector)
            except ValueError:
                error = "Sector Hydrawise inválido."
            if not error:
                conn_r = demo.conectar_db()
                try:
                    from demo_web.services.hydrawise_riego import resolver_sector_link

                    sec = resolver_sector_link(conn_r, hydra_relay_id)
                finally:
                    conn_r.close()
                if not sec:
                    error = "Sector no disponible en Link riego."
                else:
                    form_huerto = sec["huerto_cc"]
                    form_modo_riego = sec.get("modo_riego") or form_modo_riego

    try:
        horas = float((form_horas or "0").replace(",", "."))
    except ValueError:
        horas = 0.0
    try:
        m3 = float((form_m3 or "0").replace(",", "."))
    except ValueError:
        m3 = 0.0

    fert_lineas_post = form_fert_lineas if form_con_fert else []

    bot_claro = bool(hp) and horas <= 0 and m3 <= 0 and not form_huerto
    if bot_claro:
        ok = False
        error = None
    elif not acceso_personal:
        error = "Use su enlace personal para registrar riego."
    elif error:
        pass
    elif not form_fecha:
        error = "Indique la fecha."
    elif _norm_cc(form_huerto) not in {_norm_cc(h) for h in huertos}:
        error = "Centro de costo del sector no válido en ERP."
    elif huerto_tiene_calculo_auto(form_huerto) and horas <= 0:
        error = "Indique horas de riego mayores a cero."
    elif not huerto_tiene_calculo_auto(form_huerto) and horas <= 0 and m3 <= 0:
        error = "Indique horas de riego o m³ mayores a cero."
    elif form_con_fert and not fertilizantes_opts:
        error = "No hay fertilizantes en bodega. Registre productos en Bodega primero."
    elif form_con_fert and not fert_lineas_post:
        error = "Agregue al menos un fertilizante con cantidad."
    elif not regadores_opts:
        error = "No hay regadores autorizados. En RRHH marque trabajadores como regador."
    else:
        try:
            res = registrar_link(
                form_fecha,
                form_huerto,
                horas,
                m3,
                (operador or {}).get("nombre", ""),
                fertilizantes=fert_lineas_post if form_con_fert else None,
                modo_riego=form_modo_riego,
                hydrawise_relay_id=hydra_relay_id,
            )
        except Exception as exc:
            error = f"No se pudo guardar: {exc}"
            res = {"ok": False}
        if not res.get("ok") and res.get("msg"):
            error = res["msg"]
        elif res.get("ok"):
            ok = True
            mail_ok = res.get("mail_ok")
            codigo = res.get("codigo")

    if not form_fert_lineas and fertilizantes_opts:
        form_fert_lineas = [{"producto_id": "", "cantidad": "", "dosis_ha": ""}]

    return {
        "ok": ok,
        "mail_ok": mail_ok,
        "codigo": codigo,
        "error": error,
        "form_fecha": form_fecha,
        "form_huerto": form_huerto,
        "form_horas": form_horas,
        "form_m3": form_m3,
        "form_con_fert": form_con_fert,
        "form_fert_lineas": form_fert_lineas,
        "form_modo_riego": form_modo_riego,
        "form_hydra_sector": form_hydra_sector,
    }


@bp.route("/registro-riego", methods=["GET", "POST"])
def formulario():
    _bind_tenant_from_request()
    if not habilitado():
        abort(404)
    tok = _token_request()
    if not token_valido(tok):
        return render_template("registro_riego/denied.html"), 403

    demo = get_demo_module()
    huertos = huertos_para_formulario()
    fertilizantes_opts = fertilizantes_bodega_para_formulario()
    hydra_sectores = _cargar_hydra_sectores(demo)
    regadores_opts = regadores_autorizados_para_formulario()
    op_query = resolver_regador_por_id(request.args.get("op"), regadores_opts)
    op_cookie = leer_operador_cookie(regadores_opts)
    operador = op_query or op_cookie
    acceso_personal = bool(operador)

    use_hydra_ui = bool(lc_contexto_hydra() and hydra_sectores)
    tab = (request.args.get("tab") or request.form.get("tab") or "control").strip().lower()
    if use_hydra_ui and tab in ("registro", "estado"):
        tab = "control"
    if tab not in _HYDRA_TABS:
        tab = "control"

    hydra_msg = (request.args.get("hydra_msg") or "").strip()
    hydra_ok = request.args.get("hydra_ok") == "1"
    live_zonas: dict = {}

    form_state = {
        "ok": False,
        "mail_ok": None,
        "codigo": None,
        "error": None,
        "form_fecha": "",
        "form_huerto": "",
        "form_horas": "",
        "form_m3": "",
        "form_con_fert": False,
        "form_fert_lineas": [],
        "form_modo_riego": "horas",
        "form_hydra_sector": "",
    }

    if request.method == "POST":
        action = (request.form.get("action") or "registro_link").strip()
        if action.startswith("hydra_") and use_hydra_ui:
            if not acceso_personal:
                hydra_msg = "Use su enlace personal para operar Hydra."
                hydra_ok = False
                tab = "control"
            else:
                conn = demo.conectar_db()
                try:
                    result = _handle_hydra_action(demo, conn, operador, action)
                finally:
                    conn.close()
                hydra_msg = str(result.get("msg") or "")
                hydra_ok = bool(result.get("ok"))
                if action == "hydra_refresh_estado" and result.get("zonas"):
                    live_zonas = result.get("zonas") or {}
                tab = _tab_despues_hydra_action(action)
        else:
            if use_hydra_ui:
                hydra_msg = (
                    "El riego se registra desde HYDRA → Control. "
                    "La pestaña Registro manual ya no está en el link."
                )
                hydra_ok = False
                tab = "control"
            else:
                form_state = _procesar_registro_legacy(
                    demo=demo,
                    hydra_sectores=hydra_sectores,
                    huertos=huertos,
                    fertilizantes_opts=fertilizantes_opts,
                    regadores_opts=regadores_opts,
                    operador=operador,
                    acceso_personal=acceso_personal,
                )

    if not form_state["form_fert_lineas"] and fertilizantes_opts:
        form_state["form_fert_lineas"] = [{"producto_id": "", "cantidad": "", "dosis_ha": ""}]

    hydra_cola = None
    hydra_bitacora: list = []
    hydra_conn_online = False
    hydra_conn_msg = ""
    hydra_conn_title = ""
    hydra_conn_cached = False
    hydra_probe_age_sec = 0
    hydra_sync_cooldown = 0
    programa_por_relay: dict = {}
    ejecucion_por_relay: dict = {}
    hydra_mostrar_apagar = False
    running_relay_ids: set[int] = set()
    queued_relay_ids: set[int] = set()
    if use_hydra_ui:
        conn = demo.conectar_db()
        try:
            from demo_web.services import hydrawise_riego as hw

            hydra_sync_cooldown = hw.cooldown_restante_segundos(conn)
            hydra_cola = hw.cola_activa_en_link(conn)
            if (
                request.method == "GET"
                and acceso_personal
                and not hydra_msg
                and hydra_cola
                and hydra_sync_cooldown <= 0
            ):
                auto = hw.sincronizar_hydrawise(
                    conn, _usuario_operador(operador), force=False
                )
                msg = str(auto.get("msg") or "").strip()
                if msg and "429" not in msg and not msg.startswith("Cola activa — próxima"):
                    hydra_msg = msg
                    hydra_ok = bool(auto.get("ok", True))
            if tab == "bitacora":
                hydra_bitacora = hw.listar_bitacora_operativa(conn, limite=40)
            programa_por_relay = hw.programa_por_relay_en_cola(conn, hydra_cola)
            ejecucion_por_relay = hw.ejecucion_por_relay_en_cola(
                conn, hydra_cola, hydra_sectores
            )
            hydra_mostrar_apagar = hw.cola_permite_apagar(hydra_cola)
            if acceso_personal:
                probe = hw.estado_conexion_controlador(conn, force=False)
                hydra_conn_online = bool(probe.get("online"))
                hydra_conn_msg = str(probe.get("msg") or "")
                hydra_conn_title = str(probe.get("title") or "")
                hydra_conn_cached = bool(probe.get("cached"))
                hydra_probe_age_sec = int(probe.get("probe_age_sec") or 0)
                if probe.get("zonas"):
                    live_zonas = probe.get("zonas") or live_zonas
            else:
                ok_cfg, msg_cfg = hw.api_lista_para_link(conn)
                hydra_conn_online = ok_cfg
                hydra_conn_msg = msg_cfg
                hydra_conn_title = "Hydrawise configurado" if ok_cfg else "Hydrawise sin configurar"
        finally:
            conn.close()
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
        for rid, st in (live_zonas or {}).items():
            if isinstance(st, dict) and st.get("running"):
                rid_i = int(rid)
                running_relay_ids.add(rid_i)
                queued_relay_ids.discard(rid_i)

    ctx = dict(
        token=tok,
        honeypot_field=_HONEYPOT_FIELD,
        huertos=huertos,
        fertilizantes=fertilizantes_opts,
        operador=operador,
        acceso_personal=acceso_personal,
        hydra_sectores=hydra_sectores,
        regadores=regadores_opts,
        riego_cc_config=config_riego_cc_para_formulario(),
        tab=tab,
        hydra_msg=hydra_msg,
        hydra_ok=hydra_ok,
        hydra_cola=hydra_cola,
        hydra_bitacora=hydra_bitacora,
        hydra_conn_online=hydra_conn_online,
        hydra_conn_msg=hydra_conn_msg,
        hydra_conn_title=hydra_conn_title,
        hydra_conn_cached=hydra_conn_cached,
        hydra_probe_age_sec=hydra_probe_age_sec,
        hydra_sync_cooldown=hydra_sync_cooldown,
        live_zonas=live_zonas,
        running_relay_ids=sorted(running_relay_ids),
        queued_relay_ids=sorted(queued_relay_ids),
        programa_por_relay=programa_por_relay,
        ejecucion_por_relay=ejecucion_por_relay,
        hydra_tiene_corriendo=bool(running_relay_ids),
        hydra_mostrar_apagar=hydra_mostrar_apagar,
        hydra_cola_programada=bool(
            hydra_cola
            and str(hydra_cola.get("estado") or "") == "programado"
            and not hydra_mostrar_apagar
        ),
        **form_state,
    )

    template = (
        "registro_riego/hydra_link.html"
        if use_hydra_ui
        else "registro_riego/form.html"
    )
    html = render_template(template, **ctx)
    resp = make_response(html)
    if form_state.get("ok") and operador:
        aplicar_cookie_operador(resp, operador["id"])
    elif op_query:
        aplicar_cookie_operador(resp, op_query["id"])
    return resp


@bp.route("/registro-riego/links")
@login_required
def links_admin():
    if not habilitado():
        abort(404)
    demo = get_demo_module()
    if not demo.es_super_admin():
        abort(403)
    return redirect(url_for("modules.riego", sec="bitacora"))
