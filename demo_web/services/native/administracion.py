from __future__ import annotations

import sqlite3
from datetime import timedelta

import pandas as pd
from flask import flash, render_template, request, url_for

from demo_web.auth import user_db
from demo_web.services.demo_loader import bind_user_session, get_demo_module
from demo_web.services.erp_loader import get_erp_app
from demo_web.services.module_runner import redirect_module, store_pdf
from demo_web.services.native._helpers import df_to_records, hoy_demo, parse_date, temporada_sel

SECCION_DEFS = [
    ("bitacora", "📜 BITÁCORA", "super"),
    ("usuarios", "👤 USUARIOS Y PERFILES", "super"),
    ("modulos", "🔐 MÓDULOS OPERADOR", "all"),
    ("familias", "🏷️ FAMILIAS PRODUCTO", "all"),
    ("maquinaria", "🚜 MAESTRA MAQUINARIA", "all"),
    ("proveedores", "🏢 MAESTRA PROVEEDORES", "all"),
    ("encargados", "💵 ENCARGADOS COMPRAS", "all"),
    ("ppto", "🍒 PPTO Y PRODUCCIÓN", "all"),
    ("flujo", "💰 INGRESOS FLUJO", "all"),
    ("respaldo", "💾 RESPALDO DATOS", "super"),
    ("plataforma", "🔧 PLATAFORMA DEMO", "super"),
]


def _secciones_visibles(demo) -> list[tuple[str, str]]:
    es_super = demo.es_super_admin()
    out = []
    for key, label, scope in SECCION_DEFS:
        if key == "plataforma" and get_erp_app() == "concepcion":
            continue
        if scope == "all" or es_super:
            out.append((key, label))
    return out


def _sec_activa(demo) -> str:
    visibles = _secciones_visibles(demo)
    keys = {k for k, _ in visibles}
    sec = request.args.get("sec", visibles[0][0] if visibles else "modulos")
    return sec if sec in keys else visibles[0][0]


def _pdf_url(demo, df, titulo: str, archivo: str) -> str | None:
    if df is None or df.empty:
        return None
    show = df.copy()
    blob = demo.generar_pdf_blob(show, titulo, incluir_precios=False)
    if not blob:
        return None
    token = store_pdf(blob, archivo)
    return url_for("modules.pdf_download", token=token)


def _gather_bitacora(demo, conn) -> dict:
    hoy = hoy_demo(demo)
    fi = parse_date(request.args.get("desde"), hoy - timedelta(days=30))
    ff = parse_date(request.args.get("hasta"), hoy)
    if fi > ff:
        fi, ff = ff, fi
    df = pd.read_sql_query(
        """SELECT usuario, accion, detalle, fecha_hora FROM bitacora
           WHERE substr(fecha_hora, 1, 10) BETWEEN ? AND ?
           ORDER BY id DESC""",
        conn,
        params=(str(fi), str(ff)),
    )
    cols, rows = df_to_records(df)
    pdf_url = _pdf_url(demo, df, f"ADMINISTRACIÓN ({fi} a {ff})", "administracion_bitacora.pdf")
    return {
        "desde": fi.isoformat(),
        "hasta": ff.isoformat(),
        "bitacora_cols": cols,
        "bitacora_rows": rows,
        "bitacora_total": len(rows),
        "pdf_bitacora_url": pdf_url,
    }


def _gather_usuarios(demo, conn) -> dict:
    demo._ensure_mail_tesoreria_usuarios(conn)
    cols = user_db.usuario_cols(conn)
    mail_pet_col = get_erp_app() == "concepcion" and hasattr(
        demo, "_ensure_mail_petroleo_bitacora_usuarios"
    )
    if mail_pet_col:
        demo._ensure_mail_petroleo_bitacora_usuarios(conn)
        cols = user_db.usuario_cols(conn)
    sel = ["email", "rol", "COALESCE(mail_tesoreria, 0)"]
    if mail_pet_col and "mail_petroleo_bitacora" in cols:
        sel.append("COALESCE(mail_petroleo_bitacora, 0)")
    if "fecha_expira" in cols:
        sel.append("fecha_expira")
    else:
        sel.append("NULL AS fecha_expira")
    if "invitado_por" in cols:
        sel.append("invitado_por")
    else:
        sel.append("NULL AS invitado_por")
    rows = conn.execute(f"SELECT {', '.join(sel)} FROM usuarios ORDER BY email").fetchall()
    usuarios = []
    emails_gestion = []
    tiene_mail_pet = mail_pet_col and "mail_petroleo_bitacora" in cols
    for row in rows:
        email, rol, mail_teso = row[0], row[1], row[2]
        idx = 3
        mail_pet = bool(row[idx]) if tiene_mail_pet else False
        if tiene_mail_pet:
            idx += 1
        fexp = row[idx]
        inv_por = row[idx + 1]
        rol_norm = demo.normalizar_rol_usuario(rol, email)
        gestionable = demo.usuario_gestionable_demo(conn, email)
        usuarios.append(
            {
                "email": email,
                "perfil": demo.etiqueta_perfil_demo(rol_norm),
                "rol": rol_norm,
                "vigencia": "Permanente" if not fexp else str(fexp)[:10],
                "mail_teso": bool(mail_teso),
                "mail_petroleo": mail_pet,
                "invitado_por": inv_por or "",
                "gestionable": gestionable,
            }
        )
        if gestionable:
            emails_gestion.append(email)

    perfiles = [
        {"key": p, "label": demo.etiqueta_perfil_demo(p)}
        for p in demo.perfiles_asignables_demo()
    ]
    return {
        "usuarios": usuarios,
        "emails_gestion": emails_gestion,
        "perfiles": perfiles,
        "dias_prueba": demo.DEMO_DIAS_PRUEBA,
        "mostrar_mail_petroleo": tiene_mail_pet,
    }


def _gather_modulos(demo, conn, user_email: str) -> dict:
    es_super = demo.es_super_admin()
    if user_db.has_invitado_por(conn):
        ops = pd.read_sql_query(
            """SELECT email, COALESCE(modulos, '') AS modulos
               FROM usuarios WHERE rol='operador'
               AND (? = 1 OR lower(COALESCE(invitado_por, '')) = lower(?))
               ORDER BY email""",
            conn,
            params=(1 if es_super else 0, user_email),
        )
    else:
        ops = pd.read_sql_query(
            """SELECT email, COALESCE(modulos, '') AS modulos
               FROM usuarios WHERE rol='operador'
               ORDER BY email""",
            conn,
        )
    operadores = ops["email"].tolist() if not ops.empty else []
    sel = request.args.get("operador") or (operadores[0] if operadores else "")
    mod_act = None
    if sel and sel in operadores:
        raw = ops.loc[ops["email"] == sel, "modulos"].iloc[0]
        mod_act = demo.parse_modulos_usuario(raw)

    todos_keys = [key for _, key in demo.MENU_COMPLETO]
    activos = set(todos_keys if mod_act is None else mod_act)
    modulos_menu = [
        {"label": lbl, "key": key, "checked": key in activos}
        for lbl, key in demo.MENU_COMPLETO
    ]
    return {
        "operadores": operadores,
        "operador_sel": sel,
        "modulos_menu": modulos_menu,
        "sin_operadores": not operadores,
        "es_super": es_super,
    }


