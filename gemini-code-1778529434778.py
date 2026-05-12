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
def agricola_erp_v2.db():
    return sqlite3.connect('agricola_erp.db')

def inicializar_db():
    conn = conectar_db(); cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS facturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nro_documento TEXT, proveedor TEXT, 
        fecha_compra DATE, fecha_vencimiento DATE, monto_neto REAL, monto_total REAL, estado TEXT DEFAULT 'Pendiente')''')
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

# --- SIDEBAR ---
with st.sidebar:
    if os.path.exists("logo.png"):
        st.image("logo.png", use_container_width=True)
    else:
        st.title("🚜")
    
    st.title("AGRICOLA LA CONCEPCION")
    st.markdown("---")
    menu = st.radio("Módulos", ["🏠 Dashboard", "📦 Compras", "💸 Cuentas por Pagar", "🚜 Inventario"])
    
    st.markdown("---")
    if os.path.exists('agricola_erp.db'):
        with open('agricola_erp.db', 'rb') as f:
            st.download_button(
                label="💾 Descargar Respaldo DB",
                data=f,
                file_name=f"respaldo_agricola_{datetime.now().strftime('%Y%m%d')}.db",
                mime="application/x-sqlite3"
            )

# --- MÓDULOS ---

# 1. DASHBOARD ACTUALIZADO CON VENCIMIENTOS A 3 MESES
if menu == "🏠 Dashboard":
    st.header("📊 Dashboard de Control Financiero")
    conn = conectar_db()
    
    # Métricas Principales
    col1, col2, col3, col4 = st.columns(4)
    
    df_facturas = pd.read_sql_query("SELECT monto_total, estado, fecha_vencimiento FROM facturas", conn)
    df_facturas['fecha_vencimiento'] = pd.to_datetime(df_facturas['fecha_vencimiento'])
    
    deuda_total = df_facturas[df_facturas['estado'] == 'Pendiente']['monto_total'].sum()
    col1.metric("Deuda Total Pendiente", f"${deuda_total:,.0f}")
    
    stock_total = pd.read_sql_query("SELECT SUM(stock) as s FROM inventario", conn)['s'][0] or 0
    col2.metric("Stock en Bodegas", f"{stock_total:,.1f}")
    
    hoy = datetime.now().date()
    vencidas = df_facturas[(df_facturas['estado'] == 'Pendiente') & (df_facturas['fecha_vencimiento'].dt.date < hoy)].shape[0]
    col3.metric("Facturas Vencidas", f"{vencidas}", delta="Urgente" if vencidas > 0 else "", delta_color="inverse")

    proximo_pago = df_facturas[(df_facturas['estado'] == 'Pendiente') & (df_facturas['fecha_vencimiento'].dt.date >= hoy)].sort_values(by='fecha_vencimiento').head(1)
    if not proximo_pago.empty:
        col4.metric("Próximo Vencimiento", proximo_pago['fecha_vencimiento'].dt.strftime('%d/%m/%y').values[0])
    else:
        col4.metric("Próximo Vencimiento", "N/A")

    st.markdown("---")
    
    # SECCIÓN: PROYECCIÓN DE VENCIMIENTOS (90 DÍAS)
    st.subheader("📅 Proyección de Vencimientos (Próximos 3 Meses)")
    
    # Lógica para agrupar por mes los próximos vencimientos
    pendientes_df = df_facturas[df_facturas['estado'] == 'Pendiente'].copy()
    
    if not pendientes_df.empty:
        # Extraer Mes y Año para agrupar
        pendientes_df['Mes'] = pendientes_df['fecha_vencimiento'].dt.strftime('%B %Y')
        # Traducción manual simple para meses (opcional)
        meses_traduccion = {
            'January': 'Enero', 'February': 'Febrero', 'March': 'Marzo', 'April': 'Abril',
            'May': 'Mayo', 'June': 'Junio', 'July': 'Julio', 'August': 'Agosto',
            'September': 'Septiembre', 'October': 'Octubre', 'November': 'Noviembre', 'December': 'Diciembre'
        }
        for eng, esp in meses_traduccion.items():
            pendientes_df['Mes'] = pendientes_df['Mes'].str.replace(eng, esp)

        proyeccion_mensual = pendientes_df.groupby('Mes')['monto_total'].sum().reset_index()
        
        c_graf, c_tabla = st.columns([2, 1])
        with c_graf:
            st.bar_chart(proyeccion_mensual.set_index('Mes'))
        with c_tabla:
            st.write("Resumen de montos por mes:")
            st.table(proyeccion_mensual.style.format({"monto_total": "${:,.0f}"}))
    else:
        st.info("No hay facturas pendientes de pago para proyectar.")

    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("📈 Compras Recientes (Histórico)")
        df_hist = pd.read_sql_query("SELECT strftime('%m-%Y', fecha_compra) as periodo, SUM(monto_total) as total FROM facturas GROUP BY periodo ORDER BY id DESC LIMIT 6", conn)
        if not df_hist.empty:
            st.line_chart(df_hist.set_index('periodo'))
    with c2:
        st.subheader("⚠️ Alertas de Stock Bajo")
        df_bajo = pd.read_sql_query("SELECT producto, stock FROM inventario WHERE stock < 10", conn)
        if not df_bajo.empty:
            st.dataframe(df_bajo, use_container_width=True)
        else:
            st.success("Stock en niveles óptimos")
    
    conn.close()

# 2. COMPRAS (RESTO DE MÓDULOS SE MANTIENEN IGUAL)
elif menu == "📦 Compras":
    st.header("Ingreso de Facturas y Documentos")
    t1, t2 = st.tabs(["Nueva Factura", "Historial / Eliminar"])
    
    with t1:
        with st.form("form_compras"):
            c1, c2 = st.columns(2)
            nro = c1.text_input("N° Documento")
            prov = c1.text_input("Proveedor")
            f_c = c1.date_input("Fecha Compra", datetime.now())
            f_v = c1.date_input("Fecha Vencimiento", datetime.now() + timedelta(days=30))
            
            neto = c2.number_input("Valor Neto ($)", min_value=0.0)
            total_final = c2.number_input("Total Factura (Incluye IVA/Impuestos)", value=neto * 1.19)
            
            conn = conectar_db()
            prods = pd.read_sql_query("SELECT id, producto FROM inventario", conn)
            p_sel = st.selectbox("Asignar Stock a Producto", prods['id'].astype(str) + " - " + prods['producto']) if not prods.empty else None
            cant = c2.number_input("Cantidad Recibida", min_value=0.0)
            bodega = st.selectbox("Bodega Destino", ["Central", "Insumos", "Petróleo"])
            cc = st.text_input("Centro de Costo")
            
            if st.form_submit_button("💾 Guardar y Procesar"):
                cursor = conn.cursor()
                cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_neto, monto_total) VALUES (?,?,?,?,?,?)", 
                               (nro, prov, f_c, f_v, neto, total_final))
                id_f = cursor.lastrowid
                if p_sel:
                    id_p = int(p_sel.split(" - ")[0])
                    cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, centro_costo, bodega, fecha, factura_id) VALUES (?,?,?,?,?,?,?)", 
                                   (id_p, "Entrada", cant, cc, bodega, f_c, id_f))
                    cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (cant, id_p))
                conn.commit(); st.success("Documento registrado!"); st.rerun()
            conn.close()

    with t2:
        conn = conectar_db()
        st.dataframe(pd.read_sql_query("SELECT * FROM facturas ORDER BY id DESC", conn), use_container_width=True)
        id_b = st.number_input("ID Factura para ELIMINAR", min_value=0, step=1)
        if st.button("🗑️ Eliminar Definitivamente"):
            eliminar_factura(id_b)
            st.warning("Registro eliminado y stock revertido."); st.rerun()
        conn.close()

# 3. CUENTAS POR PAGAR (MODULO ACTUALIZADO)
elif menu == "💸 Cuentas por Pagar":
    st.header("Control de Pagos y Tesorería")
    st.info("Filtra por fecha de vencimiento o proveedor para gestionar tus deudas.")
    
    col_a, col_b, col_c = st.columns(3)
    desde = col_a.date_input("Vence Desde", datetime.now() - timedelta(days=30))
    hasta = col_b.date_input("Vence Hasta", datetime.now() + timedelta(days=90))
    prov_f = col_c.text_input("Filtrar por Proveedor")
    
    conn = conectar_db()
    query = f"SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total, estado FROM facturas WHERE fecha_vencimiento BETWEEN '{desde}' AND '{hasta}'"
    if prov_f: query += f" AND proveedor LIKE '%{prov_f}%'"
    
    df_p = pd.read_sql_query(query, conn)
    st.dataframe(df_p, use_container_width=True)
    
    pendientes_pago = df_p[df_p['estado']=='Pendiente']
    if not pendientes_pago.empty:
        st.divider()
        id_pago = st.selectbox("Seleccionar Factura para Pagar", pendientes_pago['id'])
        metodo = st.selectbox("Método de Pago", ["Transferencia", "Cheque", "Efectivo", "Vale Vista"])
        if st.button("💰 Confirmar Pago"):
            cursor = conn.cursor()
            cursor.execute("UPDATE facturas SET estado='Pagado' WHERE id=?", (id_pago,))
            conn.commit(); st.success("¡Pago registrado con éxito!"); st.rerun()
    conn.close()

# 4. INVENTARIO (SIN CAMBIOS SIGNIFICATIVOS)
elif menu == "🚜 Inventario":
    st.header("Existencias y Movimientos de Bodega")
    t1, t2, t3 = st.tabs(["📊 Stock Real", "🔄 Movimiento Manual", "➕ Nuevo Item"])
    
    with t3:
        with st.form("nuevo_p"):
            nom = st.text_input("Nombre del Insumo/Producto")
            fam = st.selectbox("Familia", ["Fertilizantes", "Combustibles", "Semillas", "Agroquímicos", "Maquinaria"])
            if st.form_submit_button("Crear Maestro"):
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO inventario (producto, familia) VALUES (?,?)", (nom, fam))
                conn.commit(); conn.close(); st.success("Producto creado!"); st.rerun()

    with t1:
        conn = conectar_db()
        st.dataframe(pd.read_sql_query("SELECT * FROM inventario", conn), use_container_width=True)
        conn.close()
        
    with t2:
        with st.form("mov_manual"):
            conn = conectar_db()
            prods = pd.read_sql_query("SELECT id, producto FROM inventario", conn)
            p_sel = st.selectbox("Producto", prods['id'].astype(str) + " - " + prods['producto'])
            tipo = st.radio("Operación", ["Entrada", "Salida"])
            cant = st.number_input("Cantidad", min_value=0.0)
            bod = st.selectbox("Bodega", ["Central", "Insumos", "Petróleo"])
            cc = st.text_input("Centro de Costo / Cuartel")
            if st.form_submit_button("Ejecutar Operación"):
                id_p = int(p_sel.split(" - ")[0])
                cursor = conn.cursor()
                cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, centro_costo, bodega, fecha) VALUES (?,?,?,?,?,?)", 
                               (id_p, tipo, cant, cc, bod, datetime.now().date()))
                ajuste = cant if tipo == "Entrada" else -cant
                cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (ajuste, id_p))
                conn.commit(); conn.close(); st.success("Movimiento procesado!"); st.rerun()
