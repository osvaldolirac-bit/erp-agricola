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
    st.error("Faltan librerías. Revisa requirements.txt")

# --- CONFIGURACIÓN SEGURA ---
ID_CARPETA_DRIVE = "1V7IwdbJPzxQ-hJQaVqOWejHHA1mNbgLo" 
NOMBRE_DB = 'erp_concepcion_v6.db'
CLAVE_SEGURIDAD = "2908"

# LISTAS MAESTRAS
FAMILIAS_INSUMOS = ["FERTILIZANTE", "FERTILIZANTE FOLIAR", "HERBICIDA", "INSECTICIDA", "FUNGICIDA", "BIO ESTIMULANTE", "OTROS"]
CENTROS_COSTO = ["CEREZOS CORTE1", "CEREZOS CORTE2", "CIRUELOS", "NOGALES APARICION", "NOGALES CRUZ DEL SUR", "OTROS"]

# PRODUCTOS DEL PDF (Extraídos de 13_05_2026 Stock bodega.pdf)
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

# --- FUNCIONES DRIVE (MODO SECRETO) ---
def obtener_drive():
    try:
        scope = ['https://www.googleapis.com/auth/drive']
        # Aquí sacamos la llave de la "Caja Fuerte" de Streamlit
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        gauth = GoogleAuth()
        gauth.credentials = creds
        return GoogleDrive(gauth)
    except Exception as e:
        st.sidebar.error("⚠️ Configura 'Secrets' en Streamlit Cloud")
        return None

def descargar_de_drive():
    drive = obtener_drive()
    if not drive: return False
    try:
        query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
        lista = drive.ListFile({'q': query}).GetList()
        if lista:
            lista[0].GetContentFile(NOMBRE_DB)
            return True
    except: return False
    return False

def guardar_en_drive():
    drive = obtener_drive()
    if not drive: return False
    try:
        query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
        lista = drive.ListFile({'q': query}).GetList()
        f = lista[0] if lista else drive.CreateFile({'title': NOMBRE_DB, 'parents': [{'id': ID_CARPETA_DRIVE}]})
        f.SetContentFile(NOMBRE_DB)
        f.Upload()
        return True
    except: return False

# --- BASE DE DATOS ---
def conectar_db(): return sqlite3.connect(NOMBRE_DB)

def inicializar_db():
    conn = conectar_db(); cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS facturas (id INTEGER PRIMARY KEY AUTOINCREMENT, nro_documento TEXT, proveedor TEXT, fecha_compra DATE, fecha_vencimiento DATE, monto_neto REAL, monto_total REAL, estado TEXT DEFAULT 'Pendiente', tipo TEXT DEFAULT 'Factura', metodo_pago TEXT, fecha_pago DATE, concepto TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS inventario (id INTEGER PRIMARY KEY AUTOINCREMENT, producto TEXT, familia TEXT, stock REAL DEFAULT 0, stock_minimo REAL DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS movimientos (id INTEGER PRIMARY KEY AUTOINCREMENT, producto_id INTEGER, tipo TEXT, cantidad REAL, centro_costo TEXT, fecha DATE)")
    
    # Carga de productos PDF (Solo si está vacío)
    cursor.execute("SELECT count(*) FROM inventario")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("INSERT INTO inventario (producto, familia, stock, stock_minimo) VALUES (?,?,?,?)", PRODUCTOS_PDF)
    
    conn.commit(); conn.close()

# --- REPORTES PDF ---
def generar_pdf(df, titulo):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "AGRICOLA LA CONCEPCIÓN", ln=True, align="C")
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, titulo, ln=True, align="C")
    pdf.ln(5)
    pdf.set_font("Arial", "B", 8)
    cols = df.columns
    w = 190 / len(cols)
    for col in cols: pdf.cell(w, 8, str(col), border=1, align="C")
    pdf.ln()
    pdf.set_font("Arial", "", 7)
    for _, row in df.iterrows():
        for item in row:
            val = f"{int(item):,}".replace(",", ".") if isinstance(item, (int, float)) else str(item)
            pdf.cell(w, 7, val[:25], border=1)
        pdf.ln()
    return pdf.output(dest="S").encode("latin-1")

