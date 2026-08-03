"""Flujo financiero: ingresos manuales, egresos (Tesorería + RRHH) y EERR por temporada."""
from __future__ import annotations

import calendar
import sqlite3
from datetime import date, timedelta

import pandas as pd


def migrar_flujo_financiero(conn):
    from erp_solo_lectura import conn_en_solo_lectura

    if conn_en_solo_lectura(conn):
        return
    conn.execute(
        """CREATE TABLE IF NOT EXISTS flujo_ingresos_mes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            temporada TEXT NOT NULL,
            anio INTEGER NOT NULL,
            mes INTEGER NOT NULL,
            monto REAL DEFAULT 0,
            UNIQUE(temporada, anio, mes)
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS flujo_ingresos_cc (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            temporada TEXT NOT NULL,
            centro_costo TEXT NOT NULL,
            anio INTEGER NOT NULL,
            mes INTEGER NOT NULL,
            monto REAL DEFAULT 0,
            nota TEXT DEFAULT '',
            UNIQUE(temporada, centro_costo, anio, mes)
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS flujo_caja_temporada (
            temporada TEXT PRIMARY KEY,
            saldo_inicial REAL DEFAULT 0
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS flujo_egresos_teso_mes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            temporada TEXT NOT NULL,
            anio INTEGER NOT NULL,
            mes INTEGER NOT NULL,
            monto REAL DEFAULT 0,
            nota TEXT DEFAULT '',
            UNIQUE(temporada, anio, mes)
        )"""
    )
    cols = {r[1] for r in conn.execute("PRAGMA table_info(flujo_ingresos_cc)").fetchall()}
    if "nota" not in cols:
        conn.execute("ALTER TABLE flujo_ingresos_cc ADD COLUMN nota TEXT DEFAULT ''")
    conn.commit()


def _mes_label(anio, mes):
    nombres = (
        "", "Ene", "Feb", "Mar", "Abr", "May", "Jun",
        "Jul", "Ago", "Sep", "Oct", "Nov", "Dic",
    )
    try:
        return f"{nombres[int(mes)]} {int(anio)}"
    except (TypeError, ValueError, IndexError):
        return f"{mes}/{anio}"


def _mes_siguiente(anio, mes):
    mes, anio = int(mes), int(anio)
    if mes >= 12:
        return anio + 1, 1
    return anio, mes + 1


def _mes_mas_n(anio, mes, n):
    anio, mes = int(anio), int(mes)
    for _ in range(int(n)):
        anio, mes = _mes_siguiente(anio, mes)
    return anio, mes


def iter_meses_rango(desde: date, hasta: date):
    cur = date(desde.year, desde.month, 1)
    fin = date(hasta.year, hasta.month, 1)
    while cur <= fin:
        yield cur.year, cur.month
        cur = date(*_mes_siguiente(cur.year, cur.month), 1)


def meses_flujo_desde_hoy(fi: date, ff: date, hoy: date):
    inicio = date(hoy.year, hoy.month, 1)
    if inicio < date(fi.year, fi.month, 1):
        inicio = date(fi.year, fi.month, 1)
    if inicio > ff:
        return []
    return list(iter_meses_rango(inicio, ff))


def meses_anteriores_al_flujo(fi: date, ff: date, hoy: date):
    """Meses de la temporada anteriores al primer mes visible del flujo (antes de hoy)."""
    inicio_temp = date(fi.year, fi.month, 1)
    inicio_flujo = date(hoy.year, hoy.month, 1)
    if inicio_flujo <= inicio_temp:
        return []
    if inicio_flujo > ff:
        return []
    hasta = inicio_flujo - timedelta(days=1)
    if hasta < inicio_temp:
        return []
    return list(iter_meses_rango(inicio_temp, hasta))


