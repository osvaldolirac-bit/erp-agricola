#!/usr/bin/env python3
"""Limpieza total de sesión/correo pegado en Super Consola."""
from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path

APP = Path("/root/erp_master/erp_master/app.py")
LOGIN = Path("/root/erp_master/erp_master/templates/login.html")
CONFIG = Path("/root/erp_master/erp_master/config.py")
SERVICE = Path("/etc/systemd/system/erp-master-web.service")
DB = Path("/root/erp_master.db")

HELPER = '''
def _expire_legacy_session_cookies(response):
    """Invalida cookies viejas de consola (nombre anterior + actual)."""
    from flask import current_app

    names = {
        "erp_master_session",
        "erp_master_session_v2",
        current_app.config.get("SESSION_COOKIE_NAME") or "erp_master_session_v2",
    }
    for name in names:
        if not name:
            continue
        response.delete_cookie(name, path="/")
        response.delete_cookie(name, path="/consola")
    return response


def _clear_master_session(response=None):
    from flask import current_app, make_response, session

    session.clear()
    if response is None:
        response = make_response()
    return _expire_legacy_session_cookies(response)

'''

HELPER_ANCHOR = "def _session_idle_limit(app) -> int:"

LOGIN_FN_OLD = re.compile(
    r'    @app\.route\("/login", methods=\["GET", "POST"\]\)\n'
    r'    def login\(\):.*?'
    r'        return render_template\(\n'
    r'            "login\.html",.*?'
    r'            info=info,\n'
    r'        \)\n',
    re.S,
)

LOGIN_FN_NEW = '''    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        info = None

        if request.method == "POST":
            email = (request.form.get("email") or "").strip()
            password = request.form.get("password") or ""
            user = authenticate(email, password)
            if user:
                session.clear()
                session["master_email"] = user["email"]
                session["master_nombre"] = user.get("nombre") or ""
                session["master_rol"] = user.get("rol") or "admin"
                session["master_tenant"] = user.get("tenant_slug") or ""
                session["last_activity"] = time.time()
                session.permanent = True
                nxt = _safe_next_url(request.args.get("next"))
                resp = redirect(nxt, code=303)
                return _expire_legacy_session_cookies(resp)
            error = "Usuario o clave incorrectos."
        else:
            if request.args.get("out") == "1":
                info = "Sesión cerrada. Ingrese de nuevo."
            resp = make_response(
                render_template(
                    "login.html",
                    brand=app.config["BRAND_NAME"],
                    tagline="Super consola · facultades separadas",
                    error=error,
                    info=info,
                )
            )
            return _clear_master_session(resp)

        resp = make_response(
            render_template(
                "login.html",
                brand=app.config["BRAND_NAME"],
                tagline="Super consola · facultades separadas",
                error=error,
                info=info,
            )
        )
        return _clear_master_session(resp)

'''

LOGOUT_OLD = '''    @app.route("/logout", methods=["GET", "POST"])
    def logout():
        session.clear()
        return redirect(url_for("login", out=1), code=303)'''

LOGOUT_NEW = '''    @app.route("/logout", methods=["GET", "POST"])
    def logout():
        resp = redirect(url_for("login", out=1), code=303)
        return _clear_master_session(resp)'''

