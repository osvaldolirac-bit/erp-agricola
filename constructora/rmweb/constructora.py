"""Módulo Constructora: obras (CC), maestra APU y cotización por partidas."""
from __future__ import annotations

from typing import Any

from rmweb import core
from rmweb import ops_cc
from rmweb import obra_contrato as obractx

APU_ITEM_TIPOS = ("insumo", "mano_obra", "otro")
CC_TIPO_OBRA = "obra"
CC_TIPO_GENERAL = "general"


def ensure_constructora_schema(c) -> None:
    ops_cc.ensure_cc_schema(c)
    core._ensure_columns(
        c,
        "centros_costo",
        [
            ("tipo", "TEXT DEFAULT 'general'"),
            ("cliente_id", "INTEGER"),
            ("estado_obra", "TEXT DEFAULT 'activa'"),
            ("fecha_inicio", "TEXT"),
            ("fecha_fin", "TEXT"),
            ("cotizacion_id", "INTEGER"),
        ],
    )
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS apu (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT NOT NULL UNIQUE,
            nombre TEXT NOT NULL,
            unidad TEXT DEFAULT 'un',
            activo INTEGER DEFAULT 1,
            leyes_pct REAL DEFAULT 0,
            perdidas_pct REAL DEFAULT 0,
            pu_neto REAL DEFAULT 0,
            notas TEXT,
            creado_en TEXT
        );
        CREATE TABLE IF NOT EXISTS apu_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            apu_id INTEGER NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'insumo',
            descripcion TEXT NOT NULL,
            unidad TEXT DEFAULT 'un',
            cantidad REAL DEFAULT 0,
            precio_unitario REAL DEFAULT 0,
            total REAL DEFAULT 0,
            orden INTEGER DEFAULT 0,
            FOREIGN KEY(apu_id) REFERENCES apu(id) ON DELETE CASCADE
        );
        """
    )
    core._ensure_columns(
        c,
        "cotizaciones",
        [
            ("tipo_cotizacion", "TEXT DEFAULT 'normal'"),
            ("centro_costo_id", "INTEGER"),
        ],
    )
    core._ensure_columns(
        c,
        "cotizacion_items",
        [("apu_id", "INTEGER")],
    )
    core._ensure_columns(
        c,
        "inventario_movimientos",
        [("centro_costo_id", "INTEGER")],
    )
    # Maestra de precios (productos/insumos de obra) → fuente de PU del APU
    core._ensure_columns(
        c,
        "productos",
        [
            ("tipo_recurso", "TEXT DEFAULT 'insumo'"),
            ("uso_obra", "INTEGER DEFAULT 0"),
        ],
    )
    core._ensure_columns(
        c,
        "apu_items",
        [("producto_id", "INTEGER")],
    )
    core._ensure_columns(
        c,
        "apu",
        [("centro_costo_id", "INTEGER")],
    )
    obractx.ensure_obra_contrato_schema(c)


def _f(v, default: float = 0.0) -> float:
    try:
        return float(str(v if v is not None else default).replace(",", "."))
    except (TypeError, ValueError):
        return float(default)


def list_precios_obra(c, *, solo_activos: bool = True) -> list[Any]:
    """Productos para APU: PU = PMP de bodega si existe; si no, precio del producto."""
    sql = """
        SELECT p.id, p.codigo, p.nombre, p.unidad,
               CASE
                 WHEN i.id IS NOT NULL AND COALESCE(i.costo_pmp,0) > 0
                 THEN i.costo_pmp
                 ELSE COALESCE(p.precio, 0)
               END AS precio,
               COALESCE(i.costo_pmp, 0) AS pmp,
               COALESCE(i.stock, 0) AS stock,
               COALESCE(p.tipo_recurso, 'insumo') AS tipo_recurso,
               COALESCE(p.uso_obra, 0) AS uso_obra,
               COALESCE(p.es_servicio, 0) AS es_servicio,
               COALESCE(p.maneja_stock, 0) AS maneja_stock,
               COALESCE(p.activo, 1) AS activo
        FROM productos p
        LEFT JOIN inventario i ON i.producto_id = p.id
        WHERE 1=1
    """
    if solo_activos:
        sql += " AND COALESCE(p.activo,1)=1"
    sql += " ORDER BY COALESCE(p.tipo_recurso,'insumo'), lower(p.nombre), p.id"
    return c.execute(sql).fetchall()


def get_precio(c, producto_id: int) -> Any | None:
    return c.execute(
        """
        SELECT p.id, p.codigo, p.nombre, p.unidad,
               CASE
                 WHEN i.id IS NOT NULL AND COALESCE(i.costo_pmp,0) > 0
                 THEN i.costo_pmp
                 ELSE COALESCE(p.precio, 0)
               END AS precio,
               COALESCE(i.costo_pmp, 0) AS pmp,
               COALESCE(i.stock, 0) AS stock,
               COALESCE(p.tipo_recurso, 'insumo') AS tipo_recurso,
               COALESCE(p.uso_obra, 0) AS uso_obra,
               COALESCE(p.es_servicio, 0) AS es_servicio,
               COALESCE(p.maneja_stock, 0) AS maneja_stock,
               COALESCE(p.activo, 1) AS activo
        FROM productos p
        LEFT JOIN inventario i ON i.producto_id = p.id
        WHERE p.id=?
        """,
        (int(producto_id),),
    ).fetchone()


def next_precio_codigo(c, tipo: str = "insumo") -> str:
    pref = {
        "insumo": "INS",
        "mano_obra": "MO",
        "otro": "OTR",
    }.get((tipo or "insumo").strip().lower(), "INS")
    rows = c.execute(
        "SELECT codigo FROM productos WHERE codigo IS NOT NULL AND codigo != ''"
    ).fetchall()
    max_n = 0
    for r in rows:
        cod = str(r["codigo"] or "")
        if cod.upper().startswith(pref + "-"):
            try:
                max_n = max(max_n, int(cod.split("-", 1)[1]))
            except (IndexError, ValueError):
                pass
    return f"{pref}-{max_n + 1:03d}"


def guardar_precio(
    c,
    *,
    producto_id: int | None,
    codigo: str,
    nombre: str,
    unidad: str,
    precio: float,
    tipo_recurso: str,
    activo: int = 1,
    maneja_stock: int = 0,
) -> tuple[bool, str, int | None]:
    nom = (nombre or "").strip()
    if not nom:
        return False, "Indique el nombre del producto/insumo.", None
    tipo = (tipo_recurso or "insumo").strip().lower()
    if tipo not in APU_ITEM_TIPOS:
        tipo = "insumo"
    und = (unidad or "un").strip() or "un"
    cod = (codigo or "").strip().upper() or next_precio_codigo(c, tipo)
    p = max(0.0, _f(precio))
    es_servicio = 1 if tipo == "mano_obra" else 0
    stock = 0 if es_servicio else (1 if maneja_stock else 0)
    if producto_id:
        row = get_precio(c, producto_id)
        if not row:
            return False, "Producto no encontrado.", None
        dup = c.execute(
            "SELECT id FROM productos WHERE upper(COALESCE(codigo,''))=upper(?) AND id<>?",
            (cod, int(producto_id)),
        ).fetchone()
        if dup:
            return False, "Ya existe un producto con ese código.", None
        c.execute(
            """
            UPDATE productos SET
              codigo=?, nombre=?, unidad=?, precio=?,
              tipo_recurso=?, uso_obra=1, es_servicio=?, maneja_stock=?, activo=?
            WHERE id=?
            """,
            (
                cod,
                nom,
                und,
                p,
                tipo,
                es_servicio,
                stock,
                1 if activo else 0,
                int(producto_id),
            ),
        )
        return True, f"Precio «{nom}» actualizado.", int(producto_id)
    dup = c.execute(
        "SELECT id FROM productos WHERE upper(COALESCE(codigo,''))=upper(?)",
        (cod,),
    ).fetchone()
    if dup:
        # Reutilizar: marcar uso_obra
        c.execute(
            """
            UPDATE productos SET
              nombre=?, unidad=?, precio=?, tipo_recurso=?, uso_obra=1,
              es_servicio=?, maneja_stock=?, activo=?
            WHERE id=?
            """,
            (
                nom,
                und,
                p,
                tipo,
                es_servicio,
                stock,
                1 if activo else 0,
                int(dup["id"]),
            ),
        )
        return True, f"Producto existente marcado en maestra de obra: {cod}.", int(dup["id"])
    cur = c.execute(
        """
        INSERT INTO productos
        (codigo, nombre, unidad, precio, es_servicio, maneja_stock, activo, tipo_recurso, uso_obra)
        VALUES (?,?,?,?,?,?,?,?,1)
        """,
        (cod, nom, und, p, es_servicio, stock, 1 if activo else 0, tipo),
    )
    return True, f"Producto «{nom}» agregado a la maestra.", int(cur.lastrowid)



def sync_precio_desde_pmp(c, producto_id: int | None = None) -> int:
    """Copia PMP de bodega a productos.precio (maestra = costo PMP)."""
    if producto_id:
        rows = c.execute(
            """
            SELECT p.id, i.costo_pmp
            FROM productos p
            JOIN inventario i ON i.producto_id = p.id
            WHERE p.id=? AND COALESCE(p.uso_obra,0)=1 AND COALESCE(p.maneja_stock,0)=1
              AND COALESCE(i.costo_pmp,0) > 0
            """,
            (int(producto_id),),
        ).fetchall()
    else:
        rows = c.execute(
            """
            SELECT p.id, i.costo_pmp
            FROM productos p
            JOIN inventario i ON i.producto_id = p.id
            WHERE COALESCE(p.uso_obra,0)=1 AND COALESCE(p.maneja_stock,0)=1
              AND COALESCE(i.costo_pmp,0) > 0
            """
        ).fetchall()
    n = 0
    for r in rows:
        c.execute("UPDATE productos SET precio=? WHERE id=?", (float(r["costo_pmp"] or 0), int(r["id"])))
        n += 1
    return n


def precio_desde_maestra(c, producto_id: int | None) -> dict[str, Any] | None:
    if not producto_id:
        return None
    row = get_precio(c, int(producto_id))
    if not row or not int(row["activo"] or 0):
        return None
    tipo = (row["tipo_recurso"] or "insumo").strip().lower()
    if tipo not in APU_ITEM_TIPOS:
        tipo = "insumo"
    return {
        "producto_id": int(row["id"]),
        "codigo": row["codigo"] or "",
        "descripcion": row["nombre"],
        "unidad": row["unidad"] or "un",
        "precio_unitario": _f(row["precio"]),
        "tipo": tipo,
    }


def next_apu_codigo(c, obra_id: int | None = None) -> str:
    """Código único por obra: APU-{obra_id}-{nn}."""
    oid = int(obra_id or 0)
    pref = f"APU-{oid}-" if oid else "APU-"
    rows = c.execute(
        "SELECT codigo FROM apu WHERE centro_costo_id=? OR (?=0 AND codigo LIKE 'APU-%')",
        (oid, oid),
    ).fetchall() if oid else c.execute("SELECT codigo FROM apu").fetchall()
    max_n = 0
    for r in rows:
        cod = str(r["codigo"] or "")
        if oid and cod.upper().startswith(pref.upper()):
            try:
                max_n = max(max_n, int(cod.rsplit("-", 1)[-1]))
            except ValueError:
                pass
        elif not oid and cod.upper().startswith("APU-"):
            try:
                max_n = max(max_n, int(cod.split("-")[-1]))
            except ValueError:
                pass
    if oid:
        return f"APU-{oid}-{max_n + 1:02d}"
    return f"APU-{max_n + 1:02d}"


def calc_apu_desde_items(
    items: list[dict[str, Any]],
    *,
    leyes_pct: float = 0.0,
    perdidas_pct: float = 0.0,
) -> dict[str, float]:
    """Valoriza APU: insumos + MO + leyes sociales (% MO) + pérdidas (% insumos)."""
    insumos = 0.0
    mo = 0.0
    otro = 0.0
    for it in items:
        total = _f(it.get("total"))
        if total <= 0:
            total = _f(it.get("cantidad")) * _f(it.get("precio_unitario"))
        tipo = (it.get("tipo") or "insumo").strip().lower()
        if tipo == "mano_obra":
            mo += total
        elif tipo == "otro":
            otro += total
        else:
            insumos += total
    leyes = mo * (_f(leyes_pct) / 100.0)
    perdidas = insumos * (_f(perdidas_pct) / 100.0)
    pu = insumos + mo + otro + leyes + perdidas
    return {
        "insumos": round(insumos, 2),
        "mano_obra": round(mo, 2),
        "otro": round(otro, 2),
        "leyes": round(leyes, 2),
        "perdidas": round(perdidas, 2),
        "pu_neto": round(pu, 2),
    }


def list_apu(
    c,
    *,
    obra_id: int | None = None,
    solo_activos: bool = False,
) -> list[Any]:
    """APU de una obra (centro_costo_id). Sin obra_id no lista globales."""
    sql = "SELECT * FROM apu WHERE 1=1"
    params: list[Any] = []
    if obra_id is not None:
        sql += " AND centro_costo_id=?"
        params.append(int(obra_id))
    else:
        sql += " AND 1=0"  # exigir obra
    if solo_activos:
        sql += " AND COALESCE(activo,1)=1"
    sql += " ORDER BY codigo"
    return c.execute(sql, params).fetchall()


def get_apu(c, apu_id: int) -> Any | None:
    return c.execute("SELECT * FROM apu WHERE id=?", (int(apu_id),)).fetchone()


def get_apu_de_obra(c, apu_id: int, obra_id: int) -> Any | None:
    return c.execute(
        "SELECT * FROM apu WHERE id=? AND centro_costo_id=?",
        (int(apu_id), int(obra_id)),
    ).fetchone()


def list_apu_items(c, apu_id: int) -> list[Any]:
    return c.execute(
        """
        SELECT * FROM apu_items WHERE apu_id=?
        ORDER BY COALESCE(orden,0), id
        """,
        (int(apu_id),),
    ).fetchall()


def guardar_apu(
    c,
    *,
    apu_id: int | None,
    obra_id: int,
    codigo: str,
    nombre: str,
    unidad: str,
    leyes_pct: float,
    perdidas_pct: float,
    notas: str,
    activo: int,
    items: list[dict[str, Any]],
    partida_id: int | None = None,
) -> tuple[bool, str, int | None]:
    try:
        oid = int(obra_id)
    except (TypeError, ValueError):
        oid = 0
    if oid <= 0:
        return False, "APU debe pertenecer a una obra.", None
    obra = c.execute(
        "SELECT id FROM centros_costo WHERE id=? AND COALESCE(tipo,'general')='obra'",
        (oid,),
    ).fetchone()
    if not obra:
        return False, "Obra no encontrada.", None
    nom = (nombre or "").strip()
    if not nom:
        return False, "Indique el nombre del APU.", None
    und = (unidad or "un").strip() or "un"
    cod = (codigo or "").strip().upper() or next_apu_codigo(c, oid)
    breakdown = calc_apu_desde_items(
        items, leyes_pct=leyes_pct, perdidas_pct=perdidas_pct
    )
    hoy = core.hoy_chile().isoformat()
    if apu_id:
        row = get_apu(c, apu_id)
        if not row:
            return False, "APU no encontrado.", None
        row_obra = int(row["centro_costo_id"] or 0) if "centro_costo_id" in row.keys() else 0
        if row_obra and row_obra != oid:
            return False, "Este APU pertenece a otra obra.", None
        dup = c.execute(
            "SELECT id FROM apu WHERE upper(codigo)=upper(?) AND centro_costo_id=? AND id<>?",
            (cod, oid, int(apu_id)),
        ).fetchone()
        if dup:
            return False, "Ya existe un APU con ese código en esta obra.", None
        c.execute(
            """
            UPDATE apu SET codigo=?, nombre=?, unidad=?, activo=?,
              leyes_pct=?, perdidas_pct=?, pu_neto=?, notas=?, centro_costo_id=?
            WHERE id=?
            """,
            (
                cod,
                nom,
                und,
                1 if activo else 0,
                _f(leyes_pct),
                _f(perdidas_pct),
                breakdown["pu_neto"],
                (notas or "").strip() or None,
                oid,
                int(apu_id),
            ),
        )
        c.execute("DELETE FROM apu_items WHERE apu_id=?", (int(apu_id),))
        cid = int(apu_id)
    else:
        dup = c.execute(
            "SELECT id FROM apu WHERE upper(codigo)=upper(?) AND centro_costo_id=?",
            (cod, oid),
        ).fetchone()
        if dup:
            return False, "Ya existe un APU con ese código en esta obra.", None
        # código global UNIQUE en schema viejo: forzar prefijo obra si choca
        gdup = c.execute(
            "SELECT id FROM apu WHERE upper(codigo)=upper(?)", (cod,)
        ).fetchone()
        if gdup:
            cod = next_apu_codigo(c, oid)
        cur = c.execute(
            """
            INSERT INTO apu
            (codigo, nombre, unidad, activo, leyes_pct, perdidas_pct, pu_neto, notas, creado_en, centro_costo_id)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                cod,
                nom,
                und,
                1 if activo else 0,
                _f(leyes_pct),
                _f(perdidas_pct),
                breakdown["pu_neto"],
                (notas or "").strip() or None,
                hoy,
                oid,
            ),
        )
        cid = int(cur.lastrowid)

    # Foto de precios: PU viene del formulario (no se pisa con PMP de bodega).
    if apu_id:
        prev = get_apu(c, apu_id)
        if prev and int(prev["congelado"] or 0):
            return False, "APU congelado (cotización aprobada). No se puede editar.", None

    orden = 0
    resolved_items: list[dict[str, Any]] = []
    for it in items:
        try:
            pid = int(it.get("producto_id") or 0) or None
        except (TypeError, ValueError):
            pid = None
        master = precio_desde_maestra(c, pid) if pid else None
        desc = (it.get("descripcion") or "").strip()
        tipo = (it.get("tipo") or "").strip().lower()
        und_i = (it.get("unidad") or "").strip()
        pu = _f(it.get("precio_unitario"))
        if master:
            if not desc:
                desc = master["descripcion"]
            if not tipo:
                tipo = master["tipo"]
            if not und_i:
                und_i = master["unidad"]
            # si no mandaron PU, usar ref (puede ser PMP informativo)
            if pu <= 0:
                pu = master["precio_unitario"]
        if tipo not in APU_ITEM_TIPOS:
            tipo = "insumo"
        und_i = und_i or "un"
        if not desc:
            continue
        cant = _f(it.get("cantidad"))
        if cant <= 0:
            continue
        if pu < 0:
            continue
        total = round(cant * pu, 2)
        orden += 1
        resolved_items.append(
            {
                "producto_id": pid,
                "tipo": tipo,
                "descripcion": desc,
                "unidad": und,
                "cantidad": cant,
                "precio_unitario": pu,
                "total": total,
            }
        )
        c.execute(
            """
            INSERT INTO apu_items
            (apu_id, tipo, descripcion, unidad, cantidad, precio_unitario, total, orden, producto_id)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (cid, tipo, desc, und, cant, pu, total, orden, pid),
        )
    if orden == 0:
        return False, "Agregue al menos un ítem con cantidad y precio > 0.", None
    items = resolved_items
    breakdown = calc_apu_desde_items(
        resolved_items, leyes_pct=leyes_pct, perdidas_pct=perdidas_pct
    )
    c.execute(
        "UPDATE apu SET pu_neto=? WHERE id=?", (breakdown["pu_neto"], cid)
    )
    if partida_id:
        try:
            obractx.vincular_apu_a_partida(c, oid, int(partida_id), cid)
        except Exception:
            pass
    else:
        try:
            from rmweb import obra_contrato as _oc
            _oc.sync_partida_desde_apu(c, cid)
        except Exception:
            obractx.sync_partida_desde_apu(c, cid)
    pu_txt = f"{breakdown['pu_neto']:,.0f}".replace(",", ".")
    return True, f"APU {cod} guardado (PU neto ${pu_txt}).", cid


def recalcular_apu_desde_maestra(c, apu_id: int) -> tuple[bool, str]:
    """Deshabilitado: el APU es foto de precios; PMP de bodega es solo informativo."""
    return False, "El APU no se actualiza desde bodega. El PMP es solo referencia; la foto se congela al aprobar la cotización de obra."
    row = get_apu(c, apu_id)
    if not row:
        return False, "APU no encontrado."
    items = list_apu_items(c, apu_id)
    if not items:
        return False, "APU sin ítems."
    updated = 0
    for it in items:
        pid = it["producto_id"] if "producto_id" in it.keys() else None
        if not pid:
            continue
        master = precio_desde_maestra(c, int(pid))
        if not master:
            continue
        cant = _f(it["cantidad"])
        pu = master["precio_unitario"]
        c.execute(
            """
            UPDATE apu_items
            SET descripcion=?, unidad=?, tipo=?, precio_unitario=?, total=?
            WHERE id=?
            """,
            (
                master["descripcion"],
                master["unidad"],
                master["tipo"],
                pu,
                round(cant * pu, 2),
                int(it["id"]),
            ),
        )
        updated += 1
    fresh = list_apu_items(c, apu_id)
    breakdown = calc_apu_desde_items(
        [
            {
                "tipo": r["tipo"],
                "cantidad": r["cantidad"],
                "precio_unitario": r["precio_unitario"],
                "total": r["total"],
            }
            for r in fresh
        ],
        leyes_pct=_f(row["leyes_pct"]),
        perdidas_pct=_f(row["perdidas_pct"]),
    )
    c.execute("UPDATE apu SET pu_neto=? WHERE id=?", (breakdown["pu_neto"], int(apu_id)))
    pu_txt = f"{breakdown['pu_neto']:,.0f}".replace(",", ".")
    return True, f"APU actualizado desde maestra ({updated} ítem(s)). PU neto ${pu_txt}."


def list_obras(c, *, solo_activas: bool = False) -> list[Any]:
    sql = """
        SELECT cc.*, cl.razon_social AS cliente_nombre
        FROM centros_costo cc
        LEFT JOIN clientes cl ON cl.id = cc.cliente_id
        WHERE COALESCE(cc.tipo, 'general') = 'obra'
    """
    if solo_activas:
        sql += " AND COALESCE(cc.activo,1)=1 AND COALESCE(cc.estado_obra,'activa')='activa'"
    sql += " ORDER BY COALESCE(cc.orden,0), lower(cc.nombre), cc.id"
    return c.execute(sql).fetchall()


def crear_obra(
    c,
    *,
    nombre: str,
    cliente_id: int | None = None,
    presupuesto: float = 0.0,
    fecha_inicio: str | None = None,
    notas_estado: str = "activa",
) -> tuple[bool, str, int | None]:
    nom = (nombre or "").strip()
    if not nom:
        return False, "Indique el nombre de la obra.", None
    exists = c.execute(
        "SELECT id FROM centros_costo WHERE lower(nombre)=lower(?)", (nom,)
    ).fetchone()
    if exists:
        return False, "Ya existe un centro/obra con ese nombre.", None
    ord_row = c.execute(
        "SELECT COALESCE(MAX(orden),0)+1 AS o FROM centros_costo"
    ).fetchone()
    cur = c.execute(
        """
        INSERT INTO centros_costo
        (nombre, activo, orden, presupuesto, tipo, cliente_id, estado_obra, fecha_inicio)
        VALUES (?,1,?,?,'obra',?,?,?)
        """,
        (
            nom,
            int(ord_row["o"] or 1),
            max(0.0, _f(presupuesto)),
            int(cliente_id) if cliente_id else None,
            (notas_estado or "activa").strip() or "activa",
            (fecha_inicio or "").strip() or None,
        ),
    )
    return True, f"Obra «{nom}» creada (CC).", int(cur.lastrowid)


def actualizar_obra(
    c,
    obra_id: int,
    *,
    nombre: str | None = None,
    activo: int | None = None,
    cliente_id: int | None = None,
    estado_obra: str | None = None,
    fecha_inicio: str | None = None,
    fecha_fin: str | None = None,
    presupuesto: float | None = None,
) -> tuple[bool, str]:
    row = c.execute(
        "SELECT * FROM centros_costo WHERE id=? AND COALESCE(tipo,'general')='obra'",
        (int(obra_id),),
    ).fetchone()
    if not row:
        return False, "Obra no encontrada."
    nom = row["nombre"]
    act = int(row["activo"] or 0)
    cli = row["cliente_id"]
    est = row["estado_obra"] or "activa"
    fi = row["fecha_inicio"]
    ff = row["fecha_fin"]
    ppto = float(row["presupuesto"] or 0)
    if nombre is not None:
        nom = (nombre or "").strip()
        if not nom:
            return False, "Nombre vacío."
        dup = c.execute(
            "SELECT id FROM centros_costo WHERE lower(nombre)=lower(?) AND id<>?",
            (nom, int(obra_id)),
        ).fetchone()
        if dup:
            return False, "Ya existe otro CC/obra con ese nombre."
    if activo is not None:
        act = 1 if int(activo) else 0
    if cliente_id is not None:
        cli = int(cliente_id) if cliente_id else None
    if estado_obra is not None:
        est = (estado_obra or "activa").strip() or "activa"
    if fecha_inicio is not None:
        fi = (fecha_inicio or "").strip() or None
    if fecha_fin is not None:
        ff = (fecha_fin or "").strip() or None
    if presupuesto is not None:
        ppto = max(0.0, _f(presupuesto))
    c.execute(
        """
        UPDATE centros_costo SET
          nombre=?, activo=?, presupuesto=?, cliente_id=?,
          estado_obra=?, fecha_inicio=?, fecha_fin=?, tipo='obra'
        WHERE id=?
        """,
        (nom, act, ppto, cli, est, fi, ff, int(obra_id)),
    )
    return True, "Obra actualizada."


def sincronizar_ppto_obra_desde_cotizacion(c, cot_id: int) -> tuple[bool, str]:
    """Ppto de obra = subtotal de partidas (APU × cantidad)."""
    cot = c.execute("SELECT * FROM cotizaciones WHERE id=?", (int(cot_id),)).fetchone()
    if not cot:
        return False, "Cotización no encontrada."
    if (cot["tipo_cotizacion"] or "normal") != "obra":
        return False, "No es cotización de obra."
    cc_id = cot["centro_costo_id"]
    if not cc_id:
        return False, "Cotización de obra sin CC/obra."
    subtotal = float(cot["subtotal"] or 0)
    # Preferir suma de líneas de trabajo (sin GG/util embebidos)
    items = c.execute(
        """
        SELECT descripcion, total FROM cotizacion_items
        WHERE cotizacion_id=?
        """,
        (int(cot_id),),
    ).fetchall()
    partidas = 0.0
    for it in items:
        d = it["descripcion"] or ""
        if core._is_gg_line(d) or core._is_util_line(d):
            continue
        partidas += float(it["total"] or 0)
    ppto = partidas if partidas > 0 else subtotal
    c.execute(
        """
        UPDATE centros_costo
        SET presupuesto=?, cotizacion_id=?, tipo='obra',
            nombre=COALESCE(NULLIF(nombre,''), ?)
        WHERE id=?
        """,
        (ppto, int(cot_id), cot["proyecto"] or cot["titulo"] or "", int(cc_id)),
    )
    # Si proyecto vacío, poner nombre obra
    if cot["proyecto"]:
        c.execute(
            "UPDATE cotizaciones SET proyecto=? WHERE id=? AND (proyecto IS NULL OR trim(proyecto)='')",
            (cot["proyecto"], int(cot_id)),
        )
    return True, f"Presupuesto de obra actualizado: {ppto:,.0f}".replace(",", ".")


def obra_resumen(c, obra_id: int) -> dict[str, Any]:
    obra = c.execute(
        """
        SELECT cc.*, cl.razon_social AS cliente_nombre
        FROM centros_costo cc
        LEFT JOIN clientes cl ON cl.id=cc.cliente_id
        WHERE cc.id=?
        """,
        (int(obra_id),),
    ).fetchone()
    if not obra:
        return {}
    row = c.execute(
        """
        SELECT COALESCE(SUM(monto),0) AS t
        FROM factura_compra_cc WHERE centro_costo_id=?
        """,
        (int(obra_id),),
    ).fetchone()
    gasto_compras = float(row["t"] or 0)
    mat = c.execute(
        """
        SELECT COALESCE(SUM(cantidad * COALESCE(costo_unitario,0)),0) AS t
        FROM inventario_movimientos
        WHERE tipo='salida' AND centro_costo_id=?
        """,
        (int(obra_id),),
    ).fetchone()
    gasto_mat = float(mat["t"] or 0)
    ppto = float(obra["presupuesto"] or 0)
    gasto = gasto_compras + gasto_mat
    return {
        "obra": obra,
        "ppto": ppto,
        "gasto_compras": gasto_compras,
        "gasto_materiales": gasto_mat,
        "gasto_total": gasto,
        "avance_pct": (gasto / ppto * 100.0) if ppto > 0 else 0.0,
    }
