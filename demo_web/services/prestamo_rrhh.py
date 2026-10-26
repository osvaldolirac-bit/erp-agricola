"""Libro mayor de préstamos de RRHH.

Cada préstamo es una línea. Los descuentos de la planilla se abonan a esa
línea, no a la persona. El saldo es el monto de la línea menos sus abonos.

La ficha antigua tenía un solo monto. La primera migración copia ese monto
y le asigna los descuentos ya guardados. Si esos descuentos empiezan antes
de la fecha que quedó en la ficha, la línea histórica parte en el primer
descuento: esos pagos pertenecen a ese préstamo.
"""
from __future__ import annotations

import sqlite3
from datetime import date


def _mes(valor) -> str | None:
    if valor is None or str(valor).strip() == "":
        return None
    try:
        n = int(str(valor).strip())
    except ValueError:
        return None
    if n < 1 or n > 12:
        return None
    return f"{n:02d}"


def _anio(valor) -> int | None:
    if valor is None or str(valor).strip() == "":
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _periodo(mes, anio) -> int | None:
    m = _mes(mes)
    a = _anio(anio)
    if m is None or a is None:
        return None
    return a * 12 + int(m)


def _tabla(conn: sqlite3.Connection, nombre: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (nombre,),
    ).fetchone()
    return row is not None


