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


def safe_next(raw: str | None) -> str:
    return parse_next(raw) or url_for("modules.dashboard")


def stash_login_next(raw: str | None) -> None:
    nxt = parse_next(raw)
    if nxt:
        session["login_next"] = nxt


def pop_login_next() -> str | None:
    return session.pop("login_next", None)