def eerr_arrastrado_meses_anteriores(conn, temporada, fi, ff, hoy, cuarteles):
    """
    Resultado acumulado de meses ya no visibles (antes del mes en curso).

    Solo ingresos - RRHH real. La Tesorería impaga con vencimiento anterior
    se carga como atrasada en el primer mes visible (misma lógica actual),
    así no se duplica el egreso en el EERR.
    """
    meses_prev = meses_anteriores_al_flujo(fi, ff, hoy)
    if not meses_prev:
        return 0.0, [], 0.0, 0.0
    ingresos = ingresos_por_mes_desde_cc_cuarteles(conn, temporada, meses_prev, cuarteles)
    fi_prev = date(meses_prev[0][0], meses_prev[0][1], 1)
    anio_u, mes_u = meses_prev[-1]
    ff_prev = date(anio_u, mes_u, calendar.monthrange(anio_u, mes_u)[1])
    rrhh_map = _rrhh_real_por_mes(conn, fi_prev, ff_prev)
    eerr = 0.0
    tot_ing = 0.0
    tot_rrhh = 0.0
    for anio, mes in meses_prev:
        ing = float(ingresos.get((anio, mes), 0.0) or 0.0)
        rrhh = float(rrhh_map.get((anio, mes), 0.0) or 0.0)
        tot_ing += ing
        tot_rrhh += rrhh
        eerr += ing - rrhh
    return eerr, meses_prev, tot_ing, tot_rrhh



def _mes_rrhh_norm(m):
    try:
        return f"{int(m):02d}"
    except (TypeError, ValueError):
        return str(m).strip().zfill(2)


def _saldo_pendiente(monto_total, monto_pagado):
    try:
        return max(0.0, float(monto_total or 0) - float(monto_pagado or 0))
    except (TypeError, ValueError):
        return 0.0


def _norm_cc(cc, cuarteles):
    cc_u = str(cc or "").upper().strip()
    if cc_u in cuarteles:
        return cc_u
    return None


def _cargar_tesoreria(conn, cuarteles, meses=None):
    df = pd.read_sql_query(
        """SELECT fecha_vencimiento, centro_costo,
                  monto_total, COALESCE(monto_pagado, 0) AS monto_pagado
           FROM facturas
           WHERE estado='Pendiente' AND nro_documento NOT LIKE '%_P' AND monto_total > 0""",
        conn,
    )
    por_mes = {}
    por_cc = {cc: 0.0 for cc in cuarteles}
    por_cc_atrasado = {cc: 0.0 for cc in cuarteles}
    teso_atrasado_total = 0.0
    meses_set = set(meses or [])
    primer_mes = (
        date(meses[0][0], meses[0][1], 1) if meses else None
    )
    if df.empty:
        return por_mes, por_cc, teso_atrasado_total, por_cc_atrasado
    for _, row in df.iterrows():
        saldo = _saldo_pendiente(row["monto_total"], row["monto_pagado"])
        if saldo <= 0.01:
            continue
        try:
            fv = pd.to_datetime(row["fecha_vencimiento"]).date()
            key = (fv.year, fv.month)
        except Exception:
            continue
        cc = _norm_cc(row["centro_costo"], cuarteles)
        if primer_mes and fv < primer_mes:
            teso_atrasado_total += saldo
            if cc:
                por_cc_atrasado[cc] = por_cc_atrasado.get(cc, 0.0) + saldo
            continue
        if meses_set and key in meses_set and cc:
            por_cc[cc] = por_cc.get(cc, 0.0) + saldo
        por_mes[key] = por_mes.get(key, 0.0) + saldo
    return por_mes, por_cc, teso_atrasado_total, por_cc_atrasado


def _subquery_pagos_rrhh_canonicos():
    return """
        SELECT p.*
        FROM pagos_rrhh p
        INNER JOIN personal per ON per.id = p.trabajador_id
        WHERE p.id = (
            SELECT p2.id FROM pagos_rrhh p2
            WHERE p2.trabajador_id = p.trabajador_id
              AND printf('%02d', CAST(p2.mes AS INTEGER)) = printf('%02d', CAST(p.mes AS INTEGER))
              AND p2.anio = p.anio
            ORDER BY (p2.liquido + p2.leyes_sociales) DESC, p2.id DESC
            LIMIT 1
        )
    """


def _rrhh_real_por_mes(conn, fi, ff):
    out = {}
    q = f"""SELECT anio, printf('%02d', CAST(mes AS INTEGER)) AS mes,
                   SUM(liquido + leyes_sociales) AS total
            FROM ({_subquery_pagos_rrhh_canonicos()})
            GROUP BY anio, printf('%02d', CAST(mes AS INTEGER))"""
    for anio, mes, total in conn.execute(q).fetchall():
        mes_n = _mes_rrhh_norm(mes)
        try:
            anio_i, mes_i = int(anio), int(mes_n)
            ultimo = calendar.monthrange(anio_i, mes_i)[1]
            if date(anio_i, mes_i, 1) > ff or date(anio_i, mes_i, ultimo) < fi:
                continue
            monto = float(total or 0)
            if monto > 0:
                out[(anio_i, mes_i)] = monto
        except (TypeError, ValueError):
            continue
    return out


