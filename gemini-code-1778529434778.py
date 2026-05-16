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

# --- 1. CONFIGURACIÓN, CONSTANTES Y ESTADOS ---
ID_CARPETA_DRIVE = "12tjxWa_RVRP5YuYd2sypjBO8bPuyMqo6" 
NOMBRE_DB = 'erp_concepcion_v6.db'
CLAVE_MAESTRA = "2908" 
hoy = datetime.now().date()

FAMILIAS_PRODUCTOS = ["FERTILIZANTE", "FERTILIZANTE FOLIAR", "HERBICIDA", "INSECTICIDA", "FUNGICIDA", "BIO ESTIMULANTE", "ACARICIDA", "REGULADOR DE CRECIMIENTO", "ADHERENTE / MOJANTE", "OTROS"]
CENTROS_COSTO = ["CEREZOS CORTE1", "CEREZOS CORTE2", "CIRUELOS", "NOGALES APARICION", "NOGALES CRUZ DEL SUR", "EL ESPINO", "OTROS"]

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
    cursor.execute("""CREATE TABLE IF NOT EXISTS log_accesos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, fecha_hora DATETIME)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS petroleo (
        id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT, litros REAL, proveedor TEXT, 
        monto_total_compra REAL, vehiculo TEXT, responsable TEXT, centro_costo TEXT, fecha DATE, valor_imputado REAL)""")
    
    usuarios = [
        ('osvaldolira@laconcepcion.cl', hash_password('9083')),
        ('secretaria@laconcepcion.cl', hash_password('9111')),
        ('secretarialaconcepcion2@gmail.com', hash_password('5678'))
    ]
    cursor.execute("DELETE FROM usuarios") 
    for email, pw in usuarios:
        cursor.execute("INSERT INTO usuarios (email, password) VALUES (?,?)", (email, pw))
    conn.commit(); conn.close()

# --- 3. UTILIDADES Y REPORTES PDF ---
def f_puntos(v):
    try: return f"{int(round(float(v))):,}".replace(",", ".")
    except: return "0"

def f_decimal(v):
    try: return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return "0,00"

def generar_pdf_blob(df, titulo, incluir_precios=True):
    try:
        pdf = FPDF(); pdf.add_page(); pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, "AGRICOLA LA CONCEPCIÓN", ln=True, align="C")
        pdf.set_font("Helvetica", "B", 12); pdf.cell(0, 10, titulo, ln=True, align="C")
        pdf.ln(5); pdf.set_font("Helvetica", "B", 8)
        columnas_finales = df.columns
        if not incluir_precios:
            columnas_finales = [c for c in df.columns if "precio" not in c.lower() and "valor" not in c.lower() and "monto" not in c.lower()]
        df_pdf = df[columnas_finales]
        cols = df_pdf.columns; w = 190 / len(cols)
        for col in cols: pdf.cell(w, 8, str(col).upper(), border=1, align="C")
        pdf.ln(); pdf.set_font("Helvetica", "", 7); total_acum = 0
        for _, row in df_pdf.iterrows():
            for i, item in enumerate(row):
                col_name = df_pdf.columns[i].lower()
                if any(x in col_name for x in ["monto", "total", "valor", "imputado"]):
                    try: total_acum += float(item)
                    except: pass
                if any(x in col_name for x in ["cantidad", "stock", "litros"]): val = f_decimal(item)
                elif any(x in col_name for x in ["monto", "total", "precio", "valor"]): val = f_puntos(item)
                else: val = str(item)
                pdf.cell(w, 7, val[:25], border=1)
            pdf.ln()
        if incluir_precios and total_acum > 0:
            pdf.set_font("Helvetica", "B", 9); pdf.cell(w * (len(cols)-1), 8, "TOTAL FINAL:", border=1, align="R")
            pdf.cell(w, 8, f"${f_puntos(total_acum)}", border=1, align="L")
        return pdf.output(dest="S").encode("latin-1")
    except: return None

# --- 4. INTEGRACIÓN GOOGLE DRIVE ---
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
        st.success("✅ Respaldo en Drive sincronizado.")

def descargar_de_drive():
    drive = obtener_drive()
    if drive:
        query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
        lista = drive.ListFile({'q': query}).GetList()
        if lista: lista[0].GetContentFile(NOMBRE_DB)

