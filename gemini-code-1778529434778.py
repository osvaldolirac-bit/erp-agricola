import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import os

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="AGRICOLA LA CONCEPCION ERP", page_icon="🚜", layout="wide")

# --- CONEXIÓN Y MIGRACIÓN AUTOMÁTICA ---
def conectar_db():
    return sqlite3.connect('agricola_erp.db')

def inicializar_db():
    conn = conectar_db(); cursor = conn.cursor()
    # Tablas Base
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
    
    # MIGRACIÓN: Verificar si faltan columnas de versiones anteriores
    cursor.execute("PRAGMA table_info(facturas)")
    columnas = [info[1] for info in cursor.fetchall()]
    if 'nro_documento' not in columnas:
        cursor.execute("ALTER TABLE facturas ADD COLUMN nro_documento TEXT")
    if 'monto_neto' not in columnas:
        cursor.execute("ALTER TABLE facturas ADD COLUMN monto_neto REAL")
    
    conn.commit(); conn.close()

# --- FUNCIONES DE LÓGICA ---
def eliminar_factura(id_f):
    conn = conectar_db(); cursor = conn.cursor()
    movs = cursor.execute("SELECT producto_id, cantidad FROM movimientos WHERE factura_id=?", (id_f,)).fetchall()
    for p_id, cant in movs:
        cursor.execute("UPDATE inventario SET stock = stock - ? WHERE id = ?", (cant, p_id))
    cursor.execute("DELETE FROM movimientos WHERE factura_id=?", (id_f,))
    cursor.execute("DELETE FROM detalle_facturas WHERE factura_id=?", (id_f,))
    cursor.execute("DELETE FROM facturas WHERE id=?", (id_f,))
    conn.commit(); conn.close()

# --- INICIALIZAR ---
inicializar_db()

# --- SESSION STATE PARA MULTI-PRODUCTO ---
if 'items_factura' not in st.session_state:
    st.session_state['items_factura'] = []

# --- SIDEBAR ---
with st.sidebar:
    st.title("AGRICOLA LA CONCEPCION")
    menu = st.radio("Menú", ["🏠 Dashboard", "📦 Compras (Multi-Producto)", "💸 Cuentas por Pagar", "🚜 Inventario"])
    st.markdown("---")
    if st.button("🗑️ Limpiar Sesión (Reset)"):
        st.session_state['items_factura'] = []
        st.rerun()

# --- MODULOS ---

if menu == "🏠 Dashboard":
    st.header("📊 Control Financiero a 90 Días")
    conn = conectar_db()
    df_f = pd.read_sql_query("SELECT * FROM facturas", conn)
    conn.close()

    if not df_f.empty:
        df_f['fecha_vencimiento'] = pd.to_datetime(df_f['fecha_vencimiento'])
        # Mostrar vencimientos próximos 3 meses
        st.subheader("📅 Proyección de Pagos (Próximos Meses)")
        df_f['Mes'] = df_f['fecha_vencimiento'].dt.strftime('%Y-%m')
        proyeccion = df_f[df_f['estado']=='Pendiente'].groupby('Mes')['monto_total'].sum()
        st.bar_chart(proyeccion)
    else:
        st.info("Ingresa facturas para ver el Dashboard.")

elif menu == "📦 Compras (Multi-Producto)":
    st.header("Ingreso de Factura con Múltiples Productos")
    
    col_cab1, col_cab2 = st.columns(2)
    with col_cab1:
        nro_doc = st.text_input("Número de Factura")
        prov = st.text_input("Proveedor")
    with col_cab2:
        f_compra = st.date_input("Fecha Compra", datetime.now())
        f_vence = st.date_input("Fecha Vencimiento", datetime.now() + timedelta(days=30))

    st.divider()
    st.subheader("Añadir Productos a la Factura")
    
    conn = conectar_db()
    df_inv = pd.read_sql_query("SELECT id, producto FROM inventario", conn)
    conn.close()

    if not df_inv.empty:
        col_p1, col_p2, col_p3 = st.columns([3, 1, 1])
        prod_sel = col_p1.selectbox("Producto", df_inv['id'].astype(str) + " - " + df_inv['producto'])
        cant = col_p2.number_input("Cantidad", min_value=0.0, step=1.0)
        precio = col_p3.number_input("Precio Neto Unitario", min_value=0.0)
        
        if st.button("➕ Añadir Producto a la Lista"):
            id_p = int(prod_sel.split(" - ")[0])
            nom_p = prod_sel.split(" - ")[1]
            st.session_state['items_factura'].append({
                'id': id_p, 'nombre': nom_p, 'cantidad': cant, 'precio': precio, 'total': cant * precio
            })
    else:
        st.warning("Crea productos en el módulo de Inventario primero.")

    # Mostrar tabla temporal
    if st.session_state['items_factura']:
        st.markdown("### Detalle Actual")
        df_temp = pd.DataFrame(st.session_state['items_factura'])
        st.table(df_temp)
        
        neto_total = df_temp['total'].sum()
        iva_total = neto_total * 0.19
        total_f = neto_total + iva_total
        
        st.write(f"**Neto:** ${neto_total:,.0f} | **IVA (19%):** ${iva_total:,.0f}")
        total_final_input = st.number_input("Total Final (Ajustable por combustibles)", value=total_f)

        if st.button("💾 GUARDAR FACTURA COMPLETA"):
            if nro_doc and prov:
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_neto, monto_total) VALUES (?,?,?,?,?,?)",
                               (nro_doc, prov, f_compra, f_vence, neto_total, total_final_input))
                id_factura = cursor.lastrowid
                
                for item in st.session_state['items_factura']:
                    cursor.execute("INSERT INTO detalle_facturas (factura_id, producto_id, cantidad, precio_neto, total_linea) VALUES (?,?,?,?,?)",
                                   (id_factura, item['id'], item['cantidad'], item['precio'], item['total']))
                    cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, factura_id, bodega) VALUES (?,?,?,?,?,?)",
                                   (item['id'], 'Entrada', item['cantidad'], f_compra, id_factura, 'Central'))
                    cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (item['cantidad'], item['id']))
                
                conn.commit(); conn.close()
                st.session_state['items_factura'] = []
                st.success("Factura y stock guardados correctamente.")
                st.rerun()
            else:
                st.error("Faltan datos de la cabecera (N° o Proveedor)")

elif menu == "💸 Cuentas por Pagar":
    st.header("Cuentas por Pagar")
    conn = conectar_db()
    df_p = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente'", conn)
    st.dataframe(df_p, use_container_width=True)
    
    if not df_p.empty:
        id_p = st.selectbox("Seleccionar ID para Pagar", df_p['id'])
        if st.button("Marcar como Pagado"):
            cursor = conn.cursor()
            cursor.execute("UPDATE facturas SET estado='Pagado' WHERE id=?", (id_p,))
            conn.commit(); st.success("Pagado"); st.rerun()
    conn.close()

elif menu == "🚜 Inventario":
    st.header("Maestro de Productos")
    with st.form("nuevo_p"):
        n = st.text_input("Nombre Producto")
        f = st.text_input("Familia")
        if st.form_submit_button("Crear"):
            conn = conectar_db(); cursor = conn.cursor()
            cursor.execute("INSERT INTO inventario (producto, familia) VALUES (?,?)", (n, f))
            conn.commit(); conn.close(); st.rerun()
    
    conn = conectar_db()
    st.dataframe(pd.read_sql_query("SELECT * FROM inventario", conn), use_container_width=True)
    conn.close()
