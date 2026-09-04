#!/usr/bin/env python3
"""Parche tenant_admin + super_consola: clave auto en invitaciones (compatible VPS)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

TENANT_ADMIN = Path(
    sys.argv[1] if len(sys.argv) > 1 else "/root/erp_master/erp_master/tenant_admin.py"
)
SUPER_CONSOLA = Path(
    sys.argv[2]
    if len(sys.argv) > 2
    else "/root/erp_master/erp_master/templates/super_consola.html"
)


def patch_tenant_admin(text: str) -> str:
    if "def _configure_lc_module_for_db" not in text:
        helper = '''
def generar_clave_invitacion(length: int = 12) -> str:
    try:
        from erp_correo_html import generar_clave_invitacion as _gen
        return _gen(length)
    except Exception:
        import secrets
        chars = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"
        n = max(8, int(length))
        return "".join(secrets.choice(chars) for _ in range(n))


def _configure_lc_module_for_db(lc, db_path: str) -> None:
    """Branding y SMTP según DB (La Concepción vs El Espino)."""
    db = (db_path or "").strip()
    lc.NOMBRE_DB = db
    lc.PROD_URL = DEMO_LOGIN_URL
    low = db.lower()
    if "espino" in low:
        lc.TENANT_SLUG = "espino"
        lc.TENANT_NOMBRE = "El Espino"
        lc.NOMBRE_ERP = "ERP Agrícola El Espino"
        lc.SECRETS_PATH = os.environ.get(
            "ERP_ESPINO_SECRETS", "/root/espino/.streamlit/secrets.toml"
        )
    else:
        lc.TENANT_SLUG = "concepcion"
        lc.TENANT_NOMBRE = "La Concepción"
        lc.NOMBRE_ERP = "ERP Agrícola La Concepción"
        lc.SECRETS_PATH = os.environ.get(
            "ERP_LC_SECRETS",
            os.environ.get("ERP_SECRETS", "/root/.streamlit/secrets.toml"),
        )
    try:
        from demo_web.services.streamlit_mock import set_secrets_path
        if lc.SECRETS_PATH:
            set_secrets_path(lc.SECRETS_PATH)
    except Exception:
        pass

'''
        anchor = "def create_user("
        if anchor not in text:
            raise SystemExit("anchor create_user not found")
        text = text.replace(anchor, helper + anchor, 1)

    text = re.sub(
        r"if not password or len\(password\) < 4:\n        return False, \"La clave debe tener al menos 4 caracteres\.\"",
        'pwd_plain = (password or "").strip()\n    if not pwd_plain:\n        pwd_plain = generar_clave_invitacion()\n    elif len(pwd_plain) < 4:\n        return False, "La clave debe tener al menos 4 caracteres."',
        text,
        count=1,
    )
    text = text.replace("pwd = hash_password(password, kind)", "pwd = hash_password(pwd_plain, kind)", 1)
    text = text.replace(
        "                password,\n                rol,\n                invitado_por or \"\",\n                exp,",
        "                pwd_plain,\n                rol,\n                invitado_por or \"\",\n                exp,",
        1,
    )
    text = text.replace(
        "            db_path, email_n, password, rol, invitado_por or \"\"\n        )",
        "            db_path, email_n, pwd_plain, rol, invitado_por or \"\"\n        )",
        1,
    )
    if "La clave solo fue enviada por correo" not in text:
        text = text.replace(
            '    return True, msg\n\n\ndef send_demo_invitation(',
            '    if enviar_invitacion:\n        msg += " La clave solo fue enviada por correo."\n    elif kind in ("demo", "lc"):\n        msg += " Use «Reenviar mail» para enviar credenciales."\n    return True, msg\n\n\ndef send_demo_invitation(',
            1,
        )

    old_lc = '''        lc.NOMBRE_DB = db_path
        lc.PROD_URL = DEMO_LOGIN_URL
        ok = bool('''
    new_lc = '''        _configure_lc_module_for_db(lc, db_path)
        ok = bool('''
    if old_lc in text:
        text = text.replace(old_lc, new_lc, 1)

    old_re = '''    if not password_plain or len(password_plain) < 4:
        return False, "Indique la clave actual o una nueva (mín. 4) para reenviar."
'''
    new_re = '''    password_plain = (password_plain or "").strip()
    if not password_plain:
        password_plain = generar_clave_invitacion()
    elif len(password_plain) < 4:
        return False, "Clave inválida."
'''
    if old_re in text:
        text = text.replace(old_re, new_re, 1)
    elif "password_plain = generar_clave_invitacion()" not in text:
        raise SystemExit("reenviar_invitacion block not found")

    return text


def patch_super_consola(text: str) -> str:
    text = text.replace(
        "Alta y control de cuentas del cliente seleccionado. Operas desde Master.",
        "Alta y control de cuentas. La clave se genera sola y solo va en el correo de invitación.",
        1,
    )
    text = re.sub(
        r"\s*<label>Clave\s*\n\s*<input type=\"text\" name=\"password\" required minlength=\"4\" autocomplete=\"off\">\s*\n\s*</label>",
        "\n",
        text,
        count=1,
    )
    pwd_line = (
        '                    <input type="text" name="password" '
        'placeholder="Clave p/ invitación" minlength="4" required>\n'
    )
    if pwd_line in text:
        text = text.replace(pwd_line, "", 1)
    old_btn = '<button class="btn btn-ghost" type="submit">Reenviar mail</button>'
    new_btn = (
        '<button class="btn btn-ghost" type="submit" '
        "onclick=\"return confirm('¿Reenviar invitación a {{ u.email }}? "
        "Se generará clave nueva (solo en el correo).');\">Reenviar mail</button>"
    )
    if old_btn in text and "reenviar_invitacion" in text:
        text = text.replace(old_btn, new_btn, 1)
    return text


def main() -> int:
    for path, patcher in ((TENANT_ADMIN, patch_tenant_admin), (SUPER_CONSOLA, patch_super_consola)):
        if not path.is_file():
            print(f"MISSING {path}", file=sys.stderr)
            return 1
        raw = path.read_text(encoding="utf-8")
        out = patcher(raw)
        if out != raw:
            path.write_text(out, encoding="utf-8")
            print(f"patched {path}")
        else:
            print(f"unchanged {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
