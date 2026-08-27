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
        foreign = []
        for m in MEMBRETES.values():
            if m.slug == self.slug:
                continue
            if m.razon.upper() in u:
                foreign.append(m.razon)
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


def _file_text(path: Path) -> str:
    if zipfile.is_zipfile(path):
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
        return False, "ok"
    if membrete.has_foreign(text):
        return True, "foreign-membrete"
    if not membrete.markers_ok(text):
        return True, "incomplete-membrete"
    return False, "ok"


def _apply_legacy_replacements(data: bytes | str, membrete: Membrete) -> bytes | str:
    is_bytes = isinstance(data, bytes)
    text = data.decode("latin-1", errors="ignore") if is_bytes else data
    for old, new in _LEGACY_RAZON:
        text = re.sub(re.escape(old), membrete.razon, text, flags=re.I)
    for old, new in _LEGACY_DIR:
        if membrete.slug == "ciruelos":
            text = re.sub(re.escape(old), membrete.direccion, text, flags=re.I)
        elif membrete.slug == "cerezos" and "SAUCE" in old.upper():
            text = re.sub(re.escape(old), membrete.direccion, text, flags=re.I)
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

    new = _apply_legacy_replacements(patched, membrete)
    if isinstance(new, bytes) and new != patched:
        patched = new
        notes.append("legacy")

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
    return True, ";".join(notes) or "doc"


def _patch_header_footer_xml(xml: str, membrete: Membrete) -> tuple[str, bool]:
    orig = xml
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

    # RUT
    if membrete.rut not in xml:
        rut_block = (
            f"</w:t></w:r><w:r><w:rPr/><w:t>RUT: {membrete.rut}</w:t></w:r><w:r><w:rPr/><w:t>"
        )
        xml = xml.replace(f">{membrete.razon}</w:t>", f">{membrete.razon}{rut_block}", 1)

    # Quitar otras razones sociales del encabezado
    for other in MEMBRETES.values():
        if other.slug == membrete.slug:
            continue
        xml = re.sub(re.escape(other.razon), "", xml, flags=re.I)
        xml = re.sub(re.escape(other.razon.rstrip(".")), "", xml, flags=re.I)

    return xml, xml != orig


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
    path.write_bytes(out_buf.getvalue())
    return True, ";".join(notes[:5])


def patch_file(path: Path, membrete: Membrete) -> tuple[bool, str]:
    ext = path.suffix.lower()
    if ext == ".doc":
        return patch_doc(path, membrete)
    if ext in {".docx", ".xlsx", ".xls"}:
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--bootstrap-espino", action="store_true")
    parser.add_argument("--slug", action="append", default=[], help="cerezos|ciruelos|espino")
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()

    slugs = args.slug or ["cerezos", "ciruelos", "espino"]

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
