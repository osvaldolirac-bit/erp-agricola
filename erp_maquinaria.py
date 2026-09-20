"""Maestra de maquinaria: catálogo con código para bitácora de mantenciones."""
from __future__ import annotations

import html as html_lib
import re

from erp_solo_lectura import conn_en_solo_lectura
import unicodedata

import pandas as pd
import streamlit as st

TIPOS_MAQUINARIA = [
    "Tractor",
    "Nebulizador",
    "Aplicador",
    "Implemento",
    "Grúa horquilla",
    "Camión",
    "Vehículo",
    "Motobomba",
    "Otro",
]

TIPOS_MAQUINARIA_TRACTOR = ("Tractor",)
TIPOS_MAQUINARIA_APLICACION = ("Nebulizador", "Aplicador", "Implemento", "Motobomba")
TIPOS_MAQUINARIA_PETROLEO = TIPOS_MAQUINARIA

TRACTORES_PREDETERMINADOS = (
    ("TRAC-SAME", "Tractor Same", "Tractor"),
    ("TRAC-CHINO", "Tractor Chino", "Tractor"),
    ("TRAC-MF", "Massey Ferguson", "Tractor"),
    ("TRAC-F4610", "Ford 4610 / Ford 4000", "Tractor"),
    ("TRAC-F3000", "Ford 3000", "Tractor"),
)

_PREFIJOS_TIPO_CODIGO = {
    "Tractor": "TRAC",
    "Nebulizador": "NEB",
    "Aplicador": "APL",
    "Implemento": "IMP",
    "Grúa horquilla": "GRU",
    "Camión": "CAM",
    "Vehículo": "VEH",
    "Motobomba": "MOT",
    "Otro": "MAQ",
}

_CODIGO_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{1,19}$")

# Texto histórico (normalizado) → código en maestra
_ALIASES_LEGACY_CODIGO = {
    "3000": "TRAC-F3000",
    "4610": "TRAC-F4610",
    "FORD 4000": "TRAC-F4610",
    "FORD 4610": "TRAC-F4610",
    "4000": "TRAC-F4610",
    "5000": "TRAC-06",
    "FORD 5000": "TRAC-06",
    "TRACTOR 3000": "TRAC-F3000",
    "CHINO": "TRAC-CHINO",
    "TRACTOR CHINO": "TRAC-CHINO",
    "SAME": "TRAC-SAME",
    "MF": "TRAC-MF",
    "MASSEY FERGUSON": "TRAC-MF",
    "MASSEY": "TRAC-MF",
    "FURGON": "VEH-03",
    "FURGON ROJO": "VEH-03",
    "JAC": "VEH-01",
    "CAMIONETA OLC": "VEH-01",
    "OLC": "VEH-01",
    "MERCEDES": "VEH-02",
    "MERCEDEZ": "VEH-02",
    "TOYOTA": "VEH-04",
    "TURBO NARANJA": "NEB-01",
    "TURBO VERDE": "NEB-02",
    "CAMION NEGO": "CAM-02",
    "GENERADOR": "MAQ-01",
    "GRUA HORQUILLA": "GRU-01",
    "GRUA HORQUILLA TOYOTA": "GRU-01",
    "GRÚA HORQUILLA": "GRU-01",
    "GRÚA HORQUILLA TOYOTA": "GRU-01",
}

# Equipos que faltaban en maestra al estandarizar registros antiguos
_EQUIPOS_LEGACY_MAESTRA = (
    ("CAM-01", "Camión", "Camión"),
    ("CAM-02", "Camión Nego", "Camión"),
    ("MAQ-01", "Generador", "Otro"),
)

_EQUIPOS_FIJOS_MAESTRA = (
    ("GRU-01", "Grúa horquilla Toyota", "Grúa horquilla"),
)

# Códigos antiguos en maestra → formato estándar PREFIJO-NN
_RENOMBRES_CODIGO_ESTANDAR = (
    ("FORD 5000", "TRAC-06", "Ford 5000"),
    ("TURBO VERDE", "NEB-02", "Turbo Verde"),
    ("FURGON", "VEH-03", "Furgón"),
    ("TOYOTA", "VEH-04", "Toyota"),
)

_CAMPOS_REFERENCIA_MAQUINARIA = (
    ("petroleo", "vehiculo"),
    ("libro_campo", "maquina"),
    ("libro_campo", "tractor"),
    ("bitacora_maquinaria", "id_maquinaria"),
)


def _normalizar_alias(txt):
    s = str(txt or "").strip().upper()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def _codigo_en_maestra(conn, codigo):
    row = conn.execute(
        "SELECT codigo FROM maestra_maquinaria WHERE UPPER(TRIM(codigo))=?",
        (_normalizar_codigo(codigo),),
    ).fetchone()
    return row[0] if row else None


def _asegurar_equipos_legacy_en_maestra(conn):
    max_ord = conn.execute("SELECT COALESCE(MAX(orden), -1) FROM maestra_maquinaria").fetchone()[0]
    for codigo, nombre, tipo in _EQUIPOS_LEGACY_MAESTRA:
        if not _codigo_en_maestra(conn, codigo):
            max_ord += 1
            _insertar_equipo_maestra(
                conn,
                codigo,
                nombre,
                tipo,
                max_ord,
                "Importado al estandarizar petróleo / libro de campo",
            )


def _sembrar_equipos_fijos_maestra(conn):
    max_ord = conn.execute("SELECT COALESCE(MAX(orden), -1) FROM maestra_maquinaria").fetchone()[0]
    for codigo, nombre, tipo in _EQUIPOS_FIJOS_MAESTRA:
        if not _codigo_en_maestra(conn, codigo):
            max_ord += 1
            _insertar_equipo_maestra(
                conn,
                codigo,
                nombre,
                tipo,
                max_ord,
                "Equipo fijo del inventario",
            )


def _construir_mapa_resolucion_legacy(conn):
    mapa = {_normalizar_alias(k): v for k, v in _ALIASES_LEGACY_CODIGO.items()}
    for codigo, nombre in conn.execute(
        "SELECT codigo, nombre FROM maestra_maquinaria"
    ).fetchall():
        mapa[_normalizar_alias(codigo)] = codigo
        mapa[_normalizar_alias(nombre)] = codigo
    return mapa


def mapear_legacy_a_codigo(conn, valor, mapa=None, resolver_fallback=True):
    """Convierte texto libre histórico al código de maestra, si es posible."""
    raw = str(valor or "").strip()
    if not raw:
        return None
    exacto = _codigo_en_maestra(conn, raw)
    if exacto:
        return exacto
    if mapa is None:
        mapa = _construir_mapa_resolucion_legacy(conn)
    key = _normalizar_alias(raw)
    if key in mapa:
        dest = mapa[key]
        return _codigo_en_maestra(conn, dest) or dest
    if resolver_fallback:
        cod = resolver_codigo_maquinaria(conn, raw)
        if cod:
            return _codigo_en_maestra(conn, cod) or cod
    return None


def migrar_registros_maquinaria_legacy(conn):
    """Actualiza petróleo y libro de campo: textos libres → códigos de maestra."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS maestra_maquinaria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT UNIQUE NOT NULL,
            nombre TEXT NOT NULL,
            tipo TEXT DEFAULT 'Otro',
            activo INTEGER DEFAULT 1,
            orden INTEGER DEFAULT 0,
            notas TEXT DEFAULT ''
        )"""
    )
    conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (clave TEXT PRIMARY KEY, valor TEXT)")
    cur = conn.cursor()
    if cur.execute(
        "SELECT 1 FROM schema_meta WHERE clave='maestra_maquinaria_v3_registros'"
    ).fetchone():
        return {"petroleo": 0, "libro_maquina": 0, "libro_tractor": 0, "bitacora": 0}

    _asegurar_equipos_legacy_en_maestra(conn)
    mapa = _construir_mapa_resolucion_legacy(conn)
    stats = {"petroleo": 0, "libro_maquina": 0, "libro_tractor": 0, "bitacora": 0}

    def _actualizar_campo(tabla, col_id, col_valor, stat_key):
        for row_id, val in conn.execute(
            f"SELECT {col_id}, {col_valor} FROM {tabla} "
            f"WHERE TRIM(COALESCE({col_valor}, '')) != ''"
        ):
            cod = mapear_legacy_a_codigo(conn, val, mapa, resolver_fallback=False)
            if cod and str(val).strip() != cod:
                conn.execute(
                    f"UPDATE {tabla} SET {col_valor}=? WHERE {col_id}=?",
                    (cod, row_id),
                )
                stats[stat_key] += 1

    _actualizar_campo("petroleo", "id", "vehiculo", "petroleo")
    _actualizar_campo("libro_campo", "id", "maquina", "libro_maquina")
    _actualizar_campo("libro_campo", "id", "tractor", "libro_tractor")
    _actualizar_campo("bitacora_maquinaria", "id", "id_maquinaria", "bitacora")

    cur.execute(
        "INSERT INTO schema_meta (clave, valor) VALUES ('maestra_maquinaria_v3_registros', '1')"
    )
    conn.commit()
    return stats


def _renombrar_codigo_maestra(conn, codigo_viejo, codigo_nuevo, nombre=None):
    viejo = _codigo_en_maestra(conn, codigo_viejo)
    if not viejo:
        return False
    if _normalizar_codigo(viejo) == _normalizar_codigo(codigo_nuevo):
        return False
    if _codigo_en_maestra(conn, codigo_nuevo):
        return False
    for tabla, columna in _CAMPOS_REFERENCIA_MAQUINARIA:
        conn.execute(
            f"UPDATE {tabla} SET {columna}=? WHERE UPPER(TRIM({columna}))=UPPER(TRIM(?))",
            (codigo_nuevo, viejo),
        )
    row = conn.execute(
        "SELECT nombre FROM maestra_maquinaria WHERE UPPER(TRIM(codigo))=?",
        (_normalizar_codigo(viejo),),
    ).fetchone()
    nom_final = str(nombre or (row[0] if row else codigo_nuevo)).strip()
    conn.execute(
        "UPDATE maestra_maquinaria SET codigo=?, nombre=? WHERE UPPER(TRIM(codigo))=?",
        (codigo_nuevo, nom_final, viejo),
    )
    return True


