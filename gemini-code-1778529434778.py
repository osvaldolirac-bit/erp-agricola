import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import os

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="AGRICOLA LA CONCEPCION ERP", page_icon="🚜", layout="wide")

# --- SEGURIDAD ---
CLAVE_SEGURIDAD = "2908"
DB_NAME = 'erp_concepcion_v6.db'

# --- DIAGNÓSTICO DE BASE DE DATOS ---
if not os.path.exists(DB_NAME):
    st.warning(f"⚠️ No se encontró el archivo '{DB_NAME}'. El sistema iniciará una base de datos nueva (vacía).")
else:
    st.sidebar.success(f"✔️ Base de Datos '{DB_NAME}' detectada.")

# --- CONEXIÓN A BASE DE DATOS ---
def conectar_db():
    return sqlite3.connect(DB_NAME)

def inicializar_db():
    conn = conectar_db(); cursor = conn.cursor()
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
    
    # Migración: Asegurar columnas de pago
    cursor.execute("PRAGMA table_info(facturas)")
    columnas = [info[1] for info in cursor.fetchall()]
    if 'metodo_pago' not in columnas: cursor.execute("ALTER TABLE facturas ADD COLUMN metodo_pago TEXT")
    if 'fecha_pago' not in columnas: cursor.execute("ALTER TABLE facturas ADD COLUMN fecha_pago DATE")
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
    if os.path.exists(DB_NAME):
        with open(DB_NAME, 'rb') as f:
            st.download_button("💾 Descargar Respaldo DB", f, DB_NAME, "application/x-sqlite3")
    if st.button("🗑️ Limpiar Carrito"):
        st.session_state['carrito'] = []
        st.rerun()

# --- 1. DASHBOARD ---
if menu == "🏠 Dashboard":
    st.header("📊 Resumen de Compromisos")
    conn = conectar_db()
    df_f = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente'", conn)
    conn.close()
    
    col1, col2 = st.columns(2)
    total_deuda = df_f['monto_total'].sum() if not df_f.empty else 0
    col1.metric("Deuda Total Pendiente", f"${total_deuda:,.0f}")
    
    hoy = datetime.now().date()
    vencidas = 0
    if not df_f.empty:
        df_f['fecha_vencimiento'] = pd.to_datetime(df_f['fecha_vencimiento']).dt.date
        vencidas = df_f[df_f['fecha_vencimiento'] < hoy].shape[0]
    col2.metric("Vencimientos Atrasados", vencidas, delta_color="inverse")
    
    st.markdown("---")
    st.subheader("📅 Pagos Próximos 4 Meses")
    fecha_actual = datetime.now()
    cols_meses = st.columns(4)
    for i in range(4):
        m = (fecha_actual.month + i - 1) % 12 + 1
        a = fecha_actual.year + (fecha_actual.month + i - 1) // 12
        monto_mes = 0
        if not df_f.empty:
            df_f['fecha_vencimiento'] = pd.to_datetime(df_f['fecha_vencimiento'])
            monto_mes = df_f[(df_f['fecha_vencimiento'].dt.month == m) & (df_f['fecha_vencimiento'].dt.year == a)]['monto_total'].sum()
        with cols_meses[i]:
            st.markdown(f"### {obtener_nombre_mes(m)}")
            st.markdown(f"<h2 style='color: #2E7D32;'>${monto_mes:,.0f}</h2>", unsafe_allow_html=True)