def asegurar_tablas(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS prestamo_rrhh (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trabajador_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            monto REAL NOT NULL,
            cuotas INTEGER NOT NULL,
            primera_cuota_mes TEXT,
            primera_cuota_anio INTEGER,
            creado_en TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS prestamo_rrhh_abono (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prestamo_id INTEGER NOT NULL,
            trabajador_id INTEGER NOT NULL,
            mes TEXT NOT NULL,
            anio INTEGER NOT NULL,
            monto REAL NOT NULL,
            UNIQUE (trabajador_id, mes, anio)
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS prestamo_rrhh_migrado (
            trabajador_id INTEGER PRIMARY KEY
        )"""
    )


def _marcar_migrado(conn: sqlite3.Connection, trabajador_id: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO prestamo_rrhh_migrado (trabajador_id) VALUES (?)",
        (int(trabajador_id),),
    )


def _ya_migrado(conn: sqlite3.Connection, trabajador_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM prestamo_rrhh_migrado WHERE trabajador_id=?",
        (int(trabajador_id),),
    ).fetchone()
    return row is not None


def migrar_desde_ficha(conn: sqlite3.Connection) -> int:
    """Crea la línea histórica una sola vez por trabajador. Devuelve cuántas creó."""
    asegurar_tablas(conn)
    if not _tabla(conn, "remuneraciones_fichas") and not _tabla(conn, "remuneracion_mes"):
        return 0
    fichas: dict[int, sqlite3.Row] = {}
    if _tabla(conn, "remuneraciones_fichas"):
        conn.row_factory = sqlite3.Row
        for row in conn.execute(
            """SELECT trabajador_id, monto_prestamo, cuotas_prestamo,
                      primera_cuota_mes, primera_cuota_anio
               FROM remuneraciones_fichas"""
        ):
            fichas[int(row["trabajador_id"])] = row
    abonos: dict[int, list[sqlite3.Row]] = {}
    if _tabla(conn, "remuneracion_mes"):
        conn.row_factory = sqlite3.Row
        for row in conn.execute(
            """SELECT trabajador_id, mes, anio, descuento_prestamo
               FROM remuneracion_mes
               WHERE COALESCE(descuento_prestamo, 0) > 0.01
               ORDER BY anio, CAST(mes AS INTEGER), trabajador_id"""
        ):
            abonos.setdefault(int(row["trabajador_id"]), []).append(row)
    creados = 0
    for tid in sorted(set(fichas) | set(abonos)):
        if _ya_migrado(conn, tid):
            continue
        _marcar_migrado(conn, tid)
        ficha = fichas.get(tid)
        monto = float(ficha["monto_prestamo"] or 0) if ficha else 0.0
        cuotas = int(ficha["cuotas_prestamo"] or 0) if ficha else 0
        pm = _mes(ficha["primera_cuota_mes"]) if ficha else None
        pa = _anio(ficha["primera_cuota_anio"]) if ficha else None
        pagos = abonos.get(tid, [])
        if monto <= 0.01 and not pagos:
            continue
        if monto <= 0.01:
            monto = sum(float(p["descuento_prestamo"] or 0) for p in pagos)
            if cuotas <= 0:
                cuotas = len(pagos)
        if pagos:
            primero = pagos[0]
            fm, fa = _mes(primero["mes"]), _anio(primero["anio"])
            if _periodo(fm, fa) is not None and (
                _periodo(pm, pa) is None or _periodo(fm, fa) < _periodo(pm, pa)
            ):
                pm, pa = fm, fa
        if cuotas <= 0:
            cuotas = 1
        fecha = f"{pa or date.today().year}-{pm or '01'}-01"
        cur = conn.execute(
            """INSERT INTO prestamo_rrhh
               (trabajador_id, fecha, monto, cuotas, primera_cuota_mes, primera_cuota_anio, creado_en)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (tid, fecha, monto, cuotas, pm, pa, "migracion"),
        )
        pid = int(cur.lastrowid)
        for pago in pagos:
            conn.execute(
                """INSERT OR IGNORE INTO prestamo_rrhh_abono
                   (prestamo_id, trabajador_id, mes, anio, monto)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    pid,
                    tid,
                    _mes(pago["mes"]),
                    int(pago["anio"]),
                    float(pago["descuento_prestamo"] or 0),
                ),
            )
        creados += 1
    return creados


def _descontado(conn: sqlite3.Connection, prestamo_id: int) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(monto), 0) FROM prestamo_rrhh_abono WHERE prestamo_id=?",
        (int(prestamo_id),),
    ).fetchone()
    return float(row[0] or 0)


def _enriquecer(row: sqlite3.Row, descontado: float) -> dict:
    monto = float(row["monto"] or 0)
    cuotas = int(row["cuotas"] or 0)
    descontado = float(descontado or 0)
    saldo = max(0.0, monto - descontado)
    cuota_ref = (monto / cuotas) if cuotas > 0 else 0.0
    if monto > 0.01 and saldo <= 0.01:
        pagadas = cuotas
        estado = "saldado"
    elif cuota_ref > 0:
        pagadas = min(cuotas, int(round(descontado / cuota_ref)))
        estado = "vigente"
    else:
        pagadas = 0
        estado = "vigente"
    return {
        "id": int(row["id"]),
        "trabajador_id": int(row["trabajador_id"]),
        "fecha": str(row["fecha"] or "")[:10],
        "monto": monto,
        "cuotas": cuotas,
        "cuotas_pagadas": pagadas,
        "primera_cuota_mes": _mes(row["primera_cuota_mes"]),
        "primera_cuota_anio": _anio(row["primera_cuota_anio"]),
        "descontado": descontado,
        "saldo": saldo,
        "cuota_ref": cuota_ref,
        "estado": estado,
    }


def _filas(conn: sqlite3.Connection, trabajador_id: int | None = None) -> list[dict]:
    conn.row_factory = sqlite3.Row
    if trabajador_id is None:
        rows = conn.execute(
            """SELECT id, trabajador_id, fecha, monto, cuotas,
                      primera_cuota_mes, primera_cuota_anio
               FROM prestamo_rrhh
               ORDER BY trabajador_id, id"""
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT id, trabajador_id, fecha, monto, cuotas,
                      primera_cuota_mes, primera_cuota_anio
               FROM prestamo_rrhh
               WHERE trabajador_id=?
               ORDER BY id""",
            (int(trabajador_id),),
        ).fetchall()
    return [_enriquecer(row, _descontado(conn, int(row["id"]))) for row in rows]


def listar_trabajador(conn: sqlite3.Connection, trabajador_id: int) -> list[dict]:
    migrar_desde_ficha(conn)
    return _filas(conn, int(trabajador_id))


def listar_todos(conn: sqlite3.Connection) -> list[dict]:
    migrar_desde_ficha(conn)
    return _filas(conn)


def _abiertos_en_orden(prestamos: list[dict]) -> list[dict]:
    abiertos = [p for p in prestamos if p["saldo"] > 0.01]
    abiertos.sort(
        key=lambda p: (
            _periodo(p["primera_cuota_mes"], p["primera_cuota_anio"]) or 0,
            p["id"],
        )
    )
    return abiertos


def prestamo_vigente(conn: sqlite3.Connection, trabajador_id: int) -> dict | None:
    """El préstamo que recibe la cuota: el más antiguo que aún tiene saldo."""
    return next(iter(_abiertos_en_orden(listar_trabajador(conn, trabajador_id))), None)


def prestamo_para_corregir(conn: sqlite3.Connection, trabajador_id: int) -> dict | None:
    """El vigente, o el último si todos están saldados."""
    prestamos = listar_trabajador(conn, trabajador_id)
    abierto = next(iter(_abiertos_en_orden(prestamos)), None)
    if abierto:
        return abierto
    return prestamos[-1] if prestamos else None


def info_prestamo(conn: sqlite3.Connection, trabajador_id: int) -> dict:
    """Misma forma que ``_info_prestamo_worker`` de app_concepcion."""
    elegido = prestamo_para_corregir(conn, int(trabajador_id))
    if not elegido:
        return {
            "monto": 0.0,
            "cuotas": 0,
            "cuota_ref": 0.0,
            "descontado": 0.0,
            "saldo": 0.0,
            "primera_cuota_mes": None,
            "primera_cuota_anio": None,
        }
    return {
        "monto": elegido["monto"],
        "cuotas": elegido["cuotas"],
        "cuota_ref": elegido["cuota_ref"],
        "descontado": elegido["descontado"],
        "saldo": elegido["saldo"],
        "primera_cuota_mes": elegido["primera_cuota_mes"],
        "primera_cuota_anio": elegido["primera_cuota_anio"],
    }


def _abono_del_mes(conn: sqlite3.Connection, trabajador_id: int, mes, anio):
    conn.row_factory = sqlite3.Row
    return conn.execute(
        """SELECT id, prestamo_id, monto FROM prestamo_rrhh_abono
           WHERE trabajador_id=? AND mes=? AND anio=?""",
        (int(trabajador_id), _mes(mes), int(anio)),
    ).fetchone()


def prestamo_dueno_del_mes(conn: sqlite3.Connection, trabajador_id: int, mes, anio) -> int | None:
    """El mes ya abonado sigue en ese préstamo. Si no, va al vigente que ya aplica."""
    migrar_desde_ficha(conn)
    existente = _abono_del_mes(conn, trabajador_id, mes, anio)
    if existente:
        return int(existente["prestamo_id"])
    periodo = _periodo(mes, anio)
    for prestamo in _abiertos_en_orden(listar_trabajador(conn, trabajador_id)):
        inicio = _periodo(prestamo["primera_cuota_mes"], prestamo["primera_cuota_anio"])
        if inicio is not None and periodo is not None and periodo < inicio:
            continue
        return int(prestamo["id"])
    return None


def saldo_disponible_mes(conn: sqlite3.Connection, trabajador_id: int, mes, anio) -> float:
    pid = prestamo_dueno_del_mes(conn, trabajador_id, mes, anio)
    if pid is None:
        return 0.0
    prestamo = next((p for p in _filas(conn, int(trabajador_id)) if p["id"] == pid), None)
    if not prestamo:
        return 0.0
    existente = _abono_del_mes(conn, trabajador_id, mes, anio)
    ya = float(existente["monto"] or 0) if existente else 0.0
    return prestamo["saldo"] + ya


def sincronizar_abono_mes(
    conn: sqlite3.Connection,
    trabajador_id: int,
    mes,
    anio,
    monto: float,
) -> None:
    """Deja el abono del mes en el préstamo que ya lo tenía, o en el vigente."""
    migrar_desde_ficha(conn)
    mes_n = _mes(mes)
    anio_n = int(anio)
    monto = float(monto or 0)
    existente = _abono_del_mes(conn, trabajador_id, mes_n, anio_n)
    if monto <= 0.01:
        if existente:
            conn.execute("DELETE FROM prestamo_rrhh_abono WHERE id=?", (int(existente["id"]),))
        return
    if existente:
        conn.execute(
            "UPDATE prestamo_rrhh_abono SET monto=? WHERE id=?",
            (monto, int(existente["id"])),
        )
        return
    pid = prestamo_dueno_del_mes(conn, trabajador_id, mes_n, anio_n)
    if pid is None:
        return
    conn.execute(
        """INSERT INTO prestamo_rrhh_abono
           (prestamo_id, trabajador_id, mes, anio, monto)
           VALUES (?, ?, ?, ?, ?)""",
        (pid, int(trabajador_id), mes_n, anio_n, monto),
    )


def descuento_sugerido(
    conn: sqlite3.Connection,
    trabajador_id: int,
    mes,
    anio,
    desc_guardado: float | None = None,
) -> float:
    """Cuota del préstamo vigente. Un descuento ya guardado en el mes se respeta."""
    if desc_guardado is not None and float(desc_guardado or 0) > 0.01:
        return float(desc_guardado)
    info = info_prestamo(conn, int(trabajador_id))
    if info["cuota_ref"] <= 0 or info["saldo"] <= 0.01:
        return 0.0
    inicio = _periodo(info["primera_cuota_mes"], info["primera_cuota_anio"])
    actual = _periodo(mes, anio)
    if inicio is not None and actual is not None and actual < inicio:
        return 0.0
    return min(float(info["cuota_ref"]), saldo_disponible_mes(conn, trabajador_id, mes, anio))


def reflejar_cuotas_ficha(conn: sqlite3.Connection, trabajador_id: int) -> None:
    """La ficha espeja el préstamo vigente para la planilla y el módulo viejo."""
    if not _tabla(conn, "remuneraciones_fichas"):
        return
    elegido = prestamo_para_corregir(conn, int(trabajador_id))
    conn.row_factory = sqlite3.Row
    ficha = conn.execute(
        "SELECT sueldo_pactado, suple_fijo FROM remuneraciones_fichas WHERE trabajador_id=?",
        (int(trabajador_id),),
    ).fetchone()
    sueldo = float(ficha["sueldo_pactado"] or 0) if ficha else 0.0
    suple = float(ficha["suple_fijo"] or 0) if ficha else 0.0
    if not elegido:
        monto = cuotas = pagadas = 0
        pm = pa = None
    else:
        monto = elegido["monto"]
        cuotas = elegido["cuotas"]
        pagadas = elegido["cuotas_pagadas"]
        pm = elegido["primera_cuota_mes"]
        pa = elegido["primera_cuota_anio"]
    conn.execute(
        """INSERT INTO remuneraciones_fichas
           (trabajador_id, sueldo_pactado, monto_prestamo, cuotas_prestamo, cuotas_pagadas,
            suple_fijo, primera_cuota_mes, primera_cuota_anio)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(trabajador_id) DO UPDATE SET
             monto_prestamo=excluded.monto_prestamo,
             cuotas_prestamo=excluded.cuotas_prestamo,
             cuotas_pagadas=excluded.cuotas_pagadas,
             primera_cuota_mes=excluded.primera_cuota_mes,
             primera_cuota_anio=excluded.primera_cuota_anio""",
        (int(trabajador_id), sueldo, monto, cuotas, pagadas, suple, pm, pa),
    )


def registrar_prestamo(
    conn: sqlite3.Connection,
    trabajador_id: int,
    monto: float,
    cuotas: int,
    primera_cuota_mes,
    primera_cuota_anio,
    fecha: str,
) -> tuple[bool, str]:
    migrar_desde_ficha(conn)
    monto = float(monto or 0)
    cuotas = int(cuotas or 0)
    if monto <= 0 or cuotas <= 0:
        return False, "Monto y cuotas deben ser mayores a cero."
    pm, pa = _mes(primera_cuota_mes), _anio(primera_cuota_anio)
    conn.execute(
        """INSERT INTO prestamo_rrhh
           (trabajador_id, fecha, monto, cuotas, primera_cuota_mes, primera_cuota_anio, creado_en)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (int(trabajador_id), str(fecha)[:10], monto, cuotas, pm, pa, "alta"),
    )
    _marcar_migrado(conn, int(trabajador_id))
    reflejar_cuotas_ficha(conn, int(trabajador_id))
    return True, "Préstamo registrado."


def actualizar_prestamo(
    conn: sqlite3.Connection,
    prestamo_id: int,
    monto: float,
    cuotas: int,
    primera_cuota_mes,
    primera_cuota_anio,
) -> tuple[bool, str]:
    migrar_desde_ficha(conn)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id, trabajador_id FROM prestamo_rrhh WHERE id=?",
        (int(prestamo_id),),
    ).fetchone()
    if not row:
        return False, "Préstamo no encontrado."
    tid = int(row["trabajador_id"])
    descontado = _descontado(conn, int(prestamo_id))
    monto = float(monto or 0)
    cuotas = int(cuotas or 0)
    if monto < descontado - 0.5:
        return False, "El monto no puede ser menor que lo ya descontado en ese préstamo."
    if monto <= 0.01:
        if descontado > 0.01:
            return False, "Ese préstamo ya tiene descuentos. Registre uno nuevo en vez de borrarlo."
        conn.execute("DELETE FROM prestamo_rrhh WHERE id=?", (int(prestamo_id),))
        reflejar_cuotas_ficha(conn, tid)
        return True, "Préstamo eliminado."
    if cuotas <= 0:
        return False, "Las cuotas deben ser mayores a cero."
    conn.execute(
        """UPDATE prestamo_rrhh
           SET monto=?, cuotas=?, primera_cuota_mes=?, primera_cuota_anio=?
           WHERE id=?""",
        (monto, cuotas, _mes(primera_cuota_mes), _anio(primera_cuota_anio), int(prestamo_id)),
    )
    reflejar_cuotas_ficha(conn, tid)
    return True, "Crédito actualizado."


def reflejar_todos(conn: sqlite3.Connection) -> None:
    migrar_desde_ficha(conn)
    for row in conn.execute("SELECT DISTINCT trabajador_id FROM prestamo_rrhh"):
        reflejar_cuotas_ficha(conn, int(row[0]))
