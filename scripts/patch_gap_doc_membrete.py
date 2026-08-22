#!/usr/bin/env python3
"""Actualiza membrete .doc GlobalGAP con las 3 razones sociales completas.

Reemplazo binario same-length sobre la región de control (\\x03\\r\\r\\x04...)
y bloques secundarios del encabezado. No usa LibreOffice.
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

CTRL = b"\x03\r\r\x04\r\r\x03\r\r\x04"

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
    ]


def _fit_inner_to_budget(budget: int) -> bytes:
    """Distribuye L1/L2/L3 en budget bytes (incluye \\r entre filas)."""
    if budget >= len(INNER3):
        return _pad(INNER3, budget)

    need_l1_l2 = len(L1) + 1 + len(L2)
    need_three_min = need_l1_l2 + 1 + 1  # L1 + L2 + al menos 1 char de L3

    if budget >= need_three_min:
        l3_len = budget - need_l1_l2 - 1
        inner = L1 + b"\r" + L2 + b"\r" + L3[:l3_len]
        return inner[:budget]

    if budget >= need_l1_l2:
        return L1 + b"\r" + L2 + b" " * (budget - need_l1_l2)

    if budget >= len(L1):
        return _pad(L1, budget)

    if budget >= len(L2):
        return _pad(L2, budget)

    return _pad(L1, budget)[:budget]


def _fit_ctrl_region(old_region: bytes) -> tuple[bytes | None, str]:
    if not old_region.startswith(CTRL) or not old_region.endswith(b"\x07"):
        return None, ""

    target = len(old_region)
    body_budget = target - len(CTRL) - 1
    if body_budget <= 0:
        return None, ""

    if body_budget >= len(INNER3):
        pad_len = body_budget - len(INNER3)
        body = (b"\r" * pad_len) + INNER3 if pad_len else INNER3
        kind = "ctrl-3line"
    else:
        body = _fit_inner_to_budget(body_budget)
        kind = "ctrl-fit"

    new_region = CTRL + body + b"\x07"
    if len(new_region) != target:
        return None, ""
    return new_region, kind


def _find_ctrl_regions(raw: bytes) -> list[tuple[int, int, bytes]]:
    seen: set[tuple[int, int]] = set()
    out: list[tuple[int, int, bytes]] = []

    for marker in (b"INTRUCTIVO", b"INSTRUCTIVO"):
        idx = 0
        while True:
            idx = raw.find(marker, idx)
            if idx < 0:
                break
            start_search = max(0, idx - 160)
            chunk = raw[start_search:idx]
            pos = chunk.rfind(CTRL)
            if pos >= 0:
                abs_start = start_search + pos
                segment = raw[abs_start:idx]
                x7 = segment.rfind(b"\x07")
                if x7 >= 0:
                    abs_end = abs_start + x7 + 1
                    key = (abs_start, abs_end)
                    if key not in seen:
                        seen.add(key)
                        out.append((abs_start, abs_end, raw[abs_start:abs_end]))
            idx += len(marker)

    return sorted(out, key=lambda item: item[0])


def _patch_ctrl_regions(raw: bytes) -> tuple[bytes, list[str]]:
    data = bytearray(raw)
    notes: list[str] = []
    patched_ranges: list[tuple[int, int]] = []

    for start, end, old_region in _find_ctrl_regions(raw):
        new_region, kind = _fit_ctrl_region(old_region)
        if new_region is None or new_region == old_region:
            notes.append(f"ctrl-skip@{start}:{len(old_region)}B")
            continue
        data[start:end] = new_region
        patched_ranges.append((start, end))
        notes.append(f"{kind}@{start}:{len(old_region)}B")

    return bytes(data), notes, patched_ranges


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


def _fit_block(old_block: bytes) -> tuple[bytes | None, str]:
    n = len(old_block)
    variants = _build_block_variants(n)
    if variants:
        return variants[0], "block-3line"
    tight = _build_tight_block(old_block)
    if tight:
        return tight, "block-tight"
    prefix, inner, suffix = _split_suffix(old_block)
    body_len = len(inner)
    if body_len > 0:
        fitted = _fit_inner_to_budget(body_len)
        new_block = prefix + fitted + suffix
        if len(new_block) == n and fitted != inner:
            return new_block, "block-fit"
    return None, ""


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _find_blocks(raw: bytes) -> list[tuple[int, int, bytes]]:
    return [
        (m.start(), m.start() + len(m.group(1)), m.group(1))
        for m in _BLOCK_RE.finditer(raw)
    ]


def _patch_membrete_blocks(
    raw: bytes, skip_ranges: list[tuple[int, int]]
) -> tuple[bytes, list[str]]:
    data = bytearray(raw)
    notes: list[str] = []
    blocks = _find_blocks(raw)
    if not blocks:
        return raw, []

    for start, end, old_block in reversed(blocks):
        if any(_overlaps((start, end), skip) for skip in skip_ranges):
            notes.append(f"block-skip-overlap@{start}:{len(old_block)}B")
            continue
        new_block, kind = _fit_block(old_block)
        if new_block is None or new_block == old_block:
            notes.append(f"block-skip@{start}:{len(old_block)}B")
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
    patched, ctrl_notes, ctrl_ranges = _patch_ctrl_regions(raw)
    patched, block_notes = _patch_membrete_blocks(patched, ctrl_ranges)
    patched, body_notes = _apply_body_replacements(patched)
    notes = ctrl_notes + block_notes + body_notes
    if not notes or all("skip" in n for n in notes):
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
            raw = path.read_bytes()
            patched, ctrl_notes, ctrl_ranges = _patch_ctrl_regions(raw)
            _, block_notes = _patch_membrete_blocks(patched, ctrl_ranges)
            notes = ctrl_notes + block_notes
            ok = notes and not all("skip" in n for n in notes)
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