def _gather_familias(demo, conn) -> dict:
    familias = demo.listar_familias_producto(conn)
    rows = [
        {"familia": f, "productos": demo.contar_productos_familia(conn, f)}
        for f in familias
    ]
    sel = request.args.get("familia") or (familias[0] if familias else "")
    if sel and sel not in familias:
        sel = familias[0] if familias else ""
    return {"familias_rows": rows, "familias_list": familias, "familia_sel": sel}


def _gather_maquinaria(conn) -> dict:
    from erp_maquinaria import (
        TIPOS_MAQUINARIA,
        contar_eventos_maquinaria,
        generar_codigo_maquinaria,
        listar_maquinaria,
        migrar_maestra_maquinaria,
    )

    migrar_maestra_maquinaria(conn)
    maqs = listar_maquinaria(conn)
    rows = []
    for m in maqs:
        rows.append(
            {
                "codigo": m["codigo"],
                "nombre": m["nombre"],
                "tipo": m["tipo"],
                "activo": m["activo"],
                "activo_txt": "Sí" if m["activo"] else "No",
                "eventos": contar_eventos_maquinaria(conn, m["codigo"]),
                "notas": m["notas"] or "",
            }
        )
    tipo_sel = request.args.get("tipo") or TIPOS_MAQUINARIA[0]
    if tipo_sel not in TIPOS_MAQUINARIA:
        tipo_sel = TIPOS_MAQUINARIA[0]
    cod_preview = generar_codigo_maquinaria(conn, tipo_sel)
    codigos = [m["codigo"] for m in maqs]
    edit_sel = request.args.get("codigo") or (codigos[0] if codigos else "")
    edit_item = next((m for m in rows if m["codigo"] == edit_sel), None)
    return {
        "maquinaria_rows": rows,
        "tipos_maquinaria": TIPOS_MAQUINARIA,
        "tipo_sel": tipo_sel,
        "cod_preview": cod_preview,
        "maq_edit_sel": edit_sel,
        "maq_edit": edit_item,
    }


def _gather_proveedores(conn) -> dict:
    from erp_proveedores import (
        TIPOS_PROVEEDOR,
        contar_referencias_proveedor,
        generar_codigo_proveedor,
        listar_proveedores,
        migrar_maestra_proveedores,
    )

    migrar_maestra_proveedores(conn)
    provs = listar_proveedores(conn)
    rows = []
    for p in provs:
        rows.append(
            {
                "codigo": p["codigo"],
                "nombre": p["nombre"],
                "rut": p["rut"] or "",
                "contacto": p["contacto"] or "",
                "mail": p["email"] or "",
                "telefono": p["telefono"] or "",
                "celular": p.get("celular") or "",
                "direccion": p.get("direccion") or "",
                "tipo": p["tipo"] or "",
                "activo": p["activo"],
                "activo_txt": "Sí" if p["activo"] else "No",
                "mail_pago": bool(p["mail_pago"]),
                "whatsapp_pago": bool(p.get("whatsapp_pago")),
                "notas": p.get("notas") or "",
                "refs": contar_referencias_proveedor(conn, p["nombre"]),
            }
        )
    codigos = [p["codigo"] for p in provs]
    edit_sel = request.args.get("codigo") or (codigos[0] if codigos else "")
    edit_item = next((r for r in rows if r["codigo"] == edit_sel), None)
    return {
        "proveedores_rows": rows,
        "tipos_proveedor": TIPOS_PROVEEDOR,
        "cod_preview_prov": generar_codigo_proveedor(conn),
        "prov_edit_sel": edit_sel,
        "prov_edit": edit_item,
    }


def _gather_encargados(conn) -> dict:
    from erp_caja_chica import listar_encargados, migrar_caja_chica

    migrar_caja_chica(conn)
    df = listar_encargados(conn, solo_activos=False)
    rows = []
    if not df.empty:
        for _, r in df.iterrows():
            rows.append(
                {
                    "id": int(r["id"]),
                    "nombre": r["nombre"],
                    "rut": r["rut"] or "",
                    "email": r["email"] or "",
                    "telefono": r["telefono"] or "",
                    "activo": bool(r["activo"]),
                    "estado": "Activo" if r["activo"] else "Inactivo",
                    "notas": r["notas"] or "",
                }
            )
    edit_id_raw = request.args.get("enc_id")
    edit_id = int(edit_id_raw) if edit_id_raw and edit_id_raw.isdigit() else (rows[0]["id"] if rows else 0)
    edit_item = next((r for r in rows if r["id"] == edit_id), None)
    return {"encargados_rows": rows, "enc_edit_id": edit_id, "enc_edit": edit_item}


def _gather_ppto(demo, conn) -> dict:
    temp_nombre, fi, ff = temporada_sel(demo, "temp")
    cuarteles = []
    for cc in demo.CUARTELES_OFICIALES:
        ppto = demo._obtener_ppto_temporada(conn, temp_nombre, cc)
        kg = demo._obtener_kg_estimado_temporada(conn, temp_nombre, cc)
        cuarteles.append(
            {
                "nombre": cc.title(),
                "cc": cc,
                "ppto": float(ppto),
                "ppto_fmt": demo.f_peso(float(ppto)),
                "kg": float(kg),
            }
        )
    return {
        "temporadas": demo.TEMPORADAS_COSTOS,
        "temp_sel": temp_nombre,
        "temp_fi": fi.strftime("%d-%m-%Y"),
        "temp_ff": ff.strftime("%d-%m-%Y"),
        "ppto_cuarteles": cuarteles,
    }


