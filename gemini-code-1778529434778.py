import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import os
import hashlib
from fpdf import FPDF
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. CONFIGURACIÓN Y CONSTANTES ---
ID_CARPETA_DRIVE = "12tjxWa_RVRP5YuYd2sypjBO8bPuyMqo6" 
NOMBRE_DB = 'erp_concepcion_v6.db'
CLAVE_MAESTRA = "2908" 
hoy = datetime.now().date()

FAMILIAS_PRODUCTOS = ["FERTILIZANTE", "FERTILIZANTE FOLIAR", "HERBICIDA", "INSECTICIDA", "FUNGICIDA", "BIO ESTIMULANTE", "ACARICIDA", "REGULADOR DE CRECIMIENTO", "ADHERENTE / MOJANTE", "OTROS"]
CENTROS_COSTO = ["CEREZOS CORTE1", "CEREZOS CORTE2", "CIRUELOS", "NOGALES APARICION", "NOGALES CRUZ DEL SUR", "OTROS"]

# --- 2. MOTOR DE BASE DE DATOS Y SEGURIDAD ---
def conectar_db():
    return sqlite3.connect(NOMBRE_DB)

def hash_password(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def inicializar_db():
    conn = conectar_db(); cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS facturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nro_documento TEXT, proveedor TEXT, 
        fecha_compra DATE, fecha_vencimiento DATE, monto_neto REAL, monto_total REAL, 
        estado TEXT DEFAULT 'Pendiente', tipo TEXT DEFAULT 'Factura', 
        metodo_pago TEXT, fecha_pago DATE, concepto TEXT, centro_costo TEXT, monto_imputado REAL DEFAULT 0)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS inventario (
        id INTEGER PRIMARY KEY AUTOINCREMENT, producto TEXT, familia TEXT, 
        stock REAL DEFAULT 0, stock_minimo REAL DEFAULT 0, precio_medio REAL DEFAULT 0)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS movimientos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, producto_id INTEGER, tipo TEXT, 
        cantidad REAL, centro_costo TEXT, fecha DATE, valor_imputado REAL DEFAULT 0)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, password TEXT)""")
    
    usuarios = [
        ('osvaldolira@laconcepcion.cl', hash_password('9083')),
        ('secretaria@laconcepcion.cl', hash_password('1234')),
        ('secretarialaconcepcion@gmail.com', hash_password('5678'))
    ]
    for email, pw in usuarios:
        cursor.execute("SELECT * FROM usuarios WHERE email=?", (email,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO usuarios (email, password) VALUES (?,?)", (email, pw))
    conn.commit(); conn.close()

# --- 3. UTILIDADES ---
def f_puntos(v):
    try: return f"{int(round(float(v))):,}".replace(",", ".")
    except: return "0"

def f_decimal(v):
    try: return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return "0,00"

def generar_pdf_blob(df, titulo):
    try:
        pdf = FPDF(); pdf.add_page(); pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, "AGRICOLA LA CONCEPCIÓN", ln=True, align="C")
        pdf.set_font("Helvetica", "B", 12); pdf.cell(0, 10, titulo, ln=True, align="C")
        pdf.ln(5); pdf.set_font("Helvetica", "B", 8)
        cols = df.columns; w = 190 / len(cols)
        for col in cols: pdf.cell(w, 8, str(col).upper(), border=1, align="C")
        pdf.ln(); pdf.set_font("Helvetica", "", 7); total_acum = 0
        for _, row in df.iterrows():
            for i, item in enumerate(row):
                col_name = df.columns[i].lower()
                if any(x in col_name for x in ["monto", "total", "valor", "imputado"]):
                    try: total_acum += float(item)
                    except: pass
                val = f_decimal(item) if any(x in col_name for x in ["cantidad", "stock"]) else (f_puntos(item) if isinstance(item, (int, float)) else str(item))
                pdf.cell(w, 7, val[:25], border=1)
            pdf.ln()
        pdf.set_font("Helvetica", "B", 9); pdf.cell(w * (len(cols)-1), 8, "TOTAL FINAL:", border=1, align="R")
        pdf.cell(w, 8, f"${f_puntos(total_acum)}", border=1, align="L")
        return pdf.output(dest="S").encode("latin-1")
    except: return None

# --- DRIVE ---
def obtener_drive():
    try:
        if "gcp_service_account" not in st.secrets: return None
        info = dict(st.secrets["gcp_service_account"])
        if "private_key" in info: info["private_key"] = info["private_key"].replace("\\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(info, ['https://www.googleapis.com/auth/drive'])
        gauth = GoogleAuth(); gauth.credentials = creds
        return GoogleDrive(gauth)
    except: return None

def guardar_en_drive():
    drive = obtener_drive()
    if drive:
        query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
        lista = drive.ListFile({'q': query}).GetList()
        f = lista[0] if lista else drive.CreateFile({'title': NOMBRE_DB, 'parents': [{'id': ID_CARPETA_DRIVE}]})
        f.SetContentFile(NOMBRE_DB); f.Upload()
        st.success("✅ Sincronizado con Drive.")

def descargar_de_drive():
    drive = obtener_drive()
    if drive:
        query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
        lista = drive.ListFile({'q': query}).GetList()
        if lista: lista[0].GetContentFile(NOMBRE_DB)

# --- ESTILOS ---
def inyectar_css():
    st.markdown("""
        <style>
        .main { background-color: #f4f7f6; }
        .stMetric { background-color: white; padding: 20px; border-radius: 12px; border-left: 6px solid #2E7D32; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }
        h1, h2, h3 { color: #1B5E20; font-family: 'Arial'; }
        .stButton>button { border-radius: 8px; background-color: #2E7D32; color: white; font-weight: bold; }
        </style>
    """, unsafe_allow_html=True)

# --- LOGIN ---
def login_page():
    inyectar_css()
    st.markdown("<h1 style='text-align: center; color: #1B5E20; margin-top: 50px;'>🚜 ERP La Concepción</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        with st.form("login_form"):
            e = st.text_input("Email Corporativo")
            p = st.text_input("Contraseña", type="password")
            if st.form_submit_button("ACCEDER AL SISTEMA"):
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("SELECT email FROM usuarios WHERE email=? AND password=?", (e, hash_password(p)))
                if cursor.fetchone():
                    st.session_state['logged_in'] = True; st.session_state['email'] = e; st.rerun()
                else: st.error("Email o clave incorrectos.")

# --- MÓDULOS ---
def modulo_dashboard():
    inyectar_css()
    st.markdown("<h1>🚜 ERP Agrícola La Concepción</h1>", unsafe_allow_html=True)
    st.subheader(f"Usuario: {st.session_state['email']}")
    conn = conectar_db(); df_f = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente'", conn)
    query_c = """
    SELECT UPPER(TRIM(centro_costo)) as cc, SUM(monto_imputado) as total_neto FROM (
        SELECT centro_costo, valor_imputado as monto_imputado FROM movimientos WHERE tipo LIKE 'Salida%'
        UNION ALL
        SELECT centro_costo, monto_imputado FROM facturas WHERE tipo = 'Gasto Vario'
    ) WHERE cc IS NOT NULL AND cc != '' GROUP BY cc """
    df_c = pd.read_sql_query(query_c, conn); conn.close()
    
    t_d = df_f['monto_total'].sum() if not df_f.empty else 0
    v_a = df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < hoy.replace(day=1)]['monto_total'].sum() if not df_f.empty else 0
    v_h = len(df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < hoy]) if not df_f.empty else 0
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("DEUDA TOTAL", f"${f_puntos(t_d)}")
    with c2: st.markdown("MESES ANTERIORES"); st.markdown(f"<h2 style='color:red;'>${f_puntos(v_a)}</h2>", unsafe_allow_html=True)
    with c3: st.markdown("VENCIDOS HOY"); st.markdown(f"<h2 style='color:orange;'>{v_h}</h2>", unsafe_allow_html=True)
    c4.metric("DOCS. PENDIENTES", f"{len(df_f)}")
    
    st.divider()
    col1, col2 = st.columns([1.5, 1])
    with col1:
        st.subheader("💰 Resumen Costos por Cuartel")
        if not df_c.empty:
            df_total = pd.DataFrame([{"cc": "TOTAL GENERAL", "total_neto": df_c["total_neto"].sum()}])
            df_res = pd.concat([df_c, df_total], ignore_index=True)
            def bold_t(row): return ['font-weight: bold; background-color: #E8F5E9' if row['cc'] == "TOTAL GENERAL" else '' for _ in row]
            st.dataframe(df_res.style.apply(bold_t, axis=1).format({"total_neto": "${:,.0f}"}), use_container_width=True)
    with col2:
        st.subheader("📅 Proyección Mensual (4 Meses)")
        meses = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]
        for i in range(4):
            ft = (datetime.now().replace(day=1) + timedelta(days=i*31)).replace(day=1)
            v = df_f[(pd.to_datetime(df_f['fecha_vencimiento']).dt.month == ft.month) & (pd.to_datetime(df_f['fecha_vencimiento']).dt.year == ft.year)]['monto_total'].sum() if not df_f.empty else 0
            st.markdown(f"<div style='background:white; padding:12px; border-radius:10px; margin-bottom:8px; display:flex; justify-content:space-between; border:1px solid #ddd;'><b>{meses[ft.month-1]} {ft.year}</b> <span style='color:#2E7D32;'>${f_puntos(v)}</span></div>", unsafe_allow_html=True)

def modulo_compras():
    st.header("📦 Compras y Gastos")
    t1, t2, t3 = st.tabs(["➕ Factura Insumos", "💸 Gasto Vario", "🔍 Historial / Gestión"])
    conn = conectar_db()
    with t1:
        c1, c2 = st.columns(2); nro, prov = c1.text_input("N° Factura"), c1.text_input("Proveedor"); fe, fv = c2.date_input("Emisión"), c2.date_input("Vencimiento")
        df_inv = pd.read_sql_query("SELECT id, producto, stock, precio_medio FROM inventario ORDER BY producto", conn)
        cp1, cp2, cp3, cp4 = st.columns([3,1,1,1]); ps = cp1.selectbox("Insumo", df_inv['id'].astype(str) + " - " + df_inv['producto']) if not df_inv.empty else None
        ct, pr = cp2.number_input("Cant", 0.0), cp3.number_input("Neto", 0.0)
        if cp4.button("Añadir ➕") and ps:
            if 'car' not in st.session_state: st.session_state['car'] = []
            st.session_state['car'].append({'id': int(ps.split(" - ")[0]), 'n': ps.split(" - ")[1], 'c': ct, 'p': pr, 't': ct*pr}); st.rerun()
        if st.session_state.get('car'):
            df_car = pd.DataFrame(st.session_state['car']); st.table(df_car); total_f = st.number_input("Total (IVA)", value=float(df_car['t'].sum()*1.19))
            if st.button("💾 GUARDAR FACTURA"):
                conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total) VALUES (?,?,?,?,?)", (nro, prov, fe, fv, total_f))
                for i in st.session_state['car']:
                    cur = conn.execute("SELECT stock, precio_medio FROM inventario WHERE id=?", (i['id'],)).fetchone()
                    n_pmp = ((cur[0]*cur[1]) + (i['c']*i['p'])) / (cur[0]+i['c']) if (cur[0]+i['c']) > 0 else i['p']
                    conn.execute("UPDATE inventario SET stock = stock + ?, precio_medio = ? WHERE id = ?", (i['c'], n_pmp, i['id']))
                conn.commit(); guardar_en_drive(); st.session_state['car'] = []; st.rerun()
    with t2:
        c1, c2 = st.columns(2); prov_g, nro_g = c1.text_input("Proveedor ", key="pg"), c2.text_input("N° Doc ", key="ng")
        cf1, cf2 = st.columns(2); fe_g, fv_g = cf1.date_input("Compra", hoy, key="fg1"), cf2.date_input("Vence", hoy, key="fg2")
        detalles_g = st.text_area("Concepto", height=70); ccs_sel = []; cols = st.columns(3)
        for i, cc in enumerate(CENTROS_COSTO):
            if cols[i % 3].checkbox(cc, key=f"gv_{cc}"): ccs_sel.append(cc)
        m1, m2 = st.columns(2); m_n = m1.number_input("Neto Total", 0.0); iva = m2.radio("IVA al costo?", ["SÍ", "NO"])
        if len(ccs_sel) > 0 and m_n > 0:
            imp = (m_n / len(ccs_sel)) if iva == "SÍ" else (m_n / len(ccs_sel)) / 1.19
            if st.button("💾 GUARDAR GASTO PRORRATEADO"):
                conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, concepto) VALUES (?,?,?,?,?,?,?)", (nro_g, prov_g, fe_g, fv_g, m_n*1.19, 'Gasto Vario', detalles_g))
                for c in ccs_sel: conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, centro_costo, monto_imputado, concepto) VALUES (?,?,?,?,?,?,?,?,?)", (nro_g+"_P", prov_g, fe_g, fv_g, 0, 'Gasto Vario', c.upper(), imp, detalles_g))
                conn.commit(); guardar_en_drive(); st.rerun()
    with t3:
        rf = conn.execute("SELECT MIN(fecha_compra), MAX(fecha_compra) FROM facturas").fetchone()
        fmin = pd.to_datetime(rf[0]).date() if rf[0] else hoy-timedelta(days=365); fmax = pd.to_datetime(rf[1]).date() if rf[1] else hoy
        cf1, cf2 = st.columns(2); h1, h2 = cf1.date_input("Desde", fmin), cf2.date_input("Hasta", fmax)
        df_h = pd.read_sql_query(f"SELECT id, nro_documento, proveedor, fecha_compra, monto_total, estado, tipo, concepto FROM facturas WHERE monto_total > 0 AND fecha_compra BETWEEN '{h1}' AND '{h2}' ORDER BY fecha_compra DESC", conn)
        st.dataframe(df_h.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
        if not df_h.empty:
            st.download_button("📥 PDF Historial", generar_pdf_blob(df_h, "HISTORIAL COMPRAS"), "compras.pdf")
            st.divider(); id_sel = st.selectbox("ID a Gestionar", df_h['id']); row = df_h[df_h['id'] == id_sel].iloc[0]
            mn, mm = st.text_input("Nuevo N° Doc", row['nro_documento']), st.number_input("Nuevo Monto ", value=float(row['monto_total']))
            cl = st.text_input("Clave Maestra", type="password", key="cl_hist")
            col1, col2 = st.columns(2)
            if col1.button("✏️ MODIFICAR") and cl == CLAVE_MAESTRA:
                conn.execute("UPDATE facturas SET nro_documento=?, monto_total=? WHERE id=?", (mn, mm, id_sel)); conn.commit(); guardar_en_drive(); st.rerun()
            if col2.button("🗑️ ELIMINAR") and cl == CLAVE_MAESTRA:
                conn.execute("DELETE FROM facturas WHERE id=?", (id_sel,)); conn.commit(); guardar_en_drive(); st.rerun()
    conn.close()

def modulo_tesoreria():
    st.header("💸 Tesorería")
    tp1, tp2, tp3 = st.tabs(["🔴 Pendientes", "🏢 Proveedor", "📅 Rango de Vencimiento"])
    conn = conectar_db()
    with tp1:
        df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' AND monto_total > 0 ORDER BY fecha_vencimiento ASC", conn)
        st.info(f"### DEUDA PENDIENTE: ${f_puntos(df_p['monto_total'].sum() if not df_p.empty else 0)}")
        if not df_p.empty:
            st.dataframe(df_p.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
            st.download_button("📥 PDF Pendientes", generar_pdf_blob(df_p, "DEUDAS PENDIENTES"), "deuda.pdf")
            id_p = st.selectbox("ID Factura", df_p['id']); met = st.selectbox("Medio", ["Transferencia", "Efectivo", "Cheque"])
            if st.button("💰 MARCAR PAGADO"):
                conn.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (met, hoy, id_p)); conn.commit(); guardar_en_drive(); st.rerun()
    with tp3:
        f1, f2 = st.date_input("Vence Desde", hoy), st.date_input("Hasta", hoy+timedelta(days=30))
        df_r = pd.read_sql_query(f"SELECT nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' AND monto_total > 0 AND fecha_vencimiento BETWEEN '{f1}' AND '{f2}' ORDER BY fecha_vencimiento ASC", conn)
        st.success(f"### DEUDA EN RANGO: ${f_puntos(df_r['monto_total'].sum() if not df_r.empty else 0)}")
        if not df_r.empty:
            st.dataframe(df_r.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
            st.download_button("📥 PDF Rango", generar_pdf_blob(df_r, "VENCIMIENTOS"), "rango.pdf")
    conn.close()

def modulo_bodega():
    st.header("🚜 Bodega")
    tb1, tb2, tb3, tb4 = st.tabs(["📊 Stock", "🔄 Movimientos", "➕ Nuevo", "🔍 Consulta CC"])
    conn = conectar_db()
    with tb1:
        df_s = pd.read_sql_query("SELECT id, producto, familia, stock, precio_medio FROM inventario ORDER BY producto ASC", conn)
        st.dataframe(df_s.style.format({"stock": "{:,.2f}", "precio_medio": "${:,.0f}"}), use_container_width=True)
        if not df_s.empty:
            st.divider(); id_ins = st.selectbox("Insumo", df_s['id']); item = df_s[df_s['id']==id_ins].iloc[0]
            n_n, n_p = st.text_input("Nombre", item['producto']), st.number_input("Precio PMP", value=float(item['precio_medio']))
            cl = st.text_input("Clave Maestro", type="password", key="cbod")
            c1, c2 = st.columns(2)
            if c1.button("✏️ ACTUALIZAR") and cl == CLAVE_MAESTRA:
                conn.execute("UPDATE inventario SET producto=?, precio_medio=? WHERE id=?", (n_n, n_p, id_ins)); conn.commit(); guardar_en_drive(); st.rerun()
            if c2.button("🗑️ ELIMINAR") and cl == CLAVE_MAESTRA:
                conn.execute("DELETE FROM inventario WHERE id=?", (id_ins,)); conn.commit(); guardar_en_drive(); st.rerun()
    with tb2:
        tipo = st.radio("Acción", ["Salida (Campo)", "Entrada"])
        with st.form("mov_form"):
            df_i = pd.read_sql_query("SELECT id, producto, precio_medio FROM inventario", conn)
            ps = st.selectbox("Producto", df_i['id'].astype(str) + " - " + df_i['producto']); ct = st.number_input("Cant", 0.01)
            cc = st.selectbox("CC (Solo Salidas)", CENTROS_COSTO) if tipo == "Salida (Campo)" else ""
            if st.form_submit_button("REGISTRAR"):
                item = df_i[df_i['id'] == int(ps.split(" - ")[0])].iloc[0]; val = ct * item['precio_medio'] if "Salida" in tipo else 0
                conn.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado) VALUES (?,?,?,?,?,?)", (item['id'], tipo, ct, hoy, cc, val))
                f = 1 if tipo == "Entrada" else -1; conn.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (ct*f, item['id']))
                conn.commit(); guardar_en_drive(); st.rerun()
    with tb4:
        cc_sel = st.selectbox("Cuartel", CENTROS_COSTO); h1, h2 = st.date_input("Desde ", hoy-timedelta(days=365)), st.date_input("Hasta ", hoy)
        df_cc = pd.read_sql_query(f"SELECT m.fecha, i.producto, m.tipo, m.cantidad, m.valor_imputado FROM movimientos m JOIN inventario i ON m.producto_id = i.id WHERE UPPER(TRIM(m.centro_costo)) = '{cc_sel.upper()}' AND m.fecha BETWEEN '{h1}' AND '{h2}' ORDER BY m.fecha DESC", conn)
        if not df_cc.empty: st.dataframe(df_cc.style.format({"cantidad": "{:,.2f}", "valor_imputado": "${:,.0f}"}), use_container_width=True)
    conn.close()

def modulo_costos():
    st.header("💰 Costos")
    conn = conectar_db(); query = """
    SELECT UPPER(TRIM(centro_costo)) as cc, SUM(CASE WHEN fuente = 'BODEGA' THEN val ELSE 0 END) as insumos, SUM(CASE WHEN fuente = 'FACTURA' THEN val ELSE 0 END) as gastos, SUM(val) as total
    FROM (SELECT centro_costo, valor_imputado as val, 'BODEGA' as fuente FROM movimientos WHERE tipo LIKE 'Salida%' UNION ALL SELECT centro_costo, monto_imputado as val, 'FACTURA' as fuente FROM facturas WHERE tipo = 'Gasto Vario') WHERE cc != '' GROUP BY cc """
    df_t = pd.read_sql_query(query, conn); conn.close()
    if not df_t.empty:
        df_total = pd.DataFrame([{"cc": "TOTAL GENERAL", "insumos": df_t["insumos"].sum(), "gastos": df_t["gastos"].sum(), "total": df_t["total"].sum()}])
        df_res = pd.concat([df_t, df_total], ignore_index=True)
        st.dataframe(df_res.style.apply(lambda r: ['font-weight: bold; background-color: #f1f8e9' if r['cc'] == "TOTAL GENERAL" else '' for _ in r], axis=1).format({"insumos": "${:,.0f}", "gastos": "${:,.0f}", "total": "${:,.0f}"}), use_container_width=True)

# --- NAVEGACIÓN ---
st.set_page_config(page_title="LA CONCEPCIÓN ERP", layout="wide")
inicializar_db()
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if not st.session_state['logged_in']: login_page()
else:
    if 'init' not in st.session_state: descargar_de_drive(); st.session_state['init'] = True
    with st.sidebar:
        st.title("MENÚ")
        if obtener_drive(): st.markdown("🟢 **Drive: CONECTADO**")
        menu = st.radio("", ["🏠 Dashboard", "📦 Compras", "💸 Tesorería", "🚜 Bodega", "💰 COSTOS"])
        if st.button("🚀 Sincronizar"): guardar_en_drive()
        if st.button("🚪 Salir"): st.session_state.clear(); st.rerun()
    if menu == "🏠 Dashboard": modulo_dashboard()
    elif menu == "📦 Compras": modulo_compras()
    elif menu == "💸 Tesorería": modulo_tesoreria()
    elif menu == "🚜 Bodega": modulo_bodega()
    elif menu == "💰 COSTOS": modulo_costos()
