"""Acceso multi-tenant por email (LC, Espino, Demo)."""
from __future__ import annotations

from demo_web.services.erp_loader import get_erp_module_for
from demo_web.tenants import get_tenant, list_tenants

# Tenants entre los que se puede cambiar empresa sin re-login.
_SWITCHABLE_KINDS = frozenset({"lc", "demo"})


def _tenant_access_row(email: str, tenant: dict) -> dict | None:
    slug = str(tenant.get("slug") or "").strip().lower()
    if tenant.get("kind") not in _SWITCHABLE_KINDS:
        return None
    try:
        erp = get_erp_module_for(slug)
        conn = erp.conectar_db()
        try:
            from demo_web.auth.user_db import fetch_bridge_user

            row = fetch_bridge_user(conn, email)
        finally:
            conn.close()
        if not row:
            return None
        if not erp.usuario_prueba_vigente(row[2]):
            return None
        rol = (
            erp.normalizar_rol_usuario(row[1], row[0])
            if hasattr(erp, "normalizar_rol_usuario")
            else row[1]
        )
        return {
            "slug": slug,
            "nombre": tenant.get("nombre") or slug,
            "descripcion": tenant.get("descripcion") or "",
            "rol": rol,
        }
    except Exception:
        return None


def list_accessible_tenants(email: str) -> list[dict]:
    """Tenants agrícola donde el email tiene usuario activo."""
    em = (email or "").strip()
    if not em:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for tenant in list_tenants():
        slug = str(tenant.get("slug") or "").strip().lower()
        if slug in seen:
            continue
        row = _tenant_access_row(em, tenant)
        if row:
            seen.add(slug)
            out.append(row)
    return out


def tenant_access_option(email: str, slug: str) -> dict | None:
    tenant = get_tenant(slug)
    if not tenant:
        return None
    return _tenant_access_row(email, tenant)


def other_tenant_switch_options(accessible: list[dict], current_slug: str | None) -> list[dict]:
    cur = (current_slug or "").strip().lower()
    return [t for t in accessible if str(t.get("slug") or "").strip().lower() != cur]
