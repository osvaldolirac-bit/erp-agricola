from __future__ import annotations

from flask import current_app, request, session, url_for

# Módulos "Sistema": tras login normal siempre dashboard (no reabrir admin/manual/soporte).
_SISTEMA_MODULE_PATHS = ("/m/admin", "/m/manual", "/m/soporte")


def login_next_prefix() -> str:
    return (
        (request.headers.get("X-Forwarded-Prefix") or "").rstrip("/")
        or (request.environ.get("SCRIPT_NAME") or "").rstrip("/")
        or (current_app.config.get("APPLICATION_ROOT") or "").rstrip("/")
    )


def _path_without_prefix(nxt: str) -> str:
    path = (nxt or "").split("?", 1)[0].rstrip("/").lower() or "/"
    prefix = login_next_prefix().lower()
    if prefix and path.startswith(prefix):
        rest = path[len(prefix) :].rstrip("/") or "/"
        return rest
    return path


def post_login_next_blocked(raw: str | None) -> bool:
    """True si el destino es Administración / Manual / Soporte (home = dashboard)."""
    nxt = (raw or "").strip()
    if not nxt or not nxt.startswith("/") or "://" in nxt:
        return False
    path = _path_without_prefix(nxt)
    for seg in _SISTEMA_MODULE_PATHS:
        if path == seg or path.startswith(seg + "/"):
            return True
    return False


def parse_next(raw: str | None) -> str | None:
    nxt = (raw or "").strip()
    prefix = login_next_prefix()
    if (
        not nxt
        or not nxt.startswith("/")
        or nxt.startswith("//")
        or "://" in nxt
        or nxt.startswith("/riomaipo")
        or nxt.startswith("/laconcepcion")
        or nxt.startswith("/demo")
    ):
        return None
    if prefix and not (nxt == prefix or nxt.startswith(prefix + "/")):
        # Tras proxy móvil a veces llega /m/... sin SCRIPT_NAME; rearmar ruta rubro.
        if nxt.startswith("/m/") or nxt.startswith("/api/"):
            nxt = prefix.rstrip("/") + nxt
        else:
            return None
    if post_login_next_blocked(nxt):
        return None
    return nxt


def default_landing_url() -> str:
    """Destino post-login según perfil y tenant."""
    from demo_web.tenants import get_tenant

    slug = session.get("tenant_slug") or ""
    tenant = get_tenant(slug)
    if tenant and tenant.get("kind") == "globalgap":
        from demo_web.blueprints.globalgap_portal import default_landing_for_globalgap

        url = default_landing_for_globalgap()
        if url:
            return url
    rol = (session.get("rol") or "").strip().lower()
    if rol == "certificacion":
        return url_for("modules.globalgap")
    return url_for("modules.dashboard")


def safe_next(raw: str | None) -> str:
    nxt = parse_next(raw)
    if not nxt:
        return default_landing_url()
    if (session.get("rol") or "").strip().lower() == "certificacion" and "/dashboard" in nxt:
        return url_for("modules.globalgap")
    if post_login_next_blocked(nxt):
        return default_landing_url()
    return nxt


def stash_login_next(raw: str | None) -> None:
    nxt = parse_next(raw)
    if nxt:
        session["login_next"] = nxt


def pop_login_next() -> str | None:
    return session.pop("login_next", None)
