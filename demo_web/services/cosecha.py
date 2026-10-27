"""Cosecha de contratistas: fundas y totes por cuartel.

La faena cuelga de un contratista. El número de funda es de esa faena:
si el cosechero se va, el número muere y el siguiente usa el correlativo.
Cada cuartel tiene su propio enlace. El gasto no sale de aquí: se anota
en Registrar servicio.
"""
from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime
from typing import Any, Callable

from demo_web.services.espino_scope import VARIEDADES_ESPINO

# Centros de costo de La Concepción que no son un cuartel de cosecha.
_FUERA_DE_COSECHA = frozenset({"EL ESPINO", "OTROS", "OTRO"})
_VARIEDADES_ESPINO = {v.upper(): v for v in VARIEDADES_ESPINO}


def filtrar_cuarteles_cosecha(cuarteles: list[str], *, espino: bool) -> list[str]:
    """Cuarteles de la faena según el tenant. El Espino no hereda los de La Concepción."""
    if espino:
        presentes = {str(c).strip().upper() for c in cuarteles if str(c).strip()}
        return [v for v in VARIEDADES_ESPINO if v.upper() in presentes]
    salida: list[str] = []
    vistos: set[str] = set()
    for crudo in cuarteles:
        nombre = str(crudo).strip()
        if not nombre or nombre.upper() in _FUERA_DE_COSECHA:
            continue
        clave = nombre.upper()
        if clave in vistos or clave in _VARIEDADES_ESPINO:
            continue
        vistos.add(clave)
        salida.append(nombre)
    return salida


def cuarteles_de_cosecha(demo: Any) -> list[str]:
    from demo_web.services.tenant_scope import cuarteles_oficiales, is_espino_tenant

    return filtrar_cuarteles_cosecha(
        list(cuarteles_oficiales(demo) or []),
        espino=is_espino_tenant(),
    )


_TABLAS_COSECHA = (
    """CREATE TABLE IF NOT EXISTS cosecha_faena (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contratista_id INTEGER NOT NULL,
            estado TEXT NOT NULL DEFAULT 'abierta',
            creada TEXT NOT NULL,
            cerrada TEXT
        );
        CREATE TABLE IF NOT EXISTS cosecha_funda (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            faena_id INTEGER NOT NULL,
            numero INTEGER NOT NULL,
            nombre TEXT NOT NULL DEFAULT '',
            rut TEXT NOT NULL DEFAULT '',
            estado TEXT NOT NULL DEFAULT 'activa',
            asignado INTEGER NOT NULL DEFAULT 0,
            UNIQUE(faena_id, numero)
        );
        CREATE TABLE IF NOT EXISTS cosecha_link (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            faena_id INTEGER NOT NULL,
            cuartel TEXT NOT NULL,
            token TEXT NOT NULL UNIQUE,
            UNIQUE(faena_id, cuartel)
        );
        CREATE TABLE IF NOT EXISTS cosecha_precio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            faena_id INTEGER NOT NULL,
            cuartel TEXT NOT NULL,
            precio REAL NOT NULL DEFAULT 0,
            UNIQUE(faena_id, cuartel)
        );
        CREATE TABLE IF NOT EXISTS cosecha_tote (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            faena_id INTEGER NOT NULL,
            funda_id INTEGER NOT NULL,
            cuartel TEXT NOT NULL,
            anulado INTEGER NOT NULL DEFAULT 0,
            creado TEXT NOT NULL,
            fecha TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS cosecha_abono (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            faena_id INTEGER NOT NULL,
            cuartel TEXT NOT NULL,
            monto REAL NOT NULL,
            nota TEXT NOT NULL DEFAULT '',
            fecha TEXT NOT NULL,
            factura_abono_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS cosecha_cierre (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            faena_id INTEGER NOT NULL,
            cuartel TEXT NOT NULL,
            factura_id INTEGER,
            nro_documento TEXT,
            totes INTEGER NOT NULL,
            precio REAL NOT NULL,
            bruto REAL NOT NULL,
            cerrado TEXT NOT NULL,
            UNIQUE(faena_id, cuartel)
        )""",
)


def asegurar_tablas(conn: sqlite3.Connection) -> None:
    # execute(), no executescript(): este último hace COMMIT y soltaría el cierre.
    for sql in _TABLAS_COSECHA:
        for parte in sql.split(";"):
            stmt = parte.strip()
            if stmt:
                conn.execute(stmt)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(cosecha_funda)")}
    if cols and "rut" not in cols:
        conn.execute("ALTER TABLE cosecha_funda ADD COLUMN rut TEXT NOT NULL DEFAULT ''")
    if cols and "asignado" not in cols:
        conn.execute("ALTER TABLE cosecha_funda ADD COLUMN asignado INTEGER NOT NULL DEFAULT 0")
    if cols:
        conn.execute(
            """UPDATE cosecha_funda
               SET asignado=1
               WHERE asignado=0
                 AND TRIM(COALESCE(nombre, '')) <> ''
                 AND TRIM(COALESCE(rut, '')) <> ''"""
        )
    tote_cols = {r[1] for r in conn.execute("PRAGMA table_info(cosecha_tote)")}
    if tote_cols and "fecha" not in tote_cols:
        conn.execute("ALTER TABLE cosecha_tote ADD COLUMN fecha TEXT NOT NULL DEFAULT ''")
    if tote_cols or "fecha" in {r[1] for r in conn.execute("PRAGMA table_info(cosecha_tote)")}:
        conn.execute(
            """UPDATE cosecha_tote
               SET fecha = substr(creado, 1, 10)
               WHERE COALESCE(fecha, '') = '' AND length(COALESCE(creado, '')) >= 10"""
        )


