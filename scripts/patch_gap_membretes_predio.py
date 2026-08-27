#!/usr/bin/env python3
"""Membretes GlobalGAP La Concepción — un predio por carpeta (cerezos/ciruelos/espino).

Parchea .doc / .docx / .xls / .xlsx solo si el membrete no coincide.
Omite PDF de política GlobalGAP internacional.
"""
from __future__ import annotations

import argparse
import io
import re
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DOCS_ROOT = Path("/root/demo-web/demo_web/static/globalgap/docs")
SKIP_PDF_SUBSTR = "241126_GG_IFA_Food_safety_policy_declaration"
OFFICE_EXTS = {".doc", ".docx", ".xls", ".xlsx"}


@dataclass(frozen=True)
class Membrete:
    slug: str
    razon: str
    rut: str
    direccion: str

    @property
    def lineas(self) -> list[str]:
        return [self.razon, f"RUT: {self.rut}", self.direccion]

    def markers_ok(self, text: str) -> bool:
        u = text.upper()
        return (
            self.razon.upper() in u
            and self.rut in text
            and self.direccion.upper() in u
        )

    def has_foreign(self, text: str) -> bool:
        u = text.upper()
        if self.markers_ok(text):
            # Membrete correcto: solo importa otra razón social explícita en encabezado.
            for m in MEMBRETES.values():
                if m.slug == self.slug:
                    continue
                if m.razon.upper() in u:
                    return True
            return False
        foreign = []
        for m in MEMBRETES.values():
            if m.slug == self.slug:
                continue
            if m.razon.upper() in u:
                foreign.append(m.razon)
            if self.slug == "espino" and "LA CONCEPCION" in u and "EL ESPINO" not in u:
                foreign.append("LA CONCEPCION")
            if self.slug == "ciruelos" and "LA CONCEPCION AGRICOLA" in u:
                foreign.append("LA CONCEPCION")
        return bool(foreign)


MEMBRETES = {
    "cerezos": Membrete(
        slug="cerezos",
        razon="SOCIEDAD AGRICOLA LA CONCEPCION LTDA.",
        rut="76.056.813-9",
        direccion="PARC. EL SAUCE LOTE 4 LA APARICION PAINE",
    ),
    "ciruelos": Membrete(
        slug="ciruelos",
        razon="CARLOS LIRA VALENCIA",
        rut="4.017.686-1",
        direccion="CAMINO LAS LILAS PARC. 44 CHADA PAINE",
    ),
    "espino": Membrete(
        slug="espino",
        razon="SOCIEDAD AGRICOLA EL ESPINO LTDA.",
        rut="77.352.447-5",
        direccion="CHADA PC 60 LT C PAINE",
    ),
}

# Variantes históricas → reemplazo (upper en lógica de match)
_LEGACY_RAZON = [
    ("LA CONCEPCION AGRICOLA LTDA.", "SOCIEDAD AGRICOLA LA CONCEPCION LTDA."),
    ("LA CONCEPCION SOCIEDAD AGRICOLA LTDA.", "SOCIEDAD AGRICOLA LA CONCEPCION LTDA."),
    ("La Concepción Sociedad Agrícola Ltda.", "SOCIEDAD AGRICOLA LA CONCEPCION LTDA."),
    ("La Concepcion Sociedad Agricola Ltda.", "SOCIEDAD AGRICOLA LA CONCEPCION LTDA."),
    ("SOCIEDAD AGRICOLA EL ESPINO LTDA", "SOCIEDAD AGRICOLA EL ESPINO LTDA."),
]

_LEGACY_DIR = [
    ("CAMINO LAS LILAS PARC.44", "CAMINO LAS LILAS PARC. 44 CHADA PAINE"),
    ("CAMINO LAS LILAS PARC. 44 PAINE", "CAMINO LAS LILAS PARC. 44 CHADA PAINE"),
    ("PARC. EL SAUCE LOTE 4 LA APARICION PAINE", "PARC. EL SAUCE LOTE 4 LA APARICION PAINE"),
]

