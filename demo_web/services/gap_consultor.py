"""Tenant GlobalGAP consultor: etiquetas (clientes), ámbitos (huerto+especie) y panel."""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

_PLANTILLAS = ("cerezos", "ciruelos")
_ESPECIE_LABEL = {"cerezos": "Cerezos", "ciruelos": "Ciruelos"}


@dataclass
class GapAmbitoCtx:
    etiqueta_id: int
    ambito_id: int
    etiqueta_nombre: str
    huerto: str
    especie_cultivo: str
    plantilla: str
    especie_key: str
    docs_root: Path
    razon_social: str
    direccion: str


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return s[:80] or "item"


def _docs_base() -> Path:
    import os

    root = (os.environ.get("ERP_GLOBALGAP_DOCS") or "/root/globalgap/docs").strip()
    return Path(root)


def _static_gap_docs() -> Path:
    import os

    for raw in (
        os.environ.get("ERP_GAP_DOCS"),
        "/root/demo-web/demo_web/static/globalgap/docs",
        str(Path(__file__).resolve().parents[1] / "static" / "globalgap" / "docs"),
    ):
        if raw:
            p = Path(raw)
            if p.is_dir():
                return p
    return Path(__file__).resolve().parents[1] / "static" / "globalgap" / "docs"


def migrar_gap_consultor(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS gap_etiquetas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            notas TEXT DEFAULT '',
            activo INTEGER DEFAULT 1,
            creado_en TEXT DEFAULT ''
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS gap_ambitos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            etiqueta_id INTEGER NOT NULL,
            nombre_huerto TEXT NOT NULL,
            slug TEXT NOT NULL,
            especie_cultivo TEXT NOT NULL,
            plantilla_docs TEXT DEFAULT 'cerezos',
            razon_social TEXT DEFAULT '',
            direccion TEXT DEFAULT '',
            logo_relpath TEXT DEFAULT '',
            activo INTEGER DEFAULT 1,
            creado_en TEXT DEFAULT '',
            UNIQUE(etiqueta_id, slug),
            FOREIGN KEY (etiqueta_id) REFERENCES gap_etiquetas(id)
        )"""
    )
    gap_tables = (
        "gap_documentos",
        "gap_evaluacion",
        "gap_nc",
        "gap_pppl",
        "gap_capacitaciones",
        "gap_cosecha",
        "gap_agua",
        "gap_calibracion",
        "gap_orden_aplicacion",
    )
    for tbl in gap_tables:
        try:
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()}
        except sqlite3.OperationalError:
            continue
        if "ambito_id" not in cols:
            conn.execute(f"ALTER TABLE {tbl} ADD COLUMN ambito_id INTEGER")
        if "etiqueta_id" not in cols:
            conn.execute(f"ALTER TABLE {tbl} ADD COLUMN etiqueta_id INTEGER")
    conn.commit()


def list_etiquetas(conn: sqlite3.Connection, *, activos_only: bool = True) -> list[dict]:
    migrar_gap_consultor(conn)
    q = "SELECT id, nombre, slug, notas, activo, creado_en FROM gap_etiquetas"
    if activos_only:
        q += " WHERE activo=1"
    q += " ORDER BY nombre COLLATE NOCASE"
    rows = conn.execute(q).fetchall()
    out = []
    for r in rows:
        eid = int(r[0])
        ambitos = list_ambitos(conn, eid, activos_only=activos_only)
        out.append(
            {
                "id": eid,
                "nombre": r[1],
                "slug": r[2],
                "notas": r[3] or "",
                "activo": int(r[4] or 0),
                "creado_en": r[5] or "",
                "ambitos": ambitos,
                "n_ambitos": len(ambitos),
            }
        )
    return out


def get_etiqueta(conn: sqlite3.Connection, etiqueta_id: int) -> dict | None:
    migrar_gap_consultor(conn)
    r = conn.execute(
        "SELECT id, nombre, slug, notas, activo, creado_en FROM gap_etiquetas WHERE id=?",
        (int(etiqueta_id),),
    ).fetchone()
    if not r:
        return None
    return {
        "id": int(r[0]),
        "nombre": r[1],
        "slug": r[2],
        "notas": r[3] or "",
        "activo": int(r[4] or 0),
        "creado_en": r[5] or "",
    }


def list_ambitos(
    conn: sqlite3.Connection,
    etiqueta_id: int,
    *,
    activos_only: bool = True,
) -> list[dict]:
    migrar_gap_consultor(conn)
    q = """SELECT id, etiqueta_id, nombre_huerto, slug, especie_cultivo, plantilla_docs,
                  razon_social, direccion, logo_relpath, activo, creado_en
           FROM gap_ambitos WHERE etiqueta_id=?"""
    if activos_only:
        q += " AND activo=1"
    q += " ORDER BY nombre_huerto COLLATE NOCASE, especie_cultivo COLLATE NOCASE"
    rows = conn.execute(q, (int(etiqueta_id),)).fetchall()
    return [_ambito_row(r) for r in rows]


def get_ambito(conn: sqlite3.Connection, ambito_id: int) -> dict | None:
    migrar_gap_consultor(conn)
    r = conn.execute(
        """SELECT id, etiqueta_id, nombre_huerto, slug, especie_cultivo, plantilla_docs,
                  razon_social, direccion, logo_relpath, activo, creado_en
           FROM gap_ambitos WHERE id=?""",
        (int(ambito_id),),
    ).fetchone()
    if not r:
        return None
    return _ambito_row(r)


def _ambito_row(r) -> dict:
    return {
        "id": int(r[0]),
        "etiqueta_id": int(r[1]),
        "nombre_huerto": r[2],
        "slug": r[3],
        "especie_cultivo": r[4],
        "plantilla_docs": r[5] or "cerezos",
        "razon_social": r[6] or "",
        "direccion": r[7] or "",
        "logo_relpath": r[8] or "",
        "activo": int(r[9] or 0),
        "creado_en": r[10] or "",
        "label": f"{r[2]} · {r[4]}",
    }


def ambito_docs_dir(etiqueta_slug: str, ambito_slug: str) -> Path:
    return _docs_base() / _slugify(etiqueta_slug) / _slugify(ambito_slug)


def _write_membrete_json(path: Path, razon: str, direccion: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"razon_social": razon, "direccion": direccion},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _clone_plantilla_docs(dest: Path, plantilla: str) -> None:
    src = _static_gap_docs() / plantilla
    static_root = _static_gap_docs()
    if not src.is_dir():
        return
    dest.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dest / item.name
        if item.is_dir():
            if target.exists():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
    for name in (f"catalogo_{plantilla}.json", f"doc_checklist_map_{plantilla}.json"):
        src_file = static_root / name
        if src_file.is_file():
            shutil.copy2(src_file, dest / name)


def create_etiqueta(conn: sqlite3.Connection, nombre: str, notas: str = "") -> tuple[bool, str, int | None]:
    migrar_gap_consultor(conn)
    nombre = (nombre or "").strip()
    if not nombre:
        return False, "Indique el nombre del cliente.", None
    slug = _slugify(nombre)
    base = slug
    n = 1
    while conn.execute("SELECT 1 FROM gap_etiquetas WHERE slug=?", (slug,)).fetchone():
        n += 1
        slug = f"{base}-{n}"
    try:
        cur = conn.execute(
            "INSERT INTO gap_etiquetas (nombre, slug, notas, activo, creado_en) VALUES (?,?,?,1,?)",
            (nombre, slug, (notas or "").strip(), date.today().isoformat()),
        )
        conn.commit()
        return True, f"Cliente «{nombre}» creado.", int(cur.lastrowid)
    except sqlite3.IntegrityError:
        return False, "Ya existe un cliente con ese identificador.", None


def create_ambito(
    conn: sqlite3.Connection,
    *,
    etiqueta_id: int,
    nombre_huerto: str,
    especie_cultivo: str,
    plantilla_docs: str,
    razon_social: str = "",
    direccion: str = "",
) -> tuple[bool, str, int | None]:
    migrar_gap_consultor(conn)
    etiqueta = get_etiqueta(conn, etiqueta_id)
    if not etiqueta:
        return False, "Cliente no encontrado.", None
    huerto = (nombre_huerto or "").strip()
    especie = (especie_cultivo or "").strip()
    plantilla = (plantilla_docs or "cerezos").strip().lower()
    if plantilla not in _PLANTILLAS:
        plantilla = "cerezos"
    if not huerto or not especie:
        return False, "Huerto y especie son obligatorios.", None
    slug = _slugify(f"{huerto}-{especie}")
    base = slug
    n = 1
    while conn.execute(
        "SELECT 1 FROM gap_ambitos WHERE etiqueta_id=? AND slug=?",
        (int(etiqueta_id), slug),
    ).fetchone():
        n += 1
        slug = f"{base}-{n}"
    cur = conn.execute(
        """INSERT INTO gap_ambitos
           (etiqueta_id, nombre_huerto, slug, especie_cultivo, plantilla_docs,
            razon_social, direccion, activo, creado_en)
           VALUES (?,?,?,?,?,?,?,1,?)""",
        (
            int(etiqueta_id),
            huerto,
            slug,
            especie,
            plantilla,
            (razon_social or "").strip(),
            (direccion or "").strip(),
            date.today().isoformat(),
        ),
    )
    conn.commit()
    ambito_id = int(cur.lastrowid)
    docs = ambito_docs_dir(etiqueta["slug"], slug)
    _clone_plantilla_docs(docs, plantilla)
    _write_membrete_json(docs / "membrete.json", razon_social or etiqueta["nombre"], direccion)
    return True, f"Ámbito «{huerto} · {especie}» creado.", ambito_id


def especie_key_for_ambito(ambito_id: int) -> str:
    return f"__ambito_{int(ambito_id)}__"


def load_ambito_ctx(conn: sqlite3.Connection, ambito_id: int) -> GapAmbitoCtx | None:
    amb = get_ambito(conn, ambito_id)
    if not amb:
        return None
    et = get_etiqueta(conn, amb["etiqueta_id"])
    if not et:
        return None
    docs = ambito_docs_dir(et["slug"], amb["slug"])
    return GapAmbitoCtx(
        etiqueta_id=int(et["id"]),
        ambito_id=int(amb["id"]),
        etiqueta_nombre=et["nombre"],
        huerto=amb["nombre_huerto"],
        especie_cultivo=amb["especie_cultivo"],
        plantilla=amb["plantilla_docs"],
        especie_key=especie_key_for_ambito(int(amb["id"])),
        docs_root=docs,
        razon_social=amb["razon_social"] or et["nombre"],
        direccion=amb["direccion"] or "",
    )


def panel_resumen(conn: sqlite3.Connection) -> dict:
    migrar_gap_consultor(conn)
    etiquetas = list_etiquetas(conn)
    n_amb = sum(e["n_ambitos"] for e in etiquetas)
    nc_abiertas = 0
    try:
        nc_abiertas = int(
            conn.execute(
                "SELECT COUNT(*) FROM gap_nc WHERE estado='Abierta' AND ambito_id IS NOT NULL"
            ).fetchone()[0]
            or 0
        )
    except sqlite3.OperationalError:
        pass
    alertas = 0
    cards = []
    cards_by_ambito: dict[int, dict] = {}
    for et in etiquetas:
        for amb in et["ambitos"]:
            pct = _ambito_checklist_pct(conn, amb["id"], especie_key_for_ambito(amb["id"]))
            nc = _ambito_nc_abiertas(conn, amb["id"])
            alertas += nc
            card = {
                "etiqueta_id": et["id"],
                "etiqueta_nombre": et["nombre"],
                "ambito_id": amb["id"],
                "label": f"{amb['nombre_huerto']} · {amb['especie_cultivo']}",
                "pct_checklist": pct,
                "nc_abiertas": nc,
            }
            cards.append(card)
            cards_by_ambito[int(amb["id"])] = card
    return {
        "n_clientes": len(etiquetas),
        "n_ambitos": n_amb,
        "nc_abiertas": nc_abiertas,
        "alertas": alertas,
        "etiquetas": etiquetas,
        "cards": cards,
        "cards_by_ambito": cards_by_ambito,
    }


def _ambito_checklist_pct(conn: sqlite3.Connection, ambito_id: int, especie_key: str) -> float:
    try:
        total = conn.execute("SELECT COUNT(*) FROM gap_checklist").fetchone()[0] or 0
        if not total:
            return 0.0
        cumple = conn.execute(
            """SELECT COUNT(*) FROM gap_evaluacion e
               JOIN gap_checklist c ON c.id=e.checklist_id
               WHERE COALESCE(e.especie,'')=? AND e.estado='Cumple' AND e.ambito_id=?""",
            (especie_key, int(ambito_id)),
        ).fetchone()[0]
        return round(100.0 * float(cumple or 0) / float(total), 1)
    except sqlite3.OperationalError:
        return 0.0


def _ambito_nc_abiertas(conn: sqlite3.Connection, ambito_id: int) -> int:
    try:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM gap_nc WHERE estado='Abierta' AND ambito_id=?",
                (int(ambito_id),),
            ).fetchone()[0]
            or 0
        )
    except sqlite3.OperationalError:
        return 0


def sql_ambito_clause(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    return f"({prefix}ambito_id IS NULL OR {prefix}ambito_id=?)"


def bind_ambito_on_write(conn: sqlite3.Connection, ambito_id: int, etiqueta_id: int) -> None:
    """Reservado para inserts posteriores desde globalgap."""
    migrar_gap_consultor(conn)
