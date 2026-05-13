import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import os
from fpdf import FPDF # Recuerda añadir fpdf a tu requirements.txt

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="AGRICOLA LA CONCEPCION ERP", page_icon="🚜", layout="wide")

# --- SEGURIDAD Y CONFIGURACIÓN ---
CLAVE_SEGURIDAD = "2908"
DB_NAME = 'erp_concepcion_v6.db'

# --- FUNCIÓN PARA GENERAR PDF ---
def exportar_pdf(df, titulo):
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", "B", 14)
        pdf.cell(0, 10, titulo, ln=True, align="C")
        pdf.ln(5)
        pdf.set_font("Arial", "B", 8)
        
        # Ajuste de anchos de columna dinámico
        cols = df.columns
        col_width = 190 / len(cols)
        
        # Encabezados
        for col in cols:
            pdf.cell(col_width, 8, str(col), border=1, align="C")
        pdf.ln()
        
        # Datos
        pdf.set_font("Arial", "", 7)
        for index, row in df.iterrows():
            for item in row:
                pdf.cell(col_width, 7, str(item)[:20], border=1)
            pdf.ln()
        
        return pdf.output(dest="S").encode("latin-1")
    except:
        return None

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
    conn.commit(); conn.close()

# --- FUNCIONES DE ACCIÓN ---
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
    st.title("AGRICOLA LA CONCEPCION")
    st.markdown("---")
    menu = st.radio("Navegación", ["🏠 Dashboard", "📦 Compras", "💸 Cuentas por Pagar", "🚜 Inventario"])
    st.markdown("---")
    if os.path.exists(DB_NAME):
        with open(DB_NAME, 'rb') as f:
            st.download_button("💾 Respaldo Base Datos", f, DB_NAME, "application/x-sqlite3")
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
    cols_m = st.columns(4)
    for i in range(4):
        m = (fecha_actual.month + i - 1) % 12 + 1
        a = fecha_actual.year + (fecha_actual.month + i - 1) // 12
        monto_mes = 0
        if not df_f.empty:
            df_f['fecha_vencimiento'] = pd.to_datetime(df_f['fecha_vencimiento'])
            monto_mes = df_f[(df_f['fecha_vencimiento'].dt.month == m) & (df_f['fecha_vencimiento'].dt.year == a)]['monto_total'].sum()
        with cols_m[i]:
            st.markdown(f"**{obtener_nombre_mes(m)}**")
            st.markdown(f"<h2 style='color: #2E7D32;'>${monto_mes:,.0f}</h2>", unsafe_allow_html=True)