def normalizar_codigos_maestra_inventario(conn):
    """Renombra códigos legacy en maestra al formato PREFIJO-NN y actualiza referencias."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS maestra_maquinaria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT UNIQUE NOT NULL,
            nombre TEXT NOT NULL,
            tipo TEXT DEFAULT 'Otro',
            activo INTEGER DEFAULT 1,
            orden INTEGER DEFAULT 0,
            notas TEXT DEFAULT ''
        )"""
    )
    conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (clave TEXT PRIMARY KEY, valor TEXT)")
    cur = conn.cursor()
    if cur.execute(
        "SELECT 1 FROM schema_meta WHERE clave='maestra_maquinaria_v4_codigos'"
    ).fetchone():
        return {}

    renombres = {}
    for cod_viejo, cod_nuevo, nombre in _RENOMBRES_CODIGO_ESTANDAR:
        if _renombrar_codigo_maestra(conn, cod_viejo, cod_nuevo, nombre):
            renombres[cod_viejo] = cod_nuevo

    cur.execute(
        "INSERT INTO schema_meta (clave, valor) VALUES ('maestra_maquinaria_v4_codigos', '1')"
    )
    conn.commit()
    return renombres


def _normalizar_codigo(txt):
    return str(txt or "").strip().upper()


def _codigo_valido(txt):
    c = _normalizar_codigo(txt)
    return bool(c) and bool(_CODIGO_RE.match(c))


def _prefijo_codigo_tipo(tipo):
    return _PREFIJOS_TIPO_CODIGO.get(str(tipo or "").strip(), "MAQ")


def generar_codigo_maquinaria(conn, tipo):
    """Genera el siguiente código libre según tipo (ej. TRAC-01, CAM-02)."""
    migrar_maestra_maquinaria(conn)
    prefijo = _prefijo_codigo_tipo(tipo)
    for n in range(1, 1000):
        cod = f"{prefijo}-{n:02d}"
        if not conn.execute(
            "SELECT 1 FROM maestra_maquinaria WHERE UPPER(TRIM(codigo))=?",
            (cod,),
        ).fetchone():
            return cod
    return f"{prefijo}-{prefijo}{conn.execute('SELECT COUNT(*) FROM maestra_maquinaria').fetchone()[0] + 1:03d}"


def _insertar_equipo_maestra(conn, codigo, nombre, tipo, orden, notas=""):
    cod = _normalizar_codigo(codigo)
    if not cod or conn.execute(
        "SELECT 1 FROM maestra_maquinaria WHERE UPPER(TRIM(codigo))=?",
        (cod,),
    ).fetchone():
        return False
    conn.execute(
        """INSERT INTO maestra_maquinaria (codigo, nombre, tipo, activo, orden, notas)
           VALUES (?, ?, ?, 1, ?, ?)""",
        (cod, str(nombre).strip(), tipo, orden, notas),
    )
    return True


def _sembrar_tractores_predeterminados(conn):
    max_ord = conn.execute("SELECT COALESCE(MAX(orden), -1) FROM maestra_maquinaria").fetchone()[0]
    for codigo, nombre, tipo in TRACTORES_PREDETERMINADOS:
        if _insertar_equipo_maestra(conn, codigo, nombre, tipo, max_ord + 1):
            max_ord += 1


def migrar_maestra_maquinaria(conn):
    if conn_en_solo_lectura(conn):
        return
    conn.execute(
        """CREATE TABLE IF NOT EXISTS maestra_maquinaria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT UNIQUE NOT NULL,
            nombre TEXT NOT NULL,
            tipo TEXT DEFAULT 'Otro',
            activo INTEGER DEFAULT 1,
            orden INTEGER DEFAULT 0,
            notas TEXT DEFAULT ''
        )"""
    )
    conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (clave TEXT PRIMARY KEY, valor TEXT)")
    cur = conn.cursor()
    if not cur.execute("SELECT 1 FROM schema_meta WHERE clave='maestra_maquinaria_v1'").fetchone():
        existentes = {
            _normalizar_codigo(r[0])
            for r in conn.execute("SELECT codigo FROM maestra_maquinaria").fetchall()
        }
        max_ord = conn.execute("SELECT COALESCE(MAX(orden), -1) FROM maestra_maquinaria").fetchone()[0]
        for (raw,) in conn.execute(
            """SELECT DISTINCT TRIM(id_maquinaria) FROM bitacora_maquinaria
               WHERE id_maquinaria IS NOT NULL AND TRIM(id_maquinaria) != ''"""
        ).fetchall():
            cod = _normalizar_codigo(raw)
            if not cod or cod in existentes:
                continue
            max_ord += 1
            conn.execute(
                """INSERT OR IGNORE INTO maestra_maquinaria (codigo, nombre, tipo, activo, orden, notas)
                   VALUES (?, ?, 'Otro', 1, ?, 'Importado desde bitácora histórica')""",
                (cod, str(raw).strip(), max_ord),
            )
            existentes.add(cod)
        cur.execute("INSERT INTO schema_meta (clave, valor) VALUES ('maestra_maquinaria_v1', '1')")
    if not cur.execute("SELECT 1 FROM schema_meta WHERE clave='maestra_maquinaria_v2_tractores'").fetchone():
        _sembrar_tractores_predeterminados(conn)
        cur.execute(
            "INSERT INTO schema_meta (clave, valor) VALUES ('maestra_maquinaria_v2_tractores', '1')"
        )
    migrar_registros_maquinaria_legacy(conn)
    normalizar_codigos_maestra_inventario(conn)
    _sembrar_equipos_fijos_maestra(conn)
    conn.commit()


def sincronizar_maestra_maquinaria_desde_lc(conn_dst, lc_db_path: str | None = None) -> int:
    """Copia equipos faltantes desde La Concepción (INSERT OR IGNORE por código)."""
    import os
    import sqlite3

    path = (lc_db_path or os.environ.get("ERP_LC_DB") or "/root/erp_concepcion_v6.db").strip()
    if not path or not os.path.isfile(path):
        return 0
    migrar_maestra_maquinaria(conn_dst)
    src = sqlite3.connect(path)
    try:
        rows = src.execute(
            """SELECT codigo, nombre, tipo, activo, orden, notas
               FROM maestra_maquinaria ORDER BY orden, codigo"""
        ).fetchall()
    finally:
        src.close()
    n = 0
    for codigo, nombre, tipo, activo, orden, notas in rows:
        cur = conn_dst.execute(
            """INSERT OR IGNORE INTO maestra_maquinaria (codigo, nombre, tipo, activo, orden, notas)
               VALUES (?,?,?,?,?,?)""",
            (
                codigo,
                nombre,
                tipo or "Otro",
                int(activo if activo is not None else 1),
                int(orden or 0),
                notas or "",
            ),
        )
        if cur.rowcount:
            n += 1
    if n:
        conn_dst.commit()
    return n


def listar_maquinaria(conn, solo_activos=False, tipos=None):
    migrar_maestra_maquinaria(conn)
    q = """SELECT codigo, nombre, tipo, activo, notas, orden
           FROM maestra_maquinaria"""
    if solo_activos:
        q += " WHERE activo=1"
    q += " ORDER BY orden, codigo"
    rows = conn.execute(q).fetchall()
    items = [
        {
            "codigo": r[0],
            "nombre": r[1],
            "tipo": r[2] or "Otro",
            "activo": bool(r[3]),
            "notas": r[4] or "",
            "orden": int(r[5] or 0),
        }
        for r in rows
    ]
    if tipos:
        tipos_set = set(tipos)
        items = [m for m in items if m["tipo"] in tipos_set]
    return items


def resolver_codigo_maquinaria(conn, valor):
    """Resuelve código desde valor guardado (código, etiqueta o nombre legacy)."""
    migrar_maestra_maquinaria(conn)
    txt = str(valor or "").strip()
    if not txt:
        return None
    if "—" in txt:
        txt = txt.split("—", 1)[0].strip()
    cod = _normalizar_codigo(txt)
    if conn.execute(
        "SELECT codigo FROM maestra_maquinaria WHERE UPPER(TRIM(codigo))=?",
        (cod,),
    ).fetchone():
        return cod
    row = conn.execute(
        "SELECT codigo FROM maestra_maquinaria WHERE UPPER(TRIM(nombre))=UPPER(TRIM(?))",
        (txt,),
    ).fetchone()
    return row[0] if row else None


def texto_maquinaria_para_display(conn, valor):
    cod = resolver_codigo_maquinaria(conn, valor)
    if cod:
        return etiqueta_maquinaria(cod, nombre_maquinaria_por_codigo(conn, cod))
    return str(valor or "").strip()