# --- 2. COMPRAS ---
elif menu == "📦 Compras":
    st.header("Gestión de Adquisiciones")
    t1, t2, t3 = st.tabs(["➕ Factura Insumos", "💸 Gasto Vario", "🔍 Historial y Eliminación"])
    
    with t1:
        c1, c2 = st.columns(2)
        nro = c1.text_input("N° Factura")
        prov = c1.text_input("Proveedor")
        f_c = c2.date_input("Fecha Compra", datetime.now())
        f_v = c2.date_input("Fecha Vencimiento", datetime.now() + timedelta(days=30))
        conn = conectar_db()
        df_inv = pd.read_sql_query("SELECT id, producto FROM inventario ORDER BY producto", conn)
        conn.close()
        
        st.markdown("---")
        if df_inv.empty:
            st.info("ℹ️ No hay productos creados. Ve a 'Inventario' para registrar productos primero.")
        else:
            cp1, cp2, cp3, cp4 = st.columns([3,1,1,1])
            p_sel = cp1.selectbox("Seleccione Producto", df_inv['id'].astype(str) + " - " + df_inv['producto'])
            cant = cp2.number_input("Cantidad", min_value=0.0)
            prec = cp3.number_input("Precio Neto", min_value=0.0)
            if cp4.button("➕ Añadir"):
                if cant > 0:
                    st.session_state['carrito'].append({'id': int(p_sel.split(" - ")[0]), 'nombre': p_sel.split(" - ")[1], 'cantidad': cant, 'precio': prec, 'total': cant * prec})
                    st.rerun()

        if st.session_state['carrito']:
            st.table(pd.DataFrame(st.session_state['carrito'])[['nombre', 'cantidad', 'precio', 'total']])
            neto_t = sum(i['total'] for i in st.session_state['carrito'])
            total_f = st.number_input("Total Final (IVA incl.)", value=neto_t * 1.19)
            bod = st.selectbox("Bodega", ["Central", "Insumos", "Petróleo"])
            if st.button("💾 GUARDAR FACTURA COMPLETA"):
                if nro and prov:
                    conn = conectar_db(); cursor = conn.cursor()
                    cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_neto, monto_total, tipo) VALUES (?,?,?,?,?,?,?)", (nro, prov, f_c, f_v, neto_t, total_f, 'Factura'))
                    id_f = cursor.lastrowid
                    for i in st.session_state['carrito']:
                        cursor.execute("INSERT INTO detalle_facturas (factura_id, producto_id, cantidad, precio_neto, total_linea) VALUES (?,?,?,?,?)", (id_f, i['id'], i['cantidad'], i['precio'], i['total']))
                        cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, bodega, fecha, factura_id, centro_costo) VALUES (?,?,?,?,?,?,?)", (i['id'], "Entrada", i['cantidad'], bod, f_c, id_f, "Bodega"))
                        cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (i['cantidad'], i['id']))
                    conn.commit(); conn.close(); st.session_state['carrito'] = []; st.success("¡Factura guardada!"); st.rerun()
                else:
                    st.error("N° Factura y Proveedor son campos obligatorios.")

    with t2:
        with st.form("fg"):
            st.subheader("Registrar Gasto Directo (Servicios, Fletes, etc.)")
            g1, g2 = st.columns(2)
            gd = g1.text_input("N° Documento (Opcional)")
            gp = g1.text_input("Proveedor/Beneficiario")
            gc = g1.text_area("Concepto del Gasto")
            gf = g2.date_input("Fecha Gasto")
            gv = g2.date_input("Fecha Vencimiento Pago", datetime.now() + timedelta(days=7))
            gm = g2.number_input("Monto Total ($)", min_value=0.0)
            if st.form_submit_button("💾 GUARDAR GASTO"):
                if gp and gm > 0:
                    doc = gd if gd else f"G-{datetime.now().strftime('%y%m%d%H%M')}"
                    conn = conectar_db(); cursor = conn.cursor()
                    cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_neto, monto_total, tipo) VALUES (?,?,?,?,?,?,?)", (doc, gp, gf, gv, gm, gm, 'Gasto Vario'))
                    conn.commit(); conn.close(); st.success("Gasto registrado."); st.rerun()

    with t3:
        st.subheader("Consulta de Historial")
        h1, h2, h3, h4 = st.columns(4)
        di = h1.date_input("Fecha Desde", datetime.now() - timedelta(days=90))
        df = h2.date_input("Fecha Hasta", datetime.now())
        tf = h3.selectbox("Filtrar por Tipo", ["Todos", "Factura", "Gasto Vario"])
        ef = h4.selectbox("Filtrar por Estado", ["Todos", "Pendiente", "Pagado"])
        conn = conectar_db()
        query = f"SELECT id, nro_documento, proveedor, fecha_compra, monto_total, estado, tipo, metodo_pago, fecha_pago FROM facturas WHERE fecha_compra BETWEEN '{di}' AND '{df}'"
        if tf != "Todos": query += f" AND tipo='{tf}'"
        if ef != "Todos": query += f" AND estado='{ef}'"
        df_hist = pd.read_sql_query(query, conn)
        st.dataframe(df_hist, use_container_width=True)
        st.markdown("---")
        st.subheader("🗑️ Zona de Seguridad (Eliminar)")
        col_del1, col_del2, col_del3 = st.columns([1, 2, 2])
        id_b = col_del1.number_input("ID de registro", min_value=0, step=1)
        pass_input = col_del2.text_input("Clave de Autorización", type="password")
        if col_del3.button("❌ ELIMINAR REGISTRO"):
            if pass_input == CLAVE_SEGURIDAD:
                if id_b > 0: eliminar_factura(id_b); st.success(f"ID {id_b} eliminado."); st.rerun()
            else: st.error("🔑 Clave incorrecta.")
        conn.close()