def _gather_flujo(demo, conn) -> dict:
    from erp_flujo_financiero import (
        cargar_ingresos_cc,
        cargar_notas_ingresos_cc,
        cargar_saldo_caja_inicial,
        iter_meses_rango,
        _mes_label,
    )

    temp_nombre, fi, ff = temporada_sel(demo, "temp")
    meses = list(iter_meses_rango(fi, ff))
    ing = cargar_ingresos_cc(conn, temp_nombre)
    notas = cargar_notas_ingresos_cc(conn, temp_nombre)
    caja_ini = cargar_saldo_caja_inicial(conn, temp_nombre)
    es_vigente = fi <= demo.hoy <= ff

    filas = []
    flujo_cuarteles = []
    for cc in demo.CUARTELES_OFICIALES:
        row = {"cuartel": cc.title()}
        total_cc = 0.0
        meses_edit = []
        for anio, mes in meses:
            monto = ing.get((cc, anio, mes), 0.0)
            lbl = _mes_label(anio, mes)
            row[lbl] = demo.f_peso(monto)
            total_cc += monto
            meses_edit.append(
                {
                    "anio": anio,
                    "mes": mes,
                    "label": lbl,
                    "monto": float(monto),
                    "nota": notas.get((cc, anio, mes), ""),
                }
            )
        row["total"] = demo.f_peso(total_cc)
        filas.append(row)
        flujo_cuarteles.append({"cc": cc, "nombre": cc.title(), "meses": meses_edit})

    totales_mes = {}
    for anio, mes in meses:
        lbl = _mes_label(anio, mes)
        totales_mes[lbl] = demo.f_peso(
            sum(ing.get((cc, anio, mes), 0.0) for cc in demo.CUARTELES_OFICIALES)
        )

    meses_txt = ", ".join(_mes_label(a, m) for a, m in meses)
    return {
        "temporadas": demo.TEMPORADAS_COSTOS,
        "temp_sel": temp_nombre,
        "temp_fi": fi.strftime("%d-%m-%Y"),
        "temp_ff": ff.strftime("%d-%m-%Y"),
        "flujo_meses": [_mes_label(a, m) for a, m in meses],
        "flujo_rows": filas,
        "flujo_totales_mes": totales_mes,
        "flujo_cuarteles": flujo_cuarteles,
        "caja_inicial": float(caja_ini),
        "caja_inicial_fmt": demo.f_peso(caja_ini),
        "flujo_meses_txt": meses_txt,
        "flujo_vigente": es_vigente,
    }


def _gather_respaldo(demo, conn) -> dict:
    from erp_respaldo import (
        FRECUENCIAS_ETIQUETA,
        FRECUENCIAS_RESPALDO,
        formatear_ultimo_respaldo,
        formatear_ultimo_respaldo_codigo,
        migrar_config_respaldo,
        obtener_config_respaldo,
        spec_respaldo_codigo_por_nombre,
    )

    migrar_config_respaldo(conn)
    config = obtener_config_respaldo(conn)
    spec_codigo = spec_respaldo_codigo_por_nombre(demo.NOMBRE_ERP)
    frecuencias = [
        {"key": f, "label": FRECUENCIAS_ETIQUETA.get(f, f)} for f in FRECUENCIAS_RESPALDO
    ]
    return {
        "nombre_db": demo.NOMBRE_DB,
        "respaldo_email": config.get("email", ""),
        "respaldo_activo": config.get("activo", False),
        "respaldo_freq_datos": config.get("frecuencia", "diario"),
        "respaldo_freq_codigo": config.get("frecuencia_codigo", "semanal"),
        "respaldo_estado_datos": formatear_ultimo_respaldo(config),
        "respaldo_estado_codigo": formatear_ultimo_respaldo_codigo(config),
        "respaldo_error_datos": config.get("ultimo_error") or "",
        "respaldo_error_codigo": config.get("ultimo_error_codigo") or "",
        "respaldo_frecuencias": frecuencias,
        "respaldo_tiene_codigo": bool(spec_codigo),
    }


def _gather_plataforma(demo, conn) -> dict:
    from demo_seed import DEMO_SEED_VERSION

    n_super, n_cliente = demo.contar_roles_admin_demo(conn)
    seed_ok = conn.execute(
        "SELECT valor FROM schema_meta WHERE clave=?", (DEMO_SEED_VERSION,),
    ).fetchone()
    cols = user_db.usuario_cols(conn)
    sel = ["email", "COALESCE(rol, 'operador') AS rol"]
    if "fecha_expira" in cols:
        sel.append("fecha_expira")
    else:
        sel.append("NULL AS fecha_expira")
    if "invitado_por" in cols:
        sel.append("invitado_por")
    else:
        sel.append("NULL AS invitado_por")
    df_u = pd.read_sql_query(f"SELECT {', '.join(sel)} FROM usuarios ORDER BY email", conn)
    usuarios_plat = []
    for _, r in df_u.iterrows():
        rol = demo.normalizar_rol_usuario(r["rol"], r["email"])
        usuarios_plat.append(
            {
                "email": r["email"],
                "perfil": demo.etiqueta_perfil_demo(rol),
                "vigencia": "Permanente" if not r["fecha_expira"] else str(r["fecha_expira"])[:10],
                "invitado_por": r["invitado_por"] or "",
            }
        )
    return {
        "n_super": n_super,
        "n_cliente": n_cliente,
        "dias_prueba": demo.DEMO_DIAS_PRUEBA,
        "seed_version": DEMO_SEED_VERSION,
        "seed_ok": bool(seed_ok),
        "nombre_db": demo.NOMBRE_DB,
        "usuarios_plat": usuarios_plat,
    }


def gather_admin(user_email: str, user_rol: str) -> dict:
    demo = get_demo_module()
    bind_user_session(user_email, user_rol)

    if not demo.puede_administracion():
        return {"acceso_denegado": True}

    sec = _sec_activa(demo)
    secciones = _secciones_visibles(demo)
    ctx: dict = {
        "acceso_denegado": False,
        "secciones": secciones,
        "sec_activa": sec,
        "es_super": demo.es_super_admin(),
        "title": "⚙️ Administración",
    }

    conn = demo.conectar_db()
    try:
        if sec == "bitacora":
            ctx.update(_gather_bitacora(demo, conn))
        elif sec == "usuarios":
            ctx.update(_gather_usuarios(demo, conn))
        elif sec == "modulos":
            ctx.update(_gather_modulos(demo, conn, user_email))
        elif sec == "familias":
            ctx.update(_gather_familias(demo, conn))
        elif sec == "maquinaria":
            ctx.update(_gather_maquinaria(conn))
        elif sec == "proveedores":
            ctx.update(_gather_proveedores(conn))
        elif sec == "encargados":
            ctx.update(_gather_encargados(conn))
        elif sec == "ppto":
            ctx.update(_gather_ppto(demo, conn))
        elif sec == "flujo":
            ctx.update(_gather_flujo(demo, conn))
        elif sec == "respaldo":
            ctx.update(_gather_respaldo(demo, conn))
        elif sec == "plataforma":
            ctx.update(_gather_plataforma(demo, conn))
    finally:
        conn.close()

    return ctx


