"""ERP Master · Río Maipo — Flask + Bootstrap + DataTables (reemplazo de Streamlit)."""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import date, timedelta
from functools import wraps

from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from io import BytesIO

from rmweb import core
from rmweb.tenants import get_tenant, list_tenants, modulo_visible
from rmweb.pricing import pricing_context
from rmweb.mail_alertas import enviar_correo_alerta, enviar_correo_alerta_pago
from rmweb.master_bitacora import log_master_bitacora
from rmweb.demo_bitacora import log_movimiento_demo

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/static",
)
app.secret_key = os.getenv("SECRET_KEY", "riomaipo-web-change-me")

_TENANT_DB_INIT: set[str] = set()

# Prefijo público detrás de nginx (/comercial)
try:
    from werkzeug.middleware.proxy_fix import ProxyFix

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
except Exception:  # pragma: no cover
    pass


SESSION_IDLE_SECONDS = int(os.environ.get('ERP_COMERCIAL_SESSION_IDLE', str(1200)))
SESSION_IDLE_WARN_SECONDS = int(os.environ.get('ERP_COMERCIAL_SESSION_IDLE_WARN', str(120)))
SESSION_PASSIVE_ENDPOINTS = {'session_status', 'static'}

def _status_dir() -> str:
    return os.environ.get("ERP_STATUS_DIR", "/root/erp_status").strip() or "/root/erp_status"


def _tenant_en_mantenimiento(slug: str) -> bool:
    path = os.path.join(_status_dir(), f"{slug}.mantenimiento")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip() == "1"
    except OSError:
        return False


def _tenant_session_epoch(slug: str) -> str:
    path = os.path.join(_status_dir(), f"{slug}.session_epoch")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip() or "0"
    except OSError:
        return "0"



def _es_tenant_demo(slug: str | None) -> bool:
    return (slug or "").strip().lower() == "comercial-demo"


def _demo_prueba_context(slug: str | None, fecha_expira: str | None) -> dict:
    """Contador de días de prueba (solo DEMO Comercial con fecha_expira)."""
    if not _es_tenant_demo(slug):
        return {
            "demo_prueba_activa": False,
            "demo_dias_restantes": None,
            "demo_fecha_expira": "",
            "demo_prueba_alerta": False,
        }
    from rmweb.demo_invitacion import dias_restantes_prueba, parse_fecha

    fexp = (fecha_expira or session.get("auth_fecha_expira") or "").strip()
    dias = dias_restantes_prueba(fexp)
    f = parse_fecha(fexp)
    return {
        "demo_prueba_activa": dias is not None and dias >= 0,
        "demo_dias_restantes": dias,
        "demo_fecha_expira": f.strftime("%d-%m-%Y") if f else "",
        "demo_prueba_alerta": bool(dias is not None and 0 <= dias <= 3),
    }


def _bloquear_si_prueba_vencida(slug: str | None, fecha_expira: str | None) -> bool:
    """True si debe bloquear (prueba vencida)."""
    if not _es_tenant_demo(slug):
        return False
    from rmweb.demo_invitacion import usuario_prueba_vigente

    return not usuario_prueba_vigente(fecha_expira)


def _activate_tenant_session(slug: str, user: dict, *, from_master: bool = False) -> None:
    session.clear()
    session["auth_ok"] = True
    session["tenant_slug"] = slug
    session["auth_user"] = user["usuario"]
    session["auth_nombre"] = user.get("nombre") or user["usuario"]
    session["auth_tipo"] = user.get("tipo") or "Consulta"
    session["auth_fecha_expira"] = (user.get("fecha_expira") or "")[:10] or ""
    session["erp_session_epoch"] = _tenant_session_epoch(slug)
    session["last_activity"] = time.time()
    if from_master:
        session["from_master_console"] = True
    elif slug:
        try:
            log_master_bitacora(
                slug,
                user.get("usuario") or "",
                "INGRESO_ERP",
                "Ingreso al ERP Comercial",
            )
        except Exception:
            pass
    try:
        open(os.path.join(_status_dir(), f"{slug}.post_maint"), "w", encoding="utf-8").write("0\n")
    except OSError:
        pass



def _riomaipo_status_dir() -> str:
    return os.environ.get("ERP_STATUS_DIR", "/root/erp_status").strip() or "/root/erp_status"


def _riomaipo_en_mantenimiento() -> bool:
    path = os.path.join(_riomaipo_status_dir(), "riomaipo.mantenimiento")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip() == "1"
    except OSError:
        return False


def _riomaipo_session_epoch() -> str:
    path = os.path.join(_riomaipo_status_dir(), "riomaipo.session_epoch")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip() or "0"
    except OSError:
        return "0"


@app.before_request
def _boot():
    # Cuando nginx recorta /comercial/ y envía X-Forwarded-Prefix
    prefix = (request.headers.get("X-Forwarded-Prefix") or os.getenv("RIOMAIPO_PREFIX") or "").rstrip("/")
    if prefix:
        request.environ["SCRIPT_NAME"] = prefix
    if request.path.startswith("/static/"):
        return None
    slug = (session.get("tenant_slug") or "").strip().lower()
    if session.get("auth_ok") and _bloquear_si_prueba_vencida(slug, session.get("auth_fecha_expira")):
        session.clear()
        flash("Su periodo de prueba ha finalizado.", "danger")
        return redirect(url_for("login", tenant=slug or "comercial-demo"))
    if slug and _tenant_en_mantenimiento(slug):
        from flask import Response
        if session.get("auth_ok"):
            session.clear()
        ten_name = (get_tenant(slug) or {}).get("nombre") or "Comercial"
        html = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sitio en mantención — Río Maipo</title>