def _dia(fecha: str, fecha_hora: str = "") -> tuple[bool, str, str]:
    texto = (fecha or "").strip()
    if not texto and len(fecha_hora or "") >= 10:
        texto = fecha_hora[:10]
    partes = texto.split("-")
    if len(partes) != 3 or any(not p.isdigit() for p in partes):
        return False, "Elija la fecha.", ""
    anio, mes, dia = (int(p) for p in partes)
    try:
        datetime(anio, mes, dia)
    except ValueError:
        return False, "La fecha no es válida.", ""
    if anio < 2020 or anio > 2100:
        return False, "La fecha no es válida.", ""
    return True, "", f"{anio:04d}-{mes:02d}-{dia:02d}"


def _fecha_sql(alias: str = "") -> str:
    col = f"{alias}fecha" if alias else "fecha"
    creado = f"{alias}creado" if alias else "creado"
    return (
        f"CASE WHEN COALESCE({col}, '') <> '' THEN {col} ELSE substr({creado}, 1, 10) END"
    )


def _nombre(raw: str, *, obligatorio: bool) -> tuple[bool, str, str]:
    nombre = " ".join((raw or "").split())
    if len(nombre) > 80:
        nombre = nombre[:80].rstrip()
    if obligatorio and not nombre:
        return False, "Escriba el nombre del cosechero.", ""
    return True, "", nombre


def _una(conn: sqlite3.Connection, sql: str, params: tuple) -> dict | None:
    cur = conn.execute(sql, params)
    row = cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def _faena(conn: sqlite3.Connection, faena_id: int) -> dict | None:
    return _una(conn, "SELECT * FROM cosecha_faena WHERE id=?", (int(faena_id),))


def faena_abierta(conn: sqlite3.Connection, contratista_id: int) -> int:
    asegurar_tablas(conn)
    row = conn.execute(
        """SELECT id FROM cosecha_faena
           WHERE contratista_id=? AND estado='abierta'
           ORDER BY id DESC LIMIT 1""",
        (int(contratista_id),),
    ).fetchone()
    return int(row[0]) if row else 0


def listar_faenas(conn: sqlite3.Connection, contratista_id: int) -> list[dict]:
    asegurar_tablas(conn)
    rows = conn.execute(
        """SELECT id, estado, creada, cerrada FROM cosecha_faena
           WHERE contratista_id=? ORDER BY id DESC""",
        (int(contratista_id),),
    ).fetchall()
    return [
        {
            "id": int(r[0]),
            "estado": r[1],
            "creada": r[2] or "",
            "cerrada": r[3] or "",
            "abierta": r[1] == "abierta",
        }
        for r in rows
    ]


def _token_link() -> str:
    return secrets.token_urlsafe(16)


def asegurar_links(conn: sqlite3.Connection, faena_id: int, cuarteles: list[str]) -> None:
    asegurar_tablas(conn)
    for cuartel in cuarteles:
        nombre = str(cuartel).strip()
        if not nombre:
            continue
        conn.execute(
            """INSERT OR IGNORE INTO cosecha_link (faena_id, cuartel, token)
               VALUES (?,?,?)""",
            (int(faena_id), nombre, _token_link()),
        )


def abrir_faena(
    conn: sqlite3.Connection,
    contratista_id: int,
    cuarteles: list[str],
    fecha: str,
) -> tuple[bool, str, int]:
    asegurar_tablas(conn)
    if int(contratista_id) <= 0:
        return False, "Elija el contratista.", 0
    bloques = [str(c).strip() for c in cuarteles if str(c).strip()]
    if not bloques:
        return False, "Esta empresa no tiene cuarteles de cosecha.", 0
    if faena_abierta(conn, contratista_id):
        return False, "Este contratista ya tiene una faena abierta.", 0
    cur = conn.execute(
        "INSERT INTO cosecha_faena (contratista_id, estado, creada) VALUES (?,?,?)",
        (int(contratista_id), "abierta", fecha),
    )
    faena_id = int(cur.lastrowid)
    asegurar_links(conn, faena_id, bloques)
    return True, "Faena abierta. Los números parten de 1.", faena_id


def _siguiente_numero(conn: sqlite3.Connection, faena_id: int) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(numero), 0) FROM cosecha_funda WHERE faena_id=?",
        (int(faena_id),),
    ).fetchone()
    return int(row[0] or 0) + 1


