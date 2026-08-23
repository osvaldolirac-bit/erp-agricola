"""Registro de riego vía link personal + autorización admin (patrón Salida Link petróleo)."""
from __future__ import annotations

import os
import re
import secrets
import sqlite3
from datetime import timedelta
from typing import Any

from flask import current_app, request

from demo_web.services.demo_loader import get_demo_module, get_erp_app

_CODIGO_RE = re.compile(r"^RIE-(\d+)$", re.I)
_FAMILIAS_FERTILIZANTE = ("FERTILIZANTE",)
# Fórmula comercial N-P₂O₅-K₂O en nombre (ej. 20-20-20, 13 40 13, 10/34/0).
_NPK_FORMULA_RE = re.compile(
    r"(?<![\d.])(\d{1,2})\s*[-–/]\s*(\d{1,2})\s*[-–/]\s*(\d{1,2})(?![\d.])",
    re.I,
)
# Solución UAN (ej. UAN-32 → 32 % N).
_UAN_RE = re.compile(r"UAN[\s\-–]?(\d{2})", re.I)
# Catálogo de referencia para fertirriego (N-P₂O₅-K₂O). No refleja el stock actual de
# bodega: los productos irán ingresando según necesidad. Al registrarse un riego, el
# cálculo identifica el análisis por nombre guardado en riego_fertilizantes (fórmula
# en el nombre, UAN o coincidencia con este catálogo).
_FERTILIZANTE_NPK: tuple[tuple[tuple[str, ...], tuple[float, float, float]], ...] = (
    # --- Binarios / compuestos (doble aporte) ---
    (("NITRATO DE POTASIO", "NITRATO POTASIO", "KNO3"), (13.0, 0.0, 46.0)),
    (("FOSFATO MONOPOTASICO", "MONOPOTASICO", "MKP", "KH2PO4"), (0.0, 52.0, 34.0)),
    (("FOSFATO MONOAMONICO", "MONOAMONICO", "MAP", "NH4H2PO4"), (12.0, 61.0, 0.0)),
    (("FOSFATO DIAMONICO", "DIAMONIO", "DAP"), (18.0, 46.0, 0.0)),
    (("POLIFOSFATO", "10-34-0"), (10.0, 34.0, 0.0)),
    # --- Nitrógeno ---
    (("NITRATO DE CALCIO", "CALCINIT", "CALNIT"), (15.5, 0.0, 0.0)),
    (("NITRATO DE MAGNESIO", "MAGNESIO NITRATO"), (11.0, 0.0, 0.0)),
    (("NITRATO DE AMONIO", "AMMONIUM NITRATE"), (33.5, 0.0, 0.0)),
    (("SULFATO DE AMONIO", "SULFATO AMONIO", "(NH4)2SO4"), (21.0, 0.0, 0.0)),
    (("UREA SOLUBLE", "UREA"), (46.0, 0.0, 0.0)),
    # --- Fósforo (incl. ácido para pH / desincrustación) ---
    (("ACIDO FOSFORICO", "ÁCIDO FOSFORICO", "H3PO4", "FOSFORICO"), (0.0, 54.0, 0.0)),
    # --- Potasio ---
    (("SULFATO DE POTASIO", "SOP", "K2SO4"), (0.0, 0.0, 51.0)),
    (("CLORURO DE POTASIO", "MOP", "KCL"), (0.0, 0.0, 60.0)),
    (("TIOSULFATO DE POTASIO", "TIOSULFATO POTASIO", "K2S2O3"), (0.0, 0.0, 25.0)),
    # --- Sin macro NPK (micronutrientes / correctores) ---
    (("CALCIO BORO", "BORO FOLIAR", "BORO", "CALCIO FOLIAR"), (0.0, 0.0, 0.0)),
)


def _conn() -> sqlite3.Connection:
    demo = get_demo_module()
    return demo.conectar_db()


def formatear_codigo_rie(n: int) -> str:
    if n < 100:
        return f"RIE-{n:02d}"
    return f"RIE-{n}"


def _max_numero_codigo(conn: sqlite3.Connection, tabla: str) -> int:
    rows = conn.execute(
        f"SELECT codigo FROM {tabla} WHERE codigo IS NOT NULL AND codigo != ''"
    ).fetchall()
    max_n = 0
    for (cod,) in rows:
        m = _CODIGO_RE.match(str(cod).strip())
        if m:
            max_n = max(max_n, int(m.group(1)))
    return max_n


def _siguiente_codigo(conn: sqlite3.Connection, tabla: str = "riego_bitacora") -> str:
    n1 = _max_numero_codigo(conn, "riego_bitacora")
    n2 = _max_numero_codigo(conn, "riego")
    return formatear_codigo_rie(max(n1, n2) + 1)


def huertos_para_formulario() -> list[str]:
    demo = get_demo_module()
    raw = list(getattr(demo, "CENTROS_COSTO", []) or [])
    otros = [c for c in raw if str(c).strip().upper() == "OTROS"]
    resto = [c for c in raw if str(c).strip().upper() != "OTROS"]
    return resto + otros


# m³/h·ha por huerto — riego todo el huerto (horas × coef × ha prorrateo)
RIEGO_M3_HR_HA: dict[str, float] = {
    "CEREZOS CORTE 1": 18.0,
    "CEREZOS CORTE 2": 18.0,
    "CIRUELOS": 18.0,
    "NOGALES APARICION": 34.0,
}
# Riego por surco: m³ = horas × 40 m³/h·ha × ha (prorrateo)
RIEGO_SOLO_SURCO: frozenset[str] = frozenset({"NOGALES CRUZ DEL SUR"})
RIEGO_M3_HR_SURCO = 40.0


def _huertos_riego_auto() -> frozenset[str]:
    return frozenset(RIEGO_M3_HR_HA.keys()) | RIEGO_SOLO_SURCO


def huerto_tiene_calculo_auto(huerto: str) -> bool:
    return _norm_cc(huerto) in _huertos_riego_auto()


def huerto_solo_surco(huerto: str) -> bool:
    return _norm_cc(huerto) in RIEGO_SOLO_SURCO


def _modo_efectivo(huerto: str, modo: str | None) -> str:
    if huerto_solo_surco(huerto):
        return "surcos"
    modo_n = (modo or "horas").strip().lower()
    return "surcos" if modo_n == "surcos" else "horas"


def _norm_cc(huerto: str) -> str:
    return (huerto or "").strip().upper()


