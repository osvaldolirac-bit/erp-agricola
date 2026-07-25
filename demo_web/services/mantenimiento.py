"""Aviso de sitio en mantención — flag escrito por Super Consola ERP Master."""
from __future__ import annotations

import os

from flask import Flask, Response, request

_STATUS_DIR = os.environ.get("ERP_STATUS_DIR", "/root/erp_status").strip() or "/root/erp_status"

_SLUG_BY_APP = {
    "concepcion": "concepcion",
    "demo": "demo",
}


def slug_for_app(erp_app: str) -> str:
    return _SLUG_BY_APP.get((erp_app or "").strip().lower(), "")


def en_mantenimiento(slug: str) -> bool:
    safe = "".join(c for c in (slug or "").lower() if c.isalnum() or c in "-_")
    if not safe:
        return False
    path = os.path.join(_STATUS_DIR, f"{safe}.mantenimiento")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip() == "1"
    except OSError:
        return False


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
      --ink: #1c1914;
      --muted: #5c564c;
      --sand: #f3efe4;
      --amber: #d97706;
      --stripe: #f59e0b;
      --barrier: #111827;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        repeating-linear-gradient(
          -45deg,
          var(--stripe),
          var(--stripe) 18px,
          var(--barrier) 18px,
          var(--barrier) 36px
        );
      display: grid;
      place-items: center;
      padding: 1.5rem;
    }}
    .card {{
      width: min(560px, 100%);
      background: var(--sand);
      border: 4px solid var(--barrier);
      box-shadow: 0 18px 40px rgba(0,0,0,.28);
      padding: 2rem 1.6rem 1.7rem;
      text-align: center;
    }}
    .cones {{
      display: flex;
      justify-content: center;
      align-items: flex-end;
      gap: 1.4rem;
      margin-bottom: 1.1rem;
      height: 64px;
    }}
    .cone {{
      width: 0;
      height: 0;
      border-left: 22px solid transparent;
      border-right: 22px solid transparent;
      border-bottom: 48px solid var(--amber);
      position: relative;
      filter: drop-shadow(0 2px 0 #111);
    }}
    .cone::after {{
      content: "";
      position: absolute;
      left: -14px;
      top: 18px;
      width: 28px;
      height: 7px;
      background: #111;
    }}
    .barrier-bar {{
      width: 70px;
      height: 14px;
      margin-bottom: 8px;
      background: repeating-linear-gradient(
        90deg,
        var(--stripe) 0 10px,
        var(--barrier) 10px 20px
      );
      border: 2px solid #111;
    }}
    .badge {{
      display: inline-block;
      background: var(--amber);
      color: #111;
      font-family: "Segoe UI", sans-serif;
      font-size: .72rem;
      font-weight: 800;
      letter-spacing: .14em;
      text-transform: uppercase;
      padding: .35rem .7rem;
      margin-bottom: .85rem;
    }}
    h1 {{
      margin: 0 0 .55rem;
      font-size: clamp(1.7rem, 5vw, 2.2rem);
      line-height: 1.1;
    }}
    p {{
      margin: 0;
      font-family: "Segoe UI", sans-serif;
      color: var(--muted);
      font-size: 1.05rem;
      line-height: 1.45;
    }}
    .soon {{
      margin-top: 1rem;
      font-family: "Segoe UI", sans-serif;
      font-weight: 700;
      color: var(--ink);
      font-size: 1.12rem;
    }}
    .foot {{
      margin-top: 1.35rem;
      font-family: "Segoe UI", sans-serif;
      font-size: .82rem;
      color: #7a7468;
    }}
  </style>
</head>
<body>
  <main class="card">
    <div class="cones" aria-hidden="true">
      <span class="cone"></span>
      <span class="barrier-bar"></span>
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
        if request.path.startswith("/static/"):
            return None
        slug = slug_for_app(app.config.get("ERP_APP", ""))
        if not slug or not en_mantenimiento(slug):
            return None
        titulo = app.config.get("ERP_TITLE") or app.config.get("ERP_BRAND") or "ERP"
        html = _pagina_mantenimiento(str(titulo))
        return Response(html, status=503, mimetype="text/html; charset=utf-8")
