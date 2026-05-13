import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import os

# Intentamos importar FPDF para reportes
try:
    from fpdf import FPDF
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="AGRICOLA LA CONCEPCION ERP", page_icon="🚜", layout="wide")

# --- SEGURIDAD ---
CLAVE_SEGURIDAD = "2908"
DB_NAME = 'erp_concepcion_v6.db'

# --- FUNCIÓN DE FORMATEO (1.000.000) ---
def f_puntos(valor):
    try:
        return f"{int(valor):,}".replace(",", ".")
    except:
        return "0"

# --- FUNCIÓN GENERADORA DE PDF ---
def generar_pdf(df, titulo):
    if not PDF_AVAILABLE: return None
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", "B", 14)
        pdf.cell(0, 10, titulo, ln=True, align="C")
        pdf.ln(5)
        pdf.set_font("Arial", "B", 8)
        cols = df.columns
        w = 190 / len(cols)
        for col in cols:
            pdf.cell(w, 8, str(col), border=1, align="C")
        pdf.ln()
        pdf.set_font("Arial", "", 7)
        for _, row in df.iterrows():
            for item in row:
                val = f_puntos(item) if isinstance(item, (int, float)) else str(item)
                pdf.cell(w, 7, val[:20], border=1)
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

inicializar_db()
if 'carrito' not in st.session_state: st.session_state['carrito'] = []

# --- SIDEBAR ---
with st.sidebar:
    st.title("AGRICOLA LA CONCEPCION")
    menu = st.radio("Navegación", ["🏠 Dashboard", "📦 Compras", "💸 Cuentas por Pagar", "🚜 Inventario"])
    st.markdown("---")
    if os.path.exists(DB_NAME):
        with open(DB_NAME, 'rb') as f:
            st.download_button("💾 Respaldo DB", f, DB_NAME, "application/x-sqlite3")
    if st.button("🗑️ Vaciar Carrito"):
        st.session_state['carrito'] = []
        st.rerun()

# --- 1. DASHBOARD ---
if menu == "🏠 Dashboard":
    st.header("📊 Resumen Financiero")
    conn = conectar_db()
    df_f = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente'", conn)
    conn.close()
    c1, c2 = st.columns(2)
    total = df_f['monto_total'].sum() if not df_f.empty else 0
    c1.metric("Deuda Pendiente Total", f"${f_puntos(total)}")
    hoy = datetime.now().date()
    vencidas = df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < hoy].shape[0] if not df_f.empty else 0
    c2.metric("Documentos Vencidos", vencidas, delta_color="inverse")
    st.subheader("📅 Proyección de Pagos (4 Meses)")
    cols_m = st.columns(4)
    for i in range(4):
        f_t = datetime.now() + timedelta(days=i*30)
        m, a = f_t.month, f_t.year
        monto = 0
        if not df_f.empty:
            df_f['fv'] = pd.to_datetime(df_f['fecha_vencimiento'])
            monto = df_f[(df_f['fv'].dt.month == m) & (df_f['fv'].dt.year == a)]['monto_total'].sum()
        with cols_m[i]:
            st.markdown(f"**{obtener_nombre_mes(m)}**")
            st.markdown(f"## ${f_puntos(monto)}")

