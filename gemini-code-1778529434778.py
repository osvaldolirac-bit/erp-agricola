import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import os

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="AGRICOLA LA CONCEPCION ERP", page_icon="🚜", layout="wide")

# --- SEGURIDAD ---
CLAVE_SEGURIDAD = "2908"

# --- CONEXIÓN A BASE DE DATOS ---
def conectar_db():
    return sqlite3.connect('erp_concepcion_v6.db')

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

# --- FUNCIONES AUXILIARES ---
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

# --- INICIALIZACIÓN ---
inicializar_db()
if 'carrito' not in st.session_state:
    st.session_state['carrito'] = []

# --- SIDEBAR ---
with st.sidebar:
    if os.path.exists("logo.png"): st.image("logo.png", use_container_width=True)
    st.title("AGRICOLA LA CONCEPCION")
    st.markdown("---")
    menu = st.radio("Navegación", ["🏠 Dashboard", "📦 Compras", "💸 Cuentas por Pagar", "🚜 Inventario"])
    st.markdown("---")
    if os.path.exists('erp_concepcion_v6.db'):
        with open('erp_concepcion_v6.db', 'rb') as f:
            st.download_button("💾 Descargar Respaldo DB", f, "respaldo_agricola.db", "application/x-sqlite3")
    if st.button("🗑️ Limpiar Carrito"):
        st.session_state['carrito'] = []
        st.rerun()

# --- 1. DASHBOARD ---
if menu == "🏠 Dashboard":
    st.header("📊 Resumen de Compromisos")
    conn = conectar_db()
    df_f = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente'", conn)
    conn.close()
    col1, col2 = st.columns(2)
    total_deuda = df_f['monto_total'].sum()
    col1.metric("Deuda Total Pendiente", f"${total_deuda:,.0f}")
    hoy = datetime.now().date()
    if not df_f.empty:
        df_f['fecha_vencimiento'] = pd.to_datetime(df_f['fecha_vencimiento']).dt.date
        vencidas = df_f[df_f['fecha_vencimiento'] < hoy].shape[0]
        col2.metric("Vencimientos Atrasados", vencidas, delta_color="inverse")
    st.markdown("---")
    st.subheader("📅 Pagos Próximos 4 Meses")
    fecha_actual = datetime.now()
    cols_meses = st.columns(4)
    if not df_f.empty:
        df_f['fecha_vencimiento'] = pd.to_datetime(df_f['fecha_vencimiento'])
        for i in range(4):
            m = (fecha_actual.month + i - 1) % 12 + 1
            a = fecha_actual.year + (fecha_actual.month + i - 1) // 12
            monto_mes = df_f[(df_f['fecha_vencimiento'].dt.month == m) & (df_f['fecha_vencimiento'].dt.year == a)]['monto_total'].sum()
            with cols_meses[i]:
                st.markdown(f"### {obtener_nombre_mes(m)}")
                st.markdown(f"<h2 style='color: #2E7D32;'>${monto_mes:,.0f}</h2>", unsafe_allow_html=True)

# --- 2. COMPRAS ---
elif menu == "📦 Compras":
    st.header("Gestión de Adquisiciones")
    t1, t2, t3 = st.tabs(["➕ Factura Insumos", "💸 Gasto Vario", "🔍 Historial y Eliminación"])
    
    with t1:
        c1, c2 = st.columns(2)
        nro = c1.text_input("N° Factura")
        prov = c1.text_input("Proveedor")
        f_c = c2.date_input("Fecha Compra", datetime.now())
        f_v = c2.date_input("Fecha Vencimiento", datetime.now() + timedelta(days=30))
        conn = conectar_db()
        df_inv = pd.read_sql_query("SELECT id, producto FROM inventario ORDER BY producto", conn)
        conn.close()
        if not df_inv.empty:
            cp1, cp2, cp3, cp4 = st.columns([3,1,1,1])
            p_sel = cp1.selectbox("Producto", df_inv['id'].astype(str) + " - " + df_inv['producto'])
            cant = cp2.number_input("Cant.", min_value=0.0)
            prec = cp3.number_input("Neto Unit.", min_value=0.0)
            if cp4.button("➕"):
                if cant > 0:
                    st.session_state['carrito'].append({'id': int(p_sel.split(" - ")[0]), 'nombre': p_sel.split(" - ")[1], 'cantidad': cant, 'precio': prec, 'total': cant * prec})
                    st.rerun()
            if st.session_state['carrito']:
                st.table(pd.DataFrame(st.session_state['carrito'])[['nombre', 'cantidad', 'precio', 'total']])
                neto_t = sum(i['total'] for i in st.session_state['carrito'])
                total_f = st.number_input("Total Final Factura", value=neto_t * 1.19)
                bod = st.selectbox("Bodega", ["Central", "Insumos", "Petróleo"])
                if st.button("💾 GUARDAR FACTURA"):
                    conn = conectar_db(); cursor = conn.cursor()
                    cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_neto, monto_total, tipo) VALUES (?,?,?,?,?,?,?)", (nro, prov, f_c, f_v, neto_t, total_f, 'Factura'))
                    id_f = cursor.lastrowid
                    for i in st.session_state['carrito']:
                        cursor.execute("INSERT INTO detalle_facturas (factura_id, producto_id, cantidad, precio_neto, total_linea) VALUES (?,?,?,?,?)", (id_f, i['id'], i['cantidad'], i['precio'], i['total']))
                        cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, bodega, fecha, factura_id, centro_costo) VALUES (?,?,?,?,?,?,?)", (i['id'], "Entrada", i
