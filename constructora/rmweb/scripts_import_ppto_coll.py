#!/usr/bin/env python3
"""Importa ppto+APU Excel a obra demo ficticia; borra otras obras."""
from __future__ import annotations

import re
import sqlite3
import unicodedata
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

import openpyxl

from rmweb import constructora as cst
from rmweb import core
from rmweb import obra_contrato as obractx

XLSX = Path("/tmp/ppto_casa_coll.xlsx")
DB = "/root/constructora/data/constructora_demo.db"
NOMBRE_FICTICIO = "Residencia Los Arrayanes — Demo Ppto/APU"
XLSX_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1E3LfjBs9Oa46gq_I1bhOAyxQGpgTugkI/export?format=xlsx"
)


def _f(v, default=0.0):
    if v is None or v == "":
        return float(default)
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("$", "").replace("%", "").replace(" ", "")
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return float(default)


def norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_ppto(ws):
    header = {
        "ubicacion": None,
        "propietario": None,
        "documento_cot": None,
        "duracion_meses": 10.0,
        "valor_uf": 36076.99,
        "gg_pct": 5.0,
        "utilidades_pct": 21.0,
        "iva_pct": 19.0,
    }
    for row in ws.iter_rows(values_only=True):
        a = ("" if row[0] is None else str(row[0])).strip().lower()
        b = row[1]
        if a.startswith("ubic"):
            header["ubicacion"] = ("" if b is None else str(b)).strip()
        elif a.startswith("mandant") or a.startswith("propiet"):
            header["propietario"] = ("" if b is None else str(b)).strip()
        elif a.startswith("documento"):
            header["documento_cot"] = ("" if b is None else str(b)).strip()
        elif a.startswith("duraci"):
            m = re.search(r"([\d.,]+)", str(b or ""))
            if m:
                header["duracion_meses"] = _f(m.group(1))
            for v in row[2:]:
                if isinstance(v, (int, float)) and float(v) > 1000:
                    header["valor_uf"] = float(v)
                    break
        lab = ("" if row[3] is None else str(row[3])).strip().lower()
        if lab == "gastos generales":
            header["gg_pct"] = _f(row[5]) * (100.0 if _f(row[5]) <= 1 else 1.0)
        elif lab == "utilidades":
            header["utilidades_pct"] = _f(row[5]) * (100.0 if _f(row[5]) <= 1 else 1.0)

    lines = []
    started = False
    for row in ws.iter_rows(values_only=True):
        item, partida, notas, und, cant, pu, total = (list(row) + [None] * 7)[:7]
        if str(item).strip().upper() == "ITEM" if item is not None else False:
            started = True
            continue
        if not started or item is None or str(item).strip() == "":
            continue
        lab = ("" if und is None else str(und)).strip().lower()
        if lab in ("sub total", "gastos generales", "utilidades", "neto", "iva", "total"):
            continue
        codigo = str(item).strip()
        detalle = ("" if partida is None else str(partida)).strip()
        if not detalle:
            continue
        notas_s = ("" if notas is None else str(notas)).strip()
        und_s = ("" if und is None else str(und)).strip()
        cant_f = _f(cant)
        pu_f = _f(pu)
        marca = ""
        nl = notas_s.lower()
        ul = und_s.lower()
        if "gastos generales" in nl:
            marca = "en_gg"
        elif "mandante" in nl:
            marca = "mandante"
        elif "a definir" in nl or nl == "n/a":
            marca = "a_definir"
        elif "proforma" in nl:
            marca = "proforma"
        elif "sub-contrato" in ul or "subcontrato" in ul:
            marca = "subcontrato"
            und_s = "gl"

        es_cap = False
        if re.fullmatch(r"\d+\.0", codigo) and not und_s:
            es_cap = True
        elif not und_s and pu_f <= 0 and not marca:
            es_cap = True

        lines.append(
            {
                "codigo": codigo,
                "detalle": detalle,
                "notas": notas_s,
                "unidad": "" if es_cap else (und_s or "gl"),
                "cantidad": 0.0 if es_cap else (cant_f if cant_f > 0 else (1.0 if pu_f > 0 else 0.0)),
                "pu": 0.0 if es_cap or marca in ("en_gg", "mandante", "a_definir") else pu_f,
                "tipo_linea": "capitulo" if es_cap else "partida",
                "marca": marca,
            }
        )
    return header, lines


