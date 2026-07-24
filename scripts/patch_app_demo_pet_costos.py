#!/usr/bin/env python3
"""Alinea DEMO (app_demo.py) con los fixes de Costos/PET de La Concepción.

- Muestra bitacora_codigo (PET-xx) en detalle de Costos por CC
- Ordena movimientos Streamlit por fecha real (no string dd-mm-YYYY)

Uso en el VPS (desde /root/demo-web):
  python3 scripts/patch_app_demo_pet_costos.py
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    candidates = [
        root / "app_demo.py",
        Path("/root/demo-web/app_demo.py"),
    ]
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        print("app_demo.py no encontrado", file=sys.stderr)
        return 1

    bak = path.with_suffix(
        path.suffix + f".bak-bitacora-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    )
    shutil.copy2(path, bak)
    text = path.read_text()

    old1 = (
        "SELECT fecha as Fecha, 'Petróleo' as Rubro,\n"
        "                      TRIM(COALESCE(vehiculo, '') || ' — ' || COALESCE(responsable, '')) as Detalle,\n"
        "                      valor_imputado as Monto\n"
        "               FROM petroleo\n"
        "               WHERE UPPER(TRIM(centro_costo)) = ? AND fecha BETWEEN ? AND ?\n"
        "                 AND tipo = 'Salida' AND ABS(COALESCE(valor_imputado, 0)) > 0.01"
    )
    new1 = (
        "SELECT fecha as Fecha, 'Petróleo' as Rubro,\n"
        "                      TRIM(\n"
        "                        CASE WHEN COALESCE(bitacora_codigo,'') != '' THEN bitacora_codigo || ' · ' ELSE '' END\n"
        "                        || COALESCE(vehiculo, '') || ' — ' || COALESCE(responsable, '')\n"
        "                      ) as Detalle,\n"
        "                      valor_imputado as Monto\n"
        "               FROM petroleo\n"
        "               WHERE UPPER(TRIM(centro_costo)) = ? AND fecha BETWEEN ? AND ?\n"
        "                 AND tipo = 'Salida' AND ABS(COALESCE(valor_imputado, 0)) > 0.01"
    )
    old2 = (
        "SELECT fecha as Fecha, 'Petróleo' as Rubro,\n"
        "                      TRIM(COALESCE(vehiculo, '') || ' — ' || COALESCE(responsable, '')) as Detalle,\n"
        "                      valor_imputado as Monto\n"
        "               FROM petroleo\n"
        "               WHERE UPPER(TRIM(centro_costo)) = ? AND tipo = 'Salida'\n"
        "                 AND ABS(COALESCE(valor_imputado, 0)) > 0.01"
    )
    new2 = (
        "SELECT fecha as Fecha, 'Petróleo' as Rubro,\n"
        "                      TRIM(\n"
        "                        CASE WHEN COALESCE(bitacora_codigo,'') != '' THEN bitacora_codigo || ' · ' ELSE '' END\n"
        "                        || COALESCE(vehiculo, '') || ' — ' || COALESCE(responsable, '')\n"
        "                      ) as Detalle,\n"
        "                      valor_imputado as Monto\n"
        "               FROM petroleo\n"
        "               WHERE UPPER(TRIM(centro_costo)) = ? AND tipo = 'Salida'\n"
        "                 AND ABS(COALESCE(valor_imputado, 0)) > 0.01"
    )

    if "bitacora_codigo || ' · '" in text and 'dayfirst=True' in text:
        print(f"Ya aplicado en {path}")
        return 0

    if text.count(old1) != 1 or text.count(old2) != 1:
        print("SQL petróleo no coincide; abortando", file=sys.stderr)
        return 2
    text = text.replace(old1, new1).replace(old2, new2)

    old_sort = (
        '    if orden == "Fecha ↑":\n'
        '        df_show = df_show.sort_values("Fecha", ascending=True)\n'
        '    elif orden == "Monto ↓":\n'
        '        df_show = df_show.sort_values("Monto", ascending=False)\n'
        '    elif orden == "Monto ↑":\n'
        '        df_show = df_show.sort_values("Monto", ascending=True)\n'
        "    else:\n"
        '        df_show = df_show.sort_values("Fecha", ascending=False)\n'
        "    if df_show.empty:"
    )
    new_sort = (
        '    fecha_sort = pd.to_datetime(df_show["Fecha"], dayfirst=True, errors="coerce")\n'
        '    df_show = df_show.assign(_fecha_sort=fecha_sort)\n'
        '    if orden == "Fecha ↑":\n'
        '        df_show = df_show.sort_values("_fecha_sort", ascending=True)\n'
        '    elif orden == "Monto ↓":\n'
        '        df_show = df_show.sort_values("Monto", ascending=False)\n'
        '    elif orden == "Monto ↑":\n'
        '        df_show = df_show.sort_values("Monto", ascending=True)\n'
        "    else:\n"
        '        df_show = df_show.sort_values("_fecha_sort", ascending=False)\n'
        '    df_show = df_show.drop(columns=["_fecha_sort"], errors="ignore")\n'
        "    if df_show.empty:"
    )
    if text.count(old_sort) == 1:
        text = text.replace(old_sort, new_sort)
    elif 'dayfirst=True' not in text:
        print("Bloque de sort no encontrado; SQL sí aplicado", file=sys.stderr)

    path.write_text(text)
    print(f"OK {path} (backup {bak.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
