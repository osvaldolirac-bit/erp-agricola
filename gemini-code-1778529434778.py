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
import requests
import io

# =============================================================================
# 1. CONFIGURACIÓN, CONSTANTES Y ESTADOS
# =============================================================================
ID_CARPETA_DRIVE = "12tjxWa_RVRP5YuYd2sypjBO8bPuyMqo6" 
NOMBRE_DB = 'erp_concepcion_v6.db'
CLAVE_MAESTRA = "2908" 
IMPUESTO_ESPECIFICO_LITRO = 75 
hoy = datetime.now().date()

FAMILIAS_PRODUCTOS = ["FERTILIZANTE", "FERTILIZANTE FOLIAR", "HERBICIDA", "INSECTICIDA", "FUNGICIDA", "BIO ESTIMULANTE", "ACARICIDA", "REGULADOR DE CRECIMIENTO", "ADHERENTE / MOJANTE", "OTROS"]
CENTROS_COSTO = ["CEREZOS CORTE1", "CEREZOS CORTE2", "CIRUELOS", "NOGALES APARICION", "NOGALES CRUZ DEL SUR", "EL ESPINO", "OTROS"]

# DATA DE INYECCIÓN EL ESPINO
DATA_ESP_HISTORICA = [
    ('2025-11-12', '719', 'Alisud Auditoria GG', 1094530), ('2025-12-12', 'S/N', 'Carlos Zavala Anticipo sueldo', 0),
    ('2025-12-20', 'S/N', 'Alejandra Leviman', 150000), ('2025-12-20', 'S/N', 'Duilio Pruzzo Diferencia en gastos', 6051696),
    ('2025-12-20', 'S/N', 'Carlos Zavala Aguinaldo', 100000), ('2025-12-20', 'S/N', 'Alejandra Levimar Aguinaldo', 100000),
    ('2025-12-24', 'S/N', 'Duilio Pruzzo Reembolso Impuesto', 178083), ('2025-12-27', 'S/N', 'Alejandra Leviman', 125000),
    ('2025-12-29', 'S/N', 'Carlos Zavala Sueldo', 620000), ('2026-01-02', '2217085', 'Podastick Max 3.8 L, Konan 240 SC 1L', 146757),
    ('2026-01-03', 'S/N', 'Alejandra Leviman', 259257), ('2026-01-06', 'S/N', 'Duilio Pruzzo', 256100),
    ('2026-01-06', 'S/N', 'Carlos Zavala Sueldo', 0), ('2026-01-10', 'S/N', 'Alejandra Leviman', 137500),
    ('2026-01-14', 'S/N', 'Carlos Lira V. Reembolso Imposiciones CZ', 140556), ('2026-01-13', 'Coagra', 'Productos del agro', 196493),
    ('2026-01-16', 'CZ', 'Suple', 0), ('2026-01-17', 'S/N', 'Danixa Amaza', 25000),
    ('2026-01-17', 'S/N', 'Alejandra Leviman', 137500), ('2026-01-20', '6323030', 'Podastik Max fitosanitarios', 28575),
    ('2026-01-20', '349898', 'Serrucho Podar c/gancho', 8328), ('2026-01-25', 'S/N', 'Danixa Aplicación arañita', 50000),
    ('2026-01-26', '2224579', 'Konan 240 SC 1lt', 79183), ('2026-01-28', '2225756', 'Konan / Acaban SC', 232576),
    ('2026-01-30', 'S/N', 'Carlos Zavala', 620000), ('2026-01-30', 'S/N', 'Duilio Pruzzo', 0),
    ('2026-02-05', 'S/N', 'Danixa Amaza', 50000), ('2026-02-10', 'S/N', 'Carlos Zavala Imposiciones', 143483),
    ('2026-02-11', 'GD', 'Coagra Acaban 1lt', 89969), ('2026-02-12', 'S/N', 'Caceres M SPA', 1532084),
    ('2026-02-19', '13785', 'FerreMás Pala', 10690), ('2026-03-02', '14895', 'Marcelo Caro Pernos varios', 11500),
    ('2026-03-10', '23648', 'Soc. Los Olivos Pernos Hex', 16950), ('2026-03-12', '21049', 'FP.cl Cinta aislante', 7960),
    ('2026-03-09', '7826141', 'Ferretería codo hidráulico', 5750), ('2026-03-03', 'DAB', 'Cinta plana amarratec', 11942),
    ('2026-03-03', '2237580', 'Coagra Urea granulada', 198417), ('2026-03-06', '6966966', 'Electrocom Contractor', 220326),
    ('2026-03-09', '349613', 'Equipos Riego SPA Sonda nivel', 77571), ('2026-03-09', '54846', 'Autosystem Cable libre halógeno', 45346),
    ('2026-03-10', 'S/N', 'Alejandra Leviman', 112500), ('2026-03-10', '6854929', 'Electrocom Cable RV-K', 100399),
    ('2026-03-30', 'S/N', 'Carlos Zavala Sueldo Marzo', 620000), ('2026-03-18', 'CGE', 'Consumo Eléctrico', 309600),
    ('2026-03-14', '6991256', 'Electrocom Rele térmico', 27839), ('2026-03-15', 'S/N', 'Alejandra Leviman', 125000),
    ('2026-03-13', 'S/N', 'Héctor Zura', 300000), ('2026-03-12', 'S/N', 'Juan Zuñiga Pozo', 4830000),
    ('2026-03-11', 'S/N', 'Punto Hidraulico Mufa', 29750), ('2026-03-11', 'S/N', 'Gustavo Contador mensual', 315000),
    ('2026-03-11', 'S/N', 'Carlos Lira V.', 243882), ('2026-03-11', '349905', 'Equipos Riego Motor 4 Sum', 167171),
    ('2026-03-11', '1427603', 'Vitel Cable reviflex', 108469), ('2026-03-11', '6954495', 'Electrocom Tubo curvable', 27703),
    ('2026-03-11', 'S/N', 'Imposiciones CZ feb', 143483), ('2026-04-02', 'S/N', 'Alejandra Leviman sueldo', 112500),
    ('2026-04-07', 'S/N', 'CGE feb y marzo', 924000), ('2026-04-13', '28803', 'Topagro Fascinate 150 SL', 143032),
    ('2026-04-10', 'S/N', 'CZ Imposiciones Marzo', 143483), ('2026-04-17', '2248987', 'Coagra Sulfato zinc', 149190),
    ('2026-04-30', 'S/N', 'Carlos Zavala Sueldo', 620000), ('2026-04-30', 'S/N', 'Cáceres Heladas', 4545184),
    ('2026-05-08', 'BCI', 'Comisión tarjeta', 13368), ('2026-05-12', 'S/N', 'CZ Imposiciones Abril', 143914),
    ('2026-05-15', '19509', 'Sendai Datalogger', 58362), ('2026-05-17', 'S/N', 'Arriendo María Paola Torrez', 7000000)
]