def _post_crear_usuario(demo, conn, user_email: str) -> dict:
    nu = (request.form.get("email") or "").strip().lower()
    np = (request.form.get("password") or "").strip()
    nr = request.form.get("rol") or "operador"
    mail_teso = request.form.get("mail_teso") == "1"
    mail_pet = request.form.get("mail_petroleo") == "1"

    if not nu or not np:
        return {"ok": False, "msg": "Ingrese email y contraseña."}
    if nr == "super_admin" and not demo.es_super_admin():
        return {"ok": False, "msg": "Solo el super administrador puede crear ese perfil."}
    if nr not in demo.perfiles_asignables_demo():
        return {"ok": False, "msg": "Perfil no válido."}
    if len(np) < 4:
        return {"ok": False, "msg": "La contraseña debe tener al menos 4 caracteres."}

    try:
        cols = user_db.usuario_cols(conn)
        if get_erp_app() == "concepcion" and hasattr(demo, "_ensure_mail_petroleo_bitacora_usuarios"):
            demo._ensure_mail_petroleo_bitacora_usuarios(conn)
            cols = user_db.usuario_cols(conn)
        pwd = demo.hash_password(np)
        if get_erp_app() == "concepcion" or "fecha_expira" not in cols:
            ins_cols = ["email", "password", "rol", "mail_tesoreria"]
            ins_vals = [nu, pwd, nr, 1 if mail_teso else 0]
            if "mail_petroleo_bitacora" in cols:
                ins_cols.append("mail_petroleo_bitacora")
                ins_vals.append(1 if mail_pet else 0)
            if "solo_lectura" in cols:
                ins_cols.append("solo_lectura")
                ins_vals.append(0)
            placeholders = ", ".join("?" * len(ins_vals))
            conn.execute(
                f"INSERT INTO usuarios ({', '.join(ins_cols)}) VALUES ({placeholders})",
                ins_vals,
            )
            conn.commit()
            demo.registrar_accion("USUARIO NUEVO", f"{nu} ({nr})")
            return {"ok": True, "msg": f"Usuario {nu} creado."}
        fecha_fin = demo.fecha_fin_prueba_demo()
        conn.execute(
            """INSERT INTO usuarios (email, password, rol, fecha_expira, invitado_por,
               alerta_24h_enviada, alerta_vencido_enviada, mail_tesoreria)
               VALUES (?,?,?,?,?,0,0,?)""",
            (nu, pwd, nr, str(fecha_fin), user_email, 1 if mail_teso else 0),
        )
        conn.commit()
        demo.registrar_accion("USUARIO NUEVO", f"{nu} ({nr}) hasta {fecha_fin}")
        mail_res = demo.enviar_correo_invitacion_demo(nu, np, nr, user_email, fecha_fin)
        ok_inv = mail_res.get("invitado") if isinstance(mail_res, dict) else bool(mail_res)
        msg = f"Usuario {nu} creado. Vigencia hasta {fecha_fin.strftime('%d-%m-%Y')}."
        if ok_inv:
            msg += f" Correo de invitación enviado a {nu}."
        else:
            msg += " No se pudo enviar el correo de invitación (revise SMTP)."
        return {"ok": True, "msg": msg}
    except sqlite3.IntegrityError:
        return {"ok": False, "msg": "Ese email ya existe."}


def _post_cambiar_rol(demo, conn) -> dict:
    ue = (request.form.get("email") or "").strip()
    nuevo_rol = request.form.get("rol") or ""
    if not ue:
        return {"ok": False, "msg": "Seleccione un usuario."}
    if nuevo_rol == "super_admin" and not demo.es_super_admin():
        return {"ok": False, "msg": "Solo el super administrador puede asignar ese perfil."}
    if not demo.usuario_gestionable_demo(conn, ue):
        return {"ok": False, "msg": "No tiene permiso para modificar este usuario."}
    conn.execute("UPDATE usuarios SET rol=? WHERE email=?", (nuevo_rol, ue))
    conn.commit()
    demo.registrar_accion("USUARIO ROL", f"{ue} → {nuevo_rol}")
    return {"ok": True, "msg": "Perfil actualizado."}


def _post_cambiar_clave(demo, conn) -> dict:
    ue = (request.form.get("email") or "").strip()
    p1 = (request.form.get("password") or "").strip()
    p2 = (request.form.get("password2") or "").strip()
    if not ue:
        return {"ok": False, "msg": "Seleccione un usuario."}
    if not p1:
        return {"ok": False, "msg": "Ingrese la nueva contraseña."}
    if p1 != p2:
        return {"ok": False, "msg": "Las contraseñas no coinciden."}
    if len(p1) < 4:
        return {"ok": False, "msg": "La contraseña debe tener al menos 4 caracteres."}
    if not demo.usuario_gestionable_demo(conn, ue):
        return {"ok": False, "msg": "No tiene permiso para modificar este usuario."}
    conn.execute("UPDATE usuarios SET password=? WHERE email=?", (demo.hash_password(p1), ue))
    conn.commit()
    demo.registrar_accion("USUARIO CLAVE", ue)
    return {"ok": True, "msg": f"Contraseña actualizada para {ue}."}


def _post_eliminar_usuario(demo, conn, user_email: str) -> dict:
    ue = (request.form.get("email") or "").strip()
    if not ue:
        return {"ok": False, "msg": "Seleccione un usuario."}
    if ue == user_email:
        return {"ok": False, "msg": "No puede eliminar su propio usuario mientras está conectado."}
    if request.form.get("confirm") != "1":
        return {"ok": False, "msg": "Debe confirmar la eliminación."}
    if not demo.usuario_gestionable_demo(conn, ue):
        return {"ok": False, "msg": "No tiene permiso para eliminar este usuario."}
    rol_row = conn.execute("SELECT rol FROM usuarios WHERE email=?", (ue,)).fetchone()
    rol_del = demo.normalizar_rol_usuario(rol_row[0], ue) if rol_row else ""
    n_super, n_cliente = demo.contar_roles_admin_demo(conn)
    if rol_del == "super_admin" and n_super <= 1:
        return {"ok": False, "msg": "No puede eliminar el único super administrador."}
    if rol_del == "admin_cliente" and n_cliente <= 1:
        return {"ok": False, "msg": "No puede eliminar el único administrador de campo."}
    conn.execute("DELETE FROM usuarios WHERE email=?", (ue,))
    conn.commit()
    demo.registrar_accion("USUARIO ELIMINADO", ue)
    return {"ok": True, "msg": f"Usuario {ue} eliminado."}


def _post_mail_teso(demo, conn) -> dict:
    if get_erp_app() == "concepcion" and hasattr(demo, "_ensure_mail_petroleo_bitacora_usuarios"):
        demo._ensure_mail_petroleo_bitacora_usuarios(conn)
    cols = user_db.usuario_cols(conn)
    tiene_mail_pet = "mail_petroleo_bitacora" in cols
    for key, val in request.form.items():
        if key.startswith("mail_teso_"):
            email = key.replace("mail_teso_", "", 1)
            flag = 1 if val == "1" else 0
            conn.execute("UPDATE usuarios SET mail_tesoreria=? WHERE email=?", (flag, email))
        elif tiene_mail_pet and key.startswith("mail_pet_"):
            email = key.replace("mail_pet_", "", 1)
            flag = 1 if val == "1" else 0
            conn.execute(
                "UPDATE usuarios SET mail_petroleo_bitacora=? WHERE email=?", (flag, email)
            )
    conn.commit()
    demo.registrar_accion("MAIL USUARIOS", "Preferencias correo actualizadas")
    msg = "Preferencias de correo actualizadas."
    if tiene_mail_pet:
        msg = "Mail Tesorería y salida petróleo (QR) actualizados."
    return {"ok": True, "msg": msg}