# Instructivos .doc — bloque triple predio
_TRIPLE_DOC = re.compile(
    rb"LA CONCEPCION AGRICOLA LTDA\s*CARLOS LIRA VALENCIA\s*SOCIEDAD AGRICOLA EL ESPINO LTDA\.?",
    re.I,
)


def _is_ooxml_zip(path: Path) -> bool:
    """Solo .docx/.xlsx son ZIP OOXML; .doc/.xls OLE a veces dan falso positivo."""
    return path.suffix.lower() in {".docx", ".xlsx", ".xlsm"}


def _file_text(path: Path) -> str:
    if _is_ooxml_zip(path) and zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            parts = [
                z.read(n).decode("utf-8", errors="ignore")
                for n in z.namelist()
                if n.endswith(".xml") or n.endswith(".rels")
            ]
        raw = " ".join(parts)
        raw = re.sub(r"<[^>]+>", " ", raw)
    else:
        raw = path.read_bytes().decode("latin-1", errors="ignore")
    return " ".join(raw.split())


def needs_patch(path: Path, membrete: Membrete) -> tuple[bool, str]:
    if path.suffix.lower() == ".pdf" and SKIP_PDF_SUBSTR in path.name:
        return False, "pdf-politica-global-skip"
    if path.suffix.lower() not in OFFICE_EXTS:
        return False, "ext-skip"
    if path.name.endswith(".bak"):
        return False, "bak-skip"
    text = _file_text(path)
    if membrete.markers_ok(text) and not membrete.has_foreign(text):
        if (
            membrete.slug == "espino"
            and (
                "LA CONCEPCION SOCIEDAD AGRICOLA" in text.upper()
                or re.search(
                    r"LA CONCEPCION SOCIEDAD AGRICOLA\s*[\r\n]+CHADA PC",
                    text,
                    re.I,
                )
            )
        ):
            return True, "foreign-lc-variant"
        return False, "ok"
    if membrete.has_foreign(text):
        return True, "foreign-membrete"
    if not membrete.markers_ok(text):
        return True, "incomplete-membrete"
    return False, "ok"


def _pad_latin(value: str, size: int) -> str:
    if len(value) >= size:
        return value[:size]
    return value + " " * (size - len(value))


def _foreign_razones(membrete: Membrete) -> tuple[str, ...]:
    return tuple(m.razon for m in MEMBRETES.values() if m.slug != membrete.slug)


def _foreign_direcciones(membrete: Membrete) -> tuple[str, ...]:
    return tuple(m.direccion for m in MEMBRETES.values() if m.slug != membrete.slug)


