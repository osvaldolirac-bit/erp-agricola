from pathlib import Path
p = Path("/root/demo-web/erp_proveedores.py")
t = p.read_text()
reps = [
("rut_n = c2.text_input("RUT (opcional)", key="prov_adm_rut")", "rut_n = c2.text_input("RUT *", key="prov_adm_rut")"),
("ok_rut, msg_rut, rut_fmt = validar_rut_campo(rut_n, obligatorio=False)", "ok_rut, msg_rut, rut_fmt = validar_rut_campo(rut_n, obligatorio=True)"),
("ok_rut, msg_rut, rut_fmt = validar_rut_campo(rut_e, obligatorio=False)", "ok_rut, msg_rut, rut_fmt = validar_rut_campo(rut_e, obligatorio=True)"),
]
c=0
for o,n in reps:
    if o in t:
        t=t.replace(o,n,1); c+=1
    else:
        print("MISS", o[:50])
p.write_text(t)
print("streamlit_patches", c)
