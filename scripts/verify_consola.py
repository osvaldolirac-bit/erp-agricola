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
import http.cookiejar as cookiejar
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = os.environ.get("BASE_URL", "https://erpmaster.cl/consola").rstrip("/")
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
    ext = path if path.startswith(PREFIX) else f"{PREFIX}{path}"
    return f"http://127.0.0.1:{LOCAL_PORT}{ext}"


def _consola_headers(extra: dict | None = None) -> dict:
    hdrs = dict(extra or {})
    if not BASE.startswith("http") and PREFIX:
        hdrs.setdefault("X-Forwarded-Prefix", PREFIX)
    return hdrs


def http(method: str, path: str, data: dict | None = None, headers: dict | None = None):
    body = None
    hdrs = _consola_headers(headers)
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
    if "login-page" not in html:
        raise CheckFailed("login missing login-page layout")
    if "login-watermark" not in html:
        raise CheckFailed("login missing watermark")
    if "Acceso" not in html:
        raise CheckFailed("login missing Acceso button")
    if "Recordar usuario" not in html:
        raise CheckFailed("login missing Recordar usuario")
    if "fake_user" in html or "fake_pass" in html:
        raise CheckFailed("login still has autofill honeypot fields")

    css_path = os.path.join(
        os.environ.get("ERP_MASTER_ROOT", "/root/erp_master"),
        "erp_master",
        "static",
        "master.css",
    )
    try:
        css = Path(css_path).read_text(encoding="utf-8")
    except OSError as exc:
        raise CheckFailed(f"cannot read master.css: {exc}") from exc
    if ".login-page" not in css or "bg_login_master.png" not in css:
        raise CheckFailed("master.css missing login-page styles (page would look broken)")
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


def check_super_consola_route() -> None:
    email = os.environ.get("ERP_MASTER_SEED_EMAIL", "osvaldolirac@gmail.com")
    password = os.environ.get("ERP_MASTER_SEED_PASSWORD", "Erpmaster2026")
    cj = cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    login_body = urllib.parse.urlencode({"email": email, "password": password}).encode()
    login_req = urllib.request.Request(
        _url("/login"),
        data=login_body,
        headers=_consola_headers({"Content-Type": "application/x-www-form-urlencoded"}),
        method="POST",
    )
    opener.open(login_req)
    for path in ("/cliente/concepcion",):
        req = urllib.request.Request(_url(path), headers=_consola_headers())
        try:
            resp = opener.open(req)
            body = resp.read(12000)
            final = resp.geturl()
        except urllib.error.HTTPError as exc:
            raise CheckFailed(f"{path} status {exc.code}") from exc
        if final.rstrip("/").endswith("/login"):
            raise CheckFailed(f"{path} redirected to login (session/route broken)")
        if b"Super Consola" not in body and b"Usuarios" not in body and b"app-shell" not in body:
            raise CheckFailed(f"{path} missing expected super consola content")
    legacy_req = urllib.request.Request(_url("/concepcion"), headers=_consola_headers())
    try:
        legacy_resp = opener.open(legacy_req)
        legacy_final = legacy_resp.geturl()
    except urllib.error.HTTPError as exc:
        if exc.code not in (301, 302, 303, 307, 308):
            raise CheckFailed(f"legacy /consola/<tenant> status {exc.code}") from exc
        legacy_final = exc.headers.get("Location", "")
    if "/cliente/concepcion" not in legacy_final:
        raise CheckFailed(f"legacy redirect expected /cliente/concepcion, got {legacy_final!r}")
    print("OK  super consola route")


def main() -> int:
    checks = [
        check_health,
        check_tenant_config,
        check_login_ui,
        check_login_flow,
        check_logout_clears,
        check_super_consola_route,
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