def _cargar_superficie_ha(conn: sqlite3.Connection, huerto: str) -> float:
    cc = _norm_cc(huerto)
    try:
        row = conn.execute(
            "SELECT COALESCE(superficie_ha, 0) FROM prorrateo_cc WHERE centro_costo=?",
            (cc,),
        ).fetchone()
        if row and float(row[0] or 0) > 0:
            return float(row[0])
    except sqlite3.OperationalError:
        pass
    return 0.0


def _cargar_surcos_total(conn: sqlite3.Connection, huerto: str) -> int:
    cc = _norm_cc(huerto)
    try:
        row = conn.execute(
            "SELECT COALESCE(surcos_total, 0) FROM riego_config_cc WHERE centro_costo=?",
            (cc,),
        ).fetchone()
        if row:
            return int(row[0] or 0)
    except sqlite3.OperationalError:
        pass
    return 0


def _ensure_riego_config_cc(conn: sqlite3.Connection) -> None:
    from erp_solo_lectura import conn_en_solo_lectura

    if conn_en_solo_lectura(conn):
        return
    conn.execute(
        """CREATE TABLE IF NOT EXISTS riego_config_cc (
               centro_costo TEXT PRIMARY KEY,
               m3_hr_ha REAL NOT NULL,
               surcos_total INTEGER DEFAULT 0
           )"""
    )
    for cc, coef in RIEGO_M3_HR_HA.items():
        conn.execute(
            """INSERT OR IGNORE INTO riego_config_cc (centro_costo, m3_hr_ha, surcos_total)
               VALUES (?,?,0)""",
            (cc, float(coef)),
        )
        conn.execute(
            "UPDATE riego_config_cc SET m3_hr_ha=? WHERE centro_costo=?",
            (float(coef), cc),
        )
    for cc in RIEGO_SOLO_SURCO:
        conn.execute(
            """INSERT OR IGNORE INTO riego_config_cc (centro_costo, m3_hr_ha, surcos_total)
               VALUES (?, ?, 0)""",
            (cc, float(RIEGO_M3_HR_SURCO)),
        )


def config_riego_cc_para_formulario() -> dict[str, dict[str, float | bool]]:
    conn = _conn()
    try:
        migrar_tabla(conn)
        out: dict[str, dict[str, float | bool]] = {}
        for cc in sorted(_huertos_riego_auto()):
            solo = cc in RIEGO_SOLO_SURCO
            out[cc] = {
                "m3_hr_ha": float(RIEGO_M3_HR_HA.get(cc, 0)),
                "m3_hr_surco": float(RIEGO_M3_HR_SURCO),
                "ha": _cargar_superficie_ha(conn, cc),
                "solo_surco": solo,
            }
        return out
    finally:
        conn.close()


def listar_config_riego_cc() -> list[dict[str, Any]]:
    conn = _conn()
    try:
        migrar_tabla(conn)
        rows: list[dict[str, Any]] = []
        for cc in sorted(_huertos_riego_auto()):
            solo = cc in RIEGO_SOLO_SURCO
            rows.append(
                {
                    "centro_costo": cc,
                    "m3_hr_ha": RIEGO_M3_HR_HA.get(cc),
                    "m3_hr_surco": RIEGO_M3_HR_SURCO,
                    "superficie_ha": _cargar_superficie_ha(conn, cc),
                    "solo_surco": solo,
                }
            )
        return rows
    finally:
        conn.close()


def calcular_m3_riego(
    conn: sqlite3.Connection,
    huerto: str,
    horas: float,
    *,
    modo: str = "horas",
    surcos: float | None = None,
) -> tuple[float, str]:
    cc = _norm_cc(huerto)
    if cc not in _huertos_riego_auto():
        return 0.0, ""
    if horas <= 0:
        return 0.0, "Indique horas de riego mayores a cero."
    ha = _cargar_superficie_ha(conn, cc)
    if ha <= 0:
        return 0.0, f"No hay superficie (ha) en prorrateo de costos para {cc}."
    modo_n = _modo_efectivo(cc, modo)
    if modo_n == "surcos":
        return round(horas * RIEGO_M3_HR_SURCO * ha, 2), ""
    coef = RIEGO_M3_HR_HA.get(cc)
    if coef is None:
        return round(horas * RIEGO_M3_HR_SURCO * ha, 2), ""
    return round(horas * coef * ha, 2), ""


def resolver_m3_registro(
    conn: sqlite3.Connection,
    huerto: str,
    horas: float,
    m3_manual: float,
    *,
    modo: str = "horas",
    surcos: float | None = None,
) -> tuple[float, str | None]:
    cc = _norm_cc(huerto)
    if huerto_tiene_calculo_auto(cc):
        modo_eff = _modo_efectivo(cc, modo)
        m3, err = calcular_m3_riego(conn, cc, horas, modo=modo_eff, surcos=surcos)
        if err:
            return 0.0, err
        return m3, None
    if horas <= 0 and m3_manual <= 0:
        return 0.0, "Indique horas o m³ mayores a cero."
    return float(m3_manual or 0), None


def _norm_nombre_fertilizante(nombre: str) -> str:
    return re.sub(r"\s+", " ", str(nombre or "").strip().upper())


def _npk_desde_formula(nombre: str) -> tuple[float, float, float] | None:
    """Detecta fórmula N-P₂O₅-K₂O en el nombre (ej. Ultrasol 20-20-20)."""
    m = _NPK_FORMULA_RE.search(nombre)
    if not m:
        return None
    n, p, k = (float(m.group(i)) for i in (1, 2, 3))
    if max(n, p, k) > 70 or (n + p + k) > 120:
        return None
    return (n, p, k)


def _npk_desde_uan(nombre: str) -> tuple[float, float, float] | None:
    m = _UAN_RE.search(nombre)
    if not m:
        return None
    pct = float(m.group(1))
    if pct <= 0 or pct > 40:
        return None
    return (pct, 0.0, 0.0)


def _npk_producto(nombre: str) -> tuple[float, float, float]:
    """Retorna % N, P₂O₅, K₂O según nombre (fórmula, UAN o catálogo técnico)."""
    n = _norm_nombre_fertilizante(nombre)
    if not n:
        return (0.0, 0.0, 0.0)
    parsed = _npk_desde_formula(n)
    if parsed:
        return parsed
    uan = _npk_desde_uan(n)
    if uan:
        return uan
    for keys, npk in _FERTILIZANTE_NPK:
        if any(k in n for k in keys):
            return npk
    return (0.0, 0.0, 0.0)


