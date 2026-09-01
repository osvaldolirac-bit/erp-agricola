"""RRHH — trabajadores, sueldos e imputación proporcional a centros de costo."""
from __future__ import annotations

from typing import Any

from rmweb import core
from rmweb.ops_cc import ensure_cc_schema, list_centros

MESES = (
    "Enero",
    "Febrero",
    "Marzo",
    "Abril",
    "Mayo",
    "Junio",
    "Julio",
    "Agosto",
    "Septiembre",
    "Octubre",
    "Noviembre",
    "Diciembre",
)


def ensure_rrhh_schema(c) -> None:
    try:
        ensure_cc_schema(c)
    except Exception:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS centros_costo (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL UNIQUE,
                activo INTEGER DEFAULT 1,
                orden INTEGER DEFAULT 0,
                presupuesto REAL DEFAULT 0
            );
            """
        )
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS rrhh_trabajadores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            rut TEXT,
            cargo TEXT,
            activo INTEGER DEFAULT 1,
            creado_en TEXT
        );
        CREATE TABLE IF NOT EXISTS rrhh_pagos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trabajador_id INTEGER NOT NULL,
            mes INTEGER NOT NULL,
            anio INTEGER NOT NULL,
            liquido REAL NOT NULL DEFAULT 0,
            leyes REAL NOT NULL DEFAULT 0,
            costo_empresa REAL NOT NULL DEFAULT 0,
            fecha_registro TEXT,
            nota TEXT,
            UNIQUE(trabajador_id, mes, anio),
            FOREIGN KEY(trabajador_id) REFERENCES rrhh_trabajadores(id)
        );
        CREATE TABLE IF NOT EXISTS rrhh_pago_cc (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pago_id INTEGER NOT NULL,
            centro_costo_id INTEGER NOT NULL,
            monto REAL NOT NULL DEFAULT 0,
            FOREIGN KEY(pago_id) REFERENCES rrhh_pagos(id) ON DELETE CASCADE,
            FOREIGN KEY(centro_costo_id) REFERENCES centros_costo(id)
        );
        """
    )


def mes_label(mes: int) -> str:
    m = int(mes or 0)
    if 1 <= m <= 12:
        return MESES[m - 1]
    return str(mes)


def list_trabajadores(c, *, solo_activos: bool = False) -> list[Any]:
    ensure_rrhh_schema(c)
    sql = "SELECT * FROM rrhh_trabajadores"
    if solo_activos:
        sql += " WHERE activo=1"
    sql += " ORDER BY activo DESC, lower(nombre), id"
    return c.execute(sql).fetchall()


def crear_trabajador(c, *, nombre: str, rut: str | None = None, cargo: str | None = None) -> tuple[bool, str]:
    ensure_rrhh_schema(c)
    nom = (nombre or "").strip()
    if not nom:
        return False, "Indique el nombre del trabajador."
    if len(nom) > 120:
        return False, "Nombre demasiado largo."
    rut_v = (rut or "").strip() or None
    cargo_v = (cargo or "").strip() or None
    c.execute(
        """
        INSERT INTO rrhh_trabajadores (nombre, rut, cargo, activo, creado_en)
        VALUES (?,?,?,1,?)
        """,
        (nom, rut_v, cargo_v, core.hoy_chile().isoformat()),
    )
    return True, f"Trabajador «{nom}» creado."


def _parse_monto(valor) -> float:
    try:
        return max(0.0, float(str(valor or "0").replace(",", ".")))
    except (TypeError, ValueError):
        return 0.0


def _repartir_igual(monto_total: float, cc_ids: list[int]) -> dict[int, float]:
    """Reparto igualitario (opción C) entre CC activos."""
    if not cc_ids or monto_total <= 0:
        return {}
    n = len(cc_ids)
    total = round(float(monto_total))
    base = total // n
    resto = total - base * n
    out: dict[int, float] = {}
    for i, cid in enumerate(cc_ids):
        extra = 1 if i < resto else 0
        out[cid] = float(base + extra)
    return out