# --- MODULOS ---
def modulo_dashboard():
    st.header("📊 Dashboard Financiero")
    conn = conectar_db(); df_f = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente'", conn); conn.close()
    c1, c2, c3 = st.columns(3)
    total = df_f['monto_total'].sum() if not df_f.empty else 0
    c1.metric("Deuda Pendiente", f"${total:,.0f}".replace(",", "."))
    vencidas = 0
    if not df_f.empty:
        vencidas = df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < datetime.now().date()].shape[0]
    c2.metric("Facturas Vencidas", vencidas)
    c3.metric("Documentos", len(df_f))

def modulo_compras():
    st.header("📦 Compras")
    t1, t2 = st.tabs(["➕ Nueva Factura", "🔍 Historial"])
    with t1:
        with st.form("fac"):
            n, p = st.text_input("N° Factura"), st.text_input("Proveedor")
            fc, fv = st.date_input("Emisión"), st.date_input("Vencimiento")
            mt = st.number_input("Monto Total", min_value=0.0)
            if st.form_submit_button("GUARDAR"):
                conn = conectar_db(); conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total) VALUES (?,?,?,?,?)", (n, p, fc, fv, mt))
                conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
    with t2:
        conn = conectar_db(); df = pd.read_sql_query("SELECT * FROM facturas ORDER BY id DESC", conn); conn.close()
        st.dataframe(df, use_container_width=True)
        st.download_button("📥 PDF Historial", generar_pdf(df, "HISTORIAL DE COMPRAS"), "historial.pdf")

def modulo_tesoreria():
    st.header("💸 Tesorería")
    conn = conectar_db(); df = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente'", conn); conn.close()
    if not df.empty:
        st.dataframe(df, use_container_width=True)
        id_p = st.selectbox("ID a Pagar", df['id'])
        if st.button("💰 PAGAR"):
            conn = conectar_db(); conn.execute("UPDATE facturas SET estado='Pagado', fecha_pago=? WHERE id=?", (datetime.now().date(), id_p))
            conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
        st.download_button("📥 PDF Pendientes", generar_pdf(df, "PENDIENTES"), "pendientes.pdf")

def modulo_bodega():
    st.header("🚜 Bodega e Inventario")
    t1, t2 = st.tabs(["📊 Stock", "🔄 Movimiento"])
    with t1:
        conn = conectar_db(); df = pd.read_sql_query("SELECT id, producto, familia, stock, stock_minimo FROM inventario", conn); conn.close()
        def color_stock(row): return ['background-color: #ffcccc' if row['stock'] < row['stock_minimo'] else '' for _ in row]
        st.dataframe(df.style.apply(color_stock, axis=1), use_container_width=True)
        st.download_button("📥 PDF Stock", generar_pdf(df, "STOCK BODEGA"), "stock.pdf")
    with t2:
        with st.form("mov"):
            conn = conectar_db(); prs = pd.read_sql_query("SELECT id, producto FROM inventario ORDER BY producto", conn); conn.close()
            ps = st.selectbox("Insumo", prs['id'].astype(str) + " - " + prs['producto'])
            tm, cm = st.radio("Tipo", ["Salida (Campo)", "Entrada"]), st.number_input("Cant.", min_value=0.1)
            cc = st.selectbox("Cuartel", CENTROS_COSTO)
            if st.form_submit_button("REGISTRAR"):
                ip = int(ps.split(" - ")[0]); conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo) VALUES (?,?,?,?,?)", (ip, tm, cm, datetime.now().date(), cc))
                f = 1 if tm == "Entrada" else -1
                cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (cm*f, ip))
                conn.commit(); conn.close(); guardar_en_drive(); st.rerun()

# --- NAVEGACION ---
st.sidebar.title("LA CONCEPCIÓN ERP")
if 'db_sincronizada' not in st.session_state:
    descargar_de_drive(); st.session_state['db_sincronizada'] = True

inicializar_db()
menu = st.sidebar.radio("Navegación", ["🏠 Dashboard", "📦 Compras", "💸 Tesorería", "🚜 Bodega"])

if menu == "🏠 Dashboard": modulo_dashboard()
elif menu == "📦 Compras": modulo_compras()
elif menu == "💸 Tesorería": modulo_tesoreria()
elif menu == "🚜 Bodega": modulo_bodega()
