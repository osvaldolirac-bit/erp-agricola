import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import os

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="AGRICOLA LA CONCEPCION ERP",
    page_icon="🚜",
    layout="wide"
)

# --- CONFIGURACIÓN DE BASE DE DATOS ---
def conectar_db():
    return sqlite3.connect('agricola_erp.db')

def inicializar_db():
    conn = conectar_db(); cursor = conn.cursor()
    # Facturas
    cursor.execute('''CREATE TABLE IF NOT EXISTS facturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nro_documento TEXT, proveedor TEXT, 
        fecha_compra DATE, fecha_vencimiento DATE, monto_neto REAL, monto_total REAL, estado TEXT DEFAULT 'Pendiente')''')
    # Inventario
    cursor.execute('''CREATE TABLE IF NOT EXISTS inventario (
        id INTEGER PRIMARY KEY AUTOINCREMENT, producto TEXT, familia TEXT, stock REAL DEFAULT 0)''')
    # Movimientos
    cursor.execute('''CREATE TABLE IF NOT EXISTS movimientos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, producto_id INTEGER, tipo TEXT, 
        cantidad REAL, centro_costo TEXT, bodega TEXT, fecha DATE, factura_id INTEGER,
        FOREIGN KEY(producto_id) REFERENCES inventario(id))''')
    # Pagos
    cursor.execute('''CREATE TABLE IF NOT EXISTS pagos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, factura_id INTEGER, monto_pagado REAL, 
        fecha_pago DATE, metodo_pago TEXT, FOREIGN KEY(factura_id) REFERENCES facturas(id))''')
    conn.commit(); conn.close()

# --- FUNCIONES DE APOYO ---
def eliminar_factura(id_factura):
    conn = conectar_db(); cursor = conn.cursor()
    movs = cursor.execute("SELECT producto_id, cantidad, tipo FROM movimientos WHERE factura_id=?", (id_factura,)).fetchall()
    for p_id, cant, tipo in movs:
        ajuste = -cant if tipo == "Entrada" else cant
        cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (ajuste, p_id))
    cursor.execute("DELETE FROM movimientos WHERE factura_id=?", (id_factura,))
    cursor.execute("DELETE FROM facturas WHERE id=?", (id_factura,))
    conn.commit(); conn.close()

# --- INICIO ---
inicializar_db()

# --- SIDEBAR (LOGO Y NOMBRE) ---
with st.sidebar:
    # Intentar cargar logo, si no, usar emoji
    if os.path.exists("logo.png"):
        st.image("logo.png", use_container_width=True)
    else:
        st.title("🚜")
    
    st.title("AGRICOLA LA CONCEPCION")
    st.markdown("---")
    menu = st.radio("Módulos", ["🏠 Dashboard", "📦 Compras", "💸 Cuentas por Pagar", "🚜 Inventario"])
    
    st.markdown("---")
    # BOTÓN DE RESPALDO (Punto 4)
    if os.path.exists('agricola_erp.db'):
        with open('agricola_erp.db', 'rb') as f:
            st.download_button(
                label="💾 Descargar Respaldo DB",
                data=f,
                file_name=f"respaldo_agricola_{datetime.now().strftime('%Y%m%d')}.db",
                mime="application/x-sqlite3"
            )

# --- MÓDULOS ---

# 1. DASHBOARD ATRACTIVO (Punto 2)
if menu == "🏠 Dashboard":
    st.header("📊 Resumen Operativo - La Concepción")
    conn = conectar_db()
    
    # Métricas en cajas atractivas
    col1, col2, col3, col4 = st.columns(4)
    
    df_facturas = pd.read_sql_query("SELECT monto_total, estado, fecha_vencimiento FROM facturas", conn)
    deuda_total = df_facturas[df_facturas['estado'] == 'Pendiente']['monto_total'].sum()
    
    col1.metric("Deuda Pendiente", f"${deuda_total:,.0f}", delta_color="inverse")
    
    stock_bajo = pd.read_sql_query("SELECT COUNT(*) as c FROM inventario WHERE stock < 5", conn)['c'][0]
    col2.metric("Alertas Stock Bajo", f"{stock_bajo}", delta="- Crítico" if stock_bajo > 0 else "")
    
    hoy = datetime.now().date()
    vencen_hoy = df_facturas[(df_facturas['estado'] == 'Pendiente') & (pd.to_datetime(df_facturas['fecha_vencimiento']).dt.date <= hoy)].shape[0]
    col3.metric("Vencen Hoy/Atrasadas", f"{vencen_hoy}", delta="Urgente" if vencen_hoy > 0 else "")

    total_items = pd.read_sql_query("SELECT SUM(stock) as s FROM inventario", conn)['s'][0] or 0
    col4.metric("Total Productos", f"{total_items:,.1f}")

    st.markdown("---")
    c1, c2 = st.columns(2)
    
    with c1:
        st.subheader("📦 Compras por Mes")
        # Gráfico simple de barras
        df_mes = pd.read_sql_query("SELECT strftime('%m', fecha_compra) as mes, SUM(monto_total) as total FROM facturas GROUP BY mes", conn)
        if not df_mes.empty:
            st.bar_chart(df_mes.set_index('mes'))
        else:
            st.info("Sin datos para gráficos")
            
    with c2:
        st.subheader("📑 Últimas Facturas")
        st.dataframe(pd.read_sql_query("SELECT nro_documento, proveedor, monto_total FROM facturas ORDER BY id DESC LIMIT 5", conn), use_container_width=True)
    
    conn.close()

