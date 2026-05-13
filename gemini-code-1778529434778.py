import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import os

# --- LIBRERÍAS DE PERSISTENCIA Y REPORTES ---
try:
    from fpdf import FPDF
    from pydrive2.auth import GoogleAuth
    from pydrive2.drive import GoogleDrive
    from oauth2client.service_account import ServiceAccountCredentials
except ImportError:
    st.error("Faltan librerías. Revisa tu archivo requirements.txt")

# --- CONFIGURACIÓN DE PERSISTENCIA (GOOGLE DRIVE) ---
ID_CARPETA_DRIVE = "1V7IwdbJPzxQ-hJQaVqOWejHHA1mNbgLo" 
NOMBRE_DB = 'erp_concepcion_v6.db'
JSON_KEY = 'secretos.json'

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

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="AGRICOLA LA CONCEPCION ERP", page_icon="🚜", layout="wide")

# Sincronización inicial
if 'db_sincronizada' not in st.session_state:
    descargar_de_drive()
    st.session_state['db_sincronizada'] = True

CLAVE_SEGURIDAD = "2908"

def f_puntos(v):
    try: return f"{int(v):,}".replace(",", ".")
    except: return "0"

# --- GENERADOR DE PDF ---
def generar_pdf(df, titulo_reporte):
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", "B", 16)
        pdf.cell(0, 10, "AGRICOLA LA CONCEPCIÓN", ln=True, align="C")
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 10, titulo_reporte, ln=True, align="C")
        pdf.ln(5)
        pdf.set_font("Arial", "I", 8)
        pdf.cell(0, 5, f"Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True, align="R")
        pdf.ln(5)
        
        pdf.set_font("Arial", "B", 8)
        cols = df.columns
        w = 190 / len(cols)
        for col in cols: pdf.cell(w, 8, str(col), border=1, align="C")
        pdf.ln()
        
        pdf.set_font("Arial", "", 7)
        for _, row in df.iterrows():
            for item in row:
                val = f_puntos(item) if isinstance(item, (int, float)) else str(item)
                pdf.cell(w, 7, val[:20], border=1)
            pdf.ln()
        return pdf.output(dest="S").encode("latin-1")
    except: return None

# --- BASE DE DATOS ---
def conectar_db(): return sqlite3.connect(NOMBRE_DB)

def inicializar_db():
    conn = conectar_db(); cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS facturas (id INTEGER PRIMARY KEY AUTOINCREMENT, nro_documento TEXT, proveedor TEXT, fecha_compra DATE, fecha_vencimiento DATE, monto_neto REAL, monto_total REAL, estado TEXT DEFAULT 'Pendiente', tipo TEXT DEFAULT 'Factura', metodo_pago TEXT, fecha_pago DATE, concepto TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS detalle_facturas (id INTEGER PRIMARY KEY AUTOINCREMENT, factura_id INTEGER, producto_id INTEGER, cantidad REAL, precio_neto REAL, total_linea REAL)")
    cursor.execute("CREATE TABLE IF NOT EXISTS inventario (id INTEGER PRIMARY KEY AUTOINCREMENT, producto TEXT, familia TEXT, stock REAL DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS movimientos (id INTEGER PRIMARY KEY AUTOINCREMENT, producto_id INTEGER, tipo TEXT, cantidad REAL, centro_costo TEXT, fecha DATE, factura_id INTEGER)")
    conn.commit(); conn.close()

def eliminar_factura(id_f):
    conn = conectar_db(); cursor = conn.cursor()
    detalles = cursor.execute("SELECT producto_id, cantidad FROM detalle_facturas WHERE factura_id=?", (id_f,)).fetchall()
    for p_id, cant in detalles:
        cursor.execute("UPDATE inventario SET stock = stock - ? WHERE id = ?", (cant, p_id))
    cursor.execute("DELETE FROM movimientos WHERE factura_id=?", (id_f,))
    cursor.execute("DELETE FROM detalle_facturas WHERE factura_id=?", (id_f,))
    cursor.execute("DELETE FROM facturas WHERE id=?", (id_f,))
    conn.commit(); conn.close(); guardar_en_drive()

inicializar_db()
if 'carrito' not in st.session_state: st.session_state['carrito'] = []

# --- BARRA LATERAL ---
with st.sidebar:
    st.title("LA CONCEPCIÓN ERP")
    if os.path.exists(JSON_KEY): st.success("☁️ Drive: ACTIVA")
    else: st.error("⚠️ Falta secretos.json")
    menu = st.radio("Navegación", ["🏠 Dashboard", "📦 Compras", "💸 Tesorería", "🚜 Bodega"])
    if st.button("🗑️ Vaciar Carrito"): st.session_state['carrito'] = []; st.rerun()

# --- 1. DASHBOARD ---
if menu == "🏠 Dashboard":
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

    st.subheader("📅 Proyección de Pagos (4 Meses)")
    cols_m = st.columns(4)
    meses_n = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]
    for i in range(4):
        fp = datetime.now() + timedelta(days=i*30)
        m, a = fp.month, fp.year
        val_m = 0
        if not df_f.empty:
            df_f['fv'] = pd.to_datetime(df_f['fecha_vencimiento'])
            val_m = df_f[(df_f['fv'].dt.month == m) & (df_f['fv'].dt.year == a)]['monto_total'].sum()
        cols_m[i].metric(f"{meses_n[m-1]} {a}", f"${f_puntos(val_m)}")

# --- 2. COMPRAS ---
elif menu == "📦 Compras":
    st.header("Módulo de Compras")
    t1, t2, t3 = st.tabs(["➕ Factura Insumos", "💸 Gasto Vario", "🔍 Historial"])
    
    with t1:
        c1, c2 = st.columns(2)
        nro, prov = c1.text_input("Número Factura"), c1.text_input("Proveedor")
        f_c, f_v = c2.date_input("Emisión"), c2.date_input("Vencimiento")
        
        conn = conectar_db(); df_inv = pd.read_sql_query("SELECT id, producto FROM inventario", conn); conn.close()
        if not df_inv.empty:
            st.subheader("🛒 Carrito")
            cp1, cp2, cp3, cp4 = st.columns([3,1,1,1])
            p_sel = cp1.selectbox("Producto", df_inv['id'].astype(str) + " - " + df_inv['producto'])
            cant, prec = cp2.number_input("Cant.", min_value=0.1), cp3.number_input("Neto Un.", min_value=0.0)
            if cp4.button("➕"):
                st.session_state['carrito'].append({'id': int(p_sel.split(" - ")[0]), 'nombre': p_sel.split(" - ")[1], 'cantidad': cant, 'precio': prec, 'total': cant * prec})
                st.rerun()

        if st.session_state['carrito']:
            df_c = pd.DataFrame(st.session_state['carrito'])
            st.table(df_c[['nombre', 'cantidad', 'precio', 'total']])
            neto = df_c['total'].sum()
            m_final = st.number_input("Total Final Factura", value=float(neto*1.19))
            if st.button("💾 GUARDAR FACTURA"):
                conn = conectar_db(); cursor = conn.cursor()
