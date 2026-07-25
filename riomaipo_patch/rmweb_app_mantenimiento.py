"""ERP Master · Río Maipo — Flask + Bootstrap + DataTables (reemplazo de Streamlit)."""

from __future__ import annotations

import os
from datetime import date, timedelta
from functools import wraps

from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from io import BytesIO

from rmweb import core

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/static",
)
app.secret_key = os.getenv("SECRET_KEY", "riomaipo-web-change-me")

# Prefijo público detrás de nginx (/riomaipo)
try:
    from werkzeug.middleware.proxy_fix import ProxyFix

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
except Exception:  # pragma: no cover
    pass


def _riomaipo_en_mantenimiento() -> bool:
    status_dir = os.environ.get("ERP_STATUS_DIR", "/root/erp_status").strip() or "/root/erp_status"
    path = os.path.join(status_dir, "riomaipo.mantenimiento")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip() == "1"
    except OSError:
        return False


@app.before_request
def _boot():
    # Cuando nginx recorta /riomaipo/ y envía X-Forwarded-Prefix
    prefix = (request.headers.get("X-Forwarded-Prefix") or os.getenv("RIOMAIPO_PREFIX") or "").rstrip("/")
    if prefix:
        request.environ["SCRIPT_NAME"] = prefix
    if request.path.startswith("/static/"):
        return None
    if _riomaipo_en_mantenimiento():
        from flask import Response

        html = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sitio en mantención — Río Maipo</title>
