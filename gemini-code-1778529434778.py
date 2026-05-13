import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import os

# --- LIBRERÍAS ---
try:
    from fpdf import FPDF
    from pydrive2.auth import GoogleAuth
    from pydrive2.drive import GoogleDrive
    from oauth2client.service_account import ServiceAccountCredentials
except ImportError:
    st.error("Error: Faltan librerías. Revisa requirements.txt")

# --- CONFIGURACIÓN DRIVE ---
ID_CARPETA_DRIVE = "1V7IwdbJPzxQ-hJQaVqOWejHHA1mNbgLo" 
NOMBRE_DB = 'erp_concepcion_v6.db'
JSON_KEY = 'secretos.json'
CLAVE_SEGURIDAD = "2908"

# --- LISTAS MAESTRAS ---
FAMILIAS_INSUMOS = ["FERTILIZANTE", "FERTILIZANTE FOLIAR", "HERBICIDA", "INSECTICIDA", "FUNGICIDA", "BIO ESTIMULANTE", "OTROS"]
CENTROS_COSTO = ["CEREZOS CORTE1", "CEREZOS CORTE2", "CIRUELOS", "NOGALES APARICION", "NOGALES CRUZ DEL SUR", "OTROS"]

# --- CARGA MASIVA DEFINITIVA (EXTRAÍDA DE SU PDF) ---
PRODUCTOS_PDF = [
    ("ACABAN", "INSECTICIDA", 0.0, 5.0),
    ("ACETAMIPRID 20%", "INSECTICIDA", 0.5, 1.0),
    ("ACETAMIPRID 70%", "INSECTICIDA", 0.9, 5.0),
    ("ADMIRAL", "INSECTICIDA", 2.0, 1.0),
    ("AFFINITY", "HERBICIDA", 1.0, 1.0),
    ("AGROMIL", "FERTILIZANTE FOLIAR", 15.0, 10.0),
    ("AMPLIGO", "INSECTICIDA", 1.5, 1.0),
    ("BACK CA B", "FERTILIZANTE FOLIAR", 10.0, 10.0),
    ("BAPSOL", "BIO ESTIMULANTE", 15.0, 10.0),
    ("KEYLATE ZINC", "FERTILIZANTE FOLIAR", 3.0, 10.0),
    ("KORU CALCIO", "FERTILIZANTE FOLIAR", 0.0, 10.0),
    ("MACROQUEL CALCIO", "FERTILIZANTE FOLIAR", 20.0, 10.0),
    ("MAP", "FERTILIZANTE", 141.0, 100.0),
    ("MICROQUEL BORO", "FERTILIZANTE FOLIAR", 16.0, 10.0),
    ("MIMIC", "INSECTICIDA", 1.0, 1.0),
    ("CALCIO NITRATO DE", "FERTILIZANTE", 325.0, 100.0),
    ("POTASIO NITRATO DE", "FERTILIZANTE", -190.0, 100.0),
    ("NUTRICHELATES ZINC", "FERTILIZANTE FOLIAR", 5.0, 10.0)
]

# --- UTILIDADES ---
def f_puntos(v):
    try: return f"{int(v):,}".replace(",", ".")
    except: return "0"

def conectar_db(): return sqlite3.connect(NOMBRE_DB)

# --- SINCRONIZACIÓN DRIVE ---
def obtener_drive():
    scope = ['https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(JSON_KEY, scope)
    gauth = GoogleAuth()
    gauth.credentials = creds
    return GoogleDrive(gauth)

def descargar_de_drive():
    if not os.path.exists(JSON_KEY): return False
    try:
        drive = obtener_drive()
        query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
        lista = drive.ListFile({'q': query}).GetList()
        if lista:
            lista[0].GetContentFile(NOMBRE_DB)
            return True
    except: return False
    return False

def guardar_en_drive():
    if not os.path.exists(JSON_KEY): return False
    try:
        drive = obtener_drive()
        query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
        lista = drive.ListFile({'q': query}).GetList()
        f = lista[0] if lista else drive.CreateFile({'title': NOMBRE_DB, 'parents': [{'id': ID_CARPETA_DRIVE}]})
        f.SetContentFile(NOMBRE_DB)
        f.Upload()
        return True
    except: return False

# --- GENERADOR DE PDF ---
def descargar_pdf(df, titulo):
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, "AGRICOLA LA CONCEPCIÓN", ln=True, align="C")
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 10, titulo, ln=True, align="C")
        pdf.ln(5)
        pdf.set_font("Helvetica", "B", 8)
        cols = df.columns
        w = 190 / len(cols)
        for col in cols: pdf.cell(w, 8, str(col), border=1, align="C")
        pdf.ln()
        pdf.set_font("Helvetica", "", 7)
        for _, row in df.iterrows():
            for item in row:
                val = f_puntos(item) if isinstance(item, (int, float)) else str(item)
                pdf.cell(w, 7, val[:25], border=1)
            pdf.ln()
        return pdf.output(dest="S").encode("latin-1")
    except: return None

