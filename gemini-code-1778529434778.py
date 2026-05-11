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
    # Facturas (ahora con nro_documento)
    cursor.execute('''CREATE TABLE IF NOT EXISTS facturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nro_documento TEXT, proveedor TEXT, fecha_compra DATE, 
        fecha_vencimiento DATE, monto_total REAL, estado TEXT DEFAULT 'Pendiente')''')
    
    # Detalle de Facturas (para productos, cantidades y precios)
    cursor.execute('''CREATE TABLE IF NOT EXISTS detalle_facturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        factura_id INTEGER, producto_id INTEGER, cantidad REAL, precio_neto REAL,
        FOREIGN KEY(factura_id) REFERENCES facturas(id))''')
    
    # Inventario
    cursor.execute('''CREATE TABLE IF NOT EXISTS inventario (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        producto TEXT, familia TEXT, stock REAL DEFAULT 0)''')
    
    # Movimientos (añadida BODEGA)
    cursor.execute('''CREATE TABLE IF NOT EXISTS movimientos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        producto_id INTEGER, tipo TEXT, cantidad REAL, centro_costo TEXT, 
        bodega TEXT, fecha DATE, factura_id INTEGER,
        FOREIGN KEY(producto_id) REFERENCES inventario(id))''')
    
    conn.commit()
    conn.close()

# --- INTERFAZ ---
st.set_page_config(page_title="AGRICOLA ERP v2", layout="wide")
inicializar_db()

st.sidebar.title("🚜 AGRICOLA ERP v2.0")
menu = st.sidebar.radio("Menú Principal", ["📦 Compras (Facturación)", "💸 Cuentas por Pagar", "🚜 Inventario y Bodega"])

# --- MÓDULO 1: COMPRAS (FACTURACIÓN DETALLADA) ---
if menu == "📦 Compras (Facturación)":
    st.header("Ingreso de Facturas de Compra")
    
    with st.expander("➕ Registrar Nueva Factura Detallada", expanded=True):
        with st.form("form_factura_completa"):
            col1, col2, col3 = st.columns(3)
            with col1:
                nro_doc = st.text_input("N° Documento / Factura")
                prov = st.text_input("Proveedor")
            with col2:
                f_c = st.date_input("Fecha Compra", datetime.now())
                f_v = st.date_input("Fecha Vencimiento", datetime.now())
            with col3:
                bodega_destino = st.selectbox("Asignar a Bodega", ["Bodega Central", "Bodega Insumos", "Bodega Maquinaria"])
                centro_costo = st.text_input("Centro de Costo (ej: Cuartel 1)")

            st.divider()
            st.subheader("Detalle de Productos")
            
            # Cargar productos existentes para el selector
            conn = conectar_db()
            prods_df = pd.read_sql_query("SELECT id, producto FROM inventario", conn)
            conn.close()
            
            # Formulario simplificado para 1 producto (puedes repetir esto o usar una lista)
            if not prods_df.empty:
                prod_sel = st.selectbox("Seleccionar Producto", prods_df['id'].astype(str) + " - " + prods_df['producto'])
            else:
                st.warning("⚠️ Primero crea productos en el módulo de Inventario")
                prod_sel = None
                
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                cant_compra = st.number_input("Cantidad", min_value=0.0, step=0.1)
            with col_d2:
                precio_neto = st.number_input("Precio Unitario Neto ($)", min_value=0.0)
            
            total_calculado = cant_compra * precio_neto
            st.info(f"Total Neto de esta línea: ${total_calculado:,.2f}")

            if st.form_submit_button("💾 GUARDAR FACTURA E INGRESAR A BODEGA"):
                if nro_doc and prov and prod_sel:
                    id_prod = int(prod_sel.split(" - ")[0])
                    conn = conectar_db(); cursor = conn.cursor()
                    
                    # 1. Guardar Cabecera de Factura
                    cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total) VALUES (?,?,?,?,?)", 
                                   (nro_doc, prov, f_c, f_v, total_calculado))
                    id_factura = cursor.lastrowid
                    
                    # 2. Guardar Detalle
                    cursor.execute("INSERT INTO detalle_facturas (factura_id, producto_id, cantidad, precio_neto) VALUES (?,?,?,?)",
                                   (id_factura, id_prod, cant_compra, precio_neto))
                    
                    # 3. Generar Movimiento de Inventario (Entrada a Bodega)
                    cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, centro_costo, bodega, fecha, factura_id) VALUES (?,?,?,?,?,?,?)",
                                   (id_prod, "Entrada", cant_compra, centro_costo, bodega_destino, f_c, id_factura))
                    
                    # 4. Actualizar Stock Real
                    cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (cant_compra, id_prod))
                    
                    conn.commit(); conn.close()
                    st.success(f"Factura {nro_doc} registrada y stock actualizado en {bodega_destino}")
                else:
                    st.error("Faltan datos obligatorios")

    st.subheader("🔍 Consultas de Facturas")
    conn = conectar_db()
    df_f = pd.read_sql_query("SELECT * FROM facturas", conn)
    st.dataframe(df_f, use_container_width=True)
    conn.close()

