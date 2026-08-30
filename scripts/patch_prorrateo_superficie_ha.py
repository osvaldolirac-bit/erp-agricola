#!/usr/bin/env python3
"""Parche consola Master: superficie ha en prorrateo CC + defaults LC."""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LC_SUPERFICIE_HA = {
    "CEREZOS CORTE 1": 1.7,
    "CEREZOS CORTE 2": 1.7,
    "CIRUELOS": 7.0,
    "NOGALES APARICION": 7.0,
    "NOGALES CRUZ DEL SUR": 4.0,
}


def patch_tenant_admin(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if '"default_ha"' not in text:
        text = text.replace(
            '        "directos": ["EL ESPINO", "OTROS"],\n    },\n}',
            '        "directos": ["EL ESPINO", "OTROS"],\n'
            '        "default_ha": {\n'
            '            "CEREZOS CORTE 1": 1.7,\n'
            '            "CEREZOS CORTE 2": 1.7,\n'
            '            "CIRUELOS": 7.0,\n'
            '            "NOGALES APARICION": 7.0,\n'
            '            "NOGALES CRUZ DEL SUR": 4.0,\n'
            "        },\n    },\n}",
        )

    old_get = '''def get_prorrateo_cc(db_path: str, kind: str) -> dict[str, Any]:
    """% de prorrateo por CC (solo porcentajes, ingreso manual)."""
    meta = _prorrateo_meta(kind)
    cuarteles = list(meta["cuarteles"])
    default = dict(meta.get("default_pct") or {})
    with tenant_conn(db_path) as conn:
        _ensure_prorrateo_table(conn)
        rows = conn.execute(
            "SELECT centro_costo, porcentaje FROM prorrateo_cc ORDER BY centro_costo"
        ).fetchall()
        pcts = {str(r[0]): float(r[1]) for r in rows} if rows else dict(default)
        # Si hay filas en DB que no están en la lista fija, incluirlas (orden alfabético al final).
        extras = [cc for cc in pcts if cc not in cuarteles]
        if extras:
            cuarteles = cuarteles + sorted(extras)
    rows_out = []
    for cc in cuarteles:
        rows_out.append(
            {
                "cc": cc,
                "nombre": str(cc).title() if str(cc).isupper() else str(cc),
                "porcentaje": float(pcts.get(cc, default.get(cc, 0)) or 0),
            }
        )
    suma = sum(r["porcentaje"] for r in rows_out)
    return {
        "rows": rows_out,
        "suma": suma,
        "ok": abs(suma - 100.0) < 0.05,
        "directos": list(meta.get("directos") or []),
    }'''

    new_get = '''def get_prorrateo_cc(db_path: str, kind: str) -> dict[str, Any]:
    """Prorrateo % y superficie (ha) por centro de costo."""
    meta = _prorrateo_meta(kind)
    cuarteles = list(meta["cuarteles"])
    default = dict(meta.get("default_pct") or {})
    default_ha = dict(meta.get("default_ha") or {})
    with tenant_conn(db_path) as conn:
        _ensure_prorrateo_table(conn)
        rows = conn.execute(
            """SELECT centro_costo, porcentaje, COALESCE(superficie_ha, 0)
               FROM prorrateo_cc ORDER BY centro_costo"""
        ).fetchall()
        pcts = {str(r[0]): float(r[1]) for r in rows} if rows else dict(default)
        has_ha = {str(r[0]): float(r[2] or 0) for r in rows} if rows else {}
        extras = [cc for cc in pcts if cc not in cuarteles]
        if extras:
            cuarteles = cuarteles + sorted(extras)
    rows_out = []
    for cc in cuarteles:
        ha_val = has_ha.get(cc)
        if ha_val is None or ha_val <= 0:
            ha_val = float(default_ha.get(cc, 0) or 0)
        rows_out.append(
            {
                "cc": cc,
                "nombre": str(cc).title() if str(cc).isupper() else str(cc),
                "porcentaje": float(pcts.get(cc, default.get(cc, 0)) or 0),
                "superficie_ha": float(ha_val or 0),
            }
        )
    suma = sum(r["porcentaje"] for r in rows_out)
    return {
        "rows": rows_out,
        "suma": suma,
        "ok": abs(suma - 100.0) < 0.05,
        "directos": list(meta.get("directos") or []),
    }'''

    if old_get in text:
        text = text.replace(old_get, new_get)

    old_save_sig = "def save_prorrateo_cc(\n    db_path: str, kind: str, porcentajes: dict[str, float]\n) -> tuple[bool, str]:"
    new_save_sig = (
        "def save_prorrateo_cc(\n"
        "    db_path: str,\n"
        "    kind: str,\n"
        "    porcentajes: dict[str, float],\n"
        "    superficies: dict[str, float] | None = None,\n"
        ") -> tuple[bool, str]:"
    )
    if old_save_sig in text:
        text = text.replace(old_save_sig, new_save_sig)

    text = text.replace(
        '    """Guarda % manuales (deben sumar 100). Conserva superficie_ha si existe."""',
        '    """Guarda % (suma 100) y superficie ha por CC."""',
    )

    old_loop = '''        for cc, pct in vals.items():
            if has_ha:
                conn.execute(
                    "INSERT INTO prorrateo_cc (centro_costo, porcentaje, superficie_ha) VALUES (?,?,?) "
                    "ON CONFLICT(centro_costo) DO UPDATE SET porcentaje=excluded.porcentaje",
                    (cc, float(pct), float(ha_map.get(cc, 0))),
                )
            else:
                conn.execute(
                    "INSERT INTO prorrateo_cc (centro_costo, porcentaje) VALUES (?,?) "
                    "ON CONFLICT(centro_costo) DO UPDATE SET porcentaje=excluded.porcentaje",
                    (cc, float(pct)),
                )'''

    new_loop = '''        superficies = superficies or {}
        for cc, pct in vals.items():
            ha = float(superficies.get(cc, ha_map.get(cc, 0)) or 0)
            if has_ha:
                conn.execute(
                    """INSERT INTO prorrateo_cc (centro_costo, porcentaje, superficie_ha)
                       VALUES (?,?,?)
                       ON CONFLICT(centro_costo) DO UPDATE SET
                         porcentaje=excluded.porcentaje,
                         superficie_ha=excluded.superficie_ha""",
                    (cc, float(pct), ha),
                )
            else:
                conn.execute(
                    "INSERT INTO prorrateo_cc (centro_costo, porcentaje) VALUES (?,?) "
                    "ON CONFLICT(centro_costo) DO UPDATE SET porcentaje=excluded.porcentaje",
                    (cc, float(pct)),
                )'''

    if old_loop in text:
        text = text.replace(old_loop, new_loop)

    path.write_text(text, encoding="utf-8")
    print(f"OK tenant_admin: {path}")


def patch_app_py(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    needle = "        return tad.save_prorrateo_cc(db, kind, mapped)"
    if needle in text and "superficies[cc]" not in text:
        insert = '''        superficies: dict[str, float] = {}
        for row in actual.get("rows") or []:
            cc = row["cc"]
            ha_key = "ha_" + cc.replace(" ", "_")
            raw_ha = request.form.get(ha_key)
            if raw_ha is None or str(raw_ha).strip() == "":
                continue
            try:
                superficies[cc] = float(str(raw_ha).replace(",", "."))
            except (TypeError, ValueError):
                return False, f"Superficie inválida en {cc}."
            if superficies[cc] < 0:
                return False, f"Superficie negativa en {cc}."
        return tad.save_prorrateo_cc(db, kind, mapped, superficies)'''
        text = text.replace(needle, insert)
    path.write_text(text, encoding="utf-8")
    print(f"OK app.py: {path}")


def patch_super_consola(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    old_block = '''        <form method="post" class="form-grid">
          <input type="hidden" name="action" value="prorrateo_guardar">
          <input type="hidden" name="sec" value="prorrateo">
          {% for r in prorrateo.rows %}
          <label>{{ r.nombre }} (%)
            <input type="number" name="pct_{{ r.cc|replace(' ', '_') }}" value="{{ '%.4f'|format(r.porcentaje) }}" min="0" max="100" step="0.0001" required>
          </label>
          {% endfor %}'''

    new_block = '''        <form method="post" class="form-grid">
          <input type="hidden" name="action" value="prorrateo_guardar">
          <input type="hidden" name="sec" value="prorrateo">
          <div class="table-wrap" style="grid-column:1/-1;">
            <table class="data">
              <thead>
                <tr>
                  <th>Centro de costo</th>
                  <th>Prorrateo %</th>
                  <th>Superficie (ha)</th>
                </tr>
              </thead>
              <tbody>
                {% for r in prorrateo.rows %}
                <tr>
                  <td><strong>{{ r.nombre }}</strong></td>
                  <td>
                    <input type="number" name="pct_{{ r.cc|replace(' ', '_') }}"
                           value="{{ '%.4f'|format(r.porcentaje) }}" min="0" max="100" step="0.0001" required
                           style="max-width:7rem;">
                  </td>
                  <td>
                    <input type="number" name="ha_{{ r.cc|replace(' ', '_') }}"
                           value="{{ '%.2f'|format(r.superficie_ha|default(0)) }}" min="0" step="0.01"
                           style="max-width:7rem;" placeholder="ha">
                  </td>
                </tr>
                {% endfor %}
              </tbody>
            </table>
          </div>'''

    if old_block in text:
        text = text.replace(old_block, new_block)
        help_old = "          Deben sumar <strong>100 %</strong>."
        help_new = (
            "          Deben sumar <strong>100 %</strong>. "
            "Superficie en <strong>hectáreas reales</strong> (riego y otros cálculos; no usar % como ha)."
        )
        text = text.replace(help_old, help_new, 1)

    path.write_text(text, encoding="utf-8")
    print(f"OK super_consola: {path}")


def patch_registro_riego(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    old = '''    except sqlite3.OperationalError:
        pass
    demo = get_demo_module()
    defaults = getattr(demo, "PRORRATEO_CC_DEFAULT", {}) or {}
    if cc in defaults:
        return float(defaults[cc])
    return 0.0'''
    new = '''    except sqlite3.OperationalError:
        pass
    return 0.0'''
    if old in text:
        text = text.replace(old, new)
        path.write_text(text, encoding="utf-8")
        print(f"OK registro_riego: {path}")


def seed_db(db_path: Path) -> None:
    if not db_path.is_file():
        print(f"skip db (missing): {db_path}")
        return
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS prorrateo_cc (
               centro_costo TEXT PRIMARY KEY,
               porcentaje REAL NOT NULL,
               superficie_ha REAL DEFAULT 0)"""
        )
        for cc, ha in LC_SUPERFICIE_HA.items():
            conn.execute(
                """INSERT INTO prorrateo_cc (centro_costo, porcentaje, superficie_ha)
                   VALUES (?, COALESCE((SELECT porcentaje FROM prorrateo_cc WHERE centro_costo=?), 0), ?)
                   ON CONFLICT(centro_costo) DO UPDATE SET superficie_ha=excluded.superficie_ha""",
                (cc, cc, float(ha)),
            )
        conn.commit()
        rows = conn.execute(
            "SELECT centro_costo, porcentaje, superficie_ha FROM prorrateo_cc ORDER BY centro_costo"
        ).fetchall()
        print(f"OK db {db_path}:")
        for r in rows:
            print(f"  {r[0]}: {r[1]}% · {r[2]} ha")
    finally:
        conn.close()


def main() -> None:
    erp = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/root/erp_master/erp_master")
    demo = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/root/demo-web/demo_web")
    db = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("/root/erp_concepcion_v6.db")

    patch_tenant_admin(erp / "tenant_admin.py")
    patch_app_py(erp / "app.py")
    patch_super_consola(erp / "templates" / "super_consola.html")
    patch_registro_riego(demo / "services" / "registro_riego.py")
    seed_db(db)


if __name__ == "__main__":
    main()
