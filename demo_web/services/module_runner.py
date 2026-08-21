"""Ejecuta funciones modulo_* de app_demo capturando la UI como HTML Flask."""
from __future__ import annotations

import base64
import importlib
import json
import os
import secrets
from datetime import date, datetime
from typing import Any, Callable
from urllib.parse import urlencode, urlparse, parse_qs, urlunparse

from flask import flash, redirect, request, session, url_for

from demo_web.services.demo_loader import bind_user_session, get_demo_module, get_erp_app
from demo_web.services.module_registry import get_modules
from demo_web.services.st_capture import (
    RerunRedirect,
    StopRender,
    install_streamlit_capture,
    uninstall_streamlit_capture,
)

def _load_modules() -> dict[str, tuple[str, str]]:
    return get_modules()


MODULES: dict[str, tuple[str, str]] = _load_modules()

_ERP_RELOAD = (
    "erp_ui_nav",
    "erp_compras_ui",
    "erp_pdf_ui",
    "erp_caja_chica",
    "erp_soporte",
    "erp_maquinaria",
    "erp_proveedores",
)


def _serialize_val(val: Any) -> Any:
    if isinstance(val, (date, datetime)):
        return {"__t": "date", "v": val.isoformat()}
    if isinstance(val, list):
        return [_serialize_val(x) for x in val]
    if isinstance(val, dict):
        return {str(k): _serialize_val(v) for k, v in val.items()}
    if isinstance(val, (str, int, float, bool)) or val is None:
        return val
    return str(val)


def _deserialize_val(val: Any) -> Any:
    if isinstance(val, dict) and val.get("__t") == "date":
        s = val["v"]
        try:
            return datetime.fromisoformat(s).date()
        except ValueError:
            return datetime.fromisoformat(s)
    if isinstance(val, list):
        return [_deserialize_val(x) for x in val]
    if isinstance(val, dict):
        return {k: _deserialize_val(v) for k, v in val.items()}
    return val


def get_module_state(slug: str) -> dict:
    all_st = session.setdefault("_demo_st", {})
    if slug not in all_st:
        all_st[slug] = {}
    return all_st[slug]


def save_module_state(slug: str, st_state: dict) -> None:
    session.setdefault("_demo_st", {})[slug] = _serialize_val(dict(st_state))
    session.modified = True


def apply_query_to_state(st_state: dict) -> None:
    for key, values in request.args.items():
        if key.startswith("_"):
            continue
        if values:
            st_state[key] = values[0]


def apply_post_to_state(st_state: dict) -> None:
    if request.method != "POST":
        return
    for key, val in request.form.items():
        if key.startswith("st_"):
            st_state[key[3:]] = _coerce_form_value(val)
        elif key.startswith("stjson_"):
            try:
                st_state[key[7:]] = json.loads(val)
            except json.JSONDecodeError:
                pass
    submit = request.form.get("_st_submit")
    if submit:
        st_state[f"__submit__{submit}"] = True
    form = request.form.get("_st_form")
    if form:
        st_state[f"__form_submit__{form}"] = True


def _coerce_form_value(val: str) -> Any:
    if val == "on":
        return True
    if val == "true":
        return True
    if val == "false":
        return False
    try:
        if "." in val:
            return float(val)
        return int(val)
    except ValueError:
        return val


def clear_submit_flags(st_state: dict) -> None:
    for k in list(st_state.keys()):
        if k.startswith("__submit__") or k.startswith("__form_submit__"):
            del st_state[k]


def was_submitted(st_state: dict, key: str | None = None, form_key: str | None = None) -> bool:
    if key and st_state.get(f"__submit__{key}"):
        return True
    if form_key and st_state.get(f"__form_submit__{form_key}"):
        return True
    if key is None and form_key and st_state.get(f"__form_submit__{form_key}"):
        return True
    return False


def store_pdf(blob: bytes, filename: str) -> str:
    from demo_web.services.pdf_cache import store_pdf as _store

    return _store(blob, filename)


def get_pdf(token: str) -> tuple[bytes, str] | None:
    from demo_web.services.pdf_cache import get_pdf as _get

    return _get(token)


def build_module_url(slug: str, **params: str) -> str:
    endpoint = slug.replace("-", "_")
    base = url_for(f"modules.{endpoint}")
    args = request.args.to_dict(flat=True)
    args.update({k: str(v) for k, v in params.items()})
    if not args:
        return base
    return base + "?" + urlencode(args)


def redirect_module(slug: str, **params: str):
    return redirect(build_module_url(slug, **params))


def _reload_demo_modules() -> None:
    import sys

    app_mod = "app_concepcion" if get_erp_app() == "concepcion" else "app_demo"
    erp = __import__(app_mod)

    for name in list(sys.modules):
        if name == app_mod or name.startswith("erp_"):
            try:
                importlib.reload(sys.modules[name])
            except Exception:
                pass
    importlib.reload(erp)


def run_module_view(slug: str, user_email: str, user_rol: str):
    if slug not in MODULES:
        from flask import abort

        abort(404)
    module_key, fn_name = MODULES[slug]
    bind_user_session(user_email, user_rol)

    st_state = get_module_state(slug)
    st_state = _deserialize_val(st_state)
    if not isinstance(st_state, dict):
        st_state = {}
    st_state["email"] = user_email
    st_state["rol"] = user_rol
    st_state["logged_in"] = True
    apply_query_to_state(st_state)
    if request.method == "POST":
        apply_post_to_state(st_state)

    os.environ["ERP_DEMO_FLASK"] = "1"
    capture = install_streamlit_capture(
        st_state=st_state,
        module_slug=slug,
        url_builder=lambda **kw: build_module_url(slug, **kw),
        pdf_store=store_pdf,
        submitted_check=lambda key=None, form=None: was_submitted(st_state, key, form),
    )
    demo = get_demo_module()
    demo.st = capture
    import sys

    for name, mod in sys.modules.items():
        if (name.startswith("erp_") or name == "manual_contenido") and hasattr(mod, "st"):
            mod.st = capture

    try:
        getattr(demo, fn_name)()
    except RerunRedirect:
        save_module_state(slug, st_state)
        clear_submit_flags(st_state)
        return redirect_module(slug)
    except StopRender:
        pass
    finally:
        capture.finalize()
        uninstall_streamlit_capture()

    for msg in capture.toasts:
        flash(msg["body"], msg.get("type", "info"))

    save_module_state(slug, st_state)
    clear_submit_flags(st_state)

    from flask import render_template

    return render_template(
        "modules/captured.html",
        page_title=module_key,
        active_key=module_key,
        title=module_key if module_key != "DASHBOARD" else "Dashboard",
        fragments=capture.fragments,
        extra_css=capture.extra_css,
    )