def fundas_en_blanco(conn: sqlite3.Connection, faena_id: int, cantidad: int) -> tuple[bool, str]:
    asegurar_tablas(conn)
    faena = _faena(conn, faena_id)
    if not faena or faena["estado"] != "abierta":
        return False, "La faena no está abierta."
    n = int(cantidad)
    if n < 1 or n > 60:
        return False, "Imprima entre 1 y 60 fundas a la vez."
    primero = _siguiente_numero(conn, faena_id)
    for i in range(n):
        conn.execute(
            "INSERT INTO cosecha_funda (faena_id, numero, nombre, estado) VALUES (?,?,?, 'activa')",
            (int(faena_id), primero + i, ""),
        )
    ultimo = primero + n - 1
    return True, f"Fundas {primero} a {ultimo} listas para imprimir."


def entregar_funda(conn: sqlite3.Connection, faena_id: int, nombre_raw: str) -> tuple[bool, str, int]:
    """Asigna el nombre a la primera funda libre, o abre el correlativo siguiente."""
    asegurar_tablas(conn)
    faena = _faena(conn, faena_id)
    if not faena or faena["estado"] != "abierta":
        return False, "La faena no está abierta.", 0
    ok, msg, nombre = _nombre(nombre_raw, obligatorio=True)
    if not ok:
        return False, msg, 0
    libre = conn.execute(
        """SELECT id, numero FROM cosecha_funda
           WHERE faena_id=? AND estado='activa' AND TRIM(nombre)=''
           ORDER BY numero ASC LIMIT 1""",
        (int(faena_id),),
    ).fetchone()
    if libre:
        conn.execute("UPDATE cosecha_funda SET nombre=? WHERE id=?", (nombre, int(libre[0])))
        return True, f"{nombre} quedó con el número {int(libre[1])}.", int(libre[1])
    numero = _siguiente_numero(conn, faena_id)
    conn.execute(
        "INSERT INTO cosecha_funda (faena_id, numero, nombre, estado) VALUES (?,?,?, 'activa')",
        (int(faena_id), numero, nombre),
    )
    return True, f"{nombre} quedó con el número {numero}.", numero


def poner_nombre(
    conn: sqlite3.Connection,
    faena_id: int,
    numero: int,
    nombre_raw: str,
    *,
    permitir_cambio: bool,
) -> tuple[bool, str]:
    asegurar_tablas(conn)
    ok, msg, nombre = _nombre(nombre_raw, obligatorio=True)
    if not ok:
        return False, msg
    row = conn.execute(
        "SELECT id, nombre, estado FROM cosecha_funda WHERE faena_id=? AND numero=?",
        (int(faena_id), int(numero)),
    ).fetchone()
    if not row:
        return False, "Ese número no está en esta faena."
    if row[2] != "activa":
        return False, f"El número {int(numero)} ya no se usa."
    actual = (row[1] or "").strip()
    if actual and not permitir_cambio:
        return False, f"El número {int(numero)} ya es de {actual}."
    conn.execute("UPDATE cosecha_funda SET nombre=? WHERE id=?", (nombre, int(row[0])))
    return True, f"Número {int(numero)}: {nombre}."


def dar_de_baja(conn: sqlite3.Connection, faena_id: int, numero: int) -> tuple[bool, str]:
    asegurar_tablas(conn)
    row = conn.execute(
        "SELECT id, estado, nombre FROM cosecha_funda WHERE faena_id=? AND numero=?",
        (int(faena_id), int(numero)),
    ).fetchone()
    if not row:
        return False, "Ese número no está en esta faena."
    if row[1] != "activa":
        return False, f"El número {int(numero)} ya estaba dado de baja."
    conn.execute("UPDATE cosecha_funda SET estado='muerta' WHERE id=?", (int(row[0]),))
    quien = (row[2] or "").strip() or "sin nombre"
    return True, f"El número {int(numero)} ({quien}) queda fuera. No se vuelve a usar."


def _link_por_token(conn: sqlite3.Connection, token: str) -> dict | None:
    asegurar_tablas(conn)
    tok = (token or "").strip()
    if not tok:
        return None
    return _una(conn, "SELECT * FROM cosecha_link WHERE token=?", (tok,))


def _funda(conn: sqlite3.Connection, faena_id: int, numero: int) -> dict | None:
    return _una(
        conn,
        "SELECT * FROM cosecha_funda WHERE faena_id=? AND numero=?",
        (int(faena_id), int(numero)),
    )


def _cerrado(conn: sqlite3.Connection, faena_id: int, cuartel: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM cosecha_cierre WHERE faena_id=? AND cuartel=?",
        (int(faena_id), cuartel),
    ).fetchone()
    return bool(row)


def contar_totes(conn: sqlite3.Connection, faena_id: int, cuartel: str, funda_id: int | None = None) -> int:
    sql = """SELECT COUNT(*) FROM cosecha_tote
             WHERE faena_id=? AND cuartel=? AND anulado=0"""
    params: list[Any] = [int(faena_id), cuartel]
    if funda_id is not None:
        sql += " AND funda_id=?"
        params.append(int(funda_id))
    row = conn.execute(sql, params).fetchone()
    return int(row[0] or 0)


