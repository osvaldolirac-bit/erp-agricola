import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import os

# Intentamos importar FPDF
try:
    from fpdf import FPDF
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="AGRICOLA LA CONCEPCION ERP", page_icon="🚜", layout="wide")

# --- SEGURIDAD ---
CLAVE_SEGURIDAD = "2908"
DB_NAME = 'erp_concepcion_v6.db'

# --- FUNCIÓN DE FORMATEO (1.000.000) ---
def f_puntos(valor):
    try:
        return f"{int(valor):,}".replace(",", ".")
    except:
        return "0"

# --- DIAGNÓSTICO ---
if not PDF_AVAILABLE:
    st.sidebar.warning("⚠️ Sin PDF: Agregue 'fpdf' a requirements.txt")

# --- FUNCIÓN GENERADORA DE PDF ---
def generar_pdf(df, titulo):
    if not PDF_AVAILABLE: return None
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", "B", 14)
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
                val = f_num_simple(item) if isinstance(item, (int, float)) else str(item)
                pdf.cell(w, 7, val[:20], border=1)
            pdf.ln()
        return pdf.output(dest="S").encode("latin-1")
    except: return None

def f_num_simple(n):
    return f"{int(n):,}".replace(",", ".")

# --- CONEXIÓN A BASE DE DATOS ---
def conectar_db():
    return sqlite3.connect(DB_NAME)

def inicializar_db():
    conn = conectar_db(); cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS facturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nro_documento TEXT, proveedor TEXT, 
        fecha_compra DATE, fecha_vencimiento DATE, monto_neto REAL, monto_total REAL, 
        estado TEXT DEFAULT 'Pendiente', tipo TEXT DEFAULT 'Factura',
        metodo_pago TEXT, fecha_pago DATE)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS detalle_facturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, factura_id INTEGER, producto_id INTEGER, 
        cantidad REAL, precio_neto REAL, total_linea REAL)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS inventario (
        id INTEGER PRIMARY KEY AUTOINCREMENT, producto TEXT, familia TEXT, stock REAL DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS movimientos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, producto_id INTEGER, tipo TEXT, 
        cantidad REAL, centro_costo TEXT, bodega TEXT, fecha DATE, factura_id INTEGER)''')
    conn.commit(); conn.close()

def eliminar_factura(id_f):
    conn = conectar_db(); cursor = conn.cursor()
    detalles = cursor.execute("SELECT producto_id, cantidad FROM detalle_facturas WHERE factura_id=?", (id_f,)).fetchall()
    for p_id, cant in detalles:
        cursor.execute("UPDATE inventario SET stock = stock - ? WHERE id = ?", (cant, p_id))
    cursor.execute("DELETE FROM movimientos WHERE factura_id=?", (id_f,))
    cursor.execute("DELETE FROM detalle_facturas WHERE factura_id=?", (id_f,))
    cursor.execute("DELETE FROM facturas WHERE id=?", (id_f,))
    conn.commit(); conn.close()

def obtener_nombre_mes(mes_num):
    meses = {1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
             7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"}
    return meses.get(mes_num, "")

inicializar_db()
if 'carrito' not in st.session_state: st.session_state['carrito'] = []

# --- SIDEBAR ---
with st.sidebar:
    st.title("AGRICOLA LA CONCEPCION")
    menu = st.radio("Navegación", ["🏠 Dashboard", "📦 Compras", "💸 Cuentas por Pagar", "🚜 Inventario"])
    st.markdown("---")
    if os.path.exists(DB_NAME):
        with open(DB_NAME, 'rb') as f:
            st.download_button("💾 Respaldo DB", f, DB_NAME, "application/x-sqlite3")
    if st.button("🗑️ Vaciar Carrito"):
        st.session_state['carrito'] = []
        st.rerun()

# --- 1. DASHBOARD ---
if menu == "🏠 Dashboard":
    st.header("📊 Resumen Financiero")
    conn = conectar_db()
    df_f = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente'", conn)
    conn.close()
    
    c1, c2 = st.columns(2)
    total = df_f['monto_total'].sum() if not df_f.empty else 0
    c1.metric("Deuda Pendiente Total", f"${f_puntos(total)}")
    
    hoy = datetime.now().date()
    vencidas = df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < hoy].shape[0] if not df_f.empty else 0
    c2.metric("Documentos Vencidos", vencidas, delta_color="inverse")
    
    st.subheader("📅 Proyección de Pagos (Próximos 4 meses)")
    cols_m = st.columns(4)
    for i in range(4):
        f_target = datetime.now() + timedelta(days=i*30)
        m, a = f_target.month, f_target.year
        monto = 0
        if not df_f.empty:
            df_f['fv'] = pd.to_datetime(df_f['fecha_vencimiento'])
            monto = df_f[(df_f['fv'].dt.month == m) & (df_f['fv'].dt.year == a)]['monto_total'].sum()
        with cols_m[i]:
            st.markdown(f"**{obtener_nombre_mes(m)}**")
            st.markdown(f"## ${f_puntos(monto)}")

# --- 2. COMPRAS ---
elif menu == "📦 Compras":
    st.header("Gestión de Compras")
    t1, t2, t3 = st.tabs(["➕ Factura", "💸 Gasto Vario", "🔍 Historial"])
    
    with t1:
        c1, c2 = st.columns(2)
        nro = c1.text_input("N° Factura")
        prov = c1.text_input("Proveedor
