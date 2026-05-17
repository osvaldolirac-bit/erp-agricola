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
IMPUESTO_ESPECIFICO_LITRO = 75 
hoy = datetime.now().date()

FAMILIAS_PRODUCTOS = ["FERTILIZANTE", "FERTILIZANTE FOLIAR", "HERBICIDA", "INSECTICIDA", "FUNGICIDA", "BIO ESTIMULANTE", "ACARICIDA", "REGULADOR DE CRECIMIENTO", "ADHERENTE / MOJANTE", "OTROS"]
CENTROS_COSTO = ["CEREZOS CORTE1", "CEREZOS CORTE2", "CIRUELOS", "NOGALES APARICION", "NOGALES CRUZ DEL SUR", "EL ESPINO", "OTROS"]

# --- 2. MOTOR DE BASE DE DATOS Y UTILIDADES ---

def conectar_db():
    return sqlite3.connect(NOMBRE_DB)

def hash_password(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def f_puntos(v):
    try: return f"{int(round(float(v))):,}".replace(",", ".")
    except: return "0"

def f_decimal(v):
    try: return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return "0,00"

def registrar_accion(accion, detalle):
    user = st.session_state.get('email', 'Desconocido')
    fecha = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        conn = conectar_db()
        conn.execute("INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)", (user, accion, detalle, fecha))
        conn.commit(); conn.close()
    except: pass

def sanear_y_recalcular():
    try:
        conn = conectar_db()
        conn.execute("DELETE FROM facturas WHERE nro_documento LIKE '%_P' AND REPLACE(nro_documento, '_P', '') NOT IN (SELECT nro_documento FROM facturas WHERE nro_documento NOT LIKE '%_P')")
        conn.commit(); conn.close()
    except: pass

def inicializar_db():
    conn = conectar_db(); cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS facturas (id INTEGER PRIMARY KEY AUTOINCREMENT, nro_documento TEXT, proveedor TEXT, fecha_compra DATE, fecha_vencimiento DATE, monto_neto REAL, monto_total REAL, estado TEXT DEFAULT 'Pendiente', tipo TEXT DEFAULT 'Factura', metodo_pago TEXT, fecha_pago DATE, concepto TEXT, centro_costo TEXT, monto_imputado REAL DEFAULT 0)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS inventario (id INTEGER PRIMARY KEY AUTOINCREMENT, producto TEXT, familia TEXT, stock REAL DEFAULT 0, stock_minimo REAL DEFAULT 0, precio_medio REAL DEFAULT 0)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS movimientos (id INTEGER PRIMARY KEY AUTOINCREMENT, producto_id INTEGER, tipo TEXT, cantidad REAL, centro_costo TEXT, fecha DATE, valor_imputado REAL DEFAULT 0)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, password TEXT)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS log_accesos (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, fecha_hora DATETIME)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS petroleo (id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT, litros REAL, proveedor TEXT, monto_total_compra REAL, vehiculo TEXT, responsable TEXT, centro_costo TEXT, fecha DATE, valor_imputado REAL)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS bitacora (id INTEGER PRIMARY KEY AUTOINCREMENT, usuario TEXT, accion TEXT, detalle TEXT, fecha_hora DATETIME)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS ajustes_costos (id INTEGER PRIMARY KEY AUTOINCREMENT, centro_costo TEXT, monto REAL, fecha DATE, motivo TEXT)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS gastos_espino (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha DATE, documento TEXT, item TEXT, monto REAL)""")
    
    usuarios = [('osvaldolira@laconcepcion.cl', hash_password('9083')), ('secretaria@laconcepcion.cl', hash_password('9111'))]
    for u, p in usuarios:
        cursor.execute("INSERT OR IGNORE INTO usuarios (email, password) VALUES (?,?)", (u, p))

    cursor.execute("SELECT COUNT(*) FROM gastos_espino")
    if cursor.fetchone()[0] == 0:
        datos_ex = [
            ('2025-11-12', '719', 'Alisud Auditoria GG', 1094530), ('2025-12-12', 'S/N', 'Carlos Zavala Anticipo', 0),
            ('2025-12-20', 'S/N', 'Alejandra Leviman', 150000), ('2025-12-20', 'S/N', 'Duilio Pruzzo Diferencia Gastos', 6051696),
            ('2025-12-20', 'S/N', 'Carlos Zavala Aguinaldo', 100000), ('2025-12-20', 'S/N', 'Alejandra Levimar Aguinaldo', 100000),
            ('2025-12-24', 'S/N', 'Duilio Pruzzo Reembolso Impuesto', 178083), ('2025-12-27', 'S/N', 'Alejandra Leviman', 125000),
            ('2025-12-29', 'S/N', 'Carlos Zavala Sueldo', 620000), ('2026-01-02', '2217085', 'Podastick Max / Konan', 146757),
            ('2026-01-03', 'S/N', 'Alejandra Leviman', 259257), ('2026-01-06', 'S/N', 'Duilio Pruzzo', 256100),
            ('2026-01-10', 'S/N', 'Alejandra Leviman', 137500), ('2026-01-13', 'Coagra', 'Productos agro', 196493),
            ('2026-01-14', 'S/N', 'Carlos Lira V. Reembolso CZ', 140556), ('2026-01-17', 'S/N', 'Danixa Amaza', 25000),
            ('2026-01-17', 'S/N', 'Alejandra Leviman', 137500), ('2026-01-20', '6323030', 'Podastik Max', 28575),
            ('2026-01-20', '349898', 'Serrucho Podar', 8328), ('2026-01-25', 'S/N', 'Danixa Aplicación arañita', 50000),
            ('2026-01-26', '2224579', 'Konan 240 SC', 79183), ('2026-01-28', '2225756', 'Konan / Acaban SC', 232576),
            ('2026-01-30', 'S/N', 'Carlos Zavala', 620000), ('2026-02-05', 'S/N', 'Danixa Amaza', 50000),
            ('2026-02-10', 'S/N', 'Carlos Zavala Imposiciones', 143483), ('2026-02-11', 'GD', 'Coagra Acaban 1lt', 89969),
            ('2026-02-12', 'S/N', 'Caceres M SPA', 1532084), ('2026-02-19', '13785', 'FerreMás Pala', 10690),
            ('2026-03-02', '14895', 'Marcelo Caro Pernos', 11500), ('2026-03-03', 'DAB', 'Cinta plana amarratec', 11942),
            ('2026-03-03', '2237580', 'Coagra Urea 25k', 198417), ('2026-03-06', '6966966', 'Electrocom Contractor', 220326),
            ('2026-03-09', '7826141', 'Codo hidráulico 75mm', 5750), ('2026-03-09', '349613', 'Equipos Riego Sonda', 77571),
            ('2026-03-09', '54846', 'Autosystem Cable libre', 45346), ('2026-03-10', '23648', 'Los Olivos Perno Hex', 16950),
            ('2026-03-10', '6854929', 'Electrocom CableRV-K', 100399), ('2026-03-10', 'S/N', 'Alejandra Leviman', 112500),
            ('2026-03-11', 'S/N', 'Gustavo Contador', 315000), ('2026-03-11', '349905', 'Motor sumergible 4"', 167171),
            ('2026-03-11', '1427603', 'Vitel Cable reviflex', 108469), ('2026-03-11', '6954495', 'Electrocom Tubo', 27703),
            ('2026-03-11', 'S/N', 'Imposiciones CZ feb', 143483), ('2026-03-11', 'S/N', 'Carlos Lira V.', 243882),
            ('2026-03-12', '21049', 'FP.cl Cinta aislante', 7960), ('2026-03-12', 'S/N', 'Juan Zuñiga Pozo', 4830000),
            ('2026-03-13', 'S/N', 'Héctor Zura', 300000), ('2026-03-14', '6991256', 'Electrocom Rele térmico', 27839),
            ('2026-03-15', 'S/N', 'Alejandra Leviman', 125000), ('2026-03-18', 'CGE', 'Consumo Energía', 309600),
            ('2026-03-30', 'S/N', 'Carlos Zavala Sueldo', 620000), ('2026-04-02', 'S/N', 'Alejandra Leviman sueldo', 112500),
            ('2026-04-07', 'S/N', 'CGE feb y marzo', 924000), ('2026-04-10', 'S/N', 'CZ Imposiciones Marzo', 143483),
            ('2026-04-13', '28803', 'Topagro Fascinate 150 SL', 143032), ('2026-04-17', '2248987', 'Coagra Sulfato zinc', 149190),
            ('2026-04-17', 'S/N', 'Alejandra Leviman', 125000), ('2026-04-17', '7621', 'Fermaco Fumigador 16L', 37900),
            ('2026-04-22', 'S/N', 'Duilio Pruzzo Saco urea', 28000), ('2026-04-30', 'S/N', 'Carlos Zavala Sueldo', 620000),
            ('2026-04-30', 'S/N', 'Cáceres Heladas', 4545184), ('2026-05-08', 'BCI', 'Comisión tarjeta', 13368),
            ('2026-05-12', 'S/N', 'CZ Imposiciones Abril', 143914), ('2026-05-15', '19509', 'Sendai Datalogger', 58362),
            ('2026-05-17', 'S/N', 'María Paola Arriendo', 7000000)
        ]
        cursor.executemany("INSERT INTO gastos_espino (fecha, documento, item, monto) VALUES (?,?,?,?)", datos_ex)
    conn.commit(); conn.close(); sanear_y_recalcular()

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
        st.success("✅ Datos sincronizados con Drive.")

def descargar_de_drive():
    drive = obtener_drive()
    if drive:
        query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
        lista = drive.ListFile({'q': query}).GetList()
        if lista: lista[0].GetContentFile(NOMBRE_DB)

def generar_pdf_blob(df, titulo, incluir_precios=True, total_manual=None, modo_petroleo=False):
    try:
        pdf = FPDF(); pdf.add_page(); pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, "AGRICOLA LA CONCEPCIÓN", ln=True, align="C")
        pdf.set_font("Helvetica", "B", 12); pdf.cell(0, 10, titulo, ln=True, align="C")
        pdf.ln(5); pdf.set_font("Helvetica", "B", 8)
        df_p = df.copy()
        
        t_sum = total_manual
        if t_sum is None:
            cols_money = ["monto", "total", "monto_total", "valor_imputado"]
            for c in df_p.columns:
                if any(x in c.lower() for x in cols_money):
                    try: t_sum = (t_sum or 0) + df_p[c].sum()
                    except: pass

        if modo_petroleo:
            df_p = df_p.drop(columns=[c for c in df_p.columns if any(x in c.lower() for x in ["imputado", "valor", "monto", "precio"])])
            incluir_precios = False
        
        cols = df_p.columns; w = 190 / len(cols)
        for col in cols: pdf.cell(w, 8, str(col).upper(), border=1, align="C")
        pdf.ln(); pdf.set_font("Helvetica", "", 7)
        for _, row in df_p.iterrows():
            for i, item in enumerate(row):
                col_n = df_p.columns[i].lower()
                val = f_puntos(item) if any(x in col_n for x in ["monto", "total", "valor"]) else str(item)
                pdf.cell(w, 7, val[:25], border=1)
            pdf.ln()
        if incluir_precios and t_sum is not None:
            pdf.set_font("Helvetica", "B", 9); pdf.cell(w*(len(cols)-1), 8, "TOTAL FINAL:", border=1, align="R")
            pdf.cell(w, 8, f"${f_puntos(t_sum)}", border=1, align="L")
        return pdf.output(dest="S").encode("latin-1")
    except: return None

def inyectar_css():
    st.markdown("""<style>
        .main { background-color: #f4f7f6; }
        .stMetric { background-color: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); border-left: 6px solid #2E7D32; }
        .metric-big { font-size: 2.8rem !important; font-weight: 800; color: #1B5E20; line-height: 1.2; }
        .metric-red { color: #d32f2f !important; font-size: 2.2rem !important; font-weight: 700; }
        .metric-blue { color: #1976d2 !important; font-size: 2.2rem !important; font-weight: 700; }
        .card-critico { border-left-color: #d32f2f !important; }
        .card-vencida { border-left-color: #1976d2 !important; }
        </style>""", unsafe_allow_html=True)
    if st.session_state.get('logged_in') and st.session_state.get('email') != 'osvaldolira@laconcepcion.cl':
        st.markdown("<style>header {visibility: hidden;} #MainMenu {visibility: hidden;} footer {visibility: hidden;}</style>", unsafe_allow_html=True)

# --- 3. MÓDULOS DEL SISTEMA ---

def modulo_dashboard():
    st.markdown("<h1 style='text-align: center; color: #1B5E20;'>🚜 DASHBOARD PRINCIPAL</h1>", unsafe_allow_html=True)
    conn = conectar_db()
    df_f = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente' AND nro_documento NOT LIKE '%_P'", conn)
    df_p_c = pd.read_sql_query("SELECT SUM(litros) as l FROM petroleo WHERE tipo='Carga'", conn)
    df_p_s = pd.read_sql_query("SELECT SUM(litros) as l FROM petroleo WHERE tipo='Salida'", conn)
    saldo_pet = (df_p_c['l'].fillna(0).iloc[0]) - (df_p_s['l'].fillna(0).iloc[0])
    
    m1, m2, m3, m4, m5 = st.columns(5)
    with m1: st.markdown(f"<div class='stMetric'><small>💰 DEUDA TOTAL</small><br><span class='metric-big'>${f_puntos(df_f['monto_total'].sum())}</span></div>", unsafe_allow_html=True)
    p_dia = hoy.replace(day=1); d_critica = df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < p_dia]['monto_total'].sum()
    with m2: st.markdown(f"<div class='stMetric card-critico'><small>🔥 MESES ANTERIORES</small><br><span class='metric-red'>${f_puntos(d_critica)}</span><br><small style='color:red;'>CRÍTICO</small></div>", unsafe_allow_html=True)
    v_count = len(df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < hoy])
    with m3: st.markdown(f"<div class='stMetric card-vencida'><small>⚠️ VENCIDAS</small><br><span class='metric-blue'>{v_count}</span><br><small style='color:#1976d2;'>DOCUMENTOS</small></div>", unsafe_allow_html=True)
    with m4: st.markdown(f"<div class='stMetric'><small>📄 PENDIENTES</small><br><span style='font-size:2rem; font-weight:600;'>{len(df_f)}</span><br><small>CARTERA</small></div>", unsafe_allow_html=True)
    with m5: st.markdown(f"<div class='stMetric'><small>⛽ PETRÓLEO</small><br><span style='font-size:2rem; font-weight:600;'>{f_decimal(saldo_pet)}L</span><br><small>NETO</small></div>", unsafe_allow_html=True)
    
    st.divider(); c_izq, c_der = st.columns([1.6, 1])
    with c_izq:
        st.markdown("### 📊 Gastos Netos por Cuartel")
        q = """SELECT UPPER(TRIM(cc)) as cc, SUM(val) as total FROM (SELECT centro_costo as cc, valor_imputado as val FROM movimientos WHERE tipo LIKE 'Salida%' UNION ALL SELECT centro_costo as cc, monto_imputado as val FROM facturas WHERE nro_documento LIKE '%_P' UNION ALL SELECT centro_costo as cc, valor_imputado as val FROM petroleo WHERE tipo = 'Salida' UNION ALL SELECT centro_costo as cc, monto as val FROM ajustes_costos) WHERE cc != '' AND cc != 'BODEGA' GROUP BY cc"""
        df_c = pd.read_sql_query(q, conn)
        if not df_c.empty:
            df_c = pd.concat([df_c, pd.DataFrame([{'cc': 'TOTAL GENERAL', 'total': df_c['total'].sum()}])], ignore_index=True)
            st.dataframe(df_c.style.format({"total": "${:,.0f}"}), use_container_width=True)
    with c_der:
        st.markdown("### 📅 Proyección 4 Meses")
        for i in range(4):
            f_p = (datetime.now().replace(day=1) + timedelta(days=i*31)).replace(day=1)
            total_m = df_f[(pd.to_datetime(df_f['fecha_vencimiento']).dt.month == f_p.month) & (pd.to_datetime(df_f['fecha_vencimiento']).dt.year == f_p.year)]['monto_total'].sum() if not df_f.empty else 0
            st.markdown(f"<div style='background:white; padding:10px; border-radius:8px; margin-bottom:5px; border-right: 5px solid #1976d2; display:flex; justify-content:space-between;'><b>{f_p.strftime('%B %Y').upper()}</b> <span>${f_puntos(total_m)}</span></div>", unsafe_allow_html=True)
    conn.close()

def modulo_petroleo():
    st.header("⛽ Gestión de Petróleo")
    t1, t2, t3 = st.tabs(["📥 Carga", "🚜 Salida", "📊 Historial"]); conn = conectar_db()
    with t1:
        with st.form("p_c"):
            l, mt, f = st.number_input("Litros", 0.0), st.number_input("Total Bruto ($)", 0.0), st.date_input("Fecha", hoy)
            if st.form_submit_button("CARGAR"):
                neto = (mt / 1.19) - (l * IMPUESTO_ESPECIFICO_LITRO)
                conn.execute("INSERT INTO petroleo (tipo, litros, monto_total_compra, fecha) VALUES (?,?,?,?)", ("Carga", l, neto, f)); conn.commit(); guardar_en_drive(); st.rerun()
    with t2:
        with st.form("p_s"):
            ls, v, r = st.number_input("Litros Salida", 0.0), st.text_input("Vehículo"), st.text_input("Responsable")
            ccs = [cc for cc in CENTROS_COSTO if st.checkbox(cc, key=f"ps_{cc}")]
            if st.form_submit_button("REGISTRAR SALIDA"):
                df_calc = pd.read_sql_query("SELECT SUM(litros) as l, SUM(monto_total_compra) as m FROM petroleo WHERE tipo='Carga'", conn)
                pmp = (df_calc['m'].iloc[0] / df_calc['l'].iloc[0]) if df_calc['l'].iloc[0] > 0 else 0
                for c in ccs: conn.execute("INSERT INTO petroleo (tipo, litros, vehiculo, responsable, centro_costo, fecha, valor_imputado) VALUES (?,?,?,?,?,?,?)", (ls/len(ccs), v, r, c.upper(), hoy, (ls/len(ccs)*pmp)))
                conn.commit(); st.rerun()
    with t3:
        df = pd.read_sql_query("SELECT id, fecha, tipo, litros, vehiculo, responsable, centro_costo, valor_imputado FROM petroleo ORDER BY id DESC", conn)
        st.dataframe(df.style.format({"litros": "{:,.2f}", "valor_imputado": "${:,.0f}"}), use_container_width=True)
        st.download_button("📥 PDF Operativo", generar_pdf_blob(df, "HISTORIAL PETROLEO", modo_petroleo=True), "petroleo.pdf")
        if st.button("🗑️ ELIMINAR") and st.text_input("Clave Maestro", type="password", key="cl_p") == CLAVE_MAESTRA:
            id_p = st.selectbox("ID borrar", df['id']); conn.execute("DELETE FROM petroleo WHERE id=?", (id_p,)); conn.commit(); st.rerun()
    conn.close()

def modulo_espino():
    st.header("🏡 El Espino - Gestión de Gastos")
    es_admin = (st.session_state.get('email') == 'osvaldolira@laconcepcion.cl')
    t1, t2 = st.tabs(["➕ Registro", "📜 Historial"]); conn = conectar_db()
    with t1:
        df_anual = pd.read_sql_query(f"SELECT SUM(monto) as total FROM gastos_espino WHERE strftime('%Y', fecha) = '{hoy.year}'", conn)
        st.markdown(f"<div class='stMetric'><b>TOTAL ACUMULADO {hoy.year}</b><br><span style='font-size:2.2rem; color:#1B5E20;'>${f_puntos(df_anual['total'].iloc[0] or 0)}</span></div>", unsafe_allow_html=True)
        with st.form("esp_f"):
            f, d, it, mt = st.date_input("Fecha", hoy), st.text_input("Doc/Proveedor"), st.text_input("Descripción"), st.number_input("Monto ($)", 0.0)
            if st.form_submit_button("💾 GUARDAR GASTO"):
                conn.execute("INSERT INTO gastos_espino (fecha, documento, item, monto) VALUES (?,?,?,?)", (f, d, it, mt)); conn.commit(); st.rerun()
    with t2:
        df_bounds = pd.read_sql_query("SELECT MIN(fecha) as min_f FROM gastos_espino", conn)
        f_min = datetime.strptime(df_bounds['min_f'].iloc[0], '%Y-%m-%d').date() if df_bounds['min_f'].iloc[0] else hoy
        col1, col2 = st.columns(2)
        f_ini = col1.date_input("Desde", f_min); f_fin = col2.date_input("Hasta", hoy)
        df_h = pd.read_sql_query(f"SELECT * FROM gastos_espino WHERE fecha BETWEEN '{f_ini}' AND '{f_fin}' ORDER BY fecha DESC", conn)
        
        st.markdown(f"<div class='stMetric' style='border-left-color:#1976d2;'><b>💰 GASTO EN ESTE PERÍODO ({f_ini} al {f_fin})</b><br><span style='font-size:1.8rem; color:#1976d2;'>${f_puntos(df_h['monto'].sum())}</span></div>", unsafe_allow_html=True)
        
        st.dataframe(df_h.style.format({"monto": "${:,.0f}"}), use_container_width=True)
        st.download_button("📥 PDF El Espino", generar_pdf_blob(df_h.drop(columns=['id']), f"GASTOS EL ESPINO: {f_ini} / {f_fin}"), "espino.pdf")
        if es_admin and not df_h.empty:
            st.divider(); id_e = st.selectbox("ID Editar", df_h['id'])
            item_e = df_h[df_h['id']==id_e].iloc[0]
            n_it = st.text_input("Nuevo Item", item_e['item']); n_mt = st.number_input("Nuevo Monto", value=float(item_e['monto']))
            clv = st.text_input("Clave Master", type="password", key="cl_e")
            c1, c2 = st.columns(2)
            if c1.button("✏️ ACTUALIZAR") and clv == CLAVE_MAESTRA:
                conn.execute("UPDATE gastos_espino SET item=?, monto=? WHERE id=?", (n_it, n_mt, id_e)); conn.commit(); st.rerun()
            if c2.button("🗑️ ELIMINAR") and clv == CLAVE_MAESTRA:
                conn.execute("DELETE FROM gastos_espino WHERE id=?", (id_e,)); conn.commit(); st.rerun()
    conn.close()

def modulo_tesoreria():
    st.header("💸 Tesorería")
    conn = conectar_db()
    df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' AND nro_documento NOT LIKE '%_P' AND monto_total > 0 ORDER BY fecha_vencimiento ASC", conn)
    st.warning(f"### DEUDA PENDIENTE: ${f_puntos(df_p['monto_total'].sum())}")
    def color_v(row): return ['color: red' if pd.to_datetime(row.fecha_vencimiento).date() < hoy else '' for _ in row]
    st.dataframe(df_p.style.apply(color_v, axis=1).format({"monto_total": "${:,.0f}"}), use_container_width=True)
    st.download_button("📥 PDF Pendientes", generar_pdf_blob(df_p.drop(columns=['id']), "LISTADO PENDIENTES"), "pendientes.pdf")
    id_p = st.selectbox("ID Pagar", df_p['id']); met = st.selectbox("Método", ["Transferencia", "Efectivo", "Cheque"])
    if st.button("💰 PAGAR"): conn.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (met, hoy, id_p)); conn.commit(); st.rerun()
    conn.close()

def modulo_bodega():
    st.header("🏠 Gestión de Bodega")
    t1, t2, t3, t4 = st.tabs(["📊 Stock", "🔄 Salida", "➕ Registro", "🔍 Consulta CC"]); conn = conectar_db()
    with t1:
        df_s = pd.read_sql_query("SELECT id, producto, familia, stock, precio_medio FROM inventario", conn)
        st.dataframe(df_s.drop(columns=['id']).style.format({"stock": "{:,.2f}", "precio_medio": "${:,.0f}"}), use_container_width=True)
        st.divider(); id_g = st.selectbox("ID Insumo", df_s['id']); item = df_s[df_s['id']==id_g].iloc[0]
        n_nom = st.text_input("Nombre", item['producto']); n_st = st.number_input("Stock", value=float(item['stock']))
        clv = st.text_input("Clave Maestra", type="password", key="cl_b")
        if st.button("✏️ MODIFICAR") and clv == CLAVE_MAESTRA:
            conn.execute("UPDATE inventario SET producto=?, stock=? WHERE id=?", (n_nom, round(n_st, 2), id_g)); conn.commit(); st.rerun()
    with t2:
        df_i = pd.read_sql_query("SELECT id, producto, precio_medio FROM inventario", conn)
        ps = st.selectbox("Insumo", df_i['id'].astype(str) + " - " + df_i['producto']); ct = st.number_input("Cant", 0.0)
        ccs = [cc for cc in CENTROS_COSTO if st.checkbox(cc, key=f"mb_{cc}")]
        if st.button("REGISTRAR SALIDA"):
            iid = int(ps.split(" - ")[0]); pmp = df_i[df_i['id']==iid]['precio_medio'].iloc[0]
            if ct > 0 and ccs:
                for c in ccs: conn.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado) VALUES (?,?,?,?,?,?)", (iid, "Salida", ct/len(ccs), hoy, c.upper(), (ct/len(ccs)*pmp)))
                conn.execute("UPDATE inventario SET stock = stock - ? WHERE id = ?", (round(ct, 2), iid)); conn.commit(); st.rerun()
    with t4:
        cc_q = st.selectbox("Cuartel", CENTROS_COSTO)
        df_cc = pd.read_sql_query(f"SELECT m.fecha, i.producto, m.cantidad, m.valor_imputado FROM movimientos m JOIN inventario i ON m.producto_id = i.id WHERE m.centro_costo = '{cc_q.upper()}' ORDER BY m.fecha DESC", conn)
        st.dataframe(df_cc.style.format({"cantidad": "{:,.2f}", "valor_imputado": "${:,.0f}"}), use_container_width=True)
        st.download_button(f"📥 PDF {cc_q}", generar_pdf_blob(df_cc, f"MOVIMIENTOS EN {cc_q}"), "cc.pdf")
    conn.close()

def modulo_compras():
    st.header("📦 Compras")
    t1, t2, t3 = st.tabs(["➕ Insumos", "💸 Gastos", "🔍 Historial"]); conn = conectar_db()
    with t1:
        c1, c2 = st.columns(2); nro, prov, fe, fv = c1.text_input("N° Doc"), c1.text_input("Proveedor"), c2.date_input("Emisión"), c2.date_input("Vence")
        df_i = pd.read_sql_query("SELECT id, producto FROM inventario", conn)
        ps = st.selectbox("Insumo", df_i['id'].astype(str) + " - " + df_i['producto']) if not df_i.empty else None
        ct, pr = st.number_input("Cant", 0.0), st.number_input("Neto Unit.", 0.0)
        if st.button("➕ AGREGAR"):
            if 'car' not in st.session_state: st.session_state['car'] = []
            st.session_state['car'].append({'id': int(ps.split(" - ")[0]), 'n': ps.split(" - ")[1], 'c': ct, 'p': pr, 't': ct*pr}); st.rerun()
        if st.session_state.get('car'):
            df_car = pd.DataFrame(st.session_state['car']); st.table(df_car)
            if st.button("💾 GUARDAR FACTURA"):
                conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total) VALUES (?,?,?,?,?)", (nro, prov, fe, fv, df_car['t'].sum()*1.19))
                for i in st.session_state['car']:
                    cur = conn.execute("SELECT stock, precio_medio FROM inventario WHERE id=?", (i['id'],)).fetchone()
                    n_pmp = ((cur[0]*cur[1]) + (i['c']*i['p'])) / (cur[0]+i['c']) if (cur[0]+i['c']) > 0 else i['p']
                    conn.execute("UPDATE inventario SET stock = stock + ?, precio_medio = ? WHERE id = ?", (i['c'], n_pmp, i['id']))
                conn.commit(); st.session_state['car'] = []; guardar_en_drive(); st.rerun()
    with t3:
        df_h = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_compra, monto_total FROM facturas WHERE monto_total > 0 AND nro_documento NOT LIKE '%_P' ORDER BY id DESC", conn)
        st.dataframe(df_h.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
    conn.close()

def modulo_costos():
    st.header("💰 Costos Consolidados")
    es_admin = (st.session_state.get('email') == 'osvaldolira@laconcepcion.cl')
    conn = conectar_db()
    q = """SELECT UPPER(TRIM(cc)) as cc, SUM(CASE WHEN fuente = 'BODEGA' THEN val ELSE 0 END) as Insumos, SUM(CASE WHEN fuente = 'FACTURA' THEN val ELSE 0 END) as Gastos, SUM(CASE WHEN fuente = 'PETROLEO' THEN val ELSE 0 END) as Petroleo, SUM(CASE WHEN fuente = 'AJUSTE' THEN val ELSE 0 END) as Ajustes, SUM(val) as Total FROM (SELECT centro_costo as cc, valor_imputado as val, 'BODEGA' as fuente FROM movimientos UNION ALL SELECT centro_costo as cc, monto_imputado as val, 'FACTURA' as fuente FROM facturas WHERE nro_documento LIKE '%_P' UNION ALL SELECT centro_costo as cc, valor_imputado as val, 'PETROLEO' as fuente FROM petroleo WHERE tipo='Salida' UNION ALL SELECT centro_costo as cc, monto as val, 'AJUSTE' as fuente FROM ajustes_costos) WHERE cc != '' AND cc != 'BODEGA' GROUP BY cc"""
    df_r = pd.read_sql_query(q, conn)
    if not df_r.empty:
        tot = df_r['Total'].sum(); df_m = df_r.copy()
        if not es_admin: df_m = df_m.drop(columns=['Ajustes'])
        st.dataframe(df_m.style.format({c: ("${:,.0f}" if c in ["Gastos", "Total", "Insumos", "Petroleo", "Ajustes"] else str) for c in df_m.columns if c != 'cc'}), use_container_width=True)
        st.download_button("📥 PDF Costos", generar_pdf_blob(df_r, "INFORME DE COSTOS", total_manual=tot), "costos.pdf")
    conn.close()

# --- 4. LOGIN Y NAVEGACIÓN ---

def login_page():
    inyectar_css()
    st.markdown("<h1 style='text-align: center; color: #1B5E20; margin-top: 50px;'>🚜 ERP LA CONCEPCIÓN</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        with st.form("login"):
            e, p = st.text_input("Usuario (Email)"), st.text_input("Contraseña", type="password")
            if st.form_submit_button("ACCEDER"):
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("SELECT email FROM usuarios WHERE email=? AND password=?", (e, hash_password(p)))
                if cursor.fetchone(): st.session_state['logged_in'], st.session_state['email'] = True, e; st.rerun()
                else: st.error("Acceso denegado")

st.set_page_config(page_title="ERP v10.8.85", layout="wide")
inicializar_db()

if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False

if not st.session_state['logged_in']: login_page()
else:
    if 'init' not in st.session_state: descargar_de_drive(); st.session_state['init'] = True
    inyectar_css()
    with st.sidebar:
        st.title("MENÚ")
        st.markdown("<span style='color:green;'>🟢 CONECTADO</span>", unsafe_allow_html=True)
        m_opts = { "🏠 DASHBOARD": "DASHBOARD", "⛽ Petróleo": "Petróleo", "📦 Compras": "Compras", "💸 Tesorería": "Tesorería", "🏠 Bodega": "Bodega", "🏡 El Espino": "Espino", "💰 Costos": "Costos" }
        if st.session_state['email'] == 'osvaldolira@laconcepcion.cl': m_opts["🕵️ Seguridad"] = "Seguridad"
        menu = m_opts[st.radio("Navegación", list(m_opts.keys()))]
        if st.button("🚀 Sincronizar Drive"): guardar_en_drive()
        if st.button("🚪 Salir"): st.session_state.clear(); st.rerun()
    
    if menu == "DASHBOARD": modulo_dashboard()
    elif menu == "Petróleo": modulo_petroleo()
    elif menu == "Compras": modulo_compras()
    elif menu == "Tesorería": modulo_tesoreria()
    elif menu == "Bodega": modulo_bodega()
    elif menu == "Espino": modulo_espino()
    elif menu == "Costos": modulo_costos()
    elif menu == "Seguridad": 
        st.header("🕵️ Auditoría")
        conn = conectar_db()
        st.dataframe(pd.read_sql_query("SELECT * FROM bitacora ORDER BY id DESC", conn))
        conn.close()
