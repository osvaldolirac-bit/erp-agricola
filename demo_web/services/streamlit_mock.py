"""Mock mínimo de Streamlit para importar app_demo sin ejecutar la UI."""
from __future__ import annotations

import os
import sys
from contextvars import ContextVar
from types import ModuleType
from typing import Any

_session_ctx: ContextVar["SessionState | None"] = ContextVar("demo_st_session", default=None)
_secrets_cache: dict | None = None
_secrets_path: str | None = None


class SessionState(dict):
    def __getitem__(self, key: str) -> Any:
        if key not in self:
            self[key] = None
        return super().__getitem__(key)


class SecretsProxy:
    def __contains__(self, key: object) -> bool:
        return key in _load_secrets()

    def __getitem__(self, key: str) -> Any:
        data = _load_secrets()
        if key not in data:
            raise KeyError(key)
        return data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return _load_secrets().get(key, default)


def _secrets_file_path() -> str:
    global _secrets_path
    if _secrets_path:
        return _secrets_path
    for env_key in ("ERP_SECRETS", "ERP_DEMO_SECRETS"):
        val = os.environ.get(env_key, "").strip()
        if val:
            _secrets_path = val
            return val
    _secrets_path = "/root/.streamlit/secrets.toml"
    return _secrets_path


def set_secrets_path(path: str | None) -> None:
    global _secrets_cache, _secrets_path
    _secrets_cache = None
    _secrets_path = (path or "").strip() or None


def _load_secrets() -> dict:
    global _secrets_cache
    if _secrets_cache is not None:
        return _secrets_cache
    path = _secrets_file_path()
    try:
        try:
            import tomllib

            with open(path, "rb") as fh:
                _secrets_cache = tomllib.load(fh)
        except ImportError:
            import tomli

            with open(path, "rb") as fh:
                _secrets_cache = tomli.load(fh)
    except Exception:
        _secrets_cache = {}
    return _secrets_cache


def _get_session() -> SessionState:
    s = _session_ctx.get()
    if s is None:
        s = SessionState()
        _session_ctx.set(s)
    return s


def bind_demo_session(email: str, rol: str, **extra: Any) -> SessionState:
    s = SessionState(logged_in=True, email=email, rol=rol, **extra)
    _session_ctx.set(s)
    return s


def clear_demo_session() -> None:
    _session_ctx.set(SessionState())


class _CtxMgr:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _noop(*args, **kwargs):
    pass


def _false(*args, **kwargs):
    return False


def _empty_list(*args, **kwargs):
    return []


def _first_opt(*args, **kwargs):
    opts = kwargs.get("options") or (args[1] if len(args) > 1 else [])
    return opts[0] if opts else None


def _columns(spec, **kwargs):
    n = spec if isinstance(spec, int) else len(spec)
    return [_CtxMgr() for _ in range(n)]


def _cache_deco(fn=None, **kwargs):
    if fn and callable(fn):
        return fn

    def wrap(f):
        return f

    return wrap


def install_streamlit_mock() -> ModuleType:
    if isinstance(sys.modules.get("streamlit"), ModuleType) and hasattr(
        sys.modules["streamlit"], "_demo_mock"
    ):
        return sys.modules["streamlit"]

    st = ModuleType("streamlit")
    st._demo_mock = True  # type: ignore[attr-defined]

    components_pkg = ModuleType("streamlit.components")
    components_v1 = ModuleType("streamlit.components.v1")
    components_v1.html = _noop
    components_v1.iframe = _noop
    components_pkg.v1 = components_v1

    st.session_state = property(lambda self: _get_session())  # type: ignore[assignment]
    # property on module doesn't work — use __getattr__ on a wrapper class instead

    class StModule(ModuleType):
        @property
        def session_state(self) -> SessionState:
            return _get_session()

        @property
        def secrets(self) -> SecretsProxy:
            return SecretsProxy()

        def __getattr__(self, name: str):
            defaults = {
                "set_page_config": _noop,
                "markdown": _noop,
                "title": _noop,
                "header": _noop,
                "subheader": _noop,
                "caption": _noop,
                "info": _noop,
                "warning": _noop,
                "error": _noop,
                "success": _noop,
                "divider": _noop,
                "stop": _noop,
                "rerun": _noop,
                "columns": _columns,
                "tabs": lambda labels: [_CtxMgr() for _ in labels],
                "sidebar": _CtxMgr(),
                "form": lambda *a, **k: _CtxMgr(),
                "form_submit_button": _false,
                "button": _false,
                "download_button": _false,
                "checkbox": lambda *a, **k: k.get("value", False),
                "radio": _first_opt,
                "selectbox": _first_opt,
                "multiselect": _empty_list,
                "text_input": lambda *a, **k: k.get("value", ""),
                "text_area": lambda *a, **k: k.get("value", ""),
                "number_input": lambda *a, **k: k.get("value", 0.0),
                "date_input": lambda *a, **k: k.get("value"),
                "time_input": lambda *a, **k: k.get("value"),
                "file_uploader": lambda *a, **k: None,
                "dataframe": _noop,
                "data_editor": lambda *a, **k: a[0] if a else None,
                "metric": _noop,
                "spinner": lambda *a, **k: _CtxMgr(),
                "expander": lambda *a, **k: _CtxMgr(),
                "container": lambda: _CtxMgr(),
                "empty": lambda *a, **k: _CtxMgr(),
                "plotly_chart": _noop,
                "pyplot": _noop,
                "write": _noop,
                "json": _noop,
                "cache_data": _cache_deco,
                "cache_resource": _cache_deco,
                "components": components_pkg,
            }
            if name in defaults:
                return defaults[name]
            raise AttributeError(name)

    st_mod = StModule("streamlit")
    st_mod._demo_mock = True  # type: ignore[attr-defined]

    sys.modules["streamlit"] = st_mod
    sys.modules["streamlit.components"] = components_pkg
    sys.modules["streamlit.components.v1"] = components_v1
    return st_mod