# --- INICIALIZACIÓN ---
st.set_page_config(page_title="AGRICOLA LA CONCEPCION ERP", page_icon="🚜", layout="wide")

if 'db_sincronizada' not in st.session_state:
    descargar_de_drive()
    st.session_state['db_sincronizada'] = True

def inicializar_db():
    conn = conectar_db(); cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS facturas (id INTEGER PRIMARY KEY AUTOINCREMENT, nro_documento TEXT, proveedor TEXT, fecha_compra DATE, fecha_vencimiento DATE, monto_neto REAL, monto_total REAL, estado TEXT DEFAULT 'Pendiente', tipo TEXT DEFAULT 'Factura', metodo_pago TEXT, fecha_pago DATE, concepto TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS detalle_facturas (id INTEGER PRIMARY KEY AUTOINCREMENT, factura_id INTEGER, producto_id INTEGER, cantidad REAL, precio_neto REAL, total_linea REAL)")
    cursor.execute("CREATE TABLE IF NOT EXISTS inventario (id INTEGER PRIMARY KEY AUTOINCREMENT, producto TEXT, familia TEXT, stock REAL DEFAULT 0, stock_minimo REAL DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS movimientos (id INTEGER PRIMARY KEY AUTOINCREMENT, producto_id INTEGER, tipo TEXT, cantidad REAL, centro_costo TEXT, fecha DATE)")
    
    # Migraciones
    cursor.execute("PRAGMA table_info(facturas)")
    if 'concepto' not in [info[1] for info in cursor.fetchall()]:
        cursor.execute("ALTER TABLE facturas ADD COLUMN concepto TEXT")

    cursor.execute("PRAGMA table_info(inventario)")
    if 'stock_minimo' not in [info[1] for info in cursor.fetchall()]:
        cursor.execute("ALTER TABLE inventario ADD COLUMN stock_minimo REAL DEFAULT 0")
    
    # CARGA DE PRODUCTOS DEL PDF (Solo si no hay nada)
    cursor.execute("SELECT count(*) FROM inventario")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("INSERT INTO inventario (producto, familia, stock, stock_minimo) VALUES (?,?,?,?)", PRODUCTOS_PDF)
    
    conn.commit(); conn.close()

inicializar_db()

# --- MÓDULOS ---

def modulo_dashboard():
    st.header("📊 Resumen Financiero")
    conn = conectar_db(); df_f = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente'", conn); conn.close()
    c1, c2, c3 = st.columns(3)
    total_deuda = df_f['monto_total'].sum() if not df_f.empty else 0
    c1.metric("Deuda Pendiente", f"${f_puntos(total_deuda)}")
    vencidas = 0
    if not df_f.empty:
        hoy = datetime.now().date()
        vencidas = df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < hoy].shape[0]
    c2.metric("Vencidas", vencidas, delta_color="inverse")
    c3.metric("Documentos", len(df_f))
    
    st.subheader("📅 Proyección de Pagos")
    cols_m = st.columns(4)
    meses_n = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]
    for i in range(4):
        fp = datetime.now() + timedelta(days=i*30); m, a = fp.month, fp.year
        val_m = 0
        if not df_f.empty:
            df_f['fv'] = pd.to_datetime(df_f['fecha_vencimiento'])
            val_m = df_f[(df_f['fv'].dt.month == m) & (df_f['fv'].dt.year == a)]['monto_total'].sum()
        cols_m[i].metric(f"{meses_n[m-1]} {a}", f"${f_puntos(val_m)}")

