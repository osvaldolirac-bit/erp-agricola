#!/usr/bin/env python3
"""Actualiza membrete .doc GlobalGAP con las 3 razones sociales completas.

Reemplazo binario same-length: reorganiza \\r del prefijo para caber 3 líneas.
No usa LibreOffice.
"""
from __future__ import annotations

import argparse
import glob
import re
import sys
from pathlib import Path

DOCS_ROOT = Path("/root/demo-web/demo_web/static/globalgap/docs")
SUBDIRS = ("Instructivos", "Anexos")

L1 = b"LA CONCEPCION AGRICOLA LTDA"
L2 = b"CARLOS LIRA VALENCIA"
L3 = b"SOCIEDAD AGRICOLA EL ESPINO LTDA"
INNER3 = L1 + b"\r" + L2 + b"\r" + L3

_MARKERS = (
    b"GGIN",
    b"GGAN",
    b"ANEXO",
    b"INTRUCTIVO",
    b"INSTRUCTIVO",
    b"PROCEDIMIENTO",
    b"C\xf3d.",
)

_BLOCK_RE = re.compile(
    rb"(\r{1,6}(?:LA CONCEPCION|CARLOS LIRA|SOCIEDAD AGRICOLA|CAMINO LAS).{5,110}?\x07\r*)"
    rb"(?=INTRUCTIVO|INSTRUCTIVO)",
)

_BODY_REPLACEMENTS: list[tuple[bytes, bytes]] = []
_SUFFIXES = (b"\x07\r", b"\x07", b"\x07\r\r", b"\r\x07", b"\r\r\x07", b"\r\x07\r")


def _pad(value: bytes, size: int) -> bytes:
    if len(value) > size:
        return value[:size]
    return value + b" " * (size - len(value))


def _build_body_replacements() -> list[tuple[bytes, bytes]]:
    razon_lc = "Raz\u00f3n Social/Predio: LA CONCEPCION AGRICOLA LTDA.".encode("latin-1")
    razon_cv = "Raz\u00f3n Social/Predio: LA CONCEPCION AGRICO.".encode("latin-1")
    dir_carlos = "DIRECCI\u00d3N: CARLOS LIRA VALENCIA".encode("latin-1")
    dir_espino = "DIRECCI\u00d3N: SOCIEDAD AGRICOLA EL ESPINO LTDA".encode("latin-1")
    return [
        (
            "Raz\u00f3n Social/Predio: LA CONCEPCION SOCIEDAD AGRICOLA LTDA.".encode("latin-1"),
            _pad(b"Raz\u00f3n Social/Predio: LA CONCEPCION AGRICOLA LTDA.", 58),
        ),
        (
            "Raz\u00f3n Social/Predio: CARLOS LIRA VALENCIA.".encode("latin-1"),
            _pad(b"Raz\u00f3n Social/Predio: LA CONCEPCION AGRICO.", 42),
        ),
        (
            "DIRECCI\u00d3N:  PARC. EL SAUCE LOTE 4 LA APARICION PAINE".encode("latin-1"),
            _pad(b"DIRECCI\u00d3N: CARLOS LIRA VALENCIA", 52),
        ),
        (
            "DIRECCI\u00d3N: CAMINO LAS LILAS PARC.44 CHADA PAINE".encode("latin-1"),
            _pad(b"DIRECCI\u00d3N: SOCIEDAD AGRICOLA EL ESPINO LTDA", 47),
        ),
    ]


def _split_suffix(block: bytes) -> tuple[bytes, bytes, bytes]:
    for suf in _SUFFIXES:
        if block.endswith(suf):
            core = block[: -len(suf)]
            prefix_len = len(core) - len(core.lstrip(b"\r"))
            return core[:prefix_len], core[prefix_len:], suf
    core = block
    prefix_len = len(core) - len(core.lstrip(b"\r"))
    return core[:prefix_len], core[prefix_len:], b""


