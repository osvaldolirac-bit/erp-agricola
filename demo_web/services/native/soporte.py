from __future__ import annotations

from flask import flash, render_template, request, redirect, url_for

from demo_web.services.demo_loader import bind_user_session, get_demo_module
from demo_web.services.module_runner import redirect_module

SECCIONES_USER = [
    ("nuevo", "➕ NUEVO TICKET"),
    ("mis", "📋 MIS TICKETS"),
]

MASTER_SOPORTE_URL = "https://erpmaster.cl/plataforma/soporte"


def _admin_email(demo) -> str:
    conf = demo._conf_smtp_demo()
    if conf:
        return conf.get("receptor_admin", "osvaldolira@laconcepcion.cl")
    return "osvaldolira@laconcepcion.cl"


def _mis_tickets(conn, usuario: str) -> list[dict]:
    rows = conn.execute(
        """SELECT id, codigo_ticket, fecha_creacion, erp_origen, status,
                  CASE WHEN respuesta_admin IS NOT NULL AND TRIM(respuesta_admin)!=''
                       THEN 1 ELSE 0 END AS tiene_respuesta,
                  descripcion
           FROM tickets_soporte WHERE usuario=? ORDER BY id DESC""",
        (usuario,),
    ).fetchall()
    out = []
    for r in rows:
        desc = str(r[6] or "")
        resumen = desc[:100] + ("…" if len(desc) > 100 else "")
        out.append(
            {
                "id": int(r[0]),
                "codigo": r[1] or f"#{r[0]}",
                "fecha": str(r[2] or "")[:19],
                "erp": r[3] or "",
                "estado": r[4] or "",
                "respuesta": "Sí" if r[5] else "Pendiente",
                "resumen": resumen,
            }
        )
    return out


def _ticket_detalle(conn, ticket_id: int) -> dict | None:
    row = conn.execute(
        """SELECT codigo_ticket, descripcion, status, respuesta_admin, fecha_respuesta, usuario
           FROM tickets_soporte WHERE id=?""",
        (ticket_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "id": ticket_id,
        "codigo": row[0] or f"#{ticket_id}",
        "descripcion": row[1] or "",
        "estado": row[2] or "",
        "respuesta": row[3] or "",
        "fecha_respuesta": str(row[4] or "")[:19],
        "usuario": row[5] or "",
    }


def _crear_ticket(demo, conn, user_email: str) -> dict:
    from erp_soporte import enviar_correo_ticket_nuevo, generar_codigo_ticket, migrar_tickets_soporte

    migrar_tickets_soporte(conn)
    txt = (request.form.get("descripcion") or "").strip()
    if len(txt) < 10:
        return {"ok": False, "msg": "Describa el problema con al menos 10 caracteres."}

    f_h = demo.hora_chile().strftime("%Y-%m-%d %H:%M:%S")
    codigo = generar_codigo_ticket(conn, demo.NOMBRE_ERP, demo.hora_chile())
    conn.execute(
        """INSERT INTO tickets_soporte
           (codigo_ticket, usuario, descripcion, status, erp_origen, fecha_creacion, fecha_actualizacion, leido_admin)
           VALUES (?,?,?,?,?,?,?,0)""",
        (codigo, user_email, txt, "Abierto", demo.NOMBRE_ERP, f_h, f_h),
    )
    conn.commit()

    mail_ok = enviar_correo_ticket_nuevo(
        demo.NOMBRE_ERP,
        codigo,
        user_email,
        txt,
        demo._enviar_correo_html,
        _admin_email(demo),
    )
    demo.registrar_accion("SOPORTE", f"Ticket {codigo}")
    if mail_ok:
        return {"ok": True, "msg": f"Ticket {codigo} registrado. El administrador fue notificado por correo."}
    return {
        "ok": True,
        "msg": f"Ticket {codigo} registrado, pero no se pudo enviar el correo (revise SMTP).",
    }


def gather_soporte(user_email: str, user_rol: str) -> dict:
    from erp_soporte import migrar_tickets_soporte

    demo = get_demo_module()
    bind_user_session(user_email, user_rol)
    conn = demo.conectar_db()
    try:
        migrar_tickets_soporte(conn)
        # Inbox/respuesta se gestiona en Super Consola (Master).
        if demo.es_admin():
            return {
                "es_admin": True,
                "master_soporte_url": MASTER_SOPORTE_URL,
                "n_pendientes": 0,
                "tickets_pendientes": [],
                "tickets_historial": [],
                "statuses": [],
            }

        sec = request.args.get("sec", "nuevo")
        if sec not in {k for k, _ in SECCIONES_USER}:
            sec = "nuevo"

        mis = _mis_tickets(conn, user_email)
        detalle = None
        if sec == "mis" and mis:
            tid_raw = request.args.get("ticket_id")
            tid = int(tid_raw) if tid_raw and tid_raw.isdigit() else mis[0]["id"]
            if any(t["id"] == tid for t in mis):
                detalle = _ticket_detalle(conn, tid)

        return {
            "es_admin": False,
            "secciones": SECCIONES_USER,
            "sec_activa": sec,
            "mis_tickets": mis,
            "ticket_detalle": detalle,
            "ticket_sel": request.args.get("ticket_id", str(mis[0]["id"]) if mis else ""),
            "nombre_erp": demo.NOMBRE_ERP,
        }
    finally:
        conn.close()


def view(user_email: str, user_rol: str):
    demo = get_demo_module()
    bind_user_session(user_email, user_rol)

    if request.method == "POST":
        action = request.form.get("action", "")
        # Responder tickets ya no se hace en el ERP.
        if action == "responder":
            flash(
                "La gestión de tickets se realiza en la Super Consola de ERP Master.",
                "warning",
            )
            return redirect(url_for("modules.soporte"))
        conn = demo.conectar_db()
        try:
            if action == "crear":
                if demo.es_admin():
                    flash(
                        "Como administrador, gestione y responda tickets en la Super Consola.",
                        "warning",
                    )
                    return redirect(url_for("modules.soporte"))
                result = _crear_ticket(demo, conn, user_email)
                flash(result["msg"], "success" if result["ok"] else "danger")
                return redirect_module("soporte", sec="mis" if result.get("ok") else "nuevo")
        finally:
            conn.close()

    ctx = gather_soporte(user_email, user_rol)
    return render_template(
        "modules/soporte.html",
        page_title="Soporte",
        active_key="Soporte",
        title="🎫 Soporte",
        **ctx,
    )