# --- 5. ESTILOS CSS PERSONALIZADOS (MODO DINÁMICO) ---
def inyectar_css():
    css = """
        <style>
        .main { background-color: #f4f7f6; }
        [data-testid="stMetricValue"] { font-size: 1.8rem !important; }
        .custom-metric { background-color: white; padding: 15px; border-radius: 12px; border-left: 6px solid #2E7D32; box-shadow: 0 4px 6px rgba(0,0,0,0.05); min-height: 100px; }
        .metric-label { font-size: 0.8rem; color: #666; font-weight: bold; text-transform: uppercase; }
        .metric-value { font-size: 1.8rem; font-weight: bold; display: block; }
        h1, h2, h3 { color: #1B5E20; font-family: 'Arial'; }
        .stButton>button { border-radius: 8px; background-color: #2E7D32; color: white; font-weight: bold; width: 100%; }
        .stTabs [data-baseweb="tab-list"] { gap: 10px; }
        .stTabs [data-baseweb="tab"] { background-color: #e8f5e9; border-radius: 5px 5px 0 0; padding: 10px 20px; }
        </style>
    """
    st.markdown(css, unsafe_allow_html=True)
    if st.session_state.get('logged_in') and st.session_state.get('email') != 'osvaldolira@laconcepcion.cl':
        st.markdown("""<style>header {visibility: hidden;} #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display:none;}</style>""", unsafe_allow_html=True)