<style>
body{margin:0;min-height:100vh;display:grid;place-items:center;padding:1.5rem;font-family:Georgia,serif;color:#1c1914;
background:repeating-linear-gradient(-45deg,#f59e0b,#f59e0b 18px,#111827 18px,#111827 36px)}
.card{width:min(560px,100%);background:#f3efe4;border:4px solid #111827;box-shadow:0 18px 40px rgba(0,0,0,.28);padding:2rem 1.6rem;text-align:center}
.cones{display:flex;justify-content:center;align-items:flex-end;gap:1.4rem;height:64px;margin-bottom:1rem}
.cone{width:0;height:0;border-left:22px solid transparent;border-right:22px solid transparent;border-bottom:48px solid #d97706;filter:drop-shadow(0 2px 0 #111);position:relative}
.cone:after{content:"";position:absolute;left:-14px;top:18px;width:28px;height:7px;background:#111}
.bar{width:70px;height:14px;margin-bottom:8px;border:2px solid #111;background:repeating-linear-gradient(90deg,#f59e0b 0 10px,#111 10px 20px)}
.badge{display:inline-block;background:#d97706;font-family:Segoe UI,sans-serif;font-size:.72rem;font-weight:800;letter-spacing:.14em;text-transform:uppercase;padding:.35rem .7rem;margin:.2rem 0 .85rem}
h1{margin:0 0 .55rem;font-size:clamp(1.7rem,5vw,2.2rem)}
p{margin:0;font-family:Segoe UI,sans-serif;color:#5c564c;font-size:1.05rem;line-height:1.45}
.soon{margin-top:1rem;font-weight:700;color:#1c1914;font-size:1.12rem}
.foot{margin-top:1.35rem;font-size:.82rem;color:#7a7468}
</style></head><body><main class="card">
<div class="cones" aria-hidden="true"><span class="cone"></span><span class="bar"></span><span class="cone"></span></div>
<div class="badge">Sitio en mantención</div>
<h1>Río Maipo</h1>
<p>Estamos realizando una actualización o reparación programada.</p>
<p class="soon">Regresamos a la brevedad.</p>
<p class="foot">Más adelante publicaremos datos de contacto aquí.</p>
</main></body></html>"""
        return Response(html, status=503, mimetype="text/html; charset=utf-8")
    if not getattr(g, "_db_ready", False):
        core.init_db()
        g._db_ready = True


def _safe_next_redirect(nxt: str | None):
    """Evita salir de /riomaipo (p.ej. next=/ cae en nginx → /laconcepcion/)."""
    nxt = (nxt or "").strip()
    if not nxt or nxt == "/" or not nxt.startswith("/") or nxt.startswith("//") or "://" in nxt:
        return redirect(url_for("dashboard"))
    # request.path viene sin SCRIPT_NAME; hay que anteponer el prefijo público
    prefix = (request.script_root or "").rstrip("/")
    return redirect(prefix + nxt)


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("auth_ok"):
            path = request.path or "/"
            if path in ("/", ""):
                return redirect(url_for("login"))
            return redirect(url_for("login", next=path))
        return fn(*args, **kwargs)

    return wrapper


@app.context_processor
def inject_globals():
    return {
        "clp": core.clp,
        "fmt_dmy": core.fmt_dmy,
        "estado_label_cot": core.estado_label_cot,
        "cxc_estado_label": core.cxc_estado_label,
        "cxc_estado_class": core.cxc_estado_class,
        "auth_user": session.get("auth_user", ""),
        "auth_nombre": session.get("auth_nombre", ""),
        "auth_tipo": session.get("auth_tipo", ""),
        "app_name": "ERP Master",
        "track_name": "Río Maipo",
    }


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("auth_ok"):
        return redirect(url_for("dashboard"))
    accesos = core.list_accesos()
    default_user = request.form.get("usuario") or request.args.get("acceso") or core.DEFAULT_ACCESO
    if default_user not in accesos:
        default_user = accesos[0] if accesos else core.DEFAULT_ACCESO
    error = None
    if request.method == "POST":
        user = core.get_user_if_valid(
            request.form.get("usuario", ""),
            request.form.get("clave", ""),
        )
        if user:
            session["auth_ok"] = True
            session["auth_user"] = user["usuario"]
            session["auth_nombre"] = user["nombre"] or user["usuario"]
            session["auth_tipo"] = user["tipo"] or "Consulta"
            return _safe_next_redirect(request.args.get("next"))
        error = "Usuario o clave incorrectos"
        default_user = request.form.get("usuario") or default_user
    return render_template(
        "login.html",
        error=error,
        default_user=default_user,
        accesos=accesos,
    )


@app.route("/favicon.ico")
def favicon():
    return app.send_static_file("favicon.svg")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@app.route("/")
@login_required
def dashboard():
    db = core.conn()
    cotas = db.execute(
        "SELECT estado, COUNT(*) n, COALESCE(SUM(total),0) t FROM cotizaciones GROUP BY estado"
    ).fetchall()
    n_cot = sum(r["n"] for r in cotas)
    sum_cot = sum(float(r["t"]) for r in cotas)
    n_apr = sum(r["n"] for r in cotas if r["estado"] == "aprobada")
    saldo = db.execute("SELECT COALESCE(SUM(saldo),0) s FROM cuentas").fetchone()["s"]
    pend = db.execute(
        "SELECT COUNT(*) n FROM cuentas WHERE saldo > 0"
    ).fetchone()["n"]
    venc = db.execute(
        """
        SELECT COUNT(*) n FROM cuentas
        WHERE saldo > 0 AND fecha_vencimiento IS NOT NULL AND fecha_vencimiento < date('now')
        """
    ).fetchone()["n"]
    top = db.execute(
        """
        SELECT cl.razon_social, COALESCE(SUM(cu.saldo),0) saldo
        FROM cuentas cu LEFT JOIN clientes cl ON cl.id=cu.cliente_id
        GROUP BY cu.cliente_id
        HAVING saldo > 0
        ORDER BY saldo DESC LIMIT 8
        """
    ).fetchall()
    db.close()
    return render_template(
        "dashboard.html",
        active="dashboard",
        n_cot=n_cot,
        sum_cot=sum_cot,
        n_apr=n_apr,
        saldo=saldo,
        pend=pend,
        venc=venc,
        top=top,
        cotas=cotas,
    )


# ---------------------------------------------------------------------------
# Clientes
# ---------------------------------------------------------------------------
@app.route("/clientes/")
@login_required
def clientes_list():
    q = (request.args.get("q") or "").strip()
    db = core.conn()
    sql = """
        SELECT id, rut, razon_social, contacto, telefono, email, comuna, activo
        FROM clientes WHERE 1=1
    """
    params: list = []
    if q:
        like = f"%{q}%"
        sql += " AND (rut LIKE ? OR razon_social LIKE ? OR email LIKE ? OR contacto LIKE ?)"
        params.extend([like, like, like, like])
    sql += " ORDER BY razon_social"
    rows = db.execute(sql, params).fetchall()
    db.close()
    return render_template("clientes/lista.html", active="clientes", rows=rows, q=q)


@app.route("/clientes/nuevo", methods=["GET", "POST"])
@app.route("/clientes/<int:cid>/editar", methods=["GET", "POST"])
@login_required
def clientes_form(cid: int | None = None):
    db = core.conn()
    row = db.execute("SELECT * FROM clientes WHERE id=?", (cid,)).fetchone() if cid else None
    if request.method == "POST":
        data = (
            request.form.get("rut", "").strip() or None,
            request.form.get("razon_social", "").strip(),
            request.form.get("contacto", "").strip() or None,
            request.form.get("telefono", "").strip() or None,
            request.form.get("email", "").strip() or None,
            request.form.get("direccion", "").strip() or None,
            request.form.get("comuna", "").strip() or None,
            1 if request.form.get("activo") else 0,
        )
        if not data[1]:
            flash("La razón social es obligatoria", "danger")
        else:
            try:
                if row:
                    db.execute(
                        """
                        UPDATE clientes SET rut=?, razon_social=?, contacto=?, telefono=?,
                        email=?, direccion=?, comuna=?, activo=? WHERE id=?
                        """,
                        (*data, row["id"]),
                    )
                else:
                    db.execute(
                        """
                        INSERT INTO clientes
                        (rut, razon_social, contacto, telefono, email, direccion, comuna, activo, creado_en)
                        VALUES (?,?,?,?,?,?,?,?,?)
                        """,
                        (*data, date.today().isoformat()),
                    )
                db.commit()
                flash("Cliente guardado", "ok")
                db.close()
                return redirect(url_for("clientes_list"))
            except Exception as exc:
                flash(f"No se pudo guardar: {exc}", "danger")
    db.close()
    return render_template("clientes/form.html", active="clientes", row=row)


# ---------------------------------------------------------------------------
# Cotizaciones
# ---------------------------------------------------------------------------
@app.route("/cotizaciones/")
@login_required
def cotizaciones_list():
    db = core.conn()
    rows = db.execute(
        """
        SELECT c.id, c.folio, c.fecha, c.estado, c.total, c.asunto, c.proyecto, c.titulo,
               cl.razon_social AS cliente
        FROM cotizaciones c
        LEFT JOIN clientes cl ON cl.id = c.cliente_id
        ORDER BY COALESCE(c.fecha,'') DESC, c.id DESC
        """
    ).fetchall()
    n_total = len(rows)
    sum_total = sum(float(r["total"] or 0) for r in rows)
    n_apr = sum(1 for r in rows if r["estado"] == "aprobada")
    n_rec = sum(1 for r in rows if r["estado"] == "rechazada")
    sum_apr = sum(float(r["total"] or 0) for r in rows if r["estado"] == "aprobada")
    sum_rec = sum(float(r["total"] or 0) for r in rows if r["estado"] == "rechazada")
    conv = (n_apr / n_total * 100) if n_total else 0
    db.close()
    return render_template(
        "cotizaciones/lista.html",
        active="cotizaciones",
        rows=rows,
        kpis={
            "n_total": n_total,
            "sum_total": sum_total,
            "n_apr": n_apr,
            "sum_apr": sum_apr,
            "n_rec": n_rec,
            "sum_rec": sum_rec,
            "conv": conv,
        },
    )


@app.route("/cotizaciones/nueva", methods=["GET", "POST"])
@app.route("/cotizaciones/<int:cot_id>/editar", methods=["GET", "POST"])
@login_required
def cotizaciones_form(cot_id: int | None = None):
    db = core.conn()
    clientes = db.execute(
        "SELECT id, razon_social FROM clientes WHERE activo=1 ORDER BY razon_social"
    ).fetchall()
    edit = None
    items = []
    if cot_id:
        edit = db.execute(
            """
            SELECT c.*, cl.razon_social FROM cotizaciones c
            LEFT JOIN clientes cl ON cl.id=c.cliente_id WHERE c.id=?
            """,
            (cot_id,),
        ).fetchone()
        if not edit:
            flash("Cotización no encontrada", "danger")
            db.close()
            return redirect(url_for("cotizaciones_list"))
        raw_items = db.execute(
            """
            SELECT * FROM cotizacion_items WHERE cotizacion_id=?
            ORDER BY COALESCE(orden,0), id
            """,
            (cot_id,),
        ).fetchall()
        # En el formulario no se editan GG/Utilidad como ítems (van en el resumen)
        items = [
            it
            for it in raw_items
            if not core._is_gg_line(it["descripcion"]) and not core._is_util_line(it["descripcion"])
        ]

    iva_def = core.param(db, "iva", 19)
    iva_pct = float(iva_def) / 100.0
    gg_def = core.param(db, "gg_pct", 5)
    util_def = core.param(db, "utilidad_pct", 15)
    validez_def = int(core.param(db, "validez_cotizacion", 30))

    if request.method == "POST":
        cliente_id = int(request.form["cliente_id"])
        version = (request.form.get("version") or "1").strip().lstrip("Vv") or "1"
        titulo = (request.form.get("titulo") or "").strip() or None
        proyecto = (request.form.get("proyecto") or "").strip() or None
        asunto = (request.form.get("asunto") or "").strip() or None
        estado = request.form.get("estado") or "borrador"
        fecha = (request.form.get("fecha") or "").strip() or date.today().isoformat()
        validez = int(request.form.get("validez") or validez_def)
        gg_pct = float(request.form.get("gg_pct") or gg_def)
        utilidad_pct = float(request.form.get("utilidad_pct") or util_def)
        # Permite ajustar IVA por cotización; si no viene, usa parámetro
        try:
            iva_pct = float(request.form.get("iva_pct") or iva_def) / 100.0
        except (TypeError, ValueError):
            iva_pct = float(iva_def) / 100.0
        notas = (request.form.get("notas") or "").strip() or None

        descs = request.form.getlist("desc")
        obss = request.form.getlist("obs")
        unds = request.form.getlist("und")
        cants = request.form.getlist("cant")
        valores = request.form.getlist("valor")
        lineas = []
        orden = 0
        for i, desc in enumerate(descs):
            d = str(desc).strip()
            if not d:
                continue
            # No persistir GG/Utilidad como ítems de planilla
            if core._is_gg_line(d) or core._is_util_line(d):
                continue
            cant = float(cants[i] or 0)
            pu = float(valores[i] or 0)
            # Permite encabezados de sección (cant/pu en 0) si hay descripción
            if cant < 0:
                continue
            if cant == 0 and pu == 0:
                # encabezado: se guarda con cantidad 1 y valor 0 para no perderlo
                cant = 1.0
                pu = 0.0
            if cant <= 0:
                continue
            total = cant * pu
            orden += 1
            lineas.append(
                (
                    None,
                    d,
                    (obss[i] if i < len(obss) else "").strip() or None,
                    orden,
                    (unds[i] if i < len(unds) else "un").strip() or "un",
                    cant,
                    pu,
                    total,
                )
            )
        if not lineas:
            flash("Agrega al menos un ítem con cantidad > 0", "danger")
        else:
            tots = core.calc_cotizacion_totales(
                sum(x[7] for x in lineas), gg_pct, utilidad_pct, iva_pct
            )
            if edit:
                db.execute(
                    """
                    UPDATE cotizaciones SET
                      cliente_id=?, asunto=?, proyecto=?, estado=?, fecha=?, validez_dias=?,
                      version=?, titulo=?, gg_pct=?, utilidad_pct=?,
                      gg_monto=?, utilidad_monto=?, valor_neto=?,
                      subtotal=?, iva=?, total=?, notas=?
                    WHERE id=?
                    """,
                    (
                        cliente_id, asunto, proyecto, estado, fecha, validez,
                        version, titulo, gg_pct, utilidad_pct,
                        tots["gg_monto"], tots["utilidad_monto"], tots["valor_neto"],
                        tots["subtotal"], tots["iva"], tots["total"], notas, edit["id"],
                    ),
                )
                db.execute("DELETE FROM cotizacion_items WHERE cotizacion_id=?", (edit["id"],))
                cid = edit["id"]
                folio = edit["folio"]
            else:
                folio = core.next_code(db, "cotizaciones", "folio", "COT")
                cur = db.cursor()
                cur.execute(
                    """
                    INSERT INTO cotizaciones
                    (folio, cliente_id, asunto, proyecto, estado, fecha, validez_dias,
                     version, titulo, gg_pct, utilidad_pct,
                     gg_monto, utilidad_monto, valor_neto, subtotal, iva, total, notas)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        folio, cliente_id, asunto, proyecto, estado,
                        fecha, validez,
                        version, titulo, gg_pct, utilidad_pct,
                        tots["gg_monto"], tots["utilidad_monto"], tots["valor_neto"],
                        tots["subtotal"], tots["iva"], tots["total"], notas,
                    ),
                )
                cid = cur.lastrowid
            db.executemany(
                """
                INSERT INTO cotizacion_items
                (cotizacion_id, producto_id, descripcion, obs, orden, unidad, cantidad, precio_unitario, total)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                [(cid, *ln) for ln in lineas],
            )
            cxc_doc = None
            if estado == "aprobada":
                cxc_doc = core.ensure_cxc_from_cotizacion(db, cid)
            db.commit()
            msg = f"{folio} guardada · total {core.clp(tots['total'])}"
            if cxc_doc:
                msg += f" · CxC {cxc_doc} generada"
            flash(msg, "ok")
            db.close()
            return redirect(url_for("cotizaciones_detalle", cot_id=cid))

    # defaults for new form title from first client
    titulo_default = ""
    if not edit and clientes:
        titulo_default = (clientes[0]["razon_social"] or "").upper()
    if edit and edit["titulo"]:
        titulo_default = edit["titulo"]

    db.close()
    return render_template(
        "cotizaciones/form.html",
        active="cotizaciones",
        edit=edit,
        items=items,
        clientes=clientes,
        titulo_default=titulo_default,
        gg_def=gg_def,
        util_def=util_def,
        iva_def=iva_def,
        validez_def=validez_def,
        hoy=date.today().isoformat(),
        slots=16,
    )


@app.route("/cotizaciones/<int:cot_id>")
@login_required
def cotizaciones_detalle(cot_id: int):
    db = core.conn()
    cot = db.execute(
        """
        SELECT c.*, cl.razon_social, cl.rut AS cliente_rut
        FROM cotizaciones c LEFT JOIN clientes cl ON cl.id=c.cliente_id
        WHERE c.id=?
        """,
        (cot_id,),
    ).fetchone()
    if not cot:
        flash("Cotización no encontrada", "danger")
        db.close()
        return redirect(url_for("cotizaciones_list"))
    items = db.execute(
        """
        SELECT * FROM cotizacion_items WHERE cotizacion_id=?
        ORDER BY COALESCE(orden,0), id
        """,
        (cot_id,),
    ).fetchall()
    items = [
        it
        for it in items
        if not core._is_gg_line(it["descripcion"]) and not core._is_util_line(it["descripcion"])
    ]
    cxc = None
    if cot["cxc_id"]:
        cxc = db.execute(
            "SELECT id, documento, num_factura, saldo, estado FROM cuentas WHERE id=?",
            (cot["cxc_id"],),
        ).fetchone()
    db.close()
    return render_template(
        "cotizaciones/detalle.html",
        active="cotizaciones",
        cot=cot,
        items=items,
        cxc=cxc,
    )


@app.route("/cotizaciones/<int:cot_id>/pdf")
@login_required
def cotizaciones_pdf(cot_id: int):
    db = core.conn()
    cot = db.execute(
        """
        SELECT c.*, cl.razon_social, cl.rut AS cliente_rut
        FROM cotizaciones c LEFT JOIN clientes cl ON cl.id=c.cliente_id
        WHERE c.id=?
        """,
        (cot_id,),
    ).fetchone()
    items = db.execute(
        """
        SELECT descripcion, COALESCE(obs,'') AS obs, unidad, cantidad, precio_unitario, total,
               COALESCE(orden,0) AS orden
        FROM cotizacion_items WHERE cotizacion_id=? ORDER BY COALESCE(orden,0), id
        """,
        (cot_id,),
    ).fetchall()
    empresa = db.execute("SELECT * FROM empresa WHERE id=1").fetchone()
    iva_pct = core.param(db, "iva", 19) / 100.0
    db.close()
    if not cot:
        flash("Cotización no encontrada", "danger")
        return redirect(url_for("cotizaciones_list"))
    pdf = core.cotizacion_pdf_bytes(cot, items, empresa, iva_pct=iva_pct)
    return send_file(
        BytesIO(pdf),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{cot['folio']}.pdf",
    )


@app.route("/cotizaciones/<int:cot_id>/borrar", methods=["POST"])
@login_required
def cotizaciones_borrar(cot_id: int):
    db = core.conn()
    row = db.execute("SELECT folio, cxc_id FROM cotizaciones WHERE id=?", (cot_id,)).fetchone()
    if not row:
        flash("No encontrada", "danger")
    elif row["cxc_id"]:
        flash("No se puede eliminar: tiene CxC vinculada", "danger")
    else:
        db.execute("DELETE FROM cotizacion_items WHERE cotizacion_id=?", (cot_id,))
        db.execute("DELETE FROM cotizaciones WHERE id=?", (cot_id,))
        db.commit()
        flash(f"{row['folio']} eliminada", "ok")
    db.close()
    return redirect(url_for("cotizaciones_list"))


@app.route("/cotizaciones/<int:cot_id>/estado", methods=["POST"])
@login_required
def cotizaciones_estado(cot_id: int):
    estado = request.form.get("estado") or "borrador"
    db = core.conn()
    db.execute("UPDATE cotizaciones SET estado=? WHERE id=?", (estado, cot_id))
    cxc_doc = None
    if estado == "aprobada":
        cxc_doc = core.ensure_cxc_from_cotizacion(db, cot_id)
    db.commit()
    db.close()
    if cxc_doc:
        flash(f"Estado actualizado · CxC {cxc_doc} generada automáticamente", "ok")
    else:
        flash("Estado actualizado", "ok")
    return redirect(url_for("cotizaciones_detalle", cot_id=cot_id))


# ---------------------------------------------------------------------------
# Cuentas por cobrar
# ---------------------------------------------------------------------------
@app.route("/cuentas/")
@login_required
def cuentas_list():
    q = (request.args.get("q") or "").strip()
    db = core.conn()
    core.scrub_import_labels(db)
    core.sync_cuenta_cotizacion_links(db)
    sql = """
        SELECT cu.*, cl.razon_social AS cliente, cot.folio AS cot_folio
        FROM cuentas cu
        LEFT JOIN clientes cl ON cl.id=cu.cliente_id
        LEFT JOIN cotizaciones cot ON cot.id=cu.cotizacion_id
        WHERE 1=1
    """
    params: list = []
    if q:
        like = f"%{q}%"
        sql += """
            AND (cl.razon_social LIKE ? OR cu.documento LIKE ? OR cu.num_factura LIKE ?
                 OR cu.concepto LIKE ? OR cot.folio LIKE ?)
        """
        params.extend([like, like, like, like, like])
    sql += " ORDER BY date(cu.fecha_emision) DESC, cu.id DESC"
    # Recalcular saldos vs abonos antes de KPIs/tabla.
    for row in db.execute("SELECT id FROM cuentas").fetchall():
        core.recalc_cuenta(db, int(row["id"]))
    db.commit()

    rows = db.execute(sql, params).fetchall()
    docs = []
    for r in rows:
        d = dict(r)
        doc_disp, fac_disp = core.cuenta_doc_factura_display(d)
        d["doc_display"] = doc_disp
        d["factura_display"] = fac_disp
        docs.append(d)

    total_docs = len(docs)
    total_monto = sum(float(d["monto"] or 0) for d in docs)

    def _bucket(d: dict) -> str:
        """Clasifica por saldo/abonado real, no solo por texto de estado."""
        saldo = float(d.get("saldo") or 0)
        abonado = float(d.get("abonado") or 0)
        if saldo <= 0:
            return "pagado"
        if abonado > 0:
            return "abonado"
        return "pendiente"

    abon = [d for d in docs if _bucket(d) == "abonado"]
    pag = [d for d in docs if _bucket(d) == "pagado"]
    # Pendientes = cartera abierta real (todo documento con saldo > 0).
    abiertos = [d for d in docs if float(d.get("saldo") or 0) > 0]
    kpis = {
        "total_docs": total_docs,
        "total_monto": total_monto,
        "pend_n": len(abiertos),
        "pend_m": sum(float(d["saldo"] or 0) for d in abiertos),
        "abon_n": len(abon),
        "abon_m": sum(float(d["saldo"] or 0) for d in abon),
        "pag_n": len(pag),
        "pag_m": sum(float(d["monto"] or 0) for d in pag),
        "tasa": (len(pag) / total_docs * 100) if total_docs else 0,
        "sum_total": sum(float(d["monto"] or 0) for d in docs),
        "sum_abonos": sum(float(d["abonado"] or 0) for d in docs),
        "sum_saldo": sum(float(d["saldo"] or 0) for d in docs),
    }
    db.close()
    return render_template(
        "cuentas/lista.html",
        active="cuentas",
        rows=docs,
        kpis=kpis,
        q=q,
    )


def _load_vista360(db, cid: int | None):
    core.scrub_import_labels(db)
    core.sync_cuenta_cotizacion_links(db)
    cli = db.execute("SELECT * FROM clientes WHERE id=?", (cid,)).fetchone() if cid else None
    cuentas = []
    abonos = []
    cots = []
    deuda = 0.0
    if cid:
        rows = db.execute(
            """
            SELECT cu.*, cot.folio AS cot_folio
            FROM cuentas cu
            LEFT JOIN cotizaciones cot ON cot.id = cu.cotizacion_id
            WHERE cu.cliente_id=?
            ORDER BY cu.id DESC
            """,
            (cid,),
        ).fetchall()
        cuentas = []
        for r in rows:
            d = dict(r)
            doc_disp, fac_disp = core.cuenta_doc_factura_display(d)
            d["doc_display"] = doc_disp
            d["factura_display"] = fac_disp
            cuentas.append(d)
        deuda = sum(float(x["saldo"] or 0) for x in cuentas)
        abono_rows = db.execute(
            """
            SELECT a.fecha, a.monto, a.medio, a.nota,
                   cu.documento, cu.num_factura, cu.cotizacion_id,
                   cot.folio AS cot_folio
            FROM abonos a
            JOIN cuentas cu ON cu.id=a.cuenta_id
            LEFT JOIN cotizaciones cot ON cot.id = cu.cotizacion_id
            WHERE cu.cliente_id=?
            ORDER BY date(a.fecha) DESC, a.id DESC
            """,
            (cid,),
        ).fetchall()
        abonos = []
        for r in abono_rows:
            d = dict(r)
            doc_disp, _fac = core.cuenta_doc_factura_display(d)
            d["documento"] = doc_disp
            abonos.append(d)
        cots = db.execute(
            """
            SELECT id, folio, fecha, estado, total,
                   COALESCE(titulo, asunto, proyecto,'') AS titulo
            FROM cotizaciones
            WHERE cliente_id=?
            ORDER BY COALESCE(fecha,'') DESC, id DESC
            """,
            (cid,),
        ).fetchall()
    return cli, cuentas, abonos, cots, deuda


@app.route("/cuentas/360")
@login_required
def cuentas_360():
    db = core.conn()
    clientes = db.execute(
        "SELECT id, razon_social FROM clientes WHERE activo=1 ORDER BY razon_social"
    ).fetchall()
    cid = request.args.get("cliente_id", type=int)
    if not cid and clientes:
        cid = clientes[0]["id"]
    cli, cuentas, abonos, cots, deuda = _load_vista360(db, cid)
    sum_abonos = sum(float(a["monto"] or 0) for a in abonos)
    db.close()
    return render_template(
        "cuentas/vista360.html",
        active="cuentas",
        clientes=clientes,
        cid=cid,
        cli=cli,
        cuentas=cuentas,
        abonos=abonos,
        sum_abonos=sum_abonos,
        cots=cots,
        deuda=deuda,
    )


@app.route("/cuentas/360/pdf")
@login_required
def cuentas_360_pdf():
    cid = request.args.get("cliente_id", type=int)
    db = core.conn()
    if not cid:
        flash("Selecciona un cliente", "danger")
        db.close()
        return redirect(url_for("cuentas_360"))
    cli, cuentas, abonos, cots, deuda = _load_vista360(db, cid)
    empresa = db.execute("SELECT * FROM empresa WHERE id=1").fetchone()
    db.close()
    if not cli:
        flash("Cliente no encontrado", "danger")
        return redirect(url_for("cuentas_360"))
    pdf = core.estado_cuenta_pdf_bytes(cli, cuentas, abonos, cots, deuda, empresa)
    safe = "".join(ch if ch.isalnum() else "_" for ch in (cli["razon_social"] or "cliente"))[:40]
    return send_file(
        BytesIO(pdf),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"estado_cuenta_{safe}.pdf",
    )


@app.route("/cuentas/nueva", methods=["GET", "POST"])
@app.route("/cuentas/<int:cuenta_id>/editar", methods=["GET", "POST"])
@login_required
def cuentas_form(cuenta_id: int | None = None):
    db = core.conn()
    clientes = db.execute(
        "SELECT id, razon_social FROM clientes WHERE activo=1 ORDER BY razon_social"
    ).fetchall()
    dias = int(core.param(db, "dias_credito", 30))
    edit = db.execute("SELECT * FROM cuentas WHERE id=?", (cuenta_id,)).fetchone() if cuenta_id else None
    if cuenta_id and not edit:
        flash("Documento no encontrado", "danger")
        db.close()
        return redirect(url_for("cuentas_list"))

    if request.method == "POST":
        cliente_id = int(request.form["cliente_id"])
        tipo = request.form.get("tipo_doc") or "EP"
        concepto = (request.form.get("concepto") or "").strip() or None
        monto = float(request.form.get("monto") or 0)
        emision = request.form.get("fecha_emision") or date.today().isoformat()
        venc = request.form.get("fecha_vencimiento") or (date.today() + timedelta(days=dias)).isoformat()
        facturado = 1 if request.form.get("facturado") else 0
        num_factura = (request.form.get("num_factura") or "").strip() or None
        if facturado and not num_factura:
            flash("Ingresa el número de factura", "danger")
        else:
            if facturado or num_factura:
                facturado = 1
            if facturado and tipo == "EP":
                tipo = "FAC"
            if edit:
                db.execute(
                    """
                    UPDATE cuentas SET cliente_id=?, tipo_doc=?, concepto=?, fecha_emision=?,
                      fecha_vencimiento=?, monto=?, facturado=?, num_factura=?
                    WHERE id=?
                    """,
                    (cliente_id, tipo, concepto, emision, venc, monto, facturado, num_factura, edit["id"]),
                )
                core.recalc_cuenta(db, edit["id"])
                db.commit()
                flash("Documento actualizado", "ok")
                db.close()
                return redirect(url_for("cuentas_detalle", cuenta_id=edit["id"]))
            else:
                doc = core.next_code(db, "cuentas", "documento", tipo if tipo in ("EP", "FAC", "ND") else "EP")
                cur = db.cursor()
                cur.execute(
                    """
                    INSERT INTO cuentas
                    (documento, cliente_id, tipo_doc, concepto, fecha_emision, fecha_vencimiento,
                     monto, abonado, saldo, estado, facturado, num_factura)
                    VALUES (?,?,?,?,?,?,?,0,?, 'pendiente', ?, ?)
                    """,
                    (doc, cliente_id, tipo, concepto, emision, venc, monto, monto, facturado, num_factura),
                )
                new_id = cur.lastrowid
                db.commit()
                flash(f"Documento {doc} creado", "ok")
                db.close()
                return redirect(url_for("cuentas_detalle", cuenta_id=new_id))

    db.close()
    return render_template(
        "cuentas/form.html",
        active="cuentas",
        edit=edit,
        clientes=clientes,
        dias=dias,
        today=date.today().isoformat(),
        vence_default=(date.today() + timedelta(days=dias)).isoformat(),
    )


@app.route("/cuentas/<int:cuenta_id>")
@login_required
def cuentas_detalle(cuenta_id: int):
    db = core.conn()
    cuenta = db.execute(
        """
        SELECT cu.*, cl.razon_social, cl.rut AS cliente_rut FROM cuentas cu
        LEFT JOIN clientes cl ON cl.id=cu.cliente_id WHERE cu.id=?
        """,
        (cuenta_id,),
    ).fetchone()
    if not cuenta:
        flash("No encontrado", "danger")
        db.close()
        return redirect(url_for("cuentas_list"))
    abonos = db.execute(
        "SELECT * FROM abonos WHERE cuenta_id=? ORDER BY id DESC", (cuenta_id,)
    ).fetchall()
    db.close()
    return render_template(
        "cuentas/detalle.html",
        active="cuentas",
        cuenta=cuenta,
        abonos=abonos,
    )


@app.route("/cuentas/<int:cuenta_id>/pdf")
@login_required
def cuentas_pdf(cuenta_id: int):
    db = core.conn()
    cuenta = db.execute(
        """
        SELECT cu.*, cl.razon_social, cl.rut AS cliente_rut,
               COALESCE(cu.tipo_doc, '') AS tipo
        FROM cuentas cu
        LEFT JOIN clientes cl ON cl.id=cu.cliente_id
        WHERE cu.id=?
        """,
        (cuenta_id,),
    ).fetchone()
    if not cuenta:
        db.close()
        flash("Documento no encontrado", "danger")
        return redirect(url_for("cuentas_list"))
    abonos = db.execute(
        "SELECT fecha, monto, medio, nota FROM abonos WHERE cuenta_id=? ORDER BY id",
        (cuenta_id,),
    ).fetchall()
    empresa = db.execute("SELECT * FROM empresa WHERE id=1").fetchone()
    db.close()
    pdf = core.cuenta_pdf_bytes(cuenta, abonos, empresa)
    return send_file(
        BytesIO(pdf),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{cuenta['documento']}.pdf",
    )


@app.route("/cuentas/<int:cuenta_id>/abono", methods=["GET", "POST"])
@login_required
def cuentas_abono(cuenta_id: int):
    db = core.conn()
    core.scrub_import_labels(db)
    core.sync_cuenta_cotizacion_links(db)
    cuenta = db.execute(
        """
        SELECT cu.*, cl.razon_social, cot.folio AS cot_folio
        FROM cuentas cu
        LEFT JOIN clientes cl ON cl.id=cu.cliente_id
        LEFT JOIN cotizaciones cot ON cot.id=cu.cotizacion_id
        WHERE cu.id=?
        """,
        (cuenta_id,),
    ).fetchone()
    if not cuenta:
        flash("No encontrado", "danger")
        db.close()
        return redirect(url_for("cuentas_list"))
    if float(cuenta["saldo"] or 0) <= 0:
        flash("Documento ya pagado", "ok")
        db.close()
        return redirect(url_for("cuentas_detalle", cuenta_id=cuenta_id))

    medios = [
        ("Transferencia", "Transferencia"),
        ("Cheque", "Cheque"),
        ("Efectivo", "Efectivo"),
        ("Tarjeta", "Tarjeta"),
        ("Otro", "Otro"),
    ]
    saldo = float(cuenta["saldo"] or 0)
    monto_total = float(cuenta["monto"] or 0)
    abonado = float(cuenta["abonado"] or 0)

    if request.method == "POST":
        monto = float(request.form.get("monto") or 0)
        medio = (request.form.get("medio") or "Transferencia").strip() or "Transferencia"
        nota = (request.form.get("nota") or "").strip() or None
        fecha = (request.form.get("fecha") or "").strip() or date.today().isoformat()
        if monto <= 0 or monto > saldo + 0.001:
            flash("Monto inválido: debe ser mayor a 0 y no superar el saldo", "danger")
        else:
            db.execute(
                "INSERT INTO abonos (cuenta_id, fecha, monto, medio, nota) VALUES (?,?,?,?,?)",
                (cuenta_id, fecha, monto, medio, nota),
            )
            core.recalc_cuenta(db, cuenta_id)
            db.commit()
            nuevo = db.execute("SELECT saldo FROM cuentas WHERE id=?", (cuenta_id,)).fetchone()
            if nuevo and float(nuevo["saldo"] or 0) <= 0:
                flash(f"Pago de {core.clp(monto)} registrado. Documento pagado.", "ok")
            else:
                flash(f"Abono de {core.clp(monto)} registrado correctamente.", "ok")
            db.close()
            return redirect(url_for("cuentas_detalle", cuenta_id=cuenta_id))

    abonos = db.execute(
        "SELECT fecha, monto, medio, nota FROM abonos WHERE cuenta_id=? ORDER BY id DESC",
        (cuenta_id,),
    ).fetchall()
    doc_disp, fac_disp = core.cuenta_doc_factura_display(dict(cuenta))
    pct = (abonado / monto_total * 100.0) if monto_total > 0 else 0.0
    saldo_int = int(round(saldo))
    db.close()
    return render_template(
        "cuentas/abono.html",
        active="cuentas",
        cuenta=cuenta,
        abonos=abonos,
        doc_display=doc_disp,
        factura_display=fac_disp,
        medios=medios,
        today=date.today().isoformat(),
        saldo_int=saldo_int,
        mitad=int(round(saldo / 2)),
        cuarto=int(round(saldo / 4)),
        pct_pagado=min(100.0, max(0.0, pct)),
    )


@app.route("/cuentas/<int:cuenta_id>/borrar", methods=["POST"])
@login_required
def cuentas_borrar(cuenta_id: int):
    db = core.conn()
    db.execute("UPDATE cotizaciones SET cxc_id=NULL WHERE cxc_id=?", (cuenta_id,))
    db.execute("DELETE FROM abonos WHERE cuenta_id=?", (cuenta_id,))
    db.execute("DELETE FROM cuentas WHERE id=?", (cuenta_id,))
    db.commit()
    db.close()
    flash("Documento eliminado", "ok")
    return redirect(url_for("cuentas_list"))


# ---------------------------------------------------------------------------
# Administración (empresa, parámetros, usuarios/claves)
# ---------------------------------------------------------------------------
def _is_admin() -> bool:
    return (session.get("auth_tipo") or "") == "Administrador"


def _admin_redirect(tab: str = "empresa"):
    return redirect(url_for("admin", tab=tab))


@app.route("/admin/")
@login_required
def admin():
    tab = request.args.get("tab") or "empresa"
    if tab not in ("empresa", "parametros", "usuarios"):
        tab = "empresa"
    edit_id = request.args.get("edit", type=int)
    db = core.conn()
    empresa = db.execute("SELECT * FROM empresa WHERE id=1").fetchone()
    params = db.execute(
        """
        SELECT clave, nombre, valor, unidad FROM parametros
        WHERE clave != 'auth_seed'
        ORDER BY nombre
        """
    ).fetchall()
    usuarios = db.execute(
        """
        SELECT id, usuario, COALESCE(nombre,'') AS nombre,
               COALESCE(tipo,'Administrador') AS tipo, activo
        FROM usuarios
        ORDER BY tipo, usuario
        """
    ).fetchall()
    edit_user = None
    if edit_id:
        edit_user = db.execute(
            "SELECT id, usuario, nombre, tipo, activo FROM usuarios WHERE id=?",
            (edit_id,),
        ).fetchone()
    db.close()
    return render_template(
        "admin.html",
        active="admin",
        tab=tab,
        empresa=empresa,
        params=params,
        usuarios=usuarios,
        edit_user=edit_user,
        tipos_usuario=core.TIPOS_USUARIO,
        is_admin=_is_admin(),
    )


@app.route("/admin/empresa", methods=["POST"])
@login_required
def admin_empresa():
    db = core.conn()
    db.execute(
        """
        UPDATE empresa SET rut=?, razon_social=?, telefono=?, email=?, direccion=?, region=?, pais=?
        WHERE id=1
        """,
        (
            request.form.get("rut"),
            request.form.get("razon_social"),
            request.form.get("telefono"),
            request.form.get("email"),
            request.form.get("direccion"),
            request.form.get("region"),
            request.form.get("pais") or "Chile",
        ),
    )
    db.commit()
    db.close()
    flash("Empresa actualizada", "ok")
    return _admin_redirect("empresa")


@app.route("/admin/parametro", methods=["POST"])
@login_required
def admin_parametro():
    clave = (request.form.get("clave") or "").strip()
    valor = (request.form.get("valor") or "").strip()
    if not clave or clave == "auth_seed":
        flash("Parámetro no válido", "danger")
        return _admin_redirect("parametros")
    db = core.conn()
    db.execute("UPDATE parametros SET valor=? WHERE clave=?", (valor, clave))
    db.commit()
    db.close()
    flash("Parámetro actualizado", "ok")
    return _admin_redirect("parametros")


@app.route("/admin/clave", methods=["POST"])
@login_required
def admin_clave():
    actual = request.form.get("clave_actual") or ""
    nueva = (request.form.get("clave_nueva") or "").strip()
    nueva2 = (request.form.get("clave_nueva2") or "").strip()
    auth_user = session.get("auth_user") or ""
    if not core.get_user_if_valid(auth_user, actual):
        flash("La clave actual no es correcta", "danger")
    elif len(nueva) < 4:
        flash("La nueva clave debe tener al menos 4 caracteres", "danger")
    elif nueva != nueva2:
        flash("Las claves nuevas no coinciden", "danger")
    else:
        salt, digest = core.hash_password(nueva)
        db = core.conn()
        db.execute(
            "UPDATE usuarios SET salt=?, clave_hash=? WHERE lower(usuario)=lower(?)",
            (salt, digest, auth_user),
        )
        db.commit()
        db.close()
        flash("Clave actualizada", "ok")
    return _admin_redirect("usuarios")


@app.route("/admin/usuarios/nuevo", methods=["POST"])
@login_required
def admin_usuario_nuevo():
    if not _is_admin():
        flash("Solo un Administrador puede crear usuarios", "danger")
        return _admin_redirect("usuarios")
    u_nuevo = (request.form.get("usuario") or "").strip()
    n_nuevo = (request.form.get("nombre") or "").strip()
    t_nuevo = request.form.get("tipo") or "Consulta"
    c_nuevo = (request.form.get("clave") or "").strip()
    c_nuevo2 = (request.form.get("clave2") or "").strip()
    if t_nuevo not in core.TIPOS_USUARIO:
        t_nuevo = "Consulta"
    if not u_nuevo:
        flash("Ingrese un usuario", "danger")
    elif len(c_nuevo) < 4:
        flash("La clave debe tener al menos 4 caracteres", "danger")
    elif c_nuevo != c_nuevo2:
        flash("Las claves no coinciden", "danger")
    else:
        try:
            salt, digest = core.hash_password(c_nuevo)
            db = core.conn()
            db.execute(
                """
                INSERT INTO usuarios (usuario, salt, clave_hash, nombre, tipo, activo)
                VALUES (?,?,?,?,?,1)
                """,
                (u_nuevo, salt, digest, n_nuevo or None, t_nuevo),
            )
            db.commit()
            db.close()
            flash(f"Usuario {u_nuevo} creado", "ok")
        except Exception:
            flash("Ese usuario ya existe", "danger")
    return _admin_redirect("usuarios")


@app.route("/admin/usuarios/<int:uid>", methods=["POST"])
@login_required
def admin_usuario_editar(uid: int):
    if not _is_admin():
        flash("Solo un Administrador puede editar usuarios", "danger")
        return _admin_redirect("usuarios")
    n_edit = (request.form.get("nombre") or "").strip()
    t_edit = request.form.get("tipo") or "Consulta"
    activo_edit = 1 if request.form.get("activo") == "1" else 0
    reset_clave = (request.form.get("clave") or "").strip()
    reset_clave2 = (request.form.get("clave2") or "").strip()
    if t_edit not in core.TIPOS_USUARIO:
        t_edit = "Consulta"
    db = core.conn()
    row = db.execute(
        "SELECT id, usuario FROM usuarios WHERE id=?", (uid,)
    ).fetchone()
    if not row:
        db.close()
        flash("Usuario no encontrado", "danger")
        return _admin_redirect("usuarios")
    auth_user = session.get("auth_user") or ""
    if row["usuario"] == auth_user and not activo_edit:
        db.close()
        flash("No puedes desactivarte a ti mismo", "danger")
        return redirect(url_for("admin", tab="usuarios", edit=uid))
    if reset_clave and len(reset_clave) < 4:
        db.close()
        flash("La nueva clave debe tener al menos 4 caracteres", "danger")
        return redirect(url_for("admin", tab="usuarios", edit=uid))
    if reset_clave and reset_clave != reset_clave2:
        db.close()
        flash("Las claves nuevas no coinciden", "danger")
        return redirect(url_for("admin", tab="usuarios", edit=uid))
    db.execute(
        "UPDATE usuarios SET nombre=?, tipo=?, activo=? WHERE id=?",
        (n_edit or None, t_edit, activo_edit, uid),
    )
    if reset_clave:
        salt, digest = core.hash_password(reset_clave)
        db.execute(
            "UPDATE usuarios SET salt=?, clave_hash=? WHERE id=?",
            (salt, digest, uid),
        )
    db.commit()
    db.close()
    if row["usuario"] == auth_user:
        session["auth_tipo"] = t_edit
        session["auth_nombre"] = n_edit or auth_user
    flash("Usuario actualizado", "ok")
    return _admin_redirect("usuarios")


def create_app():
    core.init_db()
    return app


if __name__ == "__main__":
    core.init_db()
    port = int(os.getenv("PORT", "8505"))
    app.run(host="0.0.0.0", port=port, debug=True)
