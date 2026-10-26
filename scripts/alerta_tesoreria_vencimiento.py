#!/usr/bin/env python3
"""Aviso diario de Tesorería: documentos con saldo que vencen hoy.

La Concepción y El Espino, cada uno a sus usuarios con Mail tesorería.
La hora de envío es las 07:00 de Chile o más tarde el mismo día, por si
el servidor no estaba a las 07:00. El cron puede correr cada hora desde
esa hora: antes de las 07:00 no hace nada y, después, no repite un
documento ya avisado.

  python3 scripts/alerta_tesoreria_vencimiento.py
  python3 scripts/alerta_tesoreria_vencimiento.py --ahora
  python3 scripts/alerta_tesoreria_vencimiento.py --dry-run --ahora
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CHILE = ZoneInfo("America/Santiago")
HORA_ENVIO = 7
SLUGS = ("concepcion", "espino")


def _ahora_chile() -> datetime:
    return datetime.now(CHILE)


def _dentro_de_horario(ahora: datetime) -> bool:
    return ahora.hour >= HORA_ENVIO


def _procesar(slug: str, hoy, enviar: bool) -> dict:
    from flask import Flask, g, session

    from demo_web.services.erp_loader import get_erp_module_for
    from demo_web.services.tenant_scope import RAZON_SOCIAL_ESPINO
    from demo_web.services.tesoreria_alerta import (
        armar_correo,
        documentos_por_vencer,
        marcar_avisados,
    )

    app = Flask("alerta_tesoreria")
    app.secret_key = "alerta-tesoreria"
    with app.test_request_context("/"):
        session["tenant_slug"] = slug
        g.tenant_slug = slug
        erp = get_erp_module_for(slug)
        conn = erp.conectar_db()
        try:
            excluir = RAZON_SOCIAL_ESPINO if slug == "concepcion" else None
            docs = documentos_por_vencer(conn, hoy, excluir_razon_social=excluir)
            if not docs:
                return {"slug": slug, "n": 0, "enviado": False, "motivo": "sin documentos"}
            dest = []
            try:
                dest = [d for d in (erp.obtener_destinatarios_tesoreria(conn) or []) if str(d).strip()]
            except Exception:
                dest = []
            if not dest:
                return {
                    "slug": slug,
                    "n": len(docs),
                    "enviado": False,
                    "motivo": "sin destinatarios",
                }
            asunto, cuerpo = armar_correo(getattr(erp, "NOMBRE_ERP", "") or slug, docs)
            if not enviar:
                return {
                    "slug": slug,
                    "n": len(docs),
                    "destinatarios": len(dest),
                    "enviado": False,
                    "motivo": "simulacion",
                    "docs": [d["nro_documento"] for d in docs],
                }
            ok = bool(erp._enviar_correo_html(asunto, cuerpo, dest))
            if not ok:
                return {"slug": slug, "n": len(docs), "enviado": False, "motivo": "fallo smtp"}
            marca = _ahora_chile().strftime("%Y-%m-%d %H:%M:%S")
            marcar_avisados(conn, docs, marca)
            try:
                fh = erp.hora_chile().strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                fh = marca
            vence = docs[0]["fecha_vencimiento"]
            conn.execute(
                "INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)",
                (
                    "sistema",
                    "ALERTA TESORERIA",
                    f"{len(docs)} documento(s) vencen {vence}; aviso a {len(dest)} correo(s)",
                    fh,
                ),
            )
            conn.commit()
            return {
                "slug": slug,
                "n": len(docs),
                "destinatarios": len(dest),
                "enviado": True,
                "docs": [d["nro_documento"] for d in docs],
            }
        finally:
            conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ahora",
        action="store_true",
        help="Enviar aunque todavía no sean las 07:00 de Chile.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Lista los documentos y no envía ni marca el aviso.",
    )
    args = parser.parse_args(argv)
    ahora = _ahora_chile()
    print(f"alerta tesoreria {ahora.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    if not args.ahora and not _dentro_de_horario(ahora):
        print(f"antes de las {HORA_ENVIO:02d}:00 Chile; no envía")
        return 0
    fallo = False
    for slug in SLUGS:
        try:
            res = _procesar(slug, ahora.date(), enviar=not args.dry_run)
        except Exception as exc:
            print(f"{slug}: ERROR {type(exc).__name__}: {exc}")
            fallo = True
            continue
        print(f"{slug}: {res}")
        if res.get("motivo") == "fallo smtp":
            fallo = True
    return 1 if fallo else 0


if __name__ == "__main__":
    raise SystemExit(main())
