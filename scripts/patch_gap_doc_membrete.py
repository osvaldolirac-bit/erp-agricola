#!/usr/bin/env python3
"""Actualiza solo textos de membrete en .doc GlobalGAP (Instructivos / Anexos).

Reemplazo binario same-length: preserva código del documento, título, marcos
y estructura Word. No usa LibreOffice (re-guardar .doc nativos los corrompe).
"""
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

DOCS_ROOT = Path("/root/demo-web/demo_web/static/globalgap/docs")
SUBDIRS = ("Instructivos", "Anexos")

_MARKERS = (
    b"GGIN",
    b"GGAN",
    b"ANEXO",
    b"INTRUCTIVO",
    b"INSTRUCTIVO",
    b"PROCEDIMIENTO",
    b"C\xf3d.",
)


def _pad(value: bytes, size: int) -> bytes:
    if len(value) > size:
        raise ValueError(f"texto demasiado largo ({len(value)}>{size}): {value!r}")
    return value + b" " * (size - len(value))


def _build_replacements() -> list[tuple[bytes, bytes]]:
    razon_lc = "Raz\u00f3n Social/Predio: LA CONCEPCION AGRICOLA LTDA.".encode("latin-1")
    razon_cv = "Raz\u00f3n Social/Predio: LA CONCEPCION AGRICO.".encode("latin-1")
    dir_carlos = "DIRECCI\u00d3N: CARLOS LIRA VALENCIA".encode("latin-1")
    dir_espino = "DIRECCI\u00d3N: SOCIEDAD AGRICOLA EL ESPINO LTDA".encode("latin-1")
    return [
        # GGIN01 — bloque Razón Social / Dirección en cuerpo
        (
            "Raz\u00f3n Social/Predio: LA CONCEPCION SOCIEDAD AGRICOLA LTDA.".encode("latin-1"),
            _pad(razon_lc, 58),
        ),
        (
            "Raz\u00f3n Social/Predio: CARLOS LIRA VALENCIA.".encode("latin-1"),
            _pad(razon_cv, 42),
        ),
        (
            "DIRECCI\u00d3N:  PARC. EL SAUCE LOTE 4 LA APARICION PAINE".encode("latin-1"),
            _pad(dir_carlos, 52),
        ),
        (
            "DIRECCI\u00d3N: CAMINO LAS LILAS PARC.44 CHADA PAINE".encode("latin-1"),
            _pad(dir_espino, 47),
        ),
        # Ciruelos — línea 1 del membrete (con contexto \rCAMINO para no tocar cuerpo)
        (
            b"CARLOS LIRA VALENCIA\rCAMINO LAS LILAS PARC.44\rCHADA",
            b"LA CONCEPCION AGRICO\rCAMINO LAS LILAS PARC.44\rCHADA",
        ),
        (
            b"CARLOS LIRA VALENCIA \rCAMINO",
            b"LA CONCEPCION AGRICOL\rCAMINO",
        ),
        (
            b"CARLOS LIRA VALENCIA\rCAMINO",
            b"LA CONCEPCION AGRICO\rCAMINO",
        ),
        # Cerezos — membrete tabla
        (
            b"PARC. EL SAUCE LOTE 4 LA APARICION PAINE ",
            _pad(b"CARLOS LIRA VALENCIA", 41),
        ),
        (
            b"PARC. EL SAUCE LOTE 4 LA APARICION PAINE",
            _pad(b"SOCIEDAD AGRICOLA EL ESPINO LTDA", 40),
        ),
        (
            b"LA CONCEPCION SOCIEDAD AGRICOLA LTDA",
            _pad(b"LA CONCEPCION AGRICOLA LTDA", 36),
        ),
        (
            b"SOCIEDAD AGRICOLA EL ESPINO LTDA.",
            _pad(b"CARLOS LIRA VALENCIA", 33),
        ),
        # Ciruelos — líneas de dirección en membrete
        (
            b"CAMINO LAS LILAS PARC.44 CHADA PAINE ",
            _pad(b"CARLOS LIRA VALENCIA", 37),
        ),
        (
            b"CAMINO LAS LILAS PARC.44 CHADA PAINE",
            _pad(b"SOCIEDAD AGRICOLA EL ESPINO LTDA", 36),
        ),
        (
            b"CAMINO LAS LILAS PARC.44 ",
            _pad(b"CARLOS LIRA VALENCIA", 25),
        ),
        (
            b"CHADA PAINE ",
            _pad(b"ESPINO LTDA ", 12),
        ),
        (
            b"CHADA PAINE",
            _pad(b"ESPINO LTDA", 11),
        ),
    ]