# --- 2. COMPRAS ---
elif menu == "📦 Compras":
    st.header("Gestión de Adquisiciones")
    t1, t2, t3 = st.tabs(["➕ Factura Insumos", "💸 Gasto Vario", "🔍 Historial"])
    
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
            total_f = st.number_input("Total Factura (IVA incl.)", value=neto_t * 1.19)
            bod = st.selectbox("Bodega", ["Central", "Insumos", "Petróleo"])
            if st.button("💾 GUARDAR FACTURA COMPLETA"):
                if nro and prov:
                    conn = conectar_db(); cursor = conn.cursor()
                    cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_neto, monto_total, tipo) VALUES (?,?,?,?,?,?,?)", (nro, prov, f_c, f_v, neto_t, total_f, 'Factura'))
                    id_fact = cursor.lastrowid
                    for i in st.session_state['carrito']:
                        cursor.execute("INSERT INTO detalle_facturas (factura_id, producto_id, cantidad, precio_neto, total_linea) VALUES (?,?,?,?,?)", (id_fact, i['id'], i['cantidad'], i['precio'], i['total']))
                        cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, bodega, fecha, factura_id, centro_costo) VALUES (?,?,?,?,?,?,?)", (i['id'], "Entrada", i['cantidad'], bod, f_c, id_fact, "Bodega"))
                        cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (i['cantidad'], i['id']))
                    conn.commit(); conn.close(); st.session_state['carrito'] = []; st.success("Guardado"); st.rerun()

    with t2:
        with st.form("fg"):
            st.subheader("Gasto Directo / Servicios")
            g1, g2 = st.columns(2)
            gd = g1.text_input("N° Doc (Opcional)")
            gp = g1.text_input("Proveedor")
            gc = g1.text_area("Concepto")
            gf = g2.date_input("Fecha")
            gv = g2.date_input("Vencimiento Pago", datetime.now() + timedelta(days=7))
            gm = g2.number_input("Monto ($)", min_value=0.0)
            if st.form_submit_button("💾 REGISTRAR GASTO"):
                if gp and gm > 0:
                    doc = gd if gd else f"G-{datetime.now().strftime('%y%m%d%H%M')}"
                    conn = conectar_db(); cursor = conn.cursor()
                    cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_neto, monto_total, tipo) VALUES (?,?,?,?,?,?,?)", (doc, gp, gf, gv, gm, gm, 'Gasto Vario'))
                    conn.commit(); conn.close(); st.success("Registrado."); st.rerun()

    with t3:
        st.subheader("Historial y Eliminación")
        h1, h2, h3, h4 = st.columns(4)
        di = h1.date_input("Desde", datetime.now() - timedelta(days=90))
        df = h2.date_input("Hasta", datetime.now())
        tf = h3.selectbox("Tipo", ["Todos", "Factura", "Gasto Vario"])
        ef = h4.selectbox("Estado", ["Todos", "Pendiente", "Pagado"])
        conn = conectar_db()
        q = f"SELECT id, nro_documento, proveedor, fecha_compra, monto_total, estado, tipo, metodo_pago, fecha_pago FROM facturas WHERE fecha_compra BETWEEN '{di}' AND '{df}'"
        if tf != "Todos": q += f" AND tipo='{tf}'"
        if ef != "Todos": q += f" AND estado='{ef}'"
        df_hist = pd.read_sql_query(q, conn)
        st.dataframe(df_hist, use_container_width=True)
        
        if not df_hist.empty:
            pdf_hist = exportar_pdf(df_hist, f"Historial {di} a {df}")
            if pdf_hist: st.download_button("📥 Descargar Historial PDF", pdf_hist, "historial.pdf", "application/pdf")
        
        st.divider()
        col_d1, col_d2, col_d3 = st.columns([1, 2, 2])
        id_b = col_d1.number_input("ID a borrar", min_value=0, step=1)
        pass_in = col_d2.text_input("Clave Autorización", type="password")
        if col_d3.button("❌ ELIMINAR"):
            if pass_in == CLAVE_SEGURIDAD:
                if id_b > 0: eliminar_factura(id_b); st.success(f"ID {id_b} eliminado."); st.rerun()
            else: st.error("Clave incorrecta.")
        conn.close()

# --- 3. CUENTAS POR PAGAR ---
elif menu == "💸 Cuentas por Pagar":
    st.header("Tesorería")
    tp1, tp2, tp3 = st.tabs(["🔴 Pendientes", "🏢 Por Proveedor", "📅 Por Rango de Fechas"])
    conn = conectar_db()
    
    with tp1:
        df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente'", conn)
        if not df_p.empty:
            df_p['fecha_vencimiento'] = pd.to_datetime(df_p['fecha_vencimiento'])
            hoy = pd.Timestamp(datetime.now().date())
            st.dataframe(df_p.style.apply(lambda r: ['background-color: #ffcccc' if r.fecha_vencimiento < hoy else '' for _ in r], axis=1), use_container_width=True)
            
            pdf_p = exportar_pdf(df_p, "Cuentas Pendientes de Pago")
            if pdf_p: st.download_button("📥 Descargar Pendientes PDF", pdf_p, "pendientes.pdf", "application/pdf")
            
            st.divider()
            id_p = st.selectbox("ID a Pagar", df_p['id'])
            met = st.selectbox("Método", ["Transferencia", "Efectivo", "Cheque", "Vale Vista"])
            fec_p = st.date_input("Fecha Pago", datetime.now())
            if st.button("💰 REGISTRAR PAGO"):
                cursor = conn.cursor()
                cursor.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (met, fec_p, id_p))
                conn.commit(); st.success("Pagado!"); st.rerun()
        else: st.success("✅ Sin deudas.")

    with tp2:
        st.subheader("Deuda por Proveedor")
        d1, d2 = st.columns(2)
        f_i = d1.date_input("Vence Desde", datetime.now() - timedelta(days=60), key="p1")
        f_f = d2.date_input("Vence Hasta", datetime.now() + timedelta(days=60), key="p2")
        df_prov = pd.read_sql_query(f"SELECT proveedor, SUM(monto_total) as Total FROM facturas WHERE estado='Pendiente' AND fecha_vencimiento BETWEEN '{f_i}' AND '{f_f}' GROUP BY proveedor", conn)
        st.table(df_prov)
        if not df_prov.empty:
            pdf_prov = exportar_pdf(df_prov, f"Deuda Proveedores ({f_i} a {f_f})")
            if pdf_prov: st.download_button("📥 Descargar Deuda Proveedor PDF", pdf_prov, "deuda_prov.pdf", "application/pdf")

    with tp3:
        st.subheader("Deuda en Rango de Fechas")
        r1, r2 = st.columns(2)
        r_i = r1.date_input("Desde", datetime.now(), key="r1")
        r_f = r2.date_input("Hasta", datetime.now() + timedelta(days=30), key="r2")
        df_r = pd.read_sql_query(f"SELECT fecha_vencimiento, nro_documento, proveedor, monto_total FROM facturas WHERE estado='Pendiente' AND fecha_vencimiento BETWEEN '{r_i}' AND '{r_f}' ORDER BY fecha_vencimiento", conn)
        st.dataframe(df_r, use_container_width=True)
        if not df_r.empty:
            st.metric("Total Rango", f"${df_r['monto_total'].sum():,.0f}")
            pdf_r = exportar_pdf(df_r, f"Compromisos {r_i} a {r_f}")
            if pdf_r: st.download_button("📥 Descargar Rango PDF", pdf_r, "deuda_rango.pdf", "application/pdf")
    conn.close()

