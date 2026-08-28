#!/usr/bin/env python3
"""Verificación post-deploy del rubro agrícola (/agricola, demo-web).

Comprueba que los estáticos críticos existen, que el CSS modular está
separado (GlobalGAP / Salida Link no dependen solo de erp.css) y que
las rutas públicas principales responden.

Uso:
  python3 verify_agricola.py
  BASE_URL=http://127.0.0.1:8508 PREFIX=/agricola python3 verify_agricola.py
"""
from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8508").rstrip("/")
# Gunicorn (:8508) sirve sin prefijo; nginx externo usa /agricola
PREFIX = os.environ.get("PREFIX", os.environ.get("AGRICOLA_PREFIX", "")).rstrip("/")
DEMO_WEB_ROOT = os.environ.get("DEMO_WEB_ROOT", "/root/demo-web/demo_web")
LOCAL_PORT = os.environ.get("PORT", "8508")


class CheckFailed(Exception):
    pass


def _url(path: str) -> str:
    path = path if path.startswith("/") else f"/{path}"
    if BASE.startswith("http"):
        if PREFIX and path.startswith(PREFIX):
            return f"{BASE}{path[len(PREFIX):] or '/'}"
        if PREFIX:
            return f"{BASE}{PREFIX}{path}"
        return f"{BASE}{path}"
    base_path = PREFIX or ""
    return f"http://127.0.0.1:{LOCAL_PORT}{base_path}{path}"


def http(method: str, path: str):
    req = urllib.request.Request(_url(path), method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _read_local(rel: str) -> str:
    path = os.path.join(DEMO_WEB_ROOT, rel.replace("/", os.sep))
    if not os.path.isfile(path):
        raise CheckFailed(f"missing local file {path}")
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def check_static_salida_link() -> None:
    code, body = http("GET", "/static/css/salida-link.css")
    if code != 200:
        raise CheckFailed(f"salida-link.css HTTP {code}")
    text = body.decode("utf-8", errors="replace")
    if ".salida-petroleo-estanque-valor" not in text:
        raise CheckFailed("salida-link.css missing .salida-petroleo-estanque-valor")
    if "color: #c62828" not in text:
        raise CheckFailed("salida-link.css missing red estanque color")
    print("OK  static salida-link.css")


def check_static_globalgap() -> None:
    code, body = http("GET", "/static/css/globalgap.css")
    if code != 200:
        raise CheckFailed(f"globalgap.css HTTP {code}")
    text = body.decode("utf-8", errors="replace")
    if ".gap-comercial-wrap" not in text:
        raise CheckFailed("globalgap.css missing .gap-comercial-wrap")
    if ".gap-client-donut-row" not in text:
        raise CheckFailed("globalgap.css missing panel consultor donut styles")
    print("OK  static globalgap.css")


def check_erp_css_isolated() -> None:
    code, body = http("GET", "/static/css/erp.css")
    if code != 200:
        raise CheckFailed(f"erp.css HTTP {code}")
    text = body.decode("utf-8", errors="replace")
    if ".salida-petroleo-estanque-valor" in text:
        raise CheckFailed("erp.css still contains salida estanque (should be in salida-link.css)")
    if ".gap-comercial-wrap" in text:
        raise CheckFailed("erp.css still contains GlobalGAP panel (should be in globalgap.css)")
    print("OK  erp.css isolated from salida/globalgap")


def check_local_css_layout() -> None:
    if not os.path.isdir(DEMO_WEB_ROOT):
        print("SKIP local CSS layout (DEMO_WEB_ROOT not found)")
        return
    erp = _read_local("static/css/erp.css")
    salida = _read_local("static/css/salida-link.css")
    gap = _read_local("static/css/globalgap.css")
    if ".salida-petroleo-body" not in salida:
        raise CheckFailed("local salida-link.css incomplete")
    if ".gap-gantt-hero" not in gap:
        raise CheckFailed("local globalgap.css incomplete")
    if ".salida-petroleo-estanque-valor" in erp:
        raise CheckFailed("local erp.css still embeds salida estanque")
    print("OK  local CSS files on disk")


def check_login() -> None:
    code, body = http("GET", "/login")
    if code != 200:
        raise CheckFailed(f"login GET {code}")
    html = body.decode("utf-8", errors="replace")
    if "Acceso" not in html and "login" not in html.lower():
        raise CheckFailed("login page unexpected content")
    print("OK  agricola login")


def check_globalgap_login() -> None:
    code, body = http("GET", "/globalgap/login")
    if code != 200:
        raise CheckFailed(f"globalgap login GET {code}")
    html = body.decode("utf-8", errors="replace")
    if "GlobalGAP" not in html and "globalgap" not in html.lower():
        raise CheckFailed("globalgap login missing branding")
    print("OK  globalgap login")


def check_salida_petroleo_route() -> None:
    code, body = http("GET", "/salida-petroleo")
    if code not in (200, 403):
        raise CheckFailed(f"salida-petroleo GET {code}")
    html = body.decode("utf-8", errors="replace")
    if "salida-link.css" not in html and code == 200:
        raise CheckFailed("salida-petroleo page missing salida-link.css link")
    print("OK  salida-petroleo route")


def check_consola_globalgap_tenant() -> None:
    cfg_path = os.path.join(
        os.environ.get("ERP_MASTER_ROOT", "/root/erp_master"),
        "erp_master",
        "config.py",
    )
    if not os.path.isfile(cfg_path):
        print("SKIP consola tenant (config not on disk)")
        return
    import importlib.util

    spec = importlib.util.spec_from_file_location("erp_master_config", cfg_path)
    if spec is None or spec.loader is None:
        raise CheckFailed(f"cannot load {cfg_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    slugs = {t["slug"] for t in mod.Config.TENANTS}
    if "globalgap" not in slugs:
        raise CheckFailed("consola config missing globalgap tenant")
    print("OK  consola has globalgap tenant")


def main() -> int:
    checks = [
        check_local_css_layout,
        check_static_salida_link,
        check_static_globalgap,
        check_erp_css_isolated,
        check_login,
        check_globalgap_login,
        check_salida_petroleo_route,
        check_consola_globalgap_tenant,
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
    print("\nAll agricola checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
