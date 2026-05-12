import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import os

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="AGRICOLA LA CONCEPCION ERP", page_icon="🚜", layout="wide")

# --- LÓGICA DE BASE DE DATOS Y MIGRACIÓN ---
def conectar_db():
    return sqlite3.connect('agricola_erp.db')

def inicializar_db():
    conn = conectar_db(); cursor = conn.cursor()
    # Tablas
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
    cursor.execute('''CREATE TABLE IF NOT EXISTS pagos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, factura_id INTEGER, monto_pagado REAL, 
        fecha_pago DATE, metodo_pago TEXT)''')
    
    # Auto-reparación de columnas (Migración)
    cursor.execute("PRAGMA table_info(facturas)")
    columnas = [info[1] for info in cursor.fetchall()]
    if 'nro_documento' not in columnas: cursor.execute("ALTER TABLE facturas ADD COLUMN nro_documento TEXT")
    if 'monto_neto' not in columnas: cursor.execute("ALTER TABLE facturas ADD COLUMN monto_neto REAL")
    
    conn.commit(); conn.close()

# --- FUNCIONES DE APOYO ---
def eliminar_factura(id_f):
    conn = conectar_db(); cursor = conn.cursor()
    movs = cursor.execute("SELECT producto_id, cantidad FROM movimientos WHERE factura_id=?", (id_f,)).fetchall()
    for p_id, cant in movs:
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
    else: st.title("🚜")
    st.title("AGRICOLA LA CONCEPCION")
    st.markdown("---")
    menu = st.radio("Navegación", ["🏠 Dashboard", "📦 Compras", "💸 Cuentas por Pagar", "🚜 Inventario"])
    st.markdown("---")
    if os.path.exists('agricola_erp.db'):
        with open('agricola_erp.db', 'rb') as f:
            st.download_button("💾 Descargar Respaldo DB", f, "respaldo.db", "application/x-sqlite3")

# --- 1. DASHBOARD (DISEÑO RESTAURADO v4.2) ---
if menu == "🏠 Dashboard":
    st.header("📊 Resumen Operativo y Financiero")
    conn = conectar_db()
    
    # Métricas v4.2
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
        col3.metric("Facturas Vencidas", vencidas, delta="¡Urgente!" if vencidas > 0 else "", delta_color="inverse")
        
        prox = df_f[(df_f['estado']=='Pendiente') & (df_f['fecha_vencimiento'] >= hoy)].sort_values('fecha_vencimiento').head(1)
        col4.metric("Próximo Pago", prox['fecha_vencimiento'].values[0].strftime('%d/%m') if not prox.empty else "---")

    st.markdown("---")
    
    # Proyección 90 días (Mayo - Agosto)
    st.subheader("📅 Proyección de Pagos (Próximos 3 Meses)")
    if not df_f.empty:
        pend = df_f[df_f['estado']=='Pendiente'].copy()
        pend['Mes'] = pd.to_datetime(pend['fecha_vencimiento']).dt.strftime('%m-%Y')
        proy_mes = pend.groupby('Mes')['monto_total'].sum()
        st.bar_chart(proy_mes)
    
    st.subheader("⚠️ Alertas de Stock Bajo")
    df_bajo = pd.read_sql_query("SELECT producto, stock FROM inventario WHERE stock < 10", conn)
    st.dataframe(df_bajo, use_container_width=True)
    conn.close()