def _totes_por_funda(conn: sqlite3.Connection, faena_id: int, cuartel: str) -> dict[int, int]:
    rows = conn.execute(
        """SELECT funda_id, COUNT(*) FROM cosecha_tote
           WHERE faena_id=? AND cuartel=? AND anulado=0
           GROUP BY funda_id""",
        (int(faena_id), cuartel),
    ).fetchall()
    return {int(r[0]): int(r[1]) for r in rows}


def listar_links(conn: sqlite3.Connection, faena_id: int) -> list[dict]:
    asegurar_tablas(conn)
    rows = conn.execute(
        "SELECT cuartel, token FROM cosecha_link WHERE faena_id=? ORDER BY id",
        (int(faena_id),),
    ).fetchall()
    return [{"cuartel": r[0], "token": r[1]} for r in rows]


def listar_fundas(conn: sqlite3.Connection, faena_id: int) -> list[dict]:
    asegurar_tablas(conn)
    rows = conn.execute(
        """SELECT id, numero, nombre, COALESCE(rut, ''), estado, COALESCE(asignado, 0)
           FROM cosecha_funda
           WHERE faena_id=? ORDER BY numero""",
        (int(faena_id),),
    ).fetchall()
    return [
        {
            "id": int(r[0]),
            "numero": int(r[1]),
            "nombre": r[2] or "",
            "rut": r[3] or "",
            "estado": r[4],
            "viva": r[4] == "activa",
            "asignado": int(r[5] or 0) == 1,
        }
        for r in rows
    ]


def validar_rut_cosecha(raw: str) -> tuple[bool, str, str]:
    """El mismo criterio que el resto del ERP. Vacío se permite."""
    try:
        from erp_rut import validar_rut_campo
    except ImportError:
        return _validar_rut_local(raw)
    return validar_rut_campo(raw or "", obligatorio=False)


def _validar_rut_local(raw: str) -> tuple[bool, str, str]:
    texto = (raw or "").strip().upper().replace(".", "").replace("-", "").replace(" ", "")
    if not texto:
        return True, "", ""
    if len(texto) < 2 or not texto[:-1].isdigit() or texto[-1] not in "0123456789K":
        return False, "RUT incorrecto. Verifique el número y el dígito verificador.", ""
    cuerpo, dv = texto[:-1], texto[-1]
    suma = 0
    factor = 2
    for digito in reversed(cuerpo):
        suma += int(digito) * factor
        factor = 2 if factor == 7 else factor + 1
    resto = 11 - (suma % 11)
    esperado = "0" if resto == 11 else "K" if resto == 10 else str(resto)
    if dv != esperado:
        return False, "RUT incorrecto. Verifique el número y el dígito verificador.", ""
    grupos = []
    while cuerpo:
        grupos.append(cuerpo[-3:])
        cuerpo = cuerpo[:-3]
    return True, "", ".".join(reversed(grupos)) + "-" + dv


def guardar_persona(
    conn: sqlite3.Connection,
    faena_id: int,
    numero: int,
    nombre_raw: str,
    rut_raw: str,
) -> tuple[bool, str]:
    asegurar_tablas(conn)
    try:
        n = int(numero)
    except (TypeError, ValueError):
        return False, "El número no es válido."
    funda = _funda(conn, faena_id, n)
    if not funda:
        return False, "Ese número todavía no entra por el enlace."
    if funda["estado"] != "activa":
        return False, f"El número {n} ya no se usa."
    if int(funda.get("asignado") or 0) == 1:
        return False, f"El número {n} ya está asignado."
    _ok, _msg, nombre = _nombre(nombre_raw, obligatorio=False)
    ok_rut, msg_rut, rut = validar_rut_cosecha(rut_raw)
    if not ok_rut:
        return False, msg_rut
    asignado = 1 if nombre and rut else 0
    conn.execute(
        "UPDATE cosecha_funda SET nombre=?, rut=?, asignado=? WHERE id=?",
        (nombre, rut, asignado, int(funda["id"])),
    )
    quien = nombre or "sin nombre"
    texto = f"Número {n} · {quien}"
    if rut:
        texto += f" · {rut}"
    if asignado:
        return True, f"{texto} quedó asignado."
    return True, f"{texto} quedó guardado. Falta el RUT para cerrar este número."


def planilla_numeros(
    conn: sqlite3.Connection,
    faena_id: int,
    *,
    numero: int | None = None,
    desde: str = "",
    hasta: str = "",
) -> list[dict]:
    """Lo que la anotadora ingresó por los enlaces, por número y cuartel."""
    asegurar_tablas(conn)
    cuarteles = [x["cuartel"] for x in listar_links(conn, faena_id)]
    expr = _fecha_sql()
    sql = f"""SELECT funda_id, cuartel, COUNT(*) FROM cosecha_tote
              WHERE faena_id=? AND anulado=0"""
    params: list[Any] = [int(faena_id)]
    if desde:
        sql += f" AND ({expr}) >= ?"
        params.append(desde)
    if hasta:
        sql += f" AND ({expr}) <= ?"
        params.append(hasta)
    sql += " GROUP BY funda_id, cuartel"
    cuentas: dict[int, dict[str, int]] = {}
    for funda_id, cuartel, n in conn.execute(sql, params).fetchall():
        cuentas.setdefault(int(funda_id), {})[str(cuartel)] = int(n)
    salida = []
    for funda in listar_fundas(conn, faena_id):
        if numero is not None and int(funda["numero"]) != int(numero):
            continue
        por = cuentas.get(int(funda["id"]), {})
        totes = {cc: int(por.get(cc, 0)) for cc in cuarteles}
        total = sum(totes.values())
        if numero is None and (desde or hasta) and total <= 0:
            continue
        salida.append({**funda, "totes": totes, "total": total})
    return salida


