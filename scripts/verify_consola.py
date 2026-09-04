#!/usr/bin/env python3
"""Verificación post-deploy de Super Consola (/consola).

Uso:
  python3 verify_consola.py
  BASE_URL=https://erpmaster.cl/consola python3 verify_consola.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8507").rstrip("/")
PREFIX = os.environ.get("CONSOLA_PREFIX", "/consola")
LOCAL_PORT = os.environ.get("PORT", "8507")

REQUIRED_TENANTS = frozenset(
    {
        "concepcion",
        "demo",
        "globalgap",
        "riomaipo",
        "comercial-lc",
        "comercial-demo",
        "constructora-demo",
    }
)


class CheckFailed(Exception):
    pass


def _url(path: str) -> str:
    path = path if path.startswith("/") else f"/{path}"
    if BASE.startswith("http"):
        if path.startswith(PREFIX):
            return f"{BASE}{path[len(PREFIX):] or '/'}"
        return f"{BASE}{path}"
    return f"http://127.0.0.1:{LOCAL_PORT}{path}"


def http(method: str, path: str, data: dict | None = None, headers: dict | None = None):
    body = None
    hdrs = dict(headers or {})
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
    req = urllib.request.Request(_url(path), data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            return resp.status, dict(resp.headers), raw
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, dict(exc.headers), raw


def check_health() -> None:
    code, _, body = http("GET", "/health")
    if code != 200:
        raise CheckFailed(f"health status {code}")
    data = json.loads(body.decode("utf-8"))
    if not data.get("ok"):
        raise CheckFailed(f"health payload {data!r}")
    print("OK  health")


def check_tenant_config() -> None:
    import importlib.util

    cfg_path = os.path.join(
        os.environ.get("ERP_MASTER_ROOT", "/root/erp_master"),
        "erp_master",
        "config.py",
    )
    spec = importlib.util.spec_from_file_location("erp_master_config", cfg_path)
    if spec is None or spec.loader is None:
        raise CheckFailed(f"cannot load {cfg_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    Config = mod.Config

    slugs = {t["slug"] for t in Config.TENANTS}
    missing = REQUIRED_TENANTS - slugs
    if missing:
        raise CheckFailed(f"config TENANTS missing: {sorted(missing)}")
    admin = {t["slug"] for t in Config.ADMIN_TENANTS}
    if "globalgap" not in admin:
        raise CheckFailed("globalgap missing from ADMIN_TENANTS")
    print(f"OK  tenants ({len(slugs)}): {', '.join(sorted(slugs))}")


def check_login_ui() -> None:
    code, _, body = http("GET", "/login")
    if code != 200:
        raise CheckFailed(f"login GET status {code}")
    html = body.decode("utf-8", errors="replace")
    if "dropdown-toggle" not in html or "Acceso" not in html:
        raise CheckFailed("login missing Acceso dropdown")
    if "Recordar usuario" not in html:
        raise CheckFailed("login missing Recordar usuario")
    if "bootstrap.Dropdown(btn).show()" in html:
        raise CheckFailed("login auto-opens dropdown (must stay closed on load)")
    if "login-center" in html and 'class="login-panel' in html:
        raise CheckFailed("login uses always-visible center panel (deprecated)")
    print("OK  login UI")


def check_login_flow() -> None:
    code, _, body = http("POST", "/login", {"email": "bad@test", "password": "bad"})
    if code != 200:
        raise CheckFailed(f"bad login POST status {code} (expected 200 with error)")
    if b"incorrectos" not in body and b"Incorrect" not in body:
        raise CheckFailed("bad login POST missing error message")
    print("OK  login POST processes credentials")


def check_logout_clears() -> None:
    code, hdrs, _ = http("GET", "/login?out=1")
    if code != 200:
        raise CheckFailed(f"login out=1 status {code}")
    cookies = hdrs.get("Set-Cookie", "")
    if isinstance(cookies, list):
        joined = " ".join(cookies)
    else:
        joined = cookies or ""
    if "Max-Age=0" not in joined and "1970" not in joined:
        raise CheckFailed("login out=1 did not expire session cookie")
    print("OK  logout clears session cookie")


def main() -> int:
    checks = [
        check_health,
        check_tenant_config,
        check_login_ui,
        check_login_flow,
        check_logout_clears,
    ]
    failed = 0
    for fn in checks:
        try:
            fn()
        except CheckFailed as exc:
            print(f"FAIL {fn.__name__}: {exc}", file=sys.stderr)
            failed += 1
        except Exception as exc:
            print(f"FAIL {fn.__name__}: {exc}", file=sys.stderr)
            failed += 1
    if failed:
        print(f"\n{failed} check(s) failed", file=sys.stderr)
        return 1
    print("\nAll consola checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
