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


def _xlsx_headers_text(path: Path) -> str:
    if path.suffix.lower() != ".xlsx" or not zipfile.is_zipfile(path):
        return ""
    parts: list[str] = []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not (name.startswith("xl/worksheets/") and name.endswith(".xml")):
                continue
            xml = z.read(name).decode("utf-8", errors="ignore")
            for m in re.finditer(
                r"<(?:odd|even|first)(?:Header|Footer)[^>]*>(.*?)</(?:odd|even|first)(?:Header|Footer)>",
                xml,
                re.S | re.I,
            ):
                parts.append(m.group(1))
    return "\n".join(parts)


def _excel_header_has_lc(text: str) -> bool:
    u = text.upper()
    if not u.strip():
        return False
    left = u.split("&C")[0]
    if "EL ESPINO" in left and "LA CONCEPCION" not in left and "EL SAUCE" not in left:
        return False
    return any(
        k in left
        for k in (
            "LA CONCEPCION",
            "SOCIEDAD AGRICOLA LA CONCEPCION",
            "PARC. EL SAUCE",
            " EL SAUCE LOTE",
        )
    )


def needs_patch(path: Path, membrete: Membrete) -> tuple[bool, str]:
    if path.suffix.lower() == ".pdf" and SKIP_PDF_SUBSTR in path.name:
        return False, "pdf-politica-global-skip"
    if path.suffix.lower() not in OFFICE_EXTS:
        return False, "ext-skip"
    if path.name.endswith(".bak"):
        return False, "bak-skip"
    if path.suffix.lower() == ".xlsx":
        hx = _xlsx_headers_text(path)
        if hx and _excel_header_has_lc(hx):
            return True, "excel-header-lc"
        if membrete.slug == "espino" and hx and membrete.markers_ok(hx):
            return False, "ok"
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


def _excel_header_block(membrete: Membrete, sep: str) -> str:
    return f"{membrete.razon}{sep}RUT: {membrete.rut}{sep}{membrete.direccion} "


def _patch_excel_header_content(content: str, membrete: Membrete) -> tuple[str, bool]:
    orig = content
    sep = "\n" if "\n" in content else "\r"
    block = _excel_header_block(membrete, sep)

    # Espino: encabezado Excel ya tiene razón social pero arrastra dirección LC → reconstruir &L.
    if (
        membrete.slug == "espino"
        and "&amp;C" in content
        and _excel_header_has_lc(content)
    ):
        left, _, right = content.partition("&amp;C")
        if "EL ESPINO" in left.upper():
            razon_idx = left.upper().find(membrete.razon.upper())
            if razon_idx < 0:
                razon_idx = left.upper().find("EL ESPINO")
            prefix = left[:razon_idx] if razon_idx > 0 else '&amp;L&amp;"-,Negrita"'
            sep_left = "\n" if "\n" in left else "\r"
            rebuilt = prefix + _excel_header_block(membrete, sep_left) + "&amp;C" + right
            if rebuilt != orig:
                return rebuilt, True

    patterns = (
        r"LA CONCEPCION SOCIEDAD AGRICOLA\s+LTD\s*[\r\n]+PARC\.\s*EL SAUCE LOTE 4\s*[\r\n]+LA APARICION\s*PAINE\s*",
        r"LA CONCEPCION SOC\.\s*AGRICOLA\s+LTDA\.?\s*[\r\n]+\s*EL SAUCE LOTE 4\s*[\r\n]+\s*LA APARICION\s*",
        r"LA CONCEPCION SOCIEDAD AGRICOLA\s+LTDA\.?\s*[\r\n]+PARC\.\s*EL SAUCE LOTE 4\s*[\r\n]+LA APARICION\s*PAINE\s*",
        r"LA CONCEPCION SOCIEDAD AGRICOLA\s*[\r\n]+\s*CHADA PC 60 LT C PAINE\s*",
        r"LA CONCEPCION SOCIEDAD AGRICOLA\s*[\r\n]+CHADA PC 60 LT C PAINE\s*",
        r"SOCIEDAD AGRICOLA LA CONCEPCION LTDA\.?\s*(?:[\r\n]+RUT:[^\r\n]*)?[\r\n]+PARC\.\s*EL SAUCE[^\r\n]*[\r\n]+(?:LA APARICION\s*)?PAINE\s*",
        r"LA CONCEPCION SOCIEDAD AGRICOLA\s+LTDA\.?\s*PARC\.\s*EL SAUCE LOTE 4\s*LA APARICION\s*PAINE\s*",
        r"LA CONCEPCION SOCIEDAD AGRICOLA\s*[\r\n]+",
        r"LA CONCEPCION SOCIEDAD AGRICOLA\s+LTDA\.?\s*",
        r"LA CONCEPCION SOC\.\s*AGRICOLA\s+LTDA\.?\s*",
        r"SOCIEDAD AGRICOLA LA CONCEPCION LTDA\.?\s*",
    )
    for pat in patterns:
        if membrete.slug != "cerezos":
            content = re.sub(pat, block, content, flags=re.I)
    if membrete.slug == "espino" and _excel_header_has_lc(content):
        m = re.match(r"((?:&amp;L.*?))(\s*&amp;C)", content, re.S | re.I)
        if m and "EL ESPINO" not in m.group(1).upper():
            content = block + m.group(2) + content[m.end() :]
        elif "&amp;C" not in content:
            content = re.sub(
                r"PARC\.\s*EL SAUCE LOTE 4\s*(?:\r\n|\n|\\r\\n)\s*LA APARICION\s*PAINE\s*",
                "",
                content,
                flags=re.I,
            )
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
    sep = b"\n" if b"\n" in data else b"\r"
    block = (
        membrete.razon.encode("latin-1")
        + sep
        + f"RUT: {membrete.rut}".encode("latin-1")
        + sep
        + membrete.direccion.encode("latin-1")
    )
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


