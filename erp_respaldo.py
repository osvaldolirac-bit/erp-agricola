"""Respaldo SQLite por correo — compartido entre ERP prod, demo y cron."""
from __future__ import annotations

import glob
import re
import gzip
import io
import os
import shutil
import smtplib
import sqlite3
import tarfile
import tempfile
from datetime import date, datetime, timedelta, timezone
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

META_EMAIL = "respaldo_email"
META_FRECUENCIA = "respaldo_frecuencia"
META_CODIGO_FRECUENCIA = "respaldo_codigo_frecuencia"
META_ACTIVO = "respaldo_activo"
META_ULTIMO_ENVIO = "respaldo_ultimo_envio"
META_ULTIMO_ERROR = "respaldo_ultimo_error"
META_CODIGO_ULTIMO_ENVIO = "respaldo_codigo_ultimo_envio"
META_CODIGO_ULTIMO_ERROR = "respaldo_codigo_ultimo_error"

FRECUENCIAS_RESPALDO = ("diario", "semanal", "mensual")
FRECUENCIAS_ETIQUETA = {
    "diario": "Diario",
    "semanal": "Semanal",
    "mensual": "Mensual",
}

CODIGO_ARCHIVOS_EXCLUIDOS = frozenset({"secrets.toml", "secrets.example.toml"})
CODIGO_DIRS_EXCLUIDOS = frozenset(
    {"__pycache__", ".git", "snap", ".cache", ".venv", "node_modules", "backups"}
)
CODIGO_SUFIJOS_EXCLUIDOS = (
    ".db",
    ".db.gz",
    ".pyc",
    ".log",
    ".RESPALDO_OFICIAL",
    ".bak",
    ".enc",
)

# Codigo: 1 zip por rubro (tenants del mismo producto comparten codigo).
SPECS_RESPALDO_CODIGO_RUBRO = {
    "agricola": {
        "nombre": "Codigo Agrícola",
        "slug": "agricola",
        "producto": "agricola",
        "db": "/root/erp_concepcion_v6.db",
        "secrets": "/root/.streamlit/secrets.toml",
        "roots": [
            {"path": "/root/demo-web", "recursive": True},
            {"path": "/root/static", "recursive": True},
            {"path": "/root", "patterns": ["*.py", "config_*.toml", "*.nginx.conf"]},
            {"path": "/root/.streamlit", "files": ["config.toml"]},
            {"path": "/root/scripts", "recursive": True},
            {
                "path": "/etc/systemd/system",
                "files": ["erp-agricola-web.service", "erp-lc-web.service"],
            },
        ],
    },
    "comercial": {
        "nombre": "Codigo Comercial",
        "slug": "comercial",
        "producto": "comercial",
        "db": "/root/riomaipo/data/riomaipo_erp.db",
        "secrets": "/root/riomaipo/secrets_riomaipo.toml",
        "roots": [
            {"path": "/root/riomaipo", "recursive": True},
            {
                "path": "/etc/systemd/system",
                "files": [
                    "erp-riomaipo.service",
                    "erp-comercial.service",
                    "erp-comercial-lc.service",
                ],
            },
        ],
    },
    "constructora": {
        "nombre": "Codigo Constructora",
        "slug": "constructora",
        "producto": "constructora",
        "db": "/root/constructora/data/constructora_demo.db",
        "secrets": "/root/constructora/secrets.toml",
        "roots": [
            {"path": "/root/constructora", "recursive": True},
            {
                "path": "/etc/systemd/system",
                "files": ["erp-constructora.service"],
            },
        ],
    },
}

# Compat: lista / lookup por nombre ERP antiguo → rubro
_TENANT_NOMBRE_A_RUBRO = {
    "erp agrícola la concepción": "agricola",
    "erp agricola la concepcion": "agricola",
    "erp demo agricola": "agricola",
    "río maipo": "comercial",
    "rio maipo": "comercial",
    "comercial lc": "comercial",
    "demo comercial": "comercial",
    "demo constructora": "constructora",
    "constructora": "constructora",
}

SPECS_RESPALDO_CODIGO = list(SPECS_RESPALDO_CODIGO_RUBRO.values())


def rubro_de_producto(producto: str) -> str:
    p = (producto or "").strip().lower()
    if p in SPECS_RESPALDO_CODIGO_RUBRO:
        return p
    return ""


def rubro_de_nombre_erp(nombre_erp: str) -> str:
    clave = (nombre_erp or "").strip().lower()
    if clave in SPECS_RESPALDO_CODIGO_RUBRO:
        return clave
    if clave in _TENANT_NOMBRE_A_RUBRO:
        return _TENANT_NOMBRE_A_RUBRO[clave]
    # fuzzy contains
    if "agrícola" in clave or "agricola" in clave or "concepción" in clave or "concepcion" in clave:
        return "agricola"
    if "comercial" in clave or "maipo" in clave:
        return "comercial"
    if "constructora" in clave:
        return "constructora"
    return ""


def spec_respaldo_codigo_por_rubro(rubro: str):
    return SPECS_RESPALDO_CODIGO_RUBRO.get((rubro or "").strip().lower())


def _status_dir_respaldo() -> str:
    return (os.environ.get("ERP_STATUS_DIR") or "/root/erp_status").strip() or "/root/erp_status"


def _codigo_rubro_meta_path(rubro: str) -> str:
    safe = re.sub(r"[^a-z0-9_-]+", "", (rubro or "").strip().lower())
    return os.path.join(_status_dir_respaldo(), f"respaldo_codigo_{safe}.json")


