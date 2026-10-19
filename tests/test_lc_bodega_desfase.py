"""LC Libro ↔ bodega: emparejamiento y movimiento_id (SQLite en memoria)."""
from __future__ import annotations

import sqlite3
import unittest

from demo_web.services.lc_bodega_desfase import (
    ensure_movimiento_id_column,
    insertar_salida_desde_lc,
    lc_dict_desde_linea_libro,
    revertir_salida_desde_lc,
    revertir_salidas_lineas_libro,
    vincular_movimiento_linea_libro,
)


def _mem_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE inventario (
            id INTEGER PRIMARY KEY,
            producto TEXT,
            precio_medio REAL,
            unidad_medida TEXT,
            stock REAL
        );
        CREATE TABLE movimientos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            producto_id INTEGER,
            tipo TEXT,
            cantidad REAL,
            fecha TEXT,
            centro_costo TEXT,
            valor_imputado REAL,
            unidad_medida TEXT
        );
        CREATE TABLE libro_campo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            n_aplicacion INTEGER,
            fecha TEXT,
            sector TEXT,
            producto TEXT,
            gasto_total REAL,
            movimiento_id INTEGER
        );
        """
    )
    conn.execute(
        "INSERT INTO inventario (id, producto, precio_medio, unidad_medida, stock) VALUES (1, 'EVOLUTION', 10, 'L', 100)"
    )
    return conn


class TestMovimientoIdColumn(unittest.TestCase):
    def test_ensure_column(self):
        conn = _mem_db()
        conn.execute("DROP TABLE libro_campo")
        conn.execute(
            "CREATE TABLE libro_campo (id INTEGER PRIMARY KEY, producto TEXT, gasto_total REAL)"
        )
        ensure_movimiento_id_column(conn)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(libro_campo)").fetchall()}
        self.assertIn("movimiento_id", cols)


class TestInsertarSalida(unittest.TestCase):
    def test_crea_movimiento_y_descuenta_stock(self):
        conn = _mem_db()
        lc = {"producto": "EVOLUTION", "gasto": 5.0, "sector": "CIRUELOS", "fecha": "2026-09-17"}
        res = insertar_salida_desde_lc(conn, lc)
        self.assertTrue(res.get("ok"))
        self.assertIn("mov_id", res)
        st = conn.execute("SELECT stock FROM inventario WHERE id=1").fetchone()[0]
        self.assertAlmostEqual(st, 95.0)
        cnt = conn.execute("SELECT COUNT(*) FROM movimientos").fetchone()[0]
        self.assertEqual(cnt, 1)

    def test_dup_no_reutiliza_mov_vinculado_a_otra_linea(self):
        conn = _mem_db()
        lc1 = {"producto": "EVOLUTION", "gasto": 5.0, "sector": "CIRUELOS", "fecha": "2026-09-17"}
        r1 = insertar_salida_desde_lc(conn, lc1)
        mov1 = int(r1["mov_id"])
        conn.execute(
            "INSERT INTO libro_campo (n_aplicacion, fecha, sector, producto, gasto_total, movimiento_id)"
            " VALUES (19, '2026-09-17', 'CIRUELOS', 'EVOLUTION', 5, ?)",
            (mov1,),
        )
        lc2 = dict(lc1)
        r2 = insertar_salida_desde_lc(conn, lc2)
        self.assertTrue(r2.get("ok"))
        self.assertNotIn("skipped", r2)
        self.assertNotEqual(int(r2["mov_id"]), mov1)
        st = conn.execute("SELECT stock FROM inventario WHERE id=1").fetchone()[0]
        self.assertAlmostEqual(st, 90.0)


class TestRevertirSalida(unittest.TestCase):
    def test_usa_movimiento_id_ligado(self):
        conn = _mem_db()
        conn.execute(
            """INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado, unidad_medida)
               VALUES (1, 'Salida', 5, '2026-09-17', 'CIRUELOS', 50, 'L')"""
        )
        mov_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        conn.execute("UPDATE inventario SET stock=95 WHERE id=1")
        conn.execute(
            """INSERT INTO libro_campo (n_aplicacion, fecha, sector, producto, gasto_total, movimiento_id)
               VALUES (20, '2026-09-17', 'CIRUELOS', 'EVOLUTION', 5, ?)""",
            (mov_id,),
        )
        row = conn.execute(
            "SELECT id, movimiento_id, producto, gasto_total, fecha, sector FROM libro_campo WHERE id=1"
        ).fetchone()
        linea = {
            "id": row[0],
            "movimiento_id": row[1],
            "producto": row[2],
            "gasto_total": row[3],
            "fecha": row[4],
            "sector": row[5],
        }
        lc = lc_dict_desde_linea_libro(linea)
        res = revertir_salida_desde_lc(conn, lc)
        self.assertEqual(res.get("mov_id"), mov_id)
        self.assertIsNone(conn.execute("SELECT id FROM movimientos WHERE id=?", (mov_id,)).fetchone())
        st = conn.execute("SELECT stock FROM inventario WHERE id=1").fetchone()[0]
        self.assertAlmostEqual(st, 100.0)

    def test_dos_lineas_dos_movimientos_sin_cruzar(self):
        conn = _mem_db()
        for n_app in (19, 20):
            lc = {"producto": "EVOLUTION", "gasto": 3.0, "sector": "CIRUELOS", "fecha": "2026-09-17"}
            r = insertar_salida_desde_lc(conn, lc)
            mid = int(r["mov_id"])
            conn.execute(
                """INSERT INTO libro_campo (n_aplicacion, fecha, sector, producto, gasto_total, movimiento_id)
                   VALUES (?, '2026-09-17', 'CIRUELOS', 'EVOLUTION', 3, ?)""",
                (n_app, mid),
            )
        rows = [
            dict(
                zip(
                    ["id", "movimiento_id", "producto", "gasto_total", "fecha", "sector"],
                    r,
                )
            )
            for r in conn.execute(
                "SELECT id, movimiento_id, producto, gasto_total, fecha, sector FROM libro_campo ORDER BY id"
            ).fetchall()
        ]
        rev = revertir_salidas_lineas_libro(conn, rows)
        mov_ids = {int(x["mov_id"]) for x in rev if x.get("mov_id")}
        self.assertEqual(len(mov_ids), 2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM movimientos").fetchone()[0], 0)
        st = conn.execute("SELECT stock FROM inventario WHERE id=1").fetchone()[0]
        self.assertAlmostEqual(st, 100.0)


class TestVincular(unittest.TestCase):
    def test_vincular_persiste(self):
        conn = _mem_db()
        ensure_movimiento_id_column(conn)
        conn.execute(
            "INSERT INTO libro_campo (n_aplicacion, producto, gasto_total) VALUES (1, 'X', 1)"
        )
        lid = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        vincular_movimiento_linea_libro(conn, lid, 42)
        mid = conn.execute("SELECT movimiento_id FROM libro_campo WHERE id=?", (lid,)).fetchone()[0]
        self.assertEqual(mid, 42)


if __name__ == "__main__":
    unittest.main()