def _build_block_variants(target_len: int) -> list[bytes]:
    out: list[bytes] = []
    for prefix_len in range(8):
        for suffix in _SUFFIXES:
            block = (b"\r" * prefix_len) + INNER3 + suffix
            if len(block) == target_len:
                out.append(block)
    return out


def _build_tight_inner(body_len: int) -> bytes | None:
    """3 líneas en body_len bytes; recorte mínimo solo al final de L3 si hace falta."""
    if body_len >= len(INNER3):
        return _pad(INNER3, body_len)
    trim = len(INNER3) - body_len
    if trim <= 0 or trim > 3:
        return None
    l3 = L3[:-trim] if trim < len(L3) else L3
    inner = L1 + b"\r" + L2 + b"\r" + l3
    return inner if len(inner) == body_len else None


def _build_tight_block(old_block: bytes) -> bytes | None:
    prefix, _, suffix = _split_suffix(old_block)
    target = len(old_block)
    best: bytes | None = None
    best_trim = 999
    # Probar prefijos de 0..len(prefix) priorizando prefijo mínimo (más espacio al cuerpo)
    for prefix_len in range(0, min(len(prefix), 4) + 1):
        body_len = target - prefix_len - len(suffix)
        if body_len <= 0:
            continue
        trim = len(INNER3) - body_len
        if trim < 0 or trim > 3:
            continue
        inner = _build_tight_inner(body_len)
        if inner is None:
            continue
        block = (b"\r" * prefix_len) + inner + suffix
        if len(block) != target:
            continue
        if trim < best_trim:
            best_trim = trim
            best = block
    return best


def _fit_single_line_block(target_len: int) -> bytes | None:
    for prefix_len in range(6):
        for suffix in (b"\r\x07", b"\x07\r", b"\x07", b"\r\r\x07"):
            body_len = target_len - prefix_len - len(suffix)
            if body_len <= 0:
                continue
            block = (b"\r" * prefix_len) + _pad(L1, body_len) + suffix
            if len(block) == target_len:
                return block
    return None


def _rebuild_ciruelos_block(old_block: bytes) -> bytes | None:
    """Distribuye L1/L2/L3 en las filas existentes (same-length)."""
    prefix, inner, suffix = _split_suffix(old_block)
    rows = [p for p in inner.split(b"\r") if p.strip()]
    if len(rows) < 2:
        return None

    # Prefijo mínimo y sufijo compacto para maximizar espacio útil
    min_prefix = b""
    compact_suffix = b"\x07" if suffix.startswith(b"\x07") else suffix
    budget = len(old_block) - len(min_prefix) - len(compact_suffix)

    if len(rows) == 2:
        n1 = len(rows[0])
        n2 = budget - n1 - 1
        if n2 < len(L2) + 2:
            return None
        row1 = _pad(L1, n1)
        l3_room = n2 - len(L2) - 1
        l3_part = L3 if len(L3) <= l3_room else L3[:l3_room]
        row2 = _pad(L2 + b"\r" + l3_part, n2)
        new_inner = row1 + b"\r" + row2
    else:
        n1 = len(rows[0])
        n2 = budget - n1 - 1
        if n2 < len(L2) + 2:
            return None
        row1 = _pad(L1, n1)
        l3_room = n2 - len(L2) - 1
        l3_part = L3 if len(L3) <= l3_room else L3[:l3_room]
        row2 = _pad(L2 + b"\r" + l3_part, n2)
        new_inner = row1 + b"\r" + row2

    if len(new_inner) > budget:
        return None
    if len(new_inner) < budget:
        new_inner = _pad(new_inner, budget)

    new_block = min_prefix + new_inner + compact_suffix
    if len(new_block) != len(old_block) and compact_suffix != suffix:
        # Compensar con espacios si el sufijo compacto liberó bytes
        pad = len(old_block) - len(new_block)
        if pad > 0:
            new_inner = _pad(new_inner, len(new_inner) + pad)
            new_block = min_prefix + new_inner + compact_suffix
    return new_block if len(new_block) == len(old_block) else None