def _post_guardar_modulos(demo, conn) -> dict:
    ue = (request.form.get("operador") or "").strip()
    if not ue:
        return {"ok": False, "msg": "Seleccione un operador."}
    todos_keys = [key for _, key in demo.MENU_COMPLETO]
    seleccionados = [k for k in todos_keys if request.form.get(f"mod_{k}") == "1"]
    mod_txt = "" if set(seleccionados) >= set(todos_keys) else ",".join(seleccionados)
    conn.execute("UPDATE usuarios SET modulos=? WHERE email=?", (mod_txt, ue))
    conn.commit()
    demo.registrar_accion("USUARIO MODULOS", f"{ue}: {mod_txt or 'todos'}")
    return {"ok": True, "msg": "Módulos actualizados."}


def _post_crear_familia(demo, conn) -> dict:
    nom = (request.form.get("nombre") or "").strip().upper()
    if not nom:
        return {"ok": False, "msg": "Ingrese un nombre para la familia."}
    if conn.execute(
        "SELECT 1 FROM familias_producto WHERE UPPER(TRIM(nombre))=?", (nom,),
    ).fetchone():
        return {"ok": False, "msg": f"La familia «{nom}» ya existe."}
    orden = conn.execute("SELECT COALESCE(MAX(orden), -1) + 1 FROM familias_producto").fetchone()[0]
    conn.execute("INSERT INTO familias_producto (nombre, orden) VALUES (?, ?)", (nom, orden))
    conn.commit()
    demo.registrar_accion("FAMILIA PRODUCTO", f"Nueva: {nom}")
    return {"ok": True, "msg": f"Familia «{nom}» creada."}


def _post_guardar_metas(demo, conn) -> dict:
    temp = request.form.get("temporada") or ""
    if not temp:
        return {"ok": False, "msg": "Temporada no válida."}
    for cc in demo.CUARTELES_OFICIALES:
        ppto_raw = request.form.get(f"ppto_{cc}") or "0"
        kg_raw = request.form.get(f"kg_{cc}") or "0"
        try:
            ppto = float(ppto_raw)
            kg = float(kg_raw)
        except ValueError:
            return {"ok": False, "msg": f"Valores inválidos para {cc}."}
        demo._guardar_ppto_temporada(conn, temp, cc, ppto)
        demo._guardar_kg_estimado_temporada(conn, temp, cc, kg)
    demo.registrar_accion("METAS COSTOS", f"{temp}: {len(demo.CUARTELES_OFICIALES)} cuarteles")
    return {"ok": True, "msg": f"Metas guardadas para temporada {temp}."}


def _post_renombrar_familia(demo, conn) -> dict:
    sel = (request.form.get("familia") or "").strip()
    nuevo = (request.form.get("nuevo_nombre") or "").strip().upper()
    if not sel or not nuevo:
        return {"ok": False, "msg": "Seleccione familia e ingrese el nuevo nombre."}
    if nuevo == sel.strip().upper():
        return {"ok": False, "msg": "El nombre no cambió."}
    if conn.execute(
        "SELECT 1 FROM familias_producto WHERE UPPER(TRIM(nombre))=? AND UPPER(TRIM(nombre))!=?",
        (nuevo, sel.strip().upper()),
    ).fetchone():
        return {"ok": False, "msg": f"Ya existe otra familia llamada «{nuevo}»."}
    n_prod = demo.contar_productos_familia(conn, sel)
    conn.execute(
        "UPDATE familias_producto SET nombre=? WHERE UPPER(TRIM(nombre))=?",
        (nuevo, sel.strip().upper()),
    )
    conn.execute(
        "UPDATE inventario SET familia=? WHERE UPPER(TRIM(familia))=?",
        (nuevo, sel.strip().upper()),
    )
    conn.commit()
    demo.registrar_accion("FAMILIA PRODUCTO", f"Renombrada: {sel} → {nuevo} ({n_prod} producto(s))")
    return {"ok": True, "msg": f"Familia renombrada a «{nuevo}» ({n_prod} producto(s) actualizados)."}


def _post_eliminar_familia(demo, conn) -> dict:
    sel = (request.form.get("familia") or "").strip()
    if not sel:
        return {"ok": False, "msg": "Seleccione una familia."}
    if request.form.get("confirm") != "1":
        return {"ok": False, "msg": "Debe confirmar la eliminación."}
    n_prod = demo.contar_productos_familia(conn, sel)
    if n_prod > 0:
        return {
            "ok": False,
            "msg": f"No se puede eliminar: {n_prod} producto(s) usan la familia «{sel}».",
        }
    conn.execute(
        "DELETE FROM familias_producto WHERE UPPER(TRIM(nombre))=?",
        (sel.strip().upper(),),
    )
    conn.commit()
    demo.registrar_accion("FAMILIA PRODUCTO", f"Eliminada: {sel}")
    return {"ok": True, "msg": f"Familia «{sel}» eliminada."}


def _post_crear_maquinaria(demo, conn) -> dict:
    from erp_maquinaria import TIPOS_MAQUINARIA, generar_codigo_maquinaria

    nom = (request.form.get("nombre") or "").strip()
    tipo = request.form.get("tipo") or TIPOS_MAQUINARIA[0]
    notas = (request.form.get("notas") or "").strip()
    if not nom:
        return {"ok": False, "msg": "Ingrese el nombre del equipo."}
    if tipo not in TIPOS_MAQUINARIA:
        return {"ok": False, "msg": "Tipo de equipo no válido."}
    cod = generar_codigo_maquinaria(conn, tipo)
    if conn.execute(
        "SELECT 1 FROM maestra_maquinaria WHERE UPPER(TRIM(codigo))=?",
        (cod,),
    ).fetchone():
        return {"ok": False, "msg": f"El código «{cod}» ya fue tomado. Intente de nuevo."}
    orden = conn.execute("SELECT COALESCE(MAX(orden), -1) + 1 FROM maestra_maquinaria").fetchone()[0]
    conn.execute(
        """INSERT INTO maestra_maquinaria (codigo, nombre, tipo, activo, orden, notas)
           VALUES (?, ?, ?, 1, ?, ?)""",
        (cod, nom, tipo, orden, notas),
    )
    conn.commit()
    demo.registrar_accion("MAESTRA MAQ", f"Nuevo: {cod} — {nom} ({tipo})")
    return {"ok": True, "msg": f"Equipo registrado: {cod} — {nom}"}


def _post_editar_maquinaria(demo, conn) -> dict:
    from erp_maquinaria import TIPOS_MAQUINARIA

    cod = (request.form.get("codigo") or "").strip()
    nom = (request.form.get("nombre") or "").strip()
    tipo = request.form.get("tipo") or ""
    activo = request.form.get("activo") == "1"
    notas = (request.form.get("notas") or "").strip()
    if not cod or not nom:
        return {"ok": False, "msg": "Código y nombre son obligatorios."}
    if tipo not in TIPOS_MAQUINARIA:
        return {"ok": False, "msg": "Tipo no válido."}
    conn.execute(
        """UPDATE maestra_maquinaria SET nombre=?, tipo=?, activo=?, notas=?
           WHERE UPPER(TRIM(codigo))=?""",
        (nom, tipo, 1 if activo else 0, notas, cod),
    )
    conn.commit()
    demo.registrar_accion("MAESTRA MAQ", f"Editado: {cod}")
    return {"ok": True, "msg": "Equipo actualizado."}


