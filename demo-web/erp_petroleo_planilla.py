"""Planilla maestra imprimible para control físico del estanque de petróleo."""
from __future__ import annotations

from fpdf import FPDF

from erp_respaldo import hora_chile


def _pdf_txt(texto):
    return str(texto or "").encode("latin-1", "replace").decode("latin-1")


def _fpdf_to_bytes(pdf):
    """Compatible fpdf 1.x (dest=S str) y fpdf 2.x (bytearray)."""
    raw = None
    for call in (
        lambda: pdf.output(dest="S"),
        lambda: pdf.output(name="S"),
        lambda: pdf.output("S"),
    ):
        try:
            raw = call()
            break
        except TypeError:
            continue
        except Exception:
            continue
    if raw is None:
        raw = pdf.output()
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw.encode("latin-1")
    return bytes(raw)


def _encabezado_planilla(pdf, titulo, logo_path=None, empresa="ERP AGRICOLA"):
    """Membrete planilla: logo tenant o nombre de empresa (sin LC por defecto)."""
    ancho_util = pdf.w - 20
    logo = logo_path
    if logo:
        try:
            pdf.image(logo, x=10, y=8, w=40)
        except Exception:
            logo = None
    if not logo:
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_xy(10, 10)
        pdf.cell(80, 6, _pdf_txt(empresa))

    fh = hora_chile().strftime("%d/%m/%Y %H:%M")
    pdf.set_font("Helvetica", "", 8)
    pdf.set_xy(10, 10)
    pdf.cell(ancho_util, 5, f"Generado: {fh}", align="R")

    pdf.set_font("Helvetica", "B", 13)
    pdf.set_xy(10, 30)
    pdf.cell(ancho_util, 9, _pdf_txt(str(titulo)), align="C", ln=1)
    pdf.ln(6)


def generar_pdf_planilla_maestra_petroleo(
    fecha_carga,
    litros_carga,
    n_filas=26,
    empresa=None,
    logo_path=None,
):
    """
    PDF carta vertical: encabezado con fecha/carga y grilla vacía para anotar salidas.
    logo_path: ruta_logo_pdf() desde la app (respeta tenant).
    """
    try:
        pdf = FPDF(orientation="P", unit="mm", format="Letter")
        pdf.set_margins(12, 12, 12)
        pdf.set_auto_page_break(auto=False)
        pdf.add_page()

        ancho = pdf.w - pdf.l_margin - pdf.r_margin
        x0 = pdf.l_margin

        kwargs_hdr = {"logo_path": logo_path}
        if empresa:
            kwargs_hdr["empresa"] = str(empresa).upper()
        _encabezado_planilla(pdf, "PLANILLA MAESTRA - ESTANQUE PETROLEO", **kwargs_hdr)

        y_hdr = pdf.get_y() + 2
        lbl_w = 28
        val_w = 52
        gap = 8

        pdf.set_xy(x0, y_hdr)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(lbl_w, 7, _pdf_txt("Fecha:"), border=0)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(val_w, 7, _pdf_txt(str(fecha_carga)), border="B")

        pdf.set_xy(x0 + lbl_w + val_w + gap, y_hdr)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(32, 7, _pdf_txt("Carga (Lts):"), border=0)
        pdf.set_font("Helvetica", "", 10)
        try:
            lts_txt = f"{float(litros_carga):,.0f}".replace(",", ".")
        except (TypeError, ValueError):
            lts_txt = str(litros_carga or "")
        pdf.cell(val_w, 7, _pdf_txt(lts_txt), border="B")

        pdf.set_y(y_hdr + 12)

        cols = ("FECHA", "LITROS", "HUERTO", "MAQUINARIA", "QUIEN RETIRA")
        anchos = (28, 22, 42, 48, ancho - 28 - 22 - 42 - 48)
        h_hdr = 7
        h_row = 8.2

        pdf.set_font("Helvetica", "B", 8)
        y_tab = pdf.get_y()
        x = x0
        for col, w in zip(cols, anchos):
            pdf.set_xy(x, y_tab)
            pdf.cell(w, h_hdr, _pdf_txt(col), border=1, align="C")
            x += w

        y_row = y_tab + h_hdr
        y_max = pdf.h - pdf.b_margin - 8
        filas = min(n_filas, max(1, int((y_max - y_row) / h_row)))

        pdf.set_font("Helvetica", "", 8)
        for _ in range(filas):
            if y_row + h_row > y_max - h_row:
                break
            x = x0
            for w in anchos:
                pdf.set_xy(x, y_row)
                pdf.cell(w, h_row, "", border=1)
                x += w
            y_row += h_row

        if y_row + h_row <= y_max:
            pdf.set_font("Helvetica", "B", 8)
            x = x0
            for i, w in enumerate(anchos):
                pdf.set_xy(x, y_row)
                txt = "TOTAL" if i == 0 else ""
                pdf.cell(w, h_row, _pdf_txt(txt), border=1, align="C" if i == 0 else "R")
                x += w

        pdf.set_font("Helvetica", "", 7)
        pdf.set_xy(x0, pdf.h - pdf.b_margin - 5)
        pdf.cell(
            ancho,
            4,
            _pdf_txt("Anote cada salida en el estanque y luego registre en Petroleo - Salida."),
            align="C",
        )

        return _fpdf_to_bytes(pdf)
    except Exception:
        return None


def defaults_planilla_petroleo(conn, hoy):
    """Fecha del día al imprimir y 1000 L como carga sugerida."""
    return hoy, 1000.0
