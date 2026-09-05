#!/usr/bin/env python3
"""Verificación post-deploy rubro agrícola (VPS producción).

Comprueba estáticos, rutas, separación Libro de Campo vs GlobalGAP,
imports críticos y carga de módulos nativos.

Uso:
  python3 /root/scripts/verify_agricola.py
  APP_ROOT=/root/demo-web python3 /root/scripts/verify_agricola.py
"""
from __future__ import annotations

import importlib.util
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8508").rstrip("/")
PREFIX = os.environ.get("PREFIX", os.environ.get("AGRICOLA_PREFIX", "")).rstrip("/")
DEMO_WEB_ROOT = os.environ.get("DEMO_WEB_ROOT", "/root/demo-web/demo_web")
APP_ROOT = os.environ.get("APP_ROOT", "/root/demo-web")
LOCAL_PORT = os.environ.get("PORT", "8508")

LC_ESPECIES_EXPECTED = frozenset({"Cerezos", "Ciruelos", "Nogales"})
GAP_AMBITOS_EXPECTED = frozenset({"LA CONCEPCION", "CARLOS LIRA", "EL ESPINO"})


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


def _load_app_module(name: str, path: str):
    if not os.path.isfile(path):
        raise CheckFailed(f"missing {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise CheckFailed(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_local_css_layout() -> None:
    if not os.path.isdir(DEMO_WEB_ROOT):
        raise CheckFailed(f"DEMO_WEB_ROOT not found: {DEMO_WEB_ROOT}")
    erp = _read_local("static/css/erp.css")
    salida = _read_local("static/css/salida-link.css")
    gap = _read_local("static/css/globalgap.css")
    if ".salida-petroleo-body" not in salida:
        raise CheckFailed("local salida-link.css incomplete")
    if ".gap-gantt-hero" not in gap and ".gap-comercial-wrap" not in gap:
        raise CheckFailed("local globalgap.css incomplete")
    if ".salida-petroleo-estanque-valor" in erp:
        raise CheckFailed("local erp.css still embeds salida estanque")
    print("OK  local CSS files on disk")


def check_static_salida_link() -> None:
    code, body = http("GET", "/static/css/salida-link.css")
    if code != 200:
        raise CheckFailed(f"salida-link.css HTTP {code}")
    text = body.decode("utf-8", errors="replace")
    if ".salida-petroleo-estanque-valor" not in text:
        raise CheckFailed("salida-link.css missing estanque styles")
    print("OK  static salida-link.css")


def check_static_globalgap() -> None:
    code, body = http("GET", "/static/css/globalgap.css")
    if code != 200:
        raise CheckFailed(f"globalgap.css HTTP {code}")
    text = body.decode("utf-8", errors="replace")
    if ".gap-comercial-wrap" not in text:
        raise CheckFailed("globalgap.css missing .gap-comercial-wrap")
    print("OK  static globalgap.css")


def check_erp_css_isolated() -> None:
    code, body = http("GET", "/static/css/erp.css")
    if code != 200:
        raise CheckFailed(f"erp.css HTTP {code}")
    text = body.decode("utf-8", errors="replace")
    if ".salida-petroleo-estanque-valor" in text:
        raise CheckFailed("erp.css still contains salida estanque")
    if ".gap-comercial-wrap" in text:
        raise CheckFailed("erp.css still contains GlobalGAP panel")
    print("OK  erp.css isolated from salida/globalgap")


def check_login() -> None:
    code, _ = http("GET", "/login")
    if code != 200:
        raise CheckFailed(f"login GET {code}")
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
    if code == 200:
        html = body.decode("utf-8", errors="replace")
        if "salida-link.css" not in html:
            raise CheckFailed("salida-petroleo missing salida-link.css")
    print("OK  salida-petroleo route")


def check_consola_agricola_tenants() -> None:
    cfg_path = os.path.join(
        os.environ.get("ERP_MASTER_ROOT", "/root/erp_master"),
        "erp_master",
        "config.py",
    )
    if not os.path.isfile(cfg_path):
        print("SKIP consola tenant (config not on disk)")
        return
    mod = _load_app_module("erp_master_config", cfg_path)
    slugs = {t["slug"] for t in mod.Config.TENANTS}
    for need in ("globalgap", "espino"):
        if need not in slugs:
            raise CheckFailed(f"consola config missing {need} tenant")
    print("OK  consola has globalgap + espino tenants")


def check_tenant_registry_espino() -> None:
    path = os.path.join(APP_ROOT, "demo_web", "tenants.py")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if '"espino"' not in text or "ERP Agrícola El Espino" not in text:
        raise CheckFailed("tenants.py missing espino entry")
    print("OK  tenants.py has espino")


def check_respaldo_cron_tenants() -> None:
    """Todos los tenants agrícola en tenants.py deben estar en el cron de respaldo."""
    if APP_ROOT not in sys.path:
        sys.path.insert(0, APP_ROOT)
    from demo_web.services.respaldo_cron_clientes import (
        clientes_respaldo_datos,
        tenants_agricola_sin_respaldo_cron,
    )

    faltan = tenants_agricola_sin_respaldo_cron()
    if faltan:
        raise CheckFailed(
            f"tenants agrícola sin respaldo cron: {', '.join(faltan)} "
            "(registrar en demo_web/tenants.py)"
        )

    cron_path = os.environ.get(
        "ERP_RESPALDO_CRON",
        "/root/scripts/erp_respaldo_cron.py",
    )
    if os.path.isfile(cron_path):
        with open(cron_path, encoding="utf-8") as fh:
            cron_src = fh.read()
        if "clientes_respaldo_datos" not in cron_src:
            raise CheckFailed(
                f"{cron_path} no usa clientes_respaldo_datos() — lista hardcodeada obsoleta"
            )
    else:
        print(f"SKIP respaldo cron script (not on disk: {cron_path})")

    slugs = {
        c["slug"]
        for c in clientes_respaldo_datos()
        if c.get("producto") == "agricola"
    }
    for need in ("concepcion", "espino", "demo", "globalgap"):
        if need not in slugs:
            raise CheckFailed(f"respaldo cron missing agricola tenant slug: {need}")
    print("OK  respaldo cron covers all agricola tenants")


def _parse_list_constant(source: str, name: str) -> list[str]:
    import ast

    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                val = ast.literal_eval(node.value)
                if isinstance(val, list):
                    return [str(x) for x in val]
                raise CheckFailed(f"{name} is not a list literal")
    raise CheckFailed(f"{name} not found in app_concepcion.py")


def check_libro_campo_constants() -> None:
    """LIBRO_CAMPO_ESPECIES (cultivos) no debe mezclarse con GAP_ESPECIES (ámbitos)."""
    path = os.path.join(APP_ROOT, "app_concepcion.py")
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    lc = _parse_list_constant(source, "LIBRO_CAMPO_ESPECIES")
    gap = _parse_list_constant(source, "GAP_ESPECIES")
    lc_set = set(lc)
    gap_set = set(gap)
    overlap = lc_set & gap_set
    if overlap:
        raise CheckFailed(f"LIBRO_CAMPO_ESPECIES overlaps GAP_ESPECIES: {overlap}")
    if not LC_ESPECIES_EXPECTED.issubset(lc_set):
        raise CheckFailed(f"LIBRO_CAMPO_ESPECIES missing expected: {LC_ESPECIES_EXPECTED - lc_set}")
    if not GAP_AMBITOS_EXPECTED.issubset(gap_set):
        raise CheckFailed(f"GAP_ESPECIES missing expected ámbitos: {GAP_AMBITOS_EXPECTED - gap_set}")
    print("OK  LC vs GAP constants separated")


def check_libro_campo_module() -> None:
    if APP_ROOT not in sys.path:
        sys.path.insert(0, APP_ROOT)
    from demo_web.services.native.libro_campo import _especies_libro_campo

    class _Demo:
        LIBRO_CAMPO_ESPECIES = ["Cerezos", "Ciruelos", "Nogales"]

    got = _especies_libro_campo(_Demo())
    if got != ["Cerezos", "Ciruelos", "Nogales"]:
        raise CheckFailed(f"_especies_libro_campo unexpected: {got}")

    lc_path = os.path.join(DEMO_WEB_ROOT, "services/native/libro_campo.py")
    src = open(lc_path, encoding="utf-8").read()
    if "pppl_catalogo_sag import resolver_ingrediente_activo" in src:
        raise CheckFailed("libro_campo.py still imports resolver from pppl_catalogo_sag")
    if "demo.GAP_ESPECIES" in src:
        raise CheckFailed("libro_campo.py still references demo.GAP_ESPECIES")
    print("OK  libro_campo module + species helper")


def check_resolver_ingrediente_import() -> None:
    if APP_ROOT not in sys.path:
        sys.path.insert(0, APP_ROOT)
    from erp_inventario_ia import resolver_ingrediente_activo

    if not callable(resolver_ingrediente_activo):
        raise CheckFailed("resolver_ingrediente_activo not callable")
    print("OK  erp_inventario_ia.resolver_ingrediente_activo")


def check_native_modules_compile() -> None:
    native_dir = os.path.join(DEMO_WEB_ROOT, "services/native")
    if not os.path.isdir(native_dir):
        raise CheckFailed(f"missing {native_dir}")
    import py_compile

    errors = []
    for root, _, files in os.walk(native_dir):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(root, fn)
            try:
                py_compile.compile(path, doraise=True)
            except py_compile.PyCompileError as exc:
                errors.append(f"{path}: {exc}")
    if errors:
        raise CheckFailed("native compile errors: " + "; ".join(errors[:3]))
    print("OK  native modules compile")


def check_regression_manifest() -> None:
    """Manifest anti-regresión (cabecera LC, especies, imports)."""
    guard = os.environ.get(
        "REGRESSION_GUARD",
        os.path.join(os.path.dirname(__file__), "regression_guard_agricola.py"),
    )
    if not os.path.isfile(guard):
        raise CheckFailed(f"regression guard missing: {guard}")
    import subprocess

    env = {**os.environ, "APP_ROOT": APP_ROOT}
    proc = subprocess.run(
        [sys.executable, guard, "--quiet", "--no-alert"],
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() or "unknown"
        raise CheckFailed(f"regression manifest: {detail}")
    print("OK  regression manifest (anti-regresión LC)")


def check_libro_campo_session_meta() -> None:
    """Smoke: cabecera evento persiste en sesión Flask (fecha/cuartel/vol_agua)."""
    if APP_ROOT not in sys.path:
        sys.path.insert(0, APP_ROOT)
    os.environ.setdefault("ERP_APP", "agricola")
    from demo_web.wsgi import app
    from demo_web.services.demo_loader import get_demo_module
    from demo_web.services.native import libro_campo as lc
    from demo_web.services.native.libro_campo import META_KEY

    with app.test_request_context(
        "/m/libro-campo",
        method="POST",
        data={
            "fecha": "2026-09-01",
            "cuartel": "CEREZOS CORTE 1",
            "especie": "Cerezos",
            "vol_agua": "1500",
            "aplicador": "TEST VERIFY",
            "maquinaria": "NEB-01",
            "tractor": "",
        },
    ):
        from flask import session

        demo = get_demo_module()
        lc._guardar_evento_meta(demo)
        meta = session.get(META_KEY) or {}
        if meta.get("cuartel") != "CEREZOS CORTE 1":
            raise CheckFailed(f"session meta cuartel lost: {meta!r}")
        if meta.get("vol_agua") != "1500":
            raise CheckFailed(f"session meta vol_agua lost: {meta!r}")
        if meta.get("aplicador") != "TEST VERIFY":
            raise CheckFailed(f"session meta aplicador lost: {meta!r}")
        read = lc._leer_evento_meta(demo)
        if read.get("vol_agua") != "1500":
            raise CheckFailed(f"_leer_evento_meta vol_agua lost: {read!r}")
    print("OK  libro_campo session meta roundtrip")


def main() -> int:
    checks = [
        check_regression_manifest,
        check_local_css_layout,
        check_static_salida_link,
        check_static_globalgap,
        check_erp_css_isolated,
        check_libro_campo_constants,
        check_resolver_ingrediente_import,
        check_libro_campo_module,
        check_libro_campo_session_meta,
        check_native_modules_compile,
        check_login,
        check_globalgap_login,
        check_salida_petroleo_route,
        check_consola_agricola_tenants,
        check_tenant_registry_espino,
        check_respaldo_cron_tenants,
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
