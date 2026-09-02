#!/usr/bin/env python3
"""Migra datos LC (módulo Espino) → tenant El Espino. Solo escribe en erp_espino.db."""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

LC_DB = Path(os.environ.get("ERP_LC_DB", "/root/erp_concepcion_v6.db"))
ESPINO_DB = Path(os.environ.get("ERP_ESPINO_DB", "/root/espino/erp_espino.db"))
DOCS_ROOT = Path(
    os.environ.get(
        "ERP_GAP_DOCS",
        "/root/demo-web/demo_web/static/globalgap/docs",
    )
)

CC_TARGET = "Cerezos"
CC_SOURCES = frozenset({"EL ESPINO", "NOGALES APARICION", "NOGALES CRUZ DEL SUR"})
GAP_ESPECIE = "EL ESPINO"
SUPERFICIE_HA = 7.0
PRORRATEO_PCT = 100.0

PRODUCTOS_BODEGA = (
    "PIRIPROXIFEN",
    "ACEITE BIOIL SPRAY",
    "COBRE NORDOX",
)


def _es_producto_bodega_espino(nombre: str) -> bool:
    n = (nombre or "").upper().strip()
    if n in {p.upper() for p in PRODUCTOS_BODEGA}:
        return True
    if "PIRIPROXIFEN" in n:
        return True
    if "BIOIL" in n and "SPRAY" in n:
        return True
    if n.startswith("COBRE") or " COBRE" in f" {n}":
        return True
    return False


def _remap_cc(val: str | None) -> str | None:
    if val is None:
        return None
    v = str(val).strip()
    if v.upper() in {c.upper() for c in CC_SOURCES}:
        return CC_TARGET
    return v


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _delete_all(conn: sqlite3.Connection, table: str) -> None:
    if _table_exists(conn, table):
        conn.execute(f"DELETE FROM {table}")


def _copy_table(
    src: sqlite3.Connection,
    dst: sqlite3.Connection,
    table: str,
    *,
    where: str = "",
    params: tuple = (),
    transforms: dict[str, callable] | None = None,
    skip_id: bool = False,
) -> int:
    if not _table_exists(src, table) or not _table_exists(dst, table):
        return 0
    src_cols = _columns(src, table)
    dst_cols = _columns(dst, table)
    cols = [c for c in src_cols if c in dst_cols and not (skip_id and c == "id")]
    if not cols:
        return 0
    q = f"SELECT {', '.join(cols)} FROM {table}"
    if where:
        q += f" WHERE {where}"
    rows = src.execute(q, params).fetchall()
    if not rows:
        return 0
    transforms = transforms or {}
    ph = ", ".join("?" for _ in cols)
    ins = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({ph})"
    n = 0
    for row in rows:
        data = dict(zip(cols, row))
        for col, fn in transforms.items():
            if col in data:
                data[col] = fn(data[col])
        dst.execute(ins, [data[c] for c in cols])
        n += 1
    return n


def _sync_users(src: sqlite3.Connection, dst: sqlite3.Connection) -> int:
    cols = [c for c in _columns(src, "usuarios") if c in _columns(dst, "usuarios")]
    if "email" not in cols or "password" not in cols:
        return 0
    rows = src.execute(
        f"SELECT {', '.join(cols)} FROM usuarios ORDER BY lower(email)"
    ).fetchall()
    _delete_all(dst, "usuarios")
    ph = ", ".join("?" for _ in cols)
    dst.executemany(
        f"INSERT INTO usuarios ({', '.join(cols)}) VALUES ({ph})",
        rows,
    )
    return len(rows)


def _migrate_proveedores(src: sqlite3.Connection, dst: sqlite3.Connection) -> int:
    _delete_all(dst, "maestra_proveedores")
    return _copy_table(src, dst, "maestra_proveedores")


def _migrate_inventario(src: sqlite3.Connection, dst: sqlite3.Connection) -> int:
    _delete_all(dst, "inventario")
    _delete_all(dst, "movimientos")
    inv_cols = [c for c in _columns(src, "inventario") if c in _columns(dst, "inventario")]
    if "producto" not in inv_cols:
        return 0
    rows = src.execute(f"SELECT {', '.join(inv_cols)} FROM inventario").fetchall()
    n = 0
    ph = ", ".join("?" for _ in inv_cols)
    ins = f"INSERT INTO inventario ({', '.join(inv_cols)}) VALUES ({ph})"
    for row in rows:
        data = dict(zip(inv_cols, row))
        if not _es_producto_bodega_espino(str(data.get("producto") or "")):
            continue
        data["stock"] = 0
        dst.execute(ins, [data[c] for c in inv_cols])
        n += 1
    return n