# --- 6. PÁGINA DE LOGIN ---
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
                    cursor.execute("INSERT INTO log_accesos (email, fecha_hora) VALUES (?,?)", (e, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                    conn.commit(); conn.close()
                    st.session_state['logged_in'] = True; st.session_state['email'] = e; st.rerun()
                else: conn.close(); st.error("Email o clave incorrectos.")

# --- 7. MÓDULO DASHBOARD ---
def modulo_dashboard():
    inyectar_css()
    st.markdown("<h1>🏠 Dashboard Informativo</h1>", unsafe_allow_html=True)
    conn = conectar_db()
    df_f_reales = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente' AND nro_documento NOT LIKE '%_P'", conn)
    df_p_c = pd.read_sql_query("SELECT SUM(litros) as l FROM petroleo WHERE tipo='Carga'", conn)
    df_p_s = pd.read_sql_query("SELECT SUM(litros) as l FROM petroleo WHERE tipo='Salida'", conn)
    saldo_pet = (df_p_c['l'].fillna(0).iloc[0]) - (df_p_s['l'].fillna(0).iloc[0])
    
    t_d = df_f_reales['monto_total'].sum() if not df_f_reales.empty else 0
    v_a = df_f_reales[pd.to_datetime(df_f_reales['fecha_vencimiento']).dt.date < hoy.replace(day=1)]['monto_total'].sum() if not df_f_reales.empty else 0
    v_h = len(df_f_reales[pd.to_datetime(df_f_reales['fecha_vencimiento']).dt.date < hoy])
    
    c1, c2, c3, c4, c5 = st.columns([1.5, 1.5, 1, 1, 1])
    with c1: st.markdown(f"<div class='custom-metric'><span class='metric-label'>DEUDA TOTAL</span><span class='metric-value'>${f_puntos(t_d)}</span></div>", unsafe_allow_html=True)
    with c2: st.markdown(f"<div class='custom-metric'><span class='metric-label'>MESES ANTERIORES</span><span class='metric-value' style='color:red;'>${f_puntos(v_a)}</span><span style='color:red; font-size:0.7rem; font-weight:bold;'>⚠️ CRÍTICO</span></div>", unsafe_allow_html=True)
    with c3: st.markdown(f"<div class='custom-metric'><span class='metric-label'>VENCIDAS</span><span class='metric-value' style='color:orange;'>{v_h}</span></div>", unsafe_allow_html=True)
    with c4: st.markdown(f"<div class='custom-metric'><span class='metric-label'>PENDIENTES</span><span class='metric-value'>{len(df_f_reales)}</span></div>", unsafe_allow_html=True)
    with c5: st.markdown(f"<div class='custom-metric'><span class='metric-label'>PETRÓLEO</span><span class='metric-value'>{f_decimal(saldo_pet)}L</span></div>", unsafe_allow_html=True)
    
    st.divider()
    col1, col2 = st.columns([1.6, 1])
    with col1:
        st.subheader("💰 Resumen Costos por Cuartel")
        query_cc = """SELECT UPPER(TRIM(centro_costo)) as cc, SUM(monto_imputado) as total_neto 
                      FROM (SELECT centro_costo, valor_imputado as monto_imputado FROM movimientos WHERE tipo LIKE 'Salida%' 
                      UNION ALL SELECT centro_costo, monto_imputado FROM facturas WHERE tipo = 'Gasto Vario' AND centro_costo != '' 
                      UNION ALL SELECT centro_costo, valor_imputado as monto_imputado FROM petroleo WHERE tipo = 'Salida') 
                      WHERE cc IS NOT NULL AND cc != '' GROUP BY cc"""
        df_c = pd.read_sql_query(query_cc, conn)
        if not df_c.empty: st.dataframe(df_c.style.format({"total_neto": "${:,.0f}"}), use_container_width=True)
    with col2:
        st.subheader("📅 Vencimientos (4 Meses)")
        meses_n = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
        for i in range(4):
            f_p = (datetime.now().replace(day=1) + timedelta(days=i*31)).replace(day=1)
            total_m = df_f_reales[(pd.to_datetime(df_f_reales['fecha_vencimiento']).dt.month == f_p.month) & (pd.to_datetime(df_f_reales['fecha_vencimiento']).dt.year == f_p.year)]['monto_total'].sum() if not df_f_reales.empty else 0
            st.markdown(f"<div style='background:white; padding:10px; border-radius:10px; margin-bottom:5px; display:flex; justify-content:space-between; border:1px solid #ddd;'><b>{meses_n[f_p.month-1]} {f_p.year}</b> <span style='color:#2E7D32;'>${f_puntos(total_m)}</span></div>", unsafe_allow_html=True)
    conn.close()

# --- 8. MÓDULO PETRÓLEO ---
def modulo_petroleo():
    st.header("⛽ Gestión de Petróleo")
    tp1, tp2, tp3 = st.tabs(["📥 Carga (Compra)", "🚜 Salida (Consumo)", "📊 Historial"]); conn = conectar_db()
    
    df_c = pd.read_sql_query("SELECT SUM(litros) as l, SUM(monto_total_compra) as m FROM petroleo WHERE tipo='Carga'", conn)
    df_s = pd.read_sql_query("SELECT SUM(litros) as l FROM petroleo WHERE tipo='Salida'", conn)
    saldo = (df_c['l'].fillna(0).iloc[0]) - (df_s['l'].fillna(0).iloc[0])
    pmp_p = (df_c['m'].fillna(0).iloc[0] / df_c['l'].fillna(1).iloc[0]) if df_c['l'].fillna(0).iloc[0] > 0 else 0
    st.sidebar.metric("ESTANQUE", f"{f_decimal(saldo)} Lts")
    
    with tp1:
        with st.form("p_c"):
            lts = st.number_input("Litros", 0.0); prov = st.text_input("Proveedor"); mt = st.number_input("Total ($)", 0.0); f = st.date_input("Fecha", hoy)
            if st.form_submit_button("💾 REGISTRAR CARGA"):
                conn.execute("INSERT INTO petroleo (tipo, litros, proveedor, monto_total_compra, fecha) VALUES (?,?,?,?,?)", ("Carga", lts, prov, mt, f))
                conn.commit(); guardar_en_drive(); st.rerun()
    with tp2:
        with st.form("p_s"):
            lts_s = st.number_input("Litros ", 0.0); veh = st.text_input("Vehículo"); res = st.text_input("Responsable"); f_s = st.date_input("Fecha ", hoy)
            cols = st.columns(3); ccs = []
            for i, c_n in enumerate(CENTROS_COSTO):
                if cols[i%3].checkbox(c_n, key=f"ps_{c_n}"): ccs.append(c_n)
            if st.form_submit_button("⛽ REGISTRAR SALIDA"):
                if lts_s > 0 and ccs and lts_s <= saldo:
                    for c in ccs: conn.execute("INSERT INTO petroleo (tipo, litros, vehiculo, responsable, centro_costo, fecha, valor_imputado) VALUES (?,?,?,?,?,?,?)", ("Salida", lts_s/len(ccs), veh, res, c.upper(), f_s, (lts_s*pmp_p)/len(ccs)))
                    conn.commit(); guardar_en_drive(); st.rerun()
    with tp3:
        df_p = pd.read_sql_query("SELECT id, fecha, tipo, litros, proveedor, vehiculo, responsable, centro_costo FROM petroleo ORDER BY id DESC", conn)
        st.dataframe(df_p.style.format({"litros": "{:,.2f}"}), use_container_width=True)
        col_pdf, col_mod = st.columns([1, 2.5])
        with col_pdf: st.download_button("📥 PDF Historial", generar_pdf_blob(df_p.drop(columns=['id']), "HISTORIAL MOVIMIENTOS PETRÓLEO", True), "petroleo.pdf")
        with col_mod:
            st.subheader("🛠️ Gestión")
            id_p = st.selectbox("Seleccione ID", df_p['id'])
            sel_p = df_p[df_p['id'] == id_p].iloc[0]
            cl = st.text_input("Clave Maestra ", type="password", key="cl_p")
            b1, b2 = st.columns(2)
            if b1.button("💾 MODIFICAR") and cl == CLAVE_MAESTRA:
                st.info("Función de edición habilitada en base de datos.")
            if b2.button("🗑️ ELIMINAR REGISTRO") and cl == CLAVE_MAESTRA:
                conn.execute("DELETE FROM petroleo WHERE id=?", (id_p,))
                conn.commit(); guardar_en_drive(); st.rerun()
    conn.close()

# --- 9. MÓDULO COMPRAS (v10.8.38 - RANGO FECHAS Y PDF HISTORIAL) ---
def modulo_compras():
    st.header("📦 Gestión de Compras")
    t1, t2, t3 = st.tabs(["➕ Factura Insumos", "💸 Gasto Vario", "🔍 Historial / Gestión"]); conn = conectar_db()
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
                conn.commit(); guardar_en_drive(); st.rerun()
    with t2:
        prov_g, nro_g = st.text_input("Proveedor ", key="pg"), st.text_input("N° Doc ", key="ng")
        cf1, cf2 = st.columns(2); fe_g, fv_g = cf1.date_input("Fecha Compra", hoy), cf2.date_input("Fecha Vencimiento", hoy)
        detalles_g = st.text_area("Concepto"); ccs_sel = []; cols = st.columns(3)
        for i, cc in enumerate(CENTROS_COSTO):
            if cols[i%3].checkbox(cc, key=f"gv_{cc}"): ccs_sel.append(cc)
        mt_iva = st.number_input("Monto Total (IVA)", 0.0); iva_c = st.radio("¿Imputar TOTAL?", ["SÍ", "NO (NETO)"])
        if st.button("💾 GUARDAR GASTO VARIO"):
            if mt_iva > 0:
                m_imp = mt_iva if iva_c == "SÍ" else (mt_iva/1.19)
                if ccs_sel:
                    conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, concepto) VALUES (?,?,?,?,?,?,?)", (nro_g, prov_g, fe_g, fv_g, mt_iva, 'Gasto Vario', detalles_g))
                    for c in ccs_sel: conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, centro_costo, monto_imputado, concepto) VALUES (?,?,?,?,?,?,?,?,?)", (nro_g+"_P", prov_g, fe_g, fv_g, 0, 'Gasto Vario', c.upper(), m_imp/len(ccs_sel), detalles_g))
                else: conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, concepto, centro_costo, monto_imputado) VALUES (?,?,?,?,?,?,?,?,?)", (nro_g, prov_g, fe_g, fv_g, mt_iva, 'Gasto Vario', detalles_g, "CONTABILIDAD GENERAL", 0))
                conn.commit(); guardar_en_drive(); st.rerun()
    with t3:
        # --- NUEVA LÓGICA: RANGO DE FECHAS DINÁMICO ---
        df_all = pd.read_sql_query("SELECT MIN(fecha_compra) as min_f, MAX(fecha_compra) as max_f FROM facturas WHERE monto_total > 0", conn)
        f_min_def = pd.to_datetime(df_all['min_f'].iloc[0]).date() if df_all['min_f'].iloc[0] else hoy
        f_max_def = pd.to_datetime(df_all['max_f'].iloc[0]).date() if df_all['max_f'].iloc[0] else hoy
        
        c_f1, c_f2 = st.columns(2)
        desde = c_f1.date_input("Desde", f_min_def)
        hasta = c_f2.date_input("Hasta", f_max_def)
        
        query_h = f"SELECT id, nro_documento, proveedor, fecha_compra, monto_total, estado FROM facturas WHERE monto_total > 0 AND fecha_compra BETWEEN '{desde}' AND '{hasta}' ORDER BY fecha_compra ASC"
        df_h = pd.read_sql_query(query_h, conn)
        
        st.dataframe(df_h.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
        
        # --- BOTÓN PDF HISTORIAL ---
        if not df_h.empty:
            st.download_button("📥 Generar PDF Historial Compras", generar_pdf_blob(df_h.drop(columns=['id']), f"HISTORIAL DE COMPRAS ({desde} al {hasta})", True), "historial_compras.pdf")
            st.divider()
            id_d = st.selectbox("ID a gestionar", df_h['id']); sel = df_h[df_h['id']==id_d].iloc[0]
            cl = st.text_input("Clave Maestra", type="password", key="cl_h")
            if st.button("🗑️ ELIMINAR DOCUMENTO") and cl == CLAVE_MAESTRA:
                conn.execute("DELETE FROM facturas WHERE id=?", (id_d,))
                conn.commit(); guardar_en_drive(); st.rerun()
    conn.close()

# --- 10. MÓDULO TESORERÍA ---
def modulo_tesoreria():
    st.header("💸 Cuentas por Pagar")
    tp1, tp2 = st.tabs(["🔴 Pendientes", "🏢 Por Proveedor"]); conn = conectar_db()
    with tp1:
        df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' AND nro_documento NOT LIKE '%_P' AND monto_total > 0 ORDER BY fecha_vencimiento ASC", conn)
        st.info(f"### DEUDA PENDIENTE: ${f_puntos(df_p['monto_total'].sum())}")
        if not df_p.empty:
            def style_v(row): return ['background-color: #ffcccc' if pd.to_datetime(row['fecha_vencimiento']).date() < hoy else '' for _ in row]
            st.dataframe(df_p.style.apply(style_v, axis=1).format({"monto_total": "${:,.0f}"}), use_container_width=True)
            st.download_button("📥 PDF Pendientes", generar_pdf_blob(df_p.drop(columns=['id']), "LISTADO PENDIENTES DE PAGO", True), "pendientes.pdf")
            st.divider()
            id_p = st.selectbox("ID Factura a Pagar", df_p['id']); met = st.selectbox("Método", ["Transferencia", "Efectivo", "Cheque"])
            if st.button("💰 MARCAR COMO PAGADO"):
                conn.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (met, hoy, id_p))
                conn.commit(); guardar_en_drive(); st.rerun()
    with tp2:
        df_provs = pd.read_sql_query("SELECT DISTINCT proveedor FROM facturas WHERE estado='Pendiente' AND monto_total > 0", conn)
        if not df_provs.empty:
            ps = st.selectbox("Seleccione Proveedor", df_provs['proveedor'])
            df_d = pd.read_sql_query(f"SELECT nro_documento, fecha_vencimiento, monto_total FROM facturas WHERE proveedor='{ps}' AND estado='Pendiente' AND nro_documento NOT LIKE '%_P'", conn)
            st.success(f"### DEUDA CON {ps}: ${f_puntos(df_d['monto_total'].sum())}")
            st.dataframe(df_d.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
            st.download_button(f"📥 PDF {ps}", generar_pdf_blob(df_d, f"ESTADO DE DEUDA: {ps}", True), f"deuda_{ps}.pdf")
    conn.close()

# --- 11. MÓDULO BODEGA ---
def modulo_bodega():
    st.header("🚜 Control de Inventario")
    tb1, tb2, tb3, tb4 = st.tabs(["📊 Stock", "🔄 Movimientos", "➕ Nuevo", "🔍 Consulta CC"]); conn = conectar_db()
    with tb1:
        df_s = pd.read_sql_query("SELECT id, producto, familia, stock, precio_medio FROM inventario ORDER BY producto ASC", conn)
        st.dataframe(df_s.drop(columns=['id']).style.format({"stock": "{:,.2f}", "precio_medio": "${:,.0f}"}), use_container_width=True)
        c_p1, c_p2 = st.columns(2)
        if not df_s.empty:
            with c_p1: st.download_button("📥 Stock Admin", generar_pdf_blob(df_s.drop(columns=['id']), "INVENTARIO VALORIZADO", True), "stock_admin.pdf")
            with c_p2: st.download_button("📥 Stock Lista", generar_pdf_blob(df_s.drop(columns=['id']), "LISTADO DE STOCK TRABAJO", False), "stock_lista.pdf")
    with tb2:
        tipo = st.radio("Acción", ["Salida (Campo)", "Entrada"])
        df_i = pd.read_sql_query("SELECT id, producto, precio_medio FROM inventario", conn)
        ps = st.selectbox("Insumo ", df_i['id'].astype(str) + " - " + df_i['producto']) if not df_i.empty else None; ct = st.number_input("Cant", 0.0); ccs = []
        if tipo == "Salida (Campo)":
            cols = st.columns(3)
            for i, c_n in enumerate(CENTROS_COSTO):
                if cols[i%3].checkbox(c_n, key=f"mb_{c_n}"): ccs.append(c_n)
        if st.button("🔄 PROCESAR MOVIMIENTO"):
            iid = int(ps.split(" - ")[0]); pmp = df_i[df_i['id']==iid]['precio_medio'].values[0]
            if tipo == "Salida (Campo)" and ccs:
                for c in ccs: conn.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado) VALUES (?,?,?,?,?,?)", (iid, tipo, ct/len(ccs), hoy, c.upper(), (ct*pmp)/len(ccs)))
                conn.execute("UPDATE inventario SET stock = stock - ? WHERE id = ?", (ct, iid))
            else: conn.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (ct, iid))
            conn.commit(); guardar_en_drive(); st.rerun()
    with tb3:
        with st.form("n_p"):
            nom, fam, st_i, pr_i = st.text_input("Nombre"), st.selectbox("Familia", FAMILIAS_PRODUCTOS), st.number_input("Stock Inicial", 0.0), st.number_input("PMP", 0.0)
            if st.form_submit_button("➕ CREAR"):
                conn.execute("INSERT INTO inventario (producto, familia, stock, precio_medio) VALUES (?,?,?,?)", (nom, fam, st_i, pr_i))
                conn.commit(); guardar_en_drive(); st.rerun()
    with tb4:
        cc_s = st.selectbox("Cuartel", CENTROS_COSTO)
        st.dataframe(pd.read_sql_query(f"SELECT m.fecha, i.producto, m.tipo, m.cantidad, m.valor_imputado FROM movimientos m JOIN inventario i ON m.producto_id = i.id WHERE m.centro_costo = '{cc_s.upper()}' ORDER BY m.fecha DESC", conn), use_container_width=True)
    conn.close()

