import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import os

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="AGRICOLA LA CONCEPCION ERP", page_icon="🚜", layout="wide")

# --- CONEXIÓN A BASE DE DATOS (NUEVA VERSIÓN v6) ---
def conectar_db():
    # Cambiamos el nombre del archivo para forzar la creación de la estructura correcta
    return sqlite3.connect('erp_concepcion_v6.db')

def inicializar_db():
    conn = conectar_db(); cursor = conn.cursor()
    # Crear tablas con la estructura final desde el inicio
    cursor.execute('''CREATE TABLE IF NOT EXISTS facturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        nro_documento TEXT, 
        proveedor TEXT, 
        fecha_compra DATE, 
        fecha_vencimiento DATE, 
        monto_neto REAL, 
        monto_total REAL, 
        estado TEXT DEFAULT 'Pendiente')''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS detalle_facturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        factura_id INTEGER, 
        producto_id INTEGER, 
        cantidad REAL, 
        precio_neto REAL, 
        total_linea REAL)''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS inventario (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        producto TEXT, 
        familia TEXT, 
        stock REAL DEFAULT 0)''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS movimientos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        producto_id INTEGER, 
        tipo TEXT, 
        cantidad REAL, 
        centro_costo TEXT, 
        bodega TEXT, 
        fecha DATE, 
        factura_id INTEGER)''')
    
    conn.commit(); conn.close()

# --- FUNCIONES DE LÓGICA ---
def eliminar_factura(id_f):
    conn = conectar_db(); cursor = conn.cursor()
    # Revertir stock de todos los productos en la factura
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
    if os.path.exists("logo.png"):
        st.image("logo.png", use_container_width=True)
    else:
        st.title("🚜")
    st.title("AGRICOLA LA CONCEPCION")
    st.markdown("---")
    menu = st.radio("Navegación", ["🏠 Dashboard", "📦 Compras", "💸 Cuentas por Pagar", "🚜 Inventario"])
    st.markdown("---")
    # Botón para limpiar el carrito si hay errores de ingreso
    if st.button("🗑️ Limpiar Formulario Compras"):
        st.session_state['carrito'] = []
        st.rerun()
    # Respaldo
    if os.path.exists('erp_concepcion_v6.db'):
        with open('erp_concepcion_v6.db', 'rb') as f:
            st.download_button("💾 Descargar Respaldo DB", f, "respaldo_erp.db", "application/x-sqlite3")

# --- 1. DASHBOARD (ESTILO v4.2) ---
if menu == "🏠 Dashboard":
    st.header("📊 Resumen Operativo y Financiero")
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
        col3.metric("Facturas Vencidas", vencidas, delta="¡Urgente!" if vencidas > 0 else "", delta_color="inverse")
        
        prox = df_f[(df_f['estado']=='Pendiente') & (df_f['fecha_vencimiento'] >= hoy)].sort_values('fecha_vencimiento').head(1)
        col4.metric("Próximo Pago", prox['fecha_vencimiento'].values[0].strftime('%d/%m') if not prox.empty else "---")

    st.markdown("---")
    
    # Proyección 3 Meses
    st.subheader("📅 Proyección de Pagos (Próximos 3 Meses)")
    if not df_f.empty:
        pend = df_f[df_f['estado']=='Pendiente'].copy()
        pend['Mes'] = pd.to_datetime(pend['fecha_vencimiento']).dt.strftime('%m-%Y')
        proy_mes = pend.groupby('Mes')['monto_total'].sum().reset_index()
        st.bar_chart(proy_mes.set_index('Mes'))
    else:
        st.info("Sin facturas pendientes para proyectar.")
    
    st.subheader("⚠️ Alertas de Stock Bajo")
    df_bajo = pd.read_sql_query("SELECT producto, stock FROM inventario WHERE stock < 10", conn)
    st.dataframe(df_bajo, use_container_width=True)
    conn.close()

