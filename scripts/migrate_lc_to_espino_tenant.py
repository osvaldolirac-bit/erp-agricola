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
RAZON_SOCIAL_ESPINO = "El Espino"
GASTOS_ESPINO_DOC_PREFIX = "GE"
TIPO_GASTO_DEFAULT = "Sin clasificar"
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


def _migrate_compras_tesoreria(
    src: sqlite3.Connection,
    dst: sqlite3.Connection,
) -> tuple[int, int, int, int]:
    """Facturas El Espino + abonos (por pagar e historial auditable tesorería)."""
    _delete_all(dst, "facturas_abonos")
    _delete_all(dst, "facturas")

    src_cols = [c for c in _columns(src, "facturas") if c in _columns(dst, "facturas")]
    if not src_cols or "id" not in src_cols:
        return 0, 0, 0, 0

    rows = src.execute(
        f"""SELECT {", ".join(src_cols)} FROM facturas
            WHERE TRIM(COALESCE(razon_social, ''))=?
            ORDER BY id""",
        (RAZON_SOCIAL_ESPINO,),
    ).fetchall()
    if not rows:
        return 0, 0, 0, 0

    ins_cols = [c for c in src_cols if c != "id"]
    ph = ", ".join("?" for _ in ins_cols)
    ins = f"INSERT INTO facturas ({', '.join(ins_cols)}) VALUES ({ph})"
    id_map: dict[int, int] = {}
    n_main = 0
    n_imput = 0
    for row in rows:
        data = dict(zip(src_cols, row))
        old_id = int(data.pop("id"))
        nro = str(data.get("nro_documento") or "")
        if "centro_costo" in data:
            data["centro_costo"] = _remap_cc(data.get("centro_costo"))
        cur = dst.execute(ins, [data[c] for c in ins_cols])
        id_map[old_id] = int(cur.lastrowid)
        if nro.endswith("_P"):
            n_imput += 1
        else:
            n_main += 1

    n_abonos = 0
    if id_map and _table_exists(src, "facturas_abonos") and _table_exists(dst, "facturas_abonos"):
        ab_cols = [
            c for c in _columns(src, "facturas_abonos") if c in _columns(dst, "facturas_abonos")
        ]
        if "factura_id" in ab_cols:
            placeholders = ", ".join("?" for _ in id_map)
            ab_rows = src.execute(
                f"""SELECT {", ".join(ab_cols)} FROM facturas_abonos
                    WHERE factura_id IN ({placeholders})
                    ORDER BY id""",
                tuple(id_map),
            ).fetchall()
            ab_ins_cols = [c for c in ab_cols if c != "id"]
            ab_ph = ", ".join("?" for _ in ab_ins_cols)
            ab_ins = f"INSERT INTO facturas_abonos ({', '.join(ab_ins_cols)}) VALUES ({ab_ph})"
            for ab_row in ab_rows:
                data = dict(zip(ab_cols, ab_row))
                data.pop("id", None)
                old_fid = int(data["factura_id"])
                new_fid = id_map.get(old_fid)
                if not new_fid:
                    continue
                data["factura_id"] = new_fid
                dst.execute(ab_ins, [data[c] for c in ab_ins_cols])
                n_abonos += 1

    n_pend = dst.execute(
        """SELECT COUNT(*) FROM facturas
           WHERE estado='Pendiente' AND nro_documento NOT LIKE '%_P' AND monto_total > 0"""
    ).fetchone()[0]
    return n_main, n_imput, n_abonos, int(n_pend)


def _infer_tipo_gasto_espino(item: str | None, documento: str | None) -> str:
    """Clasificación heurística para rubro en matriz de costos."""
    txt = f"{item or ''} {documento or ''}".upper()
    if any(k in txt for k in ("ARRIENDO", "MARIA PAOLA", "TORRES ORTIZ")):
        return "Arriendos"
    if any(
        k in txt
        for k in (
            "CGE",
            "CONSUMO ELÉCTRICO",
            "CONSUMO ELECTRICO",
            "ELECTRIC",
            "ENERGÍA",
            "ENERGIA",
        )
    ):
        return "Energía eléctrica"
    if any(
        k in txt
        for k in (
            "PODA",
            "SUELDO",
            "FINIQUITO",
            "IMPOSICION",
            "IMPOSICI",
            "INDEMNIZ",
            "AGUINALDO",
            "ANTICIPO",
            "REEMBOLSO",
            "DUILIO",
            "ALEJANDRA",
            "CARLOS ZAVALA",
            "DANIXA",
            "HECHURA",
            "REPLANTE",
            "AMONTON",
            "APILAR",
            "SARMIENTO",
            "SUPERVISION",
        )
    ):
        return "Contratistas externos"
    if any(k in txt for k in ("MAQUINARIA", "TRACTOR", "TRASLADO DE BOMBA", "CAMBIO DE BOMBA")):
        return "Servicios maq. externa"
    if any(
        k in txt
        for k in (
            "TOPAGRO",
            "COAGRA",
            "MACAL",
            "FITOSANIT",
            "AGROQUÍM",
            "AGROQUIM",
            "NEXUS",
            "KONAN",
            "PIRIPROXIFEN",
            "NORDOX",
            "COBRE",
            "FASCINATE",
            "ALION",
            "PODASTIK",
            "ACABAN",
            "UREA",
            "NITRATO",
            "SYNCRON",
            "BIOIL",
            "DORMEX",
            "FERMACO",
        )
    ):
        return "Agroquímicos"
    if any(k in txt for k in ("FERRE", "ELECTROCOM", "CABLE", "PERNO", "PALA", "VITEL", "DAB,")):
        return "Repuestos y talleres"
    if any(
        k in txt
        for k in (
            "NOTARIA",
            "NOTARÍ",
            "CONTADOR",
            "AUDITORIA",
            "AUDITORÍA",
            "COMISIÓN",
            "COMISION",
            "INTERÉS",
            "INTERES",
            "GASTOS NOTARIALES",
        )
    ):
        return "Gastos administración y asesorías"
    if any(k in txt for k in ("RIEGO", "SONDA", "MOTOR 4", "EMPAR", "POZO", "HIDRÁUL", "HIDRaul")):
        return "Repuestos y talleres"
    if any(k in txt for k in ("HELADA", "CACERES", "ZUÑIGA", "ZUNIGA")):
        return "Contratistas externos"
    return TIPO_GASTO_DEFAULT