# --- 12. MÓDULO COSTOS ---
def modulo_costos():
    st.header("💰 Informe de Costos por Cuartel")
    conn = conectar_db()
    query = """SELECT UPPER(TRIM(centro_costo)) as cc, SUM(CASE WHEN fuente = 'BODEGA' THEN val ELSE 0 END) as insumos, SUM(CASE WHEN fuente = 'FACTURA' THEN val ELSE 0 END) as gastos, SUM(CASE WHEN fuente = 'PETROLEO' THEN val ELSE 0 END) as combustible, SUM(val) as total FROM (SELECT centro_costo, valor_imputado as val, 'BODEGA' as fuente FROM movimientos WHERE tipo LIKE 'Salida%' UNION ALL SELECT centro_costo, monto_imputado as val, 'FACTURA' as fuente FROM facturas WHERE tipo = 'Gasto Vario' AND centro_costo != '' AND centro_costo != 'CONTABILIDAD GENERAL' UNION ALL SELECT centro_costo, valor_imputado as val, 'PETROLEO' as fuente FROM petroleo WHERE tipo = 'Salida') GROUP BY cc"""
    df_t = pd.read_sql_query(query, conn); conn.close()
    if not df_t.empty: st.dataframe(df_t.style.format({"total": "${:,.0f}"}), use_container_width=True)

# --- NAVEGACIÓN ---
st.set_page_config(page_title="ERP LA CONCEPCIÓN v10.8.38", layout="wide")
inicializar_db()
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if not st.session_state['logged_in']: login_page()
else:
    if 'init' not in st.session_state: descargar_de_drive(); st.session_state['init'] = True
    with st.sidebar:
        st.title("MENÚ")
        if obtener_drive(): st.markdown("🟢 **Drive: CONECTADO**")
        menu = st.radio("", ["🏠 Dashboard", "⛽ PETRÓLEO", "📦 Compras", "💸 Tesorería", "🚜 Bodega", "💰 COSTOS"])
        if st.session_state['email'] == 'osvaldolira@laconcepcion.cl':
            if st.button("🚀 Sincronizar Drive"): guardar_en_drive()
        if st.button("🚪 Salir"): st.session_state.clear(); st.rerun()
    if menu == "🏠 Dashboard": modulo_dashboard()
    elif menu == "⛽ PETRÓLEO": modulo_petroleo()
    elif menu == "📦 Compras": modulo_compras()
    elif menu == "💸 Tesorería": modulo_tesoreria()
    elif menu == "🚜 Bodega": modulo_bodega()
    elif menu == "💰 COSTOS": modulo_costos()
