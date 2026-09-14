#!/usr/bin/env python3
"""Corrige acceso Super Consola: redirect POST→GET (303) y formulario visible."""
from __future__ import annotations

from pathlib import Path

ROOT = Path("/root/erp_master/erp_master")
APP = ROOT / "app.py"
LOGIN = ROOT / "templates/login.html"

LOGIN_REDIRECT_OLD = "                return redirect(nxt)"
LOGIN_REDIRECT_NEW = "                return redirect(nxt, code=303)"

LOGOUT_REDIRECT_OLD = "        return redirect(url_for(\"login\", out=1))"
LOGOUT_REDIRECT_NEW = "        return redirect(url_for(\"login\", out=1), code=303)"

AUTOOPEN_OLD = """    {% if error or info %}
    const btn = document.querySelector('.login-access-btn');
    if (btn && window.bootstrap) new bootstrap.Dropdown(btn).show();
    {% endif %}"""

AUTOOPEN_NEW = """    const btn = document.querySelector('.login-access-btn');
    if (btn && window.bootstrap) new bootstrap.Dropdown(btn).show();"""


def patch_file(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        if new.split("\n", 1)[0].strip() in text and label != "login redirect":
            print(f"{label}: already patched")
            return
        raise SystemExit(f"{label}: anchor not found in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"{label}: ok")


def main() -> None:
    app = APP.read_text(encoding="utf-8")
    if LOGIN_REDIRECT_OLD not in app:
        if "return redirect(nxt, code=303)" in app:
            print("login redirect: already patched")
        else:
            raise SystemExit("login redirect anchor not found")
    else:
        app = app.replace(LOGIN_REDIRECT_OLD, LOGIN_REDIRECT_NEW, 1)
        APP.write_text(app, encoding="utf-8")
        print("login redirect: ok")

    if LOGOUT_REDIRECT_OLD in APP.read_text(encoding="utf-8"):
        patch_file(APP, LOGOUT_REDIRECT_OLD, LOGOUT_REDIRECT_NEW, "logout redirect")
    else:
        print("logout redirect: already patched or skipped")

    login = LOGIN.read_text(encoding="utf-8")
    if AUTOOPEN_OLD in login:
        LOGIN.write_text(login.replace(AUTOOPEN_OLD, AUTOOPEN_NEW, 1), encoding="utf-8")
        print("login auto-open: ok")
    elif "new bootstrap.Dropdown(btn).show();" in login and "{% if error or info %}" not in login:
        print("login auto-open: already patched")
    else:
        raise SystemExit("login auto-open anchor not found")


if __name__ == "__main__":
    main()