def _migrate_prorrateo(dst: sqlite3.Connection) -> None:
    _delete_all(dst, "prorrateo_cc")
    dst.execute(
        "INSERT INTO prorrateo_cc (centro_costo, porcentaje, superficie_ha) VALUES (?,?,?)",
        (CC_TARGET, PRORRATEO_PCT, SUPERFICIE_HA),
    )


def _migrate_gap_checklist(src: sqlite3.Connection, dst: sqlite3.Connection) -> int:
    _delete_all(dst, "gap_checklist")
    return _copy_table(src, dst, "gap_checklist")


def _migrate_gap_pppl(src: sqlite3.Connection, dst: sqlite3.Connection) -> int:
    _delete_all(dst, "gap_pppl")
    return _copy_table(
        src,
        dst,
        "gap_pppl",
        where="COALESCE(especie, '') IN (?, ?)",
        params=(GAP_ESPECIE, "General"),
    )


def _migrate_gap_documentos(src: sqlite3.Connection, dst: sqlite3.Connection) -> tuple[int, dict[int, int]]:
    _delete_all(dst, "gap_doc_checklist")
    _delete_all(dst, "gap_documentos")
    src_cols = [c for c in _columns(src, "gap_documentos") if c in _columns(dst, "gap_documentos")]
    if not src_cols:
        return 0, {}
    rows = src.execute(
        f"SELECT {', '.join(src_cols)} FROM gap_documentos WHERE COALESCE(especie, '')=?",
        (GAP_ESPECIE,),
    ).fetchall()
    id_map: dict[int, int] = {}
    ins_cols = [c for c in src_cols if c != "id"]
    ph = ", ".join("?" for _ in ins_cols)
    ins = f"INSERT INTO gap_documentos ({', '.join(ins_cols)}) VALUES ({ph})"
    for row in rows:
        data = dict(zip(src_cols, row))
        old_id = data.pop("id", None)
        cur = dst.execute(ins, [data[c] for c in ins_cols])
        if old_id is not None:
            id_map[int(old_id)] = int(cur.lastrowid)
    return len(rows), id_map


def _migrate_gap_doc_checklist(
    src: sqlite3.Connection,
    dst: sqlite3.Connection,
    doc_id_map: dict[int, int],
) -> int:
    if not doc_id_map:
        return 0
    src_cols = [c for c in _columns(src, "gap_doc_checklist") if c in _columns(dst, "gap_doc_checklist")]
    if not src_cols or "documento_id" not in src_cols:
        return 0
    placeholders = ", ".join("?" for _ in doc_id_map)
    rows = src.execute(
        f"""SELECT {', '.join(src_cols)} FROM gap_doc_checklist
            WHERE documento_id IN ({placeholders})""",
        tuple(doc_id_map),
    ).fetchall()
    ins_cols = [c for c in src_cols if c != "id"]
    ph = ", ".join("?" for _ in ins_cols)
    ins = f"INSERT INTO gap_doc_checklist ({', '.join(ins_cols)}) VALUES ({ph})"
    n = 0
    for row in rows:
        data = dict(zip(src_cols, row))
        old_doc = int(data["documento_id"])
        new_doc = doc_id_map.get(old_doc)
        if not new_doc:
            continue
        data["documento_id"] = new_doc
        if "especie" in data and data["especie"]:
            data["especie"] = GAP_ESPECIE
        dst.execute(ins, [data[c] for c in ins_cols])
        n += 1
    return n


def _migrate_gap_evaluacion(src: sqlite3.Connection, dst: sqlite3.Connection) -> int:
    _delete_all(dst, "gap_evaluacion")
    return _copy_table(
        src,
        dst,
        "gap_evaluacion",
        where="COALESCE(especie, '')=?",
        params=(GAP_ESPECIE,),
    )


def _migrate_gap_nc(src: sqlite3.Connection, dst: sqlite3.Connection) -> int:
    _delete_all(dst, "gap_nc")
    cuarteles = tuple(CC_SOURCES)
    ph = ", ".join("?" for _ in cuarteles)
    return _copy_table(
        src,
        dst,
        "gap_nc",
        where=f"COALESCE(especie, '')=? OR UPPER(TRIM(cuartel)) IN ({ph})",
        params=(GAP_ESPECIE, *{c.upper() for c in cuarteles}),
        transforms={"cuartel": _remap_cc},
    )


