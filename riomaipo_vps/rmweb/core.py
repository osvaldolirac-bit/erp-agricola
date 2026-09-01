"""Núcleo Río Maipo Web: SQLite, auth, formatos y PDF (misma BD que Streamlit)."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore


def ahora_chile():
    """Datetime actual en Chile (evitar date.today() UTC del servidor)."""
    if ZoneInfo is not None:
        return datetime.now(ZoneInfo("America/Santiago"))
    return datetime.utcnow() - timedelta(hours=4)


def hoy_chile():
    """Fecha de hoy en Chile."""
    return ahora_chile().date()

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
import os

_DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "riomaipo_erp.db"
DB_PATH = Path(os.getenv("RIOMAIPO_DB", str(_DEFAULT_DB)))  # compat / fallback
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_db_path() -> Path:
    """DB del tenant activo (sesión) o fallback RIOMAIPO_DB."""
    try:
        from flask import g, has_request_context, session

        if has_request_context():
            slug = getattr(g, "tenant_slug", None) or session.get("tenant_slug")
            if slug:
                from rmweb.tenants import get_tenant

                ten = get_tenant(slug)
                if ten and ten.get("db"):
                    path = Path(ten["db"])
                    path.parent.mkdir(parents=True, exist_ok=True)
                    return path
    except Exception:
        pass
    path = Path(os.getenv("RIOMAIPO_DB", str(_DEFAULT_DB)))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path

STATIC_DIR = BASE_DIR / "static"
# Logos pueden estar en /static del proyecto o en rmweb/static
LOGO_RIOMAIPO = next(
    (
        p
        for p in (
            STATIC_DIR / "logo_riomaipo.png",
            Path(__file__).resolve().parent / "static" / "logo_riomaipo.png",
        )
        if p.exists()
    ),
    STATIC_DIR / "logo_riomaipo.png",
)
LOGO_ERP = next(
    (
        p
        for p in (
            STATIC_DIR / "logo_erpmaster.png",
            Path(__file__).resolve().parent / "static" / "logo_erpmaster.png",
        )
        if p.exists()
    ),
    STATIC_DIR / "logo_erpmaster.png",
)


def _tenant_slug_actual() -> str:
    try:
        from flask import g, has_request_context, session

        if has_request_context():
            return (
                getattr(g, "tenant_slug", None)
                or session.get("tenant_slug")
                or ""
            ).strip().lower()
    except Exception:
        pass
    return ""


def logo_para_pdf() -> Path:
    """Río Maipo usa su logo; DEMO/LC Comercial usan ERP Master."""
    slug = _tenant_slug_actual()
    if slug in {"comercial-demo", "comercial-lc"}:
        return LOGO_ERP if LOGO_ERP.exists() else LOGO_RIOMAIPO
    return LOGO_RIOMAIPO if LOGO_RIOMAIPO.exists() else LOGO_ERP


def marca_pdf_fallback() -> tuple[str, str]:
    """(titulo, subtitulo) si no hay archivo de logo."""
    slug = _tenant_slug_actual()
    if slug == "comercial-demo":
        return "ERP MASTER", "Comercial DEMO"
    if slug == "comercial-lc":
        return "ERP MASTER", "Comercial LC"
    return "RIO MAIPO", "Constructora"


def pie_marca_pdf() -> str:
    slug = _tenant_slug_actual()
    if slug == "comercial-demo":
        return "ERP Master Comercial DEMO"
    if slug == "comercial-lc":
        return "ERP Master Comercial LC"
    return "ERP Master Río Maipo"


def _pdf_sello_demo_prueba(pdf, x: float, y: float, w: float, h: float) -> None:
    """Sello diagonal DEMO PRUEBA sobre la zona de productos/tablas (solo DEMO)."""
    if _tenant_slug_actual() != "comercial-demo":
        return
    if w <= 0 or h <= 0:
        return
    cx = x + w / 2.0
    cy = y + max(h, 28.0) / 2.0
    try:
        pdf.set_text_color(200, 120, 120)
        size = 44 if w >= 180 else 32
        pdf.set_font("Helvetica", "B", size)
        pdf.rotate(28, cx, cy)
        label = "DEMO PRUEBA"
        tw = pdf.get_string_width(label)
        pdf.text(cx - tw / 2.0, cy + 2.0, label)
        pdf.rotate(0)
    finally:
        try:
            pdf.set_text_color(26, 43, 60)
        except Exception:
            pass



DEFAULT_ACCESO = "osvaldolira@constructorariomaipo.cl"
DEFAULT_CLAVE = "9083"
TIPOS_USUARIO = ["Administrador", "Operador", "Consulta"]
COT_PDF_ROWS = 24

try:
    from fpdf import FPDF
except ImportError:  # pragma: no cover
    FPDF = None


def conn(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, check_same_thread=False, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("PRAGMA busy_timeout = 30000")
    try:
        c.execute("PRAGMA journal_mode = WAL")
    except Exception:
        pass
    return c


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000
    ).hex()
    return salt, digest


def verify_password(password: str, salt: str, digest: str) -> bool:
    check = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000
    ).hex()
    return hmac.compare_digest(check, digest)


def _ensure_columns(c: sqlite3.Connection, table: str, columns: list[tuple[str, str]]) -> None:
    cols = {r["name"] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, decl in columns:
        if name not in cols:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def init_db(db_path: str | Path | None = None, empresa_default: dict | None = None) -> None:
    c = conn(db_path)
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS empresa (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            rut TEXT, razon_social TEXT, telefono TEXT, email TEXT,
            direccion TEXT, region TEXT, pais TEXT DEFAULT 'Chile'
        );
        CREATE TABLE IF NOT EXISTS parametros (
            clave TEXT PRIMARY KEY, nombre TEXT, valor TEXT, unidad TEXT
        );
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rut TEXT UNIQUE, razon_social TEXT NOT NULL,
            contacto TEXT, telefono TEXT, email TEXT,
            direccion TEXT, comuna TEXT, activo INTEGER DEFAULT 1, creado_en TEXT
        );
        CREATE TABLE IF NOT EXISTS productos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT UNIQUE, nombre TEXT NOT NULL,
            unidad TEXT DEFAULT 'un', precio REAL DEFAULT 0, activo INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS cotizaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folio TEXT UNIQUE, cliente_id INTEGER,
            asunto TEXT, proyecto TEXT, estado TEXT DEFAULT 'borrador',
            fecha TEXT, validez_dias INTEGER DEFAULT 30,
            version TEXT DEFAULT '1', titulo TEXT,
            gg_pct REAL DEFAULT 5, utilidad_pct REAL DEFAULT 15,
            gg_monto REAL DEFAULT 0, utilidad_monto REAL DEFAULT 0, valor_neto REAL DEFAULT 0,
            subtotal REAL DEFAULT 0, iva REAL DEFAULT 0, total REAL DEFAULT 0,
            notas TEXT, cxc_id INTEGER,
            FOREIGN KEY(cliente_id) REFERENCES clientes(id)
        );
        CREATE TABLE IF NOT EXISTS cotizacion_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cotizacion_id INTEGER NOT NULL,
            producto_id INTEGER, descripcion TEXT NOT NULL,
            obs TEXT, orden INTEGER DEFAULT 0,
            unidad TEXT DEFAULT 'un', cantidad REAL DEFAULT 1,
            precio_unitario REAL DEFAULT 0, total REAL DEFAULT 0,
            FOREIGN KEY(cotizacion_id) REFERENCES cotizaciones(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS cuentas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            documento TEXT UNIQUE, cliente_id INTEGER,
            cotizacion_id INTEGER, tipo_doc TEXT DEFAULT 'EP',
            concepto TEXT, fecha_emision TEXT, fecha_vencimiento TEXT,
            monto REAL DEFAULT 0, abonado REAL DEFAULT 0, saldo REAL DEFAULT 0,
            estado TEXT DEFAULT 'pendiente',
            facturado INTEGER DEFAULT 0, num_factura TEXT,
            FOREIGN KEY(cliente_id) REFERENCES clientes(id)
        );
        CREATE TABLE IF NOT EXISTS abonos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cuenta_id INTEGER NOT NULL, fecha TEXT, monto REAL,
            medio TEXT, nota TEXT,
            FOREIGN KEY(cuenta_id) REFERENCES cuentas(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT UNIQUE NOT NULL,
            salt TEXT NOT NULL, clave_hash TEXT NOT NULL,
            nombre TEXT, tipo TEXT NOT NULL DEFAULT 'Administrador',
            activo INTEGER DEFAULT 1
        );
        """
    )
    _ensure_columns(c, "usuarios", [("tipo", "TEXT NOT NULL DEFAULT 'Administrador'")])
    _ensure_columns(
        c,
        "usuarios",
        [
            ("fecha_expira", "TEXT"),
            ("invitado_por", "TEXT"),
            ("tenant_slug", "TEXT"),
            ("alerta_24h_enviada", "INTEGER DEFAULT 0"),
            ("alerta_vencido_enviada", "INTEGER DEFAULT 0"),
        ],
    )
    _ensure_columns(
        c,
        "cotizaciones",
        [
            ("version", "TEXT DEFAULT '1'"),
            ("titulo", "TEXT"),
            ("gg_pct", "REAL DEFAULT 5"),
            ("utilidad_pct", "REAL DEFAULT 15"),
            ("gg_monto", "REAL DEFAULT 0"),
            ("utilidad_monto", "REAL DEFAULT 0"),
            ("valor_neto", "REAL DEFAULT 0"),
        ],
    )
    _ensure_columns(c, "cotizacion_items", [("obs", "TEXT"), ("orden", "INTEGER DEFAULT 0")])
    _ensure_columns(c, "cuentas", [("facturado", "INTEGER DEFAULT 0"), ("num_factura", "TEXT")])
    # Soporte (misma tabla que agrícola / Super Consola)
    try:
        import sys as _sys, os as _os
        for _root in ("/root", "/root/demo-web"):
            if _root not in _sys.path and _os.path.isdir(_root):
                _sys.path.insert(0, _root)  # demo-web primero
        from erp_soporte import migrar_tickets_soporte  # noqa: WPS433
        migrar_tickets_soporte(c)
    except Exception:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets_soporte (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo_ticket TEXT,
                usuario TEXT,
                descripcion TEXT,
                status TEXT,
                erp_origen TEXT,
                fecha_creacion TEXT,
                fecha_actualizacion TEXT,
                leido_admin INTEGER NOT NULL DEFAULT 0,
                respuesta_admin TEXT,
                fecha_respuesta TEXT
            )
            """
        )
    scrub_import_labels(c)
    sync_cuenta_cotizacion_links(c)
    from rmweb import ops as _ops  # noqa: WPS433
    _ops.ensure_ops_schema(c)
    # Marca catálogo: SRV* = servicio (sin stock)
    try:
        c.execute("UPDATE productos SET es_servicio=1 WHERE upper(codigo) LIKE 'SRV%' OR upper(nombre) LIKE '%SERVICIO%' OR upper(nombre) LIKE '%MANO DE OBRA%' OR upper(nombre) LIKE '%SUPERVISOR%' OR upper(nombre) LIKE '%INSTALACI%' OR upper(nombre) LIKE '%PINTURA%'")
        c.execute("UPDATE productos SET maneja_stock=1 WHERE COALESCE(es_servicio,0)=0")
    except Exception:
        pass

    if c.execute("SELECT COUNT(*) FROM empresa").fetchone()[0] == 0:
        emp = empresa_default or {
            "rut": "76.073.876-K",
            "razon_social": "Constructora Rio Maipo S.A.",
            "telefono": "56990798992",
            "email": "osvaldolira@constructorariomaipo.cl",
            "direccion": "Parcela El Sauce lote 4, Paine",
            "region": "Metropolitana",
            "pais": "Chile",
        }
        c.execute(
            """
            INSERT INTO empresa (id, rut, razon_social, telefono, email, direccion, region, pais)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                emp.get("rut") or "",
                emp.get("razon_social") or "Empresa",
                emp.get("telefono") or "",
                emp.get("email") or "",
                emp.get("direccion") or "",
                emp.get("region") or "",
                emp.get("pais") or "Chile",
            ),
        )
    for clave, nombre, valor, unidad in [
        ("iva", "IVA", "19", "%"),
        ("validez_cotizacion", "Validez cotización", "30", "días"),
        ("gg_pct", "Gastos generales", "5", "%"),
        ("utilidad_pct", "Utilidad", "15", "%"),
        ("dias_credito", "Días crédito CxC", "30", "días"),
    ]:
        c.execute(
            """
            INSERT INTO parametros (clave, nombre, valor, unidad) VALUES (?,?,?,?)
            ON CONFLICT(clave) DO NOTHING
            """,
            (clave, nombre, valor, unidad),
        )

    # Usuario por defecto
    salt, digest = hash_password(DEFAULT_CLAVE)
    row = c.execute(
        "SELECT id FROM usuarios WHERE lower(usuario)=lower(?)", (DEFAULT_ACCESO,)
    ).fetchone()
    if not row:
        c.execute(
            """
            INSERT INTO usuarios (usuario, salt, clave_hash, nombre, tipo, activo)
            VALUES (?,?,?,?,?,1)
            """,
            (DEFAULT_ACCESO, salt, digest, "Osvaldo Lira", "Administrador"),
        )
    c.commit()
    c.close()


