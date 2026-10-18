"""Reparto de montos por centro de costo — respeta tenant (LC vs El Espino)."""
from __future__ import annotations

from typing import Any


def _norm_sel(seleccionados: list[str] | tuple[str, ...]) -> list[str]:
    return [str(c).strip().upper() for c in seleccionados if c and str(c).strip()]


def _espino_tenant() -> bool:
    from demo_web.services.tenant_scope import is_espino_tenant

    if is_espino_tenant():
        return True
    try:
        from demo_web.services.demo_loader import get_demo_module

        demo = get_demo_module()
        if str(getattr(demo, "TENANT_SLUG", "") or "").strip().lower() == "espino":
            return True
    except Exception:
        pass
    return False


def clasificar_cc_seleccionados(seleccionados: list[str] | tuple[str, ...]) -> tuple[list[str], list[str], list[str]]:
    sel = _norm_sel(seleccionados)
    if _espino_tenant():
        from demo_web.services.espino_scope import VARIEDADES_ESPINO

        valid = {v.upper() for v in VARIEDADES_ESPINO}
        directos = [c for c in sel if c in valid]
        invalid = [c for c in sel if c not in valid]
        return directos, [], invalid

    from demo_web.services.demo_loader import get_demo_module
    from demo_web.services.tenant_scope import cuarteles_imputacion_directa, cuarteles_prorrateo

    demo = get_demo_module()
    directos_set = {c.upper() for c in cuarteles_imputacion_directa(demo)}
    prorr_set = {c.upper() for c in cuarteles_prorrateo(demo)}
    directos = [c for c in sel if c in directos_set]
    prorr = [c for c in sel if c in prorr_set and c not in directos_set]
    invalid = [c for c in sel if c not in directos_set and c not in prorr_set]
    return directos, prorr, invalid


def reparto_por_cc(
    conn: Any,
    total: float,
    seleccionados: list[str] | tuple[str, ...],
    *,
    cargar_prorrateo_cc: Any,
) -> tuple[list[tuple[str, float]] | None, str | None]:
    """Misma firma que app_concepcion._reparto_por_cc (requiere cargar_prorrateo_cc del ERP)."""
    try:
        total = float(total)
    except (TypeError, ValueError):
        return None, "Total inválido."
    if total <= 0:
        return None, "El total debe ser mayor a cero."

    directos, prorr, invalid = clasificar_cc_seleccionados(seleccionados)
    if invalid:
        return None, f"Centro de costo no válido: {invalid[0]}"
    if not directos and not prorr:
        return None, "Seleccione al menos un cuartel."

    if _espino_tenant():
        parte = total / len(directos or prorr)
        pool = directos or prorr
        return [(c, parte) for c in pool], None

    if directos and prorr:
        return None, (
            "No mezcle cuarteles del campo (Corte 1, Corte 2, Ciruelos, Nogales) "
            "con El Espino u Otros en el mismo movimiento."
        )
    if directos:
        parte = total / len(directos)
        return [(c, parte) for c in directos], None

    pesos = cargar_prorrateo_cc(conn)
    sub = {c: pesos.get(c, 0.0) for c in prorr}
    suma = sum(sub.values())
    if suma <= 0:
        parte = total / len(prorr)
        return [(c, parte) for c in prorr], None
    return [(c, total * sub[c] / suma) for c in prorr], None