def load_codigo_rubro_meta(rubro: str) -> dict:
    import json

    rubro = (rubro or "").strip().lower()
    path = _codigo_rubro_meta_path(rubro)
    data = {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f) or {}
    except (OSError, ValueError):
        data = {}
    return {
        "activo": bool(data.get("activo")),
        "frecuencia": _normalizar_frecuencia(
            str(data.get("frecuencia") or "semanal"), default="semanal"
        ),
        "email": str(data.get("email") or "").strip(),
        "ultimo_envio": str(data.get("ultimo_envio") or "").strip(),
        "ultimo_error": str(data.get("ultimo_error") or "").strip(),
        "ultimo_archivo": str(data.get("ultimo_archivo") or "").strip(),
    }


def save_codigo_rubro_meta(rubro: str, updates: dict) -> dict:
    import json

    rubro = (rubro or "").strip().lower()
    if rubro not in SPECS_RESPALDO_CODIGO_RUBRO:
        raise ValueError(f"rubro codigo invalido: {rubro}")
    cur = load_codigo_rubro_meta(rubro)
    cur.update({k: updates[k] for k in updates if k in {
        "activo", "frecuencia", "email", "ultimo_envio", "ultimo_error", "ultimo_archivo"
    }})
    if "frecuencia" in cur:
        cur["frecuencia"] = _normalizar_frecuencia(cur["frecuencia"], default="semanal")
    if "activo" in cur:
        cur["activo"] = bool(cur["activo"])
    path = _codigo_rubro_meta_path(rubro)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return cur


def hora_chile():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Santiago"))
    except Exception:
        return datetime.now(timezone.utc) - timedelta(hours=4)


def _fecha_ultimo_envio_chile(ts):
    ts = (ts or "").strip()
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace(" ", "T")[:19]).date()
    except ValueError:
        return None


