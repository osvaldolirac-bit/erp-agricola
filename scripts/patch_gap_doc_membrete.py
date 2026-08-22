#!/usr/bin/env python3
"""Actualiza membrete en .doc / .docx GlobalGAP (Instructivos / Anexos) vía LibreOffice UNO."""
from __future__ import annotations

import argparse
import glob
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

HEADER_LINES = (
    "LA CONCEPCION AGRICOLA LTDA",
    "CARLOS LIRA VALENCIA",
    "SOCIEDAD AGRICOLA EL ESPINO LTDA",
)

DOCS_ROOT = Path("/root/demo-web/demo_web/static/globalgap/docs")
SUBDIRS = ("Instructivos", "Anexos")
UNO_PORT = 2003


def _norm(text: str) -> str:
    s = unicodedata.normalize("NFKD", text or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"\s+", " ", s).strip().upper()
    return s


def _is_membrete_paragraph(text: str) -> bool:
    t = _norm(text)
    if not t or len(t) > 90:
        return False
    if any(x in t for x in ("RAZON SOCIAL", "DIRECCION", "PREDIO:", "AVISAR", "ANTE ", "CERTIFICA")):
        return False
    keys = (
        "LA CONCEPCION",
        "CARLOS LIRA",
        "SOCIEDAD AGRICOLA EL ESPINO",
        "CONCEPCION SOCIEDAD AGRICOLA",
        "CONCEPCION AGRICOLA",
    )
    return any(k in t for k in keys)


def _start_soffice() -> None:
    subprocess.Popen(
        [
            "soffice",
            "--headless",
            "--invisible",
            "--nologo",
            "--nodefault",
            f"--accept=socket,host=127.0.0.1,port={UNO_PORT};urp;StarOffice.ServiceManager",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(3)


def _connect():
    import uno

    local_ctx = uno.getComponentContext()
    resolver = local_ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", local_ctx
    )
    ctx = resolver.resolve(
        f"uno:socket,host=127.0.0.1,port={UNO_PORT};urp;StarOffice.ComponentContext"
    )
    smgr = ctx.ServiceManager
    desktop = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
    return desktop, uno


def _prop(name: str, value) -> object:
    from com.sun.star.beans import PropertyValue

    p = PropertyValue()
    p.Name = name
    p.Value = value
    return p


def _set_page_header(doc) -> bool:
    from com.sun.star.text import ControlCharacter

    style = doc.getStyleFamilies().getByName("PageStyles").getByName("Standard")
    style.setPropertyValue("HeaderIsOn", True)
    header = style.getPropertyValue("HeaderText")
    if header is None:
        return False
    header.setString("")
    for i, line in enumerate(HEADER_LINES):
        if i:
            header.insertControlCharacter(header.getEnd(), ControlCharacter.PARAGRAPH_BREAK, False)
        header.insertString(header.getEnd(), line, False)
    return True


def _body_paragraphs(doc) -> list:
    text = doc.getText()
    enum = text.createEnumeration()
    paras = []
    while enum.hasMoreElements():
        el = enum.nextElement()
        if el.supportsService("com.sun.star.text.Paragraph"):
            paras.append(el)
    return paras


def _patch_body_membrete(doc) -> bool:
    paras = _body_paragraphs(doc)
    if not paras:
        return False

    indices: list[int] = []
    started = False
    for i, para in enumerate(paras[:20]):
        raw = para.getString()
        if not raw.strip():
            if started:
                indices.append(i)
            continue
        if _is_membrete_paragraph(raw):
            indices.append(i)
            started = True
            continue
        if started:
            break
        break

    membrete_idx = [i for i in indices if paras[i].getString().strip()]
    if not membrete_idx:
        return False

    for n, idx in enumerate(membrete_idx[:3]):
        paras[idx].setString(HEADER_LINES[n])
    for idx in membrete_idx[3:]:
        paras[idx].setString("")
    return True


def patch_file(desktop, uno, path: Path) -> tuple[bool, str]:
    url = uno.systemPathToFileUrl(str(path.resolve()))
    doc = desktop.loadComponentFromURL(
        url,
        "_blank",
        0,
        (_prop("Hidden", True), _prop("ReadOnly", False)),
    )
    if doc is None:
        return False, "no se pudo abrir"
    try:
        h = _set_page_header(doc)
        b = _patch_body_membrete(doc)
        if not h and not b:
            return False, "sin encabezado ni membrete en cuerpo"
        doc.store()
        parts = []
        if h:
            parts.append("header")
        if b:
            parts.append("body")
        return True, "+".join(parts)
    finally:
        doc.close(True)


DOC_GLOBS = ("*.doc", "*.docx")


def collect_files(roots: list[Path]) -> list[Path]:
    out: list[Path] = []
    for root in roots:
        for sub in SUBDIRS:
            d = root / sub
            if not d.is_dir():
                continue
            for pattern in DOC_GLOBS:
                out.extend(sorted(Path(p) for p in glob.glob(str(d / pattern))))
    # Evitar respaldos *.doc.bak capturados por *.doc
    return sorted({p for p in out if not p.name.endswith(".bak")})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--root", action="append", default=[])
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()

    roots = [Path(r) for r in args.root] if args.root else [
        DOCS_ROOT / "cerezos",
        DOCS_ROOT / "ciruelos",
    ]
    files = collect_files(roots)
    if not files:
        print("No se encontraron archivos .doc/.docx en Instructivos/Anexos", file=sys.stderr)
        return 1

    if args.dry_run:
        for f in files:
            print(f)
        print(f"Total: {len(files)}")
        return 0

    if not args.no_backup:
        for path in files:
            bak = path.with_suffix(path.suffix + ".bak")
            if not bak.exists():
                bak.write_bytes(path.read_bytes())

    _start_soffice()
    desktop, uno = _connect()
    ok_n = 0
    for path in files:
        try:
            ok, msg = patch_file(desktop, uno, path)
            status = "OK" if ok else "SKIP"
            print(f"{status}\t{path.name}\t{msg}")
            if ok:
                ok_n += 1
        except Exception as exc:
            print(f"ERR\t{path.name}\t{exc}", file=sys.stderr)
    print(f"Actualizados: {ok_n}/{len(files)}")
    return 0 if ok_n else 1


if __name__ == "__main__":
    sys.exit(main())