# =============================================================================
# 2. MOTOR DE BASE DE DATOS Y SANEAMIENTO
# =============================================================================
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
        conn.commit()
        conn.close()
    except: pass

def inicializar_db():
    conn = conectar_db(); cursor = conn.cursor()
    # Saneamiento de tabla accesos para v10.9.5
    cursor.execute("DROP TABLE IF EXISTS log_accesos")
    cursor.execute("CREATE TABLE log_accesos (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, fecha_hora DATETIME)")
    
    cursor.execute("""CREATE TABLE IF NOT EXISTS facturas (id INTEGER PRIMARY KEY AUTOINCREMENT, nro_documento TEXT, proveedor TEXT, fecha_compra DATE, fecha_vencimiento DATE, monto_neto REAL, monto_total REAL, estado TEXT DEFAULT 'Pendiente', tipo TEXT DEFAULT 'Factura', metodo_pago TEXT, fecha_pago DATE, concepto TEXT, centro_costo TEXT, monto_imputado REAL DEFAULT 0)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS inventario (id INTEGER PRIMARY KEY AUTOINCREMENT, producto TEXT, familia TEXT, stock REAL DEFAULT 0, stock_minimo REAL DEFAULT 0, precio_medio REAL DEFAULT 0)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS movimientos (id INTEGER PRIMARY KEY AUTOINCREMENT, producto_id INTEGER, tipo TEXT, cantidad REAL, centro_costo TEXT, fecha DATE, valor_imputado REAL DEFAULT 0)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, password TEXT)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS petroleo (id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT, litros REAL, proveedor TEXT, monto_total_compra REAL, vehiculo TEXT, responsable TEXT, centro_costo TEXT, fecha DATE, valor_imputado REAL)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS bitacora (id INTEGER PRIMARY KEY AUTOINCREMENT, usuario TEXT, accion TEXT, detalle TEXT, fecha_hora DATETIME)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS ajustes_costos (id INTEGER PRIMARY KEY AUTOINCREMENT, centro_costo TEXT, monto REAL, fecha DATE, motivo TEXT)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS gastos_espino (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha DATE, documento TEXT, item TEXT, monto REAL)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS libro_campo (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha DATE, n_orden TEXT, sector TEXT, est_fenologico TEXT, especie TEXT, motivo TEXT, producto TEXT, n_aplicacion INTEGER, ingrediente TEXT, dosis REAL, unidad_dosis TEXT, vol_total REAL, gasto_total REAL, unidad_gasto TEXT, tractor TEXT, maquina TEXT, aplicadores TEXT, car_etiqueta INTEGER, car_agenda INTEGER, car_mayor INTEGER, fecha_viable DATE)""")
    
    usuarios = [('osvaldolira@laconcepcion.cl', hash_password('9083')), ('secretaria@laconcepcion.cl', hash_password('9111'))]
    for u, p in usuarios:
        cursor.execute("INSERT OR IGNORE INTO usuarios (email, password) VALUES (?,?)", (u, p))

    cursor.execute("SELECT COUNT(*) FROM gastos_espino")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("INSERT INTO gastos_espino (fecha, documento, item, monto) VALUES (?,?,?,?)", DATA_ESP_HISTORICA)
    
    conn.commit(); conn.close()

# =============================================================================
# 3. UTILIDADES: INDICADORES, DRIVE Y PDF
# =============================================================================

