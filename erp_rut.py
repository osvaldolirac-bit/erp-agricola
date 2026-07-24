"""Validación y formato de RUT chileno."""
from __future__ import annotations

import re
from itertools import cycle


def _limpiar_rut(rut: str) -> str:
    return re.sub(r"[^0-9kK]", "", (rut or "").strip()).upper()


def _digito_verificador(cuerpo: str) -> str:
    factores = cycle(range(2, 8))
    total = sum(int(d) * f for d, f in zip(reversed(cuerpo), factores))
    resto = 11 - (total % 11)
    if resto == 11:
        return "0"
    if resto == 10:
        return "K"
    return str(resto)


def rut_es_valido(rut: str) -> bool:
    limpio = _limpiar_rut(rut)
    if len(limpio) < 2:
        return False
    cuerpo, dv = limpio[:-1], limpio[-1]
    if not cuerpo.isdigit() or int(cuerpo) == 0:
        return False
    return _digito_verificador(cuerpo) == dv


def formatear_rut(rut: str) -> str:
    limpio = _limpiar_rut(rut)
    if not limpio:
        return ""
    cuerpo, dv = limpio[:-1], limpio[-1]
    partes = []
    while cuerpo:
        partes.insert(0, cuerpo[-3:])
        cuerpo = cuerpo[:-3]
    return f"{'.'.join(partes)}-{dv}"


def validar_rut_campo(rut: str, obligatorio: bool = False) -> tuple[bool, str, str]:
    """Devuelve (ok, mensaje_error, rut_formateado)."""
    txt = (rut or "").strip()
    if not txt:
        if obligatorio:
            return False, "Ingrese un RUT.", ""
        return True, "", ""
    if not rut_es_valido(txt):
        return False, "RUT incorrecto. Verifique el número y el dígito verificador.", ""
    return True, "", formatear_rut(txt)
