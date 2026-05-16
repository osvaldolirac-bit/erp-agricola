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

def registrar_accion(accion, detalle):
    """Guarda movimiento en la bitácora de auditoría (v10.8.43)"""
    user = st.session_state.get('email', 'Desconocido')
    fecha = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        conn = conectar_db()
        conn.execute("INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)", 
                     (user, accion, detalle, fecha))
        conn.commit()
        conn.close()
    except: pass

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
    cursor.execute("""CREATE TABLE IF NOT EXISTS bitacora (
        id INTEGER PRIMARY KEY AUTOINCREMENT, usuario TEXT, accion TEXT, detalle TEXT, fecha_hora DATETIME)""")
    
    usuarios = [
        ('osvaldolira@laconcepcion.cl', hash_password('9083')),
        ('secretaria@laconcepcion.cl', hash_password('9111')),
        ('secretarialaconcepcion2@gmail.com', hash_password('5678'))
    ]
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    if cursor.fetchone()[0] == 0:
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
        df_pdf = df.copy()
        if not incluir_precios:
            cols_to_drop = [c for c in df_pdf.columns if any(x in c.lower() for x in ["precio", "valor", "monto", "total"])]
            df_pdf = df_pdf.drop(columns=cols_to_drop)
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

# --- 4. DRIVE ---
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

# --- 5. ESTILOS CSS ---
def inyectar_css():
    st.markdown("""<style>
        .main { background-color: #f4f7f6; }
        [data-testid="stMetricValue"] { font-size: 1.8rem !important; }
        .custom-metric { background-color: white; padding: 15px; border-radius: 12px; border-left: 6px solid #2E7D32; box-shadow: 0 4px 6px rgba(0,0,0,0.05); min-height: 100px; }
        .metric-label { font-size: 0.8rem; color: #666; font-weight: bold; text-transform: uppercase; }
        .metric-value { font-size: 1.8rem; font-weight: bold; display: block; }
        h1, h2, h3 { color: #1B5E20; font-family: 'Arial'; }
        .stButton>button { border-radius: 8px; background-color: #2E7D32; color: white; font-weight: bold; width: 100%; }
        .stTabs [data-baseweb="tab"] { background-color: #e8f5e9; padding: 10px 20px; }
        </style>""", unsafe_allow_html=True)
    if st.session_state.get('logged_in') and st.session_state.get('email') != 'osvaldolira@laconcepcion.cl':
        st.markdown("""<style>header {visibility: hidden;} #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display:none;}</style>""", unsafe_allow_html=True)

# --- 6. LOGIN ---
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
    st.markdown("<h1 style='color: #1B5E20;'>🚜 ERP Agrícola La Concepción</h1>", unsafe_allow_html=True)
    
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
        st.subheader("📅 Vencimientos Proyectados")
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
            lts, prov, mt, f = st.number_input("Litros", 0.0), st.text_input("Proveedor"), st.number_input("Total ($)", 0.0), st.date_input("Fecha", hoy)
            if st.form_submit_button("REGISTRAR CARGA"):
                conn.execute("INSERT INTO petroleo (tipo, litros, proveedor, monto_total_compra, fecha) VALUES (?,?,?,?,?)", ("Carga", lts, prov, mt, f))
                conn.commit(); registrar_accion("CARGA PETROLEO", f"{lts}L de {prov}"); guardar_en_drive(); st.rerun()
    with tp2:
        with st.form("p_s"):
            lts_s, veh, res, f_s = st.number_input("Litros ", 0.0), st.text_input("Vehículo"), st.text_input("Responsable"), st.date_input("Fecha ", hoy)
            cols = st.columns(3); ccs = []
            for i, c_n in enumerate(CENTROS_COSTO):
                if cols[i%3].checkbox(c_n, key=f"ps_{c_n}"): ccs.append(c_n)
            if st.form_submit_button("REGISTRAR SALIDA"):
                if lts_s > 0 and ccs and lts_s <= saldo:
                    for c in ccs: conn.execute("INSERT INTO petroleo (tipo, litros, vehiculo, responsable, centro_costo, fecha, valor_imputado) VALUES (?,?,?,?,?,?,?)", ("Salida", lts_s/len(ccs), veh, res, c.upper(), f_s, (lts_s*pmp_p)/len(ccs)))
                    conn.commit(); registrar_accion("SALIDA PETROLEO", f"{lts_s}L para {veh}"); guardar_en_drive(); st.rerun()
    with tp3:
        df_p = pd.read_sql_query("SELECT id, fecha, tipo, litros, proveedor, vehiculo, responsable, centro_costo FROM petroleo ORDER BY id DESC", conn)
        st.dataframe(df_p.style.format({"litros": "{:,.2f}"}), use_container_width=True)
        st.download_button("📥 PDF Historial", generar_pdf_blob(df_p.drop(columns=['id']), "HISTORIAL PETROLEO"), "petroleo.pdf")
        col_m1, col_m2 = st.columns(2); id_p = col_m1.selectbox("ID a gestionar", df_p['id']); cl = col_m2.text_input("Clave Maestra", type="password", key="p_cl")
        b1, b2 = st.columns(2)
        if b1.button("✏️ MODIFICAR") and cl == CLAVE_MAESTRA:
             registrar_accion("MODIFICAR PETROLEO", f"ID {id_p}")
             st.info("Modificación habilitada.")
        if b2.button("🗑️ ELIMINAR") and cl == CLAVE_MAESTRA:
            conn.execute("DELETE FROM petroleo WHERE id=?", (id_p,))
            conn.commit(); registrar_accion("ELIMINAR PETROLEO", f"ID {id_p}"); guardar_en_drive(); st.rerun()
    conn.close()