def parse_apu_blocks(ws):
    blocks = []
    current = None
    for row in ws.iter_rows(values_only=True):
        vals = [("" if v is None else str(v).strip()) for v in list(row)[:6]]
        a, b, c, d, e, f = (vals + [""] * 6)[:6]
        if a and not b and not c and a.lower() not in ("nº", "n°", "no"):
            if current and current["items"]:
                blocks.append(current)
            current = {
                "titulo": a,
                "items": [],
                "leyes_pct": 29.0,
                "perdidas_pct": 10.0,
                "pu": None,
            }
            continue
        if not current:
            continue
        if a.lower() in ("nº", "n°", "nº.", "no") or b.lower() == "especificación":
            continue
        label = (d or b or "").lower()
        if "total general" in label:
            current["pu"] = _f(f or e)
            continue
        if "materiales" in label or "mano de obra" in label:
            continue
        if not a or not b:
            continue
        bl = b.lower()
        if "leyes sociales" in bl:
            current["leyes_pct"] = _f(c) * (100.0 if _f(c) <= 1 else 1.0)
            continue
        if "perdida" in bl or "pérdida" in bl:
            current["perdidas_pct"] = _f(c) * (100.0 if _f(c) <= 1 else 1.0)
            continue
        und = d or "un"
        cant = _f(c)
        precio = _f(e)
        if cant <= 0 and precio <= 0:
            continue
        tipo = "insumo"
        if any(
            k in bl
            for k in (
                "cuadrilla",
                "maestro",
                "ayudante",
                "jornal",
                "soldador",
                "mano de obra",
                "direccion",
                "dirección",
            )
        ) or und.lower() in ("jh", "hh"):
            tipo = "mano_obra"
        elif any(k in bl for k in ("arriendo", "flete", "excavadora", "rodillo")):
            tipo = "otro"
        current["items"].append(
            {
                "descripcion": b,
                "cantidad": cant if cant > 0 else 1.0,
                "unidad": und,
                "precio_unitario": precio,
                "tipo": tipo,
            }
        )
    if current and current["items"]:
        blocks.append(current)
    return blocks


def best_apu(partida_nombre: str, blocks, used: set[int]):
    pn = norm(partida_nombre)
    best_i, best_s = None, 0.0
    for i, b in enumerate(blocks):
        if i in used:
            continue
        bn = norm(b["titulo"])
        if not bn:
            continue
        score = SequenceMatcher(None, pn, bn).ratio()
        if bn in pn or pn in bn:
            score = max(score, 0.85)
        ta, tb = set(pn.split()), set(bn.split())
        if ta and tb:
            score = max(score, len(ta & tb) / max(len(ta), len(tb)))
        if score > best_s:
            best_s, best_i = score, i
    if best_i is not None and best_s >= 0.58:
        return best_i, best_s
    return None, 0.0


def wipe_obras(c):
    rows = c.execute(
        "SELECT id FROM centros_costo WHERE COALESCE(tipo,'general')='obra'"
    ).fetchall()
    ids = [int(r["id"]) for r in rows]
    for oid in ids:
        for a in c.execute("SELECT id FROM apu WHERE centro_costo_id=?", (oid,)):
            c.execute("DELETE FROM apu_items WHERE apu_id=?", (int(a["id"]),))
        c.execute("DELETE FROM apu WHERE centro_costo_id=?", (oid,))
        c.execute("DELETE FROM obra_partidas WHERE centro_costo_id=?", (oid,))
        for sql in (
            "DELETE FROM obra_subcontratos WHERE obra_id=?",
            "DELETE FROM obra_subcontratos WHERE centro_costo_id=?",
            "DELETE FROM obra_eepp_items WHERE eepp_id IN (SELECT id FROM obra_eepp WHERE centro_costo_id=?)",
            "DELETE FROM obra_eepp WHERE centro_costo_id=?",
        ):
            try:
                c.execute(sql, (oid,))
            except sqlite3.Error:
                pass
        try:
            for cot in c.execute(
                "SELECT id FROM cotizaciones WHERE centro_costo_id=?", (oid,)
            ):
                c.execute(
                    "DELETE FROM cotizacion_items WHERE cotizacion_id=?",
                    (int(cot["id"]),),
                )
            c.execute("DELETE FROM cotizaciones WHERE centro_costo_id=?", (oid,))
        except sqlite3.Error:
            pass
        try:
            c.execute(
                "DELETE FROM bodegas WHERE obra_id=? OR centro_costo_id=?", (oid, oid)
            )
        except sqlite3.Error:
            pass
        c.execute("DELETE FROM centros_costo WHERE id=?", (oid,))
    return ids