@st.cache_data(ttl=3600)
def obtener_indicadores():
    try:
        r = requests.get("https://mindicador.cl/api", timeout=5).json()
        return {
            'uf': f"${r['uf']['valor']:,.2f}",
            'utm': f"${r['utm']['valor']:,.0f}",
            'dolar': f"${r['dolar']['valor']:,.2f}",
            'euro': f"${r['euro']['valor']:,.2f}"
        }
    except:
        return {'uf': '$37.942,12', 'utm': '$66.628', 'dolar': '$945,50', 'euro': '$1.024,30'}

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
        st.success("✅ Respaldo Drive Sincronizado.")

def generar_pdf_blob(df, titulo, incluir_precios=True, total_manual=None, modo_petroleo=False, orden_asc=False):
    try:
        pdf = FPDF(); pdf.add_page(); pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, "AGRICOLA LA CONCEPCIÓN", ln=True, align="C")
        pdf.set_font("Helvetica", "B", 12); pdf.cell(0, 10, titulo, ln=True, align="C")
        pdf.ln(5); pdf.set_font("Helvetica", "B", 8)
        
        df_p = df.copy()
        if orden_asc and 'fecha' in [c.lower() for c in df_p.columns]:
            col_f = [c for c in df_p.columns if c.lower() == 'fecha'][0]
            df_p[col_f] = pd.to_datetime(df_p[col_f])
            df_p = df_p.sort_values(by=col_f, ascending=True)
            df_p[col_f] = df_p[col_f].dt.date

        t_sum = total_manual
        if t_sum is None:
            cols_money = ["monto", "total", "monto_total", "valor_imputado", "gasto_total", "monto_imputado"]
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
                if any(x in col_n for x in ["monto", "total", "valor"]): val = f_puntos(item)
                elif any(x in col_n for x in ["litros", "cantidad", "stock", "volumen", "dosis"]): val = f_decimal(item)
                else: val = str(item)
                pdf.cell(w, 7, val[:25], border=1)
            pdf.ln()
        if incluir_precios and t_sum is not None:
            pdf.set_font("Helvetica", "B", 9); pdf.cell(w*(len(cols)-1), 8, "TOTAL FINAL:", border=1, align="R")
            pdf.cell(w, 8, f"${f_puntos(t_sum)}", border=1, align="L")
        return pdf.output(dest="S").encode("latin-1")
    except Exception as e: return None

def inyectar_css():
    st.markdown(f"""<style>
        .main {{ background-color: #f4f7f6; }}
        .stMetric {{ background-color: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); border-left: 6px solid #2E7D32; }}
        [data-testid="stMetricValue"] {{ font-size: 1.55rem !important; font-weight: 800; color: #1B5E20; }}
        .metric-red {{ color: #d32f2f !important; font-size: 2.2rem !important; font-weight: 700; }}
        .metric-blue {{ color: #1976d2 !important; font-size: 2.2rem !important; font-weight: 700; }}
        .sidebar-user {{ color: #0D47A1 !important; font-weight: 900; font-size: 1.15rem; }}
        div[data-testid="stRadio"] label {{ text-transform: uppercase; font-weight: 700; font-size: 0.85rem; }}
        .banner-econ {{ background: #0D47A1; color: white; padding: 10px; border-radius: 8px; text-align: center; font-weight: bold; margin-bottom: 20px; font-size: 0.9rem; }}
        </style>""", unsafe_allow_html=True)
    if st.session_state.get('logged_in') and st.session_state.get('email') != 'osvaldolira@laconcepcion.cl':
        st.markdown("<style>header {visibility: hidden;} #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display:none;}</style>", unsafe_allow_html=True)

# =============================================================================
# 4. MÓDULOS DEL SISTEMA
# =============================================================================