def _migrate_gap_capacitaciones(src: sqlite3.Connection, dst: sqlite3.Connection) -> int:
    _delete_all(dst, "gap_capacitaciones")
    if not _table_exists(src, "gap_capacitaciones"):
        return 0
    worker_ids = {
        r[0]
        for r in src.execute(
            "SELECT DISTINCT trabajador_id FROM gap_capacitaciones WHERE trabajador_id IS NOT NULL"
        ).fetchall()
    }
    if worker_ids and _table_exists(src, "personal") and _table_exists(dst, "personal"):
        _delete_all(dst, "personal")
        ph = ", ".join("?" for _ in worker_ids)
        cols = [c for c in _columns(src, "personal") if c in _columns(dst, "personal")]
        rows = src.execute(
            f"SELECT {', '.join(cols)} FROM personal WHERE id IN ({ph})",
            tuple(worker_ids),
        ).fetchall()
        iph = ", ".join("?" for _ in cols)
        dst.executemany(
            f"INSERT INTO personal ({', '.join(cols)}) VALUES ({iph})",
            rows,
        )
    return _copy_table(src, dst, "gap_capacitaciones")


def _migrate_gap_cosecha(src: sqlite3.Connection, dst: sqlite3.Connection) -> int:
    _delete_all(dst, "gap_cosecha")
    cuarteles = tuple(CC_SOURCES)
    ph = ", ".join("?" for _ in cuarteles)
    return _copy_table(
        src,
        dst,
        "gap_cosecha",
        where=f"COALESCE(especie, '')=? OR UPPER(TRIM(cuartel)) IN ({ph})",
        params=(GAP_ESPECIE, *{c.upper() for c in cuarteles}),
        transforms={"cuartel": _remap_cc},
    )


def _migrate_gap_agua_cal(src: sqlite3.Connection, dst: sqlite3.Connection) -> tuple[int, int]:
    _delete_all(dst, "gap_agua")
    _delete_all(dst, "gap_calibracion")
    n_agua = _copy_table(src, dst, "gap_agua")
    n_cal = _copy_table(src, dst, "gap_calibracion")
    return n_agua, n_cal


def _migrate_gantt(src: sqlite3.Connection, dst: sqlite3.Connection) -> tuple[int, int]:
    _delete_all(dst, "gantt_tareas")
    _delete_all(dst, "gantt_proyectos")
    src_cols = [c for c in _columns(src, "gantt_proyectos") if c in _columns(dst, "gantt_proyectos")]
    rows = src.execute(
        f"SELECT {', '.join(src_cols)} FROM gantt_proyectos WHERE COALESCE(especie, '')=?",
        (GAP_ESPECIE,),
    ).fetchall()
    proj_map: dict[int, int] = {}
    ins_cols = [c for c in src_cols if c != "id"]
    ph = ", ".join("?" for _ in ins_cols)
    ins = f"INSERT INTO gantt_proyectos ({', '.join(ins_cols)}) VALUES ({ph})"
    for row in rows:
        data = dict(zip(src_cols, row))
        old_id = data.pop("id", None)
        if "centro_costo" in data:
            data["centro_costo"] = _remap_cc(data["centro_costo"])
        cur = dst.execute(ins, [data[c] for c in ins_cols])
        if old_id is not None:
            proj_map[int(old_id)] = int(cur.lastrowid)
    n_tasks = 0
    if proj_map:
        tcols = [c for c in _columns(src, "gantt_tareas") if c in _columns(dst, "gantt_tareas")]
        t_ins_cols = [c for c in tcols if c != "id"]
        placeholders = ", ".join("?" for _ in proj_map)
        task_rows = src.execute(
            f"SELECT {', '.join(tcols)} FROM gantt_tareas WHERE proyecto_id IN ({placeholders})",
            tuple(proj_map),
        ).fetchall()
        tph = ", ".join("?" for _ in t_ins_cols)
        tins = f"INSERT INTO gantt_tareas ({', '.join(t_ins_cols)}) VALUES ({tph})"
        for trow in task_rows:
            tdata = dict(zip(tcols, trow))
            old_pid = int(tdata["proyecto_id"])
            new_pid = proj_map.get(old_pid)
            if not new_pid:
                continue
            tdata["proyecto_id"] = new_pid
            dst.execute(tins, [tdata[c] for c in t_ins_cols])
            n_tasks += 1
    return len(rows), n_tasks