def _apply_legacy_replacements(data: bytes | str, membrete: Membrete) -> bytes | str:
    is_bytes = isinstance(data, bytes)
    text = data.decode("latin-1", errors="ignore") if is_bytes else data
    for old, new in _LEGACY_RAZON:
        text = re.sub(re.escape(old), membrete.razon, text, flags=re.I)
    for foreign in _foreign_razones(membrete):
        text = re.sub(re.escape(foreign), membrete.razon, text, flags=re.I)
        text = re.sub(re.escape(foreign.rstrip(".")), membrete.razon, text, flags=re.I)
    for old, new in _LEGACY_DIR:
        if membrete.slug == "ciruelos":
            text = re.sub(re.escape(old), membrete.direccion, text, flags=re.I)
        elif membrete.slug == "cerezos" and "SAUCE" in old.upper():
            text = re.sub(re.escape(old), membrete.direccion, text, flags=re.I)
    for foreign in _foreign_direcciones(membrete):
        text = re.sub(re.escape(foreign), membrete.direccion, text, flags=re.I)
    text = re.sub(
        r"PARC\.\s*EL SAUCE LOTE 4\s*(?:\r|\n|<[^>]+>)?\s*LA APARICION\s*PAINE",
        membrete.direccion,
        text,
        flags=re.I,
    )
    text = re.sub(
        r"PARC\.\s*EL SAUCE LOTE 4\s*LA APARICION\s*PAINE",
        membrete.direccion,
        text,
        flags=re.I,
    )
    text = re.sub(
        rf"({re.escape(membrete.razon)}[^\r\n<]{{0,24}}(?:\r|\n|</w:t>).*?RUT:\s*{re.escape(membrete.rut)}\.?)\s*(?:\r|\n|</w:t>)?\s*PARC\.\s*EL SAUCE[^\r\n<]{{0,48}}",
        rf"\1\r{membrete.direccion}",
        text,
        count=1,
        flags=re.I | re.S,
    )
    if membrete.slug == "espino":
        text = re.sub(
            r"LA CONCEPCION SOCIEDAD AGRICOLA\s+LTDA\.?",
            membrete.razon,
            text,
            flags=re.I,
        )
        text = re.sub(
            r"ORGANIGRAMA INOCUIDAD\s+LA CONCEPCION SOCIEDAD AGRICOLA\s+LTDA\.?",
            f"ORGANIGRAMA INOCUIDAD {membrete.razon}",
            text,
            flags=re.I,
        )
    # Insertar RUT si falta cerca de razón social
    if membrete.rut not in text and membrete.razon.upper() in text.upper():
        text = re.sub(
            re.escape(membrete.razon),
            f"{membrete.razon}\rRUT: {membrete.rut}",
            text,
            count=1,
            flags=re.I,
        )
    if is_bytes:
        return text.encode("latin-1", errors="ignore")
    return text


def _patch_excel_header_content(content: str, membrete: Membrete) -> tuple[str, bool]:
    orig = content
    block = (
        f"{membrete.razon}\r"
        f"RUT: {membrete.rut}\r"
        f"{membrete.direccion} "
    )
    patterns = (
        r"LA CONCEPCION SOCIEDAD AGRICOLA\s+LTDA\.?\s*[\r\n]+PARC\.\s*EL SAUCE LOTE 4\s*[\r\n]+LA APARICION\s*PAINE\s*",
        r"LA CONCEPCION SOCIEDAD AGRICOLA\s*[\r\n]+CHADA PC 60 LT C PAINE\s*",
        r"SOCIEDAD AGRICOLA LA CONCEPCION LTDA\.?\s*(?:[\r\n]+RUT:[^\r\n]*)?[\r\n]+PARC\.\s*EL SAUCE[^\r\n]*[\r\n]+(?:LA APARICION\s*)?PAINE\s*",
        r"LA CONCEPCION SOCIEDAD AGRICOLA\s+LTDA\.?\s*PARC\.\s*EL SAUCE LOTE 4\s*LA APARICION\s*PAINE\s*",
        r"LA CONCEPCION SOCIEDAD AGRICOLA\s+LTDA\.?\s*",
        r"SOCIEDAD AGRICOLA LA CONCEPCION LTDA\.?\s*",
    )
    for pat in patterns:
        if membrete.slug != "cerezos":
            content = re.sub(pat, block, content, flags=re.I)
    if membrete.slug == "ciruelos":
        content = re.sub(
            r"CAMINO LAS LILAS PARC\.?\s*44\s*PAINE",
            membrete.direccion,
            content,
            flags=re.I,
        )
    for foreign in _foreign_razones(membrete):
        content = re.sub(re.escape(foreign), membrete.razon, content, flags=re.I)
    for foreign in _foreign_direcciones(membrete):
        content = re.sub(re.escape(foreign), membrete.direccion, content, flags=re.I)
    return content, content != orig