# --- 9. MÓDULO COMPRAS ---
def modulo_compras():
    st.header("📦 Gestión de Compras")
    t1, t2, t3 = st.tabs(["➕ Factura Insumos", "💸 Gasto Vario", "🔍 Historial / Gestión"]); conn = conectar_db()
    with t1:
        c1, c2 = st.columns(2); nro, prov = c1.text_input("N°"), c1.text_input("Proveedor"); fe, fv = c2.date_input("Emisión"), c2.date_input("Vencimiento")
        df_i = pd.read_sql_query("SELECT id, producto, stock, precio_medio FROM inventario", conn)
        cp1, cp2, cp3, cp4 = st.columns([3,1,1,1]); ps = cp1.selectbox("Insumo", df_i['id'].astype(str) + " - " + df_i['producto']) if not df_i.empty else None
        ct, pr = cp2.number_input("Cant", 0.0), cp3.number_input("Neto", 0.0)
        if cp4.button("➕ Añadir"):
            if 'car' not in st.session_state: st.session_state['car'] = []
            st.session_state['car'].append({'id': int(ps.split(" - ")[0]), 'n': ps.split(" - ")[1], 'c': ct, 'p': pr, 't': ct*pr}); st.rerun()
        if st.session_state.get('car'):
            df_car = pd.DataFrame(st.session_state['car']); st.table(df_car)
            if st.button("💾 GUARDAR FACTURA"):
                total = df_car['t'].sum() * 1.19
                conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total) VALUES (?,?,?,?,?)", (nro, prov, fe, fv, total))
                for i in st.session_state['car']:
                    cur = conn.execute("SELECT stock, precio_medio FROM inventario WHERE id=?", (i['id'],)).fetchone()
                    n_pmp = ((cur[0]*cur[1]) + (i['c']*i['p'])) / (cur[0]+i['c']) if (cur[0]+i['c']) > 0 else i['p']
                    conn.execute("UPDATE inventario SET stock = stock + ?, precio_medio = ? WHERE id = ?", (i['c'], n_pmp, i['id']))
                conn.commit(); registrar_accion("FACTURA INSUMOS", f"{nro} de {prov}"); st.session_state['car'] = []; guardar_en_drive(); st.rerun()
    with t2:
        pg, ng = st.text_input("Proveedor ", key="pg"), st.text_input("N° Doc ", key="ng")
        fg1, fg2 = st.date_input("Fecha Compra", hoy), st.date_input("Fecha Vencimiento", hoy)
        det = st.text_area("Concepto"); sel_cc = []
        cols = st.columns(3)
        for i, cc in enumerate(CENTROS_COSTO):
            if cols[i%3].checkbox(cc, key=f"gv_{cc}"): sel_cc.append(cc)
        mt = st.number_input("Total (IVA)", 0.0); iva = st.radio("¿Imputar Total?", ["SÍ", "NO (NETO)"])
        if st.button("💾 GUARDAR GASTO VARIO"):
            imp = mt if iva == "SÍ" else mt/1.19
            if sel_cc:
                conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, concepto) VALUES (?,?,?,?,?,?,?)", (ng, pg, fg1, fg2, mt, 'Gasto Vario', det))
                for c in sel_cc: conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, centro_costo, monto_imputado, concepto) VALUES (?,?,?,?,?,?,?,?,?)", (ng+"_P", pg, fg1, fg2, 0, 'Gasto Vario', c.upper(), imp/len(sel_cc), det))
            else: conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, concepto, centro_costo, monto_imputado) VALUES (?,?,?,?,?,?,?,?,?)", (ng, pg, fg1, fg2, mt, 'Gasto Vario', det, "SIN CC", 0))
            conn.commit(); registrar_accion("GASTO VARIO", f"{ng} de {pg}"); guardar_en_drive(); st.rerun()
    with t3:
        df_lim = pd.read_sql_query("SELECT MIN(fecha_compra) as min_f, MAX(fecha_compra) as max_f FROM facturas", conn)
        f_min = pd.to_datetime(df_lim['min_f'].iloc[0]).date() if df_lim['min_f'].iloc[0] else hoy
        d1, d2 = st.date_input("Desde", f_min), st.date_input("Hasta", hoy)
        df_h = pd.read_sql_query(f"SELECT id, nro_documento, proveedor, fecha_compra, monto_total, estado FROM facturas WHERE monto_total > 0 AND fecha_compra BETWEEN '{d1}' AND '{d2}' ORDER BY fecha_compra ASC", conn)
        st.dataframe(df_h.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
        st.download_button("📥 PDF Historial", generar_pdf_blob(df_h.drop(columns=['id']), f"HISTORIAL {d1}-{d2}"), "historial.pdf")
        id_e = st.selectbox("ID factura", df_h['id']); cl = st.text_input("Master", type="password", key="cl_h")
        if st.button("🗑️ ELIMINAR") and cl == CLAVE_MAESTRA:
            conn.execute("DELETE FROM facturas WHERE id=? OR nro_documento LIKE ?", (id_e, f"%{id_e}%_P"))
            conn.commit(); registrar_accion("ELIMINAR FACTURA", f"ID {id_e}"); guardar_en_drive(); st.rerun()
    conn.close()

# --- 10. MÓDULO TESORERÍA ---
def modulo_tesoreria():
    st.header("💸 Cuentas por Pagar")
    tp1, tp2 = st.tabs(["🔴 Pendientes", "🏢 Proveedor"]); conn = conectar_db()
    with tp1:
        df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' AND nro_documento NOT LIKE '%_P' AND monto_total > 0 ORDER BY fecha_vencimiento ASC", conn)
        st.info(f"### DEUDA PENDIENTE: ${f_puntos(df_p['monto_total'].sum())}")
        st.dataframe(df_p.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
        id_pay = st.selectbox("ID a Pagar", df_p['id']); met = st.selectbox("Método", ["Transferencia", "Efectivo", "Cheque"])
        if st.button("💰 MARCAR COMO PAGADO"):
            conn.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (met, hoy, id_pay))
            conn.commit(); registrar_accion("PAGO", f"Factura ID {id_pay}"); guardar_en_drive(); st.rerun()
    with tp2:
        pr = st.selectbox("Seleccione Proveedor", pd.read_sql_query("SELECT DISTINCT proveedor FROM facturas WHERE estado='Pendiente'", conn)['proveedor'])
        df_pr = pd.read_sql_query(f"SELECT nro_documento, fecha_vencimiento, monto_total FROM facturas WHERE proveedor='{pr}' AND estado='Pendiente' AND nro_documento NOT LIKE '%_P'", conn)
        st.dataframe(df_pr.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
        st.download_button(f"📥 PDF Deuda {pr}", generar_pdf_blob(df_pr, f"DEUDA {pr}"), f"deuda_{pr}.pdf")
    conn.close()

# --- 11. MÓDULO BODEGA ---
def modulo_bodega():
    st.header("🚜 Gestión de Bodega")
    tb1, tb2, tb3, tb4 = st.tabs(["📊 Stock", "🔄 Salida", "➕ Nuevo", "🔍 Consulta CC"]); conn = conectar_db()
    with tb1:
        df_s = pd.read_sql_query("SELECT id, producto, familia, stock, precio_medio FROM inventario", conn)
        st.dataframe(df_s.drop(columns=['id']).style.format({"stock": "{:,.2f}", "precio_medio": "${:,.0f}"}), use_container_width=True)
        st.download_button("📥 PDF Admin", generar_pdf_blob(df_s, "INVENTARIO VALORIZADO", True), "stock_admin.pdf")
        st.download_button("📥 PDF Campo", generar_pdf_blob(df_s, "INVENTARIO CAMPO", False), "stock_campo.pdf")
    with tb2:
        df_i = pd.read_sql_query("SELECT id, producto, precio_medio FROM inventario", conn)
        ps = st.selectbox("Insumo", df_i['id'].astype(str) + " - " + df_i['producto']); ct = st.number_input("Cant", 0.0)
        sel_cc = []
        cols = st.columns(3)
        for i, c_n in enumerate(CENTROS_COSTO):
            if cols[i%3].checkbox(c_n, key=f"mb_{c_n}"): sel_cc.append(c_n)
        if st.button("🔄 REGISTRAR SALIDA"):
            iid = int(ps.split(" - ")[0]); p = df_i[df_i['id']==iid]['precio_medio'].iloc[0]
            if ct > 0 and sel_cc:
                for c in sel_cc: conn.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado) VALUES (?,?,?,?,?)", (iid, "Salida", ct/len(sel_cc), c.upper(), hoy, (ct*p)/len(sel_cc)))
                conn.execute("UPDATE inventario SET stock = stock - ? WHERE id = ?", (ct, iid))
                conn.commit(); registrar_accion("SALIDA BODEGA", f"{ct} de {ps}"); guardar_en_drive(); st.rerun()
    with tb3:
        with st.form("n"):
            nom, fam, si, pi = st.text_input("Nombre"), st.selectbox("Familia", FAMILIAS_PRODUCTOS), st.number_input("Stock", 0.0), st.number_input("PMP", 0.0)
            if st.form_submit_button("➕ CREAR INSUMO"):
                conn.execute("INSERT INTO inventario (producto, familia, stock, precio_medio) VALUES (?,?,?,?)", (nom, fam, si, pi))
                conn.commit(); registrar_accion("BODEGA NUEVO", nom); st.rerun()
    with tb4:
        cc_s = st.selectbox("Centro Costo", CENTROS_COSTO)
        st.dataframe(pd.read_sql_query(f"SELECT m.fecha, i.producto, m.tipo, m.cantidad, m.valor_imputado FROM movimientos m JOIN inventario i ON m.producto_id = i.id WHERE m.centro_costo = '{cc_s.upper()}' ORDER BY m.fecha DESC", conn), use_container_width=True)
    conn.close()

# --- 12. MÓDULO SEGURIDAD ---
def modulo_seguridad():
    st.header("🕵️ Auditoría")
    conn = conectar_db()
    t1, t2 = st.tabs(["📜 Bitácora", "🔑 Accesos"])
    with t1:
        df_b = pd.read_sql_query("SELECT * FROM bitacora ORDER BY id DESC", conn)
        st.dataframe(df_b, use_container_width=True)
        st.download_button("📥 Bitácora CSV", df_b.to_csv(index=False), "auditoria.csv")
    with t2:
        df_a = pd.read_sql_query("SELECT * FROM log_accesos ORDER BY id DESC", conn)
        st.dataframe(df_a, use_container_width=True)
    conn.close()

# --- NAVEGACIÓN ---
st.set_page_config(page_title="ERP LA CONCEPCIÓN v10.8.42", layout="wide")
inicializar_db()
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if not st.session_state['logged_in']: login_page()
else:
    if 'init' not in st.session_state: descargar_de_drive(); st.session_state['init'] = True
    with st.sidebar:
        st.title("MENÚ ERP")
        # ESTADO CONECTADO (Sidebar)
        st.markdown("<span style='color:green; font-weight:bold;'>🟢 CONECTADO</span>", unsafe_allow_html=True)
        st.divider()
        modulos = ["🏠 Dashboard", "⛽ PETRÓLEO", "📦 Compras", "💸 Tesorería", "🚜 Bodega", "💰 COSTOS"]
        if st.session_state['email'] == 'osvaldolira@laconcepcion.cl': modulos.append("🕵️ SEGURIDAD")
        menu = st.radio("", modulos)
        if st.session_state['email'] == 'osvaldolira@laconcepcion.cl':
            if st.button("🚀 Sincronizar Drive"): guardar_en_drive()
        if st.button("🚪 Cerrar Sesión"): st.session_state.clear(); st.rerun()
    
    if menu == "🏠 Dashboard": modulo_dashboard()
    elif menu == "⛽ PETRÓLEO": modulo_petroleo()
    elif menu == "📦 Compras": modulo_compras()
    elif menu == "💸 Tesorería": modulo_tesoreria()
    elif menu == "🚜 Bodega": modulo_bodega()
    elif menu == "🕵️ SEGURIDAD": modulo_seguridad()
    elif menu == "💰 COSTOS":
        st.header("💰 Informe de Costos")
        conn = conectar_db()
        df_r = pd.read_sql_query("""SELECT UPPER(TRIM(centro_costo)) as cc, 
            SUM(CASE WHEN fuente = 'BODEGA' THEN val ELSE 0 END) as Insumos, 
            SUM(CASE WHEN fuente = 'FACTURA' THEN val ELSE 0 END) as Gastos, 
            SUM(CASE WHEN fuente = 'PETROLEO' THEN val ELSE 0 END) as Combustible, 
            SUM(val) as Total 
            FROM (SELECT centro_costo, valor_imputado as val, 'BODEGA' as fuente FROM movimientos 
            UNION ALL SELECT centro_costo, monto_imputado as val, 'FACTURA' as fuente FROM facturas WHERE centro_costo != '' 
            UNION ALL SELECT centro_costo, valor_imputado as val, 'PETROLEO' as fuente WHERE tipo='Salida') 
            GROUP BY cc""", conn)
        st.dataframe(df_r.style.format({"Insumos": "${:,.0f}","Gastos": "${:,.0f}","Combustible": "${:,.0f}","Total": "${:,.0f}"}), use_container_width=True)
        conn.close()
