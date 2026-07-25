#!/usr/bin/env python3
"""Patch app_demo.py + app_concepcion.py: admin access DEMO + prorrateo/superficies CC."""
from __future__ import annotations

from pathlib import Path

DEMO = Path("/root/demo-web/app_demo.py")
LC = Path("/root/demo-web/app_concepcion.py")


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"FAIL {label}: pattern not found")
    return text.replace(old, new, 1)


def patch_demo(text: str) -> str:
    text = _replace_once(
        text,
        """def puede_administracion():
    return es_super_admin() or es_admin_cliente()
""",
        """def puede_administracion():
    \"\"\"Acceso al módulo Administración (todos los perfiles DEMO pueden verlo).\"\"\"
    return _rol_sesion() in (
        "super_admin",
        "admin_cliente",
        "operador",
        "certificacion",
    )
""",
        "puede_administracion",
    )

    text = _replace_once(
        text,
        """def construir_menu_rol(rol, modulos_txt=None, email=None):
    rol_norm = normalizar_rol_usuario(rol, email)
    if rol_norm in ("super_admin", "admin_cliente"):
        opts = dict(MENU_COMPLETO)
        opts["⚙️ ADMINISTRACIÓN"] = "Administracion"
        return opts
    if rol_norm == "certificacion":
        return dict(MENU_CERTIFICACION)
    asignados = parse_modulos_usuario(modulos_txt)
    if not asignados:
        return dict(MENU_COMPLETO)
    opts = {lbl: key for lbl, key in MENU_COMPLETO if key in asignados}
    if "Manual" not in opts.values():
        opts["📖 MANUAL"] = "Manual"
    if "Soporte" not in opts.values():
        opts["🎫 SOPORTE"] = "Soporte"
    return opts if opts else dict(MENU_COMPLETO)
""",
        """def construir_menu_rol(rol, modulos_txt=None, email=None):
    rol_norm = normalizar_rol_usuario(rol, email)
    if rol_norm in ("super_admin", "admin_cliente"):
        opts = dict(MENU_COMPLETO)
        opts["⚙️ ADMINISTRACIÓN"] = "Administracion"
        return opts
    if rol_norm == "certificacion":
        opts = dict(MENU_CERTIFICACION)
        opts["⚙️ ADMINISTRACIÓN"] = "Administracion"
        return opts
    asignados = parse_modulos_usuario(modulos_txt)
    if not asignados:
        opts = dict(MENU_COMPLETO)
    else:
        opts = {lbl: key for lbl, key in MENU_COMPLETO if key in asignados}
        if "Manual" not in opts.values():
            opts["📖 MANUAL"] = "Manual"
        if "Soporte" not in opts.values():
            opts["🎫 SOPORTE"] = "Soporte"
        if not opts:
            opts = dict(MENU_COMPLETO)
    # Módulo básico de Administración visible para todos (configuración / superficies CC).
    opts["⚙️ ADMINISTRACIÓN"] = "Administracion"
    return opts
""",
        "construir_menu_rol",
    )

    text = _replace_once(
        text,
        """def es_admin():
    return puede_administracion()
""",
        """def es_admin():
    \"\"\"Edición privilegiada (no incluye operador/certificación solo lectura de Admin).\"\"\"
    return es_super_admin() or es_admin_cliente()
""",
        "es_admin",
    )

    insert_after = "PRORRATEO_FUNDO = _normalizar_prorrateo(PESOS_PRORRATEO_FUNDO, CUARTELES_PRORRATEO)\n"
    block = '''PRORRATEO_FUNDO = _normalizar_prorrateo(PESOS_PRORRATEO_FUNDO, CUARTELES_PRORRATEO)
PRORRATEO_CC_DEFAULT = {
    k: round(float(v) * 100.0, 4) for k, v in PRORRATEO_RRHH.items()
}


def _ensure_prorrateo_cc(conn):
    """Tabla editable de superficies / % para imputación de costos fijos (sueldos, etc.)."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS prorrateo_cc (
            centro_costo TEXT PRIMARY KEY,
            porcentaje REAL NOT NULL,
            superficie_ha REAL DEFAULT 0
        )"""
    )
    cols = {r[1] for r in conn.execute("PRAGMA table_info(prorrateo_cc)").fetchall()}
    if "superficie_ha" not in cols:
        conn.execute("ALTER TABLE prorrateo_cc ADD COLUMN superficie_ha REAL DEFAULT 0")
    _sembrar_prorrateo_cc(conn)


def _sembrar_prorrateo_cc(conn):
    for cc, pct in PRORRATEO_CC_DEFAULT.items():
        ha = float(pct)  # semilla didáctica: 1 % ≈ 1 ha (total ~100 ha)
        conn.execute(
            "INSERT OR IGNORE INTO prorrateo_cc (centro_costo, porcentaje, superficie_ha) VALUES (?,?,?)",
            (cc, float(pct), ha),
        )
    conn.commit()


def cargar_prorrateo_cc(conn):
    """Porcentajes 0–1 para imputación (RRHH / costos fijos)."""
    _ensure_prorrateo_cc(conn)
    rows = conn.execute(
        "SELECT centro_costo, porcentaje FROM prorrateo_cc ORDER BY centro_costo"
    ).fetchall()
    if rows:
        return {str(r[0]): float(r[1]) / 100.0 for r in rows}
    return {k: float(v) / 100.0 for k, v in PRORRATEO_CC_DEFAULT.items()}


def cargar_prorrateo_cc_pct(conn):
    _ensure_prorrateo_cc(conn)
    rows = conn.execute(
        "SELECT centro_costo, porcentaje FROM prorrateo_cc ORDER BY centro_costo"
    ).fetchall()
    if rows:
        return {str(r[0]): float(r[1]) for r in rows}
    return dict(PRORRATEO_CC_DEFAULT)


def cargar_superficies_cc(conn):
    _ensure_prorrateo_cc(conn)
    rows = conn.execute(
        "SELECT centro_costo, COALESCE(superficie_ha, 0) FROM prorrateo_cc ORDER BY centro_costo"
    ).fetchall()
    return {str(r[0]): float(r[1] or 0) for r in rows}


def guardar_prorrateo_superficies_cc(conn, datos):
    """datos: {cc: {'porcentaje': float, 'superficie_ha': float}}"""
    _ensure_prorrateo_cc(conn)
    for cc, vals in datos.items():
        conn.execute(
            "INSERT INTO prorrateo_cc (centro_costo, porcentaje, superficie_ha) VALUES (?,?,?) "
            "ON CONFLICT(centro_costo) DO UPDATE SET "
            "porcentaje=excluded.porcentaje, superficie_ha=excluded.superficie_ha",
            (cc, float(vals["porcentaje"]), float(vals.get("superficie_ha") or 0)),
        )
    conn.commit()

'''
    if "def cargar_prorrateo_cc(" in text:
        print("demo: prorrateo helpers already present")
    else:
        text = _replace_once(text, insert_after, block, "insert prorrateo helpers")

    # Usar prorrateo editable en liquidación RRHH
    old_imp = "    for cc_interno, porcentaje in PRORRATEO_FUNDO.items():"
    new_imp = "    for cc_interno, porcentaje in cargar_prorrateo_cc(conn).items():"
    if old_imp in text:
        text = text.replace(old_imp, new_imp, 1)
        print("demo: _imputar_costos_rrhh -> cargar_prorrateo_cc")
    else:
        print("WARN: _imputar_costos_rrhh loop not found")

    # Sembrar tabla al inicializar DB si hay hook claro
    return text