def _migrate_gastos_espino_costos(
    src: sqlite3.Connection,
    dst: sqlite3.Connection,
) -> tuple[int, float, int]:
    """gastos_espino (LC) → facturas GE-* + imputación _P en Cerezos (Costos)."""
    if not _table_exists(src, "gastos_espino") or not _table_exists(dst, "facturas"):
        return 0, 0.0, 0

    # Evitar doble conteo: quitar imputaciones _P de compras; gastos_espino es la fuente (~61M).
    dst.execute("DELETE FROM facturas WHERE nro_documento GLOB 'GE-*'")
    dst.execute(
        """DELETE FROM facturas
           WHERE nro_documento LIKE '%\_P' ESCAPE '\\'
             AND nro_documento NOT GLOB 'GE-*'"""
    )

    rows = src.execute(
        """SELECT id, fecha, documento, item, monto
           FROM gastos_espino
           WHERE ABS(COALESCE(monto, 0)) > 0.01
           ORDER BY id"""
    ).fetchall()
    if not rows:
        return 0, 0.0, 0

    n = 0
    total = 0.0
    for gid, fecha, documento, item, monto in rows:
        monto_f = float(monto or 0)
        if monto_f <= 0.01:
            continue
        doc_base = f"{GASTOS_ESPINO_DOC_PREFIX}-{int(gid)}"
        prov = (str(documento or "").strip() or "S/N")[:120]
        concepto = (str(item or "").strip() or "Gasto El Espino")[:500]
        tg = _infer_tipo_gasto_espino(concepto, prov)
        fv = str(fecha)[:10] if fecha else None

        dst.execute(
            """INSERT INTO facturas
               (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, monto_neto,
                estado, tipo, concepto, razon_social, tipo_gasto, folio_interno)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                doc_base,
                prov,
                fv,
                fv,
                monto_f,
                monto_f,
                "Pagado",
                "Gasto Varios",
                concepto,
                RAZON_SOCIAL_ESPINO,
                tg,
                prov if not str(prov).upper().startswith("INT-") else "",
            ),
        )
        dst.execute(
            """INSERT INTO facturas
               (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total,
                tipo, centro_costo, monto_imputado, concepto, razon_social, tipo_gasto)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                f"{doc_base}_P",
                prov,
                fv,
                fv,
                0.0,
                "Gasto Varios",
                CC_TARGET,
                monto_f,
                concepto,
                RAZON_SOCIAL_ESPINO,
                tg,
            ),
        )
        n += 1
        total += monto_f

    n_imput = dst.execute(
        """SELECT COUNT(*) FROM facturas
           WHERE nro_documento LIKE ? AND ABS(COALESCE(monto_imputado,0))>0.01""",
        (f"{GASTOS_ESPINO_DOC_PREFIX}-%_P",),
    ).fetchone()[0]
    return n, total, int(n_imput)


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