def clp_round(v) -> float:
    """Redondea a peso chileno entero (sin centavos)."""
    try:
        return float(int(round(float(v or 0))))
    except (TypeError, ValueError):
        return 0.0


def clp(v) -> str:
    try:
        return f"${int(round(float(v or 0))):,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return "$0"


def fmt_dmy(s) -> str:
    if not s:
        return "—"
    try:
        return date.fromisoformat(str(s)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return str(s)


def param(c: sqlite3.Connection, clave: str, default: float = 0.0) -> float:
    row = c.execute("SELECT valor FROM parametros WHERE clave=?", (clave,)).fetchone()
    if not row:
        return default
    try:
        return float(row["valor"])
    except ValueError:
        return default


def next_code(c: sqlite3.Connection, table: str, field: str, prefix: str) -> str:
    """Siguiente correlativo PREFIX-NNNN según el máximo existente (no COUNT)."""
    start = len(prefix) + 2  # tras «COT-»
    row = c.execute(
        f"""
        SELECT MAX(CAST(substr({field}, ?) AS INTEGER)) AS m
        FROM {table}
        WHERE {field} LIKE ?
        """,
        (start, f"{prefix}-%"),
    ).fetchone()
    n = int(row["m"] or 0) + 1
    return f"{prefix}-{n:04d}"


def next_cotizacion_folio(c: sqlite3.Connection) -> str:
    """Correlativo COT-NNNN en secuencia operativa (<1000).

    Ignora folios legado COT-1000+ (migración Streamlit) para no saltar a 1019
    cuando la secuencia real va COT-0020, COT-0021, …
    """
    row = c.execute(
        """
        SELECT MAX(CAST(substr(folio, 5) AS INTEGER)) AS m
        FROM cotizaciones
        WHERE folio LIKE 'COT-%'
          AND CAST(substr(folio, 5) AS INTEGER) < 1000
        """
    ).fetchone()
    n = int(row["m"] or 0) + 1
    return f"COT-{n:04d}"


def list_accesos(db_path: str | Path | None = None) -> list[str]:
    c = conn(db_path)
    rows = c.execute(
        """
        SELECT usuario FROM usuarios
        WHERE activo=1
        ORDER BY CASE WHEN lower(usuario)=lower(?) THEN 0 ELSE 1 END, usuario
        """,
        (DEFAULT_ACCESO,),
    ).fetchall()
    c.close()
    users = [r["usuario"] for r in rows]
    if DEFAULT_ACCESO not in users:
        users.insert(0, DEFAULT_ACCESO)
    return users


def get_user_if_valid(usuario: str, clave: str, db_path: str | Path | None = None):
    c = conn(db_path)
    row = c.execute(
        """
        SELECT id, usuario, salt, clave_hash, nombre, tipo, activo,
               fecha_expira, invitado_por, tenant_slug
        FROM usuarios WHERE lower(usuario)=lower(?) AND activo=1
        """,
        (usuario.strip(),),
    ).fetchone()
    c.close()
    if not row:
        return None
    if not verify_password(clave, row["salt"], row["clave_hash"]):
        return None
    return dict(row)


def get_user_by_email(usuario: str, db_path: str | Path | None = None):
    c = conn(db_path)
    row = c.execute(
        """
        SELECT id, usuario, salt, clave_hash, nombre, tipo, activo,
               fecha_expira, invitado_por, tenant_slug
        FROM usuarios WHERE lower(usuario)=lower(?) AND activo=1
        """,
        ((usuario or "").strip(),),
    ).fetchone()
    c.close()
    return dict(row) if row else None


def ensure_cxc_from_cotizacion(c: sqlite3.Connection, cot_id: int) -> str | None:
    """
    Si la cotización está aprobada y aún no tiene CxC, crea el documento.
    Retorna el código del documento creado, o None si no correspondía crear.
    """
    cot = c.execute(
        """
        SELECT id, folio, cliente_id, estado, total, cxc_id, asunto, titulo, proyecto
        FROM cotizaciones WHERE id=?
        """,
        (cot_id,),
    ).fetchone()
    if not cot:
        return None
    if (cot["estado"] or "") != "aprobada":
        return None
    if cot["cxc_id"]:
        return None
    if not cot["cliente_id"]:
        return None

    dias = int(param(c, "dias_credito", 30))
    doc = next_code(c, "cuentas", "documento", "EP")
    concepto = f"Desde cotización {cot['folio']}"
    titulo = (cot["titulo"] or cot["asunto"] or cot["proyecto"] or "").strip()
    if titulo:
        concepto = f"{concepto} · {titulo[:80]}"
    monto = float(cot["total"] or 0)
    cur = c.cursor()
    cur.execute(
        """
        INSERT INTO cuentas
        (documento, cliente_id, cotizacion_id, tipo_doc, concepto,
         fecha_emision, fecha_vencimiento, monto, abonado, saldo, estado, facturado)
        VALUES (?,?,?,?,?,?,?,?,0,?, 'pendiente', 0)
        """,
        (
            doc,
            cot["cliente_id"],
            cot["id"],
            "EP",
            concepto,
            hoy_chile().isoformat(),
            (hoy_chile() + timedelta(days=dias)).isoformat(),
            monto,
            monto,
        ),
    )
    cxc_id = cur.lastrowid
    cur.execute("UPDATE cotizaciones SET cxc_id=? WHERE id=?", (cxc_id, cot["id"]))
    return doc


def calc_cotizacion_totales(subtotal: float, gg_pct: float, utilidad_pct: float, iva_pct: float) -> dict:
    sub = float(subtotal or 0)
    gg = int(round(sub * float(gg_pct or 0) / 100.0))
    util = int(round(sub * float(utilidad_pct or 0) / 100.0))
    neto = int(round(sub + gg + util))
    iva = int(round(neto * float(iva_pct or 0)))
    return {
        "subtotal": sub,
        "gg_monto": gg,
        "utilidad_monto": util,
        "valor_neto": neto,
        "iva": iva,
        "total": neto + iva,
    }


def estado_label_cot(estado: str | None) -> str:
    return {
        "borrador": "Borrador",
        "enviada": "Enviada",
        "aprobada": "Aprobada",
        "rechazada": "Rechazada",
    }.get(estado or "", estado or "—")


ESTADOS_COT = (
    ("borrador", "Borrador"),
    ("enviada", "Enviada"),
    ("aprobada", "Aprobada"),
    ("rechazada", "Rechazada"),
)


def cxc_estado_label(estado: str | None) -> str:
    e = (estado or "").lower()
    if e in ("pagado", "pagada"):
        return "Pagado"
    if e in ("parcial", "abonado", "abonada"):
        return "Abonado"
    return "Pendiente"


def cxc_estado_class(estado: str | None) -> str:
    e = (estado or "").lower()
    if e in ("pagado", "pagada"):
        return "pagado"
    if e in ("parcial", "abonado", "abonada"):
        return "abonado"
    return "pendiente"


def recalc_cuenta(c: sqlite3.Connection, cuenta_id: int) -> None:
    row = c.execute("SELECT monto FROM cuentas WHERE id=?", (cuenta_id,)).fetchone()
    abonado = c.execute(
        "SELECT COALESCE(SUM(monto),0) AS s FROM abonos WHERE cuenta_id=?", (cuenta_id,)
    ).fetchone()["s"]
    monto = float(row["monto"])
    saldo = max(0.0, monto - float(abonado))
    estado = "pagado" if saldo <= 0 else ("parcial" if abonado > 0 else "pendiente")
    c.execute(
        "UPDATE cuentas SET abonado=?, saldo=?, estado=? WHERE id=?",
        (abonado, saldo, estado, cuenta_id),
    )


def _pdf_txt(value) -> str:
    s = str(value or "")
    # Evita "?" por guiones tipográficos / bullets fuera de latin-1
    s = (
        s.replace("—", "-")
        .replace("–", "-")
        .replace("•", "-")
        .replace("·", "|")
        .replace("“", '"')
        .replace("”", '"')
        .replace("’", "'")
    )
    return s.encode("latin-1", "replace").decode("latin-1")


def scrub_import_labels(c: sqlite3.Connection) -> dict:
    """Elimina textos 'importado' / 'SOLUERP' de conceptos, notas y medios."""
    stats = {"cuentas": 0, "abonos_nota": 0, "abonos_medio": 0, "cotizaciones": 0}

    # Cuentas: "Importado SOLUERP 254" → vacío (el Nº queda en num_factura)
    cur = c.execute(
        """
        UPDATE cuentas
        SET concepto=NULL
        WHERE concepto IS NOT NULL
          AND (
            lower(concepto) LIKE '%importad%'
            OR lower(concepto) LIKE '%soluerp%'
          )
        """
    )
    stats["cuentas"] = cur.rowcount if cur.rowcount is not None else 0

    cur = c.execute(
        """
        UPDATE abonos
        SET nota=NULL
        WHERE nota IS NOT NULL
          AND (
            lower(nota) LIKE '%importad%'
            OR lower(nota) LIKE '%soluerp%'
          )
        """
    )
    stats["abonos_nota"] = cur.rowcount if cur.rowcount is not None else 0

    cur = c.execute(
        """
        UPDATE abonos
        SET medio='Transferencia'
        WHERE medio IS NOT NULL
          AND (
            lower(medio) LIKE '%importad%'
            OR lower(medio) LIKE '%soluerp%'
          )
        """
    )
    stats["abonos_medio"] = cur.rowcount if cur.rowcount is not None else 0

    cur = c.execute(
        """
        UPDATE cotizaciones
        SET notas=NULL
        WHERE notas IS NOT NULL
          AND (
            lower(notas) LIKE '%importad%'
            OR lower(notas) LIKE '%soluerp%'
          )
        """
    )
    stats["cotizaciones"] = cur.rowcount if cur.rowcount is not None else 0

    c.commit()
    return stats


def extract_num_factura(*texts) -> str | None:
    """Extrae Nº de factura exacto desde documento/asunto/concepto."""
    blob = " ".join(str(t or "") for t in texts).strip()
    if not blob:
        return None
    if re.fullmatch(r"\d+", blob):
        return blob
    patterns = [
        r"\bfactura\s+(\d+)\b",
        r"\bfact\.?\s+(\d+)\b",
        r"\bsoluerp\s+(\d+)\b",
        r"\bFAC[- ]?(\d+)\b",
        r"^(?:FAC|FA|EP|ND)[- ]?(\d+)$",
    ]
    for pat in patterns:
        m = re.search(pat, blob, flags=re.IGNORECASE | re.MULTILINE)
        if m:
            return m.group(1)
    return None


def sync_cuenta_cotizacion_links(c: sqlite3.Connection) -> int:
    """Rellena num_factura y enlaza cuentas <-> cotizaciones por Nº de factura."""
    cuentas = c.execute(
        """
        SELECT id, documento, concepto, num_factura, cotizacion_id, cliente_id
        FROM cuentas
        """
    ).fetchall()
    for cu in cuentas:
        num = (cu["num_factura"] or "").strip()
        if not num:
            num = extract_num_factura(cu["documento"], cu["concepto"]) or ""
            if num:
                c.execute(
                    "UPDATE cuentas SET num_factura=?, facturado=1 WHERE id=?",
                    (num, cu["id"]),
                )

    cuentas = c.execute(
        """
        SELECT id, documento, concepto, num_factura, cotizacion_id, cliente_id
        FROM cuentas
        """
    ).fetchall()
    cots = c.execute(
        """
        SELECT id, folio, asunto, titulo, proyecto, cxc_id, cliente_id
        FROM cotizaciones
        """
    ).fetchall()

    cot_by_fac: dict[tuple[int, str], sqlite3.Row] = {}
    for cot in cots:
        num = extract_num_factura(cot["asunto"], cot["titulo"], cot["proyecto"])
        if not num or not cot["cliente_id"]:
            continue
        key = (int(cot["cliente_id"]), str(num))
        # Si hay varias, preferir la ya enlazada a esta factura / la más antigua
        if key not in cot_by_fac:
            cot_by_fac[key] = cot

    linked = 0

    def _link(cu_id: int, cot_id: int, num: str | None) -> None:
        nonlocal linked
        if num:
            c.execute(
                """
                UPDATE cuentas
                SET cotizacion_id=?, num_factura=?, facturado=1
                WHERE id=?
                """,
                (cot_id, num, cu_id),
            )
        else:
            c.execute("UPDATE cuentas SET cotizacion_id=? WHERE id=?", (cot_id, cu_id))
        c.execute("UPDATE cotizaciones SET cxc_id=? WHERE id=?", (cu_id, cot_id))
        linked += 1

    for cu in cuentas:
        if not cu["cliente_id"]:
            continue
        num = (cu["num_factura"] or "").strip() or extract_num_factura(cu["documento"], cu["concepto"]) or ""
        if not num:
            continue
        cot = cot_by_fac.get((int(cu["cliente_id"]), str(num)))
        if not cot:
            continue
        if cu["cotizacion_id"] and int(cu["cotizacion_id"]) != int(cot["id"]):
            continue
        if cot["cxc_id"] and int(cot["cxc_id"]) != int(cu["id"]):
            continue
        _link(int(cu["id"]), int(cot["id"]), num)

    # Segundo paso: cuentas y cotizaciones aún libres, mismo cliente y monto,
    # emparejadas por fecha (útil para arriendos mensuales sin "factura N" en el título).
    free_cuentas = c.execute(
        """
        SELECT id, cliente_id, monto, fecha_emision, fecha_vencimiento, num_factura, documento, concepto
        FROM cuentas
        WHERE cotizacion_id IS NULL AND cliente_id IS NOT NULL
        ORDER BY COALESCE(fecha_emision, fecha_vencimiento, ''), id
        """
    ).fetchall()
    free_cots = c.execute(
        """
        SELECT id, cliente_id, total, fecha, asunto, titulo, proyecto
        FROM cotizaciones
        WHERE cxc_id IS NULL AND cliente_id IS NOT NULL
        ORDER BY COALESCE(fecha, ''), id
        """
    ).fetchall()
    used_cots: set[int] = set()
    for cu in free_cuentas:
        cid = int(cu["cliente_id"])
        monto = round(float(cu["monto"] or 0), 2)
        match = None
        for cot in free_cots:
            if int(cot["id"]) in used_cots:
                continue
            if int(cot["cliente_id"]) != cid:
                continue
            if round(float(cot["total"] or 0), 2) != monto:
                continue
            # No reutilizar cotizaciones que ya tienen Nº factura distinto
            cot_fac = extract_num_factura(cot["asunto"], cot["titulo"], cot["proyecto"])
            cu_fac = (cu["num_factura"] or "").strip() or extract_num_factura(cu["documento"], cu["concepto"]) or ""
            if cot_fac and cu_fac and str(cot_fac) != str(cu_fac):
                continue
            match = cot
            break
        if not match:
            continue
        used_cots.add(int(match["id"]))
        num = (cu["num_factura"] or "").strip() or extract_num_factura(cu["documento"], cu["concepto"]) or ""
        _link(int(cu["id"]), int(match["id"]), num or None)

    c.commit()
    return linked


def cuenta_doc_factura_display(cuenta) -> tuple[str, str]:
    """Devuelve (documento visible, Nº factura). Documento = COT si está enlazada."""
    keys = set(cuenta.keys()) if hasattr(cuenta, "keys") else set(cuenta)
    folio = str(cuenta["cot_folio"]).strip() if "cot_folio" in keys and cuenta["cot_folio"] else ""
    doc = str(cuenta["documento"] or "").strip() if "documento" in keys else ""
    concepto = cuenta["concepto"] if "concepto" in keys else ""
    num = ""
    if "num_factura" in keys and cuenta["num_factura"]:
        num = str(cuenta["num_factura"]).strip()
    if not num:
        num = extract_num_factura(doc, concepto) or ""
    return (folio or doc or "-"), (num or "-")


def fmt_clp_plain(v) -> str:
    try:
        return f"{int(round(float(v or 0))):,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return "0"


def fmt_cant_pdf(v) -> str:
    try:
        return f"{float(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "0,00"


def cotizacion_titulo_pdf(cot) -> str:
    version = str(cot["version"] if "version" in cot.keys() else "1") or "1"
    version = version.lstrip("Vv") or "1"
    titulo = ""
    for key in ("titulo", "asunto", "proyecto"):
        if key in cot.keys() and cot[key]:
            titulo = str(cot[key]).strip()
            if titulo:
                break
    if not titulo and "razon_social" in cot.keys() and cot["razon_social"]:
        titulo = str(cot["razon_social"]).strip()
    if not titulo:
        titulo = "COTIZACION"
    return f"V{version} COTIZACIÓN {titulo}".upper()


def _pct_from_text(text: str | None, default: float | None = None) -> float | None:
    import re

    m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", text or "")
    if not m:
        return default
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return default


def _is_gg_line(desc: str | None) -> bool:
    """Fila-resumen GG importada (no partidas de obra que empiecen parecido)."""
    import re

    d = (desc or "").strip().lower()
    if not d:
        return False
    return bool(
        re.match(r"^(gg|g\.?\s*g\.?|gastos?\s+generales)(\s+\d+([.,]\d+)?\s*%?)?$", d)
    )


def _is_util_line(desc: str | None) -> bool:
    """Fila-resumen utilidad importada (no «Utilidades eléctricas», etc.)."""
    import re

    d = (desc or "").strip().lower()
    if not d:
        return False
    if d in ("util", "util."):
        return True
    return bool(re.match(r"^utilidad(es)?(\s+\d+([.,]\d+)?\s*%?)?$", d))


def _split_cotizacion_items(items):
    """Separa ítems de trabajo vs filas GG/Utilidad (datos históricos)."""
    work = []
    gg_it = None
    util_it = None
    for it in items:
        desc = it["descripcion"] if "descripcion" in it.keys() else ""
        if _is_gg_line(desc):
            gg_it = it
        elif _is_util_line(desc):
            util_it = it
        else:
            work.append(it)
    return work, gg_it, util_it


def _cotizacion_planilla_totales(cot, items, iva_pct: float = 0.19) -> dict:
    """Arma subtotal/GG/Utilidad/IVA ordenados para la planilla PDF."""
    work, gg_it, util_it = _split_cotizacion_items(items)
    subtotal = sum(float(it["total"] or 0) for it in work)

    gg_pct = float(cot["gg_pct"] if "gg_pct" in cot.keys() and cot["gg_pct"] is not None else 5)
    util_pct = float(
        cot["utilidad_pct"] if "utilidad_pct" in cot.keys() and cot["utilidad_pct"] is not None else 15
    )
    if gg_it is not None:
        gg = float(gg_it["total"] or 0)
        desc_pct = _pct_from_text(gg_it["descripcion"], None)
        if desc_pct is not None:
            gg_pct = desc_pct
        # si el ítem histórico no trae %, se mantiene el % configurado solo como etiqueta
    else:
        stored_gg = float(cot["gg_monto"] or 0) if "gg_monto" in cot.keys() else 0.0
        gg = stored_gg if stored_gg > 0 else float(round(subtotal * gg_pct / 100.0))

    if util_it is not None:
        util = float(util_it["total"] or 0)
        desc_pct = _pct_from_text(util_it["descripcion"], None)
        if desc_pct is not None:
            util_pct = desc_pct
    else:
        stored_util = float(cot["utilidad_monto"] or 0) if "utilidad_monto" in cot.keys() else 0.0
        util = stored_util if stored_util > 0 else float(round(subtotal * util_pct / 100.0))

    neto = float(round(subtotal + gg + util))
    stored_iva = float(cot["iva"] or 0) if "iva" in cot.keys() else 0.0
    stored_total = float(cot["total"] or 0) if "total" in cot.keys() else 0.0
    stored_neto = float(cot["valor_neto"] or 0) if "valor_neto" in cot.keys() else 0.0

    if stored_neto > 0 and abs(stored_neto - neto) <= 1 and stored_iva >= 0:
        iva = stored_iva
        total = stored_total if stored_total > 0 else neto + iva
    elif stored_total > 0 and stored_iva > 0 and abs(stored_total - stored_iva - neto) <= 2:
        # Legacy: a veces el neto coincidía con total-iva
        iva = stored_iva
        total = stored_total
    else:
        iva = float(round(neto * float(iva_pct or 0.19)))
        total = neto + iva

    return {
        "work_items": work,
        "subtotal": subtotal,
        "gg_pct": gg_pct,
        "util_pct": util_pct,
        "gg": gg,
        "util": util,
        "neto": neto,
        "iva": iva,
        "iva_pct": float(iva_pct or 0.19) * 100.0,
        "total": total,
    }


def cotizacion_pdf_bytes(cot, items, empresa_row, iva_pct: float = 0.19) -> bytes:
    """PDF cotización — diseño alineado a la UI Comercial (navy/cyan)."""
    if FPDF is None:
        raise RuntimeError("FPDF no está instalado")

    C_BRAND = (22, 58, 95)
    C_CYAN = (15, 143, 168)
    C_TEXT = (26, 43, 60)
    C_MUTED = (91, 107, 124)
    C_LINE = (215, 224, 234)
    C_BG = (238, 242, 247)
    C_ROW = (245, 248, 252)
    C_WHITE = (255, 255, 255)

    plan = _cotizacion_planilla_totales(cot, items, iva_pct=iva_pct)
    work = plan["work_items"]

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()
    page_w, page_h = pdf.w, pdf.h
    left, right = 12.0, page_w - 12.0
    content_w = right - left

    pdf.set_fill_color(*C_BRAND)
    pdf.rect(0, 0, page_w, 22, "F")
    pdf.set_fill_color(*C_CYAN)
    pdf.rect(0, 22, page_w, 1.6, "F")

    logo = logo_para_pdf()
    if logo.exists():
        pdf.set_fill_color(*C_WHITE)
        pdf.rect(left - 1, 3.5, 30, 15, "F")
        try:
            pdf.image(str(logo), x=left, y=4.2, h=13)
        except Exception:
            pdf.image(str(logo), x=left, y=4.2, w=28)

    razon = ""
    if empresa_row:
        keys = set(empresa_row.keys())
        if "razon_social" in keys and empresa_row["razon_social"]:
            razon = str(empresa_row["razon_social"])
    if not razon:
        t, s = marca_pdf_fallback()
        razon = f"{t} {s}".strip()
    pdf.set_xy(left + 32, 5)
    pdf.set_text_color(*C_WHITE)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(content_w - 80, 5, _pdf_txt(razon)[:48], ln=1)
    pdf.set_x(left + 32)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(180, 205, 230)
    pdf.cell(content_w - 80, 4, _pdf_txt(pie_marca_pdf())[:52], ln=1)

    folio = cot["folio"] if "folio" in cot.keys() and cot["folio"] else ""
    if folio:
        bw, bh = 42, 10
        bx = right - bw
        pdf.set_fill_color(*C_CYAN)
        pdf.rect(bx, 6, bw, bh, "F")
        pdf.set_xy(bx, 7.5)
        pdf.set_text_color(*C_WHITE)
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(bw, 7, _pdf_txt(folio), align="C")

    y = 28.0
    cliente = cot["razon_social"] if "razon_social" in cot.keys() and cot["razon_social"] else ""
    try:
        estado = estado_label_cot(cot["estado"] if "estado" in cot.keys() else None)
    except Exception:
        estado = str(cot["estado"] if "estado" in cot.keys() and cot["estado"] else "")
    if "fecha" in cot.keys() and cot["fecha"]:
        fecha_cot = fmt_dmy(cot["fecha"])
    else:
        fecha_cot = hoy_chile().strftime("%d/%m/%Y")

    pdf.set_fill_color(*C_BG)
    pdf.rect(left, y, content_w, 16, "F")
    pdf.set_xy(left + 3, y + 2)
    pdf.set_text_color(*C_MUTED)
    pdf.set_font("Helvetica", "", 7)
    pdf.cell(18, 4, _pdf_txt("CLIENTE"), ln=0)
    pdf.set_text_color(*C_TEXT)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(content_w - 24, 4, _pdf_txt(cliente or "—")[:58], ln=1)
    pdf.set_xy(left + 3, y + 8)
    pdf.set_text_color(*C_MUTED)
    pdf.set_font("Helvetica", "", 7)
    pdf.cell(14, 4, _pdf_txt("FECHA"), ln=0)
    pdf.set_text_color(*C_TEXT)
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(32, 4, _pdf_txt(fecha_cot), ln=0)
    pdf.set_text_color(*C_MUTED)
    pdf.set_font("Helvetica", "", 7)
    pdf.cell(16, 4, _pdf_txt("ESTADO"), ln=0)
    pdf.set_text_color(*C_CYAN)
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(0, 4, _pdf_txt(estado or "—"), ln=1)

    y = 48.0
    title = _pdf_txt(cotizacion_titulo_pdf(cot))
    pdf.set_xy(left, y)
    pdf.set_text_color(*C_BRAND)
    pdf.set_font("Helvetica", "B", 12)
    pdf.multi_cell(content_w, 6, title)
    y = pdf.get_y() + 2

    headers = ["#", "Especificación", "Obs", "Und", "Cant.", "Valor", "Total"]
    # A4 vertical: ~186 mm útiles
    widths = [10, 62, 26, 12, 18, 28, 30]
    x0 = left
    row_h = 6.2

    def draw_row(yy, cells, *, header=False, alt=False, bold=False):
        pdf.set_xy(x0, yy)
        if header:
            pdf.set_fill_color(*C_BRAND)
            pdf.set_text_color(*C_WHITE)
            pdf.set_font("Helvetica", "B", 8)
        else:
            pdf.set_fill_color(*(C_ROW if alt else C_WHITE))
            pdf.set_text_color(*C_TEXT)
            pdf.set_font("Helvetica", "B" if bold else "", 8)
        pdf.set_draw_color(*C_LINE)
        for (txt, align), w in zip(cells, widths):
            pdf.cell(w, row_h, _pdf_txt(txt), border=1, align=align, fill=True)

    table_top_y = y
    draw_row(y, [(h, "C") for h in headers], header=True)
    y += row_h

    rows = list(work)
    n_drawn = 0
    if not rows:
        draw_row(y, [("", "C"), ("Sin ítems", "L"), ("", "L"), ("", "C"), ("", "R"), ("", "R"), ("", "R")])
        y += row_h
        n_drawn = 1
    else:
        for idx, it in enumerate(rows, start=1):
            desc = str(it["descripcion"] or "")
            obs = str(it["obs"] if "obs" in it.keys() and it["obs"] else "")
            und = str(it["unidad"] or "")
            cant = float(it["cantidad"] or 0)
            pu = float(it["precio_unitario"] or 0)
            tot = float(it["total"] or 0)
            is_section = tot == 0 and pu == 0
            if is_section:
                draw_row(
                    y,
                    [(str(idx), "C"), (desc[:42], "L"), ("", "L"), ("", "C"), ("", "R"), ("", "R"), ("", "R")],
                    alt=(idx % 2 == 0),
                    bold=True,
                )
            else:
                draw_row(
                    y,
                    [
                        (str(idx), "C"),
                        (desc[:42], "L"),
                        (obs[:16], "L"),
                        (und[:6], "C"),
                        (fmt_cant_pdf(cant), "R"),
                        (f"$ {fmt_clp_plain(pu)}", "R"),
                        (f"$ {fmt_clp_plain(tot)}", "R"),
                    ],
                    alt=(idx % 2 == 0),
                )
            y += row_h
            n_drawn = idx
            if y > page_h - 52:
                break

    # Completar cuadriculado vacío hasta el bloque de totales / pie.
    table_bottom = page_h - 52.0
    empty_i = n_drawn
    while y + row_h <= table_bottom + 0.01:
        empty_i += 1
        draw_row(
            y,
            [("", "C"), ("", "L"), ("", "L"), ("", "C"), ("", "R"), ("", "R"), ("", "R")],
            alt=(empty_i % 2 == 0),
        )
        y += row_h

    # Sello DEMO atravesado en la zona de productos (tabla de ítems).
    zone_h = max(y - table_top_y, page_h - 55.0 - table_top_y, 50.0)
    _pdf_sello_demo_prueba(pdf, left, table_top_y, content_w, zone_h)

    summary = [
        ("Subtotal", f"$ {fmt_clp_plain(plan['subtotal'])}", False),
        (f"GG {plan['gg_pct']:g}%", f"$ {fmt_clp_plain(plan['gg'])}", False),
        (f"Utilidad {plan['util_pct']:g}%", f"$ {fmt_clp_plain(plan['util'])}", False),
        ("Valor neto", f"$ {fmt_clp_plain(plan['neto'])}", True),
        (f"IVA {plan['iva_pct']:g}%", f"$ {fmt_clp_plain(plan['iva'])}", False),
        ("TOTAL", f"$ {fmt_clp_plain(plan['total'])}", True),
    ]
    label_w, val_w = 42, 36
    box_w = label_w + val_w
    sx = right - box_w
    sy = page_h - 48
    pdf.set_fill_color(*C_WHITE)
    pdf.set_draw_color(*C_LINE)
    pdf.rect(sx - 2, sy - 2, box_w + 4, len(summary) * 6.2 + 4, "DF")
    for i, (lab, val, bold) in enumerate(summary):
        yy = sy + i * 6.2
        pdf.set_xy(sx, yy)
        if bold and lab == "TOTAL":
            pdf.set_fill_color(*C_CYAN)
            pdf.set_text_color(*C_WHITE)
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(label_w, 6.2, _pdf_txt(lab), border=0, fill=True)
            pdf.cell(val_w, 6.2, _pdf_txt(val), border=0, align="R", fill=True)
        elif bold:
            pdf.set_fill_color(*C_BG)
            pdf.set_text_color(*C_BRAND)
            pdf.set_font("Helvetica", "B", 8)
            pdf.cell(label_w, 6.2, _pdf_txt(lab), border=0, fill=True)
            pdf.cell(val_w, 6.2, _pdf_txt(val), border=0, align="R", fill=True)
        else:
            pdf.set_text_color(*C_MUTED)
            pdf.set_font("Helvetica", "", 8)
            pdf.cell(label_w, 6.2, _pdf_txt(lab), border=0)
            pdf.set_text_color(*C_TEXT)
            pdf.set_font("Helvetica", "B", 8)
            pdf.cell(val_w, 6.2, _pdf_txt(val), border=0, align="R")

    pdf.set_xy(left, page_h - 10)
    pdf.set_draw_color(*C_CYAN)
    pdf.set_line_width(0.4)
    pdf.line(left, page_h - 12, right, page_h - 12)
    pdf.set_text_color(*C_MUTED)
    pdf.set_font("Helvetica", "", 7)
    pdf.cell(
        content_w,
        5,
        _pdf_txt(
            f"{folio} · {cliente} · Cotización · {hoy_chile().strftime('%d/%m/%Y')} · {pie_marca_pdf()}"
        ),
        align="L",
    )

    raw = pdf.output(dest="S")
    return raw.encode("latin-1") if isinstance(raw, str) else bytes(raw)


def _pdf_header_portrait(pdf, empresa_row, subtitle: str) -> None:
    """Encabezado portrait alineado a la UI Comercial."""
    C_BRAND = (22, 58, 95)
    C_CYAN = (15, 143, 168)
    C_TEXT = (26, 43, 60)
    C_MUTED = (91, 107, 124)
    C_WHITE = (255, 255, 255)
    C_BG = (238, 242, 247)

    left = 12.0
    right = pdf.w - pdf.r_margin
    content_w = right - left
    page_w = pdf.w

    pdf.set_fill_color(*C_BRAND)
    pdf.rect(0, 0, page_w, 20, "F")
    pdf.set_fill_color(*C_CYAN)
    pdf.rect(0, 20, page_w, 1.4, "F")

    logo = logo_para_pdf()
    if logo.exists():
        pdf.set_fill_color(*C_WHITE)
        pdf.rect(left - 1, 3, 30, 14, "F")
        try:
            pdf.image(str(logo), x=left, y=3.8, h=12)
        except Exception:
            pdf.image(str(logo), x=left, y=3.8, w=28)

    titulo_fb, sub_fb = marca_pdf_fallback()
    razon = f"{titulo_fb} {sub_fb}".strip()
    rut = telefono = email = direccion = ""
    if empresa_row:
        keys = set(empresa_row.keys())
        if "razon_social" in keys and empresa_row["razon_social"]:
            razon = str(empresa_row["razon_social"])
        if "rut" in keys and empresa_row["rut"]:
            rut = str(empresa_row["rut"])
        if "telefono" in keys and empresa_row["telefono"]:
            telefono = str(empresa_row["telefono"])
        if "email" in keys and empresa_row["email"]:
            email = str(empresa_row["email"])
        if "direccion" in keys and empresa_row["direccion"]:
            direccion = str(empresa_row["direccion"])

    pdf.set_xy(left + 32, 4.5)
    pdf.set_text_color(*C_WHITE)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(content_w - 70, 5, _pdf_txt(razon), ln=1)
    pdf.set_x(left + 32)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(180, 205, 230)
    meta = [x for x in (f"RUT {rut}" if rut else "", telefono, email) if x]
    pdf.cell(content_w - 70, 4, _pdf_txt(" · ".join(meta) if meta else pie_marca_pdf()), ln=1)

    pdf.set_xy(left, 5)
    pdf.set_text_color(180, 205, 230)
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(content_w, 5, _pdf_txt(hoy_chile().strftime("%d/%m/%Y")), align="R")

    y = 28.0
    if direccion:
        pdf.set_xy(left, y)
        pdf.set_text_color(*C_MUTED)
        pdf.set_font("Helvetica", "", 8)
        pdf.cell(content_w, 4, _pdf_txt(direccion), ln=1)
        y = pdf.get_y() + 1

    pdf.set_fill_color(*C_BG)
    pdf.rect(left, y, content_w, 9, "F")
    pdf.set_xy(left + 3, y + 1.8)
    pdf.set_text_color(*C_BRAND)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(content_w - 6, 6, _pdf_txt(subtitle), ln=1)
    pdf.set_text_color(*C_TEXT)
    pdf.set_y(y + 12)


def cuenta_pdf_bytes(cuenta, abonos, empresa_row) -> bytes:
    """PDF vertical de un documento CxC con historial de abonos."""
    if FPDF is None:
        raise RuntimeError("FPDF no está instalado")
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    doc = cuenta["documento"] if "documento" in cuenta.keys() else "CxC"
    _pdf_header_portrait(pdf, empresa_row, f"Documento {doc}")

    pdf.set_font("Helvetica", "", 10)
    lines = [
        ("Cliente", cuenta["razon_social"] if "razon_social" in cuenta.keys() else "—"),
        ("RUT cliente", cuenta["cliente_rut"] if "cliente_rut" in cuenta.keys() else "—"),
        (
            "Tipo",
            cuenta["tipo"]
            if "tipo" in cuenta.keys() and cuenta["tipo"]
            else (cuenta["tipo_doc"] if "tipo_doc" in cuenta.keys() else "—"),
        ),
        ("Nº Factura", cuenta["num_factura"] if "num_factura" in cuenta.keys() and cuenta["num_factura"] else "—"),
        ("Emisión", fmt_dmy(cuenta["fecha_emision"] if "fecha_emision" in cuenta.keys() else None)),
        ("Vencimiento", fmt_dmy(cuenta["fecha_vencimiento"] if "fecha_vencimiento" in cuenta.keys() else None)),
        ("Estado", cxc_estado_label(cuenta["estado"] if "estado" in cuenta.keys() else None)),
        ("Concepto", cuenta["concepto"] if "concepto" in cuenta.keys() and cuenta["concepto"] else "—"),
    ]
    for lab, val in lines:
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(40, 6, _pdf_txt(lab), border=0)
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 6, _pdf_txt(val), border=0)

    pdf.ln(3)
    pdf.set_fill_color(238, 243, 249)
    pdf.set_font("Helvetica", "B", 9)
    for lab, val in [
        ("Total", f"$ {fmt_clp_plain(cuenta['monto'] if 'monto' in cuenta.keys() else 0)}"),
        ("Abonos", f"$ {fmt_clp_plain(cuenta['abonado'] if 'abonado' in cuenta.keys() else 0)}"),
        ("Saldo", f"$ {fmt_clp_plain(cuenta['saldo'] if 'saldo' in cuenta.keys() else 0)}"),
    ]:
        pdf.cell(40, 7, _pdf_txt(lab), border=1, fill=True)
        pdf.cell(50, 7, _pdf_txt(val), border=1, align="R", ln=1)

    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(22, 58, 95)
    pdf.cell(0, 7, _pdf_txt("Abonos registrados"), ln=1)
    headers = ["Fecha", "Monto", "Medio", "Nota"]
    widths = [28, 35, 35, 92]
    pdf.set_fill_color(22, 58, 95)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 8)
    for h, w in zip(headers, widths):
        pdf.cell(w, 6, h, border=1, align="C", fill=True)
    pdf.ln()
    pdf.set_text_color(26, 43, 60)
    pdf.set_font("Helvetica", "", 8)
    if not abonos:
        pdf.cell(sum(widths), 6, _pdf_txt("Sin abonos"), border=1, ln=1)
    else:
        for a in abonos:
            pdf.cell(widths[0], 6, _pdf_txt(fmt_dmy(a["fecha"])), border=1)
            pdf.cell(widths[1], 6, _pdf_txt(f"$ {fmt_clp_plain(a['monto'])}"), border=1, align="R")
            pdf.cell(widths[2], 6, _pdf_txt(a["medio"] if "medio" in a.keys() else ""), border=1)
            nota = a["nota"] if "nota" in a.keys() else ""
            pdf.cell(widths[3], 6, _pdf_txt(nota)[:48], border=1, ln=1)

    # Sello DEMO sobre zona de detalle / abonos.
    _pdf_sello_demo_prueba(pdf, 10.0, 55.0, 190.0, 120.0)

    pdf.ln(8)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 5, _pdf_txt(f"Generado {hoy_chile().strftime('%d/%m/%Y')} · {pie_marca_pdf()}"), ln=1)
    raw = pdf.output(dest="S")
    return raw.encode("latin-1") if isinstance(raw, str) else bytes(raw)