def _fit_block(old_block: bytes) -> tuple[bytes | None, str]:
    n = len(old_block)
    variants = _build_block_variants(n)
    if variants:
        return variants[0], "3-line"
    tight = _build_tight_block(old_block)
    if tight:
        return tight, "3-line-tight"
    if n <= 40:
        single = _fit_single_line_block(n)
        if single:
            return single, "1-line-L1"
    if b"CAMINO" in old_block or (
        b"CARLOS LIRA" in old_block and b"LA CONCEPCION SOCIEDAD" not in old_block
    ):
        cir = _rebuild_ciruelos_block(old_block)
        if cir:
            return cir, "3-line-ciruelos"
    return None, ""


def _find_blocks(raw: bytes) -> list[tuple[int, int, bytes]]:
    return [
        (m.start(), m.start() + len(m.group(1)), m.group(1))
        for m in _BLOCK_RE.finditer(raw)
    ]


def _patch_membrete_blocks(raw: bytes) -> tuple[bytes, list[str]]:
    data = bytearray(raw)
    notes: list[str] = []
    blocks = _find_blocks(raw)
    if not blocks:
        return raw, []

    for start, end, old_block in reversed(blocks):
        new_block, kind = _fit_block(old_block)
        if new_block is None:
            notes.append(f"skip@{start}:{len(old_block)}B")
            continue
        data[start:end] = new_block
        notes.append(f"{kind}@{start}:{len(old_block)}B")

    return bytes(data), notes


def _apply_body_replacements(raw: bytes) -> tuple[bytes, list[str]]:
    data = raw
    applied: list[str] = []
    for old, new in _BODY_REPLACEMENTS:
        if old in data:
            data = data.replace(old, new)
            applied.append("body")
    return data, applied


def _integrity_ok(raw: bytes) -> tuple[bool, str]:
    if not any(m in raw for m in _MARKERS):
        return False, "sin marcadores GGIN/ANEXO/INTRUCTIVO/Cód."
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
    patched, block_notes = _patch_membrete_blocks(raw)
    patched, body_notes = _apply_body_replacements(patched)
    notes = block_notes + body_notes
    if not notes or all(n.startswith("skip") for n in notes):
        return False, "sin cambios"
    ok, reason = _integrity_ok(patched)
    if not ok:
        return False, f"abortado: {reason}"
    path.write_bytes(patched)
    return True, "; ".join(notes)


def main() -> int:
    global _BODY_REPLACEMENTS
    _BODY_REPLACEMENTS = _build_body_replacements()
    for old, new in _BODY_REPLACEMENTS:
        if len(old) != len(new):
            raise ValueError("body rule len mismatch")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--root", action="append", default=[])
    parser.add_argument("--no-backup", action="store_true")
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args()

    roots = [Path(r) for r in args.root] if args.root else [
        DOCS_ROOT / "cerezos",
        DOCS_ROOT / "ciruelos",
    ]

    if args.restore:
        n = 0
        for root in roots:
            for bak in sorted(root.rglob("*.bak")):
                target = Path(str(bak)[:-4])
                if target.suffix.lower() == ".doc":
                    target.write_bytes(bak.read_bytes())
                    n += 1
                    print(f"RESTORE\t{target}")
        print(f"Restaurados: {n}")
        return 0

    files = collect_files(roots)
    if not files:
        print("No se encontraron .doc", file=sys.stderr)
        return 1

    if args.dry_run:
        for path in files:
            _, notes = _patch_membrete_blocks(path.read_bytes())
            ok = notes and not all(n.startswith("skip") for n in notes)
            print(f"{'OK' if ok else 'SKIP'}\t{path.name}\t{'; '.join(notes)}")
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
            print(f"{'OK' if ok else 'SKIP'}\t{path.name}\t{msg}")
            if ok:
                ok_n += 1
        except Exception as exc:
            print(f"ERR\t{path.name}\t{exc}", file=sys.stderr)
    print(f"Actualizados: {ok_n}/{len(files)}")
    return 0 if ok_n else 1


if __name__ == "__main__":
    sys.exit(main())