def main():
    if not XLSX.exists() or XLSX.stat().st_size < 1000:
        urllib.request.urlretrieve(XLSX_URL, XLSX)

    wb = openpyxl.load_workbook(XLSX, data_only=True)
    header, lines = parse_ppto(wb["Casa A"])
    blocks = parse_apu_blocks(wb["A.P.U."])
    print(f"Ppto líneas: {len(lines)} | APU blocks: {len(blocks)}")

    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    cst.ensure_constructora_schema(c)
    obractx.ensure_obra_contrato_schema(c)

    deleted = wipe_obras(c)
    print("Obras eliminadas:", deleted)

    ok, msg, oid = cst.crear_obra(
        c, nombre=NOMBRE_FICTICIO, presupuesto=0, notas_estado="activa"
    )
    if not ok:
        raise SystemExit(msg)
    print(msg, "id=", oid)

    obractx.guardar_parametros_presupuesto(
        c,
        oid,
        ubicacion="Parcelación Los Arrayanes, sector Demo",
        propietario="Familia Sepúlveda (demo)",
        documento_cot=header.get("documento_cot") or "Presupuesto preliminar",
        duracion_meses=header.get("duracion_meses") or 10,
        gg_pct=header.get("gg_pct") or 5,
        utilidades_pct=header.get("utilidades_pct") or 21,
        descuento_clp=0,
        iva_pct=19.0,
        valor_uf=header.get("valor_uf") or 36076.99,
    )
    c.execute(
        "UPDATE centros_costo SET cotizacion_obra_estado='borrador' WHERE id=?",
        (oid,),
    )

    # Insert partidas preservando código/orden del Excel (sin renumerar)
    hoy = core.hoy_chile().isoformat()
    pid_by_orden = {}
    n_cap = n_part = 0
    for orden, ln in enumerate(lines, start=1):
        cur = c.execute(
            """
            INSERT INTO obra_partidas
            (centro_costo_id, codigo, detalle, unidad, cantidad, pu_neto, total,
             avance_pct, orden, notas, activo, creado_en, tipo_linea, marca, apu_id)
            VALUES (?,?,?,?,?,0,0,0,?,?,1,?,?,?,NULL)
            """,
            (
                oid,
                ln["codigo"],
                ln["detalle"],
                ln["unidad"],
                ln["cantidad"],
                orden,
                ln["notas"] or None,
                hoy,
                ln["tipo_linea"],
                ln["marca"] or None,
            ),
        )
        pid_by_orden[orden] = int(cur.lastrowid)
        if ln["tipo_linea"] == "capitulo":
            n_cap += 1
        else:
            n_part += 1

    used_apu: set[int] = set()
    n_apu = n_stub = 0
    for orden, ln in enumerate(lines, start=1):
        if ln["tipo_linea"] == "capitulo":
            continue
        if ln["marca"] in ("en_gg", "mandante", "a_definir"):
            continue
        pid = pid_by_orden[orden]
        bi, score = best_apu(ln["detalle"], blocks, used_apu)
        items = []
        leyes = 0.0
        perdidas = 0.0
        if bi is not None:
            used_apu.add(bi)
            blk = blocks[bi]
            items = blk["items"]
            leyes = float(blk.get("leyes_pct") or 0)
            perdidas = float(blk.get("perdidas_pct") or 0)
            n_apu += 1
            notas = f"Import APU «{blk['titulo']}» score={score:.2f}"
        elif ln["pu"] > 0:
            items = [
                {
                    "descripcion": ln["detalle"],
                    "cantidad": 1.0,
                    "unidad": ln["unidad"] or "gl",
                    "precio_unitario": ln["pu"],
                    "tipo": "otro",
                }
            ]
            n_stub += 1
            notas = "PU desde ppto (sin desglose APU en planilla)"
        else:
            continue

        ok, msg, apu_id = cst.guardar_apu(
            c,
            apu_id=None,
            obra_id=oid,
            codigo="",
            nombre=ln["detalle"][:120],
            unidad=ln["unidad"] or "gl",
            leyes_pct=leyes,
            perdidas_pct=perdidas,
            notas=notas,
            activo=1,
            items=items,
            partida_id=pid,
        )
        if not ok:
            print("APU fail", ln["codigo"], ln["detalle"][:40], msg)
            continue
        # Foto del ppto: el PU del Excel manda (partida + APU) para totales
        if ln["pu"] > 0:
            c.execute(
                """
                UPDATE obra_partidas
                SET pu_neto=?, total=ROUND(?*?,2), cantidad=?, unidad=?
                WHERE id=?
                """,
                (
                    ln["pu"],
                    ln["cantidad"],
                    ln["pu"],
                    ln["cantidad"],
                    ln["unidad"] or "gl",
                    pid,
                ),
            )
            c.execute(
                "UPDATE apu SET pu_neto=? WHERE id=? AND centro_costo_id=?",
                (ln["pu"], int(apu_id), oid),
            )
        else:
            # sin precio en ppto: no valorizar
            c.execute(
                "UPDATE obra_partidas SET pu_neto=0, total=0 WHERE id=?",
                (pid,),
            )
            c.execute(
                "UPDATE apu SET pu_neto=0 WHERE id=? AND centro_costo_id=?",
                (int(apu_id), oid),
            )

    tot = obractx.totales_cotizacion_obra(c, oid)
    c.execute(
        "UPDATE centros_costo SET presupuesto=? WHERE id=?",
        (float(tot.get("neto") or 0), oid),
    )
    c.commit()
    print(
        f"OK obra {oid}: caps={n_cap} partidas={n_part} apu_match={n_apu} apu_stub={n_stub}"
    )
    print(
        "Totales:",
        {
            k: tot.get(k)
            for k in ("subtotal", "gg", "utilidades", "neto", "iva", "total", "monto_uf")
        },
    )
    print(
        "Partidas activas:",
        c.execute(
            "select count(*) from obra_partidas where centro_costo_id=? and coalesce(activo,1)=1",
            (oid,),
        ).fetchone()[0],
    )
    print(
        "APUs:",
        c.execute("select count(*) from apu where centro_costo_id=?", (oid,)).fetchone()[0],
    )
    print(
        "Obras restantes:",
        [dict(r) for r in c.execute("select id,nombre from centros_costo where tipo='obra'")],
    )
    c.close()


if __name__ == "__main__":
    main()