<style>
body{margin:0;min-height:100vh;display:grid;place-items:center;padding:1.5rem;font-family:Segoe UI,sans-serif;color:#1f2a24;
background:radial-gradient(900px 500px at 20% 0%,rgba(180,83,9,.10),transparent 55%),linear-gradient(180deg,#f8f5ee 0%,#ece7db 100%)}
.card{width:min(520px,100%);background:rgba(247,244,236,.96);border:1px solid rgba(31,42,36,.12);border-radius:18px;box-shadow:0 16px 40px rgba(31,42,36,.10);padding:2rem 1.6rem;text-align:center}
.mark{display:flex;justify-content:center;align-items:flex-end;gap:1rem;height:56px;margin-bottom:1rem}
.cone{width:0;height:0;border-left:18px solid transparent;border-right:18px solid transparent;border-bottom:40px solid #c2410c;position:relative}
.cone:after{content:"";position:absolute;left:-12px;top:14px;width:24px;height:5px;background:#1f2a24}
.bar{width:64px;height:12px;margin-bottom:6px;border-radius:3px;background:#c2410c;border:1px solid #1f2a24}
.badge{display:inline-block;background:#fff7ed;color:#b45309;border:1px solid rgba(180,83,9,.25);font-size:.72rem;font-weight:800;letter-spacing:.12em;text-transform:uppercase;padding:.35rem .7rem;border-radius:999px;margin-bottom:.85rem}
h1{margin:0 0 .55rem;font-family:Georgia,serif;font-size:clamp(1.7rem,5vw,2.15rem);font-weight:600}
p{margin:0;color:#5f6b64;font-size:1.02rem;line-height:1.45}
.soon{margin-top:1rem;font-weight:700;color:#1f2a24;font-size:1.1rem}
.foot{margin-top:1.25rem;font-size:.82rem;color:#7a7468}
</style></head><body><main class="card">
<div class="mark" aria-hidden="true"><span class="cone"></span><span class="bar"></span><span class="cone"></span></div>
<div class="badge">Sitio en mantención</div>
<h1>Río Maipo</h1>
<p>Estamos realizando una actualización o reparación programada.</p>
<p class="soon">Regresamos a la brevedad.</p>
<p class="foot">Más adelante publicaremos datos de contacto aquí.</p>
</main></body></html>"""
        html = html.replace("Río Maipo", ten_name)
        return Response(html, status=503, mimetype="text/html; charset=utf-8")
    # Tras restaurar mantención: acceso limpio (sin URL de actividad previa).
    post_path = os.path.join(_status_dir(), f"{slug}.post_maint") if slug else ""
    post_maint = False
    try:
        with open(post_path, encoding="utf-8") as f:
            post_maint = f.read().strip() == "1"
    except OSError:
        post_maint = False
    if post_maint:
        if session.get("auth_ok"):
            session.clear()
        if request.endpoint != "login":
            return redirect(url_for("login"))
        return None

    if slug:
        g.tenant_slug = slug
        epoch = _tenant_session_epoch(slug)
        if session.get("auth_ok"):
            sess_epoch = session.get("erp_session_epoch")
            if sess_epoch is None:
                session["erp_session_epoch"] = epoch
            elif sess_epoch != epoch:
                session.clear()
                if request.endpoint not in {"login", "master_entry"}:
                    return redirect(url_for("login"))
        ten = get_tenant(slug) or {}
        init_key = f'{slug}:{ten.get("db") or ""}'
        if init_key not in _TENANT_DB_INIT:
            core.init_db(ten.get("db"), ten.get("empresa_default"))
            _TENANT_DB_INIT.add(init_key)



@app.before_request
def _comercial_session_idle():
    if not session.get("auth_ok"):
        return None
    endpoint = request.endpoint or ""
    if endpoint in {"login", "logout", "master_entry", "static", "favicon"}:
        return None
    now = time.time()
    try:
        last = float(session.get("last_activity") or now)
    except (TypeError, ValueError):
        last = now
    if (now - last) > SESSION_IDLE_SECONDS:
        session.clear()
        if endpoint in {"session_status", "session_continue"} or (request.path or "").startswith("/api/"):
            return {"ok": False, "error": "session_expired"}, 401
        return redirect(url_for("login"))
    if endpoint == "session_continue":
        session["last_activity"] = now
    elif endpoint not in SESSION_PASSIVE_ENDPOINTS:
        session["last_activity"] = now
    return None


def _safe_next_redirect(nxt: str | None):
    """Evita salir de /comercial (p.ej. next=/ cae en otra app)."""
    nxt = (nxt or "").strip()
    if not nxt or nxt == "/" or not nxt.startswith("/") or nxt.startswith("//") or "://" in nxt:
        return redirect(url_for("dashboard"))
    # request.path viene sin SCRIPT_NAME; hay que anteponer el prefijo público
    prefix = (request.script_root or "").rstrip("/")
    return redirect(prefix + nxt)


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("auth_ok"):
            path = request.path or "/"
            if path in ("/", ""):
                return redirect(url_for("login"))
            return redirect(url_for("login", next=path))
        return fn(*args, **kwargs)

    return wrapper


@app.context_processor
def inject_globals():
    slug = (session.get("tenant_slug") or "").strip().lower()
    ten = get_tenant(slug) if slug else None
    ctx = {
        "clp": core.clp,
        "fmt_dmy": core.fmt_dmy,
        "estado_label_cot": core.estado_label_cot,
        "estados_cot": getattr(core, "ESTADOS_COT", ()),
        "cxc_estado_label": core.cxc_estado_label,
        "cxc_estado_class": core.cxc_estado_class,
        "auth_user": session.get("auth_user", ""),
        "auth_nombre": session.get("auth_nombre", ""),
        "auth_tipo": session.get("auth_tipo", ""),
        "app_name": "ERP Master",
        "track_name": (ten or {}).get("nombre") or "Comercial",
        "tenant_slug": slug,
        "tenants": list_tenants(),
        "session_idle_limit": SESSION_IDLE_SECONDS,
        "session_idle_warn": SESSION_IDLE_WARN_SECONDS,
    }
    ctx.update(pricing_context(slug))
    ctx.update(_demo_prueba_context(slug, session.get("auth_fecha_expira")))
    ctx["modulo_visible"] = lambda mod: modulo_visible(slug, mod)
    return ctx


_MODULO_PATH_PREFIXES: dict[str, tuple[str, ...]] = {
    "arriendos": ("/arriendos",),
    "mercadolibre": ("/ml", "/mercadolibre"),
}


@app.before_request
def _guard_modulos_ocultos():
    if request.endpoint in SESSION_PASSIVE_ENDPOINTS or request.endpoint in {
        "login", "logout", "favicon", "static",
    }:
        return None
    slug = (session.get("tenant_slug") or "").strip().lower()
    if not slug:
        return None
    path = (request.path or "").lower()
    for mod, prefixes in _MODULO_PATH_PREFIXES.items():
        if not modulo_visible(slug, mod) and any(
            path == p or path.startswith(p + "/") for p in prefixes
        ):
            flash("Este módulo no está disponible en su tenant.", "warning")
            return redirect(url_for("dashboard"))
    return None


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _find_login_matches(usuario: str, clave: str) -> list[dict]:
    """Busca el mismo correo/clave en todos los ERP Comercial (estilo Agrícola)."""
    matches: list[dict] = []
    email = (usuario or "").strip()
    password = clave or ""
    if not email or not password:
        return matches
    for ten in list_tenants():
        slug = ten["slug"]
        if _tenant_en_mantenimiento(slug):
            continue
        try:
            core.init_db(ten["db"], ten.get("empresa_default"))
            user = core.get_user_if_valid(email, password, ten["db"])
            if not user:
                continue
            from rmweb.demo_invitacion import acceso_permitido_en_tenant

            if not acceso_permitido_en_tenant(slug, dict(user)):
                continue
            if _bloquear_si_prueba_vencida(slug, user.get("fecha_expira")):
                continue
            matches.append(
                {
                    "slug": slug,
                    "nombre": ten.get("nombre") or slug,
                    "descripcion": ten.get("descripcion") or "",
                    "tipo": user.get("tipo") or "Consulta",
                    "user": {
                        "usuario": user["usuario"],
                        "nombre": user.get("nombre") or user["usuario"],
                        "tipo": user.get("tipo") or "Consulta",
                        "fecha_expira": (user.get("fecha_expira") or "")[:10] or "",
                        "id": user.get("id"),
                        "invitado_por": user.get("invitado_por") or "",
                    },
                }
            )
        except Exception:
            continue
    return matches


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("auth_ok") and session.get("tenant_slug"):
        return redirect(url_for("dashboard"))
    # Bio / entrada DEMO: sin acceso precargado → formulario de prueba (OTP), no el ERP.
    if request.method == "GET" and not request.args.get("acceso"):
        tenant_q = (request.args.get("tenant") or "").strip().lower()
        demo_q = (request.args.get("demo") or "").strip().lower()
        if tenant_q == "comercial-demo" or demo_q in {"1", "true", "si", "sí", "demo"}:
            return redirect(url_for("probar"))
    # Si ya validó clave y debe elegir empresa, no volver al formulario.
    if session.get("pending_login") and request.method == "GET" and not request.args.get("acceso"):
        pending = session.get("pending_login") or {}
        if pending.get("options"):
            return redirect(url_for("elegir_empresa"))

    error = None
    default_user = (
        request.form.get("usuario") or request.args.get("acceso") or ""
    ).strip()

    if request.method == "POST":
        email = (request.form.get("usuario") or "").strip()
        clave = request.form.get("clave") or ""
        default_user = email
        matches = _find_login_matches(email, clave)
        if not matches:
            error = "Usuario o clave incorrectos, o periodo de prueba finalizado."
            # Alerta best-effort en DEMO (si existe), sin filtrar otros ERP.
            try:
                ten = get_tenant("comercial-demo") or (list_tenants()[0] if list_tenants() else None)
                if ten:
                    enviar_correo_alerta(
                        secrets_path=ten.get("secrets") or "",
                        tenant_nombre=ten.get("nombre") or ten.get("slug") or "Comercial",
                        usuario=email or "desconocido",
                        exitoso=False,
                    )
                    if (ten.get("slug") or "").strip().lower() == "comercial-demo":
                        log_master_bitacora(
                            "comercial-demo",
                            email or "desconocido",
                            "INGRESO_FALLIDO",
                            "Intento de acceso rechazado",
                        )
            except Exception:
                pass
        elif len(matches) == 1:
            m = matches[0]
            slug = m["slug"]
            ten = get_tenant(slug) or {}
            _activate_tenant_session(slug, dict(m["user"]), from_master=False)
            try:
                enviar_correo_alerta(
                    secrets_path=ten.get("secrets") or "",
                    tenant_nombre=ten.get("nombre") or slug,
                    usuario=m["user"]["usuario"],
                    exitoso=True,
                )
            except Exception:
                pass
            return _safe_next_redirect(request.args.get("next"))
        else:
            session["pending_login"] = {
                "email": matches[0]["user"]["usuario"],
                "options": [
                    {
                        "slug": m["slug"],
                        "nombre": m["nombre"],
                        "descripcion": m["descripcion"],
                        "tipo": m["tipo"],
                        "user": m["user"],
                    }
                    for m in matches
                ],
            }
            return redirect(url_for("elegir_empresa"))

    return render_template(
        "login.html",
        error=error,
        default_user=default_user,
    )


@app.route("/login/empresa", methods=["GET", "POST"])
def elegir_empresa():
    """Selector interno cuando el correo participa en más de un ERP Comercial."""
    if session.get("auth_ok") and session.get("tenant_slug"):
        return redirect(url_for("dashboard"))
    pending = session.get("pending_login") or {}
    options = pending.get("options") or []
    email = pending.get("email") or ""
    if not options or not email:
        return redirect(url_for("login"))

    if request.method == "POST":
        slug = (request.form.get("tenant_slug") or "").strip().lower()
        chosen = next((o for o in options if o.get("slug") == slug), None)
        ten = get_tenant(slug)
        if not chosen or not ten:
            flash("Elige una empresa válida.", "warning")
            return redirect(url_for("elegir_empresa"))
        if _tenant_en_mantenimiento(slug):
            flash(ten["nombre"] + " está en mantención.", "warning")
            return redirect(url_for("elegir_empresa"))
        user = dict(chosen.get("user") or {})
        if not user.get("usuario"):
            user["usuario"] = email
        if _bloquear_si_prueba_vencida(slug, user.get("fecha_expira")):
            flash("Su periodo de prueba ha finalizado.", "danger")
            return redirect(url_for("login"))
        _activate_tenant_session(slug, user, from_master=False)
        session.pop("pending_login", None)
        try:
            enviar_correo_alerta(
                secrets_path=ten.get("secrets") or "",
                tenant_nombre=ten.get("nombre") or slug,
                usuario=user["usuario"],
                exitoso=True,
            )
        except Exception:
            pass
        return redirect(url_for("dashboard"))

    return render_template(
        "select_tenant.html",
        email=email,
        options=options,
    )


@app.route("/login/master")
def master_entry():
    """Ingreso desde Super Consola → tenant del token + dashboard."""
    from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

    token = (request.args.get("t") or "").strip()
    secret = (os.environ.get("ERP_MASTER_BRIDGE_SECRET") or "").strip()
    if not token or not secret:
        return redirect(url_for("login"))
    try:
        data = URLSafeTimedSerializer(secret, salt="erp-master-bridge-v1").loads(token, max_age=120)
    except SignatureExpired:
        return redirect(url_for("login"))
    except BadSignature:
        return redirect(url_for("login"))
    email = (data.get("email") or "").strip().lower() if isinstance(data, dict) else ""
    slug = (data.get("slug") or "").strip().lower() if isinstance(data, dict) else ""
    ten = get_tenant(slug)
    if not email or not ten:
        return redirect(url_for("login"))
    if _tenant_en_mantenimiento(slug):
        return redirect(url_for("login", tenant=slug))
    core.init_db(ten["db"], ten.get("empresa_default"))
    c = core.conn(ten["db"])
    try:
        row = c.execute(
            """SELECT id, usuario, salt, clave_hash, nombre, tipo, activo,
                      fecha_expira, invitado_por
               FROM usuarios WHERE lower(usuario)=? AND activo=1""",
            (email,),
        ).fetchone()
    finally:
        c.close()
    if not row:
        return redirect(url_for("login", tenant=slug))
    user = dict(row)
    from rmweb.demo_invitacion import acceso_permitido_en_tenant

    if not acceso_permitido_en_tenant(slug, user):
        flash("Este acceso de prueba no aplica a este tenant.", "danger")
        return redirect(url_for("login", tenant=slug))
    if _bloquear_si_prueba_vencida(slug, user.get("fecha_expira")):
        flash("Su periodo de prueba ha finalizado.", "danger")
        return redirect(url_for("login", tenant=slug))
    _activate_tenant_session(slug, user, from_master=True)
    return redirect(url_for("dashboard"))


@app.route("/presentacion")
def presentacion_comercial():
    """Presentación de venta Comercial (HTML estático)."""
    resp = app.send_static_file("venta/presentacion-comercial.html")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.route("/venta/canales")
def canales_venta_comercial():
    """Esquema de canales (markdown como texto)."""
    from flask import Response
    path = os.path.join(app.static_folder, "venta", "canales-venta-comercial.md")
    try:
        texto = open(path, encoding="utf-8").read()
    except OSError:
        return "No disponible", 404
    return Response(texto, mimetype="text/markdown; charset=utf-8")


@app.route("/favicon.ico")
def favicon():
    # PNG de la M (mejor en pestañas); ?v= evita caché del SVG/ICO viejo
    resp = app.send_static_file("favicon-32x32.png")
    resp.headers["Content-Type"] = "image/png"
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.get("/api/session-status")
@login_required
def session_status():
    now = time.time()
    try:
        last = float(session.get("last_activity") or now)
    except (TypeError, ValueError):
        last = now
    idle_for = max(0.0, now - last)
    return {
        "ok": True,
        "idle_limit": SESSION_IDLE_SECONDS,
        "warn_seconds": SESSION_IDLE_WARN_SECONDS,
        "idle_for": round(idle_for, 1),
        "idle_left": round(max(0.0, SESSION_IDLE_SECONDS - idle_for), 1),
    }


@app.post("/api/session-continue")
@login_required
def session_continue():
    session["last_activity"] = time.time()
    return {"ok": True, "idle_left": SESSION_IDLE_SECONDS}


@app.route("/planes")
@login_required
def planes():
    """Valoración de módulos (DEMO Comercial)."""
    from rmweb.pricing import (
        MODULOS_FEE,
        PACK,
        PACK_COMPRAS,
        PACK_VENTAS,
        suma_modulos,
        suma_modulos_keys,
    )
    from rmweb.demo_invitacion import DEMO_DIAS_PRUEBA

    slug = (session.get("tenant_slug") or "").strip().lower()
    if slug != "comercial-demo":
        flash("Esta vista aplica al tenant DEMO Comercial.", "ok")
        return redirect(url_for("dashboard"))
    suma = suma_modulos()
    suma_ventas = suma_modulos_keys(PACK_VENTAS["modulos"])
    suma_compras = suma_modulos_keys(PACK_COMPRAS["modulos"])
    pagos = [int(m["fee"]) for m in MODULOS_FEE.values() if int(m["fee"]) > 0 and not m.get("addon")]
    return render_template(
        "planes.html",
        active="planes",
        modulos=MODULOS_FEE,
        pack=PACK,
        pack_ventas=PACK_VENTAS,
        pack_compras=PACK_COMPRAS,
        suma=suma,
        suma_ventas=suma_ventas,
        suma_compras=suma_compras,
        ahorro=max(0, suma - int(PACK["fee"])),
        ahorro_ventas=max(0, suma_ventas - int(PACK_VENTAS["fee"])),
        ahorro_compras=max(0, suma_compras - int(PACK_COMPRAS["fee"])),
        modulos_pago_min=min(pagos) if pagos else 0,
        dias_prueba=DEMO_DIAS_PRUEBA,
    )


@app.route("/")
@login_required
def dashboard():
    from rmweb import ops as _ops
    from rmweb import indicadores as _ind

    db = core.conn()
    _ops.ensure_ops_schema(db)
    cotas = db.execute(
        "SELECT estado, COUNT(*) n, COALESCE(SUM(total),0) t FROM cotizaciones GROUP BY estado"
    ).fetchall()
    n_cot = sum(r["n"] for r in cotas)
    sum_cot = sum(float(r["t"]) for r in cotas)
    n_apr = sum(r["n"] for r in cotas if r["estado"] == "aprobada")
    saldo = db.execute("SELECT COALESCE(SUM(saldo),0) s FROM cuentas").fetchone()["s"]
    pend = db.execute(
        "SELECT COUNT(*) n FROM cuentas WHERE saldo > 0"
    ).fetchone()["n"]
    venc = db.execute(
        """
        SELECT COUNT(*) n FROM cuentas
        WHERE saldo > 0 AND fecha_vencimiento IS NOT NULL AND fecha_vencimiento < date('now')
        """
    ).fetchone()["n"]
    top = db.execute(
        """
        SELECT cl.razon_social, COALESCE(SUM(cu.saldo),0) saldo
        FROM cuentas cu LEFT JOIN clientes cl ON cl.id=cu.cliente_id
        GROUP BY cu.cliente_id
        HAVING saldo > 0
        ORDER BY saldo DESC LIMIT 8
        """
    ).fetchall()

    # Tesorería (CxP): misma base que /tesoreria/
    kpis_cxp = _ops.kpis_cxp(db)
    venc_cxp_row = db.execute(
        """
        SELECT COUNT(*) n, COALESCE(SUM(saldo),0) m
        FROM facturas_compra
        WHERE COALESCE(saldo,0) > 0.009
          AND fecha_vencimiento IS NOT NULL
          AND fecha_vencimiento < date('now')
        """
    ).fetchone()
    venc_cxp = int(venc_cxp_row["n"] or 0)
    venc_cxp_monto = float(venc_cxp_row["m"] or 0)
    vencimientos_cxp = db.execute(
        """
        SELECT f.id, f.documento, f.fecha_vencimiento, f.saldo, f.estado,
               p.razon_social AS proveedor,
               CASE
                 WHEN f.fecha_vencimiento IS NOT NULL
                      AND f.fecha_vencimiento < date('now') THEN 1
                 ELSE 0
               END AS vencido
        FROM facturas_compra f
        LEFT JOIN proveedores p ON p.id=f.proveedor_id
        WHERE COALESCE(f.saldo,0) > 0.009
        ORDER BY COALESCE(f.fecha_vencimiento, f.fecha_emision) ASC, f.id
        LIMIT 12
        """
    ).fetchall()
    top_prov = db.execute(
        """
        SELECT COALESCE(p.razon_social, '—') AS proveedor,
               COALESCE(SUM(f.saldo),0) AS saldo
        FROM facturas_compra f
        LEFT JOIN proveedores p ON p.id=f.proveedor_id
        WHERE COALESCE(f.saldo,0) > 0.009
        GROUP BY f.proveedor_id
        HAVING saldo > 0
        ORDER BY saldo DESC
        LIMIT 8
        """
    ).fetchall()

    db.close()
    indicadores = _ind.obtener_indicadores()
    return render_template(
        "dashboard.html",
        active="dashboard",
        n_cot=n_cot,
        sum_cot=sum_cot,
        n_apr=n_apr,
        saldo=saldo,
        pend=pend,
        venc=venc,
        top=top,
        cotas=cotas,
        kpis_cxp=kpis_cxp,
        venc_cxp=venc_cxp,
        venc_cxp_monto=venc_cxp_monto,
        vencimientos_cxp=vencimientos_cxp,
        top_prov=top_prov,
        indicadores=indicadores,
    )


# ---------------------------------------------------------------------------
# Clientes
# ---------------------------------------------------------------------------
@app.route("/clientes/")
@login_required
def clientes_list():
    q = (request.args.get("q") or "").strip()
    db = core.conn()
    sql = """
        SELECT id, rut, razon_social, contacto, telefono, email, comuna, activo
        FROM clientes WHERE 1=1
    """
    params: list = []
    if q:
        like = f"%{q}%"
        sql += " AND (rut LIKE ? OR razon_social LIKE ? OR email LIKE ? OR contacto LIKE ?)"
        params.extend([like, like, like, like])
    sql += " ORDER BY razon_social"
    rows = db.execute(sql, params).fetchall()
    db.close()
    return render_template("clientes/lista.html", active="clientes", rows=rows, q=q)


@app.route("/clientes/nuevo", methods=["GET", "POST"])
@app.route("/clientes/<int:cid>/editar", methods=["GET", "POST"])
@login_required
def clientes_form(cid: int | None = None):
    db = core.conn()
    row = db.execute("SELECT * FROM clientes WHERE id=?", (cid,)).fetchone() if cid else None
    if request.method == "POST":
        data = (
            request.form.get("rut", "").strip() or None,
            request.form.get("razon_social", "").strip(),
            request.form.get("contacto", "").strip() or None,
            request.form.get("telefono", "").strip() or None,
            request.form.get("email", "").strip() or None,
            request.form.get("direccion", "").strip() or None,
            request.form.get("comuna", "").strip() or None,
            1 if request.form.get("activo") else 0,
        )
        if not data[1]:
            flash("La razón social es obligatoria", "danger")
        else:
            try:
                if row:
                    db.execute(
                        """
                        UPDATE clientes SET rut=?, razon_social=?, contacto=?, telefono=?,
                        email=?, direccion=?, comuna=?, activo=? WHERE id=?
                        """,
                        (*data, row["id"]),
                    )
                else:
                    db.execute(
                        """
                        INSERT INTO clientes
                        (rut, razon_social, contacto, telefono, email, direccion, comuna, activo, creado_en)
                        VALUES (?,?,?,?,?,?,?,?,?)
                        """,
                        (*data, core.hoy_chile().isoformat()),
                    )
                db.commit()
                log_movimiento_demo(
                    "CLIENTE",
                    f"{'Editado' if row else 'Nuevo'}: {data[1]}",
                )
                flash("Cliente guardado", "ok")
                db.close()
                return redirect(url_for("clientes_list"))
            except Exception as exc:
                flash(f"No se pudo guardar: {exc}", "danger")
    db.close()
    return render_template("clientes/form.html", active="clientes", row=row)


# ---------------------------------------------------------------------------
# Cotizaciones
# ---------------------------------------------------------------------------
def _cotizacion_aprobar_side_effects(
    db, cid: int, tipo_venta: str, tenant_slug: str | None = None
) -> tuple[bool, str | None, str | None, str | None]:
    """CxC + bodega/arriendo/OT al aprobar. Retorna (ok, cxc_doc, stock_msg, extra_msg)."""
    from rmweb import ops as _ops
    from rmweb import ops_arriendo as _arr

    _ops.ensure_ops_schema(db)
    cxc_doc = core.ensure_cxc_from_cotizacion(db, cid)
    slug = (tenant_slug or "").strip().lower()
    tv = (tipo_venta or "servicio").strip().lower()
    if tv == "arriendo":
        ok_a, extra_msg = _arr.crear_contrato_desde_cotizacion(db, cid)
        return ok_a, cxc_doc, None, extra_msg
    ok_s, stock_msg = _ops.aplicar_salida_cotizacion_producto(db, cid)
    extra_msg = None
    if tv == "servicio" and modulo_visible(slug, "taller_ot"):
        from rmweb import ops_taller as _taller

        ok_ot, extra_msg = _taller.crear_ot_desde_cotizacion(db, cid)
        if not ok_ot:
            return False, cxc_doc, stock_msg, extra_msg
    return ok_s, cxc_doc, stock_msg, extra_msg


def _cotizacion_revert_aprobacion(db, cid: int) -> None:
    """Deja la cotización en borrador y quita CxC generada en un intento fallido de aprobación."""
    row = db.execute("SELECT cxc_id FROM cotizaciones WHERE id=?", (cid,)).fetchone()
    if row and row["cxc_id"]:
        cxc_id = int(row["cxc_id"])
        db.execute("DELETE FROM abonos WHERE cuenta_id=?", (cxc_id,))
        db.execute("DELETE FROM cuentas WHERE id=?", (cxc_id,))
        db.execute("UPDATE cotizaciones SET cxc_id=NULL WHERE id=?", (cid,))
    db.execute("UPDATE cotizaciones SET estado='borrador' WHERE id=?", (cid,))


def _clientes_para_cotizacion(db, cliente_id: int | None = None):
    """Clientes activos y, al editar, el cliente actual aunque esté inactivo."""
    if cliente_id:
        cid = int(cliente_id)
        rows = db.execute(
            """
            SELECT id, razon_social, COALESCE(activo, 1) AS activo
            FROM clientes
            WHERE activo=1 OR id=?
            ORDER BY razon_social
            """,
            (cid,),
        ).fetchall()
        if not any(int(r["id"]) == cid for r in rows):
            orphan = db.execute(
                "SELECT id, razon_social FROM clientes WHERE id=?",
                (cid,),
            ).fetchone()
            label = (orphan["razon_social"] if orphan else None) or f"Cliente #{cid}"
            rows = list(rows) + [{"id": cid, "razon_social": label, "activo": 0}]
        return rows
    return db.execute(
        """
        SELECT id, razon_social, COALESCE(activo, 1) AS activo
        FROM clientes WHERE activo=1 ORDER BY razon_social
        """
    ).fetchall()


def _resolve_cliente_cotizacion_post(edit, clientes) -> int:
    """Conserva el cliente original si el select no venía marcado al guardar."""
    allowed = {int(r["id"]) for r in clientes}
    if edit:
        orig = int(edit["cliente_id"] or 0)
        try:
            posted = int(request.form.get("cliente_id") or 0)
        except (TypeError, ValueError):
            posted = 0
        if posted and posted in allowed:
            return posted
        if orig:
            return orig
        raise ValueError("cliente_id inválido")
    return int(request.form["cliente_id"])


def _fecha_cotizacion_form(raw: str | None) -> str:
    s = (raw or "").strip()
    if not s:
        return core.hoy_chile().isoformat()
    try:
        d = date.fromisoformat(s)
    except ValueError:
        raise ValueError("fecha inválida")
    if d.year < 1990 or d.year > 2100:
        raise ValueError("fecha inválida")
    return d.isoformat()


def _form_pct(name: str, default: float) -> float:
    """Lee % del formulario; «0» es válido (no cae al default por falsy)."""
    raw = request.form.get(name)
    if raw is None or str(raw).strip() == "":
        return float(default)
    try:
        return float(str(raw).strip().replace(",", "."))
    except (TypeError, ValueError):
        return float(default)


@app.route("/cotizaciones/")
@login_required
def cotizaciones_list():
    db = core.conn()
    try:
        from rmweb import constructora as _cst
        _cst.ensure_constructora_schema(db)
    except Exception:
        pass
    rows = db.execute(
        """
        SELECT c.id, c.folio, c.fecha, c.estado, c.total, c.asunto, c.proyecto, c.titulo,
               COALESCE(c.tipo_venta,'servicio') AS tipo_venta,
               COALESCE(c.tipo_cotizacion,'normal') AS tipo_cotizacion,
               c.centro_costo_id,
               cl.razon_social AS cliente
        FROM cotizaciones c
        LEFT JOIN clientes cl ON cl.id = c.cliente_id
        ORDER BY COALESCE(c.fecha,'') DESC, c.id DESC
        """
    ).fetchall()
    n_total = len(rows)
    sum_total = sum(float(r["total"] or 0) for r in rows)
    n_apr = sum(1 for r in rows if r["estado"] == "aprobada")
    n_rec = sum(1 for r in rows if r["estado"] == "rechazada")
    sum_apr = sum(float(r["total"] or 0) for r in rows if r["estado"] == "aprobada")
    sum_rec = sum(float(r["total"] or 0) for r in rows if r["estado"] == "rechazada")
    conv = (n_apr / n_total * 100) if n_total else 0
    db.close()
    return render_template(
        "cotizaciones/lista.html",
        active="cotizaciones",
        rows=rows,
        kpis={
            "n_total": n_total,
            "sum_total": sum_total,
            "n_apr": n_apr,
            "sum_apr": sum_apr,
            "n_rec": n_rec,
            "sum_rec": sum_rec,
            "conv": conv,
        },
    )


@app.route("/cotizaciones/nueva", methods=["GET", "POST"])
@app.route("/cotizaciones/<int:cot_id>/editar", methods=["GET", "POST"])
@login_required
def cotizaciones_form(cot_id: int | None = None):
    db = core.conn()
    _slug_form = (session.get("tenant_slug") or "").strip().lower()
    if modulo_visible(_slug_form, "taller_ot"):
        from rmweb import ops_taller as _taller

        _taller.ensure_taller_schema(db)
    edit = None
    items = []
    if cot_id:
        edit = db.execute(
            """
            SELECT c.*, cl.razon_social FROM cotizaciones c
            LEFT JOIN clientes cl ON cl.id=c.cliente_id WHERE c.id=?
            """,
            (cot_id,),
        ).fetchone()
        if not edit:
            flash("Cotización no encontrada", "danger")
            db.close()
            return redirect(url_for("cotizaciones_list"))
        raw_items = db.execute(
            """
            SELECT * FROM cotizacion_items WHERE cotizacion_id=?
            ORDER BY COALESCE(orden,0), id
            """,
            (cot_id,),
        ).fetchall()
        # En el formulario no se editan GG/Utilidad como ítems (van en el resumen)
        items = [
            it
            for it in raw_items
            if not core._is_gg_line(it["descripcion"]) and not core._is_util_line(it["descripcion"])
        ]

    cliente_actual = int(edit["cliente_id"]) if edit and edit["cliente_id"] else None
    clientes = _clientes_para_cotizacion(db, cliente_actual)

    iva_def = core.param(db, "iva", 19)
    iva_pct = float(iva_def) / 100.0
    gg_def = core.param(db, "gg_pct", 5)
    util_def = core.param(db, "utilidad_pct", 15)
    validez_def = int(core.param(db, "validez_cotizacion", 30))

    if request.method == "POST":
        try:
            cliente_id = _resolve_cliente_cotizacion_post(edit, clientes)
        except (TypeError, ValueError, KeyError):
            flash("Seleccione un cliente válido", "danger")
            db.close()
            return redirect(url_for("cotizaciones_form", cot_id=cot_id) if edit else url_for("cotizaciones_form"))
        version = (request.form.get("version") or "1").strip().lstrip("Vv") or "1"
        titulo = (request.form.get("titulo") or "").strip() or None
        proyecto = (request.form.get("proyecto") or "").strip() or None
        asunto = (request.form.get("asunto") or "").strip() or None
        patente = (request.form.get("patente") or "").strip() or None
        slug_cot = (session.get("tenant_slug") or "").strip().lower()
        if not modulo_visible(slug_cot, "taller_ot"):
            patente = None
        elif not patente and edit:
            try:
                patente = edit["patente"]
            except (KeyError, IndexError):
                patente = None
        if modulo_visible(slug_cot, "taller_ot"):
            from rmweb import ops_taller as _taller

            _taller.ensure_taller_schema(db)
        estado = request.form.get("estado") or "borrador"
        try:
            fecha = _fecha_cotizacion_form(request.form.get("fecha"))
        except ValueError:
            flash("Fecha inválida. Use formato AAAA-MM-DD (ej. 2026-08-27).", "danger")
            db.close()
            return redirect(url_for("cotizaciones_form", cot_id=cot_id) if edit else url_for("cotizaciones_form"))
        validez = int(request.form.get("validez") or validez_def)
        gg_pct = _form_pct("gg_pct", gg_def)
        utilidad_pct = _form_pct("utilidad_pct", util_def)
        iva_pct = _form_pct("iva_pct", iva_def) / 100.0
        notas = (request.form.get("notas") or "").strip() or None
        tipo_venta = (request.form.get("tipo_venta") or "servicio").strip().lower()
        if tipo_venta not in {"servicio", "producto", "arriendo"}:
            tipo_venta = "servicio"
        if tipo_venta == "arriendo" and not modulo_visible(slug_cot, "arriendos"):
            tipo_venta = "servicio"

        descs = request.form.getlist("desc")
        obss = request.form.getlist("obs")
        unds = request.form.getlist("und")
        cants = request.form.getlist("cant")
        valores = request.form.getlist("valor")
        pids = request.form.getlist("producto_id")
        diass = request.form.getlist("dias")
        lineas = []
        orden = 0
        for i, desc in enumerate(descs):
            d = str(desc).strip()
            try:
                pid = int(pids[i] or 0) if i < len(pids) else 0
            except (TypeError, ValueError):
                pid = 0
            pid = pid or None
            try:
                dias_arr = float(diass[i] or 0) if i < len(diass) else 0.0
            except (TypeError, ValueError):
                dias_arr = 0.0
            if tipo_venta == "arriendo" and pid and not d:
                prow = db.execute(
                    "SELECT nombre, unidad, COALESCE(tarifa_arriendo, precio, 0) AS tarifa FROM productos WHERE id=?",
                    (pid,),
                ).fetchone()
                if prow:
                    d = prow["nombre"]
            if not d:
                continue
            if core._is_gg_line(d) or core._is_util_line(d):
                continue
            cant = float(cants[i] or 0)
            pu = float(valores[i] or 0)
            if tipo_venta == "arriendo":
                if cant <= 0 and (pu > 0 or pid):
                    cant = 1.0
                if cant <= 0:
                    continue
                if dias_arr <= 0:
                    flash(f"Ítem «{d}»: indique días de arriendo.", "danger")
                    db.close()
                    return redirect(url_for("cotizaciones_form", cot_id=cot_id) if edit else url_for("cotizaciones_form"))
                if pu <= 0 and pid:
                    prow = db.execute(
                        "SELECT COALESCE(tarifa_arriendo, precio, 0) AS tarifa, unidad FROM productos WHERE id=?",
                        (pid,),
                    ).fetchone()
                    if prow:
                        pu = float(prow["tarifa"] or 0)
                total = cant * dias_arr * pu
                es_srv = 1
                tipo_linea = "arriendo"
                und = (unds[i] if i < len(unds) else "un").strip() or "un"
            else:
                if cant < 0:
                    continue
                if cant <= 0 and pu > 0:
                    cant = 1.0
                if cant == 0 and pu == 0:
                    cant = 1.0
                    pu = 0.0
                if cant <= 0:
                    continue
                total = cant * pu
                es_srv = 1 if tipo_venta == "servicio" else 0
                tipo_linea = None
                dias_arr = 0.0
                und = (unds[i] if i < len(unds) else "un").strip() or "un"
            orden += 1
            lineas.append(
                (
                    pid,
                    d,
                    (obss[i] if i < len(obss) else "").strip() or None,
                    orden,
                    und,
                    cant,
                    pu,
                    total,
                    es_srv,
                    dias_arr,
                    tipo_linea,
                )
            )
        if not lineas:
            flash(
                "Agrega al menos un ítem con descripción y cantidad (o valor unitario).",
                "danger",
            )
        else:
            tots = core.calc_cotizacion_totales(
                sum(x[7] for x in lineas), gg_pct, utilidad_pct, iva_pct
            )
            if edit:
                db.execute(
                    """
                    UPDATE cotizaciones SET
                      cliente_id=?, asunto=?, proyecto=?, patente=?, estado=?, fecha=?, validez_dias=?,
                      version=?, titulo=?, gg_pct=?, utilidad_pct=?,
                      gg_monto=?, utilidad_monto=?, valor_neto=?,
                      subtotal=?, iva=?, total=?, notas=?, tipo_venta=?
                    WHERE id=?
                    """,
                    (
                        cliente_id, asunto, proyecto, patente, estado, fecha, validez,
                        version, titulo, gg_pct, utilidad_pct,
                        tots["gg_monto"], tots["utilidad_monto"], tots["valor_neto"],
                        tots["subtotal"], tots["iva"], tots["total"], notas, tipo_venta, edit["id"],
                    ),
                )
                db.execute("DELETE FROM cotizacion_items WHERE cotizacion_id=?", (edit["id"],))
                cid = edit["id"]
                folio = edit["folio"]
            else:
                folio = core.next_cotizacion_folio(db)
                cur = db.cursor()
                try:
                    cur.execute(
                        """
                        INSERT INTO cotizaciones
                        (folio, cliente_id, asunto, proyecto, patente, estado, fecha, validez_dias,
                         version, titulo, gg_pct, utilidad_pct,
                         gg_monto, utilidad_monto, valor_neto, subtotal, iva, total, notas, tipo_venta)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            folio, cliente_id, asunto, proyecto, patente, estado,
                            fecha, validez,
                            version, titulo, gg_pct, utilidad_pct,
                            tots["gg_monto"], tots["utilidad_monto"], tots["valor_neto"],
                            tots["subtotal"], tots["iva"], tots["total"], notas, tipo_venta,
                        ),
                    )
                except sqlite3.IntegrityError:
                    db.rollback()
                    flash("No se pudo guardar: folio duplicado. Intente nuevamente.", "danger")
                    db.close()
                    return redirect(url_for("cotizaciones_form"))
                cid = cur.lastrowid
            db.executemany(
                """
                INSERT INTO cotizacion_items
                (cotizacion_id, producto_id, descripcion, obs, orden, unidad, cantidad,
                 precio_unitario, total, es_servicio, dias_arriendo, tipo_linea)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                [(cid, *ln) for ln in lineas],
            )
            db.commit()
            cxc_doc = None
            stock_msg = None
            arriendo_msg = None
            msg = f"{folio} guardada · total {core.clp(tots['total'])}"
            if estado == "aprobada":
                ok_apr, cxc_doc, stock_msg, arriendo_msg = _cotizacion_aprobar_side_effects(
                    db, cid, tipo_venta, slug_cot
                )
                if not ok_apr:
                    _cotizacion_revert_aprobacion(db, cid)
                    db.commit()
                    err = stock_msg or arriendo_msg or "No se pudo completar la aprobación"
                    msg = f"{folio} guardada como borrador · total {core.clp(tots['total'])} · {err}"
                    log_movimiento_demo("COTIZACION", msg)
                    flash(msg, "warning")
                else:
                    db.commit()
                    if cxc_doc:
                        msg += f" · CxC {cxc_doc} generada"
                    if stock_msg and "Sin impacto" not in stock_msg and "ya aplicada" not in stock_msg:
                        msg += f" · {stock_msg}"
                    if arriendo_msg and "ya existe" not in arriendo_msg.lower():
                        msg += f" · {arriendo_msg}"
                    log_movimiento_demo("COTIZACION", msg)
                    flash(msg, "ok")
            else:
                log_movimiento_demo("COTIZACION", msg)
                flash(msg, "ok")
            db.close()
            return redirect(url_for("cotizaciones_detalle", cot_id=cid))

    # defaults for new form title from first client
    titulo_default = ""
    if not edit and clientes:
        titulo_default = (clientes[0]["razon_social"] or "").upper()
    if edit and edit["titulo"]:
        titulo_default = edit["titulo"]

    productos_arriendo = []
    if not edit or (edit and (edit["tipo_venta"] or "servicio") == "arriendo"):
        db2 = core.conn()
        from rmweb import ops as _ops
        _ops.ensure_ops_schema(db2)
        productos_arriendo = db2.execute(
            """
            SELECT id, codigo, nombre, unidad,
                   COALESCE(tarifa_arriendo, precio, 0) AS tarifa,
                   COALESCE(unidad_arriendo, 'día') AS unidad_arriendo
            FROM productos
            WHERE activo=1 AND COALESCE(tipo_item,'')='arriendo'
            ORDER BY nombre
            """
        ).fetchall()
        db2.close()

    db.close()
    return render_template(
        "cotizaciones/form.html",
        active="cotizaciones",
        edit=edit,
        items=items,
        clientes=clientes,
        productos_arriendo=productos_arriendo,
        titulo_default=titulo_default,
        gg_def=gg_def,
        util_def=util_def,
        iva_def=iva_def,
        validez_def=validez_def,
        hoy=core.hoy_chile().isoformat(),
        slots=16,
    )


@app.route("/cotizaciones/<int:cot_id>")
@login_required
def cotizaciones_detalle(cot_id: int):
    db = core.conn()
    cot = db.execute(
        """
        SELECT c.*, cl.razon_social, cl.rut AS cliente_rut
        FROM cotizaciones c LEFT JOIN clientes cl ON cl.id=c.cliente_id
        WHERE c.id=?
        """,
        (cot_id,),
    ).fetchone()
    if not cot:
        flash("Cotización no encontrada", "danger")
        db.close()
        return redirect(url_for("cotizaciones_list"))
    items = db.execute(
        """
        SELECT * FROM cotizacion_items WHERE cotizacion_id=?
        ORDER BY COALESCE(orden,0), id
        """,
        (cot_id,),
    ).fetchall()
    items = [
        it
        for it in items
        if not core._is_gg_line(it["descripcion"]) and not core._is_util_line(it["descripcion"])
    ]
    cxc = None
    if cot["cxc_id"]:
        cxc = db.execute(
            "SELECT id, documento, num_factura, saldo, estado FROM cuentas WHERE id=?",
            (cot["cxc_id"],),
        ).fetchone()
    contrato_arriendo = db.execute(
        "SELECT id, folio, estado FROM arriendo_contratos WHERE cotizacion_id=? LIMIT 1",
        (cot_id,),
    ).fetchone()
    ot_taller = None
    if modulo_visible((session.get("tenant_slug") or "").strip().lower(), "taller_ot"):
        from rmweb import ops_taller as _taller

        _taller.ensure_taller_schema(db)
        ot_taller = db.execute(
            "SELECT id, folio, estado, patente, mecanico FROM taller_ordenes WHERE cotizacion_id=? LIMIT 1",
            (cot_id,),
        ).fetchone()
    db.close()
    return render_template(
        "cotizaciones/detalle.html",
        active="cotizaciones",
        cot=cot,
        items=items,
        cxc=cxc,
        contrato_arriendo=contrato_arriendo,
        ot_taller=ot_taller,
    )


@app.route("/cotizaciones/<int:cot_id>/pdf")
@login_required
def cotizaciones_pdf(cot_id: int):
    db = core.conn()
    cot = db.execute(
        """
        SELECT c.*, cl.razon_social, cl.rut AS cliente_rut
        FROM cotizaciones c LEFT JOIN clientes cl ON cl.id=c.cliente_id
        WHERE c.id=?
        """,
        (cot_id,),
    ).fetchone()
    items = db.execute(
        """
        SELECT descripcion, COALESCE(obs,'') AS obs, unidad, cantidad, precio_unitario, total,
               COALESCE(orden,0) AS orden
        FROM cotizacion_items WHERE cotizacion_id=? ORDER BY COALESCE(orden,0), id
        """,
        (cot_id,),
    ).fetchall()
    empresa = db.execute("SELECT * FROM empresa WHERE id=1").fetchone()
    iva_pct = core.param(db, "iva", 19) / 100.0
    db.close()
    if not cot:
        flash("Cotización no encontrada", "danger")
        return redirect(url_for("cotizaciones_list"))
    pdf = core.cotizacion_pdf_bytes(cot, items, empresa, iva_pct=iva_pct)
    return send_file(
        BytesIO(pdf),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{cot['folio']}.pdf",
    )


@app.route("/cotizaciones/<int:cot_id>/borrar", methods=["POST"])
@login_required
def cotizaciones_borrar(cot_id: int):
    db = core.conn()
    row = db.execute("SELECT folio, cxc_id FROM cotizaciones WHERE id=?", (cot_id,)).fetchone()
    if not row:
        flash("No encontrada", "danger")
    elif row["cxc_id"]:
        flash("No se puede eliminar: tiene CxC vinculada", "danger")
    else:
        db.execute("DELETE FROM cotizacion_items WHERE cotizacion_id=?", (cot_id,))
        db.execute("DELETE FROM cotizaciones WHERE id=?", (cot_id,))
        db.commit()
        log_movimiento_demo("COTIZACION", f"Eliminada {row['folio']}")
        flash(f"{row['folio']} eliminada", "ok")
    db.close()
    return redirect(url_for("cotizaciones_list"))


@app.route("/cotizaciones/<int:cot_id>/estado", methods=["POST"])
@login_required
def cotizaciones_estado(cot_id: int):
    estado = request.form.get("estado") or "borrador"
    db = core.conn()
    from rmweb import ops as _ops
    _ops.ensure_ops_schema(db)
    prev = db.execute(
        "SELECT estado, cliente_id FROM cotizaciones WHERE id=?",
        (cot_id,),
    ).fetchone()
    prev_estado = (prev["estado"] if prev else "borrador") or "borrador"
    prev_cliente_id = int(prev["cliente_id"] or 0) if prev else 0
    db.execute("UPDATE cotizaciones SET estado=? WHERE id=?", (estado, cot_id))
    db.commit()
    cxc_doc = None
    stock_msg = None
    arriendo_msg = None
    ppto_msg = None
    if estado == "aprobada":
        cot_row = db.execute("SELECT tipo_venta FROM cotizaciones WHERE id=?", (cot_id,)).fetchone()
        tv = (cot_row["tipo_venta"] if cot_row else "servicio") or "servicio"
        ok_apr, cxc_doc, stock_msg, arriendo_msg = _cotizacion_aprobar_side_effects(
            db, cot_id, tv, (session.get("tenant_slug") or "").strip().lower()
        )
        if not ok_apr:
            row = db.execute("SELECT cxc_id FROM cotizaciones WHERE id=?", (cot_id,)).fetchone()
            if row and row["cxc_id"]:
                cxc_id = int(row["cxc_id"])
                db.execute("DELETE FROM abonos WHERE cuenta_id=?", (cxc_id,))
                db.execute("DELETE FROM cuentas WHERE id=?", (cxc_id,))
            db.execute(
                "UPDATE cotizaciones SET estado=?, cxc_id=NULL WHERE id=?",
                (prev_estado, cot_id),
            )
            db.commit()
            err = stock_msg or arriendo_msg or "No se pudo aprobar"
            flash(err, "danger")
            db.close()
            return redirect(url_for("cotizaciones_detalle", cot_id=cot_id))
        try:
            from rmweb import constructora as _cst
            _cst.ensure_constructora_schema(db)
            ok_p, ppto_msg = _cst.sincronizar_ppto_obra_desde_cotizacion(db, cot_id)
            if not ok_p:
                ppto_msg = None
        except Exception:
            ppto_msg = None
        db.commit()
    if prev_cliente_id:
        cur_cli = db.execute("SELECT cliente_id FROM cotizaciones WHERE id=?", (cot_id,)).fetchone()
        if cur_cli and int(cur_cli["cliente_id"] or 0) != prev_cliente_id:
            db.execute(
                "UPDATE cotizaciones SET cliente_id=? WHERE id=?",
                (prev_cliente_id, cot_id),
            )
            db.commit()
    db.close()
    if cxc_doc:
        msg = f"Estado actualizado · CxC {cxc_doc} generada automáticamente"
        if stock_msg and "Sin impacto" not in stock_msg and "ya aplicada" not in stock_msg:
            msg += f" · {stock_msg}"
        if arriendo_msg and "ya existe" not in arriendo_msg.lower():
            msg += f" · {arriendo_msg}"
        if ppto_msg:
            msg += f" · {ppto_msg}"
        log_movimiento_demo("COTIZACION", msg)
        flash(msg, "ok")
    else:
        log_movimiento_demo("COTIZACION", f"Estado → {estado} (id {cot_id})")
        flash("Estado actualizado", "ok")
    return redirect(url_for("cotizaciones_detalle", cot_id=cot_id))


# ---------------------------------------------------------------------------
# Cuentas por cobrar
# ---------------------------------------------------------------------------
@app.route("/cuentas/")
@login_required
def cuentas_list():
    q = (request.args.get("q") or "").strip()
    db = core.conn()
    core.scrub_import_labels(db)
    core.sync_cuenta_cotizacion_links(db)
    sql = """
        SELECT cu.*, cl.razon_social AS cliente, cot.folio AS cot_folio
        FROM cuentas cu
        LEFT JOIN clientes cl ON cl.id=cu.cliente_id
        LEFT JOIN cotizaciones cot ON cot.id=cu.cotizacion_id
        WHERE 1=1
    """
    params: list = []
    if q:
        like = f"%{q}%"
        sql += """
            AND (cl.razon_social LIKE ? OR cu.documento LIKE ? OR cu.num_factura LIKE ?
                 OR cu.concepto LIKE ? OR cot.folio LIKE ?)
        """
        params.extend([like, like, like, like, like])
    sql += " ORDER BY date(cu.fecha_emision) DESC, cu.id DESC"
    # Recalcular saldos vs abonos antes de KPIs/tabla.
    for row in db.execute("SELECT id FROM cuentas").fetchall():
        core.recalc_cuenta(db, int(row["id"]))
    db.commit()

    rows = db.execute(sql, params).fetchall()
    docs = []
    for r in rows:
        d = dict(r)
        doc_disp, fac_disp = core.cuenta_doc_factura_display(d)
        d["doc_display"] = doc_disp
        d["factura_display"] = fac_disp
        docs.append(d)

    total_docs = len(docs)
    total_monto = sum(float(d["monto"] or 0) for d in docs)

    def _bucket(d: dict) -> str:
        """Clasifica por saldo/abonado real, no solo por texto de estado."""
        saldo = float(d.get("saldo") or 0)
        abonado = float(d.get("abonado") or 0)
        if saldo <= 0:
            return "pagado"
        if abonado > 0:
            return "abonado"
        return "pendiente"

    abon = [d for d in docs if _bucket(d) == "abonado"]
    pag = [d for d in docs if _bucket(d) == "pagado"]
    # Pendientes = cartera abierta real (todo documento con saldo > 0).
    abiertos = [d for d in docs if float(d.get("saldo") or 0) > 0]
    kpis = {
        "total_docs": total_docs,
        "total_monto": total_monto,
        "pend_n": len(abiertos),
        "pend_m": sum(float(d["saldo"] or 0) for d in abiertos),
        "abon_n": len(abon),
        "abon_m": sum(float(d["saldo"] or 0) for d in abon),
        "pag_n": len(pag),
        "pag_m": sum(float(d["monto"] or 0) for d in pag),
        "tasa": (len(pag) / total_docs * 100) if total_docs else 0,
        "sum_total": sum(float(d["monto"] or 0) for d in docs),
        "sum_abonos": sum(float(d["abonado"] or 0) for d in docs),
        "sum_saldo": sum(float(d["saldo"] or 0) for d in docs),
    }
    db.close()
    return render_template(
        "cuentas/lista.html",
        active="cuentas",
        rows=docs,
        kpis=kpis,
        q=q,
    )


def _reorder_by_ids(rows: list, ids_csv: str | None, *, id_key: str = "id") -> list:
    """Reordena filas según ids visibles en pantalla (csv). Sin ids válidos, conserva el orden."""
    if not rows or not ids_csv:
        return rows
    wanted: list[int] = []
    for part in str(ids_csv).split(","):
        part = part.strip()
        if part.isdigit():
            wanted.append(int(part))
    if not wanted:
        return rows
    by_id = {}
    for r in rows:
        try:
            by_id[int(r[id_key])] = r
        except (KeyError, TypeError, ValueError):
            continue
    ordered = [by_id[i] for i in wanted if i in by_id]
    seen = {i for i in wanted if i in by_id}
    for r in rows:
        try:
            rid = int(r[id_key])
        except (KeyError, TypeError, ValueError):
            ordered.append(r)
            continue
        if rid not in seen:
            ordered.append(r)
    return ordered


def _load_vista360(db, cid: int | None):
    core.scrub_import_labels(db)
    core.sync_cuenta_cotizacion_links(db)
    cli = db.execute("SELECT * FROM clientes WHERE id=?", (cid,)).fetchone() if cid else None
    cuentas = []
    abonos = []
    cots = []
    deuda = 0.0
    if cid:
        rows = db.execute(
            """
            SELECT cu.*, cot.folio AS cot_folio
            FROM cuentas cu
            LEFT JOIN cotizaciones cot ON cot.id = cu.cotizacion_id
            WHERE cu.cliente_id=?
            ORDER BY date(cu.fecha_emision) DESC, cu.id DESC
            """,
            (cid,),
        ).fetchall()
        cuentas = []
        for r in rows:
            d = dict(r)
            doc_disp, fac_disp = core.cuenta_doc_factura_display(d)
            d["doc_display"] = doc_disp
            d["factura_display"] = fac_disp
            cuentas.append(d)
        deuda = sum(float(x["saldo"] or 0) for x in cuentas)
        abono_rows = db.execute(
            """
            SELECT a.id, a.fecha, a.monto, a.medio, a.nota,
                   cu.documento, cu.num_factura, cu.cotizacion_id,
                   cot.folio AS cot_folio
            FROM abonos a
            JOIN cuentas cu ON cu.id=a.cuenta_id
            LEFT JOIN cotizaciones cot ON cot.id = cu.cotizacion_id
            WHERE cu.cliente_id=?
            ORDER BY date(a.fecha) DESC, a.id DESC
            """,
            (cid,),
        ).fetchall()
        abonos = []
        for r in abono_rows:
            d = dict(r)
            doc_disp, _fac = core.cuenta_doc_factura_display(d)
            d["documento"] = doc_disp
            abonos.append(d)
        cots = db.execute(
            """
            SELECT id, folio, fecha, estado, total,
                   COALESCE(titulo, asunto, proyecto,'') AS titulo
            FROM cotizaciones
            WHERE cliente_id=?
            ORDER BY COALESCE(fecha,'') DESC, id DESC
            """,
            (cid,),
        ).fetchall()
    return cli, cuentas, abonos, cots, deuda


@app.route("/cuentas/360")
@login_required
def cuentas_360():
    db = core.conn()
    clientes = db.execute(
        "SELECT id, razon_social FROM clientes WHERE activo=1 ORDER BY razon_social"
    ).fetchall()
    cid = request.args.get("cliente_id", type=int)
    if not cid and clientes:
        cid = clientes[0]["id"]
    cli, cuentas, abonos, cots, deuda = _load_vista360(db, cid)
    sum_abonos = sum(float(a["monto"] or 0) for a in abonos)
    db.close()
    return render_template(
        "cuentas/vista360.html",
        active="cuentas",
        clientes=clientes,
        cid=cid,
        cli=cli,
        cuentas=cuentas,
        abonos=abonos,
        sum_abonos=sum_abonos,
        cots=cots,
        deuda=deuda,
    )


@app.route("/cuentas/360/pdf")
@login_required
def cuentas_360_pdf():
    cid = request.args.get("cliente_id", type=int)
    db = core.conn()
    if not cid:
        flash("Selecciona un cliente", "danger")
        db.close()
        return redirect(url_for("cuentas_360"))
    cli, cuentas, abonos, cots, deuda = _load_vista360(db, cid)
    # Orden = el de la pantalla al momento de generar (ids en querystring).
    cuentas = _reorder_by_ids(cuentas, request.args.get("cuenta_ids"))
    abonos = _reorder_by_ids(abonos, request.args.get("abono_ids"))
    cots = _reorder_by_ids(list(cots) if cots else [], request.args.get("cot_ids"))
    empresa = db.execute("SELECT * FROM empresa WHERE id=1").fetchone()
    db.close()
    if not cli:
        flash("Cliente no encontrado", "danger")
        return redirect(url_for("cuentas_360"))
    pdf = core.estado_cuenta_pdf_bytes(cli, cuentas, abonos, cots, deuda, empresa)
    safe = "".join(ch if ch.isalnum() else "_" for ch in (cli["razon_social"] or "cliente"))[:40]
    return send_file(
        BytesIO(pdf),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"estado_cuenta_{safe}.pdf",
    )


@app.route("/cuentas/nueva", methods=["GET", "POST"])
@app.route("/cuentas/<int:cuenta_id>/editar", methods=["GET", "POST"])
@login_required
def cuentas_form(cuenta_id: int | None = None):
    db = core.conn()
    clientes = db.execute(
        "SELECT id, razon_social FROM clientes WHERE activo=1 ORDER BY razon_social"
    ).fetchall()
    dias = int(core.param(db, "dias_credito", 30))
    edit = db.execute("SELECT * FROM cuentas WHERE id=?", (cuenta_id,)).fetchone() if cuenta_id else None
    if cuenta_id and not edit:
        flash("Documento no encontrado", "danger")
        db.close()
        return redirect(url_for("cuentas_list"))

    if request.method == "POST":
        cliente_id = int(request.form["cliente_id"])
        tipo = request.form.get("tipo_doc") or "EP"
        concepto = (request.form.get("concepto") or "").strip() or None
        monto = float(request.form.get("monto") or 0)
        emision = request.form.get("fecha_emision") or core.hoy_chile().isoformat()
        venc = request.form.get("fecha_vencimiento") or (core.hoy_chile() + timedelta(days=dias)).isoformat()
        facturado = 1 if request.form.get("facturado") else 0
        num_factura = (request.form.get("num_factura") or "").strip() or None
        if facturado and not num_factura:
            flash("Ingresa el número de factura", "danger")
        else:
            if facturado or num_factura:
                facturado = 1
            if facturado and tipo == "EP":
                tipo = "FAC"
            if edit:
                db.execute(
                    """
                    UPDATE cuentas SET cliente_id=?, tipo_doc=?, concepto=?, fecha_emision=?,
                      fecha_vencimiento=?, monto=?, facturado=?, num_factura=?
                    WHERE id=?
                    """,
                    (cliente_id, tipo, concepto, emision, venc, monto, facturado, num_factura, edit["id"]),
                )
                core.recalc_cuenta(db, edit["id"])
                db.commit()
                log_movimiento_demo("CXC", f"Documento actualizado id {edit['id']}")
                flash("Documento actualizado", "ok")
                db.close()
                return redirect(url_for("cuentas_detalle", cuenta_id=edit["id"]))
            else:
                doc = core.next_code(db, "cuentas", "documento", tipo if tipo in ("EP", "FAC", "ND") else "EP")
                cur = db.cursor()
                cur.execute(
                    """
                    INSERT INTO cuentas
                    (documento, cliente_id, tipo_doc, concepto, fecha_emision, fecha_vencimiento,
                     monto, abonado, saldo, estado, facturado, num_factura)
                    VALUES (?,?,?,?,?,?,?,0,?, 'pendiente', ?, ?)
                    """,
                    (doc, cliente_id, tipo, concepto, emision, venc, monto, monto, facturado, num_factura),
                )
                new_id = cur.lastrowid
                db.commit()
                log_movimiento_demo("CXC", f"Documento {doc} creado")
                flash(f"Documento {doc} creado", "ok")
                db.close()
                return redirect(url_for("cuentas_detalle", cuenta_id=new_id))

    db.close()
    return render_template(
        "cuentas/form.html",
        active="cuentas",
        edit=edit,
        clientes=clientes,
        dias=dias,
        today=core.hoy_chile().isoformat(),
        vence_default=(core.hoy_chile() + timedelta(days=dias)).isoformat(),
    )


@app.route("/cuentas/<int:cuenta_id>")
@login_required
def cuentas_detalle(cuenta_id: int):
    from urllib.parse import quote
    from rmweb import ml as mlmod

    db = core.conn()
    cuenta = db.execute(
        """
        SELECT cu.*, cl.razon_social, cl.rut AS cliente_rut,
               cl.email AS cliente_email, cl.telefono AS cliente_telefono,
               cl.contacto AS cliente_contacto
        FROM cuentas cu
        LEFT JOIN clientes cl ON cl.id=cu.cliente_id WHERE cu.id=?
        """,
        (cuenta_id,),
    ).fetchone()
    if not cuenta:
        flash("No encontrado", "danger")
        db.close()
        return redirect(url_for("cuentas_list"))
    abonos = db.execute(
        "SELECT * FROM abonos WHERE cuenta_id=? ORDER BY id DESC", (cuenta_id,)
    ).fetchall()
    mlmod.ensure_ml_schema(db)
    mlmod.ensure_mp_links_schema(db)
    cfg = mlmod.get_config_dict(db)
    mp_ready = bool((cfg.get("mp_access_token") or "").strip())
    mp_link = mlmod.get_link_pago(db, cuenta_id)
    saldo = float(cuenta["saldo"] or 0)
    mp_link_stale = False
    if mp_link and saldo > 0:
        try:
            mp_link_stale = abs(float(mp_link.get("monto") or 0) - round(saldo)) > 0.5
        except Exception:
            mp_link_stale = True

    wa_url = mail_url = None
    if mp_link and mp_link.get("init_point"):
        link = mp_link["init_point"]
        doc = str(cuenta["documento"] or "")
        fac = str(cuenta["num_factura"] or "")
        cliente = str(cuenta["razon_social"] or "")
        monto_txt = core.clp(mp_link.get("monto") or saldo)
        msg_lines = [
            f"Hola{(' ' + cliente) if cliente else ''}, te envío el link de pago de {doc}"
            + (f" (Fac. {fac})" if fac else "")
            + f" por {monto_txt}:",
            link,
        ]
        msg = "\n".join(msg_lines)
        phone = "".join(ch for ch in str(cuenta["cliente_telefono"] or "") if ch.isdigit())
        if phone.startswith("0"):
            phone = phone.lstrip("0")
        if phone and not phone.startswith("56") and len(phone) == 9:
            phone = "56" + phone
        wa_url = (
            f"https://wa.me/{phone}?text={quote(msg)}"
            if phone
            else f"https://wa.me/?text={quote(msg)}"
        )
        email = str(cuenta["cliente_email"] or "").strip()
        subject = quote(f"Link de pago {doc}" + (f" · Fac. {fac}" if fac else ""))
        body = quote(msg)
        mail_url = (
            f"mailto:{email}?subject={subject}&body={body}"
            if email
            else f"mailto:?subject={subject}&body={body}"
        )

    ml_demo_ro = (session.get("tenant_slug") or "").strip().lower() == "comercial-demo"
    db.close()
    return render_template(
        "cuentas/detalle.html",
        active="cuentas",
        cuenta=cuenta,
        abonos=abonos,
        mp_ready=mp_ready and not ml_demo_ro,
        mp_link=None if ml_demo_ro else mp_link,
        mp_link_stale=False if ml_demo_ro else mp_link_stale,
        wa_url=None if ml_demo_ro else wa_url,
        mail_url=None if ml_demo_ro else mail_url,
        ml_demo_readonly=ml_demo_ro,
    )



@app.route("/cuentas/<int:cuenta_id>/link-pago", methods=["POST"])
@login_required
def cuentas_link_pago(cuenta_id: int):
    """Genera o regenera link Checkout Pro (Mercado Pago) por el saldo de la CxC."""
    from rmweb import ml as mlmod

    if (session.get("tenant_slug") or "").strip().lower() == "comercial-demo":
        flash("En DEMO no se generan links de Mercado Pago.", "warning")
        return redirect(url_for("cuentas_detalle", cuenta_id=cuenta_id))

    db = core.conn()
    cuenta = db.execute(
        """
        SELECT cu.*, cl.razon_social, cl.email AS cliente_email,
               cl.telefono AS cliente_telefono, cl.contacto AS cliente_contacto
        FROM cuentas cu
        LEFT JOIN clientes cl ON cl.id=cu.cliente_id
        WHERE cu.id=?
        """,
        (cuenta_id,),
    ).fetchone()
    if not cuenta:
        flash("Documento no encontrado", "danger")
        db.close()
        return redirect(url_for("cuentas_list"))
    if float(cuenta["saldo"] or 0) <= 0:
        flash("Documento ya pagado: no se genera link.", "warning")
        db.close()
        return redirect(url_for("cuentas_detalle", cuenta_id=cuenta_id))

    result = mlmod.crear_link_pago_cuenta(db, cuenta)
    db.close()
    flash(
        result.get("msg") or ("Link OK" if result.get("ok") else "Error al generar link"),
        "success" if result.get("ok") else "danger",
    )
    return redirect(url_for("cuentas_detalle", cuenta_id=cuenta_id))

@app.route("/cuentas/<int:cuenta_id>/pdf")
@login_required
def cuentas_pdf(cuenta_id: int):
    db = core.conn()
    cuenta = db.execute(
        """
        SELECT cu.*, cl.razon_social, cl.rut AS cliente_rut,
               COALESCE(cu.tipo_doc, '') AS tipo
        FROM cuentas cu
        LEFT JOIN clientes cl ON cl.id=cu.cliente_id
        WHERE cu.id=?
        """,
        (cuenta_id,),
    ).fetchone()
    if not cuenta:
        db.close()
        flash("Documento no encontrado", "danger")
        return redirect(url_for("cuentas_list"))
    abonos = db.execute(
        "SELECT fecha, monto, medio, nota FROM abonos WHERE cuenta_id=? "
        "ORDER BY date(fecha) DESC, id DESC",
        (cuenta_id,),
    ).fetchall()
    empresa = db.execute("SELECT * FROM empresa WHERE id=1").fetchone()
    db.close()
    pdf = core.cuenta_pdf_bytes(cuenta, abonos, empresa)
    return send_file(
        BytesIO(pdf),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{cuenta['documento']}.pdf",
    )


@app.route("/cuentas/<int:cuenta_id>/abono", methods=["GET", "POST"])
@login_required
def cuentas_abono(cuenta_id: int):
    db = core.conn()
    core.scrub_import_labels(db)
    core.sync_cuenta_cotizacion_links(db)
    cuenta = db.execute(
        """
        SELECT cu.*, cl.razon_social, cot.folio AS cot_folio
        FROM cuentas cu
        LEFT JOIN clientes cl ON cl.id=cu.cliente_id
        LEFT JOIN cotizaciones cot ON cot.id=cu.cotizacion_id
        WHERE cu.id=?
        """,
        (cuenta_id,),
    ).fetchone()
    if not cuenta:
        flash("No encontrado", "danger")
        db.close()
        return redirect(url_for("cuentas_list"))
    if float(cuenta["saldo"] or 0) <= 0:
        flash("Documento ya pagado", "ok")
        db.close()
        return redirect(url_for("cuentas_detalle", cuenta_id=cuenta_id))

    medios = [
        ("Transferencia", "Transferencia"),
        ("Cheque", "Cheque"),
        ("Efectivo", "Efectivo"),
        ("Tarjeta", "Tarjeta"),
        ("Otro", "Otro"),
    ]
    saldo = float(cuenta["saldo"] or 0)
    monto_total = float(cuenta["monto"] or 0)
    abonado = float(cuenta["abonado"] or 0)

    if request.method == "POST":
        monto = float(request.form.get("monto") or 0)
        medio = (request.form.get("medio") or "Transferencia").strip() or "Transferencia"
        nota = (request.form.get("nota") or "").strip() or None
        fecha = (request.form.get("fecha") or "").strip() or core.hoy_chile().isoformat()
        if monto <= 0 or monto > saldo + 0.001:
            flash("Monto inválido: debe ser mayor a 0 y no superar el saldo", "danger")
        else:
            db.execute(
                "INSERT INTO abonos (cuenta_id, fecha, monto, medio, nota) VALUES (?,?,?,?,?)",
                (cuenta_id, fecha, monto, medio, nota),
            )
            core.recalc_cuenta(db, cuenta_id)
            db.commit()
            nuevo = db.execute("SELECT saldo FROM cuentas WHERE id=?", (cuenta_id,)).fetchone()
            saldo_nuevo = float(nuevo["saldo"] or 0) if nuevo else 0.0
            pagado_total = saldo_nuevo <= 0
            log_movimiento_demo(
                "CXC",
                f"{'Pago total' if pagado_total else 'Abono'} {core.clp(monto)} · doc {cuenta['documento']}",
            )
            if pagado_total:
                flash(f"Pago de {core.clp(monto)} registrado. Documento pagado.", "ok")
            else:
                flash(f"Abono de {core.clp(monto)} registrado correctamente.", "ok")
            # Mail de alerta (receptor Super Consola → Alertas). Río Maipo / Comercial.
            try:
                slug = (session.get("tenant_slug") or "").strip().lower()
                ten = get_tenant(slug) if slug else None
                if ten:  # todos los tenants Comercial (incl. DEMO)
                    doc_disp, fac_disp = core.cuenta_doc_factura_display(dict(cuenta))
                    enviar_correo_alerta_pago(
                        secrets_path=ten.get("secrets") or "",
                        tenant_nombre=ten.get("nombre") or slug,
                        usuario=session.get("auth_user") or "",
                        cliente=str(cuenta["razon_social"] or ""),
                        documento=doc_disp or str(cuenta["documento"] or ""),
                        factura=fac_disp or str(cuenta["num_factura"] or ""),
                        monto_abono=monto,
                        monto_fmt=core.clp(monto),
                        medio=medio,
                        fecha=fecha,
                        saldo_nuevo=saldo_nuevo,
                        saldo_fmt=core.clp(saldo_nuevo),
                        nota=nota,
                        pagado_total=pagado_total,
                    )
            except Exception:
                pass
            db.close()
            return redirect(url_for("cuentas_detalle", cuenta_id=cuenta_id))

    abonos = db.execute(
        "SELECT fecha, monto, medio, nota FROM abonos WHERE cuenta_id=? ORDER BY id DESC",
        (cuenta_id,),
    ).fetchall()
    doc_disp, fac_disp = core.cuenta_doc_factura_display(dict(cuenta))
    pct = (abonado / monto_total * 100.0) if monto_total > 0 else 0.0
    saldo_int = int(round(saldo))
    db.close()
    return render_template(
        "cuentas/abono.html",
        active="cuentas",
        cuenta=cuenta,
        abonos=abonos,
        doc_display=doc_disp,
        factura_display=fac_disp,
        medios=medios,
        today=core.hoy_chile().isoformat(),
        saldo_int=saldo_int,
        mitad=int(round(saldo / 2)),
        cuarto=int(round(saldo / 4)),
        pct_pagado=min(100.0, max(0.0, pct)),
    )


@app.route("/cuentas/<int:cuenta_id>/borrar", methods=["POST"])
@login_required
def cuentas_borrar(cuenta_id: int):
    db = core.conn()
    db.execute("UPDATE cotizaciones SET cxc_id=NULL WHERE cxc_id=?", (cuenta_id,))
    db.execute("DELETE FROM abonos WHERE cuenta_id=?", (cuenta_id,))
    db.execute("DELETE FROM cuentas WHERE id=?", (cuenta_id,))
    db.commit()
    db.close()
    log_movimiento_demo("CXC", f"Documento eliminado id {cuenta_id}")
    flash("Documento eliminado", "ok")
    return redirect(url_for("cuentas_list"))


# ---------------------------------------------------------------------------
# Soporte (tickets — inbox en Super Consola)
# ---------------------------------------------------------------------------
@app.route("/soporte/")
@login_required
def soporte():
    from rmweb import soporte as sop

    slug = (session.get("tenant_slug") or "").strip().lower()
    ten = get_tenant(slug) or {}
    usuario = session.get("auth_user") or ""
    sec = (request.args.get("sec") or "nuevo").strip()
    if sec not in ("nuevo", "mis"):
        sec = "nuevo"
    mis = sop.mis_tickets(ten.get("db"), usuario) if usuario else []
    detalle = None
    if sec == "mis" and mis:
        tid = request.args.get("ticket_id", type=int)
        if not tid:
            tid = mis[0]["id"]
        if any(t["id"] == tid for t in mis):
            detalle = sop.ticket_detalle(ten.get("db"), tid, usuario)
    return render_template(
        "soporte.html",
        active="soporte",
        sec=sec,
        mis_tickets=mis,
        ticket_detalle=detalle,
        nombre_erp=sop.nombre_erp_tenant(slug),
    )


@app.route("/soporte/nuevo", methods=["POST"])
@login_required
def soporte_crear():
    from rmweb import soporte as sop

    slug = (session.get("tenant_slug") or "").strip().lower()
    ten = get_tenant(slug) or {}
    usuario = session.get("auth_user") or ""
    ok, msg = sop.crear_ticket(
        db_path=ten.get("db"),
        secrets_path=ten.get("secrets") or "",
        slug=slug,
        usuario=usuario,
        descripcion=request.form.get("descripcion") or "",
    )
    flash(msg, "ok" if ok else "danger")
    return redirect(url_for("soporte", sec="mis" if ok else "nuevo"))


@app.route("/manual/")
@login_required
def manual():
    """Manual de usuario Comercial (guía / completo)."""
    from rmweb import manual_contenido as mc

    doc = (request.args.get("doc") or "guia").strip().lower()
    if doc not in ("guia", "completo"):
        doc = "guia"
    html = mc.MANUAL_COMPLETO_HTML if doc == "completo" else mc.GUIA_RAPIDA_HTML
    return render_template("manual.html", active="manual", doc=doc, html=html)



# Administración (empresa, parámetros, usuarios/claves)
# ---------------------------------------------------------------------------
def _is_admin() -> bool:
    return (session.get("auth_tipo") or "") == "Administrador"


def _admin_redirect(tab: str = "empresa"):
    return redirect(url_for("admin", tab=tab))


@app.route("/admin/")
@login_required
def admin():
    tab = request.args.get("tab") or "empresa"
    if tab not in ("empresa", "parametros", "centros"):
        tab = "empresa"
    db = core.conn()
    empresa = db.execute("SELECT * FROM empresa WHERE id=1").fetchone()
    params = db.execute(
        """
        SELECT clave, nombre, valor, unidad FROM parametros
        WHERE clave != 'auth_seed'
        ORDER BY nombre
        """
    ).fetchall()
    centros = []
    rubros = []
    rubros_uso = {}
    if tab == "centros":
        from rmweb import ops, ops_cc
        ops.ensure_ops_schema(db)
        ops_cc.ensure_cc_schema(db)
        centros = ops_cc.list_centros(db, solo_activos=False)
        rubros = ops_cc.list_rubros(db, solo_activos=False)
        rubros_uso = {
            int(r["id"]): ops_cc.rubro_en_uso(db, int(r["id"])) for r in rubros
        }
    db.close()
    slug = (session.get("tenant_slug") or "").strip().lower()
    # En DEMO se mantiene la clave entregada al invitar (no autocambio).
    puede_cambiar_clave = slug != "comercial-demo"
    return render_template(
        "admin.html",
        active="admin",
        tab=tab,
        empresa=empresa,
        params=params,
        centros=centros,
        rubros=rubros,
        rubros_uso=rubros_uso,
        is_admin=_is_admin(),
        puede_cambiar_clave=puede_cambiar_clave,
        es_demo=(slug == "comercial-demo"),
    )





@app.route("/planes/contratar", methods=["POST"])
@login_required
def planes_contratar():
    """Interés de contratación por pack → ticket Super Consola + mail admin."""
    import sqlite3

    from rmweb import soporte as sop
    from rmweb.pricing import PACK, PACK_COMPRAS, PACK_VENTAS

    slug = (session.get("tenant_slug") or "").strip().lower()
    if slug != "comercial-demo":
        flash("Solo disponible en DEMO Comercial.", "danger")
        return redirect(url_for("dashboard"))

    plan = (request.form.get("plan") or "").strip().lower()
    from rmweb.pricing import MODULOS_FEE as _MFEE
    ml = _MFEE.get("mercadolibre") or {}
    planes = {
        "modulos": ("Por módulo", "pago solo por módulos activados"),
        "ventas": ("Pack Ventas", str(PACK_VENTAS.get("fee_txt") or "")),
        "compras": ("Pack Compras", str(PACK_COMPRAS.get("fee_txt") or "")),
        "comercial": ("Plan Total", str(PACK.get("fee_txt") or "")),
        "mercadolibre": (
            "Integración Mercado Libre (add-on)",
            str(ml.get("fee_txt") or "$29.900/mes")
            + (" · " + str(ml.get("setup_txt") or "") if ml.get("setup_txt") else ""),
        ),
    }
    if plan not in planes:
        flash("Elige un plan válido.", "danger")
        return redirect(url_for("planes"))

    nombre_plan, precio_txt = planes[plan]
    usuario = (session.get("auth_user") or "").strip()
    nombre = (session.get("auth_nombre") or "").strip()
    ten = get_tenant(slug) or {}
    telefono = ""
    fecha_exp = (session.get("auth_fecha_expira") or "").strip()
    try:
        conn = sqlite3.connect(ten.get("db") or "")
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT nombre, invitado_por, fecha_expira FROM usuarios WHERE lower(usuario)=lower(?)",
            (usuario,),
        ).fetchone()
        conn.close()
        if row:
            nombre = nombre or (row["nombre"] or "")
            inv = str(row["invitado_por"] or "")
            if "ig:" in inv:
                # ig:+569... or ig:+569...|contratar:ventas
                part = inv.split("|")[0].strip()
                if part.startswith("ig:"):
                    telefono = part[3:].strip()
            fecha_exp = fecha_exp or (str(row["fecha_expira"] or "")[:10])
    except Exception:
        pass

    desc = (
        f"QUIERO CONTRATAR: {nombre_plan}"
        + (f" ({precio_txt})" if precio_txt else "")
        + "\n\n"
        + f"Usuario prueba: {usuario}\n"
        + f"Nombre: {nombre or '—'}\n"
        + f"Teléfono: {telefono or '—'}\n"
        + f"Vigencia prueba hasta: {fecha_exp or '—'}\n"
        + f"Plan solicitado: {nombre_plan}\n"
    )
    ok, msg = sop.crear_ticket(
        db_path=ten.get("db"),
        secrets_path=ten.get("secrets") or "",
        slug=slug,
        usuario=usuario,
        descripcion=desc,
    )
    if ok:
        try:
            tag = f"contratar:{plan}"
            conn = sqlite3.connect(ten.get("db") or "")
            row = conn.execute(
                "SELECT invitado_por FROM usuarios WHERE lower(usuario)=lower(?)",
                (usuario,),
            ).fetchone()
            prev = (row[0] if row else "") or ""
            base = prev.split("|")[0].strip() if prev else ""
            # drop previous contratar tags from base
            if base.startswith("contratar:"):
                base = ""
            nuevo = f"{base}|{tag}" if base else tag
            conn.execute(
                "UPDATE usuarios SET invitado_por=? WHERE lower(usuario)=lower(?)",
                (nuevo[:120], usuario),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass
        log_movimiento_demo("PLAN", f"Solicitud contratar: {nombre_plan}")
        flash(f"Solicitud de «{nombre_plan}» enviada. Te contactaremos pronto.", "ok")
    else:
        flash(msg, "danger")
    return redirect(url_for("planes"))


@app.route("/demo-entry")
@app.route("/comercial-demo")
def demo_entry_public():
    """Entrada pública (link bio / marketing) → formulario de prueba con OTP."""
    return redirect(url_for("probar"))


@app.route("/probar", methods=["GET", "POST"])
def probar():
    """Landing pública (IG): datos → código por mail → acceso demo (30 días)."""
    import json
    import os
    import sqlite3
    from datetime import datetime, timezone

    from rmweb.demo_invitacion import (
        DEMO_DIAS_PRUEBA,
        crear_y_enviar_codigo_probar,
        es_permanente,
        fecha_fin_prueba,
        login_url_invitado,
        usuario_prueba_vigente,
        validar_codigo_probar,
    )
    from rmweb.tenants import get_tenant

    # Si ya está dentro del ERP, no volver al formulario (evita loop).
    if session.get("auth_ok") and session.get("tenant_slug"):
        flash("Ya tienes una sesión activa.", "ok")
        return redirect(url_for("dashboard"))

    dias = DEMO_DIAS_PRUEBA
    clave_demo = "1234"
    ok = False
    error = None
    info = None
    usuario_demo = ""
    login_url = url_for("login", tenant="comercial-demo")
    fecha_expira_txt = ""
    paso = "datos"  # datos | codigo
    pending_email = ""
    pending_nombre = ""
    pending_telefono = ""
    resend_wait = 0

    ten = get_tenant("comercial-demo") or {}
    secrets_path = ten.get("secrets") or ""

    if request.method == "POST":
        action = (request.form.get("action") or "enviar_codigo").strip()
        nombre = (request.form.get("nombre") or "").strip()
        telefono = (request.form.get("telefono") or "").strip()
        email = (request.form.get("email") or "").strip().lower()

        if action in ("enviar_codigo", "reenviar"):
            if not nombre or not telefono or not email or "@" not in email:
                error = "Completa nombre, teléfono y un correo válido."
            elif es_permanente(email):
                error = "Ese correo es interno. Usa otro mail para la prueba."
            elif not ten.get("db"):
                error = "Demo no disponible. Intenta más tarde."
            else:
                sent_ok, msg, meta = crear_y_enviar_codigo_probar(
                    secrets_path=secrets_path,
                    email=email,
                    nombre=nombre,
                    telefono=telefono,
                    force_resend=(action == "reenviar"),
                )
                if sent_ok:
                    paso = "codigo"
                    info = msg
                    pending_email = (meta or {}).get("email") or email
                    pending_nombre = (meta or {}).get("nombre") or nombre
                    pending_telefono = (meta or {}).get("telefono") or telefono
                    resend_wait = int((meta or {}).get("resend_wait") or 0)
                else:
                    if meta:
                        paso = "codigo"
                        pending_email = meta.get("email") or email
                        pending_nombre = meta.get("nombre") or nombre
                        pending_telefono = meta.get("telefono") or telefono
                        resend_wait = int(meta.get("resend_wait") or 0)
                    error = msg

        elif action == "validar":
            codigo = (request.form.get("codigo") or "").strip()
            pending_email = email
            pending_nombre = nombre
            pending_telefono = telefono
            if not email or "@" not in email:
                error = "Correo inválido. Vuelve a solicitar el código."
                paso = "datos"
            else:
                v_ok, v_msg, payload = validar_codigo_probar(email, codigo)
                if not v_ok:
                    error = v_msg
                    paso = "codigo"
                    if payload:
                        pending_nombre = payload.get("nombre") or nombre
                        pending_telefono = payload.get("telefono") or telefono
                    # Si pide código nuevo, volver a datos solo si se invalidó por intentos/expiración
                    if "Solicita" in (v_msg or "") or "agotaron" in (v_msg or "") or "expiró" in (v_msg or ""):
                        # Mantener paso codigo con opción de reenviar; datos siguen en hidden
                        pass
                else:
                    nombre_u = (payload or {}).get("nombre") or nombre
                    telefono_u = (payload or {}).get("telefono") or telefono
                    email_u = (payload or {}).get("email") or email
                    db_path = ten.get("db") or ""
                    try:
                        salt, digest = core.hash_password(clave_demo)
                        exp = fecha_fin_prueba(dias)
                        conn = sqlite3.connect(db_path)
                        conn.row_factory = sqlite3.Row
                        row = conn.execute(
                            "SELECT id, fecha_expira FROM usuarios WHERE lower(usuario)=lower(?)",
                            (email_u,),
                        ).fetchone()
                        if row:
                            prev = (row["fecha_expira"] or "")[:10]
                            if not usuario_prueba_vigente(prev):
                                exp_use = exp
                            else:
                                exp_use = prev or exp
                            conn.execute(
                                """
                                UPDATE usuarios
                                   SET salt=?, clave_hash=?, nombre=?, tipo='Administrador',
                                       activo=1, fecha_expira=?, invitado_por=?
                                 WHERE id=?
                                """,
                                (
                                    salt,
                                    digest,
                                    nombre_u[:120],
                                    exp_use,
                                    f"ig:{telefono_u}"[:80],
                                    row["id"],
                                ),
                            )
                            exp = exp_use
                        else:
                            conn.execute(
                                """
                                INSERT INTO usuarios
                                  (usuario, salt, clave_hash, nombre, tipo, activo, fecha_expira, invitado_por)
                                VALUES (?,?,?,?, 'Administrador', 1, ?, ?)
                                """,
                                (
                                    email_u,
                                    salt,
                                    digest,
                                    nombre_u[:120],
                                    exp,
                                    f"ig:{telefono_u}"[:80],
                                ),
                            )
                        conn.commit()
                        conn.close()

                        status_dir = (
                            os.environ.get("ERP_STATUS_DIR") or "/root/erp_status"
                        ).strip() or "/root/erp_status"
                        try:
                            os.makedirs(status_dir, exist_ok=True)
                        except Exception:
                            status_dir = "/tmp"
                        path = os.path.join(status_dir, "leads_demo_comercial.jsonl")
                        row_lead = {
                            "ts": datetime.now(timezone.utc).isoformat(),
                            "producto": "comercial",
                            "nombre": nombre_u,
                            "telefono": telefono_u,
                            "email": email_u,
                            "fecha_expira": exp,
                            "ip": (
                                request.headers.get("X-Forwarded-For")
                                or request.remote_addr
                                or ""
                            )[:80],
                            "verificado_mail": True,
                        }
                        with open(path, "a", encoding="utf-8") as fh:
                            fh.write(json.dumps(row_lead, ensure_ascii=False) + "\n")

                        try:
                            log_master_bitacora(
                                "comercial-demo",
                                email_u,
                                "PRUEBA_INICIO",
                                f"{nombre_u} · {telefono_u} · vence {exp}",
                            )
                        except Exception:
                            pass

                        ok = True
                        usuario_demo = email_u
                        login_url = login_url_invitado(email_u)
                        from rmweb.demo_invitacion import (
                            enviar_correo_invitacion_demo,
                            parse_fecha,
                        )
                        from rmweb.mail_alertas import receptor_admin

                        f = parse_fecha(exp)
                        fecha_expira_txt = f.strftime("%d-%m-%Y") if f else exp
                        # Un solo mail de acceso (tras validar el código).
                        try:
                            enviar_correo_invitacion_demo(
                                secrets_path=secrets_path,
                                email=email_u,
                                password_plain=clave_demo,
                                rol="Administrador",
                                admin_email=receptor_admin(secrets_path),
                                fecha_expira=exp,
                                dias=dias,
                            )
                        except Exception:
                            pass
                    except Exception as exc:
                        error = "No se pudo crear el acceso. Intenta de nuevo."
                        paso = "datos"
                        try:
                            app.logger.exception("probar lead: %s", exc)
                        except Exception:
                            pass
        else:
            error = "Acción no válida."

    return render_template(
        "probar.html",
        dias_prueba=dias,
        login_url=login_url,
        usuario_demo=usuario_demo,
        clave_demo=clave_demo,
        fecha_expira_txt=fecha_expira_txt,
        ok=ok,
        error=error,
        info=info,
        paso=paso,
        pending_email=pending_email,
        pending_nombre=pending_nombre,
        pending_telefono=pending_telefono,
        resend_wait=resend_wait,
    )


@app.route("/admin/demo/reseed", methods=["POST"])
@login_required
def admin_demo_reseed():
    """Migrado a Super Consola → Plataforma (DEMO Comercial)."""
    flash(
        "El re-sembrado de datos DEMO se gestiona en Super Consola → Plataforma.",
        "danger",
    )
    return _admin_redirect("empresa")


@app.route("/admin/empresa", methods=["POST"])
@login_required
def admin_empresa():
    db = core.conn()
    db.execute(
        """
        UPDATE empresa SET rut=?, razon_social=?, telefono=?, email=?, direccion=?, region=?, pais=?
        WHERE id=1
        """,
        (
            request.form.get("rut"),
            request.form.get("razon_social"),
            request.form.get("telefono"),
            request.form.get("email"),
            request.form.get("direccion"),
            request.form.get("region"),
            request.form.get("pais") or "Chile",
        ),
    )
    db.commit()
    db.close()
    flash("Empresa actualizada", "ok")
    return _admin_redirect("empresa")


@app.route("/admin/parametro", methods=["POST"])
@login_required
def admin_parametro():
    clave = (request.form.get("clave") or "").strip()
    valor = (request.form.get("valor") or "").strip()
    if not clave or clave == "auth_seed":
        flash("Parámetro no válido", "danger")
        return _admin_redirect("parametros")
    db = core.conn()
    db.execute("UPDATE parametros SET valor=? WHERE clave=?", (valor, clave))
    db.commit()
    db.close()
    flash("Parámetro actualizado", "ok")
    return _admin_redirect("parametros")


@app.route("/admin/clave", methods=["POST"])
@login_required
def admin_clave():
    if (session.get("tenant_slug") or "").strip().lower() == "comercial-demo":
        flash(
            "En DEMO Comercial la clave es la proporcionada al crear el acceso y no se puede cambiar aquí.",
            "danger",
        )
        return _admin_redirect("empresa")
    actual = request.form.get("clave_actual") or ""
    nueva = (request.form.get("clave_nueva") or "").strip()
    nueva2 = (request.form.get("clave_nueva2") or "").strip()
    auth_user = session.get("auth_user") or ""
    if not core.get_user_if_valid(auth_user, actual):
        flash("La clave actual no es correcta", "danger")
    elif len(nueva) < 4:
        flash("La nueva clave debe tener al menos 4 caracteres", "danger")
    elif nueva != nueva2:
        flash("Las claves nuevas no coinciden", "danger")
    else:
        salt, digest = core.hash_password(nueva)
        db = core.conn()
        db.execute(
            "UPDATE usuarios SET salt=?, clave_hash=? WHERE lower(usuario)=lower(?)",
            (salt, digest, auth_user),
        )
        db.commit()
        db.close()
        flash("Clave actualizada", "ok")
    return _admin_redirect("empresa")


@app.route("/admin/usuarios/nuevo", methods=["POST"])
@login_required
def admin_usuario_nuevo():
    flash("Los usuarios se gestionan en Super Consola → Usuarios.", "danger")
    return _admin_redirect("empresa")


@app.route("/admin/usuarios/<int:uid>", methods=["POST"])
@login_required
def admin_usuario_editar(uid: int):
    flash("Los usuarios se gestionan en Super Consola → Usuarios.", "danger")
    return _admin_redirect("empresa")



from rmweb.ops_views import register_ops_routes
from rmweb.ops_oc_views import register_oc_routes
from rmweb.ml_views import register_ml_routes
from rmweb.taller_views import register_taller_routes

register_ops_routes(app, login_required)
register_oc_routes(app, login_required)
register_ml_routes(app, login_required)
register_taller_routes(app, login_required)


def create_app():
    core.init_db()
    return app


if __name__ == "__main__":
    core.init_db()
    port = int(os.getenv("PORT", "8505"))
    app.run(host="0.0.0.0", port=port, debug=True)
