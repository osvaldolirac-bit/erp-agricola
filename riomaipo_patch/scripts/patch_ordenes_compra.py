#!/usr/bin/env python3
"""Instala módulo Órdenes de compra en /comercial (Río Maipo)."""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path("/root/riomaipo/rmweb")
SRC = Path(__file__).resolve().parents[1] / "rmweb"


def _copy(name: str, dest_rel: str) -> None:
    src = SRC / name
    dst = ROOT / dest_rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print(f"OK {dst}")


def _patch_ops_ensure() -> None:
    ops = ROOT / "ops.py"
    text = ops.read_text(encoding="utf-8")
    if "ordenes_compra" in text and "ensure_oc_schema" in text:
        print("ops.py already wired for OC")
        return
    # Call OC schema from ensure_ops_schema
    anchor = '''    core._ensure_columns(
        c,
        "cotizacion_items",
        [("es_servicio", "INTEGER DEFAULT 1")],
    )
'''
    insert = anchor + '''
    try:
        from rmweb import ops_oc
        ops_oc.ensure_oc_schema(c)
    except Exception:
        pass
'''
    if anchor not in text:
        raise SystemExit("FAIL: ensure_ops_schema anchor not found")
    if "ops_oc.ensure_oc_schema" not in text:
        shutil.copy2(ops, ops.with_suffix(".py.bak_oc"))
        ops.write_text(text.replace(anchor, insert, 1), encoding="utf-8")
        print("OK ops.py ensure_oc_schema hook")
    else:
        print("ops.py hook present")


def _patch_ops_views_register() -> None:
    ov = ROOT / "ops_views.py"
    text = ov.read_text(encoding="utf-8")
    if "register_oc_routes" in text:
        print("ops_views.py already registers OC")
        return
    # After register_ops_routes definition start's context processor is fine;
    # register at end of file after register_ops_routes function by appending call site in app.py
    # Instead: patch app.py which already calls register_ops_routes
    shutil.copy2(ov, ov.with_suffix(".py.bak_oc"))
    # Inject import is not needed if app.py imports ops_oc_views
    print("ops_views.py unchanged (OC routes in ops_oc_views)")


def _patch_app_register() -> None:
    app = ROOT / "app.py"
    text = app.read_text(encoding="utf-8")
    marker = "from rmweb.ops_views import register_ops_routes\n\nregister_ops_routes(app, login_required)"
    repl = (
        "from rmweb.ops_views import register_ops_routes\n"
        "from rmweb.ops_oc_views import register_oc_routes\n\n"
        "register_ops_routes(app, login_required)\n"
        "register_oc_routes(app, login_required)"
    )
    if "register_oc_routes" in text:
        print("app.py already registers OC")
        return
    if marker not in text:
        raise SystemExit("FAIL: register_ops_routes block not found in app.py")
    shutil.copy2(app, app.with_suffix(".py.bak_oc"))
    app.write_text(text.replace(marker, repl, 1), encoding="utf-8")
    print("OK app.py register_oc_routes")


def _patch_nav() -> None:
    base = ROOT / "templates" / "base.html"
    text = base.read_text(encoding="utf-8")
    if "oc_list" in text or "Órdenes de compra" in text:
        print("base.html nav already has OC")
        return
    old = '''        <div class="nav-section">Compras</div>
        <a class="nav-link {% if active=='compras' %}active{% endif %}" href="{{ url_for('compras_list') }}">
          <span class="nav-link-main"><i class="bi bi-cart3"></i> Compras</span>
        </a>'''
    new = '''        <div class="nav-section">Compras</div>
        <a class="nav-link {% if active=='ordenes' %}active{% endif %}" href="{{ url_for('oc_list') }}">
          <span class="nav-link-main"><i class="bi bi-clipboard-check"></i> Órdenes de compra</span>
        </a>
        <a class="nav-link {% if active=='compras' %}active{% endif %}" href="{{ url_for('compras_list') }}">
          <span class="nav-link-main"><i class="bi bi-cart3"></i> Compras</span>
        </a>'''
    if old not in text:
        raise SystemExit("FAIL: Compras nav block not found")
    shutil.copy2(base, base.with_suffix(".html.bak_oc"))
    base.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("OK base.html nav")


def _patch_compras_lista_hint() -> None:
    lista = ROOT / "templates" / "compras" / "lista.html"
    if not lista.exists():
        return
    text = lista.read_text(encoding="utf-8")
    if "Órdenes de compra" in text and "oc_list" in text:
        print("compras lista already hints OC")
        return
    old = '''  <div class="d-flex gap-2 flex-wrap">
    <a class="btn btn-outline-secondary" href="{{ url_for('proveedores_list') }}">Proveedores</a>
    <a class="btn btn-outline-primary" href="{{ url_for('tesoreria_list') }}">Tesorería</a>
    <a class="btn btn-primary" href="{{ url_for('compras_form') }}"><i class="bi bi-plus-lg"></i> Nueva compra</a>
  </div>'''
    new = '''  <div class="d-flex gap-2 flex-wrap">
    <a class="btn btn-outline-secondary" href="{{ url_for('proveedores_list') }}">Proveedores</a>
    <a class="btn btn-outline-secondary" href="{{ url_for('oc_list') }}">Órdenes de compra</a>
    <a class="btn btn-outline-primary" href="{{ url_for('tesoreria_list') }}">Tesorería</a>
    <a class="btn btn-primary" href="{{ url_for('compras_form') }}"><i class="bi bi-plus-lg"></i> Nueva compra</a>
  </div>'''
    if old in text:
        shutil.copy2(lista, lista.with_suffix(".html.bak_oc"))
        lista.write_text(text.replace(old, new, 1), encoding="utf-8")
        print("OK compras/lista.html link OC")
    else:
        print("WARN: compras lista buttons block not matched")


def main() -> int:
    _copy("ops_oc.py", "ops_oc.py")
    _copy("ops_oc_views.py", "ops_oc_views.py")
    for name in ("lista.html", "form.html", "detalle.html"):
        _copy(f"templates/ordenes/{name}", f"templates/ordenes/{name}")
    _patch_ops_ensure()
    _patch_ops_views_register()
    _patch_app_register()
    _patch_nav()
    _patch_compras_lista_hint()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