def patch_lc(text: str) -> str:
    # Ensure superficie_ha support in loaders/savers
    if "def cargar_superficies_cc(" in text:
        print("lc: superficies helpers already present")
        return text

    old_sembrar = '''def _sembrar_prorrateo_cc(conn):
    for cc, pct in PRORRATEO_CC_DEFAULT.items():
        conn.execute(
            "INSERT OR IGNORE INTO prorrateo_cc (centro_costo, porcentaje) VALUES (?, ?)",
            (cc, float(pct)),
        )
'''
    new_sembrar = '''def _ensure_prorrateo_cc(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS prorrateo_cc (
            centro_costo TEXT PRIMARY KEY,
            porcentaje REAL NOT NULL,
            superficie_ha REAL DEFAULT 0
        )"""
    )
    cols = {r[1] for r in conn.execute("PRAGMA table_info(prorrateo_cc)").fetchall()}
    if "superficie_ha" not in cols:
        try:
            conn.execute("ALTER TABLE prorrateo_cc ADD COLUMN superficie_ha REAL DEFAULT 0")
        except Exception:
            pass
    _sembrar_prorrateo_cc(conn)


def _sembrar_prorrateo_cc(conn):
    for cc, pct in PRORRATEO_CC_DEFAULT.items():
        ha = float(pct)  # semilla: 1 % ≈ 1 ha hasta que el cliente ajuste superficies reales
        conn.execute(
            "INSERT OR IGNORE INTO prorrateo_cc (centro_costo, porcentaje, superficie_ha) VALUES (?,?,?)",
            (cc, float(pct), ha),
        )
    # Rellenar ha vacías en filas ya existentes
    for cc, pct in PRORRATEO_CC_DEFAULT.items():
        row = conn.execute(
            "SELECT COALESCE(superficie_ha, 0) FROM prorrateo_cc WHERE centro_costo=?",
            (cc,),
        ).fetchone()
        if row and float(row[0] or 0) <= 0:
            conn.execute(
                "UPDATE prorrateo_cc SET superficie_ha=? WHERE centro_costo=?",
                (float(pct), cc),
            )
'''
    text = _replace_once(text, old_sembrar, new_sembrar, "lc sembrar")

    old_cargar = '''def cargar_prorrateo_cc(conn):
    """Porcentajes del fundo (0–1) para los 5 cuarteles prorrateables."""
    rows = conn.execute(
        "SELECT centro_costo, porcentaje FROM prorrateo_cc ORDER BY centro_costo"
    ).fetchall()
    if rows:
        return {str(r[0]): float(r[1]) / 100.0 for r in rows}
    return {k: float(v) / 100.0 for k, v in PRORRATEO_CC_DEFAULT.items()}

def cargar_prorrateo_cc_pct(conn):
    """Porcentajes del fundo (0–100) para pantalla de administración."""
    rows = conn.execute(
        "SELECT centro_costo, porcentaje FROM prorrateo_cc ORDER BY centro_costo"
    ).fetchall()
    if rows:
        return {str(r[0]): float(r[1]) for r in rows}
    return dict(PRORRATEO_CC_DEFAULT)
'''
    new_cargar = '''def cargar_prorrateo_cc(conn):
    """Porcentajes del fundo (0–1) para los cuarteles prorrateables."""
    _ensure_prorrateo_cc(conn)
    rows = conn.execute(
        "SELECT centro_costo, porcentaje FROM prorrateo_cc ORDER BY centro_costo"
    ).fetchall()
    if rows:
        return {str(r[0]): float(r[1]) / 100.0 for r in rows}
    return {k: float(v) / 100.0 for k, v in PRORRATEO_CC_DEFAULT.items()}

def cargar_prorrateo_cc_pct(conn):
    """Porcentajes del fundo (0–100) para pantalla de administración."""
    _ensure_prorrateo_cc(conn)
    rows = conn.execute(
        "SELECT centro_costo, porcentaje FROM prorrateo_cc ORDER BY centro_costo"
    ).fetchall()
    if rows:
        return {str(r[0]): float(r[1]) for r in rows}
    return dict(PRORRATEO_CC_DEFAULT)

def cargar_superficies_cc(conn):
    _ensure_prorrateo_cc(conn)
    rows = conn.execute(
        "SELECT centro_costo, COALESCE(superficie_ha, 0) FROM prorrateo_cc ORDER BY centro_costo"
    ).fetchall()
    out = {str(r[0]): float(r[1] or 0) for r in rows}
    for cc, pct in PRORRATEO_CC_DEFAULT.items():
        out.setdefault(cc, float(pct))
    return out

def guardar_prorrateo_superficies_cc(conn, datos):
    """datos: {cc: {'porcentaje': float, 'superficie_ha': float}}"""
    _ensure_prorrateo_cc(conn)
    for cc, vals in datos.items():
        conn.execute(
            "INSERT INTO prorrateo_cc (centro_costo, porcentaje, superficie_ha) VALUES (?,?,?) "
            "ON CONFLICT(centro_costo) DO UPDATE SET "
            "porcentaje=excluded.porcentaje, superficie_ha=excluded.superficie_ha",
            (cc, float(vals["porcentaje"]), float(vals.get("superficie_ha") or 0)),
        )
    conn.commit()
'''
    text = _replace_once(text, old_cargar, new_cargar, "lc cargar")
    return text


def main() -> None:
    demo = DEMO.read_text(encoding="utf-8")
    DEMO.write_text(patch_demo(demo), encoding="utf-8")
    print("patched", DEMO)

    lc = LC.read_text(encoding="utf-8")
    LC.write_text(patch_lc(lc), encoding="utf-8")
    print("patched", LC)

    # smoke import compile
    import ast

    ast.parse(DEMO.read_text(encoding="utf-8"))
    ast.parse(LC.read_text(encoding="utf-8"))
    print("syntax ok")


if __name__ == "__main__":
    main()