def modulo_dashboard():
    ind = obtener_indicadores()
    st.markdown(f'<div class="banner-econ">📈 INDICADORES ECONÓMICOS: UF: {ind["uf"]} | UTM: {ind["utm"]} | DÓLAR: {ind["dolar"]} | EURO: {ind["euro"]}</div>', unsafe_allow_html=True)
    st.markdown("<h1 style='text-align: center; color: #1B5E20;'>🚜 DASHBOARD PRINCIPAL</h1>", unsafe_allow_html=True)
    st.markdown(f"<p style='text-align: center; color: #0D47A1; font-weight: bold;'>SESIÓN ACTIVA: {st.session_state['email']}</p>", unsafe_allow_html=True)
    
    conn = conectar_db(); df_f = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente' AND nro_documento NOT LIKE '%_P'", conn)
    df_p_c = pd.read_sql_query("SELECT SUM(litros) as l FROM petroleo WHERE tipo='Carga'", conn)
    df_p_s = pd.read_sql_query("SELECT SUM(litros) as l FROM petroleo WHERE tipo='Salida'", conn)
    saldo_pet = (df_p_c['l'].fillna(0).iloc[0]) - (df_p_s['l'].fillna(0).iloc[0])
    
    m1, m2, m3, m4, m5 = st.columns(5)
    with m1: st.metric("💰 DEUDA TOTAL", f"${f_puntos(df_f['monto_total'].sum())}")
    p_dia = hoy.replace(day=1); d_crit = df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < p_dia]['monto_total'].sum()
    with m2: st.markdown(f"<div class='stMetric'><small>🔥 MESES ANTERIORES</small><br><span class='metric-red'>${f_puntos(d_crit)}</span></div>", unsafe_allow_html=True)
    v_count = len(df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < hoy])
    with m3: st.markdown(f"<div class='stMetric'><small>⚠️ VENCIDAS</small><br><span class='metric-blue'>{v_count} docs</span></div>", unsafe_allow_html=True)
    with m4: st.metric("📄 PENDIENTES", f"{len(df_f)}")
    with m5: st.metric("⛽ PETRÓLEO", f"{f_decimal(saldo_pet)} L")
    
    st.divider()
    c_izq, c_der = st.columns([1.6, 1])
    with c_izq:
        st.markdown("### 📊 GASTOS POR CUARTEL")
        q = """SELECT UPPER(TRIM(cc)) as cc, SUM(val) as total FROM (SELECT centro_costo as cc, valor_imputado as val FROM movimientos WHERE tipo LIKE 'Salida%' UNION ALL SELECT centro_costo as cc, monto_imputado as val FROM facturas WHERE nro_documento LIKE '%_P' UNION ALL SELECT centro_costo as cc, valor_imputado as val FROM petroleo WHERE tipo = 'Salida' UNION ALL SELECT centro_costo as cc, monto as val FROM ajustes_costos) WHERE cc != '' AND cc != 'BODEGA' GROUP BY cc"""
        df_c = pd.read_sql_query(q, conn)
        if not df_c.empty:
            st.dataframe(df_c.style.format({"total": "${:,.0f}"}), use_container_width=True)
    with c_der:
        st.markdown("### 📅 FLUJO DE PAGOS")
        for i in range(4):
            f_p = (datetime.now().replace(day=1) + timedelta(days=i*31)).replace(day=1)
            total_m = df_f[(pd.to_datetime(df_f['fecha_vencimiento']).dt.month == f_p.month) & (pd.to_datetime(df_f['fecha_vencimiento']).dt.year == f_p.year)]['monto_total'].sum() if not df_f.empty else 0
            st.markdown(f"<div style='background:white; padding:10px; border-radius:8px; margin-bottom:5px; border-right: 5px solid #1976d2; display:flex; justify-content:space-between;'><b>{f_p.strftime('%B %Y').upper()}</b> <span>${f_puntos(total_m)}</span></div>", unsafe_allow_html=True)
    conn.close()

def modulo_petroleo():
    st.header("⛽ GESTIÓN DE PETRÓLEO")
    t1, t2, t3 = st.tabs(["📥 CARGA", "🚜 SALIDA", "📊 HISTORIAL"]); conn = conectar_db()
    with t1:
        with st.form("p_c"):
            l, mt, f = st.number_input("Litros", 0.0), st.number_input("Total Bruto ($)", 0.0), st.date_input("Fecha", hoy)
            if st.form_submit_button("REGISTRAR CARGA"):
                neto = (mt / 1.19) - (l * IMPUESTO_ESPECIFICO_LITRO)
                conn.execute("INSERT INTO petroleo (tipo, litros, monto_total_compra, fecha) VALUES (?,?,?,?)", ("Carga", l, neto, f))
                conn.commit(); registrar_accion("CARGA PETROLEO", f"{l} Lts"); guardar_en_drive(); st.rerun()
    with t2:
        with st.form("p_s"):
            ls, v, r = st.number_input("Litros Salida", 0.0), st.text_input("Vehículo"), st.text_input("Responsable")
            ccs = [cc for cc in CENTROS_COSTO if st.checkbox(cc, key=f"ps_{cc}")]
            if st.form_submit_button("REGISTRAR SALIDA"):
                df_calc = pd.read_sql_query("SELECT SUM(litros) as l, SUM(monto_total_compra) as m FROM petroleo WHERE tipo='Carga'", conn)
                pmp = (df_calc['m'].iloc[0] / df_calc['l'].iloc[0]) if df_calc['l'].iloc[0] > 0 else 0
                for c in ccs: conn.execute("INSERT INTO petroleo (tipo, litros, vehiculo, responsable, centro_costo, fecha, valor_imputado) VALUES (?,?,?,?,?,?,?)", (ls/len(ccs), v, r, c.upper(), hoy, (ls/len(ccs)*pmp)))
                conn.commit(); registrar_accion("SALIDA PETROLEO", f"{ls} Lts"); st.rerun()
    with t3:
        df_p = pd.read_sql_query("SELECT id, fecha, tipo, litros, vehiculo, responsable, centro_costo, valor_imputado FROM petroleo ORDER BY id DESC", conn)
        st.dataframe(df_p.style.format({"litros": "{:,.2f}", "valor_imputado": "${:,.0f}"}), use_container_width=True)
        st.download_button("📥 PDF HISTORIAL", generar_pdf_blob(df_p, "HISTORIAL PETROLEO", modo_petroleo=True), "petroleo.pdf")
        if st.session_state['email'] == 'osvaldolira@laconcepcion.cl':
            id_p = st.selectbox("ID borrar", df_p['id']); clv = st.text_input("Clave Master", type="password", key="cl_p")
            if st.button("🗑️ ELIMINAR") and clv == CLAVE_MAESTRA: conn.execute("DELETE FROM petroleo WHERE id=?", (id_p,)); conn.commit(); st.rerun()
    conn.close()