_HEADER_TITLE_KWS = (
    "PROCEDIMIENTO",
    "PLAN",
    "INSTRUCTIVO",
    "REGISTRO",
    "CHECKLIST",
    "GGPR",
    "GGPL",
    "GGRG",
    "GGIN",
    "CÓD.",
    "COD.",
)


def _xml_plain_text(xml: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", xml).split())


def _xml_well_formed(xml: str) -> bool:
    try:
        ET.fromstring(xml.encode("utf-8"))
        return True
    except ET.ParseError:
        return False


def _header_titles_preserved(before: str, after: str) -> bool:
    bu, au = before.upper(), after.upper()
    for kw in _HEADER_TITLE_KWS:
        if kw in bu and kw not in au:
            return False
    return True


def _replace_wt_content(xml: str, old: str, new: str) -> tuple[str, bool]:
    if not old.strip():
        return xml, False
    changed = False

    def repl(m: re.Match) -> str:
        nonlocal changed
        body = m.group(2)
        if old.upper() not in body.upper():
            return m.group(0)
        nb = re.sub(re.escape(old), new, body, count=1, flags=re.I)
        if nb == body:
            return m.group(0)
        changed = True
        return m.group(1) + nb + m.group(3)

    out = re.sub(r"(<w:t(?:\s[^>]*)?>)(.*?)(</w:t>)", repl, xml, flags=re.S)
    return out, changed


def _remove_wr_runs_only_text(xml: str, text: str) -> tuple[str, bool]:
    if not text.strip():
        return xml, False
    pat = (
        r"<w:r\b[^>]*>\s*(?:<w:rPr\b.*?</w:rPr>\s*)?"
        rf"<w:t\b[^>]*>\s*{re.escape(text)}\s*</w:t>\s*</w:r>"
    )
    out, n = re.subn(pat, "", xml, flags=re.I | re.S)
    return out, n > 0


def _append_rut_to_razon_wt(xml: str, membrete: Membrete) -> tuple[str, bool]:
    if membrete.rut in xml:
        return xml, False
    changed = False

    def repl(m: re.Match) -> str:
        nonlocal changed
        body = m.group(2)
        if membrete.razon.upper() not in body.upper() or membrete.rut in body:
            return m.group(0)
        changed = True
        suffix = f"\rRUT: {membrete.rut}\r{membrete.direccion}"
        return m.group(1) + body.rstrip() + suffix + m.group(3)

    out = re.sub(r"(<w:t(?:\s[^>]*)?>)(.*?)(</w:t>)", repl, xml, count=1, flags=re.S)
    return out, changed


def _patch_docx_header_xml_safe(xml: str, membrete: Membrete) -> tuple[str, bool]:
    """Parche membrete solo en w:t de encabezados/pies Word — sin tocar document.xml."""
    orig = xml
    plain_before = _xml_plain_text(xml)
    out = xml
    changed = False

    for other in MEMBRETES.values():
        if other.slug == membrete.slug:
            continue
        for label in (other.razon, other.razon.rstrip(".")):
            out, ch = _replace_wt_content(out, label, membrete.razon)
            changed = changed or ch

    for old, new in _LEGACY_RAZON:
        if new.upper() == membrete.razon.upper() or membrete.razon.upper() in old.upper():
            out, ch = _replace_wt_content(out, old, membrete.razon)
            changed = changed or ch

    if membrete.slug == "espino":
        if re.search(r">La Concepcion\s*</w:t>", out, re.I):
            out, ch = _replace_wt_content(out, "La Concepcion", membrete.razon)
            changed = changed or ch
            for frag in ("Sociedad", "Agricola", "Ltda.", "Ltda"):
                out, ch = _remove_wr_runs_only_text(out, frag)
                changed = changed or ch
        for old in (
            "LA CONCEPCION SOCIEDAD AGRICOLA LTDA.",
            "LA CONCEPCION SOCIEDAD AGRICOLA LTDA",
            "LA CONCEPCION SOCIEDAD AGRICOLA  LTDA.",
            "LA CONCEPCION SOCIEDAD AGRICOLA",
            "LA CONCEPCION SOCIEDAD",
        ):
            out, ch = _replace_wt_content(out, old, membrete.razon)
            changed = changed or ch
            out, ch = _remove_wr_runs_only_text(out, old)
            changed = changed or ch
        for frag in (
            "PARC. EL SAUCE LOTE 4 LA APARICION PAINE",
            "PARC. EL SAUCE LOTE 4",
            "LA APARICION PAINE",
            "EL SAUCE LOTE 4",
        ):
            out, ch = _remove_wr_runs_only_text(out, frag)
            changed = changed or ch
        if "EL ESPINO" in out.upper():
            for frag in ("LA CONCEPCION", "LA APARICION", "EL SAUCE LOTE 4"):
                out, ch = _remove_wr_runs_only_text(out, frag)
                changed = changed or ch
        out, ch = _replace_wt_content(
            out, "PARC. EL SAUCE LOTE 4 LA APARICION PAINE", membrete.direccion
        )
        changed = changed or ch

    if membrete.slug == "cerezos":
        out, ch = _replace_wt_content(out, "LA CONCEPCION", membrete.razon)
        changed = changed or ch
        for frag in ("SOCIEDAD AGRICOLA LTDA.", "SOCIEDAD AGRICOLA LTDA"):
            out, ch = _remove_wr_runs_only_text(out, frag)
            changed = changed or ch

    for foreign in _foreign_direcciones(membrete):
        out, ch = _replace_wt_content(out, foreign, membrete.direccion)
        changed = changed or ch

    if membrete.slug == "ciruelos":
        out, ch = _replace_wt_content(
            out, "CAMINO LAS LILAS PARC. 44 PAINE", membrete.direccion
        )
        changed = changed or ch
        out, ch = _replace_wt_content(out, "CAMINO LAS LILAS PARC.44", membrete.direccion)
        changed = changed or ch

    out, ch = _append_rut_to_razon_wt(out, membrete)
    changed = changed or ch

    if not _xml_well_formed(out):
        return orig, False
    if not _header_titles_preserved(plain_before, _xml_plain_text(out)):
        return orig, False
    return out, changed and out != orig


def _ooxml_bytes_valid(data: bytes, xlsx: bool = False) -> bool:
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
        if xlsx:
            import openpyxl

            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True)
            wb.close()
        return True
    except Exception:
        return False


