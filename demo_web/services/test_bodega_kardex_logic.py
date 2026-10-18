"""Smoke test lógica kardex LC (sin Flask)."""
from __future__ import annotations

import sqlite3
import types

from demo_web.services import bodega_kardex


def _demo_stub():
    return types.SimpleNamespace(
        DEFAULT_UNIDAD_INSUMO="L",
        CENTROS_COSTO=["C1"],
        f_cantidad=lambda x: f"{x:.1f}".replace(".", ","),
    )


def test_apertura_solo_movimientos_sin_lc_sintetico():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE inventario (
            id INTEGER PRIMARY KEY, producto TEXT, familia TEXT,
            unidad_medida TEXT, stock REAL, ingrediente_activo TEXT
        );
        CREATE TABLE movimientos (
            id INTEGER PRIMARY KEY, producto_id INTEGER, tipo TEXT,
            cantidad REAL, fecha TEXT, centro_costo TEXT,
            valor_imputado REAL, unidad_medida TEXT
        );
        CREATE TABLE libro_campo (
            id INTEGER PRIMARY KEY, n_aplicacion INTEGER, fecha TEXT,
            sector TEXT, gasto_total REAL, producto TEXT
        );
        CREATE TABLE facturas (
            id INTEGER PRIMARY KEY, nro_documento TEXT, fecha_compra TEXT,
            concepto TEXT, monto_total REAL
        );
        """
    )
    conn.execute(
        "INSERT INTO inventario VALUES (109,'BRASSTEC','F','L',22,'')"
    )
    conn.executemany(
        "INSERT INTO movimientos VALUES (?,?,?,?,?,?,?,?)",
        [
            (131, 109, "Ingreso", 20, "2026-09-16", "BODEGA", 0, "L"),
            (146, 109, "Ingreso", 20, "2026-10-16", "BODEGA", 0, "L"),
            (1, 109, "Salida", 8.4, "2026-09-20", "C1", 0, "L"),
            (2, 109, "Salida", 12, "2026-10-01", "C1", 0, "L"),
        ],
    )
    conn.execute(
        "INSERT INTO libro_campo VALUES (1,100,'2026-09-21','C1',30,'BRASSTEC')"
    )
    conn.execute(
        """INSERT INTO facturas VALUES
           (1,'1535','2026-09-16','20 L x BRASSTEC',100),
           (2,'1587','2026-10-16','20 L x BRASSTEC',100)"""
    )
    demo = _demo_stub()
    ctx = bodega_kardex.gather_kardex_producto(demo, conn, 109, include_pdf=False)
    rows = ctx["kardex_rows"]
    compras = [r for r in rows if r.get("es_compra")]
    assert len(compras) == 2
    assert compras[-1]["origen"].startswith("Compra N° 1587")
    apertura = [r for r in rows if "arrastre" in r["origen"].lower()]
    assert len(apertura) == 1
    assert abs(apertura[0]["cant_raw"] - 2.4) < 0.05
    assert abs(rows[-1]["saldo_raw"] - 22.0) < 0.05
    assert len(ctx["kardex_lc_pendientes"]) >= 1


if __name__ == "__main__":
    test_apertura_solo_movimientos_sin_lc_sintetico()
    print("OK")
