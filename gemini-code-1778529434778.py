import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta

# --- CONFIGURACIÓN DE BASE DE DATOS ---
def conectar_db():
    return sqlite3.connect('agricola_erp.db')

def inicializar_db():
    conn = conectar_db(); cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS facturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nro_documento TEXT, proveedor TEXT, 
        fecha_compra DATE, fecha_vencimiento DATE, monto_neto REAL, monto_total REAL, estado TEXT DEFAULT 'Pendiente')''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS detalle_facturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, factura_id INTEGER, producto_id INTEGER, 
        cantidad REAL, precio_neto REAL, FOREIGN KEY(factura_id) REFERENCES facturas(id))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS inventario (
        id INTEGER PRIMARY KEY AUTOINCREMENT, producto TEXT, familia TEXT, stock REAL DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS movimientos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, producto_id INTEGER, tipo TEXT, 
        cantidad REAL, centro_costo TEXT, bodega TEXT, fecha DATE, factura_id INTEGER,
        FOREIGN KEY(producto_id) REFERENCES inventario(id))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS pagos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, factura_id INTEGER, monto_pagado REAL, 
        fecha_pago DATE, metodo_pago TEXT, FOREIGN KEY(factura_id) REFERENCES facturas(id))''')
    conn.commit(); conn.close()

# --- LÓGICA DE ELIMINACIÓN ---
def eliminar_factura(id_factura):
    conn = conectar_db(); cursor = conn.cursor()
    # Revertir stock antes de borrar movimientos
    movs = cursor.execute("SELECT producto_id, cantidad, tipo FROM movimientos WHERE factura_id=?", (id_factura,)).fetchall()
    for p_id, cant, tipo in movs:
        ajuste = -cant if tipo == "Entrada" else cant
        cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (ajuste, p_id))
    # Borrar registros
    cursor.execute("DELETE FROM movimientos WHERE factura_id=?", (id_factura,))
    cursor.execute("DELETE FROM detalle_facturas WHERE factura_id=?", (id_factura,))
    cursor.execute("DELETE FROM facturas WHERE id=?", (id_factura,))
    conn.commit(); conn.close()

# --- INTERFAZ ---
st.set_page_config(page_title="AGRICOLA ERP Pro", layout="wide")
inicializar_db()

st.sidebar.title("🚜 AGRICOLA ERP v3.0")
menu = st.sidebar.radio("Navegación", ["🏠 Dashboard", "📦 Compras", "💸 Cuentas por Pagar", "🚜 Inventario"])

# --- MODULO 0: DASHBOARD ---
if menu == "🏠 Dashboard":
    st.header("Resumen General del Campo")
    conn = conectar_db()
    
    col1, col2, col3 = st.columns(3)
    # Metricas de Cuentas por Pagar
    pendientes = pd.read_sql_query("SELECT SUM(monto_total) as total FROM facturas WHERE estado='Pendiente'", conn)['total'][0] or 0
    col1.metric("Deuda Pendiente", f"${pendientes:,.0f}", delta_color="inverse")
    
    # Metricas de Inventario
    stock_total = pd.read_sql_query("SELECT SUM(stock) as total FROM inventario", conn)['total'][0] or 0
    col2.metric("Items en Stock", f"{stock_total:,.0f} unidades")
    
    # Vencimientos próximos (7 días)
    fecha_limite = (datetime.now() + timedelta(days=7)).date()
    vencimientos = pd.read_sql_query(f"SELECT COUNT(*) as cuenta FROM facturas WHERE fecha_vencimiento <= '{fecha_limite}' AND estado='Pendiente'", conn)['cuenta'][0]
    col3.metric("Facturas por Vencer (7d)", f"{vencimientos}")

    st.subheader("Últimos Movimientos de Bodega")
    movs_recientes = pd.read_sql_query("SELECT m.fecha, i.producto, m.tipo, m.cantidad, m.bodega FROM movimientos m JOIN inventario i ON m.producto_id = i.id ORDER BY m.id DESC LIMIT 5", conn)
    st.table(movs_recientes)
    conn.close()

# --- MODULO 1: COMPRAS ---
elif menu == "📦 Compras":
    st.header("Gestión de Compras e IVA")
    
    with st.expander("➕ Nueva Factura"):
        with st.form("form_compra"):
            c1, c2, c3 = st.columns(3)
            nro = c1.text_input("N° Factura")
            prov = c1.text_input("Proveedor")
            f_c = c2.date_input("Fecha Compra")
            f_v = c2.date_input("Fecha Vencimiento")
            neto = c3.number_input("Valor Neto ($)", min_value=0.0)
            iva = neto * 0.19
            total_sugerido = neto + iva
            total_final = c3.number_input("Total Factura (Editables p/Combustible)", value=total_sugerido)
            
            st.divider()
            conn = conectar_db()
            prods = pd.read_sql_query("SELECT id, producto FROM inventario", conn)
            prod_sel = st.selectbox("Producto para Stock", prods['id'].astype(str) + " - " + prods['producto']) if not prods.empty else None
            cant = st.number_input("Cantidad que ingresa", min_value=0.0)
            bodega = st.selectbox("Bodega", ["Central", "Insumos", "Maquinaria"])
            cc = st.text_input("Centro de Costo")
            
            if st.form_submit_button("Guardar Factura"):
                cursor = conn.cursor()
                cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_neto, monto_total) VALUES (?,?,?,?,?,?)", 
                               (nro, prov, f_c, f_v, neto, total_final))
                id_f = cursor.lastrowid
                if prod_sel:
                    id_p = int(prod_sel.split(" - ")[0])
                    cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, centro_costo, bodega, fecha, factura_id) VALUES (?,?,?,?,?,?,?)", 
                                   (id_p, "Entrada", cant, cc, bodega, f_c, id_f))
                    cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (cant, id_p))
                conn.commit(); st.success("Guardado"); st.rerun()
            conn.close()

    st.subheader("Listado de Facturas")
    conn = conectar_db()
    df_f = pd.read_sql_query("SELECT * FROM facturas", conn)
    st.dataframe(df_f, use_container_width=True)
    
    eliminar_id = st.number_input("ID de factura para eliminar", min_value=0, step=1)
    if st.button("❌ Eliminar Factura Seleccionada"):
        eliminar_factura(eliminar_id)
        st.warning(f"Factura {eliminar_id} eliminada y stock revertido."); st.rerun()
    conn.close()

# --- MODULO 2: CUENTAS POR PAGAR ---
elif menu == "💸 Cuentas por Pagar":
    st.header("Cuentas por Pagar")
    conn = conectar_db()
    
    st.subheader("Filtros")
    f1, f2, f3 = st.columns(3)
    desde = f1.date_input("Desde", datetime.now() - timedelta(days=30))
    hasta = f2.date_input("Hasta", datetime.now() + timedelta(days=30))
    prov_filtro = f3.text_input("Proveedor")
    
    query = f"SELECT * FROM facturas WHERE fecha_vencimiento BETWEEN '{desde}' AND '{hasta}'"
    if prov_filtro: query += f" AND proveedor LIKE '%{prov_filtro}%'"
    
    df_p = pd.read_sql_query(query, conn)
    st.dataframe(df_p, use_container_width=True)
    
    if not df_p.empty:
        sel_p = st.selectbox("Pagar Factura ID", df_p['id'])
        metodo = st.selectbox("Método", ["Transferencia", "Cheque", "Efectivo"])
        if st.button("Registrar Pago"):
            cursor = conn.cursor()
            cursor.execute("UPDATE facturas SET estado='Pagado' WHERE id=?", (sel_p,))
            conn.commit(); st.success("Pagado"); st.rerun()
    conn.close()

# --- MODULO 3: INVENTARIO ---
elif menu == "🚜 Inventario":
    st.header("Bodega y Movimientos Manuales")
    t1, t2 = st.tabs(["Stock Actual", "Movimiento Manual (Entrada/Salida)"])
    
    with t1:
        conn = conectar_db()
        st.dataframe(pd.read_sql_query("SELECT * FROM inventario", conn), use_container_width=True)
        conn.close()
        
    with t2:
        with st.form("mov_manual"):
            conn = conectar_db()
            prods = pd.read_sql_query("SELECT id, producto FROM inventario", conn)
            p_sel = st.selectbox("Producto", prods['id'].astype(str) + " - " + prods['producto'])
            tipo_m = st.radio("Tipo de Movimiento", ["Entrada", "Salida"])
            cant_m = st.number_input("Cantidad", min_value=0.0)
            cc_m = st.text_input("Centro de Costo")
            bod_m = st.selectbox("Bodega", ["Central", "Insumos", "Maquinaria"])
            if st.form_submit_button("Ejecutar Movimiento"):
                id_p = int(p_sel.split(" - ")[0])
                cursor = conn.cursor()
                cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, centro_costo, bodega, fecha) VALUES (?,?,?,?,?,?)", 
                               (id_p, tipo_m, cant_m, cc_m, bod_m, datetime.now().date()))
                ajuste = cant_m if tipo_m == "Entrada" else -cant_m
                cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (ajuste, id_p))
                conn.commit(); st.success("Movimiento registrado"); st.rerun()
            conn.close()