def _patch_xlsx_xml(filename: str, xml: str, membrete: Membrete) -> tuple[str, bool]:
    """Solo encabezados/pies de hoja Excel — no sharedStrings (evita pisar celdas)."""
    fn = filename.lower()
    if fn.startswith("xl/worksheets/") and fn.endswith(".xml"):
        changed = False

        def _hf_sub(m: re.Match) -> str:
            nonlocal changed
            body, ch = _patch_excel_header_content(m.group(2), membrete)
            if ch:
                changed = True
            return m.group(1) + body + m.group(3)

        for tag in (
            "oddHeader",
            "evenHeader",
            "firstHeader",
            "oddFooter",
            "evenFooter",
            "firstFooter",
        ):
            xml = re.sub(
                rf"(<{tag}[^>]*>)(.*?)(</{tag}>)",
                _hf_sub,
                xml,
                flags=re.S,
            )
        return xml, changed
    return xml, False


def _patch_docx_xml(filename: str, xml: str, membrete: Membrete) -> tuple[str, bool]:
    fn = filename.lower()
    if not (fn.endswith(".xml") and ("header" in fn or "footer" in fn)):
        return xml, False
    return _patch_docx_header_xml_safe(xml, membrete)


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
    is_xlsx = path.suffix.lower() == ".xlsx"
    notes: list[str] = []
    in_buf = path.read_bytes()
    out_buf = io.BytesIO()
    changed = False
    with zipfile.ZipFile(io.BytesIO(in_buf)) as zin:
        with zipfile.ZipFile(out_buf, "w") as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                fn = item.filename.lower()
                if is_xlsx:
                    patchable = fn.startswith("xl/worksheets/") and fn.endswith(".xml")
                else:
                    patchable = ("header" in fn or "footer" in fn) and fn.endswith(".xml")
                if patchable:
                    try:
                        text = data.decode("utf-8")
                    except UnicodeDecodeError:
                        zout.writestr(item, data)
                        continue
                    if is_xlsx:
                        new_text, ch = _patch_xlsx_xml(item.filename, text, membrete)
                    else:
                        new_text, ch = _patch_docx_xml(item.filename, text, membrete)
                    if ch:
                        changed = True
                        notes.append(Path(item.filename).name)
                        data = new_text.encode("utf-8")
                zout.writestr(item, data)
    if not changed:
        return False, "sin-cambios-zip"
    out_data = out_buf.getvalue()
    if not _ooxml_bytes_valid(out_data, xlsx=is_xlsx):
        return False, "ooxml-invalido-revertido"
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