def _post_eliminar_maquinaria(demo, conn) -> dict:
    from erp_maquinaria import contar_eventos_maquinaria

    cod = (request.form.get("codigo") or "").strip()
    if not cod:
        return {"ok": False, "msg": "Seleccione un equipo."}
    if request.form.get("confirm") != "1":
        return {"ok": False, "msg": "Debe confirmar la eliminación."}
    n_ev = contar_eventos_maquinaria(conn, cod)
    if n_ev > 0:
        return {
            "ok": False,
            "msg": f"No se puede eliminar: tiene {n_ev} evento(s). Desactívelo en su lugar.",
        }
    conn.execute("DELETE FROM maestra_maquinaria WHERE UPPER(TRIM(codigo))=?", (cod,))
    conn.commit()
    demo.registrar_accion("MAESTRA MAQ", f"Eliminado: {cod}")
    return {"ok": True, "msg": "Equipo eliminado."}


def _contacto_proveedor_form(prefix: str = "") -> dict:
    return {
        "contacto": (request.form.get(f"{prefix}contacto") or "").strip(),
        "email": (request.form.get(f"{prefix}email") or "").strip(),
        "telefono": (request.form.get(f"{prefix}telefono") or "").strip(),
        "celular": (request.form.get(f"{prefix}celular") or "").strip(),
        "direccion": (request.form.get(f"{prefix}direccion") or "").strip(),
        "mail_pago": request.form.get(f"{prefix}mail_pago") == "1",
        "whatsapp_pago": request.form.get(f"{prefix}whatsapp_pago") == "1",
    }


def _post_crear_proveedor(demo, conn) -> dict:
    from erp_proveedores import (
        TIPOS_PROVEEDOR,
        _nombre_en_maestra,
        _normalizar_texto,
        generar_codigo_proveedor,
    )
    from erp_rut import validar_rut_campo

    nom = _normalizar_texto(request.form.get("nombre"))
    rut_raw = request.form.get("rut") or ""
    tipo = request.form.get("tipo") or TIPOS_PROVEEDOR[0]
    notas = (request.form.get("notas") or "").strip()
    datos = _contacto_proveedor_form()
    ok_rut, msg_rut, rut_fmt = validar_rut_campo(rut_raw, obligatorio=True)
    if not nom:
        return {"ok": False, "msg": "Ingrese el nombre del proveedor."}
    if not ok_rut:
        return {"ok": False, "msg": msg_rut}
    if _nombre_en_maestra(conn, nom):
        return {"ok": False, "msg": f"Ya existe un proveedor llamado «{nom}»."}
    cod = generar_codigo_proveedor(conn)
    orden = conn.execute(
        "SELECT COALESCE(MAX(orden), -1) + 1 FROM maestra_proveedores"
    ).fetchone()[0]
    conn.execute(
        """INSERT INTO maestra_proveedores
           (codigo, nombre, rut, contacto, email, telefono, celular, direccion,
            tipo, activo, mail_pago, whatsapp_pago, orden, notas)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)""",
        (
            cod,
            nom,
            rut_fmt.strip(),
            datos["contacto"],
            datos["email"],
            datos["telefono"],
            datos["celular"],
            datos["direccion"],
            tipo,
            1 if datos["mail_pago"] else 0,
            1 if datos["whatsapp_pago"] else 0,
            orden,
            notas,
        ),
    )
    conn.commit()
    demo.registrar_accion("MAESTRA PROV", f"Nuevo: {cod} — {nom}")
    return {"ok": True, "msg": f"Proveedor registrado: {cod} — {nom}"}


def _post_editar_proveedor(demo, conn) -> dict:
    from erp_proveedores import (
        TIPOS_PROVEEDOR,
        _nombre_en_maestra,
        _normalizar_texto,
        actualizar_referencias_proveedor,
        listar_proveedores,
    )
    from erp_rut import validar_rut_campo

    cod = (request.form.get("codigo") or "").strip()
    nom = _normalizar_texto(request.form.get("nombre"))
    rut_raw = request.form.get("rut") or ""
    tipo = request.form.get("tipo") or TIPOS_PROVEEDOR[0]
    activo = request.form.get("activo") == "1"
    notas = (request.form.get("notas") or "").strip()
    datos = _contacto_proveedor_form("edit_")
    if not cod or not nom:
        return {"ok": False, "msg": "Código y nombre son obligatorios."}
    ok_rut, msg_rut, rut_fmt = validar_rut_campo(rut_raw, obligatorio=True)
    if not ok_rut:
        return {"ok": False, "msg": msg_rut}
    provs = listar_proveedores(conn)
    actual = next((p for p in provs if p["codigo"] == cod), None)
    if not actual:
        return {"ok": False, "msg": "Proveedor no encontrado."}
    if nom.upper() != actual["nombre"].upper() and _nombre_en_maestra(conn, nom):
        return {"ok": False, "msg": f"Ya existe otro proveedor llamado «{nom}»."}
    if nom != actual["nombre"]:
        actualizar_referencias_proveedor(conn, actual["nombre"], nom)
    conn.execute(
        """UPDATE maestra_proveedores
           SET nombre=?, rut=?, contacto=?, email=?, telefono=?, celular=?, direccion=?,
               tipo=?, activo=?, mail_pago=?, whatsapp_pago=?, notas=?
           WHERE UPPER(TRIM(codigo))=?""",
        (
            nom,
            rut_fmt.strip(),
            datos["contacto"],
            datos["email"],
            datos["telefono"],
            datos["celular"],
            datos["direccion"],
            tipo,
            1 if activo else 0,
            1 if datos["mail_pago"] else 0,
            1 if datos["whatsapp_pago"] else 0,
            notas,
            cod,
        ),
    )
    conn.commit()
    demo.registrar_accion("MAESTRA PROV", f"Editado: {cod} → {nom}")
    return {"ok": True, "msg": "Proveedor actualizado."}


def _post_eliminar_proveedor(demo, conn) -> dict:
    from erp_proveedores import contar_referencias_proveedor, listar_proveedores

    cod = (request.form.get("codigo") or "").strip()
    if not cod:
        return {"ok": False, "msg": "Seleccione un proveedor."}
    if request.form.get("confirm") != "1":
        return {"ok": False, "msg": "Debe confirmar la eliminación."}
    provs = listar_proveedores(conn)
    prov = next((p for p in provs if p["codigo"] == cod), None)
    if not prov:
        return {"ok": False, "msg": "Proveedor no encontrado."}
    n_ref = contar_referencias_proveedor(conn, prov["nombre"])
    if n_ref > 0:
        return {"ok": False, "msg": f"No se puede eliminar: {n_ref} referencia(s) en el sistema."}
    conn.execute("DELETE FROM maestra_proveedores WHERE UPPER(TRIM(codigo))=?", (cod,))
    conn.commit()
    demo.registrar_accion("MAESTRA PROV", f"Eliminado: {cod}")
    return {"ok": True, "msg": "Proveedor eliminado."}