# 2. COMPRAS (IVA Y ELIMINACIÓN)
elif menu == "📦 Compras":
    st.header("Gestión de Facturas")
    t1, t2 = st.tabs(["Ingresar Factura", "Historial y Borrado"])
    
    with t1:
        with st.form("form_compras"):
            c1, c2 = st.columns(2)
            nro = c1.text_input("N° Documento")
            prov = c1.text_input("Proveedor")
            f_c = c1.date_input("Fecha Compra")
            f_v = c1.date_input("Fecha Vencimiento")
            
            neto = c2.number_input("Valor Neto ($)", min_value=0.0)
            iva = neto * 0.19
            total_calc = neto + iva
            # Permitir modificar total para combustibles
            total_final = c2.number_input("Total Factura (Neto + IVA + Imp. Esp.)", value=total_calc)
            
            conn = conectar_db()
            prods = pd.read_sql_query("SELECT id, producto FROM inventario", conn)
            p_sel = st.selectbox("Producto para Bodega", prods['id'].astype(str) + " - " + prods['producto']) if not prods.empty else None
            cant = c2.number_input("Cantidad", min_value=0.0)
            bodega = st.selectbox("Bodega", ["Central", "Insumos", "Petróleo"])
            cc = st.text_input("Centro de Costo")
            
            if st.form_submit_button("✅ Guardar Factura"):
                cursor = conn.cursor()
                cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_neto, monto_total) VALUES (?,?,?,?,?,?)", 
                               (nro, prov, f_c, f_v, neto, total_final))
                id_f = cursor.lastrowid
                if p_sel:
                    id_p = int(p_sel.split(" - ")[0])
                    cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, centro_costo, bodega, fecha, factura_id) VALUES (?,?,?,?,?,?,?)", 
                                   (id_p, "Entrada", cant, cc, bodega, f_c, id_f))
                    cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (cant, id_p))
                conn.commit(); st.success("Registrada con éxito"); st.rerun()
            conn.close()

    with t2:
        conn = conectar_db()
        df_historial = pd.read_sql_query("SELECT * FROM facturas", conn)
        st.dataframe(df_historial, use_container_width=True)
        id_borrar = st.number_input("ID Factura para ELIMINAR", min_value=0, step=1)
        if st.button("🗑️ Eliminar Factura"):
            eliminar_factura(id_borrar)
            st.warning("Factura eliminada y stock actualizado"); st.rerun()
        conn.close()

# 3. CUENTAS POR PAGAR (CONSULTAS RANGO FECHAS)
elif menu == "💸 Cuentas por Pagar":
    st.header("Tesorería y Pagos")
    col_a, col_b, col_c = st.columns(3)
    desde = col_a.date_input("Fecha Inicio", datetime.now() - timedelta(days=30))
    hasta = col_b.date_input("Fecha Fin", datetime.now() + timedelta(days=30))
    prov_f = col_c.text_input("Buscar Proveedor")
    
    conn = conectar_db()
    query = f"SELECT * FROM facturas WHERE fecha_vencimiento BETWEEN '{desde}' AND '{hasta}'"
    if prov_f: query += f" AND proveedor LIKE '%{prov_f}%'"
    
    df_p = pd.read_sql_query(query, conn)
    st.dataframe(df_p, use_container_width=True)
    
    if not df_p.empty:
        id_pago = st.selectbox("Seleccionar Factura para Pagar", df_p[df_p['estado']=='Pendiente']['id'])
        metodo = st.selectbox("Método de Pago", ["Transferencia", "Cheque", "Efectivo"])
        if st.button("💰 Registrar Pago"):
            cursor = conn.cursor()
            cursor.execute("UPDATE facturas SET estado='Pagado' WHERE id=?", (id_pago,))
            conn.commit(); st.success("Pago registrado"); st.rerun()
    conn.close()

# 4. INVENTARIO (MOVIMIENTOS MANUALES)
elif menu == "🚜 Inventario":
    st.header("Control de Existencias")
    t1, t2, t3 = st.tabs(["Stock", "Movimiento Manual", "Crear Producto"])
    
    with t3:
        with st.form("nuevo_p"):
            nom = st.text_input("Nombre Producto")
            fam = st.selectbox("Familia", ["Fertilizantes", "Combustibles", "Semillas", "Repuestos"])
            if st.form_submit_button("Crear"):
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO inventario (producto, familia) VALUES (?,?)", (nom, fam))
                conn.commit(); conn.close(); st.rerun()

    with t1:
        conn = conectar_db()
        st.dataframe(pd.read_sql_query("SELECT * FROM inventario", conn), use_container_width=True)
        conn.close()
        
    with t2:
        with st.form("mov_manual"):
            conn = conectar_db()
            prods = pd.read_sql_query("SELECT id, producto FROM inventario", conn)
            p_sel = st.selectbox("Producto", prods['id'].astype(str) + " - " + prods['producto'])
            tipo = st.radio("Tipo", ["Entrada", "Salida"])
            cant = st.number_input("Cantidad", min_value=0.0)
            cc = st.text_input("Centro de Costo")
            bod = st.selectbox("Bodega", ["Central", "Insumos", "Petróleo"])
            if st.form_submit_button("Ejecutar"):
                id_p = int(p_sel.split(" - ")[0])
                cursor = conn.cursor()
                cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, centro_costo, bodega, fecha) VALUES (?,?,?,?,?,?)", 
                               (id_p, tipo, cant, cc, bod, datetime.now().date()))
                ajuste = cant if tipo == "Entrada" else -cant
                cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (ajuste, id_p))
                conn.commit(); conn.close(); st.success("Hecho"); st.rerun()
