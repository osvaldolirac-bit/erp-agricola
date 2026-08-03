#!/usr/bin/env python3
"""Quita columna TESORERÍA del flujo Streamlit; deja TESO REAL / TESO PROY."""
from pathlib import Path


def patch(path: str) -> None:
    p = Path(path)
    t = p.read_text()
    changed = False

    old1 = (
        '_COLS_FLUJO_ENC_EGRESOS = {\n'
        '    "RRHH SUELDOS", "TESORERÍA", "EGRESOS REAL", "EGRESOS PROY", "EGRESOS TOTAL",\n'
        '}'
    )
    new1 = (
        '_COLS_FLUJO_ENC_EGRESOS = {\n'
        '    "RRHH SUELDOS", "TESO REAL", "TESO PROY", "EGRESOS REAL", "EGRESOS PROY", "EGRESOS TOTAL",\n'
        '}'
    )
    if old1 in t:
        t = t.replace(old1, new1)
        changed = True
    else:
        print(path, "skip enc egresos")

    old2 = (
        '        df_show = df_flujo[\n'
        '            ["MES", "INGRESOS", "RRHH", "TESORERIA", "EGRESOS_REAL", "EGRESOS_PROY", '
        '"EGRESOS_TOTAL", "RESULTADO_MES", "EERR_ACUM"]\n'
        '        ].copy()\n'
        '        n_meses = len(df_show)\n'
        '        df_show = pd.concat(\n'
        '            [df_show, pd.DataFrame([fila_total_flujo_mensual(df_flujo)])],\n'
        '            ignore_index=True,\n'
        '        )\n'
        '        df_show = df_show.rename(\n'
        '            columns={\n'
        '                "RRHH": "RRHH SUELDOS",\n'
        '                "TESORERIA": "TESORERÍA",\n'
        '                "EGRESOS_REAL": "EGRESOS REAL",\n'
        '                "EGRESOS_PROY": "EGRESOS PROY",\n'
        '                "EGRESOS_TOTAL": "EGRESOS TOTAL",\n'
        '                "RESULTADO_MES": "RESULTADO MES",\n'
        '                "EERR_ACUM": "EERR ACUM",\n'
        '            }\n'
        '        )'
    )
    new2 = (
        '        df_show = df_flujo[\n'
        '            ["MES", "INGRESOS", "RRHH", "TESO_REAL", "TESO_PROY", "EGRESOS_REAL", '
        '"EGRESOS_PROY", "EGRESOS_TOTAL", "RESULTADO_MES", "EERR_ACUM"]\n'
        '        ].copy()\n'
        '        n_meses = len(df_show)\n'
        '        df_show = pd.concat(\n'
        '            [df_show, pd.DataFrame([fila_total_flujo_mensual(df_flujo)])],\n'
        '            ignore_index=True,\n'
        '        )\n'
        '        df_show = df_show.rename(\n'
        '            columns={\n'
        '                "RRHH": "RRHH SUELDOS",\n'
        '                "TESO_REAL": "TESO REAL",\n'
        '                "TESO_PROY": "TESO PROY",\n'
        '                "EGRESOS_REAL": "EGRESOS REAL",\n'
        '                "EGRESOS_PROY": "EGRESOS PROY",\n'
        '                "EGRESOS_TOTAL": "EGRESOS TOTAL",\n'
        '                "RESULTADO_MES": "RESULTADO MES",\n'
        '                "EERR_ACUM": "EERR ACUM",\n'
        '            }\n'
        '        )'
    )
    if old2 in t:
        t = t.replace(old2, new2)
        changed = True
    else:
        print(path, "MISSING df_show block")

    old3 = (
        '        fmt = {\n'
        '            "INGRESOS": _fmt_styler_peso,\n'
        '            "RRHH SUELDOS": _fmt_styler_peso,\n'
        '            "TESORERÍA": _fmt_styler_peso,\n'
        '            "EGRESOS REAL": _fmt_styler_peso,\n'
        '            "EGRESOS PROY": _fmt_styler_peso,\n'
        '            "EGRESOS TOTAL": _fmt_styler_peso,\n'
        '            "RESULTADO MES": _fmt_styler_peso,\n'
        '            "EERR ACUM": _fmt_styler_peso,\n'
        '        }\n'
        '        styler = df_show.style.format(fmt)\n'
        '        styler = styler.apply(_style_col_flujo_proy(df_flujo, "RRHH_PROY", "RRHH", n_meses), '
        'subset=["RRHH SUELDOS"])\n'
        '        styler = styler.apply(_style_col_flujo_proy(df_flujo, "TESO_PROY", "TESORERIA", n_meses), '
        'subset=["TESORERÍA"])\n'
        '        styler = styler.apply(_style_proy_flujo_con_total(n_meses), subset=["EGRESOS PROY"])'
    )
    new3 = (
        '        fmt = {\n'
        '            "INGRESOS": _fmt_styler_peso,\n'
        '            "RRHH SUELDOS": _fmt_styler_peso,\n'
        '            "TESO REAL": _fmt_styler_peso,\n'
        '            "TESO PROY": _fmt_styler_peso,\n'
        '            "EGRESOS REAL": _fmt_styler_peso,\n'
        '            "EGRESOS PROY": _fmt_styler_peso,\n'
        '            "EGRESOS TOTAL": _fmt_styler_peso,\n'
        '            "RESULTADO MES": _fmt_styler_peso,\n'
        '            "EERR ACUM": _fmt_styler_peso,\n'
        '        }\n'
        '        styler = df_show.style.format(fmt)\n'
        '        styler = styler.apply(_style_col_flujo_proy(df_flujo, "RRHH_PROY", "RRHH", n_meses), '
        'subset=["RRHH SUELDOS"])\n'
        '        styler = styler.apply(_style_proy_flujo_con_total(n_meses), subset=["TESO PROY"])\n'
        '        styler = styler.apply(_style_proy_flujo_con_total(n_meses), subset=["EGRESOS PROY"])'
    )
    if old3 in t:
        t = t.replace(old3, new3)
        changed = True
    else:
        print(path, "MISSING fmt/styler block")

    old4 = (
        '            "**EGRESOS TOTAL** = Tesorería + RRHH sueldos. "\n'
        '            "Fondo naranjo = monto **proyectado**."'
    )
    new4 = (
        '            "**EGRESOS TOTAL** = TESO REAL + TESO PROY + RRHH. "\n'
        '            "Fondo naranjo = monto **proyectado**."'
    )
    if old4 in t:
        t = t.replace(old4, new4)
        changed = True

    if changed:
        p.write_text(t)
        print(path, "patched")
    else:
        print(path, "no changes")


if __name__ == "__main__":
    for f in ("/root/demo-web/app_concepcion.py", "/root/demo-web/app_demo.py"):
        patch(f)
