"""Mock Streamlit que captura widgets como HTML Bootstrap para Flask."""
from __future__ import annotations

import html
import json
import sys
from contextlib import contextmanager
from datetime import date, datetime
from types import ModuleType
from typing import Any, Callable

import pandas as pd

_active: "StreamlitCapture | None" = None


class RerunRedirect(Exception):
    pass


class StopRender(Exception):
    pass


class SessionState(dict):
    def __getitem__(self, key: str) -> Any:
        if key not in self:
            self[key] = None
        return super().__getitem__(key)


class _Ctx:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FormCtx:
    def __init__(self, engine: "StreamlitCapture", form_key: str):
        self.engine = engine
        self.form_key = form_key

    def _action(self) -> str:
        from flask import request

        return html.escape((request.script_root or "") + request.path)

    def __enter__(self):
        self.engine._form_stack.append(self.form_key)
        if not self.engine._in_form_render:
            self.engine._append(
                f'<form method="post" action="{self._action()}" class="demo-st-form card card-body mb-3">'
                f'<input type="hidden" name="_st_form" value="{html.escape(self.form_key)}">'
            )
            self.engine._in_form_render = True
        return self

    def __exit__(self, *args):
        if self.engine._form_stack and self.engine._form_stack[-1] == self.form_key:
            self.engine._form_stack.pop()
        if self.engine._in_form_render and not self.engine._form_stack:
            self.engine._append("</form>")
            self.engine._in_form_render = False


class _ColumnList(list):
    pass