# --- 3. CUENTAS POR PAGAR ---
elif menu == "💸 Cuentas por Pagar":
    st.header("Tesorería")
    tp1, tp2, tp3 = st.tabs(["🔴 Pendientes", "🏢 Por Proveedor", "📅 Por Mes"])
    conn = conectar_db()
    df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total, tipo FROM facturas WHERE estado='Pendiente'", conn)
    
    with tp1:
        if not df_p.empty:
            df_p['fecha_vencimiento'] = pd.to_datetime(df_p['fecha_vencimiento'])
            hoy = pd.Timestamp(datetime.now().date())
            def highlight_vencidos(row):
                if row['fecha_vencimiento'] < hoy: return ['background-color: #ffcccc'] * len(row)
                return [''] * len(row)
            st.dataframe(df_p.style.apply(highlight_vencidos, axis=1), use_container_width=True)
            st.divider()
            id_p = st.selectbox("Seleccione ID para Pagar", df_p['id'])
            met = st.selectbox("Método de Pago", ["Transferencia", "Efectivo", "Cheque", "Vale Vista"])
            fec = st.date_input("Fecha en que pagó", datetime.now())
            if st.button("💰 REGISTRAR PAGO"):
                cursor = conn.cursor()
                cursor.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (met, fec, id_p))
                conn.commit(); st.success("¡Pago registrado!"); st.rerun()
        else: st.success("✅ No hay deudas pendientes.")

    with tp2:
        if not df_p.empty:
            deuda_prov = df_p.groupby('proveedor')['monto_total'].sum().reset_index().sort_values(by='monto_total', ascending=False)
            st.table(deuda_prov.style.format({"monto_total": "${:,.0f}"}))
        else: st.info("No hay deudas para resumir.")

    with tp3:
        if not df_p.empty:
            df_p['Mes'] = pd.to_datetime(df_p['fecha_vencimiento']).dt.strftime('%m-%Y')
            deuda_mes = df_p.groupby(['Mes'])['monto_total'].sum().reset_index()
            st.table(deuda_mes.style.format({"monto_total": "${:,.0f}"}))
        else: st.info("No hay deudas para resumir.")
    conn.close()

# --- 4. INVENTARIO ---
elif menu == "🚜 Inventario":
    st.header("Bodega")
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Stock", "🔄 Movimiento", "➕ Nuevo Producto", "🔍 Reporte CC"])
    with tab1:
        conn = conectar_db()
        df_inv_stock = pd.read_sql_query("SELECT * FROM inventario ORDER BY producto", conn)
        st.dataframe(df_inv_stock, use_container_width=True)
        conn.close()
    with tab2:
        with st.form("mm"):
            st.subheader("Entradas / Salidas Manuales")
            conn = conectar_db()
            prods = pd.read_sql_query("SELECT id, producto FROM inventario ORDER BY producto", conn)
            ps = st.selectbox("Producto", prods['id'].astype(str) + " - " + prods['producto']) if not prods.empty else None
            tipo = st.radio("Tipo Movimiento", ["Entrada", "Salida"])
            cant = st.number_input("Cantidad", min_value=0.0)
            cc = st.text_input("Centro de Costo (Ej: Cuartel 1)")
            if st.form_submit_button("EJECUTAR"):
                if ps:
                    id_p = int(ps.split(" - ")[0])
                    cursor = conn.cursor(); cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo, bodega) VALUES (?,?,?,?,?,?)", (id_p, tipo, cant, datetime.now().date(), cc, "Bodega"))
                    aj = cant if tipo == "Entrada" else -cant
                    cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (aj, id_p))
                    conn.commit(); st.success("Stock actualizado."); st.rerun()
            conn.close()
    with tab3:
        with st.form("np"):
            st.subheader("Crear Producto en Maestro")
            n = st.text_input("Nombre (Ej: Urea 46%)")
            f = st.selectbox("Familia", ["Fertilizante", "Herbicida", "Insecticida", "Fungicidas", "Bio estimulante", "Fertilizante foliar", "Petróleo/Combustible", "Otros"])
            if st.form_submit_button("CREAR PRODUCTO"):
                if n:
                    conn = conectar_db(); cursor = conn.cursor()
                    cursor.execute("INSERT INTO inventario (producto, familia) VALUES (?,?)", (n, f))
                    conn.commit(); conn.close(); st.success(f"Producto '{n}' creado."); st.rerun()
    with tab4:
        conn = conectar_db(); ccs = pd.read_sql_query("SELECT DISTINCT centro_costo FROM movimientos WHERE tipo='Salida' AND centro_costo != ''", conn)
        cc_f = st.selectbox("Filtrar Centro de Costo", ["Todos"] + list(ccs['centro_costo']))
        q_cc = "SELECT m.fecha, i.producto, m.cantidad, m.centro_costo FROM movimientos m JOIN inventario i ON m.producto_id = i.id WHERE m.tipo = 'Salida'"
        if cc_f != "Todos": q_cc += f" AND m.centro_costo = '{cc_f}'"
        st.dataframe(pd.read_sql_query(q_cc + " ORDER BY m.fecha DESC", conn), use_container_width=True); conn.close()
