import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime

# --- CONFIGURACIÓN DE BASE DE DATOS ---
def conectar_db():
    return sqlite3.connect('agricola_erp.db')

def inicializar_db():
    conn = conectar_db()
    cursor = conn.cursor()
    # Módulo de Compras
    cursor.execute('''CREATE TABLE IF NOT EXISTS facturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        proveedor TEXT, fecha_compra DATE, fecha_vencimiento DATE, monto REAL, estado TEXT DEFAULT 'Pendiente')''')
    # Módulo de Cuentas por Pagar
    cursor.execute('''CREATE TABLE IF NOT EXISTS pagos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        factura_id INTEGER, monto_pagado REAL, fecha_pago DATE, metodo_pago TEXT,
        FOREIGN KEY(factura_id) REFERENCES facturas(id))''')
    # Módulo de Inventario
    cursor.execute('''CREATE TABLE IF NOT EXISTS inventario (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        producto TEXT, familia TEXT, stock REAL DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS movimientos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        producto_id INTEGER, tipo TEXT, cantidad REAL, centro_costo TEXT, fecha DATE,
        FOREIGN KEY(producto_id) REFERENCES inventario(id))''')
    conn.commit()
    conn.close()

# --- INTERFAZ ---
st.set_page_config(page_title="AGRICOLA ERP", layout="wide")
inicializar_db()

st.sidebar.title("🚜 AGRICOLA ERP")
menu = st.sidebar.radio("Seleccione Módulo", ["Compras", "Cuentas por Pagar", "Inventario"])

# --- MÓDULO 1: COMPRAS ---
if menu == "Compras":
    st.header("📦 Gestión de Compras")
    with st.expander("➕ Registrar Nueva Factura"):
        with st.form("form_factura"):
            prov = st.text_input("Proveedor")
            monto = st.number_input("Monto", min_value=0.0)
            f_c = st.date_input("Fecha Compra", datetime.now())
            f_v = st.date_input("Fecha Vencimiento", datetime.now())
            if st.form_submit_button("Guardar"):
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO facturas (proveedor, fecha_compra, fecha_vencimiento, monto) VALUES (?,?,?,?)", (prov, f_c, f_v, monto))
                conn.commit(); conn.close(); st.success("Registrada")

    st.subheader("🔍 Consultas de Facturas")
    conn = conectar_db()
    df = pd.read_sql_query("SELECT * FROM facturas", conn)
    conn.close()
    st.dataframe(df, use_container_width=True)

# --- MÓDULO 2: CUENTAS POR PAGAR ---
elif menu == "Cuentas por Pagar":
    st.header("💸 Cuentas por Pagar")
    conn = conectar_db()
    pendientes = pd.read_sql_query("SELECT id, proveedor, monto, estado FROM facturas WHERE estado='Pendiente'", conn)
    
    if not pendientes.empty:
        factura_sel = st.selectbox("Seleccione Factura para Pagar", pendientes['id'].astype(str) + " - " + pendientes['proveedor'])
        id_fac = factura_sel.split(" - ")[0]
        metodo = st.selectbox("Método de Pago", ["Transferencia", "Cheque", "Efectivo", "Crédito"])
        monto_pago = st.number_input("Monto a Pagar", min_value=0.0)
        
        if st.button("Registrar Pago"):
            cursor = conn.cursor()
            cursor.execute("INSERT INTO pagos (factura_id, monto_pagado, fecha_pago, metodo_pago) VALUES (?,?,?,?)", (id_fac, monto_pago, datetime.now().date(), metodo))
            cursor.execute("UPDATE facturas SET estado='Pagado' WHERE id=?", (id_fac,))
            conn.commit(); st.success("Pago realizado"); st.rerun()
    else:
        st.info("No hay facturas pendientes.")
    
    st.subheader("📜 Historial de Pagos")
    df_pagos = pd.read_sql_query("SELECT * FROM pagos", conn)
    st.dataframe(df_pagos, use_container_width=True)
    conn.close()

# --- MÓDULO 3: INVENTARIO ---
elif menu == "Inventario":
    st.header("🚜 Inventario y Centros de Costo")
    tab1, tab2 = st.tabs(["Productos", "Movimientos"])
    
    with tab1:
        with st.form("nuevo_prod"):
            nombre = st.text_input("Nombre Producto")
            fam = st.selectbox("Familia", ["Semillas", "Fertilizantes", "Pesticidas", "Repuestos"])
            if st.form_submit_button("Crear"):
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO inventario (producto, familia) VALUES (?,?)", (nombre, fam))
                conn.commit(); conn.close()
        
        conn = conectar_db()
        st.dataframe(pd.read_sql_query("SELECT * FROM inventario", conn), use_container_width=True)
        conn.close()

    with tab2:
        conn = conectar_db()
        prods = pd.read_sql_query("SELECT id, producto FROM inventario", conn)
        prod_sel = st.selectbox("Producto", prods['id'].astype(str) + " - " + prods['producto'])
        tipo = st.radio("Tipo", ["Entrada", "Salida"])
        cant = st.number_input("Cantidad", min_value=0.1)
        cc = st.text_input("Centro de Costo (ej. Cuartel A)")
        
        if st.button("Registrar Movimiento"):
            id_p = prod_sel.split(" - ")[0]
            cursor = conn.cursor()
            cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, centro_costo, fecha) VALUES (?,?,?,?,?)", (id_p, tipo, cant, cc, datetime.now().date()))
            # Actualizar Stock
            ajuste = cant if tipo == "Entrada" else -cant
            cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (ajuste, id_p))
            conn.commit(); st.success("Movimiento guardado")
        
        st.subheader("📊 Historial por Centro de Costo")
        st.dataframe(pd.read_sql_query("SELECT * FROM movimientos", conn), use_container_width=True)
        conn.close()