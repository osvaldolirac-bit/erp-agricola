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
    # Estructura base
    cursor.execute('''CREATE TABLE IF NOT EXISTS facturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nro_documento TEXT, proveedor TEXT, 
        fecha_compra DATE, fecha_vencimiento DATE, monto_neto REAL, monto_total REAL, 
        estado TEXT DEFAULT 'Pendiente', tipo TEXT DEFAULT 'Factura',
        metodo_pago TEXT, fecha_pago DATE)''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS detalle_facturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, factura_id INTEGER, producto_id INTEGER, 
        cantidad REAL, precio_neto REAL, total_linea REAL)''')
        
    cursor.execute('''CREATE TABLE IF NOT EXISTS inventario (
        id INTEGER PRIMARY KEY AUTOINCREMENT, producto TEXT, familia TEXT, stock REAL DEFAULT 0)''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS movimientos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, producto_id INTEGER, tipo TEXT, 
        cantidad REAL, centro_costo TEXT, bodega TEXT, fecha DATE, factura_id INTEGER)''')
    
    # MIGRACIÓN: Asegurar columnas
    cursor.execute("PRAGMA table_info(movimientos)")
    columnas_mov = [info[1] for info in cursor.fetchall()]
    if 'centro_costo' not in columnas_mov:
        cursor.execute("ALTER TABLE movimientos ADD COLUMN centro_costo TEXT")
    
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
    
    if os.path.exists('erp_concepcion_v6.db'):
        with open('erp_concepcion_v6.db', 'rb') as f:
            st.download_button("💾 Descargar Respaldo DB", f, "respaldo_agricola.db", "application/x-sqlite3")
    
    if st.button("🗑️ Limpiar Carrito Compras"):
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
        col2.metric("Vencimientos Atrasados", vencidas, delta="¡Urgente!" if vencidas > 0 else "", delta_color="inverse")
    
    st.markdown("---")
    st.subheader("📅 Proyección de Pagos Mensuales")
    
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
            monto_mes = df_f[(df_f['fecha_vencimiento'].dt.month == m) & (df_f['fecha_vencimiento'].dt.year == a)]['monto_total'].sum()
            with cols_meses[idx]:
                st.markdown(f"### {nombre_mes}")
                st.markdown(f"<h2 style='color: #2E7D32;'>${monto_mes:,.0f}</h2>", unsafe_allow_html=True)
    else:
        st.info("No hay pagos pendientes para proyectar.")

# --- 2. COMPRAS ---
elif menu == "📦 Compras":
    st.header("Gestión de Compras y Gastos")
    t1, t2, t3 = st.tabs(["➕ Nueva Factura Insumos", "💸 Gasto Vario / Servicio", "🔍 Consultas e Historial"])
    
    with t1:
        c1, c2 = st.columns(2)
        nro = c1.text_input("N° Factura")
        prov = c1.text_input("Proveedor")
        f_c = c2.date_input("Fecha Compra", datetime.now())
        f_v = c2.date_input("Fecha Vencimiento", datetime.now() + timedelta(days=30))
        
        conn = conectar_db(); df_inv = pd.read_sql_query("SELECT id, producto FROM inventario", conn); conn.close()
        
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
                total_f = st.number_input("Total Final Factura", value=neto_t * 1.19)
                bod = st.selectbox("Bodega", ["Central", "Insumos", "Petróleo"])
                cc_compra = st.text_input("Centro de Costo Destino (Opcional)", "Bodega Central")
                
                if st.button("💾 GUARDAR FACTURA COMPLETA"):
                    conn = conectar_db(); cursor = conn.cursor()
                    cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_neto, monto_total, tipo) VALUES (?,?,?,?,?,?,?)",
                                   (nro, prov, f_c, f_v, neto_t, total_f, 'Factura'))
                    id_fact = cursor.lastrowid
                    for i in st.session_state['carrito']:
                        cursor.execute("INSERT INTO detalle_facturas (factura_id, producto_id, cantidad, precio_neto, total_linea) VALUES (?,?,?,?,?)",
                                       (id_fact, i['id'], i['cantidad'], i['precio'], i['total']))
                        cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, bodega, fecha, factura_id, centro_costo) VALUES (?,?,?,?,?,?,?)",
                                       (i['id'], "Entrada", i['cantidad'], bod, f_c, id_fact, cc_compra))
                        cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (i['cantidad'], i['id']))
                    conn.commit(); conn.close()
                    st.session_state['carrito'] = []
                    st.success("¡Factura guardada!"); st.rerun()

    with t2:
        st.subheader("Gasto Directo / Servicios")
        with st.form("form_gastos"):
            ga1, ga2 = st.columns(2)
            g_doc = ga1.text_input("N° Documento (Opcional)")
            g_prov = ga1.text_input("Proveedor o Persona")
            g_desc = ga1.text_area("Concepto")
            g_fecha = ga2.date_input("Fecha Gasto")
            g_vence = ga2.date_input("Vencimiento del Pago", datetime.now() + timedelta(days=7))
            g_monto = ga2.number_input("Monto Total ($)", min_value=0.0)
            
            if st.form_submit_button("💾 REGISTRAR GASTO"):
                if g_prov and g_monto > 0:
                    doc = g_doc if g_doc else f"G-{datetime.now().strftime('%y%m%d%H%M')}"
                    conn = conectar_db(); cursor = conn.cursor()
                    cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_neto, monto_total, tipo) VALUES (?,?,?,?,?,?,?)",
                                   (doc, g_prov, g_fecha, g_vence, g_monto, g_monto, 'Gasto Vario'))
                    conn.commit(); conn.close(); st.success("Gasto registrado"); st.rerun()

    with t3:
        st.subheader("Consultas Históricas")
        f1, f2, f3, f4 = st.columns(4)
        d_i = f1.date_input("Desde", datetime.now() - timedelta(days=90))
        d_f = f2.date_input("Hasta", datetime.now())
        t_f = f3.selectbox("Tipo", ["Todos", "Factura", "Gasto Vario"])
        e_f = f4.selectbox("Estado", ["Todos", "Pendiente", "Pagado"])
        
        conn = conectar_db()
        query = f"SELECT id, nro_documento, proveedor, fecha_compra, monto_total, estado, tipo, metodo_pago, fecha_pago FROM facturas WHERE fecha_compra BETWEEN '{d_i}' AND '{d_f}'"
        if t_f != "Todos": query += f" AND tipo='{t_f}'"
        if e_f != "Todos": query += f" AND estado='{e_f}'"
        
        df_hist = pd.read_sql_query(query, conn)
        st.dataframe(df_hist, use_container_width=True)
        conn.close()

