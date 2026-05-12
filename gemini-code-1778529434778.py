import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import os

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="AGRICOLA LA CONCEPCION ERP", page_icon="🚜", layout="wide")

# --- CONEXIÓN A BASE DE DATOS ---
def conectar_db():
    return sqlite3.connect('erp_concepcion_v6.db')

def inicializar_db():
    conn = conectar_db(); cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS facturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nro_documento TEXT, proveedor TEXT, 
        fecha_compra DATE, fecha_vencimiento DATE, monto_neto REAL, monto_total REAL, estado TEXT DEFAULT 'Pendiente')''')
    
    # Aquí estaba el error, ahora está corregido:
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
    
    # BOTÓN DE RESPALDO
    if os.path.exists('erp_concepcion_v6.db'):
        with open('erp_concepcion_v6.db', 'rb') as f:
            st.download_button(
                label="💾 Descargar Respaldo DB",
                data=f,
                file_name=f"respaldo_la_concepcion_{datetime.now().strftime('%Y%m%d')}.db",
                mime="application/x-sqlite3"
            )
    
    if st.button("🗑️ Limpiar Carrito"):
        st.session_state['carrito'] = []
        st.rerun()

# --- 1. DASHBOARD ---
if menu == "🏠 Dashboard":
    st.header("📊 Resumen de Compromisos Financieros")
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
        col2.metric("Facturas Vencidas", vencidas, delta="¡Urgente!" if vencidas > 0 else "", delta_color="inverse")
    
    st.markdown("---")
    st.subheader("📅 Proyección de Pagos Mensuales (Monto Neto + IVA)")
    
    fecha_actual = datetime.now()
    meses_proyeccion = []
    for i in range(4):
        mes = (fecha_actual.month + i - 1) % 12 + 1
        anio = fecha_actual.year + (fecha_actual.month + i - 1) // 12
        meses_proyeccion.append((mes, anio))

    cols_meses = st.columns(4)
    
    if not df_f.empty:
        df_f['fecha_vencimiento'] = pd.to_datetime(df_f['fecha_vencimiento'])
        for idx, (m, a) in enumerate(meses_proyeccion):
            nombre_mes = obtener_nombre_mes(m)
            monto_mes = df_f[(df_f['fecha_vencimiento'].dt.month == m) & 
                             (df_f['fecha_vencimiento'].dt.year == a)]['monto_total'].sum()
            
            with cols_meses[idx]:
                st.markdown(f"### {nombre_mes}")
                st.markdown(f"<h2 style='color: #2E7D32;'>${monto_mes:,.0f}</h2>", unsafe_allow_html=True)
    else:
        st.info("No hay facturas pendientes para proyectar pagos.")

# --- 2. COMPRAS ---
elif menu == "📦 Compras":
    st.header("Ingreso de Compras")
    t1, t2 = st.tabs(["➕ Nueva Factura", "📜 Historial"])
    
    with t1:
        c1, c2 = st.columns(2)
        nro = c1.text_input("N° Factura")
        prov = c1.text_input("Proveedor")
        f_c = c2.date_input("Fecha Compra", datetime.now())
        f_v = c2.date_input("Fecha Vencimiento", datetime.now() + timedelta(days=30))
        
        conn = conectar_db()
        df_inv = pd.read_sql_query("SELECT id, producto FROM inventario", conn)
        conn.close()
        
        if df_inv.empty:
            st.warning("⚠️ Crea productos en 'Inventario' primero.")
        else:
            st.markdown("---")
            cp1, cp2, cp3, cp4 = st.columns([3, 1, 1, 1])
            p_sel = cp1.selectbox("Producto", df_inv['id'].astype(str) + " - " + df_inv['producto'])
            cant = cp2.number_input("Cant.", min_value=0.0, step=0.1)
            prec = cp3.number_input("Neto Unit.", min_value=0.0)
            
            if cp4.button("➕ Añadir"):
                if cant > 0:
                    st.session_state['carrito'].append({
                        'id': int(p_sel.split(" - ")[0]), 'nombre': p_sel.split(" - ")[1],
                        'cantidad': cant, 'precio': prec, 'total': cant * prec
                    })
                    st.rerun()

            if st.session_state['carrito']:
                st.table(pd.DataFrame(st.session_state['carrito'])[['nombre', 'cantidad', 'precio', 'total']])
                neto_t = sum(i['total'] for i in st.session_state['carrito'])
                total_f = st.number_input("Total Final (IVA incluido)", value=neto_t * 1.19)
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
                        st.success("¡Factura guardada!"); st.rerun()

    with t2:
        conn = conectar_db()
        st.dataframe(pd.read_sql_query("SELECT * FROM facturas ORDER BY id DESC", conn), use_container_width=True)
        id_borrar = st.number_input("ID para borrar", min_value=0)
        if st.button("Eliminar Factura"):
            eliminar_factura(id_borrar); st.rerun()
        conn.close()

# --- 3. CUENTAS POR PAGAR ---
elif menu == "💸 Cuentas por Pagar":
    st.header("Gestión de Pagos")
    conn = conectar_db()
    df_p = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente'", conn)
    st.dataframe(df_p, use_container_width=True)
    if not df_p.empty:
        id_pago = st.selectbox("ID para Pagar", df_p['id'])
        if st.button("💰 Marcar como Pagado"):
            cursor = conn.cursor()
            cursor.execute("UPDATE facturas SET estado='Pagado' WHERE id=?", (id_pago,))
            conn.commit(); st.success("Pagado!"); st.rerun()
    conn.close()

# --- 4. INVENTARIO ---
elif menu == "🚜 Inventario":
    st.header("Maestro de Inventario")
    t1, t2 = st.tabs(["📊 Stock", "➕ Crear Producto"])
    with t2:
        with st.form("nuevo"):
            n = st.text_input("Nombre (Ej: Petróleo)")
            f = st.selectbox("Familia", ["Petróleo", "Insumos", "Fertilizantes", "Repuestos"])
            if st.form_submit_button("Crear"):
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO inventario (producto, familia) VALUES (?,?)", (n, f))
                conn.commit(); conn.close(); st.rerun()
    with t1:
        conn = conectar_db()
        st.dataframe(pd.read_sql_query("SELECT * FROM inventario", conn), use_container_width=True)
        conn.close()