def detalle_ingresos(
    conn: sqlite3.Connection,
    faena_id: int,
    *,
    numero: int | None = None,
    desde: str = "",
    hasta: str = "",
) -> list[dict]:
    """Una fila por fecha, cosechero y cuartel. Es lo que anotó el enlace."""
    asegurar_tablas(conn)
    expr = _fecha_sql("t.")
    sql = f"""SELECT f.numero, f.nombre, COALESCE(f.rut, ''), t.cuartel, {expr} AS dia, COUNT(*)
              FROM cosecha_tote t
              JOIN cosecha_funda f ON f.id = t.funda_id
              WHERE t.faena_id=? AND t.anulado=0"""
    params: list[Any] = [int(faena_id)]
    if numero is not None:
        sql += " AND f.numero=?"
        params.append(int(numero))
    if desde:
        sql += f" AND ({expr}) >= ?"
        params.append(desde)
    if hasta:
        sql += f" AND ({expr}) <= ?"
        params.append(hasta)
    sql += f" GROUP BY f.numero, t.cuartel, {expr} ORDER BY dia DESC, f.numero, t.cuartel"
    filas = []
    for numero_f, nombre, rut, cuartel, dia, n in conn.execute(sql, params).fetchall():
        iso = str(dia or "")
        visible = f"{iso[8:10]}-{iso[5:7]}-{iso[0:4]}" if len(iso) == 10 else iso
        filas.append(
            {
                "numero": int(numero_f),
                "nombre": nombre or "",
                "rut": rut or "",
                "cuartel": cuartel or "",
                "fecha": iso,
                "fecha_txt": visible,
                "totes": int(n),
            }
        )
    return filas


def guardar_precio(conn: sqlite3.Connection, faena_id: int, cuartel: str, precio: float) -> tuple[bool, str]:
    asegurar_tablas(conn)
    if _cerrado(conn, faena_id, cuartel):
        return False, "Ese cuartel ya pasó a compras."
    monto = int(round(float(precio or 0)))
    if monto <= 0:
        return False, "El precio por tote tiene que ser mayor a cero."
    link = conn.execute(
        "SELECT 1 FROM cosecha_link WHERE faena_id=? AND cuartel=?",
        (int(faena_id), cuartel),
    ).fetchone()
    if not link:
        return False, "Ese cuartel no está en esta faena."
    conn.execute(
        """INSERT INTO cosecha_precio (faena_id, cuartel, precio) VALUES (?,?,?)
           ON CONFLICT(faena_id, cuartel) DO UPDATE SET precio=excluded.precio""",
        (int(faena_id), cuartel, monto),
    )
    return True, "Precio guardado."


def precio_cuartel(conn: sqlite3.Connection, faena_id: int, cuartel: str) -> int:
    row = conn.execute(
        "SELECT precio FROM cosecha_precio WHERE faena_id=? AND cuartel=?",
        (int(faena_id), cuartel),
    ).fetchone()
    return int(round(float(row[0]))) if row else 0


def registrar_abono(
    conn: sqlite3.Connection,
    faena_id: int,
    cuartel: str,
    monto: float,
    nota: str,
    fecha: str,
) -> tuple[bool, str]:
    asegurar_tablas(conn)
    if _cerrado(conn, faena_id, cuartel):
        return False, "Ese cuartel ya pasó a compras. El abono se anota en cuenta corriente."
    link = conn.execute(
        "SELECT 1 FROM cosecha_link WHERE faena_id=? AND cuartel=?",
        (int(faena_id), cuartel),
    ).fetchone()
    if not link:
        return False, "Ese cuartel no está en esta faena."
    pesos = int(round(float(monto or 0)))
    if pesos <= 0:
        return False, "El abono tiene que ser mayor a cero."
    texto = " ".join((nota or "").split())[:200]
    conn.execute(
        """INSERT INTO cosecha_abono (faena_id, cuartel, monto, nota, fecha)
           VALUES (?,?,?,?,?)""",
        (int(faena_id), cuartel, pesos, texto, fecha),
    )
    return True, "Abono anotado. Entra a la cuenta corriente cuando este cuartel pase a compras."


def abonos_cuartel(conn: sqlite3.Connection, faena_id: int, cuartel: str) -> list[dict]:
    rows = conn.execute(
        """SELECT id, monto, nota, fecha FROM cosecha_abono
           WHERE faena_id=? AND cuartel=? ORDER BY id""",
        (int(faena_id), cuartel),
    ).fetchall()
    return [
        {"id": int(r[0]), "monto": int(round(float(r[1]))), "nota": r[2] or "", "fecha": r[3] or ""}
        for r in rows
    ]