# --- MÓDULO 2: CUENTAS POR PAGAR (SIN CAMBIOS) ---
elif menu == "💸 Cuentas por Pagar":
    st.header("Gestión de Pagos")
    conn = conectar_db()
    pendientes = pd.read_sql_query("SELECT id, nro_documento, proveedor, monto_total, estado FROM facturas WHERE estado='Pendiente'", conn)
    
    if not pendientes.empty:
        fac_display = st.selectbox("Factura a Pagar", pendientes['id'].astype(str) + " | Doc: " + pendientes['nro_documento'] + " | " + pendientes['proveedor'])
        id_fac = fac_display.split(" | ")[0]
        metodo = st.selectbox("Método", ["Transferencia", "Cheque", "Efectivo"])
        if st.button("Confirmar Pago"):
            cursor = conn.cursor()
            cursor.execute("UPDATE facturas SET estado='Pagado' WHERE id=?", (id_fac,))
            cursor.execute("INSERT INTO pagos (factura_id, monto_pagado, fecha_pago, metodo_pago) VALUES (?,?,?,?)", 
                           (id_fac, 0, datetime.now().date(), metodo)) # Monto 0 simplificado
            conn.commit(); st.success("Pagado"); st.rerun()
    else:
        st.info("No hay deudas pendientes.")
    conn.close()

# --- MÓDULO 3: INVENTARIO Y BODEGA ---
elif menu == "🚜 Inventario y Bodega":
    st.header("Control de Stock y Bodegas")
    t1, t2 = st.tabs(["Maestro de Productos", "Movimientos y Bodegas"])
    
    with t1:
        with st.form("nuevo_p"):
            n = st.text_input("Nombre Producto (ej: Urea)")
            f = st.selectbox("Familia", ["Fertilizantes", "Semillas", "Químicos", "Repuestos"])
            if st.form_submit_button("Crear Producto"):
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO inventario (producto, familia) VALUES (?,?)", (n, f))
                conn.commit(); conn.close(); st.success("Creado")
        
        conn = conectar_db()
        st.dataframe(pd.read_sql_query("SELECT * FROM inventario", conn), use_container_width=True)
        conn.close()

    with t2:
        st.subheader("Historial de Entradas y Salidas")
        conn = conectar_db()
        # Query avanzada para ver nombres de productos y bodegas
        query = '''
            SELECT m.fecha, i.producto, m.tipo, m.cantidad, m.bodega, m.centro_costo, f.nro_documento as factura
            FROM movimientos m
            JOIN inventario i ON m.producto_id = i.id
            LEFT JOIN facturas f ON m.factura_id = f.id
        '''
        df_m = pd.read_sql_query(query, conn)
        st.dataframe(df_m, use_container_width=True)
        conn.close()
