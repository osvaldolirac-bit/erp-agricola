import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import os

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="AGRICOLA LA CONCEPCION ERP", page_icon="🚜", layout="wide")

# --- SEGURIDAD ---
CLAVE_SEGURIDAD = "2908"

# --- CONEXIÓN A BASE DE DATOS ---
def conectar_db():
    return sqlite3.connect('erp_concepcion_v6.db')

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
    total_deuda = df_f['monto_total'].sum()
    col1.metric("Deuda Total Pendiente", f"${total_deuda:,.0f}")
    hoy = datetime.now().date()
    if not df_f.empty:
        df_f['fecha_vencimiento'] = pd.to_datetime(df_f['fecha_vencimiento']).dt.date
        vencidas = df_f[df_f['fecha_vencimiento'] < hoy].shape[0]
        col2.metric("Vencimientos Atrasados", vencidas, delta_color="inverse")
    st.markdown("---")
    st.subheader("📅 Pagos Próximos 4 Meses")
    fecha_actual = datetime.now()
    cols_meses = st.columns(4)
    if not df_f.empty:
        df_f['fecha_vencimiento'] = pd.to_datetime(df_f['fecha_vencimiento'])
        for i in range(4):
            m = (fecha_actual.month + i - 1) % 12 + 1
            a = fecha_actual.year + (fecha_actual.month + i - 1) // 12
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
        if not df_inv.empty:
            cp1, cp2, cp3, cp4 = st.columns([3,1,1,1])
            p_sel = cp1.selectbox("Producto", df_inv['id'].astype(str) + " - " + df_inv['producto'])
            cant = cp2.number_input("Cant.", min_value=0.0)
            prec = cp3.number_input("Neto Unit.", min_value=0.0)
            if cp4.button("➕"):
                if cant > 0:
                    st.session_state['carrito'].append({'id': int(p_sel.split(" - ")[0]), 'nombre': p_sel.split(" - ")[1], 'cantidad': cant, 'precio': prec, 'total': cant * prec})
                    st.rerun()
            if st.session_state['carrito']:
                st.table(pd.DataFrame(st.session_state['carrito'])[['nombre', 'cantidad', 'precio', 'total']])
                neto_t = sum(i['total'] for i in st.session_state['carrito'])
                total_f = st.number_input("Total Final Factura", value=neto_t * 1.19)
                bod = st.selectbox("Bodega", ["Central", "Insumos", "Petróleo"])
                if st.button("💾 GUARDAR FACTURA"):
                    conn = conectar_db(); cursor = conn.cursor()
                    cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_neto, monto_total, tipo) VALUES (?,?,?,?,?,?,?)", (nro, prov, f_c, f_v, neto_t, total_f, 'Factura'))
                    id_f = cursor.lastrowid
                    for i in st.session_state['carrito']:
                        cursor.execute("INSERT INTO detalle_facturas (factura_id, producto_id, cantidad, precio_neto, total_linea) VALUES (?,?,?,?,?)", (id_f, i['id'], i['cantidad'], i['precio'], i['total']))
                        cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, bodega, fecha, factura_id, centro_costo) VALUES (?,?,?,?,?,?,?)", (i['id'], "Entrada", i['cantidad'], bod, f_c, id_f, "Bodega"))
                        cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (i['cantidad'], i['id']))
                    conn.commit(); conn.close(); st.session_state['carrito'] = []; st.success("Guardado"); st.rerun()

    with t2:
        with st.form("fg"):
            g1, g2 = st.columns(2)
            gd = g1.text_input("N° Doc (Opcional)")
            gp = g1.text_input("Proveedor")
            gc = g1.text_area("Concepto")
            gf = g2.date_input("Fecha")
            gv = g2.date_input("Vencimiento", datetime.now() + timedelta(days=7))
            gm = g2.number_input("Monto", min_value=0.0)
            if st.form_submit_button("💾 REGISTRAR GASTO"):
                doc = gd if gd else f"G-{datetime.now().strftime('%y%m%d%H%M')}"
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_neto, monto_total, tipo) VALUES (?,?,?,?,?,?,?)", (doc, gp, gf, gv, gm, gm, 'Gasto Vario'))
                conn.commit(); conn.close(); st.success("Registrado"); st.rerun()

    with t3:
        st.subheader("Historial y Gestión de Registros")
        h1, h2, h3, h4 = st.columns(4)
        di = h1.date_input("Desde", datetime.now() - timedelta(days=90))
        df = h2.date_input("Hasta", datetime.now())
        tf = h3.selectbox("Tipo", ["Todos", "Factura", "Gasto Vario"])
        ef = h4.selectbox("Estado", ["Todos", "Pendiente", "Pagado"])
        conn = conectar_db()
        q = f"SELECT id, nro_documento, proveedor, fecha_compra, monto_total, estado, tipo, metodo_pago, fecha_pago FROM facturas WHERE fecha_compra BETWEEN '{di}' AND '{df}'"
        if tf != "Todos": q += f" AND tipo='{tf}'"
        if ef != "Todos": q += f" AND estado='{ef}'"
        st.dataframe(pd.read_sql_query(q, conn), use_container_width=True)
        st.markdown("---")
        
        # --- ELIMINACIÓN CORREGIDA (Privacidad de clave) ---
        st.subheader("🗑️ Eliminar Registro")
        col_del1, col_del2, col_del3 = st.columns([1, 2, 2])
        id_b = col_del1.number_input("ID a borrar", min_value=0, step=1)
        pass_input = col_del2.text_input("Ingrese Clave de Autorización", type="password") # Corregido: ya no muestra la clave en el label
        
        if col_del3.button("❌ ELIMINAR PERMANENTEMENTE"):
            if pass_input == CLAVE_SEGURIDAD:
                if id_b > 0:
                    eliminar_factura(id_b); st.success(f"Registro {id_b} eliminado."); st.rerun()
            else: 
                if pass_input != "": st.error("🔑 Clave incorrecta.")
        conn.close()

