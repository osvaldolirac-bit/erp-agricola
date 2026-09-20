#!/usr/bin/env python3
"""Restaura archivos GlobalGAP desde backup tar.gz (modo merge, sin borrar carpeta)."""
from __future__ import annotations

import argparse
import tarfile
from pathlib import Path

DOCS_ROOT = Path("/root/demo-web/demo_web/static/globalgap/docs")
DEFAULT_BACKUP = DOCS_ROOT.parent / "docs_backup_membrete_20260827_125118.tar.gz"


def restore_merge(
    backup: Path,
    slug: str,
    folders: tuple[str, ...],
    exts: tuple[str, ...],
) -> int:
    prefix = f"globalgap/docs/{slug}/"
    dest = DOCS_ROOT / slug
    if not backup.is_file():
        raise SystemExit(f"No existe backup {backup}")
    if not dest.is_dir():
        raise SystemExit(f"No existe {dest}")
    n = 0
    with tarfile.open(backup) as tar:
        for member in tar.getmembers():
            if not member.name.startswith(prefix) or member.isdir():
                continue
            rel = member.name[len(prefix) :]
            if not rel:
                continue
            p = Path(rel)
            if folders and p.parts[0] not in folders:
                continue
            if exts and p.suffix.lower() not in exts:
                continue
            out = dest / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as src:
                out.write_bytes(src.read())
            n += 1
            print(f"RESTORE\t{slug}/{rel}")
    print(f"OK\t{slug}\tfiles={n}\tfrom={backup.name}")
    return n


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", type=Path, default=DEFAULT_BACKUP)
    parser.add_argument("--slug", action="append", required=True)
    parser.add_argument(
        "--folders",
        nargs="+",
        default=["Procedimientos", "Planes"],
        help="Subcarpetas a restaurar (vacío = todas)",
    )
    parser.add_argument(
        "--ext",
        dest="exts",
        nargs="+",
        default=[".docx"],
        help="Extensiones incluidas, ej. .docx .xlsx",
    )
    args = parser.parse_args()
    folders = tuple(args.folders)
    exts = tuple(e.lower() if e.startswith(".") else f".{e.lower()}" for e in args.exts)
    total = 0
    for slug in args.slug:
        total += restore_merge(args.backup, slug, folders, exts)
    print(f"TOTAL\tfiles={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