def _lista_select_maquinaria(conn, tipos=None, valor_actual=None, solo_activos=True):
    items = listar_maquinaria(conn, solo_activos=solo_activos, tipos=tipos)
    if not items and tipos:
        items = listar_maquinaria(conn, solo_activos=solo_activos)
    codigos = {_normalizar_codigo(m["codigo"]) for m in items}
    if valor_actual:
        cod_act = resolver_codigo_maquinaria(conn, valor_actual)
        if cod_act and cod_act not in codigos:
            row = conn.execute(
                "SELECT codigo, nombre, tipo, activo, notas, orden FROM maestra_maquinaria WHERE UPPER(TRIM(codigo))=?",
                (cod_act,),
            ).fetchone()
            if row:
                items.insert(
                    0,
                    {
                        "codigo": row[0],
                        "nombre": row[1],
                        "tipo": row[2] or "Otro",
                        "activo": bool(row[3]),
                        "notas": row[4] or "",
                        "orden": int(row[5] or 0),
                    },
                )
        elif not cod_act and str(valor_actual).strip():
            legacy = str(valor_actual).strip()
            if legacy.upper() not in codigos:
                items.insert(
                    0,
                    {
                        "codigo": legacy,
                        "nombre": "(histórico — reasigne en maestra)",
                        "tipo": "Otro",
                        "activo": False,
                        "notas": "",
                        "orden": -1,
                    },
                )
    return items


def _indice_maquinaria(items, valor_actual, conn):
    if not items:
        return 0
    cod = resolver_codigo_maquinaria(conn, valor_actual)
    if cod:
        for i, m in enumerate(items):
            if _normalizar_codigo(m["codigo"]) == cod:
                return i
    if valor_actual:
        legacy = str(valor_actual).strip()
        for i, m in enumerate(items):
            if str(m["codigo"]).strip() == legacy:
                return i
    return 0


def etiqueta_maquinaria(codigo, nombre):
    return f"{_normalizar_codigo(codigo)} — {str(nombre or '').strip()}"


def nombre_maquinaria_por_codigo(conn, codigo):
    migrar_maestra_maquinaria(conn)
    row = conn.execute(
        "SELECT nombre FROM maestra_maquinaria WHERE UPPER(TRIM(codigo))=?",
        (_normalizar_codigo(codigo),),
    ).fetchone()
    if row:
        return row[0]
    return str(codigo or "").strip()


def contar_eventos_maquinaria(conn, codigo):
    return conn.execute(
        "SELECT COUNT(*) FROM bitacora_maquinaria WHERE UPPER(TRIM(id_maquinaria))=?",
        (_normalizar_codigo(codigo),),
    ).fetchone()[0]


def opciones_filtro_maquinaria(conn):
    """Opciones para filtro historial: maestra + códigos legacy en bitácora."""
    migrar_maestra_maquinaria(conn)
    opts = {}
    for m in listar_maquinaria(conn):
        opts[m["codigo"]] = etiqueta_maquinaria(m["codigo"], m["nombre"])
    for (raw,) in conn.execute(
        """SELECT DISTINCT TRIM(id_maquinaria) FROM bitacora_maquinaria
           WHERE id_maquinaria IS NOT NULL AND TRIM(id_maquinaria) != ''"""
    ).fetchall():
        cod = _normalizar_codigo(raw)
        if cod and cod not in opts:
            opts[cod] = f"{cod} (histórico)"
    return sorted(opts.items(), key=lambda x: x[1])


def render_select_maquinaria(
    conn,
    key="maq_reg_id",
    label="Maquinaria",
    tipos=None,
    valor_actual=None,
    permitir_vacio=False,
):
    """Selectbox de maquinaria activa. Devuelve código seleccionado o None."""
    activas = _lista_select_maquinaria(conn, tipos=tipos, valor_actual=valor_actual, solo_activos=True)
    if not activas:
        st.warning(
            "No hay maquinaria registrada. El administrador debe cargar equipos en "
            "**Administración → Maestra maquinaria**."
        )
        return None
    labels = [etiqueta_maquinaria(m["codigo"], m["nombre"]) for m in activas]
    opciones = list(range(len(labels)))
    if permitir_vacio:
        labels = ["— Sin selección —"] + labels
        opciones = list(range(len(labels)))
    idx_def = _indice_maquinaria(activas, valor_actual, conn)
    if permitir_vacio:
        idx_def += 1
    idx = st.selectbox(
        label,
        opciones,
        index=min(idx_def, len(opciones) - 1),
        format_func=lambda i: labels[i],
        key=key,
    )
    if permitir_vacio and idx == 0:
        return None
    real_idx = idx - 1 if permitir_vacio else idx
    return activas[real_idx]["codigo"]


def enriquecer_columna_maquinaria(conn, df, columna):
    if df is None or df.empty or columna not in df.columns:
        return df
    out = df.copy()
    out[columna] = out[columna].apply(lambda v: texto_maquinaria_para_display(conn, v))
    return out


def render_admin_tab_maestra_maquinaria(conn, registrar_accion):
    st.markdown("#### Maestra de maquinaria")
    st.caption(
        "Catálogo con **código automático** usado en **Maquinaria**, **Libro de Campo** y **Petróleo**. "
        "Elija el **tipo de equipo** y el sistema asigna el código (TRAC-01, CAM-01, NEB-01, etc.)."
    )
    migrar_maestra_maquinaria(conn)
    maqs = listar_maquinaria(conn)
    df = pd.DataFrame(
        [
            {
                "Código": m["codigo"],
                "Nombre": m["nombre"],
                "Tipo": m["tipo"],
                "Activo": "Sí" if m["activo"] else "No",
                "Eventos": contar_eventos_maquinaria(conn, m["codigo"]),
                "Notas": m["notas"],
            }
            for m in maqs
        ]
    )
    if df.empty:
        st.info("Aún no hay equipos registrados. Use el formulario inferior para agregar el primero.")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)

    tipo_nuevo = st.selectbox(
        "Tipo de equipo",
        TIPOS_MAQUINARIA,
        key="maq_adm_tipo",
        help="El código se genera automáticamente según el tipo (TRAC, NEB, CAM, IMP, etc.).",
    )
    cod_preview = generar_codigo_maquinaria(conn, tipo_nuevo)
    st.markdown(
        f"<div style='background:#E8F5E9;border-left:4px solid #2E7D32;padding:8px 12px;border-radius:6px;margin-bottom:12px;'>"
        f"Próximo código disponible: <b>{cod_preview}</b></div>",
        unsafe_allow_html=True,
    )

    with st.form("maq_admin_nueva", clear_on_submit=True):
        st.markdown("##### Registrar equipo")
        nom_n = st.text_input(
            "Nombre / descripción",
            placeholder="Ej. Ford 4610, Rastra de discos, Camión fumigación",
            key="maq_adm_nom",
        )
        notas_n = st.text_input("Notas (opcional)", key="maq_adm_notas")
        if st.form_submit_button("➕ REGISTRAR MAQUINARIA"):
            nom = str(nom_n or "").strip()
            if not nom:
                st.error("Ingrese el nombre o descripción del equipo.")
            else:
                cod = generar_codigo_maquinaria(conn, tipo_nuevo)
                if conn.execute(
                    "SELECT 1 FROM maestra_maquinaria WHERE UPPER(TRIM(codigo))=?",
                    (cod,),
                ).fetchone():
                    st.error(f"El código «{cod}» ya fue tomado. Intente de nuevo.")
                else:
                    orden = conn.execute(
                        "SELECT COALESCE(MAX(orden), -1) + 1 FROM maestra_maquinaria"
                    ).fetchone()[0]
                    conn.execute(
                        """INSERT INTO maestra_maquinaria (codigo, nombre, tipo, activo, orden, notas)
                           VALUES (?, ?, ?, 1, ?, ?)""",
                        (cod, nom, tipo_nuevo, orden, notas_n.strip()),
                    )
                    conn.commit()
                    registrar_accion("MAESTRA MAQ", f"Nuevo: {cod} — {nom} ({tipo_nuevo})")
                    st.success(f"Equipo registrado: **{cod}** — {nom}")
                    st.rerun()

    if maqs:
        st.divider()
        with st.form("maq_admin_editar"):
            st.markdown("##### Editar equipo")
            codigos = [m["codigo"] for m in maqs]
            sel = st.selectbox(
                "Equipo",
                codigos,
                format_func=lambda c: etiqueta_maquinaria(c, nombre_maquinaria_por_codigo(conn, c)),
                key="maq_adm_edit_sel",
            )
            actual = next(m for m in maqs if m["codigo"] == sel)
            e1, e2, e3 = st.columns(3)
            nom_e = e1.text_input("Nombre", value=actual["nombre"], key="maq_adm_edit_nom")
            tipo_e = e2.selectbox(
                "Tipo",
                TIPOS_MAQUINARIA,
                index=TIPOS_MAQUINARIA.index(actual["tipo"])
                if actual["tipo"] in TIPOS_MAQUINARIA
                else len(TIPOS_MAQUINARIA) - 1,
                key="maq_adm_edit_tipo",
            )
            activo_e = e3.checkbox("Activo (visible al registrar eventos)", value=actual["activo"], key="maq_adm_edit_act")
            notas_e = st.text_input("Notas", value=actual["notas"], key="maq_adm_edit_notas")
            if st.form_submit_button("💾 GUARDAR CAMBIOS"):
                nom = str(nom_e or "").strip()
                if not nom:
                    st.error("El nombre es obligatorio.")
                else:
                    conn.execute(
                        """UPDATE maestra_maquinaria
                           SET nombre=?, tipo=?, activo=?, notas=?
                           WHERE UPPER(TRIM(codigo))=?""",
                        (nom, tipo_e, 1 if activo_e else 0, notas_e.strip(), sel),
                    )
                    conn.commit()
                    registrar_accion("MAESTRA MAQ", f"Editado: {sel}")
                    st.success("Equipo actualizado.")
                    st.rerun()

        st.divider()
        with st.form("maq_admin_eliminar"):
            st.markdown("##### Eliminar equipo")
            st.caption("Solo se puede eliminar si no tiene eventos en la bitácora. Use «Inactivo» para ocultarlo.")
            sel_del = st.selectbox(
                "Equipo a eliminar",
                codigos,
                format_func=lambda c: etiqueta_maquinaria(c, nombre_maquinaria_por_codigo(conn, c)),
                key="maq_adm_del_sel",
            )
            confirm = st.checkbox("Confirmo eliminar este registro", key="maq_adm_del_conf")
            if st.form_submit_button("🗑️ ELIMINAR"):
                n_ev = contar_eventos_maquinaria(conn, sel_del)
                if n_ev > 0:
                    st.error(f"No se puede eliminar: tiene {n_ev} evento(s) en la bitácora. Desactívelo en su lugar.")
                elif not confirm:
                    st.error("Marque la casilla de confirmación.")
                else:
                    conn.execute(
                        "DELETE FROM maestra_maquinaria WHERE UPPER(TRIM(codigo))=?",
                        (sel_del,),
                    )
                    conn.commit()
                    registrar_accion("MAESTRA MAQ", f"Eliminado: {sel_del}")
                    st.success("Equipo eliminado.")
                    st.rerun()


