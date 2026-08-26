"""Puente firmado Super Consola → ERP (ingreso directo al dashboard)."""
from __future__ import annotations

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

_SALT = "erp-master-bridge-v1"
_MAX_AGE = 120  # segundos


def _serializer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(str(secret), salt=_SALT)


def mint_entry_token(*, secret: str, slug: str, email: str) -> str:
    return _serializer(secret).dumps({"slug": slug, "email": email})


def load_entry_token(secret: str, token: str, max_age: int = _MAX_AGE) -> dict:
    data = _serializer(secret).loads(token, max_age=max_age)
    if not isinstance(data, dict):
        raise BadSignature("payload inválido")
    return data


__all__ = ["mint_entry_token", "load_entry_token", "BadSignature", "SignatureExpired", "_MAX_AGE"]