def _patch_binary_membrete(data: bytes, membrete: Membrete) -> tuple[bytes, list[str]]:
    notes: list[str] = []
    patched = data
    block = (
        f"{membrete.razon}\rRUT: {membrete.rut}\r{membrete.direccion}"
    ).encode("latin-1")
    replacements: list[tuple[bytes, bytes]] = []
    if membrete.slug != "cerezos":
        replacements.extend(
            [
                (
                    b"LA CONCEPCION SOCIEDAD AGRICOLA   LTDA.\rPARC. EL SAUCE LOTE 4\rLA APARICION PAINE",
                    block,
                ),
                (
                    b"LA CONCEPCION SOCIEDAD AGRICOLA LTDA.\rPARC. EL SAUCE LOTE 4\rLA APARICION PAINE",
                    block,
                ),
                (
                    b"LA CONCEPCION SOCIEDAD AGRICOLA LTDA. CHADA PC 60 LT C PAINE",
                    f"{membrete.razon} RUT: {membrete.rut} {membrete.direccion}".encode("latin-1"),
                ),
                (
                    b"LA CONCEPCION SOCIEDAD AGRICOLA LTDA.\rCHADA PC 60 LT C PAINE",
                    block,
                ),
                (
                    b"SOCIEDAD AGRICOLA LA CONCEPCION LTDA.",
                    membrete.razon.encode("latin-1"),
                ),
                (
                    b"LA CONCEPCION SOCIEDAD AGRICOLA \r\nCHADA PC 60 LT C PAINE",
                    block,
                ),
                (
                    b"LA CONCEPCION SOCIEDAD AGRICOLA \nCHADA PC 60 LT C PAINE",
                    block,
                ),
                (
                    b"LA CONCEPCION SOCIEDAD AGRICOLA \rCHADA PC 60 LT C PAINE",
                    block,
                ),
                (
                    b"LA CONCEPCION SOCIEDAD AGRICOLA  LTDA.\rCHADA PC 60 LT C PAINE",
                    block,
                ),
                (
                    b"LA CONCEPCION SOCIEDAD AGRICOLA  LTDA.",
                    membrete.razon.encode("latin-1"),
                ),
            ]
        )
    lc_addr = b"PARC. EL SAUCE LOTE 4\rLA APARICION PAINE"
    espino_addr = membrete.direccion.encode("latin-1")
    if membrete.slug == "espino" and lc_addr in patched:
        patched = patched.replace(lc_addr, _pad_latin(membrete.direccion, len(lc_addr)).encode("latin-1"))
        notes.append("addr-lc")
    for old, new in replacements:
        if old in patched and patched != patched.replace(old, new):
            patched = patched.replace(old, new)
            notes.append("binary")
    new = _apply_legacy_replacements(patched, membrete)
    if isinstance(new, bytes) and new != patched:
        patched = new
        notes.append("legacy")
    return patched, notes


def patch_doc(path: Path, membrete: Membrete) -> tuple[bool, str]:
    raw = path.read_bytes()
    patched = raw
    notes: list[str] = []

    m = _TRIPLE_DOC.search(patched)
    if m:
        repl = f"{membrete.razon}\rRUT: {membrete.rut}\r{membrete.direccion}".encode("latin-1")
        old = m.group(0)
        if len(repl) <= len(old):
            repl = repl + b" " * (len(old) - len(repl))
            patched = patched[: m.start()] + repl + patched[m.end() :]
            notes.append("triple-block")
        else:
            notes.append("triple-block-skip-len")

    bin_patched, bin_notes = _patch_binary_membrete(patched, membrete)
    if bin_patched != patched:
        patched = bin_patched
        notes.extend(bin_notes)

    # Quitar otras razones sociales en regiones de membrete (.doc)
    for other in MEMBRETES.values():
        if other.slug == membrete.slug:
            continue
        for label in (other.razon, other.razon.rstrip(".")):
            b = label.encode("latin-1", errors="ignore")
            if b in patched:
                patched = patched.replace(b, b" " * len(b))
                notes.append(f"strip-{other.slug}")

    if patched == raw:
        return False, "sin-cambios-doc"
    path.write_bytes(patched)
    return True, ";".join(dict.fromkeys(notes)) or "doc"