def _ultimo_rrhh_imputado(conn):
    row = conn.execute(
        f"""SELECT anio, printf('%02d', CAST(mes AS INTEGER)) AS mes,
                   SUM(liquido + leyes_sociales) AS total
            FROM ({_subquery_pagos_rrhh_canonicos()})
            GROUP BY anio, printf('%02d', CAST(mes AS INTEGER))
            ORDER BY anio DESC, CAST(mes AS INTEGER) DESC
            LIMIT 1"""
    ).fetchone()
    if row and float(row[2] or 0) > 0:
        return float(row[2])
    return 0.0


def resumen_desde_matriz_costos(matriz_df, cuarteles):
    """Mismos ppto / gastado / saldo que el módulo Costos."""

    def _fila(rubro):
        r = matriz_df[matriz_df["Rubro"] == rubro]
        if r.empty:
            return {c: 0.0 for c in cuarteles}
        return {c: float(r.iloc[0].get(c, 0) or 0) for c in cuarteles}

    ppto = _fila("PRESUPUESTO")
    gastado = _fila("TOTAL GASTO")
    saldo = _fila("SALDO")
    rrhh = _fila("RRHH de la casa")
    return {
        "ppto": ppto,
        "gastado": gastado,
        "saldo": saldo,
        "rrhh_gastado": rrhh,
        "total_ppto": sum(ppto.values()),
        "total_gastado": sum(gastado.values()),
        "total_saldo": sum(saldo.values()),
    }


def cargar_ingresos_cc(conn, temporada):
    rows = conn.execute(
        "SELECT centro_costo, anio, mes, monto FROM flujo_ingresos_cc WHERE temporada=?",
        (temporada,),
    ).fetchall()
    out = {}
    for cc, anio, mes, monto in rows:
        out[(str(cc), int(anio), int(mes))] = float(monto or 0)
    return out


def cargar_notas_ingresos_cc(conn, temporada):
    rows = conn.execute(
        "SELECT centro_costo, anio, mes, COALESCE(nota, '') FROM flujo_ingresos_cc WHERE temporada=?",
        (temporada,),
    ).fetchall()
    return {(str(cc), int(anio), int(mes)): str(nota or "") for cc, anio, mes, nota in rows}


def cargar_saldo_caja_inicial(conn, temporada):
    row = conn.execute(
        "SELECT saldo_inicial FROM flujo_caja_temporada WHERE temporada=?",
        (temporada,),
    ).fetchone()
    return float(row[0] or 0) if row else 0.0


def guardar_saldo_caja_inicial(conn, temporada, monto):
    conn.execute(
        """INSERT INTO flujo_caja_temporada (temporada, saldo_inicial)
           VALUES (?,?)
           ON CONFLICT(temporada) DO UPDATE SET saldo_inicial=excluded.saldo_inicial""",
        (temporada, float(monto or 0)),
    )
    conn.commit()


def ingresos_por_mes_desde_cc_cuarteles(conn, temporada, meses, cuarteles):
    data = cargar_ingresos_cc(conn, temporada)
    out = {}
    for anio, mes in meses:
        out[(anio, mes)] = sum(
            data.get((cc, anio, mes), 0.0) for cc in cuarteles
        )
    return out


def guardar_ingresos_cc(conn, temporada, datos, notas=None):
    notas = notas or {}
    for (cc, anio, mes), monto in datos.items():
        nota = str(notas.get((cc, anio, mes), "") or "").strip()
        conn.execute(
            """INSERT INTO flujo_ingresos_cc (temporada, centro_costo, anio, mes, monto, nota)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(temporada, centro_costo, anio, mes)
               DO UPDATE SET monto=excluded.monto, nota=excluded.nota""",
            (temporada, str(cc), int(anio), int(mes), float(monto or 0), nota),
        )
    conn.commit()


def cargar_egresos_teso_mes(conn, temporada):
    """Egresos de tesorería/compras proyectados por mes (plan cargado en Administración)."""
    rows = conn.execute(
        "SELECT anio, mes, monto FROM flujo_egresos_teso_mes WHERE temporada=?",
        (temporada,),
    ).fetchall()
    out = {}
    for anio, mes, monto in rows:
        out[(int(anio), int(mes))] = float(monto or 0)
    return out