# --- 3. CUENTAS POR PAGAR ---
elif menu == "💸 Cuentas por Pagar":
    st.header("Tesorería y Gestión de Pagos")
    tp1, tp2, tp3 = st.tabs(["🔴 Pagos Pendientes", "🏢 Deuda por Proveedor", "📅 Deuda por Mes"])
    
    conn = conectar_db()
    df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total, tipo FROM facturas WHERE estado='Pendiente'", conn)
    
    with tp1:
        if not df_p.empty:
            st.subheader("Listado de Documentos Pendientes")
            st.info("💡 Las filas en rojo indican documentos vencidos.")
            
            df_p['fecha_vencimiento'] = pd.to_datetime(df_p['fecha_vencimiento'])
            hoy = pd.Timestamp(datetime.now().date())

            def highlight_vencidos(row):
                if row['fecha_vencimiento'] < hoy:
                    return ['background-color: #ffcccc'] * len(row)
                return [''] * len(row)

            st.dataframe(df_p.style.apply(highlight_vencidos, axis=1), use_container_width=True)
            
            st.divider()
            st.subheader("Registrar Pago")
            id_p = st.selectbox("ID a Pagar", df_p['id'])
            met = st.selectbox("Método", ["Transferencia", "Efectivo", "Cheque", "Vale Vista"])
            fec = st.date_input("Fecha Pago", datetime.now())
            if st.button("💰 MARCAR COMO PAGADO"):
                cursor = conn.cursor()
                cursor.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (met, fec, id_p))
                conn.commit(); st.success("¡Pago registrado!"); st.rerun()
        else:
            st.success("✅ No hay deudas pendientes.")

    with tp2:
        if not df_p.empty:
            st.subheader("Resumen de Deuda Total por Proveedor")
            deuda_prov = df_p.groupby('proveedor')['monto_total'].sum().reset_index()
            deuda_prov = deuda_prov.sort_values(by='monto_total', ascending=False)
            st.table(deuda_prov.style.format({"monto_total": "${:,.0f}"}))
        else:
            st.info("Sin datos pendientes.")

    with tp3:
        if not df_p.empty:
            st.subheader("Resumen de Compromisos por Mes de Vencimiento")
            df_p['Mes'] = df_p['fecha_vencimiento'].dt.strftime('%m-%Y')
            deuda_mes = df_p.groupby(['Mes'])['monto_total'].sum().reset_index()
            st.table(deuda_mes.style.format({"monto_total": "${:,.0f}"}))
        else:
            st.info("Sin datos pendientes.")
    
    conn.close()

# --- 4. INVENTARIO ---
elif menu == "🚜 Inventario":
    st.header("Bodega y Aplicaciones")
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Stock Actual", "🔄 Mov. Manual", "➕ Nuevo Producto", "🔍 Reporte CC"])
    with tab1:
        conn = conectar_db()
        st.dataframe(pd.read_sql_query("SELECT * FROM inventario ORDER BY producto", conn), use_container_width=True)
        conn.close()
    with tab2:
        with st.form("mm"):
            conn = conectar_db()
            prods = pd.read_sql_query("SELECT id, producto FROM inventario ORDER BY producto", conn)
            ps = st.selectbox("Producto", prods['id'].astype(str) + " - " + prods['producto']) if not prods.empty else None
            tipo = st.radio("Tipo", ["Entrada", "Salida"])
            cant = st.number_input("Cant.", min_value=0.0)
            cc = st.text_input("Centro de Costo (OBLIGATORIO para salidas)")
            if st.form_submit_button("EJECUTAR"):
                if ps:
                    id_p = int(ps.split(" - ")[0])
                    cursor = conn.cursor(); cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo, bodega) VALUES (?,?,?,?,?,?)", (id_p, tipo, cant, datetime.now().date(), cc, "Bodega"))
                    aj = cant if tipo == "Entrada" else -cant
                    cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (aj, id_p)); conn.commit(); st.success("Listo"); st.rerun()
            conn.close()
    with tab3:
        st.subheader("Maestro de Productos")
        with st.form("np"):
            n = st.text_input("Nombre del Producto")
            familias = ["Fertilizante", "Herbicida", "Insecticida", "Fungicidas", "Bio estimulante", "Fertilizante foliar", "Petróleo/Combustible", "Otros"]
            f = st.selectbox("Familia", familias)
            if st.form_submit_button("Crear"):
                if n:
                    conn = conectar_db(); cursor = conn.cursor()
                    cursor.execute("INSERT INTO inventario (producto, familia) VALUES (?,?)", (n, f))
                    conn.commit(); conn.close(); st.success("Creado"); st.rerun()
    with tab4:
        conn = conectar_db(); ccs = pd.read_sql_query("SELECT DISTINCT centro_costo FROM movimientos WHERE tipo='Salida' AND centro_costo != ''", conn)
        cc_f = st.selectbox("Filtrar por CC", ["Todos"] + list(ccs['centro_costo']))
        q_cc = "SELECT m.fecha, i.producto, m.cantidad, m.centro_costo FROM movimientos m JOIN inventario i ON m.producto_id = i.id WHERE m.tipo = 'Salida'"
        if cc_f != "Todos": q_cc += f" AND m.centro_costo = '{cc_f}'"
        q_cc += " ORDER BY i.producto"
        st.dataframe(pd.read_sql_query(q_cc, conn), use_container_width=True); conn.close()