def migrate_compras_tesoreria(*, dry_run: bool = False) -> dict[str, int | str]:
    """Solo compras (facturas) y tesorería (abonos) El Espino desde LC."""
    if not LC_DB.is_file():
        raise SystemExit(f"LC DB not found: {LC_DB}")
    if not ESPINO_DB.is_file():
        raise SystemExit(f"Espino DB not found: {ESPINO_DB}")

    stats: dict[str, int | str] = {}
    src = sqlite3.connect(LC_DB)
    try:
        stats["facturas_src"] = src.execute(
            """SELECT COUNT(*) FROM facturas
               WHERE TRIM(COALESCE(razon_social, ''))=?""",
            (RAZON_SOCIAL_ESPINO,),
        ).fetchone()[0]
        stats["facturas_main_src"] = src.execute(
            """SELECT COUNT(*) FROM facturas
               WHERE TRIM(COALESCE(razon_social, ''))=?
                 AND nro_documento NOT LIKE '%_P'""",
            (RAZON_SOCIAL_ESPINO,),
        ).fetchone()[0]
        stats["abonos_src"] = src.execute(
            """SELECT COUNT(*) FROM facturas_abonos a
               JOIN facturas f ON f.id=a.factura_id
               WHERE TRIM(COALESCE(f.razon_social, ''))=?""",
            (RAZON_SOCIAL_ESPINO,),
        ).fetchone()[0]
        stats["pendientes_src"] = src.execute(
            """SELECT COUNT(*) FROM facturas
               WHERE TRIM(COALESCE(razon_social, ''))=?
                 AND estado='Pendiente' AND nro_documento NOT LIKE '%_P' AND monto_total > 0""",
            (RAZON_SOCIAL_ESPINO,),
        ).fetchone()[0]
    finally:
        src.close()

    if dry_run:
        stats["dry_run"] = 1
        return stats

    backup = _backup_db(ESPINO_DB)
    stats["backup"] = str(backup)

    src = sqlite3.connect(LC_DB)
    dst = sqlite3.connect(ESPINO_DB)
    try:
        dst.execute("PRAGMA foreign_keys=OFF")
        n_main, n_imput, n_abonos, n_pend = _migrate_compras_tesoreria(src, dst)
        stats["facturas_main"] = n_main
        stats["facturas_imputacion"] = n_imput
        stats["facturas_abonos"] = n_abonos
        stats["tesoreria_pendientes"] = n_pend
        dst.commit()
    except Exception:
        dst.rollback()
        raise
    finally:
        src.close()
        dst.close()
    return stats


def migrate_gastos_espino_costos(*, dry_run: bool = False) -> dict[str, int | str | float]:
    """Módulo Espino LC (gastos_espino) → imputaciones Costos tenant (~61M)."""
    if not LC_DB.is_file():
        raise SystemExit(f"LC DB not found: {LC_DB}")
    if not ESPINO_DB.is_file():
        raise SystemExit(f"Espino DB not found: {ESPINO_DB}")

    stats: dict[str, int | str | float] = {}
    src = sqlite3.connect(LC_DB)
    try:
        stats["gastos_espino_src"] = src.execute(
            "SELECT COUNT(*) FROM gastos_espino WHERE ABS(COALESCE(monto,0))>0.01"
        ).fetchone()[0]
        stats["monto_espino_src"] = round(
            float(
                src.execute(
                    "SELECT COALESCE(SUM(monto),0) FROM gastos_espino WHERE ABS(COALESCE(monto,0))>0.01"
                ).fetchone()[0]
                or 0
            ),
            2,
        )
    finally:
        src.close()

    if dry_run:
        stats["dry_run"] = 1
        return stats

    backup = _backup_db(ESPINO_DB)
    stats["backup"] = str(backup)

    src = sqlite3.connect(LC_DB)
    dst = sqlite3.connect(ESPINO_DB)
    try:
        dst.execute("PRAGMA foreign_keys=OFF")
        n, total, n_imput = _migrate_gastos_espino_costos(src, dst)
        stats["gastos_espino"] = n
        stats["monto_imputado_costos"] = round(total, 2)
        stats["imputaciones_ge"] = n_imput
        dst.commit()
    except Exception:
        dst.rollback()
        raise
    finally:
        src.close()
        dst.close()
    return stats


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
            stats["facturas_src"] = src.execute(
                """SELECT COUNT(*) FROM facturas
                   WHERE TRIM(COALESCE(razon_social, ''))=?""",
                (RAZON_SOCIAL_ESPINO,),
            ).fetchone()[0]
            stats["abonos_src"] = src.execute(
                """SELECT COUNT(*) FROM facturas_abonos a
                   JOIN facturas f ON f.id=a.factura_id
                   WHERE TRIM(COALESCE(f.razon_social, ''))=?""",
                (RAZON_SOCIAL_ESPINO,),
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
        n_main, n_imput, n_abonos, n_pend = _migrate_compras_tesoreria(src, dst)
        stats["facturas_main"] = n_main
        stats["facturas_imputacion"] = n_imput
        stats["facturas_abonos"] = n_abonos
        stats["tesoreria_pendientes"] = n_pend
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
    parser.add_argument(
        "--solo-compras-tesoreria",
        action="store_true",
        help="Solo facturas El Espino y abonos (compras + tesorería); no toca GAP/bodega/etc.",
    )
    parser.add_argument(
        "--solo-gastos-espino-costos",
        action="store_true",
        help="Módulo Espino LC (gastos_espino ~61M) → imputaciones Costos en Cerezos.",
    )
    args = parser.parse_args()
    if args.solo_gastos_espino_costos:
        stats = migrate_gastos_espino_costos(dry_run=args.dry_run)
        print("Migración gastos Espino LC → Costos tenant El Espino")
    elif args.solo_compras_tesoreria:
        stats = migrate_compras_tesoreria(dry_run=args.dry_run)
        print("Migración compras/tesorería LC → tenant El Espino")
    else:
        stats = migrate(dry_run=args.dry_run)
        print("Migración LC → tenant El Espino")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