def _strip_lc_header_fragments(xml: str, membrete: Membrete) -> tuple[str, bool]:
    """Vacía w:t sueltos de membrete LC cuando ya está el predio Espino."""
    if membrete.slug != "espino":
        return xml, False
    if membrete.razon.upper() not in xml.upper():
        return xml, False
    orig = xml
    for frag in (
        "SOCIEDAD AGRICOLA LTDA.",
        "SOCIEDAD AGRICOLA LTDA",
        "AGRICOLA LTDA",
        "PARC. EL SAUCE LOTE 4 ",
        "PARC. ",
        "EL SAUCE LOTE 4",
        "LA APARICION ",
    ):
        xml = re.sub(rf">{re.escape(frag)}</w:t>", "></w:t>", xml, flags=re.I)
    xml = re.sub(r">PAINE\s*</w:t>", "></w:t>", xml, flags=re.I)
    if membrete.rut not in xml and f">{membrete.razon}</w:t>" in xml:
        xml = xml.replace(
            f">{membrete.razon}</w:t>",
            f">{membrete.razon}</w:t></w:r><w:r><w:rPr/><w:t xml:space=\"preserve\">RUT: {membrete.rut}\r{membrete.direccion}</w:t>",
            1,
        )
    return xml, xml != orig


def _inject_espino_header_if_lc_only(xml: str, membrete: Membrete) -> tuple[str, bool]:
    """Encabezado solo con restos LC (sin EL ESPINO): inserta membrete Espino."""
    if membrete.slug != "espino" or "EL ESPINO" in xml.upper():
        return xml, False
    if "SAUCE" not in xml.upper() and "AGRICOLA LTDA" not in xml.upper():
        return xml, False
    orig = xml
    block = f"{membrete.razon}\rRUT: {membrete.rut}\r{membrete.direccion}"
    for pat in (
        r"(<w:t[^>]*>)\s*AGRICOLA LTDA\s*(</w:t>)",
        r"(<w:t[^>]*>)\s*SOCIEDAD AGRICOLA LTDA\.?\s*(</w:t>)",
        r"(<w:t[^>]*>)\s*LA CONCEPCION\s*(</w:t>)",
    ):
        xml2 = re.sub(pat, rf"\1{block}\2", xml, count=1, flags=re.I)
        if xml2 != xml:
            return xml2, True
    return xml, xml != orig


def _collapse_split_lc_header(xml: str, membrete: Membrete) -> tuple[str, bool]:
    """Docx clonados LC: 'La Concepcion' + 'Sociedad' + 'Agricola' + 'Ltda.' en varios w:r."""
    if membrete.slug != "espino":
        return xml, False
    if not re.search(r">La Concepcion\s*</w:t>", xml, re.I):
        return xml, False
    orig = xml
    xml = re.sub(
        r">La Concepcion\s*</w:t>",
        f">{membrete.razon}</w:t>",
        xml,
        count=1,
        flags=re.I,
    )
    run_pat = (
        r"<w:r\b[^>]*>\s*(?:<w:rPr\b.*?</w:rPr>\s*)?"
        r"<w:t\b[^>]*>\s*{frag}\s*</w:t>\s*</w:r>"
    )
    for frag in ("Sociedad", "Agricola", "Ltda\\.?"):
        xml = re.sub(run_pat.format(frag=frag), "", xml, count=1, flags=re.I | re.S)
    return xml, xml != orig