ESTADOS_CASO_MAQ = (
    "Abierto",
    "En Observación",
    "En Reparación",
    "Cerrado conforme",
    "Cerrado desconforme",
)
ETIQUETAS_MAQ_CERRADAS = (
    "CERRADO CONFORME",
    "CERRADO DESCONFORME",
    "CERRADO",
    "CONFORME",
)
_MAPA_ESTADO_CASO_LEGACY = {
    "CONFORME": "Cerrado conforme",
    "CERRADO": "Cerrado conforme",
    "CERRADO CONFORME": "Cerrado conforme",
    "CERRADO DESCONFORME": "Cerrado desconforme",
    "PENDIENTE": "Abierto",
    "EN OBSERVACIÓN": "En Observación",
    "EN OBSERVACION": "En Observación",
    "CRÍTICO": "En Reparación",
    "CRITICO": "En Reparación",
    "ABIERTO": "Abierto",
    "EN REPARACIÓN": "En Reparación",
    "EN REPARACION": "En Reparación",
}

PALETA_PETROLEO_MAQ = (
    "#1565C0",
    "#2E7D32",
    "#E65100",
    "#6A1B9A",
    "#00838F",
    "#C62828",
    "#F9A825",
    "#5D4037",
    "#455A64",
    "#AD1457",
)


def migrar_bitacora_info_post(conn):
    """Columna resumen de última observación del caso."""
    if conn_en_solo_lectura(conn):
        return
    cols = [r[1] for r in conn.execute("PRAGMA table_info(bitacora_maquinaria)").fetchall()]
    if "info_post" not in cols:
        conn.execute("ALTER TABLE bitacora_maquinaria ADD COLUMN info_post TEXT")
        conn.commit()