def _post_crear_encargado(demo, conn) -> dict:
    from erp_rut import validar_rut_campo

    nombre = (request.form.get("nombre") or "").strip()
    rut_raw = request.form.get("rut") or ""
    email = (request.form.get("email") or "").strip()
    telefono = (request.form.get("telefono") or "").strip()
    notas = (request.form.get("notas") or "").strip()
    ok_rut, msg_rut, rut_fmt = validar_rut_campo(rut_raw, obligatorio=False)
    if not nombre:
        return {"ok": False, "msg": "El nombre es obligatorio."}
    if not ok_rut:
        return {"ok": False, "msg": msg_rut}
    try:
        conn.execute(
            """INSERT INTO encargados_compras (nombre, rut, email, telefono, notas, activo)
               VALUES (?,?,?,?,?,1)""",
            (nombre, rut_fmt, email, telefono, notas),
        )
        conn.commit()
        demo.registrar_accion("ENCARGADO COMPRAS", nombre)
        return {"ok": True, "msg": f"Encargado {nombre} creado."}
    except sqlite3.IntegrityError:
        return {"ok": False, "msg": "Ya existe un encargado con ese nombre."}


def _post_editar_encargado(demo, conn) -> dict:
    from erp_rut import validar_rut_campo

    enc_id = int(request.form.get("enc_id") or 0)
    nombre = (request.form.get("nombre") or "").strip()
    rut_raw = request.form.get("rut") or ""
    email = (request.form.get("email") or "").strip()
    telefono = (request.form.get("telefono") or "").strip()
    notas = (request.form.get("notas") or "").strip()
    activo = request.form.get("activo") == "1"
    ok_rut, msg_rut, rut_fmt = validar_rut_campo(rut_raw, obligatorio=False)
    if not enc_id or not nombre:
        return {"ok": False, "msg": "Datos incompletos."}
    if not ok_rut:
        return {"ok": False, "msg": msg_rut}
    try:
        conn.execute(
            """UPDATE encargados_compras
               SET nombre=?, rut=?, email=?, telefono=?, notas=?, activo=?
               WHERE id=?""",
            (nombre, rut_fmt, email, telefono, notas, 1 if activo else 0, enc_id),
        )
        conn.commit()
        demo.registrar_accion("ENCARGADO COMPRAS EDIT", nombre)
        return {"ok": True, "msg": "Encargado actualizado."}
    except sqlite3.IntegrityError:
        return {"ok": False, "msg": "Ya existe otro encargado con ese nombre."}


def _post_guardar_ingresos_flujo(demo, conn) -> dict:
    from erp_flujo_financiero import (
        guardar_ingresos_cc,
        guardar_saldo_caja_inicial,
        iter_meses_rango,
    )

    temp = request.form.get("temporada") or ""
    if not temp:
        return {"ok": False, "msg": "Temporada no válida."}
    fi = ff = None
    for t in demo.TEMPORADAS_COSTOS:
        if t[0] == temp:
            fi, ff = t[1], t[2]
            break
    if fi is None:
        return {"ok": False, "msg": "Temporada no encontrada."}
    meses = list(iter_meses_rango(fi, ff))
    try:
        caja_ini = float(request.form.get("caja_inicial") or 0)
    except ValueError:
        return {"ok": False, "msg": "Saldo caja inicial inválido."}
    ing_cc = {}
    notas_cc = {}
    for cc in demo.CUARTELES_OFICIALES:
        for anio, mes in meses:
            key = f"ing_{cc}_{anio}_{mes}"
            nota_key = f"nota_{cc}_{anio}_{mes}"
            try:
                monto = float(request.form.get(key) or 0)
            except ValueError:
                return {"ok": False, "msg": f"Monto inválido en {cc}."}
            ing_cc[(cc, anio, mes)] = monto
            notas_cc[(cc, anio, mes)] = (request.form.get(nota_key) or "").strip()
    guardar_ingresos_cc(conn, temp, ing_cc, notas_cc)
    guardar_saldo_caja_inicial(conn, temp, caja_ini)
    demo.registrar_accion("FLUJO INGRESOS", temp)
    return {"ok": True, "msg": f"Ingresos guardados para temporada {temp}."}


def _post_guardar_respaldo_config(demo, conn, user_email: str) -> dict:
    from erp_respaldo import (
        FRECUENCIAS_RESPALDO,
        _registrar_bitacora,
        guardar_config_respaldo,
        normalizar_correos,
    )

    email = (request.form.get("email") or "").strip()
    activo = request.form.get("activo") == "1"
    freq_dat = request.form.get("freq_datos") or "diario"
    freq_cod = request.form.get("freq_codigo") or "semanal"
    if freq_dat not in FRECUENCIAS_RESPALDO:
        freq_dat = "diario"
    if freq_cod not in FRECUENCIAS_RESPALDO:
        freq_cod = "semanal"
    if activo and not normalizar_correos(email):
        return {"ok": False, "msg": "Ingrese un correo válido para activar el respaldo automático."}
    guardar_config_respaldo(conn, email, freq_dat, freq_cod, activo)
    _registrar_bitacora(
        conn,
        user_email,
        "CONFIG_RESPALDO",
        f"datos={freq_dat}, código={freq_cod} → {email}",
    )
    return {"ok": True, "msg": "Configuración de respaldo guardada."}


def _post_enviar_respaldo_datos(demo, conn, user_email: str) -> dict:
    from erp_respaldo import ejecutar_respaldo, normalizar_correos, obtener_config_respaldo

    config = obtener_config_respaldo(conn)
    if not normalizar_correos(config.get("email", "")):
        return {"ok": False, "msg": "Configure un correo destino antes de enviar."}
    res = ejecutar_respaldo(
        conn, demo.NOMBRE_ERP, demo.NOMBRE_DB, demo.SECRETS_PATH, forzar=True, usuario=user_email,
    )
    if res.get("ok"):
        dest = ", ".join(res.get("destinatarios", []))
        return {"ok": True, "msg": f"Datos de {demo.NOMBRE_ERP} enviados a {dest}."}
    motivo = res.get("motivo", "")
    if motivo == "smtp":
        return {"ok": False, "msg": f"No hay SMTP configurado: {res.get('error', '')}"}
    return {"ok": False, "msg": f"No se pudo enviar: {res.get('error', motivo)}"}


