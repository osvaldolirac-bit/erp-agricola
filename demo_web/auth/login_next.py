from __future__ import annotations

from flask import current_app, request, session, url_for


def login_next_prefix() -> str:
    return (
        (request.headers.get("X-Forwarded-Prefix") or "").rstrip("/")
        or (request.environ.get("SCRIPT_NAME") or "").rstrip("/")
        or (current_app.config.get("APPLICATION_ROOT") or "").rstrip("/")
    )


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
        or (prefix and not (nxt == prefix or nxt.startswith(prefix + "/")))
    ):
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
    return nxt


def stash_login_next(raw: str | None) -> None:
    nxt = parse_next(raw)
    if nxt:
        session["login_next"] = nxt


def pop_login_next() -> str | None:
    return session.pop("login_next", None)