def _ensure_schema_meta(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (clave TEXT PRIMARY KEY, valor TEXT)")


def meta_get(conn, clave, default=""):
    _ensure_schema_meta(conn)
    row = conn.execute("SELECT valor FROM schema_meta WHERE clave=?", (clave,)).fetchone()
    if row and row[0] is not None:
        return str(row[0])
    return default


def meta_set(conn, clave, valor):
    _ensure_schema_meta(conn)
    conn.execute(
        "INSERT INTO schema_meta (clave, valor) VALUES (?, ?) "
        "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
        (clave, str(valor)),
    )


def normalizar_correos(*valores):
    vistos = set()
    salida = []
    for val in valores:
        if not val:
            continue
        for parte in str(val).replace(";", ",").split(","):
            addr = parte.strip()
            if not addr:
                continue
            clave = addr.lower()
            if clave in vistos:
                continue
            vistos.add(clave)
            salida.append(addr)
    return salida


def _cargar_toml(ruta):
    try:
        import tomllib
        with open(ruta, "rb") as f:
            return tomllib.load(f)
    except ModuleNotFoundError:
        try:
            import tomli
            with open(ruta, "rb") as f:
                return tomli.load(f)
        except Exception:
            pass
    except Exception:
        pass
    # Fallback mínimo para secrets Streamlit en Python < 3.11
    import re
    texto = open(ruta, encoding="utf-8").read()
    bloque = {}
    en_gmail = False
    for linea in texto.splitlines():
        s = linea.strip()
        if s.startswith("[") and s.endswith("]"):
            en_gmail = s.lower() == "[gmail_smtp]"
            continue
        if not en_gmail or "=" not in s or s.startswith("#"):
            continue
        k, v = s.split("=", 1)
        bloque[k.strip()] = v.strip().strip('"').strip("'")
    return {"gmail_smtp": bloque} if bloque else {}


def email_default_desde_secrets(secrets_path):
    try:
        conf = _cargar_toml(secrets_path).get("gmail_smtp", {})
        return (conf.get("correo_receptor") or conf.get("correo_emisor") or "").strip()
    except Exception:
        return ""


def migrar_config_respaldo(conn, email_default=""):
    _ensure_schema_meta(conn)
    nuevo = False
    if not conn.execute("SELECT 1 FROM schema_meta WHERE clave=?", (META_EMAIL,)).fetchone():
        meta_set(conn, META_EMAIL, email_default or "")
        meta_set(conn, META_FRECUENCIA, "diario")
        meta_set(conn, META_ACTIVO, "1")
        nuevo = True
    if not conn.execute("SELECT 1 FROM schema_meta WHERE clave=?", (META_CODIGO_FRECUENCIA,)).fetchone():
        meta_set(conn, META_CODIGO_FRECUENCIA, "semanal")
        nuevo = True
    if nuevo:
        conn.commit()


def _normalizar_frecuencia(freq, default="diario"):
    freq = (freq or default).lower().strip()
    return freq if freq in FRECUENCIAS_RESPALDO else default


def _corresponde_frecuencia(frecuencia, d_ultimo, hoy):
    """Reglas de envío programado (hora Chile).

    semanal = todos los viernes. Un forzado mid-semana no reemplaza el viernes.
    """
    freq = _normalizar_frecuencia(frecuencia)
    if freq == "semanal":
        if hoy.weekday() != 4:  # 0=lunes … 4=viernes
            return False
        return d_ultimo is None or d_ultimo < hoy
    if d_ultimo is None:
        return True
    if freq == "mensual":
        return d_ultimo.month != hoy.month or d_ultimo.year != hoy.year
    return d_ultimo < hoy


def obtener_config_respaldo(conn):
    """Config de DATOS del tenant. El activo de CODIGO vive por rubro (JSON)."""
    activo_datos = meta_get(conn, META_ACTIVO, "1") == "1"
    return {
        "email": meta_get(conn, META_EMAIL, ""),
        "frecuencia": _normalizar_frecuencia(meta_get(conn, META_FRECUENCIA, "diario")),
        "frecuencia_codigo": _normalizar_frecuencia(
            meta_get(conn, META_CODIGO_FRECUENCIA, "semanal"), default="semanal",
        ),
        "activo": activo_datos,  # datos (compat)
        "activo_datos": activo_datos,
        "ultimo_envio": meta_get(conn, META_ULTIMO_ENVIO, ""),
        "ultimo_error": meta_get(conn, META_ULTIMO_ERROR, ""),
        "ultimo_envio_codigo": meta_get(conn, META_CODIGO_ULTIMO_ENVIO, ""),
        "ultimo_error_codigo": meta_get(conn, META_CODIGO_ULTIMO_ERROR, ""),
    }


def guardar_config_respaldo(conn, email, frecuencia_datos, frecuencia_codigo, activo):
    meta_set(conn, META_EMAIL, normalizar_correos(email)[0] if normalizar_correos(email) else "")
    meta_set(conn, META_FRECUENCIA, _normalizar_frecuencia(frecuencia_datos))
    meta_set(conn, META_CODIGO_FRECUENCIA, _normalizar_frecuencia(frecuencia_codigo, default="semanal"))
    meta_set(conn, META_ACTIVO, "1" if activo else "0")
    conn.commit()


def formatear_ultimo_respaldo(config):
    ts = (config.get("ultimo_envio") or "").strip()
    if not ts:
        return "Aún no se ha enviado ningún respaldo de datos por correo."
    try:
        dt = datetime.fromisoformat(ts.replace(" ", "T")[:19])
        return f"Último respaldo de datos: {dt.strftime('%d-%m-%Y %H:%M')} (hora Chile)."
    except ValueError:
        return f"Último respaldo de datos: {ts}."


def formatear_ultimo_respaldo_codigo(config):
    ts = (config.get("ultimo_envio_codigo") or "").strip()
    if not ts:
        return "Aún no se ha generado ningún respaldo de código en el VPS."
    try:
        dt = datetime.fromisoformat(ts.replace(" ", "T")[:19])
        return f"Último respaldo de código: {dt.strftime('%d-%m-%Y %H:%M')} (hora Chile)."
    except ValueError:
        return f"Último respaldo de código: {ts}."


def _archivo_incluible_respaldo_codigo(path):
    base = os.path.basename(path)
    low = base.lower()
    if base in CODIGO_ARCHIVOS_EXCLUIDOS:
        return False
    if any(base.endswith(suf) for suf in CODIGO_SUFIJOS_EXCLUIDOS):
        return False
    # Copias *.bak / *.bak_fecha / file.py.bak_xxx (inflan el zip sin código vigente)
    if ".bak" in low or low.endswith("~") or low.endswith(".orig") or low.endswith(".swp"):
        return False
    if base.startswith(".") and base not in ("config.toml",):
        return False
    return os.path.isfile(path)


def recolectar_archivos_codigo(spec):
    """Lista archivos del ERP para tarball (sin secrets ni bases .db)."""
    archivos = []
    vistos = set()
    for root_spec in spec.get("roots", []):
        base = root_spec.get("path", "")
        if not base:
            continue
        if root_spec.get("recursive") and os.path.isdir(base):
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = [d for d in dirnames if d not in CODIGO_DIRS_EXCLUIDOS]
                for fn in filenames:
                    full = os.path.abspath(os.path.join(dirpath, fn))
                    if full in vistos or not _archivo_incluible_respaldo_codigo(full):
                        continue
                    vistos.add(full)
                    archivos.append(full)
            continue
        for pattern in root_spec.get("patterns", []):
            for p in glob.glob(os.path.join(base, pattern)):
                full = os.path.abspath(p)
                if full in vistos or not _archivo_incluible_respaldo_codigo(full):
                    continue
                vistos.add(full)
                archivos.append(full)
        for fn in root_spec.get("files", []):
            full = os.path.abspath(os.path.join(base, fn))
            if full in vistos or not _archivo_incluible_respaldo_codigo(full):
                continue
            vistos.add(full)
            archivos.append(full)
    return sorted(archivos)


DIR_RESPALDO_CODIGO = "/root/backups/codigo"
MAX_RESPALDOS_CODIGO_POR_SLUG = 6


def _dir_respaldo_codigo():
    os.makedirs(DIR_RESPALDO_CODIGO, exist_ok=True)
    return DIR_RESPALDO_CODIGO


def _podar_respaldos_codigo(slug):
    """Conserva solo los últimos N archivos de código por ERP."""
    carpeta = _dir_respaldo_codigo()
    pref = f"codigo_{slug}_"
    archivos = sorted(
        [
            os.path.join(carpeta, n)
            for n in os.listdir(carpeta)
            if n.startswith(pref) and (n.endswith(".zip") or n.endswith(".tar.gz"))
        ],
        key=lambda p: os.path.getmtime(p),
        reverse=True,
    )
    for viejo in archivos[MAX_RESPALDOS_CODIGO_POR_SLUG:]:
        try:
            os.remove(viejo)
        except OSError:
            pass


def crear_archivo_respaldo_codigo(spec):
    """ZIP en /root/backups/codigo (también se adjunta al correo)."""
    import zipfile

    archivos = recolectar_archivos_codigo(spec)
    if not archivos:
        raise FileNotFoundError(f"No hay archivos para respaldar en {spec.get('nombre', 'ERP')}")
    slug = spec.get("slug") or _slug_archivo(spec.get("nombre", "erp"))
    cuando = hora_chile()
    nombre = f"codigo_{slug}_{cuando.strftime('%Y%m%d_%H%M%S')}.zip"
    zip_path = os.path.join(_dir_respaldo_codigo(), nombre)
    manifest = []
    try:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in archivos:
                arcname = path.lstrip("/")
                zf.write(path, arcname=arcname)
                manifest.append(arcname)
            zf.writestr("MANIFEST.txt", "\n".join(manifest))
        _podar_respaldos_codigo(slug)
        return zip_path, len(archivos)
    except Exception:
        if os.path.exists(zip_path):
            os.remove(zip_path)
        raise


def debe_enviar_respaldo_codigo_hoy(config, hoy=None):
    # activo_codigo (rubro); fallback a activo solo si no viene la clave nueva
    if "activo_codigo" in config:
        if not config.get("activo_codigo"):
            return False
    elif not config.get("activo"):
        return False
    if not normalizar_correos(config.get("email", "")):
        return False
    hoy = hoy or hora_chile().date()
    d_ultimo = _fecha_ultimo_envio_chile(config.get("ultimo_envio_codigo"))
    return _corresponde_frecuencia(config.get("frecuencia_codigo", "semanal"), d_ultimo, hoy)


def _enviar_smtp_mensaje(smtp_conf, destinatarios, msg):
    server = smtplib.SMTP("smtp.gmail.com", 587, timeout=180)
    server.starttls()
    server.login(smtp_conf["emisor"], smtp_conf["clave"])
    server.sendmail(smtp_conf["emisor"], destinatarios, msg.as_string())
    server.quit()


CLAVE_CIFRADO_CODIGO = "ErpmasterCodigo2026"


def _cifrar_archivo_codigo(ruta_zip):
    """AES para que Gmail acepte el adjunto (bloquea ZIP/tar con .py)."""
    import subprocess

    ruta_enc = ruta_zip + ".enc"
    subprocess.check_call(
        [
            "openssl",
            "enc",
            "-aes-256-cbc",
            "-pbkdf2",
            "-salt",
            "-in",
            ruta_zip,
            "-out",
            ruta_enc,
            "-pass",
            f"pass:{CLAVE_CIFRADO_CODIGO}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return ruta_enc


# Gmail limita el mensaje ~25 MB; el adjunto en base64 crece ~33%.
# Tope seguro del .enc (~14 MB → ~18.6 MB en tránsito).
MAX_ADJUNTO_CODIGO_ENC_KB = 14000


def enviar_respaldo_codigo_correo(
    nombre_erp,
    destinatarios,
    smtp_conf,
    archivo_tar,
    n_archivos,
    cuando=None,
    producto=None,
):
    """Correo con adjunto cifrado, o aviso sin adjunto si supera el tope seguro de Gmail."""
    from erp_correo_html import plantilla_correo_html, producto_correo

    cuando = cuando or hora_chile()
    fecha_txt = cuando.strftime("%d-%m-%Y %H:%M")
    destinatarios = normalizar_correos(*destinatarios)
    if not destinatarios or not smtp_conf:
        return False, "Faltan destinatarios o configuración SMTP."
    if not archivo_tar or not os.path.isfile(archivo_tar):
        return False, "No se encontró el archivo de respaldo en el servidor."

    prod = producto_correo(nombre_erp, producto=producto)
    nombre_zip = os.path.basename(archivo_tar)
    asunto = f"[{nombre_erp}] Respaldo de código {cuando.strftime('%d-%m-%Y')}"
    tamano_zip_kb = os.path.getsize(archivo_tar) / 1024.0

    # Cifrar siempre (queda en VPS junto al ZIP).
    try:
        ruta_enc = _cifrar_archivo_codigo(archivo_tar)
    except Exception as e:
        return False, f"No se pudo cifrar el respaldo para adjunto: {e}"[:300]
    nombre_enc = os.path.basename(ruta_enc)
    tamano_enc_kb = os.path.getsize(ruta_enc) / 1024.0
    b64_mb = (os.path.getsize(ruta_enc) * 4 / 3) / (1024 * 1024)
    adjuntar = tamano_enc_kb <= MAX_ADJUNTO_CODIGO_ENC_KB

    if adjuntar:
        bloque_adj = (
            f"<p><b>Adjunto:</b> {nombre_enc} ({tamano_enc_kb:.1f} KB · "
            f"{n_archivos} archivos en el ZIP interno)</p>"
        )
        titulo_mail = "🗂️ Respaldo de código"
    else:
        bloque_adj = f"""
            <p style="color:#b71c1c;line-height:1.5;">
              <b>Sin adjunto:</b> el archivo cifrado pesa {tamano_enc_kb:.0f} KB
              (~{b64_mb:.1f} MB en correo) y supera el tope seguro de Gmail (~25 MB).
              El ZIP quedó en el VPS (abajo). SMTP a veces “acepta” el envío y luego
              el mensaje no llega a la bandeja.
            </p>
            <p><b>Archivo cifrado en VPS:</b> <code>{ruta_enc}</code>
              ({tamano_enc_kb:.1f} KB · ZIP {tamano_zip_kb:.1f} KB · {n_archivos} archivos)</p>
        """
        titulo_mail = "🗂️ Respaldo de código (aviso — sin adjunto)"
        asunto = f"[{nombre_erp}] Respaldo de código listo en VPS {cuando.strftime('%d-%m-%Y')}"

    interior = f"""
            <p><b>Fecha del respaldo:</b> {fecha_txt} (hora Chile)</p>
            {bloque_adj}
            <p><b>Copia ZIP en el VPS:</b> <code>{archivo_tar}</code></p>
            <p style="color:#555;line-height:1.5;">
                Gmail bloquea ZIP/tar con código fuente, por eso el archivo va
                <b>cifrado AES</b>. Clave:
                <code>{CLAVE_CIFRADO_CODIGO}</code>
            </p>
            <p style="color:#555;line-height:1.5;">
                Para abrir en Mac/Linux:<br>
                <code>openssl enc -d -aes-256-cbc -pbkdf2 -in {nombre_enc} -out {nombre_zip} -pass pass:{CLAVE_CIFRADO_CODIGO}</code>
            </p>
            <p style="color:#555;line-height:1.5;">
                Incluye código Python Flask, scripts, unit files y
                <code>static/</code>. <b>No incluye</b> bases de datos ni claves SMTP.
            </p>
    """
    cuerpo = plantilla_correo_html(
        "respaldo_codigo",
        titulo_mail,
        interior,
        nombre_erp=nombre_erp,
        pie="Generado automáticamente por ERP Master. Programación: todos los viernes.",
        producto=prod,
    )
    try:
        msg = MIMEMultipart()
        msg["From"] = smtp_conf["from_header"]
        msg["To"] = ", ".join(destinatarios)
        msg["Subject"] = asunto
        msg.attach(MIMEText(cuerpo, "html", "utf-8"))
        if adjuntar:
            with open(ruta_enc, "rb") as f:
                part = MIMEApplication(f.read(), Name=nombre_enc)
            part["Content-Disposition"] = f'attachment; filename="{nombre_enc}"'
            msg.attach(part)
        _enviar_smtp_mensaje(smtp_conf, destinatarios, msg)
        if adjuntar:
            return True, ""
        return True, (
            f"aviso_sin_adjunto ({tamano_enc_kb:.0f} KB enc ≈ {b64_mb:.1f} MB en correo)"
        )
    except Exception as e:
        # Si falla el adjunto por tamaño, reintenta aviso liviano.
        err = str(e)[:300]
        if adjuntar:
            try:
                interior_fb = f"""
            <p><b>Fecha del respaldo:</b> {fecha_txt} (hora Chile)</p>
            <p style="color:#b71c1c;line-height:1.5;">
              <b>El adjunto no pudo enviarse</b> ({err}). El ZIP quedó en el VPS.
            </p>
            <p><b>Copia ZIP en el VPS:</b> <code>{archivo_tar}</code></p>
            <p><b>Archivo cifrado:</b> <code>{ruta_enc}</code></p>
            <p style="color:#555;line-height:1.5;">
                Clave AES: <code>{CLAVE_CIFRADO_CODIGO}</code><br>
                <code>openssl enc -d -aes-256-cbc -pbkdf2 -in {nombre_enc} -out {nombre_zip} -pass pass:{CLAVE_CIFRADO_CODIGO}</code>
            </p>
                """
                cuerpo_fb = plantilla_correo_html(
                    "respaldo_codigo",
                    "🗂️ Respaldo de código (aviso — sin adjunto)",
                    interior_fb,
                    nombre_erp=nombre_erp,
                    pie="Generado automáticamente por ERP Master.",
                    producto=prod,
                )
                msg2 = MIMEMultipart()
                msg2["From"] = smtp_conf["from_header"]
                msg2["To"] = ", ".join(destinatarios)
                msg2["Subject"] = (
                    f"[{nombre_erp}] Respaldo de código listo en VPS "
                    f"{cuando.strftime('%d-%m-%Y')}"
                )
                msg2.attach(MIMEText(cuerpo_fb, "html", "utf-8"))
                _enviar_smtp_mensaje(smtp_conf, destinatarios, msg2)
                return True, f"aviso_sin_adjunto_fallback: {err}"
            except Exception as e2:
                return False, f"{err} | fallback: {str(e2)[:120]}"
        return False, err



def ejecutar_respaldo_codigo_rubro(rubro, forzar=False, usuario="SISTEMA", email_override=None):
    """Un zip de codigo por rubro (agricola|comercial). Config en erp_status JSON."""
    rubro = (rubro or "").strip().lower()
    spec = spec_respaldo_codigo_por_rubro(rubro)
    if not spec:
        return {"ok": False, "motivo": "sin_spec", "error": f"Rubro no configurado: {rubro}"}

    meta = load_codigo_rubro_meta(rubro)
    email = (email_override or meta.get("email") or "").strip()
    if not email:
        email = email_default_desde_secrets(spec.get("secrets") or "") or ""
    config = {
        "email": email,
        "activo_codigo": bool(meta.get("activo")),
        "frecuencia_codigo": meta.get("frecuencia") or "semanal",
        "ultimo_envio_codigo": meta.get("ultimo_envio") or "",
    }
    if not forzar and not debe_enviar_respaldo_codigo_hoy(config):
        return {"ok": False, "motivo": "no_corresponde", "config": config, "rubro": rubro}

    destinatarios = normalizar_correos(email)
    if not destinatarios:
        return {"ok": False, "motivo": "sin_correo", "config": config, "rubro": rubro}

    secrets_path = spec.get("secrets") or ""
    smtp = cargar_smtp(secrets_path)
    if not smtp:
        err = "SMTP no configurado en secrets.toml"
        save_codigo_rubro_meta(rubro, {"ultimo_error": err})
        return {"ok": False, "motivo": "smtp", "error": err, "config": config, "rubro": rubro}

    tar_path = None
    nombre_erp = spec.get("nombre", f"Codigo {rubro}")
    try:
        tar_path, n_arch = crear_archivo_respaldo_codigo(spec)
        ok, err = enviar_respaldo_codigo_correo(
            nombre_erp, destinatarios, smtp, tar_path, n_arch, producto=rubro,
        )
        if not ok:
            save_codigo_rubro_meta(rubro, {"ultimo_error": err, "ultimo_archivo": tar_path or ""})
            return {
                "ok": False, "motivo": "envio", "error": err,
                "config": config, "archivo": tar_path, "rubro": rubro,
            }
        ahora = hora_chile().strftime("%Y-%m-%d %H:%M:%S")
        nota_aviso = (err or "").strip()
        save_codigo_rubro_meta(
            rubro,
            {
                "ultimo_envio": ahora,
                # Si hubo aviso sin adjunto, queda visible en consola (no es fallo duro).
                "ultimo_error": nota_aviso if nota_aviso.startswith("aviso_sin_adjunto") else "",
                "ultimo_archivo": tar_path or "",
                "email": email,
            },
        )
        # Espejo en DB canonica del rubro (bitacora / UI legado)
        db_path = spec.get("db") or ""
        if db_path and os.path.isfile(db_path):
            try:
                conn = sqlite3.connect(db_path, timeout=60)
                try:
                    meta_set(conn, META_CODIGO_ULTIMO_ENVIO, ahora)
                    meta_set(
                        conn,
                        META_CODIGO_ULTIMO_ERROR,
                        nota_aviso if nota_aviso.startswith("aviso_sin_adjunto") else "",
                    )
                    det = (
                        f"{nombre_erp} → {', '.join(destinatarios)} · {tar_path} "
                        f"({n_arch} archivos)"
                    )
                    if nota_aviso:
                        det = f"{det} · {nota_aviso}"
                    _registrar_bitacora(conn, usuario, "RESPALDO_CODIGO", det)
                    conn.commit()
                finally:
                    conn.close()
            except Exception:
                pass
        out = {
            "ok": True,
            "rubro": rubro,
            "config": {**config, "ultimo_envio_codigo": ahora},
            "destinatarios": destinatarios,
            "archivos": n_arch,
            "archivo": tar_path,
        }
        if nota_aviso:
            out["aviso"] = nota_aviso
        return out
    except Exception as e:
        err = str(e)[:300]
        save_codigo_rubro_meta(rubro, {"ultimo_error": err})
        return {"ok": False, "motivo": "excepcion", "error": err, "config": config, "rubro": rubro}


def ejecutar_respaldo_codigo(conn, spec, secrets_path, forzar=False, usuario="SISTEMA"):
    config = obtener_config_respaldo(conn)
    if not forzar and not debe_enviar_respaldo_codigo_hoy(config):
        return {"ok": False, "motivo": "no_corresponde", "config": config}
    destinatarios = normalizar_correos(config.get("email", ""))
    if not destinatarios:
        return {"ok": False, "motivo": "sin_correo", "config": config}
    smtp = cargar_smtp(secrets_path)
    if not smtp:
        err = "SMTP no configurado en secrets.toml"
        meta_set(conn, META_CODIGO_ULTIMO_ERROR, err)
        conn.commit()
        return {"ok": False, "motivo": "smtp", "error": err, "config": config}
    tar_path = None
    nombre_erp = spec.get("nombre", "ERP")
    try:
        tar_path, n_arch = crear_archivo_respaldo_codigo(spec)
        ok, err = enviar_respaldo_codigo_correo(
            nombre_erp,
            destinatarios,
            smtp,
            tar_path,
            n_arch,
            producto=spec.get("producto") or rubro_de_nombre_erp(nombre_erp) or None,
        )
        if not ok:
            meta_set(conn, META_CODIGO_ULTIMO_ERROR, err)
            conn.commit()
            _registrar_bitacora(conn, usuario, "FALLO_RESPALDO_CODIGO", err)
            return {"ok": False, "motivo": "envio", "error": err, "config": config, "archivo": tar_path}
        ahora = hora_chile().strftime("%Y-%m-%d %H:%M:%S")
        nota_aviso = (err or "").strip()
        meta_set(conn, META_CODIGO_ULTIMO_ENVIO, ahora)
        meta_set(
            conn,
            META_CODIGO_ULTIMO_ERROR,
            nota_aviso if nota_aviso.startswith("aviso_sin_adjunto") else "",
        )
        conn.commit()
        det = f"{nombre_erp} → {', '.join(destinatarios)} · VPS:{tar_path} ({n_arch} archivos)"
        if nota_aviso:
            det = f"{det} · {nota_aviso}"
        else:
            det = f"{nombre_erp} → {', '.join(destinatarios)} · adjunto + VPS:{tar_path} ({n_arch} archivos)"
        _registrar_bitacora(conn, usuario, "RESPALDO_CODIGO", det)
        config = obtener_config_respaldo(conn)
        return {
            "ok": True,
            "config": config,
            "destinatarios": destinatarios,
            "archivos": n_arch,
            "archivo": tar_path,
        }
    except Exception as e:
        err = str(e)[:300]
        meta_set(conn, META_CODIGO_ULTIMO_ERROR, err)
        conn.commit()
        _registrar_bitacora(conn, usuario, "FALLO_RESPALDO_CODIGO", err)
        return {"ok": False, "motivo": "excepcion", "error": err, "config": config}


def spec_respaldo_codigo_por_nombre(nombre_erp):
    """Resuelve spec de codigo por nombre ERP o por rubro (agricola|comercial)."""
    rubro = rubro_de_nombre_erp(nombre_erp)
    if rubro:
        return spec_respaldo_codigo_por_rubro(rubro)
    clave = (nombre_erp or "").strip().lower()
    for spec in SPECS_RESPALDO_CODIGO:
        if spec["nombre"].strip().lower() == clave:
            return spec
    return None


def debe_enviar_respaldo_hoy(config, hoy=None):
    if not config.get("activo"):
        return False
    if not normalizar_correos(config.get("email", "")):
        return False
    hoy = hoy or hora_chile().date()
    d_ultimo = _fecha_ultimo_envio_chile(config.get("ultimo_envio"))
    return _corresponde_frecuencia(config.get("frecuencia", "diario"), d_ultimo, hoy)


def cargar_smtp(secrets_path):
    try:
        from erp_correo_html import smtp_from_header

        conf = _cargar_toml(secrets_path).get("gmail_smtp", {})
        clave = conf.get("clave_application") or conf.get("clave_aplicacion")
        emisor = conf.get("correo_emisor", "").strip()
        if not clave or not emisor:
            return None
        nombre = conf.get("nombre_emisor", "ERPMASTER")
        return {
            "emisor": emisor,
            "clave": clave,
            "from_header": smtp_from_header(emisor, nombre),
        }
    except Exception:
        return None


def crear_archivo_respaldo(db_path):
    """Copia consistente SQLite (.backup) comprimida en gzip. Devuelve ruta temporal."""
    db_path = os.path.abspath(db_path)
    if not os.path.isfile(db_path):
        raise FileNotFoundError(f"No existe la base de datos: {db_path}")
    fd, gz_path = tempfile.mkstemp(suffix=".db.gz", prefix="erp_respaldo_")
    os.close(fd)
    tmp_plain = gz_path[:-3] if gz_path.endswith(".gz") else gz_path + ".db"
    try:
        src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=60)
        dst = sqlite3.connect(tmp_plain)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        with open(tmp_plain, "rb") as f_in, gzip.open(gz_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        return gz_path
    finally:
        if os.path.exists(tmp_plain):
            os.remove(tmp_plain)


def _slug_archivo(nombre_erp):
    base = "".join(c if c.isalnum() else "_" for c in nombre_erp.lower())
    return base.strip("_")[:40] or "erp"


def enviar_respaldo_correo(nombre_erp, destinatarios, smtp_conf, archivo_gz, cuando=None):
    from erp_correo_html import plantilla_correo_html

    cuando = cuando or hora_chile()
    fecha_txt = cuando.strftime("%d-%m-%Y %H:%M")
    fecha_arch = cuando.strftime("%Y%m%d")
    destinatarios = normalizar_correos(*destinatarios)
    if not destinatarios or not smtp_conf:
        return False, "Faltan destinatarios o configuración SMTP."
    tamano_kb = os.path.getsize(archivo_gz) / 1024.0
    slug = _slug_archivo(nombre_erp)
    nombre_adj = f"respaldo_{slug}_{fecha_arch}.db.gz"
    asunto = f"[{nombre_erp}] Respaldo de datos {cuando.strftime('%d-%m-%Y')}"
    interior = f"""
            <p><b>Fecha del respaldo:</b> {fecha_txt} (hora Chile)</p>
            <p><b>Archivo adjunto:</b> {nombre_adj} ({tamano_kb:.1f} KB)</p>
            <p style="color:#555;line-height:1.5;">
                Copia de la base SQLite del ERP. Guárdela en un lugar seguro.
                Para restaurar, reemplace el archivo <code>.db</code> del servidor deteniendo antes el servicio.
            </p>
    """
    from erp_correo_html import producto_correo

    cuerpo = plantilla_correo_html(
        "respaldo_datos",
        "💾 Respaldo de base de datos",
        interior,
        nombre_erp=nombre_erp,
        pie="Generado automáticamente por ERP Master.",
        producto=producto_correo(nombre_erp),
    )
    try:
        msg = MIMEMultipart()
        msg["From"] = smtp_conf["from_header"]
        msg["To"] = ", ".join(destinatarios)
        msg["Subject"] = asunto
        msg.attach(MIMEText(cuerpo, "html", "utf-8"))
        with open(archivo_gz, "rb") as f:
            part = MIMEApplication(f.read(), Name=nombre_adj)
        part["Content-Disposition"] = f'attachment; filename="{nombre_adj}"'
        msg.attach(part)
        server = smtplib.SMTP("smtp.gmail.com", 587, timeout=60)
        server.starttls()
        server.login(smtp_conf["emisor"], smtp_conf["clave"])
        server.sendmail(smtp_conf["emisor"], destinatarios, msg.as_string())
        server.quit()
        return True, ""
    except Exception as e:
        return False, str(e)[:300]


def _registrar_bitacora(conn, usuario, accion, detalle):
    try:
        f_h = hora_chile().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)",
            (usuario or "SISTEMA", accion, (detalle or "")[:500], f_h),
        )
        conn.commit()
    except Exception:
        pass


def ejecutar_respaldo(conn, nombre_erp, db_path, secrets_path, forzar=False, usuario="SISTEMA"):
    config = obtener_config_respaldo(conn)
    if not forzar and not debe_enviar_respaldo_hoy(config):
        return {"ok": False, "motivo": "no_corresponde", "config": config}
    destinatarios = normalizar_correos(config.get("email", ""))
    if not destinatarios:
        return {"ok": False, "motivo": "sin_correo", "config": config}
    smtp = cargar_smtp(secrets_path)
    if not smtp:
        err = "SMTP no configurado en secrets.toml"
        meta_set(conn, META_ULTIMO_ERROR, err)
        conn.commit()
        return {"ok": False, "motivo": "smtp", "error": err, "config": config}
    gz_path = None
    try:
        gz_path = crear_archivo_respaldo(db_path)
        ok, err = enviar_respaldo_correo(nombre_erp, destinatarios, smtp, gz_path)
        if not ok:
            meta_set(conn, META_ULTIMO_ERROR, err)
            conn.commit()
            _registrar_bitacora(conn, usuario, "FALLO_RESPALDO", err)
            return {"ok": False, "motivo": "envio", "error": err, "config": config}
        ahora = hora_chile().strftime("%Y-%m-%d %H:%M:%S")
        meta_set(conn, META_ULTIMO_ENVIO, ahora)
        meta_set(conn, META_ULTIMO_ERROR, "")
        conn.commit()
        det = f"{nombre_erp} → {', '.join(destinatarios)}"
        _registrar_bitacora(conn, usuario, "RESPALDO_DATOS", det)
        config = obtener_config_respaldo(conn)
        return {"ok": True, "config": config, "destinatarios": destinatarios}
    except Exception as e:
        err = str(e)[:300]
        meta_set(conn, META_ULTIMO_ERROR, err)
        conn.commit()
        _registrar_bitacora(conn, usuario, "FALLO_RESPALDO", err)
        return {"ok": False, "motivo": "excepcion", "error": err, "config": config}
    finally:
        if gz_path and os.path.exists(gz_path):
            try:
                os.remove(gz_path)
            except OSError:
                pass


def render_admin_respaldo_datos(conn, nombre_erp, db_path, secrets_path):
    import streamlit as st

    st.markdown("#### Respaldo por correo")
    st.caption(
        "Envía al **mismo correo** una copia de la base de datos (`.db.gz`) y del código (`.tar.gz`). "
        "El cron del servidor revisa ambos **todos los días a las 03:00** (hora Chile) según la frecuencia de cada uno."
    )
    config = obtener_config_respaldo(conn)
    spec_codigo = spec_respaldo_codigo_por_nombre(nombre_erp)

    with st.form("cfg_respaldo_unificado"):
        email_in = st.text_input(
            "Correo destino",
            value=config["email"],
            placeholder="correo@ejemplo.cl",
            help="Recibirá aquí los respaldos de datos y de código.",
        )
        activo_in = st.checkbox("Envío automático activo", value=config["activo"])
        c_dat, c_cod = st.columns(2)
        idx_freq_dat = FRECUENCIAS_RESPALDO.index(config["frecuencia"])
        idx_freq_cod = FRECUENCIAS_RESPALDO.index(config["frecuencia_codigo"])
        with c_dat:
            st.markdown("**💾 Respaldo de datos**")
            st.caption("Base SQLite completa del ERP.")
            freq_datos_in = st.selectbox(
                "Frecuencia datos",
                FRECUENCIAS_RESPALDO,
                index=idx_freq_dat,
                format_func=lambda x: FRECUENCIAS_ETIQUETA.get(x, x),
                key="cfg_freq_datos",
            )
        with c_cod:
            st.markdown("**🗂️ Respaldo de código**")
            st.caption("Python, static/ y configs (sin secretos).")
            freq_codigo_in = st.selectbox(
                "Frecuencia código",
                FRECUENCIAS_RESPALDO,
                index=idx_freq_cod,
                format_func=lambda x: FRECUENCIAS_ETIQUETA.get(x, x),
                key="cfg_freq_codigo",
            )
        if st.form_submit_button("💾 GUARDAR CONFIGURACIÓN"):
            if activo_in and not normalizar_correos(email_in):
                st.error("Ingrese un correo válido para activar el respaldo automático.")
            else:
                guardar_config_respaldo(conn, email_in, freq_datos_in, freq_codigo_in, activo_in)
                registrar = st.session_state.get("email", "admin")
                det = (
                    f"datos={freq_datos_in}, código={freq_codigo_in} → {email_in.strip()}"
                )
                _registrar_bitacora(conn, registrar, "CONFIG_RESPALDO", det)
                st.success("Configuración de respaldo guardada.")
                st.rerun()

    st.divider()
    col_est_dat, col_est_cod = st.columns(2)
    with col_est_dat:
        st.markdown("**Estado · datos**")
        st.info(formatear_ultimo_respaldo(config))
        if config.get("ultimo_error"):
            st.warning(f"Último error datos: {config['ultimo_error']}")
        if st.button("📧 Enviar datos ahora", type="primary", key="btn_respaldo_manual"):
            if not normalizar_correos(config.get("email", "")):
                st.error("Configure un correo destino antes de enviar.")
            else:
                usuario = st.session_state.get("email", "admin")
                with st.spinner(f"Generando respaldo de datos de {nombre_erp}…"):
                    res = ejecutar_respaldo(
                        conn, nombre_erp, db_path, secrets_path, forzar=True, usuario=usuario,
                    )
                if res.get("ok"):
                    st.success(
                        f"✅ Datos de **{nombre_erp}** enviados a "
                        f"{', '.join(res.get('destinatarios', []))}."
                    )
                    st.rerun()
                else:
                    motivo = res.get("motivo", "")
                    if motivo == "smtp":
                        st.error(f"No hay SMTP configurado: {res.get('error', '')}")
                    else:
                        st.error(f"No se pudo enviar datos: {res.get('error', motivo)}")

    with col_est_cod:
        st.markdown("**Estado · código**")
        st.info(formatear_ultimo_respaldo_codigo(config))
        if config.get("ultimo_error_codigo"):
            st.warning(f"Último error código: {config['ultimo_error_codigo']}")
        if st.button("📧 Enviar código ahora", key="btn_respaldo_codigo_manual"):
            if not spec_codigo:
                st.error("No hay definición de respaldo de código para este ERP.")
            elif not normalizar_correos(config.get("email", "")):
                st.error("Configure un correo destino antes de enviar.")
            else:
                usuario = st.session_state.get("email", "admin")
                with st.spinner(f"Empaquetando código de {nombre_erp}…"):
                    res = ejecutar_respaldo_codigo(
                        conn, spec_codigo, secrets_path, forzar=True, usuario=usuario,
                    )
                if res.get("ok"):
                    st.success(
                        f"✅ Código de **{nombre_erp}** enviado con adjunto a "
                        f"{', '.join(res.get('destinatarios', []))} "
                        f"({res.get('archivos', 0)} archivos). "
                        f"Copia en VPS: `{res.get('archivo', DIR_RESPALDO_CODIGO)}`."
                    )
                    st.rerun()
                else:
                    motivo = res.get("motivo", "")
                    if motivo == "smtp":
                        st.error(f"No hay SMTP configurado: {res.get('error', '')}")
                    else:
                        st.error(f"No se pudo enviar código: {res.get('error', motivo)}")