def sumar_tote(
    conn: sqlite3.Connection,
    token: str,
    numero: int,
    fecha_hora: str,
    fecha: str = "",
) -> tuple[bool, str, int]:
    link = _link_por_token(conn, token)
    if not link:
        return False, "Este enlace no corresponde a la faena.", 0
    if _cerrado(conn, int(link["faena_id"]), link["cuartel"]):
        return False, "Este cuartel ya está cerrado.", int(numero or 0)
    try:
        n = int(numero)
    except (TypeError, ValueError):
        return False, "El número de la funda no es válido.", 0
    if n < 1 or n > 999:
        return False, "El número del cosechero no es válido.", 0
    funda = _funda(conn, int(link["faena_id"]), n)
    if funda and funda["estado"] != "activa":
        return False, f"El número {n} ya no se usa.", n
    ok_dia, msg_dia, dia = _dia(fecha, fecha_hora)
    if not ok_dia:
        return False, msg_dia, n
    if not funda:
        conn.execute(
            """INSERT INTO cosecha_funda (faena_id, numero, nombre, rut, estado)
               VALUES (?,?, '', '', 'activa')""",
            (int(link["faena_id"]), n),
        )
        funda = _funda(conn, int(link["faena_id"]), n)
    conn.execute(
        """INSERT INTO cosecha_tote (faena_id, funda_id, cuartel, anulado, creado, fecha)
           VALUES (?,?,?,0,?,?)""",
        (int(link["faena_id"]), int(funda["id"]), link["cuartel"], fecha_hora, dia),
    )
    total = contar_totes(conn, int(link["faena_id"]), link["cuartel"], int(funda["id"]))
    quien = (funda["nombre"] or "").strip()
    texto = f"Número {n}" + (f" · {quien}" if quien else "")
    visible = f"{dia[8:10]}-{dia[5:7]}-{dia[0:4]}"
    return True, f"{texto} lleva {total} totes el {visible}.", n


def deshacer_ultimo(conn: sqlite3.Connection, token: str, fecha: str = "") -> tuple[bool, str, int]:
    link = _link_por_token(conn, token)
    if not link:
        return False, "Este enlace no corresponde a la faena.", 0
    if _cerrado(conn, int(link["faena_id"]), link["cuartel"]):
        return False, "Este cuartel ya está cerrado.", 0
    dia = ""
    if (fecha or "").strip():
        ok_dia, msg_dia, dia = _dia(fecha, "")
        if not ok_dia:
            return False, msg_dia, 0
    expr = _fecha_sql("t.")
    sql = """SELECT t.id, f.numero, f.nombre FROM cosecha_tote t
             JOIN cosecha_funda f ON f.id=t.funda_id
             WHERE t.faena_id=? AND t.cuartel=? AND t.anulado=0"""
    params: list[Any] = [int(link["faena_id"]), link["cuartel"]]
    if dia:
        sql += f" AND ({expr})=?"
        params.append(dia)
    sql += " ORDER BY t.id DESC LIMIT 1"
    row = conn.execute(sql, params).fetchone()
    if not row:
        return False, "No hay un tote para deshacer.", 0
    conn.execute("UPDATE cosecha_tote SET anulado=1 WHERE id=?", (int(row[0]),))
    return True, f"Se quitó el último tote de {row[2] or row[1]}.", int(row[1])


def payload_qr(numero: int) -> str:
    """El QR impreso lleva solo el número de la funda."""
    n = int(numero)
    if n < 1:
        raise ValueError("número inválido")
    return str(n)


def svg_qr(texto: str, px: int | None = None) -> str:
    from demo_web.services.qrcodegen import QrCode

    qr = QrCode.encode_text(texto, QrCode.Ecc.MEDIUM)
    borde = 2
    lado = qr.get_size() + borde * 2
    medida = f' width="{int(px)}" height="{int(px)}"' if px else ""
    partes = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {lado} {lado}"{medida} shape-rendering="crispEdges">',
        f'<rect width="{lado}" height="{lado}" fill="#fff"/>',
    ]
    for y in range(qr.get_size()):
        for x in range(qr.get_size()):
            if qr.get_module(x, y):
                partes.append(
                    f'<rect x="{x + borde}" y="{y + borde}" width="1" height="1" fill="#111"/>'
                )
    partes.append("</svg>")
    return "".join(partes)