def _filtro_periodo_sql(
    *,
    desde: str | None = None,
    hasta: str | None = None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    d = (desde or "").strip()
    h = (hasta or "").strip()
    if d:
        clauses.append("AND printf('%04d-%02d', p.anio, p.mes) >= substr(?, 1, 7)")
        params.append(d)
    if h:
        clauses.append("AND printf('%04d-%02d', p.anio, p.mes) <= substr(?, 1, 7)")
        params.append(h)
    return (" ".join(clauses), params)


def registrar_pago(
    c,
    *,
    trabajador_id: int,
    mes: int,
    anio: int,
    liquido: float,
    leyes: float,
    nota: str | None = None,
) -> tuple[bool, str, int | None]:
    """Registra sueldo de un trabajador y lo reparte en partes iguales entre CC activos."""
    ensure_rrhh_schema(c)
    tid = int(trabajador_id)
    m = int(mes)
    a = int(anio)
    if not (1 <= m <= 12):
        return False, "Mes inválido.", None
    if a < 2000 or a > 2100:
        return False, "Año inválido.", None
    trab = c.execute(
        "SELECT id, nombre, activo FROM rrhh_trabajadores WHERE id=?",
        (tid,),
    ).fetchone()
    if not trab:
        return False, "Trabajador no encontrado.", None
    if not int(trab["activo"] or 0):
        return False, "El trabajador está inactivo.", None

    liq = _parse_monto(liquido)
    ley = _parse_monto(leyes)
    costo = round(liq + ley)
    if costo <= 0:
        return False, "Indique líquido y/o leyes mayores a cero.", None

    dup = c.execute(
        "SELECT id FROM rrhh_pagos WHERE trabajador_id=? AND mes=? AND anio=?",
        (tid, m, a),
    ).fetchone()
    if dup:
        return False, f"Ya existe imputación para {trab['nombre']} en {mes_label(m)} {a}.", None

    cc_rows = list_centros(c, solo_activos=True)
    cc_ids = [int(r["id"]) for r in cc_rows]
    if not cc_ids:
        return False, "No hay centros de costo activos. Créelos en Administración.", None

    reparto = _repartir_igual(float(costo), cc_ids)
    cur = c.cursor()
    cur.execute(
        """
        INSERT INTO rrhh_pagos
        (trabajador_id, mes, anio, liquido, leyes, costo_empresa, fecha_registro, nota)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            tid,
            m,
            a,
            liq,
            ley,
            float(costo),
            core.hoy_chile().isoformat(),
            (nota or "").strip() or None,
        ),
    )
    pago_id = int(cur.lastrowid)
    for cid, monto in reparto.items():
        cur.execute(
            """
            INSERT INTO rrhh_pago_cc (pago_id, centro_costo_id, monto)
            VALUES (?,?,?)
            """,
            (pago_id, cid, monto),
        )
    n = len(cc_ids)
    pct = round(100.0 / n, 1)
    return (
        True,
        f"Sueldo imputado: {core.clp(costo)} a {n} CC activo(s) (~{pct}% c/u).",
        pago_id,
    )


def list_pagos(c, *, limite: int = 100) -> list[Any]:
    ensure_rrhh_schema(c)
    return c.execute(
        """
        SELECT p.*, t.nombre AS trabajador, t.rut AS trabajador_rut
        FROM rrhh_pagos p
        JOIN rrhh_trabajadores t ON t.id = p.trabajador_id
        ORDER BY p.anio DESC, p.mes DESC, p.id DESC
        LIMIT ?
        """,
        (max(1, int(limite)),),
    ).fetchall()


def detalle_pago_cc(c, pago_id: int) -> list[Any]:
    ensure_rrhh_schema(c)
    return c.execute(
        """
        SELECT pc.*, cc.nombre AS centro_costo
        FROM rrhh_pago_cc pc
        LEFT JOIN centros_costo cc ON cc.id = pc.centro_costo_id
        WHERE pc.pago_id=?
        ORDER BY cc.orden, cc.nombre, pc.id
        """,
        (int(pago_id),),
    ).fetchall()


def totales_por_cc(
    c,
    *,
    desde: str | None = None,
    hasta: str | None = None,
) -> dict[int, float]:
    ensure_rrhh_schema(c)
    extra, params = _filtro_periodo_sql(desde=desde, hasta=hasta)
    try:
        rows = c.execute(
            f"""
            SELECT pc.centro_costo_id AS cc_id, COALESCE(SUM(pc.monto), 0) AS monto
            FROM rrhh_pago_cc pc
            JOIN rrhh_pagos p ON p.id = pc.pago_id
            WHERE 1=1 {extra}
            GROUP BY pc.centro_costo_id
            """,
            params,
        ).fetchall()
    except Exception:
        return {}
    return {int(r["cc_id"]): float(r["monto"] or 0) for r in rows if r["cc_id"]}


def resumen_cc_activos(c) -> dict[str, Any]:
    cc_rows = list_centros(c, solo_activos=True)
    n = len(cc_rows)
    pct = round(100.0 / n, 2) if n else 0.0
    return {
        "centros": cc_rows,
        "n": n,
        "pct_cada_uno": pct,
    }


def list_imputaciones_por_centro(
    c,
    cc_id: int,
    *,
    desde: str | None = None,
    hasta: str | None = None,
) -> list[Any]:
    """Filas de sueldos imputados a un CC (formato compatible con detalle_por_centro)."""
    ensure_rrhh_schema(c)
    extra, params = _filtro_periodo_sql(desde=desde, hasta=hasta)
    try:
        return c.execute(
            f"""
            SELECT
                pc.id,
                t.nombre || ' · ' || printf('%02d/%04d', p.mes, p.anio) AS documento,
                COALESCE(p.fecha_registro, printf('%04d-%02d-01', p.anio, p.mes)) AS fecha_emision,
                NULL AS fecha_vencimiento,
                p.liquido AS neto,
                pc.monto AS total,
                0 AS pagado,
                0 AS saldo,
                'imputado' AS estado,
                NULL AS orden_compra_id,
                'RRHH' AS proveedor,
                'Remuneraciones' AS rubro_nombre,
                pc.monto AS monto_cc,
                NULL AS oc_folio,
                'rrhh' AS fuente,
                t.nombre AS producto_nombre,
                NULL AS cantidad
            FROM rrhh_pago_cc pc
            JOIN rrhh_pagos p ON p.id = pc.pago_id
            JOIN rrhh_trabajadores t ON t.id = p.trabajador_id
            WHERE pc.centro_costo_id = ? {extra}
            """,
            [int(cc_id), *params],
        ).fetchall()
    except Exception:
        return []