def _post_enviar_respaldo_codigo(demo, conn, user_email: str) -> dict:
    from erp_respaldo import (
        ejecutar_respaldo_codigo,
        normalizar_correos,
        obtener_config_respaldo,
        spec_respaldo_codigo_por_nombre,
    )

    spec = spec_respaldo_codigo_por_nombre(demo.NOMBRE_ERP)
    if not spec:
        return {"ok": False, "msg": "No hay definición de respaldo de código para este ERP."}
    config = obtener_config_respaldo(conn)
    if not normalizar_correos(config.get("email", "")):
        return {"ok": False, "msg": "Configure un correo destino antes de enviar."}
    res = ejecutar_respaldo_codigo(
        conn, spec, demo.SECRETS_PATH, forzar=True, usuario=user_email,
    )
    if res.get("ok"):
        dest = ", ".join(res.get("destinatarios", []))
        n = res.get("archivos", 0)
        return {"ok": True, "msg": f"Código enviado a {dest} ({n} archivos)."}
    motivo = res.get("motivo", "")
    if motivo == "smtp":
        return {"ok": False, "msg": f"No hay SMTP configurado: {res.get('error', '')}"}
    return {"ok": False, "msg": f"No se pudo enviar código: {res.get('error', motivo)}"}


def _post_reseed(demo, conn) -> dict:
    if not demo.es_super_admin():
        return {"ok": False, "msg": "Solo super administrador puede re-sembrar."}
    if request.form.get("confirm") != "1":
        return {"ok": False, "msg": "Debe confirmar el re-seed."}
    from demo_seed import DEMO_SEED_VERSION, sembrar_datos_demo, vaciar_datos_demo

    cur = conn.cursor()
    vaciar_datos_demo(cur)
    h = demo.hora_chile().date()
    sembrar_datos_demo(
        cur,
        h,
        demo.hora_chile().strftime("%m"),
        demo.hora_chile().year,
        demo.PRORRATEO_RRHH,
        demo.CENTROS_COSTO,
        demo.CUARTELES_PRORRATEO,
        demo.TEMPORADAS_COSTOS,
        demo.RAZONES_SOCIALES_COMPRAS[0],
        demo.TIPO_GASTO_SIN_CLASIFICAR,
        demo.hora_chile,
    )
    cur.execute(
        "INSERT OR REPLACE INTO schema_meta (clave, valor) VALUES (?, '1')",
        (DEMO_SEED_VERSION,),
    )
    conn.commit()
    demo.registrar_accion("DEMO RESEED", DEMO_SEED_VERSION)
    return {"ok": True, "msg": "Datos ficticios re-sembrados."}


def view(user_email: str, user_rol: str):
    from flask import Response

    demo = get_demo_module()
    bind_user_session(user_email, user_rol)

    if not demo.puede_administracion():
        flash("Solo administradores pueden acceder a Administración.", "danger")
        return redirect_module("dashboard")

    sec = _sec_activa(demo)

    if request.method == "GET" and request.args.get("action") == "download_db":
        if not demo.es_super_admin():
            flash("Solo super administrador puede descargar la base.", "danger")
            return redirect_module("admin", sec="respaldo")
        import os

        from erp_respaldo import crear_archivo_respaldo

        try:
            gz_path = crear_archivo_respaldo(demo.NOMBRE_DB)
            with open(gz_path, "rb") as f:
                data = f.read()
        except FileNotFoundError as exc:
            flash(str(exc), "danger")
            return redirect_module("admin", sec="respaldo")
        finally:
            if "gz_path" in locals() and os.path.exists(gz_path):
                os.remove(gz_path)
        slug = "".join(c if c.isalnum() else "_" for c in demo.NOMBRE_ERP.lower()).strip("_")[:40] or "erp"
        fname = f"respaldo_{slug}.db.gz"
        demo.registrar_accion("RESPALDO DESCARGA", fname)
        return Response(
            data,
            mimetype="application/gzip",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )

    if request.method == "POST":
        action = request.form.get("action", "")
        conn = demo.conectar_db()
        try:
            result: dict | None = None
            if action == "crear_usuario":
                result = _post_crear_usuario(demo, conn, user_email)
            elif action == "cambiar_rol":
                result = _post_cambiar_rol(demo, conn)
            elif action == "cambiar_clave":
                result = _post_cambiar_clave(demo, conn)
            elif action == "eliminar_usuario":
                result = _post_eliminar_usuario(demo, conn, user_email)
            elif action == "mail_teso":
                result = _post_mail_teso(demo, conn)
            elif action == "guardar_modulos":
                result = _post_guardar_modulos(demo, conn)
            elif action == "crear_familia":
                result = _post_crear_familia(demo, conn)
            elif action == "renombrar_familia":
                result = _post_renombrar_familia(demo, conn)
            elif action == "eliminar_familia":
                result = _post_eliminar_familia(demo, conn)
            elif action == "crear_maquinaria":
                result = _post_crear_maquinaria(demo, conn)
            elif action == "editar_maquinaria":
                result = _post_editar_maquinaria(demo, conn)
            elif action == "eliminar_maquinaria":
                result = _post_eliminar_maquinaria(demo, conn)
            elif action == "crear_proveedor":
                result = _post_crear_proveedor(demo, conn)
            elif action == "editar_proveedor":
                result = _post_editar_proveedor(demo, conn)
            elif action == "eliminar_proveedor":
                result = _post_eliminar_proveedor(demo, conn)
            elif action == "crear_encargado":
                result = _post_crear_encargado(demo, conn)
            elif action == "editar_encargado":
                result = _post_editar_encargado(demo, conn)
            elif action == "guardar_metas":
                result = _post_guardar_metas(demo, conn)
            elif action == "guardar_ingresos_flujo":
                result = _post_guardar_ingresos_flujo(demo, conn)
            elif action == "guardar_respaldo_config":
                result = _post_guardar_respaldo_config(demo, conn, user_email)
            elif action == "enviar_respaldo_datos":
                result = _post_enviar_respaldo_datos(demo, conn, user_email)
            elif action == "enviar_respaldo_codigo":
                result = _post_enviar_respaldo_codigo(demo, conn, user_email)
            elif action == "reseed":
                result = _post_reseed(demo, conn)

            if result:
                flash(result["msg"], "success" if result["ok"] else "danger")
                extra = {"sec": sec}
                if action == "guardar_modulos":
                    extra["operador"] = request.form.get("operador", "")
                if action in ("guardar_metas", "guardar_ingresos_flujo"):
                    extra["temp"] = request.form.get("temporada", "")
                if action == "renombrar_familia":
                    extra["familia"] = request.form.get("nuevo_nombre", "")
                elif action == "eliminar_familia":
                    extra["familia"] = request.form.get("familia", "")
                if action in ("editar_maquinaria", "eliminar_maquinaria"):
                    extra["codigo"] = request.form.get("codigo", "")
                if action == "crear_maquinaria":
                    extra["tipo"] = request.form.get("tipo", "")
                if action in ("editar_proveedor", "eliminar_proveedor"):
                    extra["codigo"] = request.form.get("codigo", "")
                if action == "editar_encargado":
                    extra["enc_id"] = request.form.get("enc_id", "")
                return redirect_module("admin", **extra)
        finally:
            conn.close()

    ctx = gather_admin(user_email, user_rol)
    return render_template(
        "modules/administracion.html",
        page_title="Administración",
        active_key="Administracion",
        **ctx,
    )