def vista_anotadora(conn: sqlite3.Connection, token: str, tab: str, numero: int | None) -> dict | None:
    link = _link_por_token(conn, token)
    if not link:
        return None
    faena_id = int(link["faena_id"])
    cuartel = str(link["cuartel"])
    cerrado = _cerrado(conn, faena_id, cuartel)
    por_funda = _totes_por_funda(conn, faena_id, cuartel)
    filas = []
    for funda in listar_fundas(conn, faena_id):
        totes = por_funda.get(int(funda["id"]), 0)
        if not funda["viva"] and totes <= 0:
            continue
        filas.append(
            {
                "numero": funda["numero"],
                "nombre": funda["nombre"] or "",
                "rut": funda["rut"] or "",
                "totes": totes,
                "viva": funda["viva"],
                "asignado": funda["asignado"],
            }
        )
    preview = None
    if numero:
        funda = _funda(conn, faena_id, int(numero))
        if funda:
            preview = {
                "numero": int(funda["numero"]),
                "nombre": funda["nombre"] or "",
                "viva": funda["estado"] == "activa",
                "totes": por_funda.get(int(funda["id"]), 0),
            }
    pestana = "ingresado" if (tab or "").strip() == "ingresado" else "ingreso"
    return {
        "cuartel": cuartel,
        "tab": pestana,
        "cerrado": cerrado,
        "estado_cuenta": "Final" if cerrado else "Parcial",
        "filas": filas,
        "total_totes": sum(f["totes"] for f in filas),
        "preview": preview,
        "siguiente": _siguiente_numero(conn, faena_id),
    }


def atender_anotadora(
    conn: sqlite3.Connection,
    token: str,
    accion: str,
    numero: int | None,
    nombre: str,
    fecha_hora: str,
    rut: str = "",
    fecha: str = "",
) -> tuple[bool, str, int]:
    link = _link_por_token(conn, token)
    if not link:
        return False, "Este enlace no corresponde a la faena.", 0
    faena_id = int(link["faena_id"])
    if accion == "persona":
        ok, msg = guardar_persona(conn, faena_id, int(numero or 0), nombre, rut)
        return ok, msg, int(numero or 0)
    if accion == "deshacer":
        return deshacer_ultimo(conn, token, fecha)
    return sumar_tote(conn, token, int(numero or 0), fecha_hora, fecha)


def plan_cierre(conn: sqlite3.Connection, faena_id: int, cuartel: str) -> tuple[bool, str, dict | None]:
    asegurar_tablas(conn)
    faena = _faena(conn, faena_id)
    if not faena or faena["estado"] != "abierta":
        return False, "La faena no está abierta.", None
    cuartel = (cuartel or "").strip()
    link = conn.execute(
        "SELECT cuartel FROM cosecha_link WHERE faena_id=? AND cuartel=?",
        (int(faena_id), cuartel),
    ).fetchone()
    if not link:
        return False, "Ese cuartel no está en esta faena.", None
    cuartel = str(link[0])
    if _cerrado(conn, faena_id, cuartel):
        return False, "Este cuartel ya pasó a compras.", None
    totes = contar_totes(conn, faena_id, cuartel)
    if totes <= 0:
        return False, "Este cuartel todavía no tiene totes.", None
    precio = precio_cuartel(conn, faena_id, cuartel)
    if precio <= 0:
        return False, "Falta el precio por tote de este cuartel.", None
    bruto = int(totes * precio)
    abonos = abonos_cuartel(conn, faena_id, cuartel)
    ct = conn.execute(
        "SELECT razon_social FROM contratistas WHERE id=?",
        (int(faena["contratista_id"]),),
    ).fetchone()
    if not ct:
        return False, "Contratista no encontrado.", None
    return True, "", {
        "faena_id": int(faena_id),
        "contratista_id": int(faena["contratista_id"]),
        "proveedor": str(ct[0]),
        "cuartel": cuartel,
        "totes": totes,
        "precio": precio,
        "bruto": bruto,
        "abonos": abonos,
        "concepto": f"Cosecha {cuartel} · {totes} totes",
        "selcc": [cuartel],
    }


