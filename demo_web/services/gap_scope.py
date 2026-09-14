"""Contexto ámbito consultor GlobalGAP (tenant globalgap)."""
from __future__ import annotations

from flask import session

from demo_web.services.gap_consultor import GapAmbitoCtx, especie_key_for_ambito, load_ambito_ctx
from demo_web.tenants import get_tenant


def is_globalgap_tenant() -> bool:
    t = get_tenant(session.get("tenant_slug"))
    return bool(t and t.get("kind") == "globalgap")


def session_ambito_id() -> int | None:
    if not is_globalgap_tenant():
        return None
    try:
        aid = int(session.get("gap_ambito_id") or 0)
        return aid if aid > 0 else None
    except (TypeError, ValueError):
        return None


def set_session_ambito(ambito_id: int) -> None:
    session["gap_ambito_id"] = int(ambito_id)


def clear_session_ambito() -> None:
    session.pop("gap_ambito_id", None)


def load_scope(conn) -> GapAmbitoCtx | None:
    aid = session_ambito_id()
    if not aid:
        return None
    return load_ambito_ctx(conn, aid)


def ensure_demo_especies(demo, ctx: GapAmbitoCtx) -> None:
    """Inyecta la clave sintética del ámbito en GAP_ESPECIES del módulo ERP."""
    key = ctx.especie_key
    species = list(getattr(demo, "GAP_ESPECIES", []) or [])
    if key not in species:
        species = species + [key]
        demo.GAP_ESPECIES = species
    demo._gap_consultor_ctx = ctx  # noqa: SLF001 — contexto UI
    demo._gap_ambito_label = f"{ctx.etiqueta_nombre} · {ctx.huerto} · {ctx.especie_cultivo}"  # noqa: SLF001


def cuarteles_for_scope(ctx: GapAmbitoCtx) -> list[str]:
    return [ctx.huerto]


def cuarteles_gap_especie_override(demo, especie: str) -> list[str]:
    ctx = getattr(demo, "_gap_consultor_ctx", None)
    if ctx and especie == ctx.especie_key:
        return [ctx.huerto]
    if hasattr(demo, "cuarteles_gap_especie"):
        return demo.cuarteles_gap_especie(especie)
    return []