LOGIN_HTML = """<!doctype html>
<html lang=\"es\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>{{ brand }} — Acceso</title>
  <link rel=\"icon\" type=\"image/png\" href=\"{{ url_for('static', filename='favicon-32x32.png') }}?v=1785543581\" sizes=\"32x32\">
  <link rel=\"icon\" type=\"image/svg+xml\" href=\"{{ url_for('static', filename='favicon.svg') }}?v=1785543581\">
  <link rel=\"icon\" href=\"{{ url_for('static', filename='favicon.ico') }}?v=1785543581\" sizes=\"any\">
  <link href=\"https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css\" rel=\"stylesheet\">
  <link href=\"https://fonts.googleapis.com/css2?family=Manrope:wght@500;600;700;800&display=swap\" rel=\"stylesheet\">
  <link rel=\"stylesheet\" href=\"{{ url_for('static', filename='master.css') }}\">
</head>
<body class=\"login-page\">
  <div class=\"login-stage\">
    <div class=\"login-watermark\" aria-hidden=\"true\">
      <img src=\"{{ url_for('static', filename='watermark_m.png') }}?v=1785543581\" alt=\"\">
    </div>
    <header class=\"login-top\">
      <div class=\"dropdown login-access\">
        <button class=\"btn login-access-btn dropdown-toggle\" type=\"button\" data-bs-toggle=\"dropdown\" data-bs-auto-close=\"outside\" aria-expanded=\"false\">
          Acceso
        </button>
        <div class=\"dropdown-menu dropdown-menu-end login-access-menu p-3\">
          {% if info %}<div class=\"alert alert-success py-2 mb-2\">{{ info }}</div>{% endif %}
          {% if error %}<div class=\"alert alert-danger py-2 mb-2\" role=\"alert\">{{ error }}</div>{% endif %}
          <p class=\"small text-muted mb-2\">Super Consola · use su correo master (no el del ERP cliente).</p>
          <form method=\"post\" action=\"{{ url_for('login') }}\" autocomplete=\"off\" id=\"loginForm\">
            <div class=\"mb-2\">
              <label class=\"form-label fw-bold mb-1\" for=\"email\">Correo</label>
              <input class=\"form-control\" id=\"email\" name=\"email\" type=\"email\" autocomplete=\"off\" autocapitalize=\"none\" spellcheck=\"false\" required autofocus>
            </div>
            <div class=\"mb-3\">
              <label class=\"form-label fw-bold mb-1\" for=\"password\">Clave</label>
              <input class=\"form-control\" id=\"password\" name=\"password\" type=\"password\" placeholder=\"••••\" autocomplete=\"new-password\" required>
            </div>
            <button class=\"btn login-submit w-100\" type=\"submit\">Ingresar</button>
          </form>
        </div>
      </div>
    </header>

    <footer class=\"login-foot\">
      <img class=\"login-erpmaster\" src=\"{{ url_for('static', filename='logo_erpmaster.png') }}\" alt=\"{{ brand }}\">
    </footer>
  </div>

  <script src=\"https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js\"></script>
  <script>
  (function () {
    try {
      Object.keys(localStorage).forEach(function (k) {
        if (k.indexOf('erp_master') === 0) localStorage.removeItem(k);
      });
    } catch (e) {}

    var emailInput = document.getElementById('email');
    if (emailInput) emailInput.value = '';

    var btn = document.querySelector('.login-access-btn');
    if (btn && window.bootstrap) new bootstrap.Dropdown(btn).show();
  })();
  </script>
</body>
</html>
"""


def ensure_imports(app_text: str) -> str:
    if "make_response" not in app_text.split("from flask import")[1].split(")")[0]:
        app_text = app_text.replace(
            "from flask import (\n    Flask,\n    redirect,\n    render_template,\n    request,\n    session,\n    url_for,\n)",
            "from flask import (\n    Flask,\n    make_response,\n    redirect,\n    render_template,\n    request,\n    session,\n    url_for,\n)",
        )
    return app_text


def main() -> None:
    app = APP.read_text(encoding="utf-8")
    app = ensure_imports(app)

    if "_expire_legacy_session_cookies" not in app:
        if HELPER_ANCHOR not in app:
            raise SystemExit("helper anchor not found")
        app = app.replace(HELPER_ANCHOR, HELPER + HELPER_ANCHOR, 1)
        print("helpers: ok")
    else:
        print("helpers: already")

    m = LOGIN_FN_OLD.search(app)
    if not m:
        if "return _clear_master_session(resp)" in app:
            print("login fn: already patched")
        else:
            raise SystemExit("login fn not found")
    else:
        app = LOGIN_FN_OLD.sub(LOGIN_FN_NEW, app, count=1)
        print("login fn: ok")
    APP.write_text(app, encoding="utf-8")

    app = APP.read_text(encoding="utf-8")
    if LOGOUT_OLD in app:
        APP.write_text(app.replace(LOGOUT_OLD, LOGOUT_NEW, 1), encoding="utf-8")
        print("logout: ok")
    else:
        print("logout: already")

    LOGIN.write_text(LOGIN_HTML, encoding="utf-8")
    print("login.html: ok")

    cfg = CONFIG.read_text(encoding="utf-8")
    if 'erp_master_session_v2' not in cfg:
        cfg = cfg.replace(
            'SESSION_COOKIE_NAME = _env("ERP_MASTER_SESSION_COOKIE", "erp_master_session")',
            'SESSION_COOKIE_NAME = _env("ERP_MASTER_SESSION_COOKIE", "erp_master_session_v2")',
        )
        CONFIG.write_text(cfg, encoding="utf-8")
        print("config cookie: ok")
    else:
        print("config cookie: already")

    svc = SERVICE.read_text(encoding="utf-8")
    if "erp_master_session_v2" not in svc:
        svc = svc.replace(
            "Environment=ERP_MASTER_SESSION_COOKIE=erp_master_session",
            "Environment=ERP_MASTER_SESSION_COOKIE=erp_master_session_v2",
        )
        SERVICE.write_text(svc, encoding="utf-8")
        print("service cookie: ok")
    else:
        print("service cookie: already")

    pwd = "Erpmaster2026"
    h = hashlib.sha256(pwd.encode()).hexdigest()
    db = sqlite3.connect(DB)
    db.execute(
        "UPDATE master_usuarios SET password=?, activo=1 WHERE email=?",
        (h, "osvaldolirac@gmail.com"),
    )
    db.commit()
    print("password reset:", pwd)


if __name__ == "__main__":
    main()