def _kg_nutriente_aplicado(cantidad: float, unidad: str | None, pct: float) -> float:
    """kg nutriente = kg fertilizante × (% riqueza / 100)."""
    kg = _cantidad_kg_fertilizante(cantidad, unidad)
    return kg * float(pct or 0) / 100.0


def _cantidad_kg_fertilizante(cantidad: float, unidad: str | None) -> float:
    u = str(unidad or "kg").strip().lower()
    if u in ("lt", "l", "litro", "litros"):
        return float(cantidad or 0)
    return float(cantidad or 0)


def resumen_npk_por_huerto(conn: sqlite3.Connection) -> dict[str, Any]:
    """Suma N, P₂O₅ y K₂O (kg) aplicados vía fertirriego en historial autorizado."""
    migrar_tabla(conn)
    demo = get_demo_module()
    f_cant = getattr(demo, "f_cantidad", demo.f_decimal)
    rows = conn.execute(
        """SELECT r.huerto, rf.producto, rf.cantidad, rf.unidad
           FROM riego r
           INNER JOIN riego_fertilizantes rf ON rf.codigo = r.codigo
           WHERE COALESCE(rf.cantidad, 0) > 0"""
    ).fetchall()
    por_huerto: dict[str, dict[str, Any]] = {}
    totales = {"n": 0.0, "p": 0.0, "k": 0.0}
    sin_analisis: dict[str, float] = {}
    for huerto, producto, cantidad, unidad in rows:
        h = str(huerto or "—").strip() or "—"
        prod = str(producto or "").strip()
        kg_fert = _cantidad_kg_fertilizante(float(cantidad or 0), unidad)
        pct_n, pct_p, pct_k = _npk_producto(prod)
        n = _kg_nutriente_aplicado(kg_fert, "kg", pct_n)
        p = _kg_nutriente_aplicado(kg_fert, "kg", pct_p)
        k = _kg_nutriente_aplicado(kg_fert, "kg", pct_k)
        if pct_n == pct_p == pct_k == 0.0 and kg_fert > 0:
            sin_analisis[prod] = sin_analisis.get(prod, 0.0) + kg_fert
        bucket = por_huerto.setdefault(
            h,
            {"huerto": h, "n": 0.0, "p": 0.0, "k": 0.0},
        )
        bucket["n"] += n
        bucket["p"] += p
        bucket["k"] += k
        totales["n"] += n
        totales["p"] += p
        totales["k"] += k
    filas = sorted(por_huerto.values(), key=lambda x: str(x["huerto"]))
    for row in filas:
        row["n_fmt"] = f_cant(row["n"])
        row["p_fmt"] = f_cant(row["p"])
        row["k_fmt"] = f_cant(row["k"])
    avisos = sorted(sin_analisis.keys())
    return {
        "filas": filas,
        "totales": totales,
        "n_fmt": f_cant(totales["n"]),
        "p_fmt": f_cant(totales["p"]),
        "k_fmt": f_cant(totales["k"]),
        "tiene_datos": bool(filas),
        "sin_analisis": avisos,
    }


def _fmt_modo_riego(modo: str | None, surcos: float | None, demo) -> str:
    modo_n = (modo or "horas").strip().lower()
    if modo_n == "surcos":
        return "Por surco"
    return "Tecnificado"


def fertilizantes_bodega_para_formulario() -> list[dict[str, Any]]:
    """Productos de bodega (familia fertilizante) para el formulario link."""
    demo = get_demo_module()
    conn = _conn()
    try:
        migrar_tabla(conn)
        placeholders = ",".join("?" * len(_FAMILIAS_FERTILIZANTE))
        rows = conn.execute(
            f"""SELECT id, producto, COALESCE(stock, 0), COALESCE(unidad_medida, 'kg'), familia
                FROM inventario
                WHERE UPPER(TRIM(COALESCE(familia, ''))) IN ({placeholders})
                ORDER BY producto COLLATE NOCASE""",
            _FAMILIAS_FERTILIZANTE,
        ).fetchall()
        out: list[dict[str, Any]] = []
        f_cant = getattr(demo, "f_cantidad", demo.f_decimal)
        for pid, nombre, stock, um, fam in rows:
            stock_f = float(stock or 0)
            um_s = str(um or "kg")
            nom = str(nombre or "").strip()
            out.append(
                {
                    "id": int(pid),
                    "nombre": nom,
                    "stock": stock_f,
                    "stock_fmt": f_cant(stock_f),
                    "um": um_s,
                    "familia": str(fam or ""),
                    "etiqueta": f"{nom} — {f_cant(stock_f)} {um_s} en bodega",
                }
            )
        return out
    finally:
        conn.close()


def parse_fertilizantes_request(form) -> list[dict[str, Any]]:
    """Lee filas fert_producto_id / fert_cantidad / fert_dosis_ha del POST."""
    pids = form.getlist("fert_producto_id")
    cants = form.getlist("fert_cantidad")
    dosis = form.getlist("fert_dosis_ha")
    n = max(len(pids), len(cants), len(dosis))
    lineas: list[dict[str, Any]] = []
    for i in range(n):
        pid_raw = pids[i] if i < len(pids) else ""
        cant_raw = cants[i] if i < len(cants) else ""
        dosis_raw = dosis[i] if i < len(dosis) else ""
        pid = str(pid_raw or "").strip()
        if not pid:
            continue
        try:
            cant = float(str(cant_raw or "0").replace(",", "."))
        except ValueError:
            cant = 0.0
        dosis_ha = None
        if str(dosis_raw or "").strip():
            try:
                dosis_ha = float(str(dosis_raw).replace(",", "."))
            except ValueError:
                dosis_ha = None
        lineas.append(
            {
                "producto_id": int(pid),
                "cantidad": cant,
                "dosis_ha": dosis_ha,
            }
        )
    return lineas


