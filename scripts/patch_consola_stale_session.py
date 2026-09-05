#!/usr/bin/env python3
"""Evita que cookies de sesión antiguas bloqueen el login (POST ignorado / bucle)."""
from __future__ import annotations

from pathlib import Path

APP = Path("/root/erp_master/erp_master/app.py")
BASE = Path("/root/erp_master/erp_master/templates/_base_app.html")
LOGIN = Path("/root/erp_master/erp_master/templates/login.html")

HELPER = '''

def _session_idle_limit(app) -> int:
    return int(app.config.get("SESSION_IDLE_SECONDS") or 7200)


def _session_is_active(app) -> bool:
    """Sesión usable: email presente y sin expirar por inactividad."""
    if not session.get("master_email"):
        return False
    now = time.time()
    idle_limit = _session_idle_limit(app)
    try:
        last_f = float(session.get("last_activity"))
    except (TypeError, ValueError):
        return False
    return (now - last_f) <= idle_limit

'''

HELPER_ANCHOR = "def _safe_next_url(nxt: str | None) -> str:"

LOGIN_OLD = '''    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.args.get("out") == "1":
            session.clear()
        elif session.get("master_email"):
            now = time.time()
            idle_limit = int(app.config.get("SESSION_IDLE_SECONDS") or 1200)
            try:
                last_f = float(session.get("last_activity"))
            except (TypeError, ValueError):
                last_f = None
            if last_f is not None and (now - last_f) > idle_limit:
                session.clear()
            else:
                return redirect(url_for("home"))

        error = None
        if request.method == "POST":'''

LOGIN_NEW = '''    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.args.get("out") == "1":
            session.clear()

        error = None
        if request.method == "POST":'''

LOGIN_TAIL_OLD = '''            error = "Usuario o clave incorrectos."

        info = "Sesión cerrada." if request.args.get("out") == "1" else None
        return render_template('''

LOGIN_TAIL_NEW = '''            error = "Usuario o clave incorrectos."
        elif _session_is_active(app):
            return redirect(url_for("home"), code=303)
        elif session.get("master_email"):
            session.clear()

        info = "Sesión cerrada." if request.args.get("out") == "1" else None
        return render_template('''

LOGIN_REQUIRED_OLD = "            return redirect(url_for(\"login\", next=request.path))"
LOGIN_REQUIRED_NEW = "            return redirect(url_for(\"login\", next=request.path, out=1))"

BEFORE_IDLE_OLD = "            return redirect(url_for(\"login\", next=nxt))"
BEFORE_IDLE_NEW = "            return redirect(url_for(\"login\", next=nxt, out=1))"

GOLOGIN_FALLBACK_OLD = "    goLogin();"
GOLOGIN_FALLBACK_NEW = "    goLogin(true);"

LOGIN_JS_OLD = """    if (window.location.search.indexOf('out=1') >= 0) {
      try { localStorage.removeItem(storageKey); } catch (e) {}
    }"""

LOGIN_JS_NEW = """    if (window.location.search.indexOf('out=1') >= 0) {
      try { localStorage.removeItem(storageKey); } catch (e) {}
    } else {
      // Cookie de sesión antigua en el navegador: pedir limpieza al servidor.
      fetch('/consola/api/session-status', { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
        .then(function (res) {
          if (res.status === 401) {
            window.location.replace('/consola/login?out=1');
          }
        })
        .catch(function () {});
    }"""


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        if new.split("\n", 1)[0].strip() in text:
            print(f"{label}: already patched")
            return text
        raise SystemExit(f"{label}: anchor not found")
    print(f"{label}: ok")
    return text.replace(old, new, 1)


def main() -> None:
    app = APP.read_text(encoding="utf-8")

    if "_session_is_active" not in app:
        if HELPER_ANCHOR not in app:
            raise SystemExit("helper anchor not found")
        app = app.replace(HELPER_ANCHOR, HELPER + HELPER_ANCHOR, 1)
        print("helpers: ok")
    else:
        print("helpers: already patched")

    app = replace_once(app, LOGIN_OLD, LOGIN_NEW, "login reorder")
    app = replace_once(app, LOGIN_TAIL_OLD, LOGIN_TAIL_NEW, "login tail")
    app = app.replace(LOGIN_REQUIRED_OLD, LOGIN_REQUIRED_NEW)
    print("login_required out=1: ok")
    app = app.replace(BEFORE_IDLE_OLD, BEFORE_IDLE_NEW)
    print("before_request out=1: ok")
    APP.write_text(app, encoding="utf-8")

    base = BASE.read_text(encoding="utf-8")
    if GOLOGIN_FALLBACK_OLD in base and "goLogin(true);" not in base.split("doLogout")[1][:400]:
        # only the fallback inside doLogout
        idx = base.find("async function doLogout")
        chunk = base[idx:idx + 600]
        if GOLOGIN_FALLBACK_OLD in chunk:
            base = base[:idx] + chunk.replace(GOLOGIN_FALLBACK_OLD, GOLOGIN_FALLBACK_NEW, 1) + base[idx + len(chunk):]
            BASE.write_text(base, encoding="utf-8")
            print("doLogout fallback: ok")
        else:
            print("doLogout fallback: skipped")
    else:
        print("doLogout fallback: already patched")

    login = LOGIN.read_text(encoding="utf-8")
    login = replace_once(login, LOGIN_JS_OLD, LOGIN_JS_NEW, "login stale cookie js")
    LOGIN.write_text(login, encoding="utf-8")


if __name__ == "__main__":
    main()