def modulo_compras():
    st.header("Módulo de Compras")
    t1, t2, t3 = st.tabs(["➕ Factura Insumos", "💸 Gasto Vario", "🔍 Historial"])
    with t1:
        c1, c2 = st.columns(2)
        nro, prov = c1.text_input("N° Factura"), c1.text_input("Proveedor")
        f_c, f_v = c2.date_input("Emisión"), c2.date_input("Vencimiento")
        conn = conectar_db(); df_inv = pd.read_sql_query("SELECT id, producto FROM inventario ORDER BY producto", conn); conn.close()
        if not df_inv.empty:
            cp1, cp2, cp3, cp4 = st.columns([3,1,1,1])
            p_sel = cp1.selectbox("Producto", df_inv['id'].astype(str) + " - " + df_inv['producto'])
            cant, prec = cp2.number_input("Cant.", min_value=0.1), cp3.number_input("Neto Un.", min_value=0.0)
            if cp4.button("➕"):
                if 'carrito' not in st.session_state: st.session_state.carrito = []
                st.session_state.carrito.append({'id': int(p_sel.split(" - ")[0]), 'nombre': p_sel.split(" - ")[1], 'cantidad': cant, 'precio': prec, 'total': cant * prec})
                st.rerun()
        if st.session_state.get('carrito'):
            df_c = pd.DataFrame(st.session_state.carrito)
            st.table(df_c[['nombre', 'cantidad', 'precio', 'total']])
            neto = df_c['total'].sum()
            m_final = st.number_input("Total Final Factura", value=float(neto*1.19))
            if st.button("💾 GUARDAR FACTURA"):
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_neto, monto_total) VALUES (?,?,?,?,?,?)", (nro, prov, f_c, f_v, neto, m_final))
                fid = cursor.lastrowid
                for i in st.session_state.carrito:
                    cursor.execute("INSERT INTO detalle_facturas (factura_id, producto_id, cantidad, precio_neto, total_linea) VALUES (?,?,?,?,?)", (fid, i['id'], i['cantidad'], i['precio'], i['total']))
                    cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (i['cantidad'], i['id']))
                conn.commit(); conn.close(); guardar_en_drive(); st.session_state.carrito = []; st.rerun()
    with t2:
        with st.form("gv"):
            gp, gd = st.text_input("Proveedor"), st.text_input("N° Doc")
            gm, gf = st.number_input("Monto"), st.date_input("Fecha")
            g_con = st.text_area("Detalle")
            if st.form_submit_button("GUARDAR GASTO"):
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, concepto, estado) VALUES (?,?,?,?,?,?,?,?)", (gd, gp, gf, gf, gm, 'Gasto Vario', g_con, 'Pendiente'))
                conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
    with t3:
        conn = conectar_db(); df_h = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_compra, monto_total, tipo, concepto FROM facturas ORDER BY id DESC", conn); conn.close()
        st.dataframe(df_h, use_container_width=True)
        if not df_h.empty:
            st.download_button("📥 PDF Historial", descargar_pdf(df_h, "HISTORIAL"), "historial.pdf")

def modulo_tesoreria():
    st.header("Cuentas por Pagar")
    tp1, tp2, tp3 = st.tabs(["🔴 Pendientes", "🏢 Proveedor", "📅 Vencimiento"])
    conn = conectar_db()
    with tp1:
        df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente'", conn)
        if not df_p.empty:
            st.dataframe(df_p.style.apply(lambda r: ['background-color: #ffcccc' if pd.to_datetime(r['fecha_vencimiento']).date() < datetime.now().date() else '' for _ in r], axis=1), use_container_width=True)
            st.download_button("📥 PDF Pendientes", descargar_pdf(df_p, "PENDIENTES"), "pendientes.pdf")
            c1, c2 = st.columns(2); id_p = c1.selectbox("ID Pago", df_p['id']); met = c2.selectbox("Medio", ["Transferencia", "Cheque", "Efectivo"])
            if st.button("💰 PAGAR"):
                conn.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (met, datetime.now().date(), id_p))
                conn.commit(); guardar_en_drive(); st.rerun()
    with tp2:
        provs = pd.read_sql_query("SELECT DISTINCT proveedor FROM facturas WHERE estado='Pendiente'", conn)
        if not provs.empty:
            ps = st.selectbox("Elegir Proveedor", provs['proveedor'])
            df_pr = pd.read_sql_query(f"SELECT nro_documento, fecha_vencimiento, monto_total FROM facturas WHERE proveedor='{ps}' AND estado='Pendiente'", conn)
            st.table(df_pr)
            st.download_button(f"📥 PDF {ps}", descargar_pdf(df_pr, f"PENDIENTES: {ps}"), f"pendientes_{ps}.pdf")
    with tp3:
        v1, v2 = st.date_input("Desde"), st.date_input("Hasta", datetime.now()+timedelta(days=30))
        df_v = pd.read_sql_query(f"SELECT nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' AND fecha_vencimiento BETWEEN '{v1}' AND '{v2}'", conn)
        st.dataframe(df_v)
        st.download_button("📥 PDF Rango", descargar_pdf(df_v, "VENCIMIENTOS"), "vencimientos.pdf")
    conn.close()

