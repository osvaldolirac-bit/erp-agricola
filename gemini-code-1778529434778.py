import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import os

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="AGRICOLA LA CONCEPCION ERP", page_icon="🚜", layout="wide")

# --- CONEXIÓN A BASE DE DATOS (v6) ---
def conectar_db():
    return sqlite3.connect('erp_concepcion_v6.db')

def inicializar_db():
    conn = conectar_db(); cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS facturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nro_documento TEXT, proveedor TEXT, 
        fecha_compra DATE, fecha_vencimiento DATE, monto_neto REAL, monto_total REAL, estado TEXT DEFAULT 'Pendiente')''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS detalle_facturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, factura_id INTEGER, producto_id INTEGER, 
        cantidad REAL, precio_neto REAL, total_linea REAL)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS inventario (
        id INTEGER PRIMARY KEY AUTOINCREMENT, producto TEXT, familia TEXT, stock REAL DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS movimientos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, producto_id INTEGER, tipo TEXT, 
        cantidad REAL, centro_costo TEXT, bodega TEXT, fecha DATE, factura_id INTEGER)''')
    conn.commit(); conn.close()

# --- LÓGICA DE ELIMINACIÓN ---
def eliminar_factura(id_f):
    conn = conectar_db(); cursor = conn.cursor()
    detalles = cursor.execute("SELECT producto_id, cantidad FROM detalle_facturas WHERE factura_id=?", (id_f,)).fetchall()
    for p_id, cant in detalles:
        cursor.execute("UPDATE inventario SET stock = stock - ? WHERE id = ?", (cant, p_id))
    cursor.execute("DELETE FROM movimientos WHERE factura_id=?", (id_f,))
    cursor.execute("DELETE FROM detalle_facturas WHERE factura_id=?", (id_f,))
    cursor.execute("DELETE FROM facturas WHERE id=?", (id_f,))
    conn.commit(); conn.close()

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
    if st.button("🗑️ Limpiar Carrito de Compras"):
        st.session_state['carrito'] = []
        st.rerun()

# --- 1. DASHBOARD ---
if menu == "🏠 Dashboard":
    st.header("📊 Resumen Operativo")
    conn = conectar_db()
    df_f = pd.read_sql_query("SELECT * FROM facturas", conn)
    col1, col2, col3, col4 = st.columns(4)
    
    deuda = df_f[df_f['estado']=='Pendiente']['monto_total'].sum()
    col1.metric("Deuda Pendiente", f"${deuda:,.0f}")
    
    stock_t = pd.read_sql_query("SELECT SUM(stock) as s FROM inventario", conn)['s'][0] or 0
    col2.metric("Stock Total", f"{stock_t:,.1f}")
    
    hoy = datetime.now().date()
    if not df_f.empty:
        df_f['fecha_vencimiento'] = pd.to_datetime(df_f['fecha_vencimiento']).dt.date
        vencidas = df_f[(df_f['estado']=='Pendiente') & (df_f['fecha_vencimiento'] < hoy)].shape[0]
        col3.metric("Facturas Vencidas", vencidas, delta="¡Revisar!" if vencidas > 0 else "", delta_color="inverse")
    
    st.markdown("---")
    st.subheader("📅 Proyección Financiera (Próximos Meses)")
    if not df_f.empty:
        pend = df_f[df_f['estado']=='Pendiente'].copy()
        pend['Mes'] = pd.to_datetime(pend['fecha_vencimiento']).dt.strftime('%m-%Y')
        proy = pend.groupby('Mes')['monto_total'].sum().reset_index()
        st.bar_chart(proy.set_index('Mes'))
    else:
        st.info("Ingresa facturas para ver proyecciones.")
    conn.close()

# --- 2. COMPRAS (MULTI-PRODUCTO MEJORADO) ---
elif menu == "📦 Compras":
    st.header("Ingreso de Compras")
    t1, t2 = st.tabs(["➕ Nueva Factura", "📜 Historial"])
    
    with t1:
        c1, c2 = st.columns(2)
        nro = c1.text_input("N° Factura")
        prov = c1.text_input("Proveedor")
        f_c = c2.date_input("Fecha Compra", datetime.now())
        f_v = c2.date_input("Fecha Vencimiento", datetime.now() + timedelta(days=30))
        
        st.markdown("### 🛒 Detalle de Productos")
        conn = conectar_db()
        df_inv = pd.read_sql_query("SELECT id, producto FROM inventario", conn)
        conn.close()
        
        # VERIFICACIÓN CRÍTICA DE PRODUCTOS
        if df_inv.empty:
            st.error("⚠️ NO HAY PRODUCTOS EN INVENTARIO. Ve al módulo 'Inventario' y crea productos primero.")
        else:
            col_p1, col_p2, col_p3, col_p4 = st.columns([3, 1, 1, 1])
            p_sel = col_p1.selectbox("Seleccionar Producto", df_inv['id'].astype(str) + " - " + df_inv['producto'])
            c_p = col_p2.number_input("Cant.", min_value=0.0, step=0.1)
            pr_p = col_p3.number_input("Precio Neto", min_value=0.0)
            
            if col_p4.button("➕ Añadir"):
                if c_p > 0:
                    st.session_state['carrito'].append({
                        'id': int(p_sel.split(" - ")[0]), 'nombre': p_sel.split(" - ")[1],
                        'cantidad': c_p, 'precio': pr_p, 'total': c_p * pr_p
                    })
                    st.rerun()

            if st.session_state['carrito']:
                st.table(pd.DataFrame(st.session_state['carrito'])[['nombre', 'cantidad', 'precio', 'total']])
                neto_t = sum(item['total'] for item in st.session_state['carrito'])
                total_f = st.number_input("Total Final Factura (Neto + IVA + Impuestos)", value=neto_t * 1.19)
                bod = st.selectbox("Bodega", ["Central", "Insumos", "Petróleo"])
                
                if st.button("💾 GUARDAR FACTURA COMPLETA"):
                    if nro and prov:
                        conn = conectar_db(); cursor = conn.cursor()
                        cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_neto, monto_total) VALUES (?,?,?,?,?,?)",
                                       (nro, prov, f_c, f_v, neto_t, total_f))
                        id_fact = cursor.lastrowid
                        for i in st.session_state['carrito']:
                            cursor.execute("INSERT INTO detalle_facturas (factura_id, producto_id, cantidad, precio_neto, total_linea) VALUES (?,?,?,?,?)",
                                           (id_fact, i['id'], i['cantidad'], i['precio'], i['total']))
                            cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, bodega, fecha, factura_id) VALUES (?,?,?,?,?,?)",
                                           (i['id'], "Entrada", i['cantidad'], bod, f_c, id_fact))
                            cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (i['cantidad'], i['id']))
                        conn.commit(); conn.close()
                        st.session_state['carrito'] = []
                        st.success("¡Guardado!"); st.rerun()

    with t2:
        conn = conectar_db()
        st.dataframe(pd.read_sql_query("SELECT * FROM facturas ORDER BY id DESC", conn), use_container_width=True)
        conn.close()

# --- 3. CUENTAS POR PAGAR ---
elif menu == "💸 Cuentas por Pagar":
    st.header("Pagos")
    conn = conectar_db()
    df_p = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente'", conn)
    st.dataframe(df_p, use_container_width=True)
    if not df_p.empty:
        id_pago = st.selectbox("Factura a Pagar ID", df_p['id'])
        if st.button("💰 Marcar como Pagado"):
            cursor = conn.cursor()
            cursor.execute("UPDATE facturas SET estado='Pagado' WHERE id=?", (id_pago,))
            conn.commit(); st.success("Pagado!"); st.rerun()
    conn.close()

# --- 4. INVENTARIO ---
elif menu == "🚜 Inventario":
    st.header("Maestro de Inventario")
    t_inv1, t_inv2 = st.tabs(["📊 Stock", "➕ Crear Producto"])
    
    with t_inv2:
        with st.form("nuevo_item"):
            nom_p = st.text_input("Nombre (Ej: Urea)")
            fam_p = st.selectbox("Familia", ["Insumos", "Fertilizantes", "Petróleo", "Semillas"])
            if st.form_submit_button("Crear Producto"):
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO inventario (producto, familia) VALUES (?,?)", (nom_p, fam_p))
                conn.commit(); conn.close(); st.success("Producto creado con éxito!"); st.rerun()

    with t_inv1:
        conn = conectar_db()
        st.dataframe(pd.read_sql_query("SELECT * FROM inventario", conn), use_container_width=True)
        conn.close()