def _ooxml_bytes_valid(data: bytes) -> bool:
    """Verifica ZIP OOXML y XML bien formado en partes críticas."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if z.testzip() is not None:
                return False
            for name in z.namelist():
                if not name.endswith(".xml"):
                    continue
                if not (
                    name.startswith("word/")
                    or name.startswith("xl/")
                    or name == "[Content_Types].xml"
                ):
                    continue
                ET.fromstring(z.read(name))
        return True
    except Exception:
        return False


def _patch_header_footer_xml(xml: str, membrete: Membrete) -> tuple[str, bool]:
    orig = xml
    changed = False
    for tag in (
        "oddHeader",
        "evenHeader",
        "firstHeader",
        "oddFooter",
        "evenFooter",
        "firstFooter",
    ):
        pat = rf"(<{tag}[^>]*>)(.*?)(</{tag}>)"

        def _sub(m: re.Match, _tag=tag) -> str:
            nonlocal changed
            new_body, ch = _patch_excel_header_content(m.group(2), membrete)
            if ch:
                changed = True
            return m.group(1) + new_body + m.group(3)

        xml = re.sub(pat, _sub, xml, flags=re.S)

    # Unificar razón social (mayúsculas)
    for old, new in _LEGACY_RAZON:
        xml = re.sub(re.escape(old), membrete.razon, xml, flags=re.I)
    xml = re.sub(re.escape(membrete.razon.rstrip(".")), membrete.razon, xml, flags=re.I)

    # docx LC: fusionar "LA CONCEPCION" + "SOCIEDAD AGRICOLA LTDA."
    if membrete.slug == "cerezos":
        xml = re.sub(
            r">LA CONCEPCION\s*</w:t>",
            f">{membrete.razon}</w:t>",
            xml,
            flags=re.I,
        )
        xml = re.sub(r">SOCIEDAD AGRICOLA LTDA\.?\s*</w:t>", "></w:t>", xml, flags=re.I)

    # Dirección por predio
    if membrete.slug == "ciruelos":
        xml = re.sub(
            r">CAMINO LAS LILAS PARC\.?\s*44\s*</w:t>\s*<w:.*?>\s*<w:t[^>]*>\s*PAINE\s*</w:t>",
            f">{membrete.direccion}</w:t>",
            xml,
            count=1,
            flags=re.I | re.S,
        )
        xml = re.sub(
            r"CAMINO LAS LILAS PARC\.?\s*44\s*PAINE",
            membrete.direccion,
            xml,
            flags=re.I,
        )
    elif membrete.slug == "cerezos":
        xml = re.sub(
            r">PARC\.\s*</w:t>.*?<w:t[^>]*>\s*PAINE\s*</w:t>",
            f">{membrete.direccion}</w:t>",
            xml,
            count=1,
            flags=re.I | re.S,
        )
    elif membrete.slug == "espino":
        for old in (
            "PARC. EL SAUCE LOTE 4 LA APARICION PAINE",
            "CAMINO LAS LILAS PARC. 44 CHADA PAINE",
            "CAMINO LAS LILAS PARC.44",
        ):
            xml = re.sub(re.escape(old), membrete.direccion, xml, flags=re.I)
        xml = re.sub(
            r">LA CONCEPCION\s*</w:t>\s*<w:.*?>\s*<w:t[^>]*>\s*SOCIEDAD AGRICOLA LTDA\.?\s*</w:t>",
            f">{membrete.razon}</w:t>",
            xml,
            count=1,
            flags=re.I | re.S,
        )
        xml = re.sub(
            r">La Concepcion\s*</w:t>\s*<w:.*?>\s*<w:t[^>]*>\s*Sociedad Agricola Ltda\.?\s*</w:t>",
            f">{membrete.razon}</w:t>",
            xml,
            count=1,
            flags=re.I | re.S,
        )

    # Quitar otras razones sociales del encabezado
    for other in MEMBRETES.values():
        if other.slug == membrete.slug:
            continue
        xml = re.sub(re.escape(other.razon), "", xml, flags=re.I)
        xml = re.sub(re.escape(other.razon.rstrip(".")), "", xml, flags=re.I)

    xml, split_ch = _collapse_split_lc_header(xml, membrete)
    if split_ch:
        changed = True

    xml, inject_ch = _inject_espino_header_if_lc_only(xml, membrete)
    if inject_ch:
        changed = True

    xml, strip_ch = _strip_lc_header_fragments(xml, membrete)
    if strip_ch:
        changed = True

    legacy_xml = _apply_legacy_replacements(xml, membrete)
    if isinstance(legacy_xml, str) and legacy_xml != xml:
        xml = legacy_xml
        changed = True

    if xml != orig:
        changed = True
    return xml, changed


def patch_xls(path: Path, membrete: Membrete) -> tuple[bool, str]:
    raw = path.read_bytes()
    patched, notes = _patch_binary_membrete(raw, membrete)
    if patched == raw:
        return False, "sin-cambios-xls"
    path.write_bytes(patched)
    return True, ";".join(dict.fromkeys(notes)) or "xls"


def patch_zip_office(path: Path, membrete: Membrete) -> tuple[bool, str]:
    if not zipfile.is_zipfile(path):
        return False, "no-zip"
    notes: list[str] = []
    in_buf = path.read_bytes()
    out_buf = io.BytesIO()
    changed = False
    with zipfile.ZipFile(io.BytesIO(in_buf)) as zin:
        with zipfile.ZipFile(out_buf, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                fn = item.filename.lower()
                patchable = (
                    "header" in fn
                    or "footer" in fn
                    or fn.endswith("document.xml")
                    or fn.endswith("sharedstrings.xml")
                    or (fn.startswith("xl/worksheets/") and fn.endswith(".xml"))
                )
                if patchable:
                    try:
                        text = data.decode("utf-8")
                    except UnicodeDecodeError:
                        zout.writestr(item, data)
                        continue
                    new_text, ch = _patch_header_footer_xml(text, membrete)
                    if ch:
                        changed = True
                        notes.append(Path(item.filename).name)
                    zout.writestr(item, new_text.encode("utf-8"))
                else:
                    zout.writestr(item, data)
    if not changed:
        return False, "sin-cambios-zip"
    out_data = out_buf.getvalue()
    if not _ooxml_bytes_valid(out_data):
        return False, "xml-invalido-revertido"
    path.write_bytes(out_data)
    return True, ";".join(notes[:5])


def patch_file(path: Path, membrete: Membrete) -> tuple[bool, str]:
    ext = path.suffix.lower()
    if ext == ".doc":
        return patch_doc(path, membrete)
    if ext == ".xls":
        return patch_xls(path, membrete)
    if ext in {".docx", ".xlsx"}:
        return patch_zip_office(path, membrete)
    return False, "ext-skip"


def bootstrap_espino(dry_run: bool = False) -> list[str]:
    src = DOCS_ROOT / "cerezos"
    dest = DOCS_ROOT / "espino"
    notes: list[str] = []
    if dest.exists():
        notes.append("espino-ya-existe")
        return notes
    if not src.is_dir():
        raise SystemExit(f"No existe plantilla {src}")
    if dry_run:
        notes.append(f"clonar {src} -> {dest}")
        return notes
    shutil.copytree(src, dest)
    # Renombrar carpeta registros
    old_reg = dest / "Registros La Concepcion"
    new_reg = dest / "Registros El Espino"
    if old_reg.is_dir():
        old_reg.rename(new_reg)
    for name in ("catalogo_cerezos.json", "doc_checklist_map_cerezos.json"):
        s = DOCS_ROOT / name
        if s.is_file():
            slug_name = name.replace("cerezos", "espino")
            shutil.copy2(s, DOCS_ROOT / slug_name)
    notes.append("espino-clonado-desde-cerezos")
    return notes


def collect_files(slug: str) -> list[Path]:
    root = DOCS_ROOT / slug
    if not root.is_dir():
        return []
    out: list[Path] = []
    for f in root.rglob("*"):
        if not f.is_file():
            continue
        if f.suffix.lower() not in OFFICE_EXTS:
            continue
        if f.name.endswith(".bak"):
            continue
        out.append(f)
    return sorted(out)


def backup_tree(slugs: list[str]) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = DOCS_ROOT.parent / f"docs_backup_membrete_{ts}.tar.gz"
    import tarfile

    with tarfile.open(bak, "w:gz") as tar:
        for slug in slugs:
            p = DOCS_ROOT / slug
            if p.is_dir():
                tar.add(p, arcname=f"globalgap/docs/{slug}")
        for name in ("catalogo_espino.json", "doc_checklist_map_espino.json"):
            p = DOCS_ROOT / name
            if p.is_file():
                tar.add(p, arcname=f"globalgap/docs/{name}")
    return bak


def restore_slug_from_backup(slug: str, backup: Path) -> None:
    import tarfile

    if not backup.is_file():
        raise SystemExit(f"No existe backup {backup}")
    prefix = f"globalgap/docs/{slug}/"
    dest = DOCS_ROOT / slug
    if dest.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.move(str(dest), str(dest.with_name(f"{slug}_pre_restore_{ts}")))
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(backup) as tar:
        for member in tar.getmembers():
            if not member.name.startswith(prefix) or member.isdir():
                continue
            rel = member.name[len(prefix) :]
            if not rel or rel.endswith(".bak"):
                continue
            out = dest / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as src:
                out.write_bytes(src.read())
    print(f"RESTORE\t{slug}\tfrom {backup.name}\t-> {dest}")


def validate_slug(slug: str) -> int:
    root = DOCS_ROOT / slug
    bad: list[tuple[str, str]] = []
    ok = 0
    for path in collect_files(slug):
        rel = str(path.relative_to(DOCS_ROOT))
        ext = path.suffix.lower()
        if ext in {".docx", ".xlsx", ".xlsm"}:
            data = path.read_bytes()
            if not _ooxml_bytes_valid(data):
                bad.append((rel, "ooxml-invalid"))
            else:
                ok += 1
        elif ext == ".doc":
            try:
                import olefile

                if not olefile.isOleFile(str(path)):
                    bad.append((rel, "not-ole"))
                else:
                    ok += 1
            except Exception as exc:
                bad.append((rel, str(exc)))
        elif ext == ".xls":
            ok += 1
    print(f"VALIDATE\t{slug}\tok={ok}\tbad={len(bad)}")
    for rel, reason in bad:
        print(f"BAD\t{rel}\t{reason}")
    return len(bad)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--bootstrap-espino", action="store_true")
    parser.add_argument("--slug", action="append", default=[], help="cerezos|ciruelos|espino")
    parser.add_argument("--no-backup", action="store_true")
    parser.add_argument(
        "--restore-from-backup",
        type=Path,
        help="Restaura carpeta slug desde tar.gz (globalgap/docs/{slug}/...)",
    )
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    slugs = args.slug or ["cerezos", "ciruelos", "espino"]

    if args.restore_from_backup:
        for slug in slugs:
            restore_slug_from_backup(slug, args.restore_from_backup)
        return 0

    if args.validate_only:
        err = 0
        for slug in slugs:
            err += validate_slug(slug)
        return 1 if err else 0

    if args.bootstrap_espino:
        for line in bootstrap_espino(dry_run=args.dry_run):
            print(f"BOOT\t{line}")

    if args.dry_run:
        total_patch = 0
        for slug in slugs:
            m = MEMBRETES.get(slug)
            if not m:
                continue
            for path in collect_files(slug):
                do, reason = needs_patch(path, m)
                rel = path.relative_to(DOCS_ROOT)
                print(f"{'PATCH' if do else 'OK'}\t{rel}\t{reason}")
                if do:
                    total_patch += 1
        print(f"Total a parchear: {total_patch}")
        return 0

    if not args.no_backup:
        bak = backup_tree(slugs)
        print(f"BACKUP\t{bak}")

    ok_n = 0
    skip_n = 0
    for slug in slugs:
        m = MEMBRETES[slug]
        for path in collect_files(slug):
            do, reason = needs_patch(path, m)
            if not do:
                skip_n += 1
                continue
            try:
                ok, msg = patch_file(path, m)
                rel = path.relative_to(DOCS_ROOT)
                print(f"{'OK' if ok else 'SKIP'}\t{rel}\t{msg}")
                if ok:
                    ok_n += 1
            except Exception as exc:
                print(f"ERR\t{path.name}\t{exc}", file=sys.stderr)
    print(f"Actualizados: {ok_n} | Sin cambio necesario: {skip_n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