class StreamlitCapture(ModuleType):
    def __init__(
        self,
        st_state: SessionState,
        module_slug: str,
        url_builder: Callable[..., str],
        pdf_store: Callable[[bytes, str], str],
        submitted_check: Callable[..., bool],
    ):
        super().__init__("streamlit")
        self._demo_capture = True
        self.session_state = st_state
        self.module_slug = module_slug
        self.url_builder = url_builder
        self.pdf_store = pdf_store
        self.submitted_check = submitted_check
        self.fragments: list[str] = []
        self.extra_css: list[str] = []
        self.toasts: list[dict] = []
        self._form_stack: list[str] = []
        self._in_form_render = False
        self._row_open = False
        self._widget_defaults: dict[str, Any] = {}

    def finalize(self) -> None:
        if self._row_open:
            self._append("</div>")
            self._row_open = False
        if self._in_form_render:
            self._append("</form>")
            self._in_form_render = False

    def _append(self, piece: str) -> None:
        if piece.startswith("<div class='row"):
            if self._row_open:
                self.fragments.append("</div>")
            self._row_open = True
        elif self._row_open and piece.startswith("<div class='alert"):
            self.fragments.append("</div>")
            self._row_open = False
        self.fragments.append(piece)

    def _field_name(self, key: str | None) -> str:
        return f"st_{key}" if key else ""

    def _get_widget_value(self, key: str | None, default: Any = None) -> Any:
        if key and key in self.session_state and self.session_state[key] is not None:
            return self.session_state[key]
        return default

    def _set_widget_value(self, key: str | None, value: Any) -> Any:
        if key:
            self.session_state[key] = value
        return value

    def set_page_config(self, **kwargs):
        pass

    # ---- Salida -----------------------------------------------------------------
    def markdown(self, body, unsafe_allow_html=False):
        if unsafe_allow_html:
            self._append(str(body))
        else:
            self._append(f"<p>{html.escape(str(body))}</p>")

    def title(self, t):
        self._append(f"<h1 class='h3'>{html.escape(str(t))}</h1>")

    def header(self, t):
        self._append(f"<h2 class='h4'>{html.escape(str(t))}</h2>")

    def subheader(self, t):
        self._append(f"<h3 class='h5 mt-3'>{html.escape(str(t))}</h3>")

    def caption(self, t):
        self._append(f"<p class='text-muted small'>{html.escape(str(t))}</p>")

    def write(self, *args, **kwargs):
        for a in args:
            self.markdown(str(a))

    def info(self, t):
        self._append(f"<div class='alert alert-info'>{t if '<' in str(t) else html.escape(str(t))}</div>")

    def warning(self, t):
        self._append(f"<div class='alert alert-warning'>{html.escape(str(t))}</div>")

    def error(self, t):
        self._append(f"<div class='alert alert-danger'>{html.escape(str(t))}</div>")

    def success(self, t):
        self._append(f"<div class='alert alert-success'>{t if '<' in str(t) else html.escape(str(t))}</div>")

    def divider(self):
        self._append("<hr class='my-3'>")

    def stop(self):
        raise StopRender()

    def rerun(self):
        raise RerunRedirect()

    def toast(self, msg, icon=None):
        self.toasts.append({"body": str(msg), "type": "info"})

    def metric(self, label, value, delta=None):
        self._append(
            f"<div class='border rounded p-2 mb-2'><div class='small text-muted'>{html.escape(str(label))}</div>"
            f"<div class='fs-5 fw-bold'>{html.escape(str(value))}</div></div>"
        )

    def spinner(self, *args, **kwargs):
        return _Ctx()

    def expender(self, *args, **kwargs):
        return _Ctx()

    def container(self):
        return _Ctx()

    def empty(self):
        return self

    def sidebar(self):
        return _Ctx()

    # ---- Layout -----------------------------------------------------------------
    def columns(self, spec, **kwargs):
        n = spec if isinstance(spec, int) else len(spec)
        self._append("<div class='row g-3 mb-2'>")

        class Col:
            def __enter__(self_inner):
                self._append("<div class='col'>")
                return self_inner

            def __exit__(self_inner, *a):
                self._append("</div>")

        return _ColumnList(Col() for _ in range(n))

    def tabs(self, labels):
        self._append("<ul class='nav nav-tabs mb-3'>")
        for i, lb in enumerate(labels):
            active = "active" if i == 0 else ""
            self._append(f"<li class='nav-item'><span class='nav-link {active}'>{html.escape(str(lb))}</span></li>")
        self._append("</ul>")
        return [_Ctx() for _ in labels]

    # ---- Formularios ------------------------------------------------------------
    def form(self, key, clear_on_submit=False, **kwargs):
        return _FormCtx(self, str(key))

    def form_submit_button(self, label, **kwargs):
        key = kwargs.get("key") or f"submit_{self._form_stack[-1]}" if self._form_stack else "submit"
        self._append(
            f"<button type='submit' name='_st_submit' value='{html.escape(str(key))}' "
            f"class='btn btn-success mt-2'>{html.escape(str(label))}</button>"
        )
        if self._form_stack:
            return self.submitted_check(form=self._form_stack[-1])
        return self.submitted_check(key=key)

    def button(self, label, key=None, type="secondary", disabled=False, **kwargs):
        from flask import request

        action = html.escape((request.script_root or "") + request.path)
        if disabled:
            self._append(
                f"<button type='button' class='btn btn-outline-secondary mt-2' disabled>"
                f"{html.escape(str(label))}</button>"
            )
            return False
        if self._in_form_render:
            self._append(
                f"<button type='submit' name='_st_submit' value='{html.escape(str(key or label))}' "
                f"class='btn btn-primary mt-2'>{html.escape(str(label))}</button>"
            )
        else:
            self._append(
                f"<form method='post' action='{action}' class='d-inline'>"
                f"<button type='submit' name='_st_submit' value='{html.escape(str(key or label))}' "
                f"class='btn btn-primary mt-2 me-2'>"
                f"{html.escape(str(label))}</button></form>"
            )
        return self.submitted_check(key=key or label)

    def download_button(self, label, data, file_name=None, key=None, **kwargs):
        if not data:
            return False
        if isinstance(data, str):
            data = data.encode()
        token = self.pdf_store(data, file_name or "documento.pdf")
        href = f"/demo/pdf/{token}" if not self.url_builder else self.url_builder()  # fixed below
        from flask import url_for

        href = url_for("modules.pdf_download", token=token)
        self._append(
            f"<a class='btn btn-outline-success mt-2' href='{href}' download>"
            f"{html.escape(str(label))}</a>"
        )
        return False

    def text_input(self, label, value="", key=None, disabled=False, type=None, **kwargs):
        from flask import request

        fname = self._field_name(key)
        if request.method == "POST" and key and fname in request.form:
            val = request.form[fname]
            return self._set_widget_value(key, val)
        val = self._get_widget_value(key, kwargs.get("value", value))
        val = "" if val is None else val
        dis = "disabled" if disabled else ""
        inp_type = type or "text"
        self._append(
            f"<div class='mb-2'><label class='form-label'>{html.escape(str(label))}</label>"
            f"<input class='form-control' type='{inp_type}' name='{fname}' "
            f"value='{html.escape(str(val))}' {dis}></div>"
        )
        return self._set_widget_value(key, val)

    def text_area(self, label, value="", key=None, height=None, **kwargs):
        from flask import request

        fname = self._field_name(key)
        if request.method == "POST" and key and fname in request.form:
            return self._set_widget_value(key, request.form[fname])
        val = self._get_widget_value(key, kwargs.get("value", value)) or ""
        h = height or 100
        self._append(
            f"<div class='mb-2'><label class='form-label'>{html.escape(str(label))}</label>"
            f"<textarea class='form-control' name='{fname}' "
            f"style='min-height:{int(h)}px'>{html.escape(str(val))}</textarea></div>"
        )
        return self._set_widget_value(key, val)

    def number_input(self, label, min_value=None, max_value=None, value=0.0, key=None, **kwargs):
        from flask import request

        fname = self._field_name(key)
        if request.method == "POST" and key and fname in request.form:
            raw = request.form[fname]
            try:
                val = float(raw)
            except ValueError:
                val = 0.0
            return self._set_widget_value(key, val)
        val = self._get_widget_value(key, kwargs.get("value", value))
        try:
            val = float(val or 0)
        except (TypeError, ValueError):
            val = 0.0
        self._append(
            f"<div class='mb-2'><label class='form-label'>{html.escape(str(label))}</label>"
            f"<input class='form-control' type='number' step='any' name='{fname}' "
            f"value='{val}'></div>"
        )
        return self._set_widget_value(key, val)

    def date_input(self, label, value=None, key=None, **kwargs):
        from flask import request

        fname = self._field_name(key)
        if request.method == "POST" and key and fname in request.form:
            raw = request.form[fname]
            try:
                val = datetime.fromisoformat(raw).date()
            except ValueError:
                val = date.today()
            return self._set_widget_value(key, val)
        val = self._get_widget_value(key, kwargs.get("value", value))
        if isinstance(val, datetime):
            val = val.date()
        if not isinstance(val, date):
            val = date.today()
        self._append(
            f"<div class='mb-2'><label class='form-label'>{html.escape(str(label))}</label>"
            f"<input class='form-control' type='date' name='{fname}' "
            f"value='{val.isoformat()}'></div>"
        )
        return self._set_widget_value(key, val)

    def checkbox(self, label, value=False, key=None, **kwargs):
        from flask import request

        if request.method == "POST" and key:
            checked = request.form.get(self._field_name(key)) == "1"
            return self._set_widget_value(key, checked)
        checked = bool(self._get_widget_value(key, value))
        chk = "checked" if checked else ""
        self._append(
            f"<div class='form-check mb-2'><input class='form-check-input' type='checkbox' "
            f"name='{self._field_name(key)}' value='1' {chk} id='{key or label}'>"
            f"<label class='form-check-label' for='{key or label}'>{html.escape(str(label))}</label></div>"
        )
        return self._set_widget_value(key, checked)

    def radio(self, label, options, horizontal=False, key=None, index=0, **kwargs):
        from flask import request

        opts = list(options or [])
        default = opts[index] if opts else None
        if request.method == "POST" and key and not horizontal:
            fname = self._field_name(key)
            if fname in request.form:
                return self._set_widget_value(key, request.form[fname])
        current = self._get_widget_value(key, default)
        if horizontal and key:
            self._append(f"<div class='mb-2'><div class='small text-muted mb-1'>{html.escape(str(label))}</div>")
            self._append("<ul class='nav nav-pills flex-wrap demo-nav-seccion gap-1 mb-2'>")
            for opt in opts:
                active = "active" if str(opt) == str(current) else ""
                href = self.url_builder(**{key: str(opt)})
                self._append(
                    f"<li class='nav-item'><a class='nav-link {active}' href='{html.escape(href)}'>"
                    f"{html.escape(str(opt))}</a></li>"
                )
            self._append("</ul></div>")
            return self._set_widget_value(key, current)
        name = self._field_name(key)
        self._append(f"<div class='mb-2'><div class='form-label'>{html.escape(str(label))}</div>")
        for i, opt in enumerate(opts):
            checked = "checked" if str(opt) == str(current) else ""
            self._append(
                f"<div class='form-check'><input class='form-check-input' type='radio' name='{name}' "
                f"value='{html.escape(str(opt))}' id='{name}_{i}' {checked}>"
                f"<label class='form-check-label' for='{name}_{i}'>{html.escape(str(opt))}</label></div>"
            )
        self._append("</div>")
        return self._set_widget_value(key, current)

    def selectbox(self, label, options, index=0, key=None, format_func=None, **kwargs):
        from flask import request

        opts = list(options or [])
        default = opts[index] if opts else None
        if request.method == "POST" and key and not str(key).endswith("_nav"):
            fname = self._field_name(key)
            if fname in request.form:
                return self._set_widget_value(key, request.form[fname])
        current = self._get_widget_value(key, default)
        if key and any(k in (key, f"📅 {key}") for k in ()) :
            pass
        # Temporada / navegación por GET
        if key and str(key).endswith("_nav"):
            self._append(f"<div class='mb-2'><label class='form-label'>{html.escape(str(label))}</label>")
            self._append("<div class='btn-group flex-wrap'>")
            for opt in opts:
                label_show = format_func(opt) if format_func else str(opt)
                active = "btn-primary" if str(opt) == str(current) else "btn-outline-primary"
                href = self.url_builder(**{key: str(opt)})
                self._append(
                    f"<a class='btn btn-sm {active}' href='{html.escape(href)}'>"
                    f"{html.escape(str(label_show))}</a> "
                )
            self._append("</div></div>")
            return self._set_widget_value(key, current)
        name = self._field_name(key)
        self._append(f"<div class='mb-2'><label class='form-label'>{html.escape(str(label))}</label>")
        self._append(f"<select class='form-select' name='{name}'>")
        for opt in opts:
            label_show = format_func(opt) if format_func else str(opt)
            sel = "selected" if str(opt) == str(current) else ""
            self._append(
                f"<option value='{html.escape(str(opt))}' {sel}>{html.escape(str(label_show))}</option>"
            )
        self._append("</select></div>")
        return self._set_widget_value(key, current)

    def multiselect(self, label, options, default=None, key=None, **kwargs):
        return self._set_widget_value(key, default or [])

    # ---- Tablas -----------------------------------------------------------------
    def table(self, data):
        self._append(self._df_html(data))

    def dataframe(self, data, use_container_width=True, hide_index=False, **kwargs):
        if hasattr(data, "data"):
            data = data.data
        if isinstance(data, pd.DataFrame):
            self._append(self._df_html(data, hide_index=hide_index))
        else:
            self._append(f"<pre>{html.escape(str(data))}</pre>")

    def data_editor(self, data, key=None, column_config=None, hide_index=False, **kwargs):
        from flask import request

        df = data.copy() if isinstance(data, pd.DataFrame) else pd.DataFrame(data)
        editor_key = key or "data_editor"
        disabled_cols = set()
        if column_config:
            for col, cfg in column_config.items():
                if getattr(cfg, "disabled", False):
                    disabled_cols.add(col)
        if request.method == "POST":
            rows = []
            for ridx, row in df.iterrows():
                nrow = {}
                for col in df.columns:
                    fname = f"stjson_{editor_key}_{ridx}_{col}"
                    if col in disabled_cols or fname not in request.form:
                        nrow[col] = row[col]
                    else:
                        raw = request.form[fname]
                        try:
                            nrow[col] = float(raw)
                        except ValueError:
                            nrow[col] = raw
                rows.append(nrow)
            if rows:
                df = pd.DataFrame(rows)
        self._append("<div class='table-responsive demo-no-datatable'><table class='table table-sm table-bordered'>")
        headers = list(df.columns)
        self._append("<thead><tr>" + "".join(f"<th>{html.escape(str(c))}</th>" for c in headers) + "</tr></thead><tbody>")
        for ridx, row in df.iterrows():
            self._append("<tr>")
            for col in headers:
                val = row[col]
                if col in disabled_cols:
                    self._append(f"<td>{html.escape(str(val))}</td>")
                else:
                    fname = f"stjson_{editor_key}_{ridx}_{col}"
                    self._append(
                        f"<td><input class='form-control form-control-sm' name='{fname}' "
                        f"value='{html.escape(str(val))}'></td>"
                    )
            self._append("</tr>")
        self._append("</tbody></table></div>")
        return df

    def _df_html(self, data, hide_index=False) -> str:
        if not isinstance(data, pd.DataFrame):
            return f"<pre>{html.escape(str(data))}</pre>"
        df = data.copy()
        if hide_index:
            df = df.reset_index(drop=True)
        parts = ["<div class='table-responsive'><table class='table table-sm table-striped table-hover'>"]
        parts.append("<thead><tr>" + "".join(f"<th>{html.escape(str(c))}</th>" for c in df.columns) + "</tr></thead>")
        parts.append("<tbody>")
        for _, row in df.iterrows():
            parts.append("<tr>" + "".join(f"<td>{html.escape(str(v))}</td>" for v in row) + "</tr>")
        parts.append("</tbody></table></div>")
        return "".join(parts)

    def plotly_chart(self, *args, **kwargs):
        self._append("<div class='alert alert-secondary'>Gráfico disponible en versión completa.</div>")

    def pyplot(self, *args, **kwargs):
        pass

    def cache_data(self, *args, **kwargs):
        if args and callable(args[0]):
            return args[0]
        def deco(fn):
            return fn
        return deco

    cache_resource = cache_data

    # column_config namespace
    class column_config:
        class TextColumn:
            def __init__(self, label, disabled=False, **kw):
                self.disabled = disabled

        class NumberColumn:
            def __init__(self, label, disabled=False, **kw):
                self.disabled = disabled


class ComponentsV1(ModuleType):
    def html(self, html_str, height=None, **kwargs):
        if _active:
            h = f" style='min-height:{int(height)}px'" if height else ""
            _active._append(f"<div class='demo-component-html'{h}>{html_str}</div>")


def install_streamlit_capture(**kwargs) -> StreamlitCapture:
    global _active
    st_state = SessionState(kwargs.pop("st_state", {}))
    capture = StreamlitCapture(st_state=st_state, **kwargs)
    _active = capture

    components_v1 = ComponentsV1("streamlit.components.v1")
    components_pkg = ModuleType("streamlit.components")
    components_pkg.v1 = components_v1

    sys.modules["streamlit"] = capture
    sys.modules["streamlit.components"] = components_pkg
    sys.modules["streamlit.components.v1"] = components_v1
    return capture


def uninstall_streamlit_capture() -> None:
    global _active
    _active = None
    from demo_web.services.streamlit_mock import install_streamlit_mock

    install_streamlit_mock()


def get_active_capture() -> StreamlitCapture | None:
    return _active