# --- 3. CUENTAS POR PAGAR ---
elif menu == "💸 Cuentas por Pagar":
    st.header("Tesorería: Deudas Pendientes")
    conn = conectar_db()
    df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total, tipo FROM facturas WHERE estado='Pendiente'", conn)
    
    if not df_p.empty:
        st.dataframe(df_p, use_container_width=True)
        st.divider()
        st.subheader("Registrar Pago")
        id_pago = st.selectbox("Factura/Gasto a Pagar", df_p['id'])
        metodo = st.selectbox("Forma de Pago", ["Transferencia", "Efectivo", "Cheque", "Vale Vista", "Tarjeta"])
        f_pago = st.date_input("Fecha de Pago", datetime.now())
        
        if st.button("💰 Confirmar Pago"):
            cursor = conn.cursor()
            cursor.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (metodo, f_pago, id_pago))
            conn.commit(); st.success(f"¡Pago registrado!"); st.rerun()
    else:
        st.success("✅ No hay deudas pendientes.")
    conn.close()

# --- 4. INVENTARIO (ACTUALIZADO CON CENTRO DE COSTO Y REPORTES) ---
elif menu == "🚜 Inventario":
    st.header("Control de Inventario y Aplicaciones")
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Stock", "🔄 Movimiento Manual", "➕ Nuevo Producto", "🔍 Reporte por CC"])
    
    with tab1:
        conn = conectar_db(); st.dataframe(pd.read_sql_query("SELECT * FROM inventario", conn), use_container_width=True); conn.close()
    
    with tab2:
        st.subheader("Entradas o Salidas (Afecta Stock)")
        with st.form("mov_m"):
            conn = conectar_db(); prods = pd.read_sql_query("SELECT id, producto FROM inventario", conn)
            p_s = st.selectbox("Producto", prods['id'].astype(str) + " - " + prods['producto']) if not prods.empty else None
            tipo_m = st.radio("Tipo", ["Entrada", "Salida"])
            cant_m = st.number_input("Cantidad", min_value=0.0)
            cc_m = st.text_input("Centro de Costo (ej. Cuartel A, Tractor 3, etc.)")
            bod_m = st.selectbox("Bodega", ["Central", "Insumos", "Petróleo"])
            if st.form_submit_button("Ejecutar Movimiento"):
                if p_s:
                    id_p = int(p_s.split(" - ")[0])
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo, bodega) VALUES (?,?,?,?,?,?)", 
                                   (id_p, tipo_m, cant_m, datetime.now().date(), cc_m, bod_m))
                    ajuste = cant_m if tipo_m == "Entrada" else -cant_m
                    cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (ajuste, id_p))
                    conn.commit(); st.success("Movimiento registrado con éxito"); st.rerun()
            conn.close()

    with tab3:
        with st.form("crear"):
            n = st.text_input("Nombre Insumo")
            f = st.selectbox("Familia", ["Insumos", "Petróleo", "Fertilizantes", "Semillas"])
            if st.form_submit_button("Crear"):
                conn = conectar_db(); cursor = conn.cursor(); cursor.execute("INSERT INTO inventario (producto, familia) VALUES (?,?)", (n, f))
                conn.commit(); conn.close(); st.success("Producto creado!"); st.rerun()

    with tab4:
        st.subheader("Consulta de Aplicaciones y Salidas por Centro de Costo")
        conn = conectar_db()
        # Obtener lista de Centros de Costo únicos para filtrar
        ccs = pd.read_sql_query("SELECT DISTINCT centro_costo FROM movimientos WHERE tipo='Salida' AND centro_costo IS NOT NULL AND centro_costo != ''", conn)
        
        col_f1, col_f2 = st.columns(2)
        cc_filtro = col_f1.selectbox("Seleccionar Centro de Costo", ["Todos"] + list(ccs['centro_costo']))
        
        query_cc = """
            SELECT m.fecha, i.producto, m.cantidad, m.centro_costo, m.bodega 
            FROM movimientos m 
            JOIN inventario i ON m.producto_id = i.id 
            WHERE m.tipo = 'Salida'
        """
        if cc_filtro != "Todos":
            query_cc += f" AND m.centro_costo = '{cc_filtro}'"
        
        df_cc = pd.read_sql_query(query_cc, conn)
        st.dataframe(df_cc, use_container_width=True)
        
        if not df_cc.empty:
            st.markdown(f"**Total acumulado de salidas para este filtro:** {df_cc['cantidad'].sum():,.1f} unidades")
        conn.close()