def marcar_cierre(
    conn: sqlite3.Connection,
    plan: dict,
    factura_id: int,
    nro_documento: str,
    fecha: str,
    usuario: str,
) -> None:
    for abono in plan["abonos"]:
        cur = conn.execute(
            """INSERT INTO facturas_abonos
               (factura_id, fecha, monto, metodo_pago, usuario, fecha_registro, banco)
               VALUES (?,?,?,?,?,?,?)""",
            (
                int(factura_id),
                abono["fecha"] or fecha,
                int(abono["monto"]),
                "Abono cosecha",
                usuario or "",
                fecha,
                "",
            ),
        )
        conn.execute(
            "UPDATE cosecha_abono SET factura_abono_id=? WHERE id=?",
            (int(cur.lastrowid), int(abono["id"])),
        )
    conn.execute(
        """INSERT INTO cosecha_cierre
           (faena_id, cuartel, factura_id, nro_documento, totes, precio, bruto, cerrado)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            int(plan["faena_id"]),
            plan["cuartel"],
            int(factura_id),
            nro_documento,
            int(plan["totes"]),
            int(plan["precio"]),
            int(plan["bruto"]),
            fecha,
        ),
    )


RegistrarServicio = Callable[..., tuple[bool, str | None]]


def aplicar_en_compras(
    conn: sqlite3.Connection,
    plan: dict,
    registrar: RegistrarServicio,
    nro_documento: str,
    fecha: str,
    usuario: str,
) -> tuple[bool, str]:
    """Una sola cabecera de servicio, por el bruto, imputada al cuartel del enlace."""
    ok, err = registrar(
        plan["contratista_id"],
        plan["proveedor"],
        nro_documento,
        fecha,
        fecha,
        plan["bruto"],
        plan["concepto"],
        list(plan["selcc"]),
    )
    if not ok:
        return False, err or "No se pudo registrar el servicio."
    row = conn.execute(
        """SELECT id FROM facturas
           WHERE nro_documento=? AND contratista_id=? AND monto_total>0
           ORDER BY id DESC LIMIT 1""",
        (nro_documento, int(plan["contratista_id"])),
    ).fetchone()
    if not row:
        return False, "El servicio no quedó registrado."
    marcar_cierre(conn, plan, int(row[0]), nro_documento, fecha, usuario)
    return True, nro_documento


def puede_cerrar_faena(conn: sqlite3.Connection, faena_id: int) -> tuple[bool, str]:
    """Cerrar la faena no pasa por compras ni por la cuenta corriente."""
    faena = _faena(conn, faena_id)
    if not faena or faena["estado"] != "abierta":
        return False, "La faena no está abierta."
    return True, ""


def cerrar_faena(conn: sqlite3.Connection, faena_id: int, fecha: str) -> tuple[bool, str]:
    faena = _faena(conn, faena_id)
    if not faena or faena["estado"] != "abierta":
        return False, "La faena no está abierta."
    ok, msg = puede_cerrar_faena(conn, faena_id)
    if not ok:
        return False, msg
    conn.execute(
        "UPDATE cosecha_faena SET estado='cerrada', cerrada=? WHERE id=?",
        (fecha, int(faena_id)),
    )
    return True, "Faena cerrada."


def nueva_faena(
    conn: sqlite3.Connection,
    faena_id: int,
    cuarteles: list[str],
    fecha: str,
) -> tuple[bool, str, int]:
    faena = _faena(conn, faena_id)
    if not faena:
        return False, "Faena no encontrada.", 0
    ok, msg = cerrar_faena(conn, faena_id, fecha)
    if not ok:
        return False, msg, 0
    return abrir_faena(conn, int(faena["contratista_id"]), cuarteles, fecha)


def url_anotadora(token: str, tenant: str) -> str:
    import os

    base = (os.environ.get("ERP_PUBLIC_BASE_URL") or "https://erpmaster.cl").rstrip("/")
    prefix = "/agricola"
    try:
        from flask import current_app, has_app_context

        if has_app_context():
            base = (
                os.environ.get("ERP_PUBLIC_BASE_URL")
                or current_app.config.get("ERP_PUBLIC_BASE_URL")
                or base
            ).rstrip("/")
            prefix = (current_app.config.get("APPLICATION_ROOT") or "/agricola").rstrip("/")
    except Exception:
        pass
    slug = (tenant or "concepcion").strip().lower()
    return f"{base}{prefix}/cosecha/{token}?tenant={slug}"


def url_whatsapp(cuartel: str, url: str, marca: str = "") -> str:
    """Abre WhatsApp con el enlace del cuartel listo para reenviar."""
    from urllib.parse import quote

    titulo = f"Cosecha {(cuartel or '').strip()}"
    empresa = (marca or "").strip()
    if empresa:
        titulo = f"{titulo} — {empresa}"
    return "https://wa.me/?text=" + quote(f"{titulo}:\n{url}", safe="")


def slug_para_link() -> str:
    from demo_web.services.tenant_scope import is_espino_tenant, tenant_slug

    slug = tenant_slug()
    if slug in {"concepcion", "espino", "demo"}:
        return slug
    if is_espino_tenant():
        return "espino"
    return "concepcion"


def armar_panel(conn: sqlite3.Connection, faena_id: int) -> dict:
    asegurar_tablas(conn)
    faena = _faena(conn, faena_id)
    if not faena:
        return {}
    if faena["estado"] == "abierta":
        # Los links ya se crearon al abrir, con los cuarteles de esa empresa.
        pass
    links = listar_links(conn, int(faena_id))
    fundas = listar_fundas(conn, int(faena_id))
    filas = []
    for link in links:
        cuartel = link["cuartel"]
        totes = contar_totes(conn, int(faena_id), cuartel)
        precio = precio_cuartel(conn, int(faena_id), cuartel)
        abonos = abonos_cuartel(conn, int(faena_id), cuartel)
        suma_abonos = sum(a["monto"] for a in abonos)
        bruto = totes * precio
        filas.append(
            {
                "cuartel": cuartel,
                "token": link["token"],
                "totes": totes,
                "precio": precio,
                "bruto": bruto,
                "abonos": suma_abonos,
                "abonos_detalle": abonos,
                "saldo": bruto - suma_abonos,
                "cerrado": _cerrado(conn, int(faena_id), cuartel),
            }
        )
    ok_nueva, msg_nueva = puede_cerrar_faena(conn, int(faena_id))
    return {
        "faena_id": int(faena["id"]),
        "estado": faena["estado"],
        "abierta": faena["estado"] == "abierta",
        "creada": faena["creada"] or "",
        "filas": filas,
        "fundas": fundas,
        "numeros": planilla_numeros(conn, int(faena_id)),
        "siguiente": _siguiente_numero(conn, int(faena_id)),
        "puede_nueva": bool(faena["estado"] == "abierta" and ok_nueva),
        "aviso_nueva": msg_nueva,
    }