def estado_cuenta_pdf_bytes(cliente, cuentas, abonos, cots, deuda, empresa_row) -> bytes:
    """PDF Vista 360 / estado de cuenta del cliente."""
    if FPDF is None:
        raise RuntimeError("FPDF no está instalado")
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    nombre = cliente["razon_social"] if cliente else "Cliente"
    _pdf_header_portrait(pdf, empresa_row, "Estado de cuenta")

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, _pdf_txt(nombre), ln=1)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(
        0,
        5,
        _pdf_txt(
            f"RUT {cliente['rut'] if cliente and cliente['rut'] else '-'} | "
            f"{cliente['telefono'] if cliente and cliente['telefono'] else '-'} | "
            f"{cliente['email'] if cliente and cliente['email'] else '-'}"
        ),
        ln=1,
    )
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 10)
    if float(deuda or 0) > 0:
        pdf.set_fill_color(255, 235, 235)
    else:
        pdf.set_fill_color(230, 245, 235)
    pdf.cell(60, 8, _pdf_txt("Deuda abierta"), border=1, fill=True)
    pdf.cell(50, 8, _pdf_txt(f"$ {fmt_clp_plain(deuda)}"), border=1, align="R", fill=True, ln=1)

    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(22, 58, 95)
    pdf.cell(0, 7, _pdf_txt("Cuentas por cobrar"), ln=1)
    widths = [34, 28, 28, 32, 32, 26]
    headers = ["Documento", "Factura", "Vence", "Total", "Saldo", "Estado"]
    pdf.set_fill_color(22, 58, 95)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 8)
    for h, w in zip(headers, widths):
        pdf.cell(w, 6, h, border=1, align="C", fill=True)
    pdf.ln()
    pdf.set_text_color(26, 43, 60)
    pdf.set_font("Helvetica", "", 8)
    if not cuentas:
        pdf.cell(sum(widths), 6, _pdf_txt("Sin documentos"), border=1, ln=1)
    else:
        for x in cuentas:
            doc_disp, fac_disp = cuenta_doc_factura_display(x)
            pdf.cell(widths[0], 6, _pdf_txt(doc_disp), border=1)
            pdf.cell(widths[1], 6, _pdf_txt(fac_disp), border=1, align="C")
            pdf.cell(widths[2], 6, _pdf_txt(fmt_dmy(x["fecha_vencimiento"] if "fecha_vencimiento" in x.keys() else None)), border=1)
            pdf.cell(widths[3], 6, _pdf_txt(f"$ {fmt_clp_plain(x['monto'])}"), border=1, align="R")
            pdf.cell(widths[4], 6, _pdf_txt(f"$ {fmt_clp_plain(x['saldo'])}"), border=1, align="R")
            pdf.cell(widths[5], 6, _pdf_txt(cxc_estado_label(x["estado"])), border=1, ln=1)

    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(22, 58, 95)
    pdf.cell(0, 7, _pdf_txt("Abonos"), ln=1)
    aw = [28, 40, 35, 77]
    pdf.set_fill_color(22, 58, 95)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 8)
    for h, w in zip(["Fecha", "Documento", "Monto", "Medio"], aw):
        pdf.cell(w, 6, h, border=1, align="C", fill=True)
    pdf.ln()
    pdf.set_text_color(26, 43, 60)
    pdf.set_font("Helvetica", "", 8)
    if not abonos:
        pdf.cell(sum(aw), 6, _pdf_txt("Sin abonos"), border=1, ln=1)
    else:
        for a in abonos:
            pdf.cell(aw[0], 6, _pdf_txt(fmt_dmy(a["fecha"])), border=1)
            pdf.cell(aw[1], 6, _pdf_txt(a["documento"] if "documento" in a.keys() else ""), border=1)
            pdf.cell(aw[2], 6, _pdf_txt(f"$ {fmt_clp_plain(a['monto'])}"), border=1, align="R")
            pdf.cell(aw[3], 6, _pdf_txt(a["medio"] if "medio" in a.keys() else ""), border=1, ln=1)

    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(22, 58, 95)
    pdf.cell(0, 7, _pdf_txt("Cotizaciones"), ln=1)
    cw = [30, 28, 70, 28, 24]
    pdf.set_fill_color(22, 58, 95)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 8)
    for h, w in zip(["Folio", "Fecha", "Título", "Estado", "Total"], cw):
        pdf.cell(w, 6, h, border=1, align="C", fill=True)
    pdf.ln()
    pdf.set_text_color(26, 43, 60)
    pdf.set_font("Helvetica", "", 8)
    if not cots:
        pdf.cell(sum(cw), 6, _pdf_txt("Sin cotizaciones"), border=1, ln=1)
    else:
        for c in cots:
            pdf.cell(cw[0], 6, _pdf_txt(c["folio"]), border=1)
            pdf.cell(cw[1], 6, _pdf_txt(fmt_dmy(c["fecha"] if "fecha" in c.keys() else None)), border=1)
            titulo = c["titulo"] if "titulo" in c.keys() else ""
            pdf.cell(cw[2], 6, _pdf_txt(titulo)[:40], border=1)
            pdf.cell(cw[3], 6, _pdf_txt(estado_label_cot(c["estado"] if "estado" in c.keys() else None)), border=1)
            pdf.cell(cw[4], 6, _pdf_txt(f"$ {fmt_clp_plain(c['total'] if 'total' in c.keys() else 0)}"), border=1, align="R", ln=1)

    # Sello DEMO sobre tablas del estado de cuenta.
    _pdf_sello_demo_prueba(pdf, 10.0, 60.0, 190.0, 140.0)

    pdf.ln(8)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 5, _pdf_txt(f"Generado {hoy_chile().strftime('%d/%m/%Y')} · {pie_marca_pdf()}"), ln=1)
    raw = pdf.output(dest="S")
    return raw.encode("latin-1") if isinstance(raw, str) else bytes(raw)