def cargar_notas_egresos_teso_mes(conn, temporada):
    rows = conn.execute(
        "SELECT anio, mes, COALESCE(nota, '') FROM flujo_egresos_teso_mes WHERE temporada=?",
        (temporada,),
    ).fetchall()
    return {(int(anio), int(mes)): str(nota or "") for anio, mes, nota in rows}


def guardar_egresos_teso_mes(conn, temporada, datos, notas=None):
    notas = notas or {}
    for (anio, mes), monto in datos.items():
        nota = str(notas.get((anio, mes), "") or "").strip()
        conn.execute(
            """INSERT INTO flujo_egresos_teso_mes (temporada, anio, mes, monto, nota)
               VALUES (?,?,?,?,?)
               ON CONFLICT(temporada, anio, mes)
               DO UPDATE SET monto=excluded.monto, nota=excluded.nota""",
            (temporada, int(anio), int(mes), float(monto or 0), nota),
        )
    conn.commit()


def _armar_resumen_egresos_cc(cuarteles, resumen_costos, teso_por_cc):
    filas = []
    for cc in cuarteles:
        ppto = resumen_costos["ppto"].get(cc, 0.0)
        gastado = resumen_costos["gastado"].get(cc, 0.0)
        saldo = resumen_costos["saldo"].get(cc, 0.0)
        teso_cc = teso_por_cc.get(cc, 0.0)
        filas.append({
            "CENTRO_COSTO": cc,
            "PRESUPUESTO": ppto,
            "GASTADO": gastado,
            "SALDO": saldo,
            "TESO_PROGRAMADA": teso_cc,
            "A_PROYECTAR": max(0.0, saldo - teso_cc),
        })
    df = pd.DataFrame(filas)
    fila_t = {
        "CENTRO_COSTO": "TOTAL",
        "PRESUPUESTO": df["PRESUPUESTO"].sum(),
        "GASTADO": df["GASTADO"].sum(),
        "SALDO": df["SALDO"].sum(),
        "TESO_PROGRAMADA": df["TESO_PROGRAMADA"].sum(),
        "A_PROYECTAR": df["A_PROYECTAR"].sum(),
    }
    return pd.concat([df, pd.DataFrame([fila_t])], ignore_index=True)


