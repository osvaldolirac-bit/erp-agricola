#!/usr/bin/env python3
"""Corrige cierre de sesión en Super Consola (/consola)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path("/root/erp_master/erp_master")
APP = ROOT / "app.py"
SIDEBAR = ROOT / "templates/_sidebar.html"
BASE = ROOT / "templates/_base_app.html"
LOGIN = ROOT / "templates/login.html"
NGINX = Path("/etc/nginx/sites-enabled/erpmaster.cl")

OLD_LOGIN_GUARD = """    @app.route("/login", methods=["GET", "POST"])
    def login():
        if session.get("master_email"):
            return redirect(url_for("home"))

        error = None"""

NEW_LOGIN_GUARD = """    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.args.get("out") == "1":
            session.clear()
        elif session.get("master_email"):
            return redirect(url_for("home"))

        error = None"""

OLD_LOGIN_RENDER = """        return render_template(
            "login.html",
            brand=app.config["BRAND_NAME"],
            tagline="Super consola · facultades separadas",
            error=error,
        )"""

NEW_LOGIN_RENDER = """        info = "Sesión cerrada." if request.args.get("out") == "1" else None
        return render_template(
            "login.html",
            brand=app.config["BRAND_NAME"],
            tagline="Super consola · facultades separadas",
            error=error,
            info=info,
        )"""

OLD_LOGOUT = """    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect(url_for("login"))"""

NEW_LOGOUT = """    @app.route("/logout", methods=["GET", "POST"])
    def logout():
        session.clear()
        return redirect(url_for("login", out=1))"""

SIDEBAR_OLD = '<form method="post" action="{{ url_for(\'logout\') }}">'
SIDEBAR_NEW = '<form method="post" action="{{ request.script_root.rstrip(\'/\') }}/logout">'

BASE_OLD = """     data-continue-url="{{ url_for('session_continue') }}"
     data-login-url="{{ url_for('login') }}"
     data-logout-url="{{ url_for('logout') }}"
     data-logout-mode="post\""""

BASE_NEW = """     data-continue-url="{{ request.script_root.rstrip('/') }}/api/session-continue"
     data-login-url="{{ request.script_root.rstrip('/') }}/login"
     data-logout-url="{{ request.script_root.rstrip('/') }}/logout"
     data-logout-mode="post\""""

JS_OLD = """  const continueUrl = root.dataset.continueUrl || '/api/session-continue';
  const loginUrl = root.dataset.loginUrl || '/login';
  const logoutUrl = root.dataset.logoutUrl || '';"""

JS_NEW = """  const prefix = (window.location.pathname || '').startsWith('/consola') ? '/consola' : '';
  const continueUrl = root.dataset.continueUrl || (prefix + '/api/session-continue');
  const loginUrl = root.dataset.loginUrl || (prefix + '/login');
  const logoutUrl = root.dataset.logoutUrl || (prefix + '/logout');"""

LOGIN_INFO_OLD = "{% if error %}<div class=\"alert alert-danger py-2 mb-2\">{{ error }}</div>{% endif %}"
LOGIN_INFO_NEW = (
    "{% if info %}<div class=\"alert alert-success py-2 mb-2\">{{ info }}</div>{% endif %}\n"
    "          {% if error %}<div class=\"alert alert-danger py-2 mb-2\">{{ error }}</div>{% endif %}"
)

NGINX_MARKER = "    location = /login {\n        return 301 /consola/login;\n    }"
NGINX_INSERT = """    location = /login {
        return 301 /consola/login;
    }
    location = /logout {
        return 307 /consola/logout$is_args$args;
    }"""


def patch_file(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        if new.split("\n", 1)[0] in text and label != "nginx":
            print(f"{label}: already patched")
            return
        raise SystemExit(f"{label}: anchor not found in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"{label}: ok")


def main() -> None:
    patch_file(APP, OLD_LOGIN_GUARD, NEW_LOGIN_GUARD, "app login guard")
    patch_file(APP, OLD_LOGIN_RENDER, NEW_LOGIN_RENDER, "app login render")
    patch_file(APP, OLD_LOGOUT, NEW_LOGOUT, "app logout")
    patch_file(SIDEBAR, SIDEBAR_OLD, SIDEBAR_NEW, "sidebar")
    if BASE_OLD in BASE.read_text(encoding="utf-8"):
        patch_file(BASE, BASE_OLD, BASE_NEW, "base_app urls")
    else:
        print("base_app urls: skipped (pattern differs)")
    if JS_OLD in BASE.read_text(encoding="utf-8"):
        patch_file(BASE, JS_OLD, JS_NEW, "base_app js")
    else:
        print("base_app js: skipped (pattern differs)")
    if LOGIN_INFO_OLD in LOGIN.read_text(encoding="utf-8"):
        patch_file(LOGIN, LOGIN_INFO_OLD, LOGIN_INFO_NEW, "login template")
    else:
        print("login template: skipped")
    nginx = NGINX.read_text(encoding="utf-8")
    if "location = /logout" in nginx:
        print("nginx: already has /logout")
    elif NGINX_MARKER not in nginx:
        raise SystemExit("nginx: login marker not found")
    else:
        NGINX.write_text(nginx.replace(NGINX_MARKER, NGINX_INSERT, 1), encoding="utf-8")
        print("nginx: ok")


if __name__ == "__main__":
    main()