def _migrate_libro_campo(src: sqlite3.Connection, dst: sqlite3.Connection) -> int:
    _delete_all(dst, "libro_campo")
    return _copy_table(
        src,
        dst,
        "libro_campo",
        where="UPPER(TRIM(sector))=?",
        params=("EL ESPINO",),
        transforms={"sector": lambda _: CC_TARGET, "especie": lambda _: CC_TARGET},
    )


def _verify_docs_on_disk() -> list[str]:
    notes: list[str] = []
    espino_dir = DOCS_ROOT / "espino"
    for name in ("catalogo_espino.json", "doc_checklist_map_espino.json"):
        p = DOCS_ROOT / name
        if not p.is_file():
            notes.append(f"WARN catalog missing: {p}")
    if not espino_dir.is_dir():
        notes.append(f"WARN docs dir missing: {espino_dir}")
    else:
        n_doc = len(list(espino_dir.rglob("*.doc")))
        notes.append(f"docs/espino: {n_doc} archivos .doc")
    return notes


def _backup_db(db: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = db.with_suffix(f".{stamp}.bak.db")
    shutil.copy2(db, dest)
    return dest


def migrate(*, dry_run: bool = False) -> dict[str, int | str]:
    if not LC_DB.is_file():
        raise SystemExit(f"LC DB not found: {LC_DB}")
    if not ESPINO_DB.is_file():
        raise SystemExit(f"Espino DB not found: {ESPINO_DB}")

    stats: dict[str, int | str] = {}
    if dry_run:
        src = sqlite3.connect(LC_DB)
        try:
            stats["proveedores_src"] = src.execute("SELECT COUNT(*) FROM maestra_proveedores").fetchone()[0]
            stats["gap_docs_src"] = src.execute(
                "SELECT COUNT(*) FROM gap_documentos WHERE COALESCE(especie,'')=?",
                (GAP_ESPECIE,),
            ).fetchone()[0]
            stats["libro_src"] = src.execute(
                "SELECT COUNT(*) FROM libro_campo WHERE UPPER(TRIM(sector))='EL ESPINO'"
            ).fetchone()[0]
        finally:
            src.close()
        stats["dry_run"] = 1
        return stats

    backup = _backup_db(ESPINO_DB)
    stats["backup"] = str(backup)

    src = sqlite3.connect(LC_DB)
    dst = sqlite3.connect(ESPINO_DB)
    try:
        dst.execute("PRAGMA foreign_keys=OFF")
        stats["usuarios"] = _sync_users(src, dst)
        stats["proveedores"] = _migrate_proveedores(src, dst)
        stats["inventario"] = _migrate_inventario(src, dst)
        _migrate_prorrateo(dst)
        stats["gap_checklist"] = _migrate_gap_checklist(src, dst)
        stats["gap_pppl"] = _migrate_gap_pppl(src, dst)
        n_docs, doc_map = _migrate_gap_documentos(src, dst)
        stats["gap_documentos"] = n_docs
        stats["gap_doc_checklist"] = _migrate_gap_doc_checklist(src, dst, doc_map)
        stats["gap_evaluacion"] = _migrate_gap_evaluacion(src, dst)
        stats["gap_nc"] = _migrate_gap_nc(src, dst)
        stats["gap_capacitaciones"] = _migrate_gap_capacitaciones(src, dst)
        stats["gap_cosecha"] = _migrate_gap_cosecha(src, dst)
        n_agua, n_cal = _migrate_gap_agua_cal(src, dst)
        stats["gap_agua"] = n_agua
        stats["gap_calibracion"] = n_cal
        n_proj, n_tasks = _migrate_gantt(src, dst)
        stats["gantt_proyectos"] = n_proj
        stats["gantt_tareas"] = n_tasks
        stats["libro_campo"] = _migrate_libro_campo(src, dst)
        dst.commit()
    except Exception:
        dst.rollback()
        raise
    finally:
        src.close()
        dst.close()

    for note in _verify_docs_on_disk():
        stats[note.split(":")[0].replace(" ", "_")] = note
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    stats = migrate(dry_run=args.dry_run)
    print("Migración LC → tenant El Espino")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