def armar_flujo_financiero(
    conn,
    temporada,
    fi,
    ff,
    hoy,
    cuarteles,
    resumen_costos,
):
    # Toda la temporada: meses pasados = solo real; mes en curso y futuros = real + proyección.
    inicio_temp = date(fi.year, fi.month, 1)
    if inicio_temp > ff:
        meses = []
    else:
        meses = list(iter_meses_rango(inicio_temp, ff))
    mes_hoy = date(hoy.year, hoy.month, 1)
    meses_futuros = [(a, m) for a, m in meses if date(a, m, 1) >= mes_hoy]

    ingresos = ingresos_por_mes_desde_cc_cuarteles(conn, temporada, meses, cuarteles)
    rrhh_map = _rrhh_real_por_mes(conn, fi, ff)
    rrhh_base_proy = _ultimo_rrhh_imputado(conn)

    # EERR "efectivo" parte en el primer mes con ingresos (como cuando el flujo
    # se miraba desde ese mes). Mayo/junio se ven, pero no tiran el EERR de julio.
    mes_inicio_eerr = None
    for anio, mes in meses:
        if float(ingresos.get((anio, mes), 0.0) or 0.0) > 0.01:
            mes_inicio_eerr = (anio, mes)
            break
    if mes_inicio_eerr is None:
        mes_inicio_eerr = meses_futuros[0] if meses_futuros else (meses[0] if meses else None)
    inicio_eerr_date = (
        date(mes_inicio_eerr[0], mes_inicio_eerr[1], 1) if mes_inicio_eerr else mes_hoy
    )
    meses_desde_eerr = [m for m in meses if date(m[0], m[1], 1) >= inicio_eerr_date]

    # Tesorería con vencimiento desde el inicio EERR; lo anterior entra como atrasado
    # en ese mes (igual que cuando julio era el primer mes visible).
    teso_map, teso_por_cc, teso_atrasado, teso_por_cc_atrasado = _cargar_tesoreria(
        conn, cuarteles, meses_desde_eerr or meses,
    )
    teso_por_cc_total = {
        cc: teso_por_cc.get(cc, 0.0) + teso_por_cc_atrasado.get(cc, 0.0)
        for cc in cuarteles
    }

    saldo_total = float(resumen_costos.get("total_saldo") or 0.0)
    teso_programada_flujo = sum(teso_map.get(m, 0.0) for m in meses_futuros)
    teso_cxp_total = teso_atrasado + teso_programada_flujo
    teso_proy_plan = cargar_egresos_teso_mes(conn, temporada)
    saldo_presupuesto_sin_cxp = max(
        0.0, saldo_total - teso_programada_flujo - teso_atrasado,
    )
    teso_proy_plan_total = sum(
        float(teso_proy_plan.get(m, 0.0) or 0.0) for m in meses_futuros
    )
    meses_con_proy_teso = [
        m for m in meses_futuros if float(teso_proy_plan.get(m, 0.0) or 0.0) > 0.01
    ]
    meses_sin_teso = [m for m in meses_futuros if teso_map.get(m, 0.0) < 0.01]

    # TESO PROY automático desde mes actual + 2 (ej. si hoy es ago → desde oct):
    # valor asumido (cuota del saldo tras CxP cercana, o plan manual) − TESO REAL del mes.
    anio_corte, mes_corte_n = _mes_mas_n(hoy.year, hoy.month, 2)
    mes_corte = date(anio_corte, mes_corte_n, 1)
    meses_cerca = [m for m in meses_futuros if date(m[0], m[1], 1) < mes_corte]
    meses_lejos = [m for m in meses_futuros if date(m[0], m[1], 1) >= mes_corte]
    cxp_cerca = sum(teso_map.get(m, 0.0) for m in meses_cerca)
    if (
        teso_atrasado > 0.01
        and mes_inicio_eerr is not None
        and date(mes_inicio_eerr[0], mes_inicio_eerr[1], 1) < mes_corte
    ):
        cxp_cerca += teso_atrasado
    disponible_lejos = max(0.0, saldo_total - cxp_cerca)
    cuota_teso_lejos = (
        disponible_lejos / len(meses_lejos) if meses_lejos else 0.0
    )
    meses_lejos_set = set(meses_lejos)
    meses_residual = list(meses_lejos)
    residual_teso = disponible_lejos
    proy_residual_mensual = cuota_teso_lejos

    pre = []
    for anio, mes in meses:
        d_mes = date(anio, mes, 1)
        es_futuro = d_mes >= mes_hoy
        en_eerr = d_mes >= inicio_eerr_date
        # Antes del inicio EERR: solo RRHH/ingresos informativos (CxP se consolida al inicio EERR).
        teso_real = teso_map.get((anio, mes), 0.0) if en_eerr else 0.0
        rrhh_real = rrhh_map.get((anio, mes), 0.0)
        if es_futuro:
            plan_mes = float(teso_proy_plan.get((anio, mes), 0.0) or 0.0)
            if (anio, mes) in meses_lejos_set:
                # Desde hoy+2: asumir valor (plan o cuota) menos lo ya imputado real (CxP).
                valor = plan_mes if plan_mes > 0.01 else cuota_teso_lejos
                teso_proy = max(0.0, valor - teso_real)
            else:
                # Mes actual y +1: solo plan manual; la CxP cercana manda.
                teso_proy = plan_mes
            rrhh_proy = 0.0 if rrhh_real > 0.01 else rrhh_base_proy
        else:
            teso_proy = 0.0
            rrhh_proy = 0.0
        pre.append({
            "anio": anio,
            "mes": mes,
            "teso_real": teso_real,
            "teso_proy": teso_proy,
            "rrhh_real": rrhh_real,
            "rrhh_proy": rrhh_proy,
            "es_futuro": es_futuro,
            "en_eerr": en_eerr,
        })

    total_real = (
        sum(r["teso_real"] + r["rrhh_real"] for r in pre if r.get("es_futuro"))
        + teso_atrasado
    )
    teso_proy_necesario = sum(r["teso_proy"] for r in pre)
    rrhh_proy_necesario = sum(r["rrhh_proy"] for r in pre)

    # Tope al saldo de ppto: primero RRHH proy, luego TESO proy (misma lógica previa).
    pool = max(0.0, saldo_total - total_real)
    rrhh_proy_asignado = min(rrhh_proy_necesario, pool)
    factor_rrhh = (
        rrhh_proy_asignado / rrhh_proy_necesario if rrhh_proy_necesario > 0.01 else 1.0
    )
    pool -= rrhh_proy_asignado
    teso_proy_asignado = min(teso_proy_necesario, pool)
    factor_teso = (
        teso_proy_asignado / teso_proy_necesario if teso_proy_necesario > 0.01 else 0.0
    )
    factor_proy = (
        min(factor_teso, factor_rrhh)
        if factor_teso and factor_rrhh
        else max(factor_teso, factor_rrhh)
    )

    saldo_caja_inicial = cargar_saldo_caja_inicial(conn, temporada)
    # Caja inicial de temporada al primer mes del EERR (mismo criterio que cuando
    # ese mes era el primero visible).
    mes_caja_aplicada = mes_inicio_eerr
    filas = []
    eerr = 0.0
    eerr_started = False
    atrasado_aplicado = False
    for idx, row in enumerate(pre):
        anio, mes = row["anio"], row["mes"]
        teso_real = row["teso_real"]
        if (
            not atrasado_aplicado
            and row.get("en_eerr")
            and teso_atrasado > 0.01
            and (anio, mes) == mes_inicio_eerr
        ):
            teso_real += teso_atrasado
            atrasado_aplicado = True
        rrhh_real = row["rrhh_real"]
        teso_proy = row["teso_proy"] * factor_teso
        rrhh_proy = row["rrhh_proy"] * factor_rrhh
        ing = ingresos.get((anio, mes), 0.0)
        if mes_caja_aplicada and (anio, mes) == mes_caja_aplicada and saldo_caja_inicial > 0.01:
            ing += saldo_caja_inicial
        eg_real = teso_real + rrhh_real
        eg_proy = teso_proy + rrhh_proy
        eg_total = eg_real + eg_proy
        rrhh_total = rrhh_real + rrhh_proy
        teso_total = teso_real + teso_proy
        resultado = ing - eg_total
        if row.get("en_eerr"):
            if not eerr_started:
                eerr = 0.0
                eerr_started = True
            eerr += resultado
            eerr_acum = eerr
        else:
            # Historial previo: resultado del mes, sin encadenar al EERR de julio+.
            eerr_acum = resultado
        filas.append(
            {
                "MES": _mes_label(anio, mes),
                "anio": anio,
                "mes": mes,
                "INGRESOS": ing,
                "RRHH": rrhh_total,
                "TESORERIA": teso_total,
                "EGRESOS_REAL": eg_real,
                "EGRESOS_PROY": eg_proy,
                "EGRESOS_TOTAL": eg_total,
                "RESULTADO_MES": resultado,
                "EERR_ACUM": eerr_acum,
                "TESO_REAL": teso_real,
                "TESO_PROY": teso_proy,
                "RRHH_REAL": rrhh_real,
                "RRHH_PROY": rrhh_proy,
                "TESO_ATRASADO": (
                    teso_atrasado
                    if (row.get("en_eerr") and (anio, mes) == mes_inicio_eerr)
                    else 0.0
                ),
            }
        )

    df_flujo = pd.DataFrame(filas)
    df_cc = _armar_ingresos_cc_vista(conn, temporada, meses, cuarteles)
    df_eg_cc = _armar_resumen_egresos_cc(cuarteles, resumen_costos, teso_por_cc_total)
    meta = {
        "temporada": temporada,
        "fi": fi,
        "ff": ff,
        "total_ppto": resumen_costos.get("total_ppto", 0.0),
        "total_gastado": resumen_costos.get("total_gastado", 0.0),
        "total_saldo_ppto": saldo_total,
        "teso_programada_flujo": teso_programada_flujo,
        "teso_meses_anteriores": teso_atrasado,
        "teso_cxp_total": teso_cxp_total,
        "saldo_a_proyectar": teso_proy_asignado,
        "saldo_a_proyectar_teso_bruto": teso_proy_asignado,
        "teso_proy_plan_total": teso_proy_plan_total,
        "teso_proy_residual": residual_teso,
        "teso_proy_cuota_lejos": cuota_teso_lejos * factor_teso if meses_lejos else 0.0,
        "saldo_presupuesto_sin_cxp": saldo_presupuesto_sin_cxp,
        "teso_proy_manual": bool(meses_con_proy_teso),
        "rrhh_base_proy": rrhh_base_proy * factor_rrhh,
        "rrhh_base_proy_bruto": rrhh_base_proy,
        "meses_sin_teso": len(meses_sin_teso),
        "meses_con_proy_teso": len(meses_con_proy_teso),
        "meses_residual_teso": len(meses_residual),
        "mes_inicio_teso_proy_auto": _mes_label(anio_corte, mes_corte_n),
        "pool_proy": pool,
        "factor_proy": factor_proy,
        "factor_teso": factor_teso,
        "factor_rrhh": factor_rrhh,
        "egresos_tope": saldo_total,
        "saldo_caja_inicial": saldo_caja_inicial,
        "mes_caja_aplicada": _mes_label(*mes_caja_aplicada) if mes_caja_aplicada else "",
        "ingresos_flujo_mes_caja": ingresos.get(mes_caja_aplicada, 0.0) if mes_caja_aplicada else 0.0,
        "eerr_arrastrado": 0.0,
        "meses_arrastre": [],
        "ingresos_meses_anteriores": 0.0,
        "rrhh_meses_anteriores": 0.0,
        "meses_historial": [_mes_label(a, m) for a, m in meses if date(a, m, 1) < mes_hoy],
        "mes_inicio_proyeccion": _mes_label(*meses_futuros[0]) if meses_futuros else "",
        "mes_inicio_eerr": _mes_label(*mes_inicio_eerr) if mes_inicio_eerr else "",
    }
    return df_flujo, df_cc, df_eg_cc, meta


