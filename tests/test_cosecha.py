"""Cosecha: números que mueren, totes por cuartel y un solo pase a compras."""
from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

from demo_web.services.cosecha import (
    abrir_faena,
    asegurar_tablas,
    atender_anotadora,
    contar_totes,
    dar_de_baja,
    deshacer_ultimo,
    detalle_ingresos,
    entregar_funda,
    filtrar_cuarteles_cosecha,
    guardar_persona,
    enlace_todos,
    listar_fundas,
    listar_links,
    nueva_faena,
    payload_qr,
    planilla_numeros,
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

    def test_cerrar_la_faena_no_escribe_en_compras(self):
        conn = _conn()
        _ok, _msg, faena = abrir_faena(conn, 1, ["CIRUELOS"], "2026-11-20")
        token = listar_links(conn, faena)[0]["token"]
        for hora in ("08:00:00", "08:10:00", "08:20:00"):
            sumar_tote(conn, token, 1, f"2026-11-20 {hora}")
        ok, msg, nueva = nueva_faena(conn, faena, ["CIRUELOS"], "2026-11-21")
        self.assertTrue(ok, msg)
        self.assertNotEqual(nueva, faena)
        self.assertEqual(contar_totes(conn, faena, "CIRUELOS"), 3)
        ok, msg, _n = sumar_tote(conn, token, 1, "2026-11-21 09:00:00", "2026-11-21")
        self.assertFalse(ok)
        self.assertIn("faena ya está cerrada", msg)
        self.assertEqual(contar_totes(conn, faena, "CIRUELOS"), 3)
        vieja = vista_anotadora(conn, token, "ingreso", None, "2026-11-21")
        self.assertTrue(vieja["cerrado"])
        self.assertTrue(vieja["faena_cerrada"])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM facturas").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM facturas_abonos").fetchone()[0], 0)
        html = Path("demo_web/templates/modules/rrhh.html").read_text(encoding="utf-8")
        self.assertNotIn("Pasar a compras", html)
        self.assertNotIn("cosecha_migrar", html)
        self.assertNotIn("cosecha_precio", html)
        self.assertNotIn("cosecha_abono", html)
        self.assertIn("Registrar servicio", html)

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
        self.assertIn("not fila.asignado", html)
        self.assertIn("+ 1 tote", html)
        self.assertIn('name="nombre"', html)
        self.assertIn('name="rut"', html)
        self.assertIn("Deshacer el último", html)
        self.assertIn('type="date"', html)
        self.assertIn('name="fecha"', html)
        self.assertIn("fecha=fecha", html)
        self.assertIn("Este día no tiene ingresos.", html)
        self.assertIn("irConFecha", html)
        self.assertIn('id="cuartel"', html)
        self.assertIn("{% if todos %}", html)
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
        self.assertIn("Ingresos del enlace", html)
        self.assertIn('name="cosechero"', html)
        self.assertIn("not persona.asignado", html)
        self.assertIn("cosecha_persona", html)
        self.assertIn("Totes por cuartel", html)
        self.assertIn("Enlace de todos los cuarteles", html)
        self.assertIn("cosecha_enlace.url", html)
        self.assertIn("Enlace por cuartel", html)
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
        ok, msg = guardar_persona(conn, faena, 7, "Ana Soto", "12.345.678-9")
        self.assertFalse(ok)
        self.assertIn("RUT", msg)
        self.assertFalse(listar_fundas(conn, faena)[0]["asignado"])
        ok, msg = guardar_persona(conn, faena, 7, "Ana Soto", "12.345.678-5")
        self.assertTrue(ok, msg)
        self.assertTrue(listar_fundas(conn, faena)[0]["asignado"])
        ok, msg = guardar_persona(conn, faena, 7, "Otra persona", "12.345.678-5")
        self.assertFalse(ok)
        self.assertIn("ya está asignado", msg)
        self.assertEqual(listar_fundas(conn, faena)[0]["nombre"], "Ana Soto")
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
        sumar_tote(conn, links["CEREZOS CORTE 1"], 7, "2026-11-21 08:00:00", "2026-11-21")
        solo_dia = planilla_numeros(conn, faena, numero=7, desde="2026-11-21", hasta="2026-11-21")
        self.assertEqual(solo_dia[0]["totes"]["CEREZOS CORTE 1"], 1)
        self.assertEqual(solo_dia[0]["totes"]["CIRUELOS"], 0)
        self.assertEqual(solo_dia[0]["total"], 1)
        detalle = detalle_ingresos(conn, faena, numero=7)
        self.assertEqual(
            [(f["fecha"], f["cuartel"], f["totes"]) for f in detalle],
            [
                ("2026-11-21", "CEREZOS CORTE 1", 1),
                ("2026-11-20", "CEREZOS CORTE 1", 1),
                ("2026-11-20", "CIRUELOS", 2),
            ],
        )
        self.assertTrue(all(f["nombre"] == "Ana Soto" and f["rut"] == "12.345.678-5" for f in detalle))
        self.assertNotIn("SANTINA", {f["cuartel"] for f in detalle})
        ok, msg, _n = deshacer_ultimo(conn, links["CEREZOS CORTE 1"], "2026-11-21")
        self.assertTrue(ok, msg)
        self.assertEqual(
            contar_totes(conn, faena, "CEREZOS CORTE 1"),
            1,
        )
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
        conn.execute(
            """CREATE TABLE cosecha_tote (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                faena_id INTEGER NOT NULL,
                funda_id INTEGER NOT NULL,
                cuartel TEXT NOT NULL,
                anulado INTEGER NOT NULL DEFAULT 0,
                creado TEXT NOT NULL
            )"""
        )
        conn.execute(
            """INSERT INTO cosecha_tote (faena_id, funda_id, cuartel, anulado, creado)
               VALUES (1, 1, 'CIRUELOS', 0, '2026-10-27 10:51:08')"""
        )
        asegurar_tablas(conn)
        self.assertEqual(
            conn.execute("SELECT fecha FROM cosecha_tote").fetchone()[0],
            "2026-10-27",
        )
        fundas = listar_fundas(conn, 1)
        self.assertEqual([f["nombre"] for f in fundas], ["Ana", "Luis", "María"])
        self.assertEqual([f["numero"] for f in fundas], [1, 2, 3])
        self.assertEqual([f["rut"] for f in fundas], ["", "", ""])
        self.assertEqual([f["asignado"] for f in fundas], [False, False, False])
        conn.execute("UPDATE cosecha_funda SET rut='11.111.111-1' WHERE numero=1")
        asegurar_tablas(conn)
        fundas = listar_fundas(conn, 1)
        self.assertTrue(fundas[0]["asignado"])
        self.assertFalse(fundas[1]["asignado"])
        self.assertEqual(fundas[0]["nombre"], "Ana")


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

    def test_ingresado_de_otro_dia_queda_en_cero(self):
        conn = _conn()
        _ok, _msg, faena = abrir_faena(conn, 1, ["CEREZOS CORTE 1", "CIRUELOS"], "2026-11-20")
        links = {x["cuartel"]: x["token"] for x in listar_links(conn, faena)}
        ok, msg, n = sumar_tote(
            conn, links["CEREZOS CORTE 1"], 1, "2026-11-20 08:00:00", "2026-11-20"
        )
        self.assertTrue(ok, msg)
        sumar_tote(conn, links["CEREZOS CORTE 1"], 1, "2026-11-20 08:05:00", "2026-11-20")
        sumar_tote(conn, links["CIRUELOS"], 1, "2026-11-20 09:00:00", "2026-11-20")
        guardar_persona(conn, faena, 1, "Ana Soto", "12.345.678-5")
        mismo = vista_anotadora(conn, links["CEREZOS CORTE 1"], "ingresado", None, "2026-11-20")
        self.assertEqual(mismo["total_totes"], 2)
        self.assertEqual(mismo["fecha"], "2026-11-20")
        self.assertEqual(mismo["fecha_txt"], "20-11-2026")
        self.assertEqual([(f["numero"], f["totes"]) for f in mismo["filas"]], [(1, 2)])
        otro = vista_anotadora(conn, links["CEREZOS CORTE 1"], "ingresado", None, "2026-11-22")
        self.assertEqual(otro["total_totes"], 0)
        self.assertEqual(otro["filas"], [])
        self.assertEqual(otro["fecha"], "2026-11-22")
        self.assertEqual(otro["fecha_txt"], "22-11-2026")
        ciruelos = vista_anotadora(conn, links["CIRUELOS"], "ingresado", None, "2026-11-22")
        self.assertEqual(ciruelos["total_totes"], 0)
        self.assertEqual(ciruelos["filas"], [])
        ciruelos_dia = vista_anotadora(conn, links["CIRUELOS"], "ingresado", None, "2026-11-20")
        self.assertEqual(ciruelos_dia["total_totes"], 1)
        self.assertEqual(contar_totes(conn, faena, "CEREZOS CORTE 1"), 2)

    def test_el_enlace_de_todos_elige_el_cuartel(self):
        conn = _conn()
        ok, msg, faena = abrir_faena(conn, 1, ["CEREZOS CORTE 1", "CIRUELOS"], "2026-11-20")
        self.assertTrue(ok, msg)
        links = {x["cuartel"]: x["token"] for x in listar_links(conn, faena)}
        self.assertEqual(set(links), {"CEREZOS CORTE 1", "CIRUELOS"})
        token = enlace_todos(conn, faena)
        self.assertTrue(token)
        self.assertNotIn(token, set(links.values()))
        asegurar_tablas(conn)
        self.assertEqual(enlace_todos(conn, faena), token)
        ok, msg, _n = sumar_tote(
            conn, links["CEREZOS CORTE 1"], 1, "2026-11-20 08:00:00", "2026-11-20", "CIRUELOS"
        )
        self.assertTrue(ok, msg)
        self.assertEqual(contar_totes(conn, faena, "CEREZOS CORTE 1"), 1)
        self.assertEqual(contar_totes(conn, faena, "CIRUELOS"), 0)
        ok, msg, _n = sumar_tote(
            conn, token, 1, "2026-11-20 09:00:00", "2026-11-20", "CIRUELOS"
        )
        self.assertTrue(ok, msg)
        self.assertIn("CIRUELOS", msg)
        self.assertEqual(contar_totes(conn, faena, "CIRUELOS"), 1)
        self.assertEqual(contar_totes(conn, faena, "CEREZOS CORTE 1"), 1)
        ok, msg, _n = sumar_tote(conn, token, 2, "2026-11-20 09:05:00", "2026-11-20", "NOGALES")
        self.assertFalse(ok)
        self.assertIn("cuartel", msg.lower())
        self.assertEqual(contar_totes(conn, faena, "CEREZOS CORTE 1"), 1)
        cerezos = vista_anotadora(conn, token, "ingresado", None, "2026-11-20", "CEREZOS CORTE 1")
        self.assertTrue(cerezos["todos"])
        self.assertEqual(cerezos["cuarteles"], ["CEREZOS CORTE 1", "CIRUELOS"])
        self.assertEqual(cerezos["total_totes"], 1)
        vacio = vista_anotadora(conn, token, "ingresado", None, "2026-11-22", "CIRUELOS")
        self.assertEqual(vacio["total_totes"], 0)
        self.assertEqual(vacio["filas"], [])
        self.assertEqual(vacio["cuartel"], "CIRUELOS")
        self.assertEqual(
            vista_anotadora(conn, token, "ingreso", None, "2026-11-20")["cuartel"],
            "CEREZOS CORTE 1",
        )
        _ok, _msg, faena_e = abrir_faena(
            conn, 2, filtrar_cuarteles_cosecha(ESPINO, espino=True), "2026-11-20"
        )
        from demo_web.services.cosecha import resolver_enlace

        espino = resolver_enlace(conn, enlace_todos(conn, faena_e))
        self.assertEqual(espino["cuarteles"], ESPINO)
        self.assertNotIn("CEREZOS CORTE 1", espino["cuarteles"])


if __name__ == "__main__":
    unittest.main()
