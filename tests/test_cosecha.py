"""Cosecha: números que mueren, totes por cuartel y un solo pase a compras."""
from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

from demo_web.services.cosecha import (
    abrir_faena,
    aplicar_en_compras,
    asegurar_tablas,
    atender_anotadora,
    contar_totes,
    dar_de_baja,
    entregar_funda,
    filtrar_cuarteles_cosecha,
    guardar_persona,
    guardar_precio,
    listar_fundas,
    listar_links,
    nueva_faena,
    payload_qr,
    plan_cierre,
    planilla_numeros,
    registrar_abono,
    sumar_tote,
    url_whatsapp,
    validar_rut_cosecha,
    vista_anotadora,
)

LC = [
    "CEREZOS CORTE 1",
    "CEREZOS CORTE 2",
    "CIRUELOS",
    "NOGALES APARICION",
    "NOGALES CRUZ DEL SUR",
    "EL ESPINO",
]
ESPINO = ["ROYAL DOWN", "SWEET ARYANA", "SANTINA"]


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE contratistas (
            id INTEGER PRIMARY KEY,
            razon_social TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE facturas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nro_documento TEXT,
            proveedor TEXT,
            monto_total REAL,
            contratista_id INTEGER,
            concepto TEXT,
            centro_costo TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE facturas_abonos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            factura_id INTEGER,
            fecha TEXT,
            monto REAL,
            metodo_pago TEXT,
            usuario TEXT,
            fecha_registro TEXT,
            banco TEXT
        )"""
    )
    conn.execute("INSERT INTO contratistas (id, razon_social) VALUES (1, 'Cuadrilla Sur')")
    conn.execute("INSERT INTO contratistas (id, razon_social) VALUES (2, 'Cuadrilla Espino')")
    return conn


class TestCuarteles(unittest.TestCase):
    def test_cada_tenant_conserva_sus_cuarteles(self):
        lc = filtrar_cuarteles_cosecha(LC, espino=False)
        self.assertEqual(
            lc,
            [
                "CEREZOS CORTE 1",
                "CEREZOS CORTE 2",
                "CIRUELOS",
                "NOGALES APARICION",
                "NOGALES CRUZ DEL SUR",
            ],
        )
        self.assertNotIn("EL ESPINO", lc)
        self.assertEqual(filtrar_cuarteles_cosecha(ESPINO, espino=True), ESPINO)
        self.assertEqual(filtrar_cuarteles_cosecha(LC, espino=True), [])
        self.assertEqual(filtrar_cuarteles_cosecha(ESPINO, espino=False), [])


class TestFaena(unittest.TestCase):
    def test_el_numero_muerto_no_se_repite_y_los_totes_no_se_mezclan(self):
        conn = _conn()
        ok, _msg, faena = abrir_faena(conn, 1, filtrar_cuarteles_cosecha(LC, espino=False), "2026-11-20")
        self.assertTrue(ok)
        ok, _msg, faena_espino = abrir_faena(conn, 2, filtrar_cuarteles_cosecha(ESPINO, espino=True), "2026-11-20")
        self.assertTrue(ok)
        self.assertEqual(
            [x["cuartel"] for x in listar_links(conn, faena_espino)],
            ESPINO,
        )
        self.assertFalse(any("NOGAL" in x["cuartel"] or "CIRUELO" in x["cuartel"] for x in listar_links(conn, faena_espino)))
        self.assertFalse(any(x["cuartel"] in ESPINO for x in listar_links(conn, faena)))

        ok, _msg, n1 = entregar_funda(conn, faena, "Ana")
        ok, _msg, n2 = entregar_funda(conn, faena, "Luis")
        self.assertEqual((n1, n2), (1, 2))
        ok, msg = dar_de_baja(conn, faena, 1)
        self.assertTrue(ok, msg)
        ok, _msg, n3 = entregar_funda(conn, faena, "María")
        self.assertEqual(n3, 3)

        links = {x["cuartel"]: x["token"] for x in listar_links(conn, faena)}
        corte = links["CEREZOS CORTE 1"]
        ciruelos = links["CIRUELOS"]
        ok, msg, _n = sumar_tote(conn, corte, 1, "2026-11-20 08:00:00")
        self.assertFalse(ok)
        self.assertIn("ya no se usa", msg)
        ok, _msg, _n = sumar_tote(conn, corte, 2, "2026-11-20 08:00:00")
        ok, _msg, _n = sumar_tote(conn, corte, 2, "2026-11-20 08:05:00")
        ok, _msg, _n = sumar_tote(conn, ciruelos, 2, "2026-11-20 09:00:00")
        self.assertEqual(contar_totes(conn, faena, "CEREZOS CORTE 1"), 2)
        self.assertEqual(contar_totes(conn, faena, "CIRUELOS"), 1)
        self.assertEqual(contar_totes(conn, faena_espino, "SANTINA"), 0)

        ok, _msg, nueva = nueva_faena(conn, faena_espino, ESPINO, "2026-11-21")
        self.assertTrue(ok)
        ok, _msg, primero = entregar_funda(conn, nueva, "Pedro")
        self.assertEqual(primero, 1)
        self.assertEqual(contar_totes(conn, faena, "CEREZOS CORTE 1"), 2)

    def test_el_pase_a_compras_es_el_bruto_de_un_cuartel_y_no_se_repite(self):
        conn = _conn()
        _ok, _msg, faena = abrir_faena(conn, 1, ["CIRUELOS"], "2026-11-20")
        _ok, _msg, _n = entregar_funda(conn, faena, "Ana")
        token = listar_links(conn, faena)[0]["token"]
        for hora in ("08:00:00", "08:10:00", "08:20:00"):
            sumar_tote(conn, token, 1, f"2026-11-20 {hora}")
        guardar_precio(conn, faena, "CIRUELOS", 1000)
        registrar_abono(conn, faena, "CIRUELOS", 1500, "Adelanto", "2026-11-20")
        ok, msg, plan = plan_cierre(conn, faena, "CIRUELOS")
        self.assertTrue(ok, msg)
        self.assertEqual(plan["selcc"], ["CIRUELOS"])
        self.assertEqual(plan["totes"], 3)
        self.assertEqual(plan["bruto"], 3000)
        self.assertEqual(sum(a["monto"] for a in plan["abonos"]), 1500)
        self.assertNotIn("1500", plan["concepto"])

        llamadas = []

        def registrar(cid, proveedor, nro, f_compra, f_vence, monto, concepto, selcc):
            llamadas.append({"monto": monto, "selcc": list(selcc), "concepto": concepto})
            conn.execute(
                """INSERT INTO facturas (nro_documento, proveedor, monto_total, contratista_id, concepto)
                   VALUES (?,?,?,?,?)""",
                (nro, proveedor, monto, cid, concepto),
            )
            return True, None

        ok, doc = aplicar_en_compras(conn, plan, registrar, "CONTR-20261120-01", "2026-11-20", "oficina")
        self.assertTrue(ok, doc)
        self.assertEqual(len(llamadas), 1)
        self.assertEqual(llamadas[0]["monto"], 3000)
        self.assertEqual(llamadas[0]["selcc"], ["CIRUELOS"])
        abonos = conn.execute("SELECT factura_id, monto, metodo_pago FROM facturas_abonos").fetchall()
        self.assertEqual(abonos, [(1, 1500, "Abono cosecha")])
        ok, msg, _plan = plan_cierre(conn, faena, "CIRUELOS")
        self.assertFalse(ok)
        self.assertIn("ya pasó", msg)
        self.assertEqual(len(llamadas), 1)
        marca = conn.execute("SELECT factura_abono_id FROM cosecha_abono").fetchone()
        self.assertEqual(marca[0], 1)

    def test_el_telefono_no_lleva_precios(self):
        conn = _conn()
        _ok, _msg, faena = abrir_faena(conn, 1, ["NOGALES APARICION"], "2026-11-20")
        entregar_funda(conn, faena, "Ana")
        token = listar_links(conn, faena)[0]["token"]
        ctx = vista_anotadora(conn, token, "ingresado", 1)
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx["estado_cuenta"], "Parcial")
        self.assertNotIn("precio", ctx)
        self.assertNotIn("bruto", ctx)
        self.assertEqual(ctx["filas"][0]["nombre"], "Ana")
        html = Path("demo_web/templates/cosecha_anotadora.html").read_text(encoding="utf-8")
        self.assertIn("+ 1 tote", html)
        self.assertIn('name="nombre"', html)
        self.assertIn('name="rut"', html)
        self.assertIn("Deshacer el último", html)
        self.assertNotIn("precio", html.lower())
        self.assertNotIn("abono", html.lower())
        self.assertNotIn("peso", html.lower())
        self.assertNotIn("Escanear", html)
        self.assertNotIn("QR", html)
        self.assertNotIn("Generar", html)

    def test_el_enlace_se_comparte_por_whatsapp(self):
        from urllib.parse import unquote

        url = "https://erpmaster.cl/agricola/cosecha/abc?tenant=concepcion"
        wa = url_whatsapp("CEREZOS CORTE 1", url, "La Concepción")
        self.assertTrue(wa.startswith("https://wa.me/?text="))
        texto = unquote(wa.split("?text=", 1)[1])
        self.assertIn(url, texto)
        self.assertIn("CEREZOS CORTE 1", texto)
        self.assertIn("tenant=concepcion", texto)
        self.assertNotIn("precio", texto.lower())
        espino = unquote(
            url_whatsapp(
                "SANTINA",
                "https://erpmaster.cl/agricola/cosecha/abc?tenant=espino",
                "El Espino",
            ).split("?text=", 1)[1]
        )
        self.assertIn("tenant=espino", espino)
        self.assertNotIn("CEREZOS", espino)
        html = Path("demo_web/templates/modules/rrhh.html").read_text(encoding="utf-8")
        self.assertIn("link.wa_url", html)
        self.assertIn(">WhatsApp</a>", html)

    def test_la_oficina_arma_la_planilla_sin_qr(self):
        self.assertEqual(payload_qr(12), "12")
        html = Path("demo_web/templates/modules/rrhh.html").read_text(encoding="utf-8")
        self.assertIn("Planilla de la faena", html)
        self.assertIn("cosecha_persona", html)
        self.assertIn("Pasar a compras", html)
        self.assertNotIn("Generar QR", html)
        self.assertNotIn("cosecha_imprimir", html)


class TestNumeroYRut(unittest.TestCase):
    def test_mas_uno_crea_el_numero_y_la_planilla_separa_cuarteles(self):
        conn = _conn()
        _ok, _msg, faena = abrir_faena(
            conn, 1, filtrar_cuarteles_cosecha(LC, espino=False), "2026-11-20"
        )
        links = {x["cuartel"]: x["token"] for x in listar_links(conn, faena)}
        ok, msg, n = sumar_tote(conn, links["CEREZOS CORTE 1"], 7, "2026-11-20 08:00:00")
        self.assertTrue(ok, msg)
        self.assertEqual(n, 7)
        self.assertIn("lleva 1", msg)
        ok, msg = guardar_persona(conn, faena, 7, "Ana Soto", "12.345.678-5")
        self.assertTrue(ok, msg)
        ok, msg = guardar_persona(conn, faena, 7, "Ana Soto", "12.345.678-9")
        self.assertFalse(ok)
        self.assertIn("RUT", msg)
        sumar_tote(conn, links["CIRUELOS"], 7, "2026-11-20 09:00:00")
        sumar_tote(conn, links["CIRUELOS"], 7, "2026-11-20 09:10:00")
        planilla = planilla_numeros(conn, faena)
        self.assertEqual(len(planilla), 1)
        self.assertEqual(planilla[0]["numero"], 7)
        self.assertEqual(planilla[0]["nombre"], "Ana Soto")
        self.assertEqual(planilla[0]["rut"], "12.345.678-5")
        self.assertEqual(planilla[0]["totes"]["CEREZOS CORTE 1"], 1)
        self.assertEqual(planilla[0]["totes"]["CIRUELOS"], 2)
        self.assertEqual(planilla[0]["totes"]["NOGALES APARICION"], 0)
        self.assertNotIn("SANTINA", planilla[0]["totes"])
        self.assertNotIn("EL ESPINO", planilla[0]["totes"])
        self.assertEqual(planilla[0]["total"], 3)
        ok, _msg = dar_de_baja(conn, faena, 7)
        self.assertTrue(ok)
        ok, msg, _n = sumar_tote(conn, links["CEREZOS CORTE 1"], 7, "2026-11-20 10:00:00")
        self.assertFalse(ok)
        self.assertIn("ya no se usa", msg)

    def test_el_rut_chileno_y_la_columna_nueva_conservan_el_nombre(self):
        ok, _msg, fmt = validar_rut_cosecha("12345678-5")
        self.assertTrue(ok)
        self.assertEqual(fmt, "12.345.678-5")
        ok, _msg, vacio = validar_rut_cosecha("  ")
        self.assertTrue(ok)
        self.assertEqual(vacio, "")
        ok, _msg, _fmt = validar_rut_cosecha("12.345.678-9")
        self.assertFalse(ok)
        conn = sqlite3.connect(":memory:")
        conn.execute(
            """CREATE TABLE cosecha_funda (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                faena_id INTEGER NOT NULL,
                numero INTEGER NOT NULL,
                nombre TEXT NOT NULL DEFAULT '',
                estado TEXT NOT NULL DEFAULT 'activa'
            )"""
        )
        conn.execute(
            "INSERT INTO cosecha_funda (faena_id, numero, nombre, estado) VALUES (1, 1, 'Ana', 'activa')"
        )
        conn.execute(
            "INSERT INTO cosecha_funda (faena_id, numero, nombre, estado) VALUES (1, 2, 'Luis', 'activa')"
        )
        conn.execute(
            "INSERT INTO cosecha_funda (faena_id, numero, nombre, estado) VALUES (1, 3, 'María', 'activa')"
        )
        asegurar_tablas(conn)
        fundas = listar_fundas(conn, 1)
        self.assertEqual([f["nombre"] for f in fundas], ["Ana", "Luis", "María"])
        self.assertEqual([f["numero"] for f in fundas], [1, 2, 3])
        self.assertEqual([f["rut"] for f in fundas], ["", "", ""])


class TestAtender(unittest.TestCase):
    def test_deshacer_el_ultimo_de_ese_cuartel(self):
        conn = _conn()
        _ok, _msg, faena = abrir_faena(conn, 1, ["CEREZOS CORTE 2"], "2026-11-20")
        entregar_funda(conn, faena, "Ana")
        token = listar_links(conn, faena)[0]["token"]
        atender_anotadora(conn, token, "sumar", 1, "", "2026-11-20 10:00:00")
        atender_anotadora(conn, token, "sumar", 1, "", "2026-11-20 10:05:00")
        ok, _msg, n = atender_anotadora(conn, token, "deshacer", None, "", "")
        self.assertTrue(ok)
        self.assertEqual(n, 1)
        self.assertEqual(contar_totes(conn, faena, "CEREZOS CORTE 2"), 1)
        ok, msg, creado = atender_anotadora(conn, token, "sumar", 4, "", "2026-11-20 11:00:00")
        self.assertTrue(ok, msg)
        self.assertEqual(creado, 4)
        ok, msg, persona = atender_anotadora(
            conn, token, "persona", 4, "Pedro", "2026-11-20 11:01:00", "12345678-5"
        )
        self.assertTrue(ok, msg)
        self.assertEqual(persona, 4)
        self.assertEqual(listar_fundas(conn, faena)[-1]["rut"], "12.345.678-5")


if __name__ == "__main__":
    unittest.main()