_REPLACEMENTS = _build_replacements()


def _validate_rules() -> None:
    for old, new in _REPLACEMENTS:
        if len(old) != len(new):
            raise ValueError(f"longitud distinta: {old!r} ({len(old)}) vs {new!r} ({len(new)})")


def _patch_bytes(raw: bytes) -> tuple[bytes, list[str]]:
    data = raw
    applied: list[str] = []
    for old, new in _REPLACEMENTS:
        count = data.count(old)
        if count:
            data = data.replace(old, new)
            applied.append(f"{old.decode('latin-1', errors='replace')!r} x{count}")
    return data, applied


def _integrity_ok(raw: bytes) -> tuple[bool, str]:
    if not any(m in raw for m in _MARKERS):
        return False, "sin marcadores de código/título (GGIN/ANEXO/INTRUCTIVO/Cód.)"
    return True, ""


def collect_files(roots: list[Path]) -> list[Path]:
    out: list[Path] = []
    for root in roots:
        for sub in SUBDIRS:
            d = root / sub
            if not d.is_dir():
                continue
            out.extend(sorted(Path(p) for p in glob.glob(str(d / "*.doc"))))
    return sorted({p for p in out if not p.name.endswith(".bak")})


def patch_file(path: Path) -> tuple[bool, str]:
    raw = path.read_bytes()
    patched, applied = _patch_bytes(raw)
    if not applied:
        return False, "sin coincidencias de membrete"
    ok, reason = _integrity_ok(patched)
    if not ok:
        return False, f"abortado: {reason}"
    path.write_bytes(patched)
    return True, "; ".join(applied)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--root", action="append", default=[])
    parser.add_argument("--no-backup", action="store_true")
    parser.add_argument("--restore", action="store_true", help="Restaurar desde .bak y salir")
    args = parser.parse_args()

    _validate_rules()

    roots = [Path(r) for r in args.root] if args.root else [
        DOCS_ROOT / "cerezos",
        DOCS_ROOT / "ciruelos",
    ]

    if args.restore:
        restored = 0
        for root in roots:
            for bak in sorted(root.rglob("*.bak")):
                target = Path(str(bak)[:-4])
                if target.suffix.lower() != ".doc":
                    continue
                target.write_bytes(bak.read_bytes())
                restored += 1
                print(f"RESTORE\t{target}")
        print(f"Restaurados: {restored}")
        return 0

    files = collect_files(roots)
    if not files:
        print("No se encontraron archivos .doc en Instructivos/Anexos", file=sys.stderr)
        return 1

    if args.dry_run:
        for path in files:
            raw = path.read_bytes()
            _, applied = _patch_bytes(raw)
            status = "OK" if applied else "SKIP"
            print(f"{status}\t{path.name}\t{'; '.join(applied) if applied else '-'}")
        print(f"Total: {len(files)}")
        return 0

    if not args.no_backup:
        for path in files:
            bak = path.with_suffix(path.suffix + ".bak")
            if not bak.exists():
                bak.write_bytes(path.read_bytes())

    ok_n = 0
    for path in files:
        try:
            ok, msg = patch_file(path)
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