# --- 2. COMPRAS (NUEVO MULTI-PRODUCTO EN DISEÑO v4.2) ---
elif menu == "📦 Compras":
    st.header("Gestión de Compras")
    t1, t2 = st.tabs(["➕ Nueva Factura (Multi-Producto)", "📜 Historial / Eliminar"])
    
    with t1:
        with st.container():
            c1, c2 = st.columns(2)
            nro = c1.text_input("Número Factura")
            prov = c1.text_input("Proveedor")
            f_c = c2.date_input("Fecha Compra", datetime.now())
            f_v = c2.date_input("Fecha Vencimiento", datetime.now() + timedelta(days=30))
            
            st.divider()
            st.subheader("Añadir Productos")
            conn = conectar_db()
            prods = pd.read_sql_query("SELECT id, producto FROM inventario", conn)
            conn.close()
            
            cp1, cp2, cp3, cp4 = st.columns([3,1,1,1])
            p_sel = cp1.selectbox("Producto", prods['id'].astype(str) + " - " + prods['producto']) if not prods.empty else None
            cant_p = cp2.number_input("Cant.", min_value=0.0)
            prec_p = cp3.number_input("Precio Neto", min_value=0.0)
            if cp4.button("➕ Añadir"):
                if p_sel:
                    st.session_state['carrito'].append({
                        'id': int(p_sel.split(" - ")[0]), 'nombre': p_sel.split(" - ")[1],
                        'cantidad': cant_p, 'precio': prec_p, 'total': cant_p * prec_p
                    })

            if st.session_state['carrito']:
                df_car = pd.DataFrame(st.session_state['carrito'])
                st.table(df_car[['nombre', 'cantidad', 'precio', 'total']])
                
                neto = df_car['total'].sum()
                iva = neto * 0.19
                total_final = st.number_input("Total Final (Neto + IVA + Otros)", value=neto+iva)
                
                bod = st.selectbox("Bodega Destino", ["Central", "Insumos", "Petróleo"])
                cc = st.text_input("Centro de Costo")
                
                if st.button("💾 GUARDAR FACTURA COMPLETA"):
                    conn = conectar_db(); cursor = conn.cursor()
                    cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_neto, monto_total) VALUES (?,?,?,?,?,?)",
                                   (nro, prov, f_c, f_v, neto, total_final))
                    id_fact = cursor.lastrowid
                    for i in st.session_state['carrito']:
                        cursor.execute("INSERT INTO detalle_facturas (factura_id, producto_id, cantidad, precio_neto, total_linea) VALUES (?,?,?,?,?)",
                                       (id_fact, i['id'], i['cantidad'], i['precio'], i['total']))
                        cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, centro_costo, bodega, fecha, factura_id) VALUES (?,?,?,?,?,?,?)",
                                       (i['id'], "Entrada", i['cantidad'], cc, bod, f_c, id_fact))
                        cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (i['cantidad'], i['id']))
                    conn.commit(); conn.close()
                    st.session_state['carrito'] = []
                    st.success("Guardado!"); st.rerun()

    with t2:
        conn = conectar_db()
        st.dataframe(pd.read_sql_query("SELECT * FROM facturas ORDER BY id DESC", conn), use_container_width=True)
        id_b = st.number_input("ID para borrar", min_value=0)
        if st.button("🗑️ Eliminar"):
            eliminar_factura(id_b); st.rerun()
        conn.close()

# --- 3. CUENTAS POR PAGAR (v4.2) ---
elif menu == "💸 Cuentas por Pagar":
    st.header("Tesorería y Pagos")
    col_a, col_b = st.columns(2)
    desde = col_a.date_input("Desde", datetime.now() - timedelta(days=30))
    hasta = col_b.date_input("Hasta", datetime.now() + timedelta(days=90))
    
    conn = conectar_db()
    df_p = pd.read_sql_query(f"SELECT * FROM facturas WHERE fecha_vencimiento BETWEEN '{desde}' AND '{hasta}'", conn)
    st.dataframe(df_p, use_container_width=True)
    
    pendientes = df_p[df_p['estado']=='Pendiente']
    if not pendientes.empty:
        id_pago = st.selectbox("Factura a Pagar ID", pendientes['id'])
        if st.button("💰 Registrar Pago"):
            cursor = conn.cursor()
            cursor.execute("UPDATE facturas SET estado='Pagado' WHERE id=?", (id_pago,))
            conn.commit(); st.success("Pagado!"); st.rerun()
    conn.close()

# --- 4. INVENTARIO (v4.2) ---
elif menu == "🚜 Inventario":
    st.header("Control de Bodega")
    tab1, tab2, tab3 = st.tabs(["📊 Stock Actual", "🔄 Mov. Manual", "➕ Nuevo Producto"])
    
    with tab1:
        conn = conectar_db()
        st.dataframe(pd.read_sql_query("SELECT * FROM inventario", conn), use_container_width=True)
        conn.close()
    
    with tab2:
        with st.form("mov"):
            conn = conectar_db()
            prods = pd.read_sql_query("SELECT id, producto FROM inventario", conn)
            p_sel = st.selectbox("Producto", prods['id'].astype(str) + " - " + prods['producto'])
            tipo = st.radio("Tipo", ["Entrada", "Salida"])
            cant = st.number_input("Cantidad", min_value=0.0)
            if st.form_submit_button("Ejecutar"):
                id_p = int(p_sel.split(" - ")[0])
                cursor = conn.cursor()
                cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha) VALUES (?,?,?,?)", (id_p, tipo, cant, datetime.now().date()))
                aj = cant if tipo=="Entrada" else -cant
                cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (aj, id_p))
                conn.commit(); st.success("Hecho!"); st.rerun()
            conn.close()

    with tab3:
        with st.form("crear"):
            nom = st.text_input("Nombre")
            fam = st.selectbox("Familia", ["Fertilizantes", "Petróleo", "Semillas", "Repuestos"])
            if st.form_submit_button("Crear"):
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO inventario (producto, familia) VALUES (?,?)", (nom, fam))
                conn.commit(); conn.close(); st.rerun()
