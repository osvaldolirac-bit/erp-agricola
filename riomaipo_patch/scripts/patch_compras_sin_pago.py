#!/usr/bin/env python3
"""Quita pago redundante de Compras; el pago queda solo en Tesorería."""
from __future__ import annotations
import shutil
from pathlib import Path

ROOT = Path("/root/riomaipo/rmweb")
SRC = Path(__file__).resolve().parents[1] / "rmweb" / "templates" / "compras"
OV = ROOT / "ops_views.py"

def main() -> int:
    for name in ("lista.html", "detalle.html"):
        src = SRC / name
        dst = ROOT / "templates" / "compras" / name
        if not src.exists():
            raise SystemExit(f"missing {src}")
        shutil.copy2(dst, dst.with_suffix(dst.suffix + ".bak_sinpago"))
        shutil.copy2(src, dst)
        print(f"OK {dst}")
    text = OV.read_text(encoding="utf-8")
    needle = """                flash(f"Pago de {core.clp(monto)} registrado", "ok")
                db.close()
                return redirect(url_for("compras_detalle", fid=fid))"""
    repl = """                flash(f"Pago de {core.clp(monto)} registrado", "ok")
                db.close()
                return redirect(url_for("tesoreria_list"))"""
    if needle in text:
        OV.write_text(text.replace(needle, repl, 1), encoding="utf-8")
        print("OK ops_views redirect")
    elif 'return redirect(url_for("tesoreria_list"))' in text:
        print("ops_views already redirects to tesoreria_list")
    else:
        print("WARN: redirect pattern not found")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
