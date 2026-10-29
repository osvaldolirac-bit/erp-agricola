"""Compras abre el historial sin armar el PDF. El PDF se genera al descargarlo."""
from __future__ import annotations

import inspect
import os
import tempfile
import time
import unittest
from pathlib import Path

from demo_web.services import pdf_cache
from demo_web.services.native import compras


class ComprasPdfAlPedirTests(unittest.TestCase):
    def test_abrir_historial_no_arma_el_pdf(self):
        src = inspect.getsource(compras._historial)
        self.assertNotIn("generar_pdf_blob", src)
        self.assertIn('"pdf": "1"', src)

    def test_el_pdf_se_arma_al_pedirlo(self):
        src = inspect.getsource(compras._blob_historial)
        self.assertIn("generar_pdf_blob", src)
        view = inspect.getsource(compras.view)
        self.assertIn('request.args.get("pdf") == "1"', view)

    def test_la_cache_borra_pdf_vencidos(self):
        previo = os.environ.get("ERP_PDF_CACHE")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.environ["ERP_PDF_CACHE"] = tmp
                viejo = Path(tmp) / "viejo"
                meta = Path(tmp) / "viejo.meta"
                viejo.write_bytes(b"x")
                meta.write_text("a.pdf", encoding="utf-8")
                antiguo = time.time() - pdf_cache._TTL_SEC - 30
                os.utime(viejo, (antiguo, antiguo))
                os.utime(meta, (antiguo, antiguo))
                nuevo = Path(tmp) / "nuevo"
                nuevo.write_bytes(b"y")
                borrados = pdf_cache.purge_expired()
                self.assertFalse(viejo.exists())
                self.assertFalse(meta.exists())
                self.assertTrue(nuevo.exists())
                self.assertGreaterEqual(borrados, 2)
        finally:
            if previo is None:
                os.environ.pop("ERP_PDF_CACHE", None)
            else:
                os.environ["ERP_PDF_CACHE"] = previo


if __name__ == "__main__":
    unittest.main()
