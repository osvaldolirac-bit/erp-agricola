#!/usr/bin/env python3
"""Auditoría read-only: corrupción OOXML y títulos pisados por parche membrete."""
from __future__ import annotations

import io
import re
import tarfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path


def check_ooxml(data: bytes, xlsx: bool = False) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if z.testzip() is not None:
                return "zip-crc"
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
        return "ok"
    except Exception as exc:
        return str(exc)[:100]


def xlsx_header_parts(data: bytes) -> tuple[str, str]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            if not (name.startswith("xl/worksheets/") and name.endswith(".xml")):
                continue
            xml = z.read(name).decode("utf-8", errors="ignore")
            m = re.search(
                r"<oddHeader[^>]*>(.*?)</oddHeader>", xml, re.S | re.I
            )
            if not m:
                return "", ""
            h = m.group(1)
            left, _, center = h.partition("&amp;C")
            center = re.sub(r"&amp;[^;\"]*;?", " ", center)
            center = " ".join(center.split())
            return left[:80], center[:120]
    return "", ""


def docx_text_parts(data: bytes) -> tuple[str, str]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        hdr_text = ""
        for name in sorted(z.namelist()):
            if name.startswith("word/header") and name.endswith(".xml"):
                xml = z.read(name).decode("utf-8", errors="ignore")
                hdr_text += " " + re.sub(r"<[^>]+>", " ", xml)
        body = ""
        if "word/document.xml" in z.namelist():
            body = z.read("word/document.xml").decode("utf-8", errors="ignore")
            body = re.sub(r"<[^>]+>", " ", body)
        hdr_text = " ".join(hdr_text.split())[:250]
        body = " ".join(body.split())[:250]
        return hdr_text, body


def audit_tree(root: Path, label: str) -> dict:
    corrupt: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*")):
        ext = path.suffix.lower()
        if ext not in {".docx", ".xlsx"}:
            continue
        rel = str(path.relative_to(root))
        st = check_ooxml(path.read_bytes(), xlsx=(ext == ".xlsx"))
        if st != "ok":
            corrupt.append((rel, st))
    return {"label": label, "corrupt": corrupt}


def compare_backup(bak: Path, current: Path, prefix: str) -> list[dict]:
    issues: list[dict] = []
    if not bak.is_file() or not current.is_dir():
        return issues
    with tarfile.open(bak) as tar:
        members = {
            m.name[len(prefix) :]: m
            for m in tar.getmembers()
            if m.name.startswith(prefix) and not m.isdir()
        }
        for rel, member in sorted(members.items()):
            ext = Path(rel).suffix.lower()
            if ext not in {".xlsx", ".docx"}:
                continue
            cur = current / rel
            if not cur.is_file():
                continue
            orig = tar.extractfile(member).read()
            new = cur.read_bytes()
            if orig == new:
                continue
            if ext == ".xlsx":
                _, c_old = xlsx_header_parts(orig)
                _, c_new = xlsx_header_parts(new)
                if c_old and (not c_new or c_old[:30].upper() not in (c_new or "").upper()):
                    issues.append(
                        {
                            "kind": "xlsx-center-title",
                            "file": rel,
                            "before": c_old,
                            "after": c_new,
                        }
                    )
            else:
                h_old, b_old = docx_text_parts(orig)
                h_new, b_new = docx_text_parts(new)
                for kw in ("PROCEDIMIENTO", "PLAN", "INSTRUCTIVO", "REGISTRO"):
                    if kw in (h_old + b_old).upper() and kw not in (h_new + b_new).upper():
                        issues.append(
                            {
                                "kind": "docx-title-lost",
                                "file": rel,
                                "before_hdr": h_old,
                                "after_hdr": h_new,
                                "before_body": b_old,
                                "after_body": b_new,
                            }
                        )
                        break
    return issues


def main() -> int:
    docs = Path("/root/demo-web/demo_web/static/globalgap/docs")
    for slug in ("espino", "cerezos", "ciruelos"):
        r = audit_tree(docs / slug, slug)
        print(f"\n=== {slug}: corrupt={len(r['corrupt'])} ===")
        for rel, st in r["corrupt"][:15]:
            print(f"  BAD {rel}\t{st}")

    bak_clean = docs / "docs_backup_membrete_20260827_125118.tar.gz"
    bak_drive = Path("/root/docs_backup_espino_drive_20260827_141430.tar.gz")
    for bak, slug in (
        (bak_clean, "espino"),
        (bak_drive, "espino"),
    ):
        if bak.is_file():
            issues = compare_backup(bak, docs / slug, f"globalgap/docs/{slug}/")
            print(f"\n=== title diff vs {bak.name}: {len(issues)} ===")
            for it in issues[:20]:
                print(f"  {it['kind']}\t{it['file']}")
                if "before" in it:
                    print(f"    before: {it.get('before','')[:100]}")
                    print(f"    after:  {it.get('after','')[:100]}")
                else:
                    print(f"    hdr before: {it.get('before_hdr','')[:80]}")
                    print(f"    hdr after:  {it.get('after_hdr','')[:80]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
