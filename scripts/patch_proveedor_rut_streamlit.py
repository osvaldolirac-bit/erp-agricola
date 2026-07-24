#!/usr/bin/env python3
from pathlib import Path

p = Path("/root/demo-web/erp_proveedores.py")
t = p.read_text()
reps = [
    (
        'rut_n = c2.text_input("RUT (opcional)", key="prov_adm_rut")',
        'rut_n = c2.text_input("RUT *", key="prov_adm_rut")',
    ),
    (
        "ok_rut, msg_rut, rut_fmt = validar_rut_campo(rut_n, obligatorio=False)",
        "ok_rut, msg_rut, rut_fmt = validar_rut_campo(rut_n, obligatorio=True)",
    ),
    (
        "ok_rut, msg_rut, rut_fmt = validar_rut_campo(rut_e, obligatorio=False)",
        "ok_rut, msg_rut, rut_fmt = validar_rut_campo(rut_e, obligatorio=True)",
    ),
]
changed = 0
for old, new in reps:
    if old in t:
        t = t.replace(old, new, 1)
        changed += 1
    else:
        print("MISS", old[:60])
p.write_text(t)
print("streamlit_patches", changed)