# --- 2. COMPRAS (MULTI-PRODUCTO CON DISEÑO v4.2) ---
elif menu == "📦 Compras":
    st.header("Gestión de Compras")
    t1, t2 = st.tabs(["➕ Nueva Factura", "📜 Historial / Eliminar"])
    
    with t1:
        c1, c2 = st.columns(2)
        nro = c1.text_input("Número Factura")
        prov = c1.text_input("Proveedor")
        f_c = c2.date_input("Fecha Compra", datetime.now())
        f_v = c2.date_input("Fecha Vencimiento", datetime.now() + timedelta(days=30))
        
        st.markdown("### 🛒 Detalle de Productos")
        conn = conectar_db()
        df_inv = pd.read_sql_query("SELECT id, producto FROM inventario", conn)
        conn.close()
        
        col_p1, col_p2, col_p3, col_p4 = st.columns([3, 1, 1, 1])
        p_sel = col_p1.selectbox("Producto", df_inv['id'].astype(str) + " - " + df_inv['producto']) if not df_inv.empty else None
        c_p = col_p2.number_input("Cantidad", min_value=0.0, step=0.1)
        pr_p = col_p3.number_input("Precio Neto Unit.", min_value=0.0)
        
        if col_p4.button("➕ Añadir"):
            if p_sel and c_p > 0:
                st.session_state['carrito'].append({
                    'id': int(p_sel.split(" - ")[0]),
                    'nombre': p_sel.split(" - ")[1],
                    'cantidad': c_p,
                    'precio': pr_p,
                    'total': c_p * pr_p
                })
                st.rerun()

        if st.session_state['carrito']:
            df_car = pd.DataFrame(st.session_state['carrito'])
            st.table(df_car[['nombre', 'cantidad', 'precio', 'total']])
            
            neto_t = df_car['total'].sum()
            total_f = st.number_input("Total Final Factura (IVA e Impuestos incluidos)", value=neto_t * 1.19)
            bod = st.selectbox("Bodega Destino", ["Central", "Insumos", "Petróleo"])
            cc = st.text_input("Centro de Costo (Opcional)")
            
            if st.button("💾 GUARDAR FACTURA COMPLETA"):
                if nro and prov:
                    conn = conectar_db(); cursor = conn.cursor()
                    cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_neto, monto_total) VALUES (?,?,?,?,?,?)",
                                   (nro, prov, f_c, f_v, neto_t, total_f))
                    id_fact = cursor.lastrowid
                    for i in st.session_state['carrito']:
                        cursor.execute("INSERT INTO detalle_facturas (factura_id, producto_id, cantidad, precio_neto, total_linea) VALUES (?,?,?,?,?)",
                                       (id_fact, i['id'], i['cantidad'], i['precio'], i['total']))
                        cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, centro_costo, bodega, fecha, factura_id) VALUES (?,?,?,?,?,?,?)",
                                       (i['id'], "Entrada", i['cantidad'], cc, bod, f_c, id_fact))
                        cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (i['cantidad'], i['id']))
                    conn.commit(); conn.close()
                    st.session_state['carrito'] = []
                    st.success("¡Factura guardada y stock actualizado!"); st.rerun()
                else:
                    st.error("Debes ingresar N° de Factura y Proveedor.")

    with t2:
        conn = conectar_db()
        st.dataframe(pd.read_sql_query("SELECT * FROM facturas ORDER BY id DESC", conn), use_container_width=True)
        id_borrar = st.number_input("ID Factura para ELIMINAR", min_value=0, step=1)
        if st.button("🗑️ Eliminar Registro"):
            eliminar_factura(id_borrar)
            st.warning("Factura eliminada y stock revertido."); st.rerun()
        conn.close()

# --- 3. CUENTAS POR PAGAR ---
elif menu == "💸 Cuentas por Pagar":
    st.header("Gestión de Pagos")
    col_f1, col_f2 = st.columns(2)
    desde = col_f1.date_input("Desde", datetime.now() - timedelta(days=30))
    hasta = col_f2.date_input("Hasta", datetime.now() + timedelta(days=90))
    
    conn = conectar_db()
    df_p = pd.read_sql_query(f"SELECT * FROM facturas WHERE fecha_vencimiento BETWEEN '{desde}' AND '{hasta}'", conn)
    st.dataframe(df_p, use_container_width=True)
    
    pendientes = df_p[df_p['estado']=='Pendiente']
    if not pendientes.empty:
        id_pago = st.selectbox("ID Factura a Pagar", pendientes['id'])
        if st.button("💰 Confirmar Pago"):
            cursor = conn.cursor()
            cursor.execute("UPDATE facturas SET estado='Pagado' WHERE id=?", (id_pago,))
            conn.commit(); st.success("¡Pago registrado!"); st.rerun()
    conn.close()

# --- 4. INVENTARIO ---
elif menu == "🚜 Inventario":
    st.header("Control de Existencias")
    tab1, tab2, tab3 = st.tabs(["📊 Stock Actual", "🔄 Mov. Manual", "➕ Crear Producto"])
    
    with tab1:
        conn = conectar_db()
        st.dataframe(pd.read_sql_query("SELECT * FROM inventario", conn), use_container_width=True)
        conn.close()
    
    with tab2:
        with st.form("mov_m"):
            conn = conectar_db()
            df_i = pd.read_sql_query("SELECT id, producto FROM inventario", conn)
            p_sel = st.selectbox("Producto", df_i['id'].astype(str) + " - " + df_i['producto']) if not df_i.empty else None
            tipo = st.radio("Operación", ["Entrada", "Salida"])
            cant = st.number_input("Cantidad", min_value=0.0)
            cc_m = st.text_input("Centro de Costo")
            if st.form_submit_button("Ejecutar"):
                id_p = int(p_sel.split(" - ")[0])
                cursor = conn.cursor()
                cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo) VALUES (?,?,?,?,?)", (id_p, tipo, cant, datetime.now().date(), cc_m))
                ajuste = cant if tipo == "Entrada" else -cant
                cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (ajuste, id_p))
                conn.commit(); conn.close(); st.success("Movimiento registrado"); st.rerun()

    with tab3:
        with st.form("nuevo_item"):
            nom_p = st.text_input("Nombre del Producto")
            fam_p = st.selectbox("Familia", ["Insumos", "Fertilizantes", "Petróleo", "Repuestos", "Semillas"])
            if st.form_submit_button("Crear Producto"):
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO inventario (producto, familia) VALUES (?,?)", (nom_p, fam_p))
                conn.commit(); conn.close(); st.success("Producto creado!"); st.rerun()