def _validar_lineas_fertilizantes(
    conn: sqlite3.Connection, lineas: list[dict[str, Any]]
) -> tuple[bool, str, list[dict[str, Any]]]:
    if not lineas:
        return False, "Agregue al menos un fertilizante de bodega.", []
    demo = get_demo_module()
    placeholders = ",".join("?" * len(_FAMILIAS_FERTILIZANTE))
    out: list[dict[str, Any]] = []
    for ln in lineas:
        pid = int(ln.get("producto_id") or 0)
        cant = float(ln.get("cantidad") or 0)
        dosis_ha = ln.get("dosis_ha")
        if pid <= 0:
            return False, "Seleccione un fertilizante válido.", []
        if cant <= 0:
            return False, "Indique cantidad mayor a cero en cada fertilizante.", []
        row = conn.execute(
            f"""SELECT id, producto, COALESCE(stock, 0), COALESCE(unidad_medida, 'kg'), familia
                FROM inventario WHERE id=?
                  AND UPPER(TRIM(COALESCE(familia, ''))) IN ({placeholders})""",
            (pid, *_FAMILIAS_FERTILIZANTE),
        ).fetchone()
        if not row:
            return False, "Uno de los fertilizantes no existe o no es de bodega.", []
        _id, nombre, stock, um, _fam = row
        stock_f = float(stock or 0)
        um_s = str(um or "kg")
        f_cant = getattr(demo, "f_cantidad", demo.f_decimal)
        if cant > stock_f + 1e-9:
            return (
                False,
                f"Stock insuficiente de {nombre}: pidió {f_cant(cant)} {um_s}, "
                f"hay {f_cant(stock_f)} {um_s}.",
                [],
            )
        out.append(
            {
                "producto_id": int(_id),
                "producto": str(nombre),
                "cantidad": cant,
                "dosis_ha": dosis_ha,
                "unidad": um_s,
            }
        )
    return True, "", out


def _guardar_fertilizantes(
    conn: sqlite3.Connection, codigo: str, lineas: list[dict[str, Any]]
) -> None:
    conn.execute("DELETE FROM riego_fertilizantes WHERE codigo=?", (codigo,))
    for ln in lineas:
        conn.execute(
            """INSERT INTO riego_fertilizantes
               (codigo, producto_id, producto, cantidad, dosis_ha, unidad)
               VALUES (?,?,?,?,?,?)""",
            (
                codigo,
                ln["producto_id"],
                ln["producto"],
                float(ln["cantidad"]),
                ln.get("dosis_ha"),
                ln.get("unidad") or "kg",
            ),
        )


def _listar_fertilizantes(conn: sqlite3.Connection, codigo: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT producto_id, producto, cantidad, dosis_ha, unidad
           FROM riego_fertilizantes WHERE codigo=? ORDER BY id""",
        (codigo,),
    ).fetchall()
    return [
        {
            "producto_id": int(r[0]),
            "producto": r[1],
            "cantidad": float(r[2] or 0),
            "dosis_ha": r[3],
            "unidad": r[4] or "kg",
        }
        for r in rows
    ]


def _aplicar_salidas_bodega_fertilizantes(
    conn: sqlite3.Connection,
    codigo: str,
    huerto_cc: str,
    fecha: str,
    demo,
) -> tuple[bool, str]:
    lineas = _listar_fertilizantes(conn, codigo)
    if not lineas:
        return True, ""
    um_default = getattr(demo, "DEFAULT_UNIDAD_INSUMO", "kg")
    for ln in lineas:
        pid = ln["producto_id"]
        cant = float(ln["cantidad"])
        row = conn.execute(
            "SELECT producto, precio_medio, COALESCE(unidad_medida, ?), COALESCE(stock, 0) "
            "FROM inventario WHERE id=?",
            (um_default, pid),
        ).fetchone()
        if not row:
            return False, f"Producto id {pid} no encontrado en bodega."
        nombre, pmp, um, stock = row[0], float(row[1] or 0), row[2], float(row[3] or 0)
        f_cant = getattr(demo, "f_cantidad", demo.f_decimal)
        if cant > stock + 1e-9:
            return (
                False,
                f"Stock insuficiente de {nombre} al autorizar "
                f"({f_cant(stock)} {um} disponible).",
            )
        conn.execute(
            """INSERT INTO movimientos
               (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado, unidad_medida)
               VALUES (?,?,?,?,?,?,?)""",
            (pid, "Salida", cant, fecha, huerto_cc, cant * pmp, um),
        )
        cur = conn.execute(
            "UPDATE inventario SET stock = stock - ? WHERE id = ? AND stock >= ?",
            (cant, pid, cant),
        )
        if cur.rowcount != 1:
            return False, f"No se pudo descontar {nombre} de bodega."
    return True, ""


def _ensure_mail_riego_usuarios(conn: sqlite3.Connection) -> None:
    from erp_solo_lectura import conn_en_solo_lectura

    if conn_en_solo_lectura(conn):
        return
    cols = {r[1] for r in conn.execute("PRAGMA table_info(usuarios)").fetchall()}
    if "mail_riego_bitacora" not in cols:
        conn.execute(
            "ALTER TABLE usuarios ADD COLUMN mail_riego_bitacora INTEGER DEFAULT 0"
        )


def _migrar_personal_regador(conn: sqlite3.Connection) -> None:
    from erp_solo_lectura import conn_en_solo_lectura

    if conn_en_solo_lectura(conn):
        return
    cols = {r[1] for r in conn.execute("PRAGMA table_info(personal)").fetchall()}
    if "autorizado_registro_riego" not in cols:
        conn.execute(
            "ALTER TABLE personal ADD COLUMN autorizado_registro_riego INTEGER DEFAULT 0"
        )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS autorizados_registro_riego_extra (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               nombre TEXT NOT NULL UNIQUE,
               activo INTEGER DEFAULT 1,
               fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP
           )"""
    )