# --- 4. INVENTARIO ---
elif menu == "🚜 Inventario":
    st.header("Bodega")
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Stock Actual", "🔄 Movimiento", "➕ Nuevo", "🔍 Reporte CC"])
    with tab1:
        conn = conectar_db()
        df_s = pd.read_sql_query("SELECT * FROM inventario ORDER BY producto", conn)
        st.dataframe(df_s, use_container_width=True)
        if not df_s.empty:
            pdf_s = exportar_pdf(df_s, "Stock Actual de Bodega")
            if pdf_s: st.download_button("📥 Descargar Stock PDF", pdf_s, "stock.pdf", "application/pdf")
        conn.close()
    with tab2:
        with st.form("mm"):
            conn = conectar_db()
            prods = pd.read_sql_query("SELECT id, producto FROM inventario ORDER BY producto", conn)
            ps = st.selectbox("Producto", prods['id'].astype(str) + " - " + prods['producto']) if not prods.empty else None
            tipo = st.radio("Tipo", ["Entrada", "Salida"])
            cant = st.number_input("Cantidad", min_value=0.0)
            cc = st.text_input("Centro de Costo (OBLIGATORIO salidas)")
            if st.form_submit_button("EJECUTAR"):
                if ps:
                    id_p = int(ps.split(" - ")[0])
                    cursor = conn.cursor(); cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo, bodega) VALUES (?,?,?,?,?,?)", (id_p, tipo, cant, datetime.now().date(), cc, "Bodega"))
                    aj = cant if tipo == "Entrada" else -cant
                    cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (aj, id_p))
                    conn.commit(); st.success("Listo"); st.rerun()
            conn.close()
    with tab3:
        with st.form("np"):
            n = st.text_input("Nombre Producto")
            f = st.selectbox("Familia", ["Fertilizante", "Herbicida", "Insecticida", "Fungicidas", "Bio estimulante", "Fertilizante foliar", "Petróleo/Combustible", "Otros"])
            if st.form_submit_button("Crear"):
                if n:
                    conn = conectar_db(); cursor = conn.cursor(); cursor.execute("INSERT INTO inventario (producto, familia) VALUES (?,?)", (n, f)); conn.commit(); conn.close(); st.success("Creado"); st.rerun()
    with tab4:
        conn = conectar_db(); ccs = pd.read_sql_query("SELECT DISTINCT centro_costo FROM movimientos WHERE tipo='Salida' AND centro_costo != ''", conn)
        cc_f = st.selectbox("Filtrar Centro Costo", ["Todos"] + list(ccs['centro_costo']))
        q_cc = "SELECT m.fecha, i.producto, m.cantidad, m.centro_costo FROM movimientos m JOIN inventario i ON m.producto_id = i.id WHERE m.tipo = 'Salida'"
        if cc_f != "Todos": q_cc += f" AND m.centro_costo = '{cc_f}'"
        df_cc = pd.read_sql_query(q_cc + " ORDER BY m.fecha DESC", conn)
        st.dataframe(df_cc, use_container_width=True)
        if not df_cc.empty:
            pdf_cc = exportar_pdf(df_cc, f"Aplicaciones CC: {cc_f}")
            if pdf_cc: st.download_button("📥 Descargar Reporte CC PDF", pdf_cc, "reporte_cc.pdf", "application/pdf")
        conn.close()