def modulo_compras():
    st.header("📦 COMPRAS E HISTORIAL")
    t1, t2, t3 = st.tabs(["➕ INSUMOS", "💸 GASTOS VARIOS", "🔍 HISTORIAL"]); conn = conectar_db()
    with t1:
        c1, c2 = st.columns(2); nro, prov, fe, fv = c1.text_input("N° Factura"), c1.text_input("Proveedor"), c2.date_input("Fecha Emisión"), c2.date_input("Vencimiento")
        df_i = pd.read_sql_query("SELECT id, producto FROM inventario", conn)
        ps = st.selectbox("Insumo", df_i['id'].astype(str) + " - " + df_i['producto']) if not df_i.empty else None
        ct, pr = st.number_input("Cantidad", 0.0), st.number_input("Precio Neto Unit.", 0.0)
        if st.button("➕ AGREGAR"):
            if 'car' not in st.session_state: st.session_state['car'] = []
            st.session_state['car'].append({'id': int(ps.split(" - ")[0]), 'n': ps.split(" - ")[1], 'c': ct, 'p': pr, 't': ct*pr}); st.rerun()
        if st.session_state.get('car'):
            st.table(pd.DataFrame(st.session_state['car']))
            if st.button("💾 GUARDAR FACTURA"):
                total_bruto = pd.DataFrame(st.session_state['car'])['t'].sum() * 1.19
                conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total) VALUES (?,?,?,?,?)", (nro, prov, fe, fv, total_bruto))
                for i in st.session_state['car']:
                    cur = conn.execute("SELECT stock, precio_medio FROM inventario WHERE id=?", (i['id'],)).fetchone()
                    n_pmp = ((cur[0]*cur[1]) + (i['c']*i['p'])) / (cur[0]+i['c']) if (cur[0]+i['c']) > 0 else i['p']
                    conn.execute("UPDATE inventario SET stock = stock + ?, precio_medio = ? WHERE id = ?", (i['c'], n_pmp, i['id']))
                conn.commit(); st.session_state['car'] = []; registrar_accion("COMPRA", nro); guardar_en_drive(); st.rerun()
    with t2:
        pg, ng, fg1, fg2 = st.text_input("Proveedor Gasto", key="pg"), st.text_input("N° Doc", key="ng"), st.date_input("Fecha Gasto", hoy), st.date_input("Vence", hoy)
        sel_cc = [cc for cc in CENTROS_COSTO if st.checkbox(cc, key=f"gv_{cc}")]
        mt = st.number_input("Monto Bruto ($)", 0.0); iva = st.radio("Imputar Bruto?", ["SI", "NO (NETO)"])
        if st.button("💾 GUARDAR GASTO VARIO"):
            imp = mt if iva == "SI" else mt/1.19
            conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo) VALUES (?,?,?,?,?,?)", (ng, pg, fg1, fg2, mt, 'Gasto Vario'))
            for c in sel_cc: conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, centro_costo, monto_imputado) VALUES (?,?,?,?,?,?,?,?)", (ng+"_P", pg, fg1, fg2, 0, 'Gasto Vario', c.upper(), imp/len(sel_cc)))
            conn.commit(); registrar_accion("GASTO VARIO", ng); st.rerun()
    with t3:
        fi_c = st.date_input("Desde", hoy-timedelta(days=365)); ff_c = st.date_input("Hasta", hoy)
        df_h = pd.read_sql_query(f"SELECT id, nro_documento, proveedor, fecha_compra, monto_total FROM facturas WHERE monto_total > 0 AND nro_documento NOT LIKE '%_P' AND fecha_compra BETWEEN '{fi_c}' AND '{ff_c}' ORDER BY fecha_compra DESC", conn)
        st.dataframe(df_h.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
        st.download_button("📥 PDF COMPRAS", generar_pdf_blob(df_h, "HISTORIAL COMPRAS"), "compras.pdf")
        if st.session_state['email'] == 'osvaldolira@laconcepcion.cl':
            id_del = st.selectbox("ID factura", df_h['id'])
            if st.button("🗑️ BORRAR") and st.text_input("Clave Maestro", type="password") == CLAVE_MAESTRA:
                f_sel = df_h[df_h['id']==id_del].iloc[0]; conn.execute("DELETE FROM facturas WHERE id=?", (id_del,)); conn.execute("DELETE FROM facturas WHERE nro_documento=? AND proveedor=?", (f_sel['nro_documento']+"_P", f_sel['proveedor'])); conn.commit(); st.rerun()
    conn.close()

def modulo_espino():
    st.header("🏡 EL ESPINO - GESTIÓN DE GASTOS")
    es_admin = (st.session_state.get('email') == 'osvaldolira@laconcepcion.cl')
    t1, t2 = st.tabs(["➕ REGISTRO", "📜 HISTORIAL"]); conn = conectar_db()
    with t1:
        with st.form("esp_f"):
            f, d, it, mt = st.date_input("Fecha", hoy), st.text_input("Doc"), st.text_input("Item"), st.number_input("Monto", 0.0)
            if st.form_submit_button("GUARDAR"):
                conn.execute("INSERT INTO gastos_espino (fecha, documento, item, monto) VALUES (?,?,?,?)", (f, d, it, mt))
                conn.commit(); registrar_accion("EL ESPINO", it); st.rerun()
    with t2:
        df_h = pd.read_sql_query("SELECT * FROM gastos_espino ORDER BY fecha DESC", conn)
        st.markdown(f"**💰 TOTAL ACUMULADO:** `${f_puntos(df_h['monto'].sum())}`")
        st.dataframe(df_h.style.format({"monto": "${:,.0f}"}), use_container_width=True)
        st.download_button("📥 PDF CRONOLÓGICO", generar_pdf_blob(df_h.drop(columns=['id']), "GASTOS EL ESPINO", orden_asc=True), "espino.pdf")
    conn.close()

def modulo_libro_campo():
    st.header("📒 LIBRO DE CAMPO")
    t1, t2 = st.tabs(["📥 INGRESO", "📜 HISTORIAL"]); conn = conectar_db()
    with t1:
        with st.form("lc_form"):
            c1, c2, c3 = st.columns(3)
            with c1: f = st.date_input("Fecha Aplicación", hoy); ord_n = st.text_input("N° Orden"); cc = st.selectbox("Cuartel", CENTROS_COSTO)
            with c2: esp = st.text_input("Especie"); prod = st.text_input("Producto"); n_ap = st.number_input("N° App", 1)
            with c3: ing = st.text_input("Ingrediente Activo"); dos = st.number_input("Dosis", 0.0); vol = st.number_input("Volumen (Lt)", 0.0)
            c4, c5 = st.columns(2)
            with c4: c_et = st.number_input("Carencia Etiqueta", 0); c_ag = st.number_input("Carencia Agenda", 0)
            c_may = max(c_et, c_ag); f_via = f + timedelta(days=c_may)
            st.warning(f"FECHA COSECHA VIABLE: {f_via.strftime('%d/%m/%Y')}")
            if st.form_submit_button("💾 GUARDAR APLICACIÓN"):
                conn.execute("INSERT INTO libro_campo (fecha, n_orden, sector, especie, producto, n_aplicacion, ingrediente, dosis, vol_total, car_etiqueta, car_agenda, car_mayor, fecha_viable) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (f, ord_n, cc, esp, prod, n_ap, ing, dos, vol, c_et, c_ag, c_may, f_via))
                conn.commit(); registrar_accion("LIBRO CAMPO", f"{prod} en {cc}"); st.rerun()
    with t2:
        cc_q = st.selectbox("Filtrar Sector", ["TODOS"] + CENTROS_COSTO)
        query = "SELECT * FROM libro_campo" if cc_q == "TODOS" else f"SELECT * FROM libro_campo WHERE sector='{cc_q}'"
        df_lc = pd.read_sql_query(query, conn)
        st.dataframe(df_lc, use_container_width=True)
        st.download_button("📥 PDF LIBRO", generar_pdf_blob(df_lc.drop(columns=['id']), "LIBRO DE CAMPO"), "libro_campo.pdf")
    conn.close()

def modulo_tesoreria():
    st.header("💸 TESORERÍA Y PAGOS")
    t1, t2, t3 = st.tabs(["🔴 PENDIENTES", "🏢 DEUDA POR PROVEEDOR", "📜 HISTORIAL DE PAGOS"]); conn = conectar_db()
    with t1:
        df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' AND nro_documento NOT LIKE '%_P' AND monto_total > 0 ORDER BY fecha_vencimiento ASC", conn)
        st.error(f"### DEUDA PENDIENTE GLOBAL: ${f_puntos(df_p['monto_total'].sum())}")
        
        # TABLA EN ROJO v10.9.5 (CORREGIDO .map())
        def color_rojo(val): return 'background-color: #FFCDD2; color: #B71C1C; font-weight: bold'
        st.dataframe(df_p.style.map(color_rojo).format({"monto_total": "${:,.0f}"}), use_container_width=True)
        
        st.download_button("📥 PDF PENDIENTES GLOBALES", generar_pdf_blob(df_p.drop(columns=['id']), "LISTADO DEUDA PENDIENTE GLOBAL"), "pendientes_global.pdf")
        st.divider()
        id_p = st.selectbox("ID Factura a Pagar", df_p['id']); met = st.selectbox("Método", ["Transferencia", "Efectivo", "Cheque"])
        if st.button("💰 MARCAR PAGADO"): conn.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (met, hoy, id_p)); conn.commit(); st.rerun()
    with t2:
        prvs = pd.read_sql_query("SELECT DISTINCT proveedor FROM facturas WHERE estado='Pendiente' AND nro_documento NOT LIKE '%_P'", conn)
        if not prvs.empty:
            p_sel = st.selectbox("Seleccione Proveedor", prvs['proveedor'])
            df_pr = pd.read_sql_query(f"SELECT nro_documento, fecha_vencimiento, monto_total FROM facturas WHERE proveedor='{p_sel}' AND estado='Pendiente' AND nro_documento NOT LIKE '%_P'", conn)
            st.info(f"### TOTAL DEUDA CON {p_sel}: ${f_puntos(df_pr['monto_total'].sum())}")
            st.dataframe(df_pr.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
            st.download_button(f"📥 PDF DEUDA {p_sel}", generar_pdf_blob(df_pr, f"ESTADO DE DEUDA: {p_sel}"), f"deuda_{p_sel}.pdf")
    with t3:
        df_h = pd.read_sql_query("SELECT nro_documento, proveedor, monto_total, metodo_pago, fecha_pago FROM facturas WHERE estado='Pagado' AND nro_documento NOT LIKE '%_P' ORDER BY fecha_pago DESC", conn)
        st.success(f"**💰 TOTAL PAGADO HISTÓRICO:** `${f_puntos(df_h['monto_total'].sum())}`")
        st.dataframe(df_h.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
        st.download_button("📥 PDF HISTORIAL PAGOS", generar_pdf_blob(df_h, "HISTORIAL DE PAGOS REALIZADOS", total_manual=df_h['monto_total'].sum()), "historial_pagos.pdf")
    conn.close()

def modulo_bodega():
    st.header("🏠 GESTIÓN DE BODEGA")
    t1, t2, t3 = st.tabs(["📊 STOCK", "🔄 SALIDA", "➕ REGISTRO"]); conn = conectar_db()
    with t1:
        df_s = pd.read_sql_query("SELECT id, producto, familia, stock, precio_medio FROM inventario", conn)
        st.dataframe(df_s.style.format({"stock": "{:,.2f}", "precio_medio": "${:,.0f}"}), use_container_width=True)
        if st.session_state['email'] == 'osvaldolira@laconcepcion.cl':
            id_b = st.selectbox("ID Editar", df_s['id']); n_st = st.number_input("Corregir Stock", 0.0)
            if st.button("✏️ CORREGIR") and st.text_input("Clave Master", type="password", key="cl_bod") == CLAVE_MAESTRA:
                conn.execute("UPDATE inventario SET stock=? WHERE id=?", (n_st, id_b)); conn.commit(); st.rerun()
    with t2:
        df_i = pd.read_sql_query("SELECT id, producto, precio_medio FROM inventario", conn)
        ps = st.selectbox("Insumo", df_i['id'].astype(str) + " - " + df_i['producto']); ct = st.number_input("Cantidad", 0.0)
        ccs = [cc for cc in CENTROS_COSTO if st.checkbox(cc, key=f"mb_{cc}")]
        if st.button("REGISTRAR EGRESO"):
            iid = int(ps.split(" - ")[0]); pmp = df_i[df_i['id']==iid]['precio_medio'].iloc[0]
            if ct > 0 and ccs:
                for c in ccs: conn.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado) VALUES (?,?,?,?,?,?)", (iid, "Salida", ct/len(ccs), hoy, c.upper(), (ct/len(ccs)*pmp)))
                conn.execute("UPDATE inventario SET stock = stock - ? WHERE id = ?", (ct, iid)); conn.commit(); st.rerun()
    with t3:
        with st.form("ni"):
            np, nf, ns, npr = st.text_input("Nombre"), st.selectbox("Familia", FAMILIAS_PRODUCTOS), st.number_input("Stock", 0.0), st.number_input("PMP", 0.0)
            if st.form_submit_button("CREAR"): conn.execute("INSERT INTO inventario (producto, familia, stock, precio_medio) VALUES (?,?,?,?)", (np, nf, ns, npr)); conn.commit(); st.rerun()
    conn.close()

def modulo_costos():
    st.header("💰 COSTOS CONSOLIDADOS")
    es_admin = (st.session_state.get('email') == 'osvaldolira@laconcepcion.cl')
    t1, t2 = st.tabs(["📊 RESUMEN", "🔧 AJUSTES MANUALES"]); conn = conectar_db()
    with t1:
        q = """SELECT UPPER(TRIM(cc)) as cc, SUM(CASE WHEN fuente = 'BODEGA' THEN val ELSE 0 END) as Insumos, SUM(CASE WHEN fuente = 'FACTURA' THEN val ELSE 0 END) as Gastos, SUM(CASE WHEN fuente = 'PETROLEO' THEN val ELSE 0 END) as Petroleo, SUM(CASE WHEN fuente = 'AJUSTE' THEN val ELSE 0 END) as Ajustes, SUM(val) as Total FROM (SELECT centro_costo as cc, valor_imputado as val, 'BODEGA' as fuente FROM movimientos UNION ALL SELECT centro_costo as cc, monto_imputado as val, 'FACTURA' as fuente FROM facturas WHERE nro_documento LIKE '%_P' UNION ALL SELECT centro_costo as cc, valor_imputado as val, 'PETROLEO' as fuente FROM petroleo WHERE tipo = 'Salida' UNION ALL SELECT centro_costo as cc, monto as val, 'AJUSTE' as fuente FROM ajustes_costos) WHERE cc != '' GROUP BY cc"""
        df_r = pd.read_sql_query(q, conn)
        if not df_r.empty:
            total_sum = df_r['Total'].sum()
            df_m = df_r.copy() if es_admin else df_r.drop(columns=['Ajustes'])
            fila_t = pd.DataFrame([{'cc': 'TOTAL GENERAL', 'Insumos': df_r['Insumos'].sum(), 'Gastos': df_r['Gastos'].sum(), 'Petroleo': df_r['Petroleo'].sum(), 'Ajustes': df_r['Ajustes'].sum(), 'Total': total_sum}])
            df_m = pd.concat([df_m, fila_t], ignore_index=True)
            st.dataframe(df_m.style.format({c: ("${:,.0f}" if c != 'cc' else str) for c in df_m.columns if c != 'cc'}), use_container_width=True)
            st.download_button("📥 PDF INFORME COSTOS", generar_pdf_blob(df_r, "RESUMEN DE COSTOS POR CUARTEL"), "costos.pdf")
    with t2:
        if es_admin:
            with st.form("aj_form"):
                cc_a, m_a, mo = st.selectbox("CC Ajuste", CENTROS_COSTO), st.number_input("Monto ($)"), st.text_input("Motivo")
                if st.form_submit_button("APLICAR"): conn.execute("INSERT INTO ajustes_costos (centro_costo, monto, fecha, motivo) VALUES (?,?,?,?)", (cc_a.upper(), m_a, hoy, mo)); conn.commit(); st.rerun()
    conn.close()

def modulo_seguridad():
    st.header("🕵️ SEGURIDAD Y AUDITORÍA")
    t1, t2 = st.tabs(["📜 BITÁCORA", "🔑 LOG ACCESOS"]); conn = conectar_db()
    with t1: st.dataframe(pd.read_sql_query("SELECT * FROM bitacora ORDER BY id DESC", conn), use_container_width=True)
    with t2: st.dataframe(pd.read_sql_query("SELECT * FROM log_accesos ORDER BY id DESC", conn), use_container_width=True)
    conn.close()

# =============================================================================
# 5. LOGIN Y NAVEGACIÓN
# =============================================================================

def login_page():
    inyectar_css()
    try:
        conn = conectar_db(); cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS log_accesos (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, fecha_hora DATETIME)")
        conn.commit(); conn.close()
    except: pass

    st.markdown("<h1 style='text-align: center; color: #1B5E20; margin-top: 50px;'>🚜 ERP LA CONCEPCIÓN</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        with st.form("login"):
            e, p = st.text_input("Usuario"), st.text_input("Clave", type="password")
            if st.form_submit_button("ACCEDER"):
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("SELECT email FROM usuarios WHERE email=? AND password=?", (e, hash_password(p)))
                if cursor.fetchone():
                    conn.execute("INSERT INTO log_accesos (email, fecha_hora) VALUES (?,?)", (e, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                    conn.commit(); conn.close()
                    st.session_state['logged_in'], st.session_state['email'] = True, e; st.rerun()
                else: st.error("Acceso Denegado")

st.set_page_config(page_title="ERP AGRICOLA v10.9.5", layout="wide")
inicializar_db()
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False

if not st.session_state['logged_in']: login_page()
else:
    if 'acceso_f_v1095_ok' not in st.session_state:
        try:
            conn = conectar_db()
            conn.execute("INSERT INTO log_accesos (email, fecha_hora) VALUES (?,?)", (st.session_state['email'], datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            conn.commit(); conn.close(); st.session_state['acceso_f_v1095_ok'] = True
        except: pass
    
    if 'init' not in st.session_state: descargar_de_drive(); st.session_state['init'] = True
    inyectar_css()
    with st.sidebar:
        st.markdown("## 🚜 ERP AGRICOLA")
        st.markdown(f"👤 <span class='sidebar-user'>{st.session_state['email']}</span>", unsafe_allow_html=True)
        st.markdown("<span style='color:green;'>🟢 SISTEMA CONECTADO</span>", unsafe_allow_html=True)
        st.divider()
        m_opts = { "🏠 DASHBOARD": "DASHBOARD", "⛽ PETRÓLEO": "Petróleo", "📦 COMPRAS": "Compras", "💸 TESORERÍA": "Tesoreria", "🏠 BODEGA": "Bodega", "🏡 EL ESPINO": "Espino", "📒 LIBRO DE CAMPO": "Libro de Campo", "💰 COSTOS": "Costos" }
        if st.session_state['email'] == 'osvaldolira@laconcepcion.cl': m_opts["🕵️ SEGURIDAD"] = "Seguridad"
        menu = m_opts[st.radio("MENU", list(m_opts.keys()))]
        st.divider()
        if st.session_state['email'] == 'osvaldolira@laconcepcion.cl' and st.button("🚀 SYNC DRIVE"): guardar_en_drive()
        if st.button("🚪 SALIR"): st.session_state.clear(); st.rerun()
    
    if menu == "DASHBOARD": modulo_dashboard()
    elif menu == "Petróleo": modulo_petroleo()
    elif menu == "Compras": modulo_compras()
    elif menu == "Tesoreria": modulo_tesoreria()
    elif menu == "Bodega": modulo_bodega()
    elif menu == "Espino": modulo_espino()
    elif menu == "Libro de Campo": modulo_libro_campo()
    elif menu == "Costos": modulo_costos()
    elif menu == "Seguridad": modulo_seguridad()