# --- 2. COMPRAS ---
elif menu == "📦 Compras":
    st.header("Gestión de Compras")
    t1, t2, t3 = st.tabs(["➕ Factura", "💸 Gasto Vario", "🔍 Historial"])
    with t1:
        c1, c2 = st.columns(2)
        nro = c1.text_input("N° Factura")
        prov = c1.text_input("Proveedor")
        f_c = c2.date_input("Fecha Compra")
        f_v = c2.date_input("Vencimiento", datetime.now() + timedelta(days=30))
        conn = conectar_db(); df_inv = pd.read_sql_query("SELECT id, producto FROM inventario ORDER BY producto", conn); conn.close()
        if not df_inv.empty:
            cp1, cp2, cp3, cp4 = st.columns([3,1,1,1])
            p_sel = cp1.selectbox("Insumo", df_inv['id'].astype(str) + " - " + df_inv['producto'])
            cant = cp2.number_input("Cant.", min_value=0.0)
            prec = cp3.number_input("Precio Neto", min_value=0.0)
            if cp4.button("➕"):
                if cant > 0:
                    st.session_state['carrito'].append({'id': int(p_sel.split(" - ")[0]), 'nombre': p_sel.split(" - ")[1], 'cantidad': cant, 'precio': prec, 'total': cant * prec})
                    st.rerun()
        if st.session_state['carrito']:
            df_car = pd.DataFrame(st.session_state['carrito'])
            st.dataframe(df_car[['nombre', 'cantidad', 'precio', 'total']].style.format({"precio": "${:,.0f}", "total": "${:,.0f}"}), use_container_width=True)
            total_f = st.number_input("Total Final (IVA incl.)", value=sum(i['total'] for i in st.session_state['carrito']) * 1.19)
            if st.button("💾 GUARDAR FACTURA"):
                if nro and prov:
                    conn = conectar_db(); cursor = conn.cursor()
                    cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, estado) VALUES (?,?,?,?,?,?,?)", (nro, prov, f_c, f_v, total_f, 'Factura', 'Pendiente'))
                    fid = cursor.lastrowid
                    for i in st.session_state['carrito']:
                        cursor.execute("INSERT INTO detalle_facturas (factura_id, producto_id, cantidad, precio_neto) VALUES (?,?,?,?)", (fid, i['id'], i['cantidad'], i['precio']))
                        cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, factura_id, centro_costo, bodega) VALUES (?,?,?,?,?,?,?)", (i['id'], "Entrada", i['cantidad'], f_c, fid, "Bodega", "Central"))
                        cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (i['cantidad'], i['id']))
                    conn.commit(); conn.close(); st.session_state['carrito'] = []; st.success("Guardado!"); st.rerun()
    with t3:
        h1, h2 = st.columns(2)
        di, d_f = h1.date_input("Desde", datetime.now() - timedelta(days=90), key="h1"), h2.date_input("Hasta", datetime.now(), key="h2")
        conn = conectar_db(); df_h = pd.read_sql_query(f"SELECT id, nro_documento, proveedor, fecha_compra, monto_total, estado FROM facturas WHERE fecha_compra BETWEEN '{di}' AND '{d_f}'", conn); conn.close()
        if not df_h.empty:
            st.dataframe(df_h.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
            if PDF_AVAILABLE:
                pdf = generar_pdf(df_h, "Historial de Compras")
                st.download_button("📥 PDF Historial", pdf, "historial.pdf", "application/pdf")
        st.divider(); col_b1, col_b2, col_b3 = st.columns([1,1,2])
        id_b = col_b1.number_input("ID a borrar", min_value=0, step=1)
        pw = col_b2.text_input("Clave", type="password")
        if col_b3.button("❌ ELIMINAR"):
            if pw == CLAVE_SEGURIDAD: eliminar_factura(id_b); st.success("Eliminado"); st.rerun()
            else: st.error("Clave Incorrecta")

# --- 3. CUENTAS POR PAGAR ---
elif menu == "💸 Cuentas por Pagar":
    st.header("Tesorería")
    tp1, tp2, tp3 = st.tabs(["🔴 Pendientes", "🏢 Por Proveedor", "📅 Por Rango"])
    conn = conectar_db()
    with tp1:
        df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente'", conn)
        if not df_p.empty:
            df_p['fecha_vencimiento'] = pd.to_datetime(df_p['fecha_vencimiento'])
            hoy = pd.Timestamp(datetime.now().date())
            st.dataframe(df_p.style.apply(lambda r: ['background-color: #ffcccc' if r.fecha_vencimiento < hoy else '' for _ in r], axis=1).format({"monto_total": "${:,.0f}"}), use_container_width=True)
            id_p = st.selectbox("ID Pago", df_p['id'])
            met = st.selectbox("Método", ["Transferencia", "Efectivo", "Cheque", "Vale Vista"])
            if st.button("💰 PAGAR"):
                conn.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (met, datetime.now().date(), id_p))
                conn.commit(); st.success("Pagado!"); st.rerun()
        else: st.success("Sin deudas.")
    with tp2:
        d1, d2 = st.columns(2)
        f1, f2 = d1.date_input("Vence Desde", datetime.now()-timedelta(days=30), key="p1"), d2.date_input("Vence Hasta", datetime.now()+timedelta(days=60), key="p2")
        df_pr = pd.read_sql_query(f"SELECT proveedor, SUM(monto_total) as Total FROM facturas WHERE estado='Pendiente' AND fecha_vencimiento BETWEEN '{f1}' AND '{f2}' GROUP BY proveedor", conn)
        if not df_pr.empty:
            st.table(df_pr.style.format({"Total": "${:,.0f}"}))
            if PDF_AVAILABLE:
                pdf_pr = generar_pdf(df_pr, "Deuda por Proveedor")
                st.download_button("📥 PDF Proveedores", pdf_pr, "proveedores.pdf", "application/pdf")
    with tp3:
        r1, r2 = st.columns(2)
        ri, rf = r1.date_input("Vence Desde", datetime.now(), key="r1"), r2.date_input("Vence Hasta", datetime.now()+timedelta(days=30), key="r2")
        df_r = pd.read_sql_query(f"SELECT fecha_vencimiento, nro_documento, proveedor, monto_total FROM facturas WHERE estado='Pendiente' AND fecha_vencimiento BETWEEN '{ri}' AND '{rf}'", conn)
        if not df_r.empty:
            st.dataframe(df_r.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
            st.metric("Total en Rango", f"${f_puntos(df_r['monto_total'].sum())}")
    conn.close()

# --- 4. INVENTARIO ---
elif menu == "🚜 Inventario":
    st.header("Bodega")
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Stock", "🔄 Movimiento", "➕ Nuevo", "🔍 Reporte CC"])
    with tab1:
        conn = conectar_db(); df_s = pd.read_sql_query("SELECT id, producto, familia, stock FROM inventario ORDER BY producto", conn); conn.close()
        st.dataframe(df_s, use_container_width=True)
        if not df_s.empty and PDF_AVAILABLE:
            pdf_s = generar_pdf(df_s, "Stock Actual")
            st.download_button("📥 PDF Stock", pdf_s, "stock.pdf", "application/pdf")
    with tab2:
        with st.form("mm"):
            conn = conectar_db(); prods = pd.read_sql_query("SELECT id, producto FROM inventario ORDER BY producto", conn)
            ps = st.selectbox("Insumo", prods['id'].astype(str) + " - " + prods['producto']) if not prods.empty else None
            tipo, cant, cc = st.radio("Tipo", ["Entrada", "Salida"]), st.number_input("Cantidad", min_value=0.0), st.text_input("Centro Costo")
            if st.form_submit_button("EJECUTAR"):
                if ps and cant > 0:
                    id_p = int(ps.split(" - ")[0])
                    conn.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo, bodega) VALUES (?,?,?,?,?,?)", (id_p, tipo, cant, datetime.now().date(), cc, "Bodega"))
                    aj = cant if tipo == "Entrada" else -cant
                    conn.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (aj, id_p))
                    conn.commit(); conn.close(); st.success("Movimiento registrado."); st.rerun()
    with tab3:
        with st.form("np"):
            n = st.text_input("Nombre"); f = st.selectbox("Familia", ["Fertilizante", "Herbicida", "Insecticida", "Fungicidas", "Bio estimulante", "Fertilizante foliar", "Petróleo/Combustible", "Otros"])
            if st.form_submit_button("CREAR"):
                if n:
                    conn = conectar_db(); conn.execute("INSERT INTO inventario (producto, familia) VALUES (?,?)", (n, f)); conn.commit(); conn.close(); st.success("Creado!"); st.rerun()
    with tab4:
        conn = conectar_db(); ccs = pd.read_sql_query("SELECT DISTINCT centro_costo FROM movimientos WHERE tipo='Salida' AND centro_costo != ''", conn)
        cc_f = st.selectbox("Filtrar CC", ["Todos"] + list(ccs['centro_costo']))
        q = "SELECT m.fecha, i.producto, m.cantidad, m.centro_costo FROM movimientos m JOIN inventario i ON m.producto_id = i.id WHERE m.tipo = 'Salida'"
        if cc_f != "Todos": q += f" AND m.centro_costo = '{cc_f}'"
        df_cc = pd.read_sql_query(q, conn); conn.close()
        st.dataframe(df_cc, use_container_width=True)
        if not df_cc.empty and PDF_AVAILABLE:
            pdf_cc = generar_pdf(df_cc, f"Reporte CC: {cc_f}")
            st.download_button("📥 PDF Reporte CC", pdf_cc, "reporte_cc.pdf", "application/pdf")