def _armar_ingresos_cc_vista(conn, temporada, meses, cuarteles):
    data = cargar_ingresos_cc(conn, temporada)
    filas = []
    for cc in cuarteles:
        row = {"CENTRO_COSTO": cc}
        total = 0.0
        for anio, mes in meses:
            lbl = _mes_label(anio, mes)
            val = data.get((cc, anio, mes), 0.0)
            row[lbl] = val
            total += val
        row["TOTAL"] = total
        filas.append(row)
    if filas:
        tot_row = {"CENTRO_COSTO": "TOTAL FONDO"}
        for anio, mes in meses:
            lbl = _mes_label(anio, mes)
            tot_row[lbl] = sum(filas[i].get(lbl, 0.0) for i in range(len(filas)))
        tot_row["TOTAL"] = sum(r["TOTAL"] for r in filas)
        filas.append(tot_row)
    return pd.DataFrame(filas)


def fila_total_flujo_mensual(df_flujo):
    """Fila TOTAL para la planilla real/proyectado (EERR acum = último mes)."""
    if df_flujo.empty:
        return {}
    tot = {"MES": "TOTAL", "EERR_ACUM": float(df_flujo["EERR_ACUM"].iloc[-1])}
    for col in (
        "INGRESOS", "RRHH", "TESO_REAL", "TESO_PROY",
        "EGRESOS_REAL", "EGRESOS_PROY", "EGRESOS_TOTAL", "RESULTADO_MES",
    ):
        if col in df_flujo.columns:
            tot[col] = float(df_flujo[col].sum())
    return tot


def df_flujo_para_pdf(df_flujo):
    if df_flujo.empty:
        return df_flujo
    cols = [
        "MES", "INGRESOS", "RRHH", "TESO_REAL", "TESO_PROY",
        "EGRESOS_REAL", "EGRESOS_PROY", "EGRESOS_TOTAL", "RESULTADO_MES", "EERR_ACUM",
    ]
    cols = [c for c in cols if c in df_flujo.columns]
    df_out = df_flujo[cols].copy()
    df_out = pd.concat([df_out, pd.DataFrame([fila_total_flujo_mensual(df_flujo)])], ignore_index=True)
    return df_out.rename(
        columns={
            "RRHH": "RRHH SUELDOS",
            "TESO_REAL": "TESO REAL",
            "TESO_PROY": "TESO PROY",
            "EGRESOS_REAL": "EGRESOS REAL",
            "EGRESOS_PROY": "EGRESOS PROY",
            "EGRESOS_TOTAL": "EGRESOS TOTAL",
            "RESULTADO_MES": "RESULTADO MES",
            "EERR_ACUM": "EERR ACUM",
        }
    )