def restore_slug_from_backup(slug: str, backup: Path, excel_only: bool = False) -> None:
    import tarfile

    if not backup.is_file():
        raise SystemExit(f"No existe backup {backup}")
    prefix = f"globalgap/docs/{slug}/"
    dest = DOCS_ROOT / slug
    if excel_only:
        if not dest.is_dir():
            raise SystemExit(f"No existe {dest}")
    else:
        if dest.exists():
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.move(str(dest), str(dest.with_name(f"{slug}_pre_restore_{ts}")))
        dest.mkdir(parents=True, exist_ok=True)
    n = 0
    with tarfile.open(backup) as tar:
        for member in tar.getmembers():
            if not member.name.startswith(prefix) or member.isdir():
                continue
            rel = member.name[len(prefix) :]
            if not rel or rel.endswith(".bak"):
                continue
            if excel_only and Path(rel).suffix.lower() not in {".xlsx", ".xls"}:
                continue
            out = dest / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as src:
                out.write_bytes(src.read())
            n += 1
    kind = "excel" if excel_only else "full"
    print(f"RESTORE-{kind}\t{slug}\tfrom {backup.name}\tfiles={n}")


def validate_slug(slug: str) -> int:
    bad: list[tuple[str, str]] = []
    ok = 0
    for path in collect_files(slug):
        rel = str(path.relative_to(DOCS_ROOT))
        ext = path.suffix.lower()
        if ext in {".docx", ".xlsx", ".xlsm"}:
            data = path.read_bytes()
            if not _ooxml_bytes_valid(data, xlsx=(ext == ".xlsx")):
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
    parser.add_argument(
        "--docs-root",
        type=Path,
        default=None,
        help="Raíz globalgap/docs (contiene subcarpeta espino|cerezos|...)",
    )
    parser.add_argument(
        "--restore-excel-only",
        action="store_true",
        help="Con --restore-from-backup: solo .xlsx/.xls",
    )
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    global DOCS_ROOT
    if args.docs_root is not None:
        DOCS_ROOT = args.docs_root

    slugs = args.slug or ["cerezos", "ciruelos", "espino"]

    if args.restore_from_backup:
        for slug in slugs:
            restore_slug_from_backup(
                slug, args.restore_from_backup, excel_only=args.restore_excel_only
            )
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