def modulo_bodega():
    st.header("Inventario")
    tb1, tb2, tb3, tb4 = st.tabs(["📊 Stock", "🔍 Consultas CC", "🔄 Movimiento", "➕ Nuevo Insumo"])
    with tb1:
        conn = conectar_db(); df_s = pd.read_sql_query("SELECT id, producto, familia, stock, stock_minimo FROM inventario", conn); conn.close()
        st.dataframe(df_s.style.apply(lambda r: ['background-color: #ffcccc' if r['stock'] < r['stock_minimo'] else '' for _ in r], axis=1), use_container_width=True)
        st.download_button("📥 PDF Stock", descargar_pdf(df_s, "STOCK"), "stock.pdf")
    with tb2:
        conn = conectar_db(); ccs = pd.read_sql_query("SELECT DISTINCT centro_costo FROM movimientos", conn)
        if not ccs.empty:
            cc_s = st.selectbox("Cuartel", ccs['centro_costo'])
            df_cc = pd.read_sql_query(f"SELECT m.fecha, i.producto, m.tipo, m.cantidad FROM movimientos m JOIN inventario i ON m.producto_id = i.id WHERE m.centro_costo='{cc_s}'", conn)
            st.dataframe(df_cc)
            st.download_button("📥 PDF Consulta", descargar_pdf(df_cc, f"CONSUMO: {cc_s}"), "consumo.pdf")
        conn.close()
    with tb3:
        with st.form("mov"):
            conn = conectar_db(); prs = pd.read_sql_query("SELECT id, producto FROM inventario ORDER BY producto", conn); conn.close()
            ps = st.selectbox("Insumo", prs['id'].astype(str) + " - " + prs['producto'])
            tm, cm = st.radio("Tipo", ["Salida (Campo)", "Entrada"]), st.number_input("Cant.", min_value=0.1)
            cc_m = st.selectbox("Cuartel", CENTROS_COSTO)
            if st.form_submit_button("REGISTRAR"):
                ip = int(ps.split(" - ")[0]); conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo) VALUES (?,?,?,?,?)", (ip, tm, cm, datetime.now().date(), cc_m))
                f = 1 if tm == "Entrada" else -1
                cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (cm*f, ip))
                conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
    with tb4:
        with st.form("new"):
            nn = st.text_input("Nombre"); ff = st.selectbox("Familia", FAMILIAS_INSUMOS); sm = st.number_input("Mínimo", min_value=0.0)
            if st.form_submit_button("CREAR"):
                conn = conectar_db(); conn.execute("INSERT INTO inventario (producto, familia, stock, stock_minimo) VALUES (?,?,?,?)", (nn, ff, 0, sm)); conn.commit(); conn.close(); guardar_en_drive(); st.rerun()

# --- NAVEGACIÓN ---
with st.sidebar:
    st.title("LA CONCEPCIÓN ERP")
    menu = st.radio("Navegación", ["🏠 Dashboard", "📦 Compras", "💸 Tesorería", "🚜 Bodega"])

if menu == "🏠 Dashboard": modulo_dashboard()
elif menu == "📦 Compras": modulo_compras()
elif menu == "💸 Tesorería": modulo_tesoreria()
elif menu == "🚜 Bodega": modulo_bodega()
