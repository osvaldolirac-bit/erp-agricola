#!/usr/bin/env python3
"""Prepara carpeta espino desde Drive (La Concepcion) y aplica membrete El Espino."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

RENAME_DIRS = {
    "Registros La Concepcion": "Registros El Espino",
}


def prepare_tree(src: Path, dest_root: Path) -> Path:
    """src/La Concepcion/* -> dest_root/espino/* con carpeta Registros renombrada."""
    src_lc = src / "La Concepcion"
    if not src_lc.is_dir():
        raise SystemExit(f"No existe {src_lc}")
    espino = dest_root / "espino"
    if espino.exists():
        shutil.rmtree(espino)
    espino.mkdir(parents=True)

    for item in src_lc.iterdir():
        name = item.name
        if name in RENAME_DIRS:
            name = RENAME_DIRS[name]
        out = espino / name
        if item.is_dir():
            shutil.copytree(item, out)
        else:
            shutil.copy2(item, out)

    # GGRG03 u otros en raíz del drive fuera de La Concepcion
    for extra in src.iterdir():
        if extra.name == "La Concepcion" or not extra.is_file():
            continue
        if extra.suffix.lower() in {".pdf"} and "globalgap" in extra.name.lower():
            continue
        if extra.suffix.lower() in {".xlsx", ".xls", ".doc", ".docx"}:
            shutil.copy2(extra, espino / extra.name)
    return espino


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--src",
        type=Path,
        default=Path("/tmp/gap_drive_espino"),
        help="Carpeta descargada de Drive (contiene La Concepcion/)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("/tmp/gap_espino_clean"),
        help="Salida: {out}/espino/...",
    )
    parser.add_argument("--skip-patch", action="store_true")
    args = parser.parse_args()

    espino = prepare_tree(args.src, args.out)
    n = sum(1 for _ in espino.rglob("*") if _.is_file())
    print(f"PREPARE\t{espino}\tfiles={n}")

    if args.skip_patch:
        return 0

    script = Path(__file__).resolve().parent / "patch_gap_membretes_predio.py"
    cmd = [
        sys.executable,
        str(script),
        "--slug",
        "espino",
        "--docs-root",
        str(args.out),
        "--no-backup",
    ]
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)
    subprocess.run(
        [sys.executable, str(script), "--slug", "espino", "--docs-root", str(args.out), "--validate-only"],
        check=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
