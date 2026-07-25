"""Aviso de sitio en mantención — flag escrito por Super Consola ERP Master."""
from __future__ import annotations

import os

from flask import Flask, Response, redirect, request, session

_STATUS_DIR = os.environ.get("ERP_STATUS_DIR", "/root/erp_status").strip() or "/root/erp_status"

_SLUG_BY_APP = {
    "concepcion": "concepcion",
    "demo": "demo",
}


def slug_for_app(erp_app: str) -> str:
    return _SLUG_BY_APP.get((erp_app or "").strip().lower(), "")


def _safe_slug(slug: str) -> str:
    return "".join(c for c in (slug or "").lower() if c.isalnum() or c in "-_")


def en_mantenimiento(slug: str) -> bool:
    safe = _safe_slug(slug)
    if not safe:
        return False
    path = os.path.join(_STATUS_DIR, f"{safe}.mantenimiento")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip() == "1"
    except OSError:
        return False


def session_epoch(slug: str) -> str:
    safe = _safe_slug(slug)
    if not safe:
        return "0"
    path = os.path.join(_STATUS_DIR, f"{safe}.session_epoch")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip() or "0"
    except OSError:
        return "0"


def stamp_session_epoch(slug: str) -> None:
    session["erp_session_epoch"] = session_epoch(slug)


def _post_maint_path(slug: str) -> str:
    return os.path.join(_STATUS_DIR, f"{_safe_slug(slug)}.post_maint")


def en_post_mantenimiento(slug: str) -> bool:
    try:
        with open(_post_maint_path(slug), encoding="utf-8") as f:
            return f.read().strip() == "1"
    except OSError:
        return False


def set_post_mantenimiento(slug: str, activo: bool) -> None:
    path = _post_maint_path(slug)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("1\n" if activo else "0\n")
    except OSError:
        pass


def clear_post_mantenimiento(slug: str) -> None:
    set_post_mantenimiento(slug, False)


def acceso_login_path(app: Flask) -> str:
    """Login limpio del tenant (sin ?next= a módulos viejos)."""
    slug = slug_for_app(app.config.get("ERP_APP", ""))
    expected = {"demo": "/demo", "concepcion": "/laconcepcion"}.get(slug, "")
    prefix = expected or (app.config.get("APPLICATION_ROOT") or "").strip().rstrip("/")
    return f"{prefix}/login"


def _pagina_mantenimiento(titulo: str) -> str:
    safe_title = (titulo or "ERP").replace("<", "").replace(">", "")
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sitio en mantención — {safe_title}</title>
  <style>
    :root {{
      --ink: #1f2a24;
      --muted: #5f6b64;
      --accent: #b45309;
      --line: rgba(31, 42, 36, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(900px 500px at 20% 0%, rgba(180, 83, 9, 0.10), transparent 55%),
        linear-gradient(180deg, #f8f5ee 0%, #ece7db 100%);
      display: grid;
      place-items: center;
      padding: 1.5rem;
    }}
    .card {{
      width: min(520px, 100%);
      background: rgba(247, 244, 236, 0.96);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: 0 16px 40px rgba(31, 42, 36, 0.10);
      padding: 2rem 1.6rem 1.7rem;
      text-align: center;
    }}
    .mark {{
      display: flex;
      justify-content: center;
      align-items: flex-end;
      gap: 1rem;
      height: 56px;
      margin-bottom: 1rem;
    }}
    .cone {{
      width: 0;
      height: 0;
      border-left: 18px solid transparent;
      border-right: 18px solid transparent;
      border-bottom: 40px solid #c2410c;
      position: relative;
    }}
    .cone::after {{
      content: "";
      position: absolute;
      left: -12px;
      top: 14px;
      width: 24px;
      height: 5px;
      background: #1f2a24;
    }}
    .bar {{
      width: 64px;
      height: 12px;
      margin-bottom: 6px;
      border-radius: 3px;
      background: #c2410c;
      border: 1px solid #1f2a24;
    }}
    .badge {{
      display: inline-block;
      background: #fff7ed;
      color: var(--accent);
      border: 1px solid rgba(180, 83, 9, 0.25);
      font-size: .72rem;
      font-weight: 800;
      letter-spacing: .12em;
      text-transform: uppercase;
      padding: .35rem .7rem;
      border-radius: 999px;
      margin-bottom: .85rem;
    }}
    h1 {{
      margin: 0 0 .55rem;
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(1.7rem, 5vw, 2.15rem);
      line-height: 1.1;
      font-weight: 600;
    }}
    p {{
      margin: 0;
      color: var(--muted);
      font-size: 1.02rem;
      line-height: 1.45;
    }}
    .soon {{
      margin-top: 1rem;
      font-weight: 700;
      color: var(--ink);
      font-size: 1.1rem;
    }}
    .foot {{
      margin-top: 1.25rem;
      font-size: .82rem;
      color: #7a7468;
    }}
  </style>
</head>
<body>
  <main class="card">
    <div class="mark" aria-hidden="true">
      <span class="cone"></span>
      <span class="bar"></span>
      <span class="cone"></span>
    </div>
    <div class="badge">Sitio en mantención</div>
    <h1>{safe_title}</h1>
    <p>Estamos realizando una actualización o reparación programada.</p>
    <p class="soon">Regresamos a la brevedad.</p>
    <p class="foot">Más adelante publicaremos datos de contacto aquí.</p>
  </main>
</body>
</html>
"""


def register_mantenimiento(app: Flask) -> None:
    @app.before_request
    def _bloquea_si_mantenimiento():
        if request.path.startswith("/static/") or request.path.startswith("/assets/"):
            return None
        slug = slug_for_app(app.config.get("ERP_APP", ""))
        if not slug:
            return None

        login_path = acceso_login_path(app)
        req_path = (request.path or "").rstrip("/") or "/"
        en_login = req_path.endswith("/login")

        if en_mantenimiento(slug):
            if session.get("email") or session.get("auth_ok"):
                session.clear()
            titulo = app.config.get("ERP_TITLE") or app.config.get("ERP_BRAND") or "ERP"
            return Response(
                _pagina_mantenimiento(str(titulo)),
                status=503,
                mimetype="text/html; charset=utf-8",
            )

        # Tras restaurar: URL limpia de acceso (sin módulo viejo ni ?next=).
        if en_post_mantenimiento(slug):
            if session.get("email"):
                session.clear()
            if not en_login:
                return redirect(login_path)
            return None

        epoch = session_epoch(slug)
        if session.get("email"):
            sess_epoch = session.get("erp_session_epoch")
            if sess_epoch is None:
                session["erp_session_epoch"] = epoch
            elif sess_epoch != epoch:
                session.clear()
                if not en_login:
                    return redirect(login_path)
        return None
