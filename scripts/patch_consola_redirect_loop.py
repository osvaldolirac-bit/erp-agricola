#!/usr/bin/env python3
"""Evita bucle de redirecciones en Super Consola (login <-> home)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path("/root/erp_master/erp_master")
APP = ROOT / "app.py"
HOME = ROOT / "templates/home.html"
BASE = ROOT / "templates/_base_app.html"

LOGIN_OLD = '''    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.args.get("out") == "1":
            session.clear()
        elif session.get("master_email"):
            return redirect(url_for("home"))'''

LOGIN_NEW = '''    @app.route("/login", methods=["GET", "POST"])
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
                return redirect(url_for("home"))'''

GOLOGIN_OLD = """  function goLogin() {
    window.location = loginUrl;
  }"""

GOLOGIN_NEW = """  function goLogin(forceOut) {
    var u = loginUrl || (prefix + \"/login\");
    if (forceOut && u.indexOf(\"out=\") < 0) {
      u += (u.indexOf(\"?\") >= 0 ? \"&\" : \"?\") + \"out=1\";
    }
    window.location = u;
  }"""


def main() -> None:
    app = APP.read_text(encoding="utf-8")
    if LOGIN_OLD not in app:
        if "last_f is not None and (now - last_f) > idle_limit" in app:
            print("app.py: already patched")
        else:
            raise SystemExit("app.py login anchor not found")
    else:
        APP.write_text(app.replace(LOGIN_OLD, LOGIN_NEW, 1), encoding="utf-8")
        print("app.py: ok")

    home = HOME.read_text(encoding="utf-8")
    if "window.location = '/consola/login?out=1';" in home:
        print("home.html: already patched")
    elif "window.location = '/login';" not in home:
        raise SystemExit("home.html 401 redirect anchor not found")
    else:
        HOME.write_text(
            home.replace(
                "window.location = '/login';",
                "window.location = '/consola/login?out=1';",
            ),
            encoding="utf-8",
        )
        print("home.html: ok")

    base = BASE.read_text(encoding="utf-8")
    changed = False
    if GOLOGIN_OLD in base:
        base = base.replace(GOLOGIN_OLD, GOLOGIN_NEW, 1)
        changed = True
    if "if (res.status === 401) { goLogin(); return false; }" in base:
        base = base.replace(
            "if (res.status === 401) { goLogin(); return false; }",
            "if (res.status === 401) { goLogin(true); return false; }",
            1,
        )
        changed = True
    if changed:
        BASE.write_text(base, encoding="utf-8")
        print("_base_app.html: ok")
    else:
        print("_base_app.html: already patched")


if __name__ == "__main__":
    main()
