"""Aviso de Tesorería: documentos con saldo que vencen mañana.

Misma cola que la pantalla de pendientes: estado Pendiente, sin filas de
imputación (_P) ni gastos de estanque (GE-). El saldo es el monto del
documento menos los abonos. Cada documento se avisa una vez por fecha.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from erp_correo_html import html_esc, plantilla_correo_html

_TABLA = "alerta_tesoreria_vencimiento"


def fecha_manana(hoy: date) -> date:
    return hoy + timedelta(days=1)


def formato_peso(valor: float) -> str:
    try:
        n = int(round(float(valor)))
    except (TypeError, ValueError):
        n = 0
    signo = "-" if n < 0 else ""
    return f"{signo}${abs(n):,}".replace(",", ".")


def fecha_visible(iso: str) -> str:
    texto = (iso or "")[:10]
    partes = texto.split("-")
    if len(partes) != 3:
        return texto or "—"
    anio, mes, dia = partes
    return f"{dia}-{mes}-{anio}"


def asegurar_tabla(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {_TABLA} (
            factura_id INTEGER NOT NULL,
            fecha_vencimiento TEXT NOT NULL,
            enviado_en TEXT NOT NULL,
            PRIMARY KEY (factura_id, fecha_vencimiento)
        )"""
    )


def _saldo(monto_total, monto_pagado) -> float:
    try:
        return max(0.0, float(monto_total or 0) - float(monto_pagado or 0))
    except (TypeError, ValueError):
        return 0.0


def documentos_por_vencer(
    conn: sqlite3.Connection,
    hoy: date,
    *,
    excluir_razon_social: str | None = None,
) -> list[dict]:
    """Pendientes con saldo cuyo vencimiento es el día siguiente a ``hoy``."""
    asegurar_tabla(conn)
    manana = fecha_manana(hoy).isoformat()
    excluir = (excluir_razon_social or "").strip().casefold()
    rows = conn.execute(
        f"""SELECT f.id, f.nro_documento, f.proveedor,
                   TRIM(COALESCE(f.razon_social, '')) AS razon_social,
                   date(f.fecha_vencimiento) AS fecha_vencimiento,
                   f.monto_total,
                   COALESCE(f.monto_pagado, 0) AS monto_pagado
            FROM facturas f
            WHERE f.estado = 'Pendiente'
              AND f.monto_total > 0
              AND f.nro_documento NOT LIKE '%_P'
              AND UPPER(TRIM(f.nro_documento)) NOT GLOB 'GE-*'
              AND date(f.fecha_vencimiento) = ?
              AND NOT EXISTS (
                    SELECT 1 FROM {_TABLA} a
                    WHERE a.factura_id = f.id
                      AND a.fecha_vencimiento = date(f.fecha_vencimiento)
              )
            ORDER BY f.proveedor, f.nro_documento, f.id""",
        (manana,),
    ).fetchall()
    salida: list[dict] = []
    for row in rows:
        razon = str(row[3] or "").strip()
        if excluir and razon.casefold() == excluir:
            continue
        saldo = _saldo(row[5], row[6])
        if saldo <= 0.01:
            continue
        salida.append(
            {
                "id": int(row[0]),
                "nro_documento": str(row[1] or "").strip(),
                "proveedor": str(row[2] or "").strip(),
                "razon_social": razon,
                "fecha_vencimiento": str(row[4] or manana)[:10],
                "saldo": saldo,
            }
        )
    return salida


def marcar_avisados(conn: sqlite3.Connection, docs: list[dict], enviado_en: str) -> None:
    asegurar_tabla(conn)
    conn.executemany(
        f"""INSERT OR IGNORE INTO {_TABLA}
            (factura_id, fecha_vencimiento, enviado_en) VALUES (?, ?, ?)""",
        [
            (int(d["id"]), str(d["fecha_vencimiento"])[:10], enviado_en)
            for d in docs
        ],
    )


def armar_correo(nombre_erp: str, docs: list[dict]) -> tuple[str, str]:
    marca = (nombre_erp or "ERP Agrícola").strip()
    n = len(docs)
    cuando = fecha_visible(docs[0]["fecha_vencimiento"]) if docs else ""
    filas = []
    total = 0.0
    for d in docs:
        total += float(d["saldo"])
        razon = d["razon_social"] or "—"
        filas.append(
            "<tr>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #eee;'>{html_esc(d['nro_documento'])}</td>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #eee;'>{html_esc(d['proveedor'])}</td>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #eee;'>{html_esc(razon)}</td>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #eee;'>{html_esc(fecha_visible(d['fecha_vencimiento']))}</td>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #eee;text-align:right;'>{html_esc(formato_peso(d['saldo']))}</td>"
            "</tr>"
        )
    palabra = "documento" if n == 1 else "documentos"
    interior = f"""
        <p style="color:#1F2933;line-height:1.55;margin:0 0 12px;">
          Mañana <b>{html_esc(cuando)}</b> vence el saldo de {n} {palabra} en Tesorería.
        </p>
        <table style="width:100%;border-collapse:collapse;font-size:14px;">
          <thead>
            <tr style="text-align:left;color:#5F6B7A;">
              <th style="padding:6px 8px;">Documento</th>
              <th style="padding:6px 8px;">Proveedor</th>
              <th style="padding:6px 8px;">Razón social</th>
              <th style="padding:6px 8px;">Vencimiento</th>
              <th style="padding:6px 8px;text-align:right;">Saldo</th>
            </tr>
          </thead>
          <tbody>
            {''.join(filas)}
          </tbody>
        </table>
        <p style="margin:14px 0 0;"><b>Saldo por vencer:</b> {html_esc(formato_peso(total))}</p>
    """
    cuerpo = plantilla_correo_html(
        "vencimiento",
        "Documentos que vencen mañana",
        interior,
        nombre_erp=marca,
        pie="Aviso automático de Tesorería. Quien tiene Mail tesorería recibe este correo.",
    )
    asunto = f"[{marca}] Vence mañana: {n} {palabra}"
    return asunto, cuerpo