def migrar_tabla(conn: sqlite3.Connection | None = None) -> None:
    from erp_solo_lectura import conn_en_solo_lectura

    own = conn is None
    if own:
        conn = _conn()
    try:
        if conn_en_solo_lectura(conn):
            return
        conn.execute(
            """CREATE TABLE IF NOT EXISTS riego (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   codigo TEXT UNIQUE,
                   fecha TEXT NOT NULL,
                   huerto TEXT NOT NULL,
                   horas REAL DEFAULT 0,
                   m3 REAL DEFAULT 0,
                   fert_dosis_ha REAL,
                   fert_total REAL,
                   regador TEXT DEFAULT '',
                   origen TEXT DEFAULT 'manual',
                   bitacora_codigo TEXT DEFAULT '',
                   creado_por TEXT DEFAULT '',
                   creado_en TEXT NOT NULL
               )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS riego_bitacora (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   codigo TEXT UNIQUE,
                   fecha TEXT NOT NULL,
                   huerto TEXT NOT NULL,
                   horas REAL DEFAULT 0,
                   m3 REAL DEFAULT 0,
                   fert_dosis_ha REAL,
                   fert_total REAL,
                   regador TEXT NOT NULL,
                   ip_origen TEXT,
                   creado_en TEXT NOT NULL,
                   estado TEXT DEFAULT 'pendiente',
                   autorizado_por TEXT DEFAULT '',
                   autorizado_en TEXT DEFAULT '',
                   rechazado_por TEXT DEFAULT '',
                   rechazado_en TEXT DEFAULT '',
                   rechazo_motivo TEXT DEFAULT ''
               )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS riego_fertilizantes (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   codigo TEXT NOT NULL,
                   producto_id INTEGER NOT NULL,
                   producto TEXT NOT NULL,
                   cantidad REAL DEFAULT 0,
                   dosis_ha REAL,
                   unidad TEXT DEFAULT 'kg'
               )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_riego_fert_codigo ON riego_fertilizantes(codigo)"
        )
        for tabla in ("riego", "riego_bitacora"):
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({tabla})").fetchall()}
            if "modo_riego" not in cols:
                conn.execute(
                    f"ALTER TABLE {tabla} ADD COLUMN modo_riego TEXT DEFAULT 'horas'"
                )
            if "surcos" not in cols:
                conn.execute(f"ALTER TABLE {tabla} ADD COLUMN surcos REAL")
        _ensure_riego_config_cc(conn)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_meta (clave TEXT PRIMARY KEY, valor TEXT)"
        )
        _migrar_personal_regador(conn)
        _ensure_mail_riego_usuarios(conn)
        row = conn.execute(
            "SELECT valor FROM schema_meta WHERE clave='registro_riego_token_v1'"
        ).fetchone()
        if not row:
            token = secrets.token_urlsafe(24)
            conn.execute(
                "INSERT INTO schema_meta (clave, valor) VALUES ('registro_riego_token_v1', ?)",
                (token,),
            )
        conn.commit()
    finally:
        if own:
            conn.close()


def regadores_autorizados_para_formulario() -> list[dict[str, str]]:
    conn = _conn()
    try:
        migrar_tabla(conn)
        out: list[dict[str, str]] = []
        rows = conn.execute(
            """SELECT id, nombre FROM personal
               WHERE COALESCE(estado, 'Activo') = 'Activo'
                 AND COALESCE(autorizado_registro_riego, 0) = 1
               ORDER BY nombre"""
        ).fetchall()
        for rid, nombre in rows:
            out.append({"id": f"p-{rid}", "nombre": str(nombre)})
        extras = conn.execute(
            """SELECT id, nombre FROM autorizados_registro_riego_extra
               WHERE COALESCE(activo, 1) = 1 ORDER BY nombre"""
        ).fetchall()
        for eid, nombre in extras:
            out.append({"id": f"e-{eid}", "nombre": str(nombre)})
        out.sort(key=lambda x: x["nombre"].casefold())
        return out
    finally:
        conn.close()


_COOKIE_OP_MAX_AGE = 180 * 24 * 3600


def cookie_nombre_operador() -> str:
    app = get_erp_app() or "erp"
    return f"erp_sr_op_{app}"


def cookie_path_operador() -> str:
    return "/"


def resolver_regador_por_id(
    op_id: str | None,
    regadores: list[dict[str, str]] | None = None,
) -> dict[str, str] | None:
    key = (op_id or "").strip()
    if not key:
        return None
    opts = regadores if regadores is not None else regadores_autorizados_para_formulario()
    for r in opts:
        if r.get("id") == key:
            return {"id": r["id"], "nombre": r["nombre"]}
    return None


def leer_operador_cookie(
    regadores: list[dict[str, str]] | None = None,
) -> dict[str, str] | None:
    return resolver_regador_por_id(
        request.cookies.get(cookie_nombre_operador()),
        regadores,
    )


def aplicar_cookie_operador(response, op_id: str) -> None:
    if not op_id:
        return
    response.set_cookie(
        cookie_nombre_operador(),
        op_id,
        max_age=_COOKIE_OP_MAX_AGE,
        httponly=True,
        samesite="Lax",
        secure=bool(request.is_secure),
        path=cookie_path_operador(),
    )


def _token_db(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT valor FROM schema_meta WHERE clave='registro_riego_token_v1'"
    ).fetchone()
    return str(row[0]).strip() if row and row[0] else None


def obtener_token() -> str:
    conn = _conn()
    try:
        migrar_tabla(conn)
        token = _token_db(conn)
        if not token:
            token = secrets.token_urlsafe(24)
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta (clave, valor) VALUES ('registro_riego_token_v1', ?)",
                (token,),
            )
            conn.commit()
        return token
    finally:
        conn.close()


def token_valido(recibido: str | None) -> bool:
    if not recibido or not recibido.strip():
        return False
    conn = _conn()
    try:
        esperado = _token_db(conn)
        if not esperado:
            return False
        return secrets.compare_digest(recibido.strip(), esperado)
    finally:
        conn.close()


def url_publica(token: str | None = None, op: str | None = None) -> str:
    from urllib.parse import quote

    tok = token or obtener_token()
    base = (
        os.environ.get("ERP_PUBLIC_BASE_URL")
        or current_app.config.get("ERP_PUBLIC_BASE_URL")
        or "https://erpmaster.cl"
    ).rstrip("/")
    prefix = (current_app.config.get("APPLICATION_ROOT") or "/agricola").rstrip("/")
    url = f"{base}{prefix}/registro-riego?t={tok}"
    op_id = (op or "").strip()
    if op_id:
        url += f"&op={quote(op_id, safe='')}"
    return url


def _destinatario_alerta() -> list[str]:
    demo = get_demo_module()
    if hasattr(demo, "obtener_destinatarios_riego_bitacora"):
        conn = demo.conectar_db()
        try:
            dest = list(demo.obtener_destinatarios_riego_bitacora(conn))
            if dest:
                return dest
        finally:
            conn.close()
    conn = _conn()
    try:
        migrar_tabla(conn)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(usuarios)").fetchall()}
        if "mail_riego_bitacora" in cols:
            rows = conn.execute(
                "SELECT email FROM usuarios WHERE COALESCE(mail_riego_bitacora, 0) = 1"
            ).fetchall()
            dest = [str(r[0]).strip() for r in rows if r and r[0]]
            if dest:
                return dest
    finally:
        conn.close()
    conf = demo._conf_smtp_prod() if hasattr(demo, "_conf_smtp_prod") else None
    if conf and conf.get("receptor_admin"):
        return [str(conf["receptor_admin"]).strip()]
    return []


def _nombre_erp() -> str:
    demo = get_demo_module()
    return str(getattr(demo, "NOMBRE_ERP", None) or "ERP Agrícola")


def _fmt_fert(dosis, total, demo) -> str:
    parts = []
    if dosis is not None and float(dosis or 0) > 0:
        parts.append(f"dosis {demo.f_decimal(dosis)} x ha")
    if total is not None and float(total or 0) > 0:
        parts.append(f"total {demo.f_decimal(total)}")
    return " · ".join(parts) if parts else "—"


def _fmt_fertilizantes(
    conn: sqlite3.Connection | None,
    codigo: str,
    demo,
    dosis=None,
    total=None,
) -> str:
    if conn and codigo:
        rows = _listar_fertilizantes(conn, codigo)
        if rows:
            f_cant = getattr(demo, "f_cantidad", demo.f_decimal)
            parts = []
            for ln in rows:
                p = str(ln["producto"])
                if float(ln["cantidad"] or 0) > 0:
                    p += f" {f_cant(ln['cantidad'])} {ln['unidad']}"
                if ln.get("dosis_ha") is not None and float(ln["dosis_ha"] or 0) > 0:
                    p += f" ({demo.f_decimal(ln['dosis_ha'])}×ha)"
                parts.append(p)
            return "; ".join(parts)
    return _fmt_fert(dosis, total, demo)


def enviar_alerta(registro: dict[str, Any]) -> bool:
    demo = get_demo_module()
    if not hasattr(demo, "_enviar_correo_html"):
        return False
    from erp_correo_html import html_esc, plantilla_correo_html

    dest = _destinatario_alerta()
    if not dest:
        return False
    codigo = registro.get("codigo", "")
    fert = registro.get("fert_txt", "—")
    interior = f"""
        <p style="color:#1F2933;line-height:1.55;margin:0 0 12px;">
          Se registró un riego desde <b>Registro Link</b>. Un administrador debe
          <b>autorizarlo</b> en Riego → Link riego para imputarlo al centro de costo.
        </p>
        <div style="background:#E3F2FD;border:1px solid #90CAF9;border-radius:10px;padding:16px 18px;">
          <p style="margin:6px 0;"><b>Código:</b> {html_esc(codigo)}</p>
          <p style="margin:6px 0;"><b>Fecha:</b> {html_esc(registro.get('fecha', ''))}</p>
          <p style="margin:6px 0;"><b>Huerto:</b> {html_esc(registro.get('huerto', ''))}</p>
          <p style="margin:6px 0;"><b>Horas:</b> {html_esc(registro.get('horas_fmt', ''))}</p>
          <p style="margin:6px 0;"><b>m³:</b> {html_esc(registro.get('m3_fmt', ''))}</p>
          <p style="margin:6px 0;"><b>Fertilización:</b> {html_esc(fert)}</p>
          <p style="margin:6px 0;"><b>Regador:</b> {html_esc(registro.get('regador', ''))}</p>
        </div>
    """
    cuerpo = plantilla_correo_html(
        "vencimiento",
        f"💧 {codigo} — Registro Link riego",
        interior,
        nombre_erp=_nombre_erp(),
        pie="Registro informativo vía link personal. Pendiente de autorización.",
    )
    asunto = f"💧 {codigo} | {registro.get('huerto', '')[:20]} | {registro.get('regador', '')[:20]}"
    return bool(demo._enviar_correo_html(asunto, cuerpo, dest))


def registrar_link(
    fecha: str,
    huerto: str,
    horas: float,
    m3: float,
    regador: str,
    *,
    fert_dosis_ha: float | None = None,
    fert_total: float | None = None,
    fertilizantes: list[dict[str, Any]] | None = None,
    modo_riego: str = "horas",
    surcos: float | None = None,
) -> dict[str, Any]:
    demo = get_demo_module()
    huerto = _norm_cc(huerto)
    regador = (regador or "").strip()
    modo_riego = _modo_efectivo(huerto, modo_riego)
    fh = demo.hora_chile().strftime("%Y-%m-%d %H:%M:%S")
    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip()

    conn = _conn()
    codigo = ""
    try:
        migrar_tabla(conn)
        m3_final, err_m3 = resolver_m3_registro(
            conn, huerto, float(horas or 0), float(m3 or 0),
            modo=modo_riego, surcos=surcos,
        )
        if err_m3:
            return {"ok": False, "msg": err_m3}
        m3 = m3_final
        lineas_fert: list[dict[str, Any]] = []
        if fertilizantes:
            ok_f, msg_f, lineas_fert = _validar_lineas_fertilizantes(conn, fertilizantes)
            if not ok_f:
                return {"ok": False, "msg": msg_f}
            fert_total = sum(float(ln["cantidad"]) for ln in lineas_fert) or fert_total

        conn.execute("BEGIN IMMEDIATE")
        codigo = _siguiente_codigo(conn)
        conn.execute(
            """INSERT INTO riego_bitacora
               (codigo, fecha, huerto, horas, m3, fert_dosis_ha, fert_total,
                regador, ip_origen, creado_en, estado, modo_riego, surcos)
               VALUES (?,?,?,?,?,?,?,?,?,?,'pendiente',?,?)""",
            (
                codigo,
                fecha,
                huerto,
                float(horas or 0),
                float(m3 or 0),
                fert_dosis_ha,
                fert_total,
                regador,
                ip or None,
                fh,
                modo_riego,
                None,
            ),
        )
        if lineas_fert:
            _guardar_fertilizantes(conn, codigo, lineas_fert)
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()

    conn_fmt = _conn()
    try:
        fert_txt = _fmt_fertilizantes(
            conn_fmt, codigo, demo, fert_dosis_ha, fert_total
        )
    finally:
        conn_fmt.close()

    registro = {
        "codigo": codigo,
        "fecha": fecha,
        "huerto": huerto,
        "horas_fmt": demo.f_decimal(horas),
        "m3_fmt": demo.f_decimal(m3),
        "fert_txt": fert_txt,
        "regador": regador,
    }
    mail_ok = enviar_alerta(registro)
    try:
        conn = _conn()
        det = (
            f"Link | {codigo} | {huerto} | {registro['horas_fmt']} h | "
            f"{registro['m3_fmt']} m3 | {fert_txt[:60]} | {regador[:40]}"
            + (" | mail OK" if mail_ok else " | mail falló")
        )
        conn.execute(
            "INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)",
            ("BITACORA-RIEGO", "RIEGO LINK", det, fh),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass
    return {"ok": True, "mail_ok": mail_ok, **registro}


def autorizar_registro(codigo: str, usuario: str) -> dict[str, Any]:
    demo = get_demo_module()
    codigo = (codigo or "").strip()
    usuario = (usuario or "").strip() or "admin"
    if not codigo:
        return {"ok": False, "msg": "Código inválido."}

    conn = _conn()
    try:
        migrar_tabla(conn)
        row = conn.execute(
            """SELECT codigo, fecha, huerto, horas, m3, fert_dosis_ha, fert_total,
                      regador, COALESCE(estado, 'pendiente'), modo_riego, surcos
               FROM riego_bitacora WHERE codigo=?""",
            (codigo,),
        ).fetchone()
        if not row:
            return {"ok": False, "msg": f"No se encontró {codigo}."}
        (
            codigo,
            fecha,
            huerto,
            horas,
            m3,
            fert_dosis_ha,
            fert_total,
            regador,
            estado,
            modo_riego,
            surcos,
        ) = row
        est = str(estado or "pendiente").lower()
        if est == "autorizado":
            return {"ok": False, "msg": f"{codigo} ya está autorizado."}
        if est == "rechazado":
            return {"ok": False, "msg": f"{codigo} está rechazado."}
        if est != "pendiente":
            return {"ok": False, "msg": f"{codigo} no está pendiente."}

        huerto_cc = str(huerto or "").strip().upper()
        if not huerto_cc:
            return {"ok": False, "msg": "Huerto inválido."}

        fh_auth = demo.hora_chile().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("BEGIN IMMEDIATE")
        ok_bod, msg_bod = _aplicar_salidas_bodega_fertilizantes(
            conn, codigo, huerto_cc, str(fecha)[:10], demo
        )
        if not ok_bod:
            conn.rollback()
            return {"ok": False, "msg": msg_bod}
        conn.execute(
            """INSERT INTO riego
               (codigo, fecha, huerto, horas, m3, fert_dosis_ha, fert_total,
                regador, origen, bitacora_codigo, creado_por, creado_en, modo_riego, surcos)
               VALUES (?,?,?,?,?,?,?,?, 'link', ?, ?, ?, ?, ?)""",
            (
                codigo,
                str(fecha)[:10],
                huerto_cc,
                float(horas or 0),
                float(m3 or 0),
                fert_dosis_ha,
                fert_total,
                regador,
                codigo,
                usuario,
                fh_auth,
                modo_riego or "horas",
                surcos,
            ),
        )
        conn.execute(
            """UPDATE riego_bitacora
               SET estado='autorizado', autorizado_por=?, autorizado_en=?
               WHERE codigo=?""",
            (usuario, fh_auth, codigo),
        )
        fert_resumen = _fmt_fertilizantes(conn, codigo, demo, fert_dosis_ha, fert_total)
        conn.execute(
            "INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)",
            (
                usuario,
                "RIEGO AUTORIZAR",
                f"{codigo} | {huerto_cc} | {demo.f_decimal(horas)} h | {demo.f_decimal(m3)} m3 | {fert_resumen[:80]}",
                fh_auth,
            ),
        )
        conn.commit()
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"ok": False, "msg": f"Error al autorizar: {exc}"}
    finally:
        conn.close()

    return {
        "ok": True,
        "msg": (
            f"{codigo} autorizado e imputado al CC {huerto_cc}. "
            f"{demo.f_decimal(horas)} h · {demo.f_decimal(m3)} m³."
        ),
        "codigo": codigo,
    }


def rechazar_registro(codigo: str, usuario: str, motivo: str = "") -> dict[str, Any]:
    demo = get_demo_module()
    codigo = (codigo or "").strip()
    usuario = (usuario or "").strip() or "admin"
    motivo = (motivo or "").strip()[:200]
    if not codigo:
        return {"ok": False, "msg": "Código inválido."}

    conn = _conn()
    try:
        migrar_tabla(conn)
        row = conn.execute(
            "SELECT COALESCE(estado, 'pendiente') FROM riego_bitacora WHERE codigo=?",
            (codigo,),
        ).fetchone()
        if not row:
            return {"ok": False, "msg": f"No se encontró {codigo}."}
        est = str(row[0] or "pendiente").lower()
        if est == "autorizado":
            return {"ok": False, "msg": f"{codigo} ya está autorizado."}
        if est == "rechazado":
            return {"ok": False, "msg": f"{codigo} ya está rechazado."}
        if est != "pendiente":
            return {"ok": False, "msg": f"{codigo} no está pendiente."}

        fh = demo.hora_chile().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """UPDATE riego_bitacora
               SET estado='rechazado', rechazado_por=?, rechazado_en=?, rechazo_motivo=?
               WHERE codigo=?""",
            (usuario, fh, motivo, codigo),
        )
        det = f"{codigo} rechazado"
        if motivo:
            det += f" | {motivo}"
        conn.execute(
            "INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)",
            (usuario, "RIEGO RECHAZAR", det, fh),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "ok": True,
        "msg": f"{codigo} rechazado (sin imputar al CC).",
        "codigo": codigo,
    }


def registrar_manual(
    fecha: str,
    huerto: str,
    horas: float,
    m3: float,
    regador: str,
    usuario: str,
    *,
    fert_dosis_ha: float | None = None,
    fert_total: float | None = None,
    fertilizantes: list[dict[str, Any]] | None = None,
    modo_riego: str = "horas",
    surcos: float | None = None,
) -> dict[str, Any]:
    demo = get_demo_module()
    huerto_cc = _norm_cc(huerto)
    if not huerto_cc:
        return {"ok": False, "msg": "Seleccione huerto."}
    modo_riego = _modo_efectivo(huerto_cc, modo_riego)

    conn = _conn()
    codigo = ""
    try:
        migrar_tabla(conn)
        m3_final, err_m3 = resolver_m3_registro(
            conn, huerto_cc, float(horas or 0), float(m3 or 0),
            modo=modo_riego, surcos=surcos,
        )
        if err_m3:
            return {"ok": False, "msg": err_m3}
        m3 = m3_final
        lineas_fert: list[dict[str, Any]] = []
        if fertilizantes:
            ok_f, msg_f, lineas_fert = _validar_lineas_fertilizantes(conn, fertilizantes)
            if not ok_f:
                return {"ok": False, "msg": msg_f}
            fert_total = sum(float(ln["cantidad"]) for ln in lineas_fert) or fert_total

        conn.execute("BEGIN IMMEDIATE")
        codigo = _siguiente_codigo(conn)
        fh = demo.hora_chile().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """INSERT INTO riego
               (codigo, fecha, huerto, horas, m3, fert_dosis_ha, fert_total,
                regador, origen, creado_por, creado_en, modo_riego, surcos)
               VALUES (?,?,?,?,?,?,?,?, 'manual', ?, ?, ?, ?)""",
            (
                codigo,
                str(fecha)[:10],
                huerto_cc,
                float(horas or 0),
                float(m3 or 0),
                fert_dosis_ha,
                fert_total,
                (regador or usuario or "").strip(),
                usuario,
                fh,
                modo_riego,
                None,
            ),
        )
        if lineas_fert:
            _guardar_fertilizantes(conn, codigo, lineas_fert)
            ok_bod, msg_bod = _aplicar_salidas_bodega_fertilizantes(
                conn, codigo, huerto_cc, str(fecha)[:10], demo
            )
            if not ok_bod:
                conn.rollback()
                return {"ok": False, "msg": msg_bod}

        fert_resumen = _fmt_fertilizantes(conn, codigo, demo, fert_dosis_ha, fert_total)
        conn.execute(
            "INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)",
            (
                usuario,
                "RIEGO MANUAL",
                f"{codigo} | {huerto_cc} | {demo.f_decimal(horas)} h | {demo.f_decimal(m3)} m3 | {fert_resumen[:80]}",
                fh,
            ),
        )
        conn.commit()
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"ok": False, "msg": f"No se pudo registrar: {exc}"}
    finally:
        conn.close()

    return {"ok": True, "msg": f"{codigo} registrado en {huerto_cc}.", "codigo": codigo}


def listar_bitacora(conn, limite: int = 50) -> list[dict[str, Any]]:
    demo = get_demo_module()
    migrar_tabla(conn)
    rows = conn.execute(
        """SELECT codigo, fecha, huerto, horas, m3, fert_dosis_ha, fert_total, regador,
                  COALESCE(estado, 'pendiente'), COALESCE(autorizado_por, ''),
                  COALESCE(autorizado_en, ''), COALESCE(rechazado_por, ''),
                  COALESCE(rechazado_en, ''), COALESCE(rechazo_motivo, ''), creado_en,
                  COALESCE(modo_riego, 'horas'), surcos
           FROM riego_bitacora ORDER BY id DESC LIMIT ?""",
        (limite,),
    ).fetchall()
    out = []
    for row in rows:
        (
            codigo,
            fecha,
            huerto,
            horas,
            m3,
            dosis,
            total,
            regador,
            estado,
            auth_por,
            auth_en,
            rej_por,
            rej_en,
            rej_mot,
            creado,
            modo_riego,
            surcos,
        ) = row
        est = (estado or "pendiente").lower()
        modo_txt = _fmt_modo_riego(modo_riego, surcos, demo)
        out.append(
            {
                "codigo": codigo or "—",
                "fecha": str(fecha or "")[:10],
                "huerto": huerto or "—",
                "horas": demo.f_decimal(horas),
                "m3": demo.f_decimal(m3),
                "modo_txt": modo_txt,
                "fert_txt": _fmt_fertilizantes(conn, codigo or "", demo, dosis, total),
                "regador": regador,
                "estado": est,
                "pendiente": est == "pendiente",
                "rechazado": est == "rechazado",
                "autorizado": est == "autorizado",
                "autorizado_por": auth_por,
                "autorizado_en": auth_en,
                "rechazado_por": rej_por,
                "rechazado_en": rej_en,
                "rechazo_motivo": rej_mot,
                "creado_en": creado,
            }
        )
    return out


def listar_historial(conn, limite: int = 100) -> list[dict[str, Any]]:
    demo = get_demo_module()
    migrar_tabla(conn)
    rows = conn.execute(
        """SELECT codigo, fecha, huerto, horas, m3, fert_dosis_ha, fert_total,
                  regador, origen, bitacora_codigo, creado_por, creado_en,
                  COALESCE(modo_riego, 'horas'), surcos
           FROM riego ORDER BY fecha DESC, id DESC LIMIT ?""",
        (limite,),
    ).fetchall()
    out = []
    for i, row in enumerate(rows, start=1):
        (
            codigo,
            fecha,
            huerto,
            horas,
            m3,
            dosis,
            total,
            regador,
            origen,
            bit_cod,
            creado_por,
            creado_en,
            modo_riego,
            surcos,
        ) = row
        out.append(
            {
                "num": i,
                "codigo": codigo or "—",
                "fecha": str(fecha or "")[:10],
                "huerto": huerto or "—",
                "horas": demo.f_decimal(horas),
                "m3": demo.f_decimal(m3),
                "modo_txt": _fmt_modo_riego(modo_riego, surcos, demo),
                "fert_txt": _fmt_fertilizantes(conn, codigo or "", demo, dosis, total),
                "regador": regador or "—",
                "origen": origen or "manual",
                "bitacora_codigo": bit_cod or "",
                "creado_por": creado_por or "",
                "creado_en": creado_en or "",
            }
        )
    return out


def contar_pendientes(conn) -> int:
    migrar_tabla(conn)
    row = conn.execute(
        """SELECT COUNT(*) FROM riego_bitacora
           WHERE LOWER(COALESCE(estado, 'pendiente')) = 'pendiente'"""
    ).fetchone()
    return int(row[0] or 0) if row else 0


def links_personales_regadores_demo() -> list[dict[str, str]]:
    """Enlaces visibles en DEMO — URL ficticia, no registra riego real."""
    migrar_tabla()
    out: list[dict[str, str]] = []
    for r in regadores_autorizados_para_formulario():
        op_id = str(r.get("id") or "").strip()
        nombre = str(r.get("nombre") or "").strip()
        if not op_id or not nombre:
            continue
        url = url_publica("demo-enlace-ejemplo-no-valido", op=op_id)
        out.append(
            {
                "id": op_id,
                "nombre": nombre,
                "url": url,
                "wa_url": "#",
                "demo_falso": True,
            }
        )
    return out


def links_personales_regadores() -> list[dict[str, str]]:
    from urllib.parse import quote

    migrar_tabla()
    tok = obtener_token()
    out: list[dict[str, str]] = []
    for r in regadores_autorizados_para_formulario():
        op_id = str(r.get("id") or "").strip()
        nombre = str(r.get("nombre") or "").strip()
        if not op_id or not nombre:
            continue
        url = url_publica(tok, op=op_id)
        out.append(
            {
                "id": op_id,
                "nombre": nombre,
                "url": url,
                "wa_url": "https://wa.me/?text="
                + quote(f"Registro Link riego — {nombre}:\n{url}", safe=""),
            }
        )
    return out


def habilitado() -> bool:
    return get_erp_app() in ("concepcion", "demo")