def migrar_seguimiento_caso_maquinaria(conn):
    """Estados de caso + historial de observaciones por etapa."""
    if conn_en_solo_lectura(conn):
        return
    migrar_bitacora_info_post(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bitacora_maq_observaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cod_registro TEXT NOT NULL,
            estado TEXT NOT NULL,
            observacion TEXT,
            fecha TEXT,
            usuario TEXT
        )
        """
    )
    # Normaliza etiquetas legacy → flujo nuevo
    rows = conn.execute(
        "SELECT id, etiqueta_ingreso FROM bitacora_maquinaria"
    ).fetchall()
    for rid, etiq in rows:
        nuevo = normalizar_estado_caso_maq(etiq)
        actual = str(etiq or "").strip()
        if actual != nuevo:
            conn.execute(
                "UPDATE bitacora_maquinaria SET etiqueta_ingreso=? WHERE id=?",
                (nuevo, rid),
            )
    conn.commit()


def normalizar_estado_caso_maq(etiqueta) -> str:
    key = str(etiqueta or "").strip().upper()
    if not key:
        return "Abierto"
    if key in _MAPA_ESTADO_CASO_LEGACY:
        return _MAPA_ESTADO_CASO_LEGACY[key]
    for est in ESTADOS_CASO_MAQ:
        if est.upper() == key:
            return est
    return "Abierto"


def etiqueta_maquinaria_cerrada(etiqueta):
    e = normalizar_estado_caso_maq(etiqueta)
    return e in {"Cerrado conforme", "Cerrado desconforme"}


def listar_observaciones_caso(conn, cod_registro):
    migrar_seguimiento_caso_maquinaria(conn)
    rows = conn.execute(
        """
        SELECT id, estado, observacion, fecha, usuario
        FROM bitacora_maq_observaciones
        WHERE cod_registro=?
        ORDER BY id ASC
        """,
        (str(cod_registro).strip(),),
    ).fetchall()
    return [
        {
            "id": r[0],
            "estado": r[1],
            "observacion": r[2] or "",
            "fecha": (r[3] or "")[:16],
            "usuario": r[4] or "",
        }
        for r in rows
    ]


def actualizar_caso_maquinaria(
    conn,
    cod_registro,
    *,
    estado: str | None = None,
    observacion: str = "",
    usuario: str = "",
    fecha: str | None = None,
) -> tuple[bool, str]:
    """Actualiza estado del caso y registra observación de la etapa."""
    from datetime import datetime

    migrar_seguimiento_caso_maquinaria(conn)
    cod = str(cod_registro or "").strip()
    if not cod:
        return False, "Evento no indicado."
    row = conn.execute(
        "SELECT etiqueta_ingreso FROM bitacora_maquinaria WHERE cod_registro=?",
        (cod,),
    ).fetchone()
    if not row:
        return False, "Evento no encontrado."

    estado_actual = normalizar_estado_caso_maq(row[0])
    if estado is None or str(estado).strip() == "":
        estado_nuevo = estado_actual
    else:
        estado_nuevo = normalizar_estado_caso_maq(estado)
        if estado_nuevo not in ESTADOS_CASO_MAQ:
            return False, "Estado de caso inválido."

    obs = (observacion or "").strip()
    if estado_nuevo != estado_actual and not obs:
        return False, "Al cambiar el estado debe anotar una observación."
    if estado_nuevo == estado_actual and not obs:
        return False, "Escriba una observación para registrar el seguimiento."

    if estado_nuevo != estado_actual:
        conn.execute(
            "UPDATE bitacora_maquinaria SET etiqueta_ingreso=? WHERE cod_registro=?",
            (estado_nuevo, cod),
        )

    when = (fecha or datetime.now().strftime("%Y-%m-%d %H:%M")).strip()
    conn.execute(
        """
        INSERT INTO bitacora_maq_observaciones (cod_registro, estado, observacion, fecha, usuario)
        VALUES (?,?,?,?,?)
        """,
        (cod, estado_nuevo, obs, when, (usuario or "").strip() or None),
    )
    # Resumen visible en listado / PDF
    conn.execute(
        "UPDATE bitacora_maquinaria SET info_post=? WHERE cod_registro=?",
        (f"[{estado_nuevo}] {obs}", cod),
    )
    conn.commit()
    return True, f"Caso {cod}: {estado_nuevo}."


def actualizar_info_post_bitacora(conn, cod_registro, info_post):
    """Compat: guarda nota como observación en el estado actual."""
    row = conn.execute(
        "SELECT etiqueta_ingreso FROM bitacora_maquinaria WHERE cod_registro=?",
        (str(cod_registro).strip(),),
    ).fetchone()
    if not row:
        return False
    ok, _ = actualizar_caso_maquinaria(
        conn,
        cod_registro,
        estado=row[0],
        observacion=info_post or "",
    )
    return ok


def _codigos_maquinaria_en_reparacion(conn):
    """Equipos cuyo último evento de bitácora aún no está Cerrado."""
    migrar_maestra_maquinaria(conn)
    migrar_seguimiento_caso_maquinaria(conn)
    rows = conn.execute(
        """SELECT UPPER(TRIM(b.id_maquinaria)) AS cod, b.etiqueta_ingreso
           FROM bitacora_maquinaria b
           INNER JOIN (
               SELECT UPPER(TRIM(id_maquinaria)) AS maq, MAX(id) AS max_id
               FROM bitacora_maquinaria
               WHERE TRIM(COALESCE(id_maquinaria, '')) != ''
               GROUP BY UPPER(TRIM(id_maquinaria))
           ) lx ON b.id = lx.max_id"""
    ).fetchall()
    out = set()
    for cod, etiq in rows:
        if cod and not etiqueta_maquinaria_cerrada(etiq):
            out.add(str(cod))
    return out


def contar_maquinaria_casos_abiertos(conn):
    return len(_codigos_maquinaria_en_reparacion(conn))


def listar_casos_abiertos_maquinaria(conn):
    migrar_maestra_maquinaria(conn)
    migrar_seguimiento_caso_maquinaria(conn)
    rows = conn.execute(
        """SELECT b.id, b.cod_registro, b.id_maquinaria, b.etiqueta_ingreso, b.fecha_evento,
                  b.tipo_evento, b.detalle_mantenimiento,
                  COALESCE(m.nombre, b.id_maquinaria) AS nombre
           FROM bitacora_maquinaria b
           LEFT JOIN maestra_maquinaria m
             ON UPPER(TRIM(m.codigo)) = UPPER(TRIM(b.id_maquinaria))
           INNER JOIN (
               SELECT UPPER(TRIM(id_maquinaria)) AS maq, MAX(id) AS max_id
               FROM bitacora_maquinaria
               WHERE TRIM(COALESCE(id_maquinaria, '')) != ''
               GROUP BY UPPER(TRIM(id_maquinaria))
           ) lx ON b.id = lx.max_id
           ORDER BY b.fecha_evento DESC, b.id DESC"""
    ).fetchall()
    out = []
    for r in rows:
        if etiqueta_maquinaria_cerrada(r[3]):
            continue
        out.append(
            {
                "id": r[0],
                "cod_registro": r[1],
                "codigo": r[2],
                "etiqueta": normalizar_estado_caso_maq(r[3]),
                "fecha": r[4],
                "tipo": r[5],
                "detalle": r[6],
                "nombre": r[7],
            }
        )
    return out


def cerrar_caso_maquinaria(conn, cod_registro, etiqueta_cierre="Cerrado conforme", observacion="", usuario=""):
    etiq = normalizar_estado_caso_maq(etiqueta_cierre or "Cerrado conforme")
    if not etiqueta_maquinaria_cerrada(etiq):
        etiq = "Cerrado conforme"
    obs = (observacion or "").strip() or "Caso cerrado — equipo vuelve a operación."
    ok, msg = actualizar_caso_maquinaria(
        conn,
        cod_registro,
        estado=etiq,
        observacion=obs,
        usuario=usuario,
    )
    if not ok:
        raise ValueError(msg)


def aplicar_badge_menu_maquinaria(opts, conn):
    from demo_web.services.sidebar_badges import aplicar_badges_labels_menu

    return aplicar_badges_labels_menu(opts, conn)


MAQ_WIDGET_CSS = """
.maq-widget-petroleo-wrap{background:linear-gradient(135deg,#FFF8F0 0%,#FFF3E0 100%);border:1px solid #FFCC80;border-radius:14px;padding:0.85rem 0.95rem;text-align:center;max-width:100%;margin-left:auto;box-shadow:0 6px 16px rgba(230,81,0,0.12);}
.maq-widget-petroleo-wrap .maq-widget-kicker{font-size:0.8rem;font-weight:800;color:#E65100;margin-bottom:0.55rem;text-align:left;letter-spacing:0.02em;}
.maq-widget-petroleo-wrap .maq-donut-trio{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:0.55rem;align-items:start;}
.maq-widget-petroleo-wrap .maq-pet-col{background:rgba(255,255,255,0.72);border:1px solid #FFE0B2;border-radius:10px;padding:0.45rem 0.35rem 0.5rem;min-width:0;}
.maq-widget-petroleo-wrap .maq-pet-col-head{margin-bottom:0.35rem;padding-bottom:0.3rem;border-bottom:1px solid #FFE0B2;}
.maq-widget-petroleo-wrap .maq-pet-col-tit{font-size:0.68rem;font-weight:800;color:#BF360C;line-height:1.25;text-transform:uppercase;letter-spacing:0.03em;}
.maq-widget-petroleo-wrap .maq-pet-col-sub{font-size:0.62rem;font-weight:600;color:#5F6B7A;margin-top:0.12rem;line-height:1.2;}
.maq-widget-petroleo-wrap .maq-pet-col .maq-mini-donut{text-align:center;margin:0.15rem auto 0.25rem;}
.maq-widget-petroleo-wrap .maq-mini-ring{width:84px;height:84px;border-radius:50%;position:relative;margin:0 auto;}
.maq-widget-petroleo-wrap .maq-mini-hole{position:absolute;width:52px;height:52px;background:#fff;border-radius:50%;top:50%;left:50%;transform:translate(-50%,-50%);box-shadow:inset 0 0 0 1px rgba(230,81,0,0.12);}
.maq-widget-petroleo-wrap .maq-mini-center{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);text-align:center;z-index:2;line-height:1.05;}
.maq-widget-petroleo-wrap .maq-mini-num{font-size:0.72rem;font-weight:800;color:#E65100;}
.maq-widget-petroleo-wrap .maq-mini-lbl{font-size:0.52rem;font-weight:700;color:#6B7B8C;text-transform:uppercase;}
.maq-widget-petroleo-wrap .maq-ley-col{margin-top:0.1rem;text-align:left;padding:0 0.15rem;}
.maq-widget-petroleo-wrap .maq-ley-fila{display:flex;align-items:center;gap:0.25rem;font-size:0.6rem;line-height:1.35;color:#37474F;margin-bottom:0.1rem;}
.maq-widget-petroleo-wrap .maq-ley-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0;}
.maq-widget-petroleo-wrap .maq-ley-nom{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.maq-widget-petroleo-wrap .maq-ley-pct{font-weight:800;color:#E65100;min-width:1.5rem;text-align:right;flex-shrink:0;}
.maq-widget-petroleo-wrap .maq-pet-col-total{font-size:0.64rem;font-weight:700;color:#37474F;margin-top:0.35rem;padding-top:0.3rem;border-top:1px dashed #FFCC80;}
.maq-widget-petroleo-wrap .maq-pet-col-total b{color:#E65100;font-weight:800;}
.maq-widget-petroleo-wrap .maq-leyenda-vacia{font-size:0.6rem;color:#90A4AE;font-style:italic;text-align:center;padding:0.25rem 0;}
.maq-widget-petroleo-wrap .maq-widget-foot{font-size:0.62rem;color:#78909C;margin-top:0.5rem;line-height:1.35;text-align:left;border-top:1px solid #FFE0B2;padding-top:0.4rem;}
@media (max-width:991px){
.maq-widget-petroleo-wrap .maq-donut-trio{grid-template-columns:1fr;}
.maq-widget-petroleo-wrap{max-width:280px;}
}
"""


def _paleta_equipos_widget(datos_temp, datos_mes):
    cods = []
    seen = set()
    for datos in (datos_temp, datos_mes):
        for cod, _nom, _lts in datos:
            key = str(cod or "").strip().upper()
            if key and key not in seen:
                seen.add(key)
                cods.append(key)
    return {
        cod: PALETA_PETROLEO_MAQ[i % len(PALETA_PETROLEO_MAQ)]
        for i, cod in enumerate(cods)
    }


def _color_equipo_petroleo(codigo, paleta=None):
    cod = str(codigo or "").strip().upper()
    if paleta and cod in paleta:
        return paleta[cod]
    if not cod:
        return PALETA_PETROLEO_MAQ[0]
    idx = sum(ord(c) for c in cod) % len(PALETA_PETROLEO_MAQ)
    return PALETA_PETROLEO_MAQ[idx]


def _consolidar_litros_por_codigo(datos_raw):
    """Suma litros por código canónico (evita duplicar alias legacy)."""
    acum = {}
    nombres = {}
    for cod, nom, lts in datos_raw:
        key = str(cod or "").strip().upper() or str(nom or "").strip().upper()
        if not key:
            continue
        acum[key] = acum.get(key, 0.0) + float(lts or 0)
        if key not in nombres or len(str(nom or "")) > len(str(nombres[key] or "")):
            nombres[key] = str(nom or cod or key).strip()
    out = [(k, nombres.get(k, k), v) for k, v in acum.items() if v > 0]
    out.sort(key=lambda x: -x[2])
    return out


def _gasto_petroleo_por_cc(conn, fecha_desde, fecha_hasta):
    rows = conn.execute(
        """SELECT TRIM(centro_costo) AS cc, SUM(COALESCE(valor_imputado, 0)) AS gasto
           FROM petroleo
           WHERE tipo = 'Salida'
             AND date(fecha) BETWEEN date(?) AND date(?)
             AND TRIM(COALESCE(centro_costo, '')) != ''
           GROUP BY TRIM(centro_costo)
           HAVING gasto > 0
           ORDER BY gasto DESC""",
        (str(fecha_desde), str(fecha_hasta)),
    ).fetchall()
    out = []
    for cc, gasto in rows:
        nom = str(cc or "").strip()
        if not nom:
            continue
        out.append((nom, nom, float(gasto or 0)))
    return out


def _paleta_cc_widget(datos_cc):
    ccs = []
    seen = set()
    for cc, _nom, _val in datos_cc:
        key = str(cc or "").strip().upper()
        if key and key not in seen:
            seen.add(key)
            ccs.append(key)
    return {
        cc: PALETA_PETROLEO_MAQ[i % len(PALETA_PETROLEO_MAQ)]
        for i, cc in enumerate(ccs)
    }


def _color_cc_petroleo(cc, paleta=None):
    key = str(cc or "").strip().upper()
    if paleta and key in paleta:
        return paleta[key]
    if not key:
        return PALETA_PETROLEO_MAQ[0]
    idx = sum(ord(c) for c in key) % len(PALETA_PETROLEO_MAQ)
    return PALETA_PETROLEO_MAQ[idx]


def _litros_petroleo_por_equipo(conn, fecha_desde, fecha_hasta):
    rows = conn.execute(
        """SELECT UPPER(TRIM(vehiculo)) AS veh, SUM(ABS(litros)) AS lts
           FROM petroleo
           WHERE tipo = 'Salida'
             AND date(fecha) BETWEEN date(?) AND date(?)
             AND TRIM(COALESCE(vehiculo, '')) != ''
           GROUP BY UPPER(TRIM(vehiculo))
           HAVING lts > 0
           ORDER BY lts DESC""",
        (str(fecha_desde), str(fecha_hasta)),
    ).fetchall()
    datos_raw = []
    for veh, lts in rows:
        cod = resolver_codigo_maquinaria(conn, veh) or str(veh).strip()
        nom = nombre_maquinaria_por_codigo(conn, cod) if cod else str(veh)
        datos_raw.append((cod, nom, float(lts)))
    return _consolidar_litros_por_codigo(datos_raw)


def _segmentos_donut_litros(datos, max_slice=6, paleta=None, color_fn=None):
    total = sum(l for _, _, l in datos)
    if total <= 0:
        return [], 0.0
    color_fn = color_fn or _color_equipo_petroleo
    visibles = list(datos[:max_slice])
    resto = sum(l for _, _, l in datos[max_slice:])
    if resto > 0:
        visibles.append(("OTROS", "Otros", resto))
    segs = []
    acum = 0.0
    for cod, nom, lts in visibles:
        pct = 100.0 * lts / total
        segs.append({
            "codigo": cod,
            "nombre": nom,
            "litros": lts,
            "pct": pct,
            "color": color_fn(cod, paleta=paleta),
            "start": acum,
            "end": acum + pct,
        })
        acum += pct
    if segs:
        segs[-1]["end"] = 100.0
    return segs, total


def _fmt_litros_chile(valor):
    return f"{float(valor):,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_gasto_centro(valor):
    v = float(valor or 0)
    if v >= 1_000_000:
        return f"${v / 1_000_000:.1f}M".replace(".", ",")
    if v >= 10_000:
        return f"${v / 1000:.0f}k"
    return f"${v:,.0f}".replace(",", ".")


def _fmt_peso_chile(valor):
    return f"${_fmt_litros_chile(valor)}"


def _html_mini_donut(segs, total_valor, etiqueta_centro, unidad="L", fmt_fn=None):
    import html as html_lib

    fmt_fn = fmt_fn or _fmt_litros_chile
    etiqueta = html_lib.escape(str(etiqueta_centro or ""))
    gradiente = "#ECEFF1 0% 100%"
    if segs:
        gradiente = ", ".join(
            f"{s['color']} {s['start']:.2f}% {s['end']:.2f}%" for s in segs
        )
    total_txt = html_lib.escape(str(fmt_fn(total_valor)))
    lbl = html_lib.escape(str(unidad or ""))
    lbl_html = f'<div class="maq-mini-lbl">{lbl}</div>' if lbl else ""
    cap_html = (
        f'<div class="maq-mini-cap">{etiqueta}</div>'
        if str(etiqueta_centro or "").strip()
        else ""
    )
    return (
        f'<div class="maq-mini-donut" title="{etiqueta}">'
        f'<div class="maq-mini-ring" style="background:conic-gradient({gradiente});">'
        f'<div class="maq-mini-hole"></div>'
        f'<div class="maq-mini-center">'
        f'<div class="maq-mini-num">{total_txt}</div>'
        f"{lbl_html}"
        f"</div></div>"
        f"{cap_html}"
        f"</div>"
    )


def _html_leyenda_columna_petroleo(segs):
    import html as html_lib

    if not segs:
        return '<div class="maq-leyenda-vacia">Sin despachos</div>'
    lineas = []
    for s in segs[:5]:
        nom = html_lib.escape(str(s["nombre"] or s["codigo"])[:18])
        lineas.append(
            f'<div class="maq-ley-fila">'
            f'<span class="maq-ley-dot" style="background:{s["color"]};"></span>'
            f'<span class="maq-ley-nom">{nom}</span>'
            f'<span class="maq-ley-pct">{s["pct"]:.0f}%</span>'
            f"</div>"
        )
    return f'<div class="maq-ley-col">{"".join(lineas)}</div>'


def _html_columna_widget_petroleo(
    titulo: str,
    subtitulo: str,
    segs,
    total_valor: float,
    *,
    unidad: str = "L",
    fmt_fn=None,
    total_etiqueta: str = "Total",
):
    import html as html_lib

    fmt_fn = fmt_fn or _fmt_litros_chile
    tit = html_lib.escape(str(titulo))
    sub = html_lib.escape(str(subtitulo))
    tot_txt = html_lib.escape(str(fmt_fn(total_valor)))
    uni = html_lib.escape(str(unidad))
    tot_lbl = html_lib.escape(str(total_etiqueta))
    donut = _html_mini_donut(segs, total_valor, "", unidad, fmt_fn)
    leyenda = _html_leyenda_columna_petroleo(segs)
    return (
        f'<div class="maq-pet-col">'
        f'<div class="maq-pet-col-head">'
        f'<div class="maq-pet-col-tit">{tit}</div>'
        f'<div class="maq-pet-col-sub">{sub}</div>'
        f"</div>"
        f"{donut}"
        f"{leyenda}"
        f'<div class="maq-pet-col-total">{tot_lbl}: <b>{tot_txt}</b> {uni}</div>'
        f"</div>"
    )


def _mes_etiqueta_es(ref):
    meses = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
    try:
        return f"{meses[ref.month - 1]} {ref.year}"
    except Exception:
        return str(ref)


def html_widget_petroleo_maquinaria(conn, temporada_nombre, temporada_desde, temporada_hasta, ref_fecha=None):
    """Widget compacto: donas petróleo por equipo (temporada + mes) y gasto neto por CC."""
    from calendar import monthrange
    from datetime import date

    if ref_fecha is None:
        try:
            from erp_respaldo import hora_chile
            ref = hora_chile().date()
        except Exception:
            ref = date.today()
    elif hasattr(ref_fecha, "date"):
        ref = ref_fecha.date()
    else:
        ref = ref_fecha

    mes_desde = ref.replace(day=1)
    mes_hasta = ref.replace(day=monthrange(ref.year, ref.month)[1])

    datos_temp = _litros_petroleo_por_equipo(conn, temporada_desde, temporada_hasta)
    datos_mes = _litros_petroleo_por_equipo(conn, mes_desde, mes_hasta)
    datos_cc = _gasto_petroleo_por_cc(conn, temporada_desde, temporada_hasta)
    paleta = _paleta_equipos_widget(datos_temp, datos_mes)
    paleta_cc = _paleta_cc_widget(datos_cc)
    segs_temp, tot_temp = _segmentos_donut_litros(datos_temp, paleta=paleta)
    segs_mes, tot_mes = _segmentos_donut_litros(datos_mes, paleta=paleta)
    segs_cc, tot_cc = _segmentos_donut_litros(
        datos_cc, paleta=paleta_cc, color_fn=_color_cc_petroleo
    )
    mes_nombre = _mes_etiqueta_es(ref)
    temp_nombre = str(temporada_nombre or "Temporada")

    col_temp = _html_columna_widget_petroleo(
        "Litros por maquinaria",
        temp_nombre,
        segs_temp,
        tot_temp,
        unidad="L",
        fmt_fn=_fmt_litros_chile,
        total_etiqueta="Despachado",
    )
    col_mes = _html_columna_widget_petroleo(
        "Litros por maquinaria",
        f"Mes · {mes_nombre}",
        segs_mes,
        tot_mes,
        unidad="L",
        fmt_fn=_fmt_litros_chile,
        total_etiqueta="Despachado",
    )
    col_cc = _html_columna_widget_petroleo(
        "Gasto por CC",
        f"Temporada · {temp_nombre}",
        segs_cc,
        tot_cc,
        unidad="neto",
        fmt_fn=_fmt_gasto_centro,
        total_etiqueta="Imputado",
    )

    return (
        f"<style>{MAQ_WIDGET_CSS}</style>"
        f'<div class="maq-widget-petroleo-wrap">'
        f'<div class="maq-widget-kicker">⛽ Resumen petróleo</div>'
        f'<div class="maq-donut-trio">'
        f"{col_temp}{col_mes}{col_cc}"
        f"</div>"
        f'<div class="maq-widget-foot">'
        f"<strong>Columna 1 y 2:</strong> litros despachados por equipo (salidas). "
        f"<strong>Columna 3:</strong> gasto neto imputado por centro de costo (PMP)."
        f"</div></div>"
    )


def _mostrar_html_streamlit(html):
    """Renderiza HTML sin que Streamlit lo muestre como texto plano."""
    html = str(html or "").strip()
    if hasattr(st, "html"):
        st.html(html)
        return
    st.markdown(html, unsafe_allow_html=True)


def render_widget_petroleo_maquinaria(conn, temporada_nombre, temporada_desde, temporada_hasta, ref_fecha=None):
    try:
        html = html_widget_petroleo_maquinaria(
            conn, temporada_nombre, temporada_desde, temporada_hasta, ref_fecha=ref_fecha
        )
        _mostrar_html_streamlit(html)
    except Exception as exc:
        st.warning(f"No se pudo cargar el widget de petróleo: {exc}")


def _codigo_desde_celda_maquinaria(valor):
    txt = str(valor or "").strip()
    if " — " in txt:
        return txt.split(" — ", 1)[0].strip().upper()
    return txt.upper()


def estilo_historial_maquinaria(df, codigos_reparacion):
    """Resalta filas de equipos actualmente en reparación."""
    codigos = {str(c).upper() for c in (codigos_reparacion or [])}

    def _fila(row):
        cod = _codigo_desde_celda_maquinaria(row.get("MAQUINARIA", ""))
        etiq = str(row.get("ETIQUETA", "")).strip().upper()
        if cod in codigos:
            if not etiqueta_maquinaria_cerrada(etiq):
                return ["background-color:#FFE0B2; color:#4E342E; font-weight:600"] * len(row)
            return ["background-color:#FFF8E1; color:#5D4037"] * len(row)
        if not etiqueta_maquinaria_cerrada(etiq):
            return ["background-color:#FFEBEE"] * len(row)
        return [""] * len(row)

    if df is None or df.empty:
        return df
    try:
        return df.style.apply(_fila, axis=1)
    except Exception:
        return df


def render_panel_cerrar_casos_maquinaria(conn, registrar_accion):
    """Formulario para marcar equipos en reparación como conforme/cerrado."""
    casos = listar_casos_abiertos_maquinaria(conn)
    if not casos:
        return
    st.markdown("##### 🔧 Equipos en reparación — volver a operación")
    st.caption(
        "Equipos con el último evento aún no cerrado (Abierto / En Observación / En Reparación). "
        "Al confirmar, el caso queda resuelto y el equipo deja de aparecer en alerta."
    )
    opciones = {
        c["cod_registro"]: f"{c['cod_registro']} — {etiqueta_maquinaria(c['codigo'], c['nombre'])} ({c['etiqueta']})"
        for c in casos
    }
    with st.form("maq_cerrar_caso_form"):
        sel = st.selectbox("Caso abierto", list(opciones.keys()), format_func=lambda k: opciones[k], key="maq_cerrar_sel")
        estado = st.selectbox("Nuevo estado", list(ESTADOS_CASO_MAQ), index=list(ESTADOS_CASO_MAQ).index("Cerrado conforme"), key="maq_cerrar_estado")
        if st.form_submit_button("✅ VOLVER A OPERACIÓN"):
            cerrar_caso_maquinaria(conn, sel, estado)
            caso = next((c for c in casos if c["cod_registro"] == sel), None)
            det = f"{sel} → {estado}"
            if caso:
                det = f"{caso['codigo']} {det}"
            registrar_accion("MAQUINARIA CIERRE", det)
            st.success(f"Caso {sel} marcado como **{estado}**. Equipo disponible.")
            st.rerun()


def inyectar_css_tabs_maquinaria():
    """Pestañas del módulo Maquinaria (solo área principal, no sidebar)."""
    st.markdown(
        """<style>
        .stApp:has(.maq-module-marker) .main div[data-testid="stVerticalBlock"]:has(.maq-tabs-principal) [data-testid="stTabs"] {
            margin-bottom: 0.25rem !important;
        }
        .stApp:has(.maq-module-marker) .main [data-testid="stTabs"] [data-baseweb="tab-list"] {
            display: flex !important;
            flex-wrap: wrap !important;
            gap: 0.55rem !important;
            width: 100% !important;
            padding: 0.45rem !important;
            margin-bottom: 0.85rem !important;
            background: rgba(255, 255, 255, 0.82) !important;
            border: 1px solid #DDE5DF !important;
            border-radius: 12px !important;
            box-shadow: 0 2px 10px rgba(27, 94, 32, 0.06) !important;
        }
        .stApp:has(.maq-module-marker) .main [data-testid="stTabs"] [data-baseweb="tab"] {
            flex: 1 1 calc(33.333% - 0.55rem) !important;
            min-width: 6.5rem !important;
            max-width: 100% !important;
            justify-content: center !important;
            padding: 0.62rem 0.75rem !important;
            margin: 0 !important;
            font-size: 0.9rem !important;
            font-weight: 700 !important;
            white-space: nowrap !important;
            line-height: 1.2 !important;
            text-align: center !important;
            border-radius: 9px !important;
            border: 1px solid transparent !important;
            background: transparent !important;
            transition: background 0.15s ease, border-color 0.15s ease !important;
        }
        .stApp:has(.maq-module-marker) .main [data-testid="stTabs"] [data-baseweb="tab"]:hover {
            background: rgba(232, 245, 233, 0.85) !important;
        }
        .stApp:has(.maq-module-marker) .main [data-testid="stTabs"] [aria-selected="true"] {
            background: #FFFFFF !important;
            color: #1B5E20 !important;
            border-color: #81C784 !important;
            box-shadow: 0 2px 8px rgba(46, 125, 50, 0.14) !important;
        }
        /* Selector Faenas: Registrar / Ticket (solo contenido principal) */
        .stApp:has(.maq-module-marker) .main [data-testid="stRadio"] > div[role="radiogroup"] {
            gap: 0.5rem !important;
            flex-wrap: wrap !important;
            padding: 0.35rem !important;
            margin-bottom: 1rem !important;
            background: #F1F8E9 !important;
            border: 1px solid #C8E6C9 !important;
            border-radius: 10px !important;
        }
        .stApp:has(.maq-module-marker) .main [data-testid="stRadio"] > div[role="radiogroup"] > label {
            flex: 1 1 auto !important;
            min-width: 8rem !important;
            margin: 0 !important;
            padding: 0.55rem 0.85rem !important;
            border-radius: 8px !important;
            border: 1px solid transparent !important;
            justify-content: center !important;
            font-weight: 700 !important;
            color: #1F2933 !important;
        }
        .stApp:has(.maq-module-marker) .main [data-testid="stRadio"] > div[role="radiogroup"] > label:has(input:checked) {
            background: #fff !important;
            border-color: #2E7D32 !important;
            box-shadow: 0 1px 6px rgba(46, 125, 50, 0.12) !important;
            color: #1B5E20 !important;
        }
        @media (max-width: 640px) {
            .stApp:has(.maq-module-marker) .main [data-testid="stTabs"] [data-baseweb="tab-list"] {
                gap: 0.4rem !important;
                padding: 0.35rem !important;
            }
            .stApp:has(.maq-module-marker) .main [data-testid="stTabs"] [data-baseweb="tab"] {
                flex: 1 1 100% !important;
                font-size: 0.82rem !important;
                padding: 0.55rem 0.65rem !important;
            }
        }
        </style>""",
        unsafe_allow_html=True,
    )


MAQ_FAENA_TICKET_CSS = """
.maq-faena-ticket-wrap {
    display: flex; justify-content: center; padding: 0.5rem 0 1rem;
}
.maq-faena-ticket {
    width: 100%; max-width: 400px; background: #fff;
    border: 3px solid #2E7D32; border-radius: 16px;
    overflow: hidden; box-shadow: 0 8px 28px rgba(27,94,32,0.18);
    font-family: 'DM Sans', system-ui, sans-serif; color: #1F2933;
}
.maq-faena-ticket-head {
    background: linear-gradient(135deg, #1B5E20 0%, #2E7D32 100%);
    color: #fff; text-align: center; padding: 0.85rem 1rem 0.75rem;
}
.maq-faena-ticket-head .kicker {
    font-size: 0.72rem; letter-spacing: 0.12em; opacity: 0.92; font-weight: 700;
}
.maq-faena-ticket-head .titulo {
    font-size: 1.35rem; font-weight: 800; margin: 0.2rem 0 0; line-height: 1.15;
}
.maq-faena-ticket-body { padding: 1rem 1.1rem 0.35rem; }
.maq-faena-ticket-fecha {
    text-align: center; font-size: 1.05rem; font-weight: 800; color: #1B5E20;
    margin-bottom: 0.85rem;
}
.maq-faena-ticket-cuartel {
    text-align: center; font-size: 1.55rem; font-weight: 800; line-height: 1.2;
    margin-bottom: 0.9rem; color: #0D47A1;
}
.maq-faena-ticket-row {
    display: flex; gap: 0.65rem; padding: 0.55rem 0;
    border-top: 1px solid #E8EFE9; align-items: flex-start;
}
.maq-faena-ticket-row:first-of-type { border-top: none; }
.maq-faena-ticket-row .lbl {
    flex: 0 0 5.2rem; font-size: 0.68rem; font-weight: 800; color: #5F6B7A;
    text-transform: uppercase; letter-spacing: 0.04em; padding-top: 0.15rem;
}
.maq-faena-ticket-row .val {
    flex: 1; font-size: 1rem; font-weight: 700; line-height: 1.35;
}
.maq-faena-ticket-faena {
    background: #F1F8E9; border-radius: 10px; padding: 0.75rem 0.85rem;
    margin: 0.5rem 0 0.85rem; font-size: 1.08rem; font-weight: 800;
    line-height: 1.35; color: #1B5E20; text-align: center;
}
.maq-faena-ticket-foot {
    background: #F3F6F4; border-top: 1px dashed #C5D4C8;
    padding: 0.55rem 1rem; text-align: center;
    font-size: 0.72rem; color: #5F6B7A; font-weight: 600;
}
"""


def _html_ticket_faena_operador(
    fecha,
    cuartel,
    operador,
    faena,
    equipo_txt,
    tractor_txt="",
    notas="",
    ticket_id=None,
    nombre_erp="ERP Agrícola",
):
    """Tarjeta HTML compacta para pantallazo / WhatsApp al operador."""
    esc = html_lib.escape
    f_txt = esc(str(fecha or ""))
    cc_txt = esc(str(cuartel or ""))
    op_txt = esc(str(operador or ""))
    faena_txt = esc(str(faena or ""))
    eq_txt = esc(str(equipo_txt or "—"))
    tr_txt = esc(str(tractor_txt or "")).strip()
    notas_txt = esc(str(notas or "")).strip()
    ref = f"FAENA-{int(ticket_id):05d}" if ticket_id else "FAENA"
    fila_tractor = ""
    if tr_txt:
        fila_tractor = (
            f'<div class="maq-faena-ticket-row">'
            f'<span class="lbl">Tractor</span><span class="val">{tr_txt}</span></div>'
        )
    fila_notas = ""
    if notas_txt:
        fila_notas = (
            f'<div class="maq-faena-ticket-row">'
            f'<span class="lbl">Notas</span><span class="val">{notas_txt}</span></div>'
        )
    return f"""<div class="maq-faena-ticket-wrap">
<style>{MAQ_FAENA_TICKET_CSS}</style>
<div class="maq-faena-ticket">
  <div class="maq-faena-ticket-head">
    <div class="kicker">{esc(nombre_erp)}</div>
    <div class="titulo">Orden de faena</div>
  </div>
  <div class="maq-faena-ticket-body">
    <div class="maq-faena-ticket-fecha">{f_txt}</div>
    <div class="maq-faena-ticket-cuartel">{cc_txt}</div>
    <div class="maq-faena-ticket-faena">{faena_txt}</div>
    <div class="maq-faena-ticket-row">
      <span class="lbl">Operador</span><span class="val">{op_txt}</span>
    </div>
    <div class="maq-faena-ticket-row">
      <span class="lbl">Equipo</span><span class="val">{eq_txt}</span>
    </div>
    {fila_tractor}
    {fila_notas}
  </div>
  <div class="maq-faena-ticket-foot">Ref. {ref} · Tome pantallazo y envíe al operador</div>
</div></div>"""


def _render_vista_ticket_faena(conn, df, nombre_erp="ERP Agrícola"):
    """Selector + tarjeta ticket listo para captura en celular."""
    if df is None or df.empty:
        return
    st.markdown("##### 📱 Ticket para operador")
    st.caption(
        "Seleccione la asignación y **tome un pantallazo** de la tarjeta verde "
        "para enviarla por WhatsApp al operador."
    )
    opciones = {
        int(row["id"]): (
            f"{row['FECHA']} · {row['CUARTEL']} · {row['OPERADOR']} — {row['FAENA']}"
        )
        for _, row in df.iterrows()
    }
    ids = list(opciones.keys())
    pref = st.session_state.pop("maq_faena_ticket_id", None)
    idx_def = ids.index(pref) if pref in ids else 0
    sel_id = st.selectbox(
        "Asignación",
        ids,
        index=idx_def,
        format_func=lambda i: opciones[i],
        key="maq_faena_ticket_sel",
        label_visibility="collapsed",
    )
    row = df[df["id"] == sel_id].iloc[0]
    try:
        f_show = pd.to_datetime(row["FECHA"]).strftime("%d-%m-%Y")
    except Exception:
        f_show = str(row["FECHA"])
    eq_txt = texto_maquinaria_para_display(conn, row.get("EQUIPO", ""))
    tr_raw = str(row.get("TRACTOR", "") or "").strip()
    tr_txt = texto_maquinaria_para_display(conn, tr_raw) if tr_raw else ""
    st.html(
        _html_ticket_faena_operador(
            fecha=f_show,
            cuartel=row["CUARTEL"],
            operador=row["OPERADOR"],
            faena=row["FAENA"],
            equipo_txt=eq_txt,
            tractor_txt=tr_txt,
            notas=row.get("NOTAS", ""),
            ticket_id=sel_id,
            nombre_erp=nombre_erp,
        )
    )


def migrar_asignacion_faena_diaria(conn):
    if conn_en_solo_lectura(conn):
        return
    conn.execute(
        """CREATE TABLE IF NOT EXISTS asignacion_faena_diaria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha DATE NOT NULL,
            centro_costo TEXT NOT NULL,
            codigo_tractor TEXT,
            codigo_equipo TEXT NOT NULL,
            operador TEXT NOT NULL,
            detalle_faena TEXT NOT NULL,
            notas TEXT DEFAULT '',
            fecha_registro DATE
        )"""
    )
    conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (clave TEXT PRIMARY KEY, valor TEXT)")
    if not conn.execute(
        "SELECT 1 FROM schema_meta WHERE clave='asignacion_faena_diaria_v1'"
    ).fetchone():
        conn.execute(
            "INSERT INTO schema_meta (clave, valor) VALUES ('asignacion_faena_diaria_v1', '1')"
        )
    conn.commit()


def render_tab_asignacion_faena_diaria(
    conn,
    registrar_accion,
    centros_costo,
    hoy,
    boton_pdf_fn=None,
    generar_pdf_fn=None,
    nombre_erp="ERP Agrícola",
):
    """Pestaña: asignación diaria de equipos a faenas / cuarteles."""
    migrar_asignacion_faena_diaria(conn)
    st.markdown("#### Movimiento diario de faenas")
    st.caption(
        "Registre la asignación y genere el **ticket** (pantallazo) para el operador. "
        "Complemente con **Petróleo** y **Libro de Campo** si corresponde."
    )

    sub = st.radio(
        "Vista faenas",
        ["Registrar", "Ticket operador"],
        horizontal=True,
        key="maq_faena_vista",
        label_visibility="collapsed",
    )
    if sub == "Registrar":
        _render_form_asignacion_faena(conn, registrar_accion, centros_costo, hoy)
        _render_lista_asignacion_faena(
            conn, registrar_accion, hoy, boton_pdf_fn, generar_pdf_fn,
        )
    else:
        f_ticket = st.date_input("Día del ticket", hoy, key="maq_faena_ticket_dia")
        df_ticket = _cargar_df_asignacion_faena(conn, f_ticket, f_ticket)
        if df_ticket.empty:
            st.info("Sin asignaciones ese día. Registre una en **Registrar**.")
        else:
            _render_vista_ticket_faena(conn, df_ticket, nombre_erp=nombre_erp)


def _cargar_df_asignacion_faena(conn, fi, ff):
    return pd.read_sql_query(
        """SELECT a.id, a.fecha as FECHA, a.centro_costo as CUARTEL,
                  a.codigo_tractor as TRACTOR, a.codigo_equipo as EQUIPO,
                  a.operador as OPERADOR, a.detalle_faena as FAENA, a.notas as NOTAS
           FROM asignacion_faena_diaria a
           WHERE a.fecha BETWEEN ? AND ?
           ORDER BY a.fecha DESC, a.id DESC""",
        conn,
        params=(str(fi), str(ff)),
    )


def _render_form_asignacion_faena(conn, registrar_accion, centros_costo, hoy):
    with st.form("maq_faena_registro", clear_on_submit=True):
        st.markdown("##### Nueva asignación")
        r1, r2 = st.columns(2)
        f_asig = r1.date_input("Fecha faena", hoy, key="maq_faena_f")
        cc_asig = r1.selectbox("Cuartel / Faena", centros_costo, key="maq_faena_cc")
        operador = r2.text_input("Operador / Responsable", key="maq_faena_op")
        detalle = r2.text_input(
            "Labor / Detalle faena",
            key="maq_faena_det",
            placeholder="Ej. Raleo, riego, preparación cosecha",
        )
        c_eq1, c_eq2 = st.columns(2)
        with c_eq1:
            equipo = render_select_maquinaria(
                conn,
                key="maq_faena_eq",
                label="Equipo principal",
                tipos=TIPOS_MAQUINARIA,
            )
        with c_eq2:
            tractor = render_select_maquinaria(
                conn,
                key="maq_faena_trac",
                label="Tractor (opcional)",
                tipos=TIPOS_MAQUINARIA_TRACTOR,
                permitir_vacio=True,
            )
        notas = st.text_area("Notas (opcional)", key="maq_faena_notas", height=68)
        if st.form_submit_button("Guardar asignación", type="primary"):
            if not equipo:
                st.error("Seleccione el equipo principal desde la maestra.")
            elif not operador.strip():
                st.error("Ingrese operador o responsable.")
            elif not detalle.strip():
                st.error("Indique la labor o detalle de la faena.")
            else:
                cur = conn.cursor()
                cur.execute(
                    """INSERT INTO asignacion_faena_diaria
                       (fecha, centro_costo, codigo_tractor, codigo_equipo, operador, detalle_faena, notas, fecha_registro)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        str(f_asig),
                        cc_asig.upper(),
                        tractor or "",
                        equipo,
                        operador.strip(),
                        detalle.strip(),
                        notas.strip(),
                        str(hoy),
                    ),
                )
                conn.commit()
                st.session_state["maq_faena_ticket_id"] = int(cur.lastrowid)
                registrar_accion(
                    "MAQ FAENA",
                    f"{f_asig} {cc_asig} {equipo}" + (f" + {tractor}" if tractor else ""),
                )
                st.success("Guardado. Abra **Ticket operador** y tome el pantallazo.")
                st.rerun()


def _render_lista_asignacion_faena(conn, registrar_accion, hoy, boton_pdf_fn, generar_pdf_fn):
    st.divider()
    cf1, cf2 = st.columns(2)
    fi = cf1.date_input("Listado desde", hoy, key="maq_faena_fi")
    ff = cf2.date_input("Listado hasta", hoy, key="maq_faena_ff")
    if fi > ff:
        st.error("La fecha «Desde» no puede ser posterior a «Hasta».")
        return

    st.markdown("##### Asignaciones del período")
    df = _cargar_df_asignacion_faena(conn, fi, ff)
    if df.empty:
        st.info("Sin asignaciones en el período seleccionado.")
        return

    df_show = df.drop(columns=["id"]).copy()
    df_show = enriquecer_columna_maquinaria(conn, df_show, "TRACTOR")
    df_show = enriquecer_columna_maquinaria(conn, df_show, "EQUIPO")
    st.dataframe(df_show, use_container_width=True, hide_index=True)

    if boton_pdf_fn and generar_pdf_fn:
        titulo = f"ASIGNACIÓN FAENAS ({fi} a {ff})"
        boton_pdf_fn(
            "PDF listado",
            generar_pdf_fn(df_show, titulo, incluir_precios=False),
            "asignacion_faenas.pdf",
            key=f"maq_faena_pdf_{fi}_{ff}",
        )

    with st.expander("Eliminar asignación"):
        opciones = {
            int(row["id"]): (
                f"{row['FECHA']} · {row['CUARTEL']} · {row['EQUIPO']} — {row['FAENA']}"
            )
            for _, row in df.iterrows()
        }
        with st.form("maq_faena_del"):
            sel_id = st.selectbox(
                "Registro",
                list(opciones.keys()),
                format_func=lambda i: opciones[i],
                key="maq_faena_del_sel",
            )
            if st.form_submit_button("Eliminar"):
                conn.execute("DELETE FROM asignacion_faena_diaria WHERE id=?", (sel_id,))
                conn.commit()
                registrar_accion("MAQ FAENA DEL", opciones.get(sel_id, str(sel_id)))
                st.warning("Asignación eliminada.")
                st.rerun()
