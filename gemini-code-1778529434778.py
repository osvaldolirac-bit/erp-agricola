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
# 1. CONFIGURACIÓN, CONSTANTES Y MOTOR HORARIO (CHILE UTC-4)
# =============================================================================
ID_CARPETA_DRIVE = "12tjxWa_RVRP5YuYd2sypjBO8bPuyMqo6" 
NOMBRE_DB = 'erp_concepcion_v6.db'
CLAVE_MAESTRA = "2908" 
IMPUESTO_ESPECIFICO_LITRO = 75 

def hora_chile():
    """Retorna la hora actual ajustada a Chile Continental (UTC-4)"""
    return datetime.utcnow() - timedelta(hours=4)

hoy = hora_chile().date()

FAMILIAS_PRODUCTOS = ["FERTILIZANTE", "FERTILIZANTE FOLIAR", "HERBICIDA", "INSECTICIDA", "FUNGICIDA", "BIO ESTIMULANTE", "ACARICIDA", "REGULADOR DE CRECIMIENTO", "ADHERENTE / MOJANTE", "OTROS"]
CENTROS_COSTO = ["CEREZOS CORTE1", "CEREZOS CORTE2", "CIRUELOS", "NOGALES APARICION", "NOGALES CRUZ DEL SUR", "EL ESPINO", "OTROS"]

# MATRIZ DE PRORRATEO RRHH (Superficie Total 21.4 Ha)
PRORRATEO_RRHH = {
    "CEREZOS CORTE1": 0.0794,
    "CEREZOS CORTE2": 0.0794,
    "CIRUELOS": 0.3271,
    "NOGALES APARICION": 0.3271,
    "NOGALES CRUZ DEL SUR": 0.1870
}

# DATA DE INYECCIÓN EL ESPINO (65 REGISTROS HISTÓRICOS INTEGRALES)
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
# 2. MOTOR DE BASE DE DATOS Y UTILIDADES DRIVE
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
        try:
            query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
            lista = drive.ListFile({'q': query}).GetList()
            f = lista[0] if lista else drive.CreateFile({'title': NOMBRE_DB, 'parents': [{'id': ID_CARPETA_DRIVE}]})
            f.SetContentFile(NOMBRE_DB); f.Upload()
            st.toast("☁️ Nube Sincronizada", icon="✅")
        except: pass

def descargar_de_drive():
    drive = obtener_drive()
    if drive:
        try:
            query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
            lista = drive.ListFile({'q': query}).GetList()
            if lista: lista[0].GetContentFile(NOMBRE_DB)
        except: pass

def registrar_accion(accion, detalle):
    user = st.session_state.get('email', 'Desconocido')
    fecha_h = hora_chile().strftime('%Y-%m-%d %H:%M:%S')
    try:
        conn = conectar_db()
        conn.execute("INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)", (user, accion, detalle, fecha_h))
        conn.commit(); conn.close()
        st.cache_data.clear() 
    except: pass

def anclaje_sesion_definitivo():
    if st.session_state.get('logged_in'):
        tag = f"acceso_v112_{st.session_state['email']}_{hora_chile().strftime('%Y%m%d')}"
        if tag not in st.session_state:
            try:
                conn = conectar_db()
                f_h = hora_chile().strftime('%Y-%m-%d %H:%M:%S')
                conn.execute("INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)", 
                             (st.session_state['email'], "ACCESO", "Sesión Detectada (Chile Santiago)", f_h))
                conn.commit(); conn.close()
                st.session_state[tag] = True
                guardar_en_drive()
            except: pass

def inicializar_db():
    conn = conectar_db(); cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS facturas (id INTEGER PRIMARY KEY AUTOINCREMENT, nro_documento TEXT, proveedor TEXT, fecha_compra DATE, fecha_vencimiento DATE, monto_neto REAL, monto_total REAL, estado TEXT DEFAULT 'Pendiente', tipo TEXT DEFAULT 'Factura', metodo_pago TEXT, fecha_pago DATE, concepto TEXT, centro_costo TEXT, monto_imputado REAL DEFAULT 0)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS inventario (id INTEGER PRIMARY KEY AUTOINCREMENT, producto TEXT, familia TEXT, stock REAL DEFAULT 0, stock_minimo REAL DEFAULT 0, precio_medio REAL DEFAULT 0)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS movimientos (id INTEGER PRIMARY KEY AUTOINCREMENT, producto_id INTEGER, tipo TEXT, cantidad REAL, centro_costo TEXT, fecha DATE, valor_imputado REAL DEFAULT 0)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, password TEXT)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS petroleo (id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT, litros REAL, proveedor TEXT, monto_total_compra REAL, vehiculo TEXT, responsable TEXT, centro_costo TEXT, fecha DATE, valor_imputado REAL)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS bitacora (id INTEGER PRIMARY KEY AUTOINCREMENT, usuario TEXT, accion TEXT, detalle TEXT, fecha_hora DATETIME)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS ajustes_costos (id INTEGER PRIMARY KEY AUTOINCREMENT, centro_costo TEXT, monto REAL, fecha DATE, motivo TEXT)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS gastos_espino (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha DATE, documento TEXT, item TEXT, monto REAL)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS libro_campo (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha DATE, n_orden TEXT, sector TEXT, est_fenologico TEXT, especie TEXT, motivo TEXT, producto TEXT, n_aplicacion INTEGER, ingrediente TEXT, dosis REAL, unidad_dosis TEXT, vol_total REAL, gasto_total REAL, unidad_gasto TEXT, tractor TEXT, maquina TEXT, aplicadores TEXT, car_etiqueta INTEGER, car_agenda INTEGER, car_mayor INTEGER, fecha_viable DATE)""")
    
    # NUEVAS TABLAS RRHH v11.2.0
    cursor.execute("""CREATE TABLE IF NOT EXISTS personal (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT, rut TEXT UNIQUE, cargo TEXT, estado TEXT DEFAULT 'Activo')""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS pagos_rrhh (id INTEGER PRIMARY KEY AUTOINCREMENT, trabajador_id INTEGER, mes TEXT, anio INTEGER, liquido REAL, leyes_sociales REAL, costo_empresa REAL, tipo TEXT, fecha_registro DATE)""")
    
    usuarios = [('osvaldolira@laconcepcion.cl', hash_password('9083')), ('secretaria@laconcepcion.cl', hash_password('9111'))]
    for u, p in usuarios: cursor.execute("INSERT OR IGNORE INTO usuarios (email, password) VALUES (?,?)", (u, p))
    cursor.execute("SELECT COUNT(*) FROM gastos_espino")
    if cursor.fetchone()[0] == 0: cursor.executemany("INSERT INTO gastos_espino (fecha, documento, item, monto) VALUES (?,?,?,?)", DATA_ESP_HISTORICA)
    conn.commit(); conn.close()

# =============================================================================
# 3. UTILIDADES: INDICADORES Y PDF
# =============================================================================

@st.cache_data(ttl=3600)
def obtener_indicadores():
    try:
        r = requests.get("https://mindicador.cl/api", timeout=5).json()
        return {'uf': f"${r['uf']['valor']:,.2f}", 'utm': f"${r['utm']['valor']:,.0f}", 'dolar': f"${r['dolar']['valor']:,.2f}", 'euro': f"${r['euro']['valor']:,.2f}"}
    except: return {'uf': '$37.942,12', 'utm': '$66.628', 'dolar': '$945,50', 'euro': '$1.024,30'}

def generar_pdf_blob(df, titulo, incluir_precios=True, total_manual=None, modo_petroleo=False, orden_asc=False, saldo_petroleo=None):
    try:
        pdf = FPDF(); pdf.add_page(); pdf.set_font("Helvetica", "B", 16)
        if modo_petroleo and saldo_petroleo is not None:
            pdf.cell(100, 10, "AGRICOLA LA CONCEPCIÓN", ln=0); pdf.set_font("Helvetica", "B", 10); pdf.cell(90, 10, f"SALDO ESTANQUE: {f_decimal(saldo_petroleo)} L", ln=1, align="R")
        else: pdf.cell(0, 10, "AGRICOLA LA CONCEPCIÓN", ln=1, align="C")
        pdf.set_font("Helvetica", "B", 12); pdf.cell(0, 10, titulo, ln=True, align="C"); pdf.ln(5); pdf.set_font("Helvetica", "B", 8)
        df_p = df.copy()
        if orden_asc and 'fecha' in [c.lower() for c in df_p.columns]:
            cf = [c for c in df_p.columns if c.lower() == 'fecha'][0]; df_p[cf] = pd.to_datetime(df_p[cf]); df_p = df_p.sort_values(by=cf, ascending=True); df_p[cf] = df_p[cf].dt.date
        t_sum = total_manual
        if t_sum is None:
            cols_m = ["monto", "total", "monto_total", "valor_imputado", "gasto_total", "monto_imputado", "costo_empresa"]
            for c in df_p.columns:
                if any(x in c.lower() for x in cols_m):
                    try: t_sum = (t_sum or 0) + df_p[c].sum()
                    except: pass
        if modo_petroleo: df_p = df_p.drop(columns=[c for c in df_p.columns if any(x in c.lower() for x in ["imputado", "valor", "monto", "precio"])]); incluir_precios = False
        cols = df_p.columns; w = 190 / len(cols)
        for col in cols: pdf.cell(w, 8, str(col).upper(), border=1, align="C")
        pdf.ln(); pdf.set_font("Helvetica", "", 7)
        for _, row in df_p.iterrows():
            for i, item in enumerate(row):
                col_n = df_p.columns[i].lower()
                if any(x in col_n for x in ["monto", "total", "valor", "costo", "liquido", "leyes"]): val = f_puntos(item)
                elif any(x in col_n for x in ["litros", "cantidad", "stock", "volumen", "dosis"]): val = f_decimal(item)
                else: val = str(item)
                pdf.cell(w, 7, val[:25], border=1)
            pdf.ln()
        if incluir_precios and t_sum is not None:
            pdf.set_font("Helvetica", "B", 9); pdf.cell(w*(len(cols)-1), 8, "TOTAL FINAL:", border=1, align="R"); pdf.cell(w, 8, f"${f_puntos(t_sum)}", border=1, align="L")
        return pdf.output(dest="S").encode("latin-1")
    except: return None

def inyectar_css():
    st.markdown(f"""<style>
        .main {{ background-color: #f4f7f6; }}
        .stMetric {{ background-color: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); border-left: 6px solid #2E7D32; }}
        [data-testid="stMetricValue"] {{ font-size: 1.5rem !important; font-weight: 800; color: #1B5E20; }}
        .sidebar-user {{ color: #0D47A1 !important; font-weight: 900; font-size: 1.1rem; }}
        .banner-econ {{ background: #0D47A1; color: white; padding: 10px; border-radius: 8px; text-align: center; font-weight: bold; margin-bottom: 20px; font-size: 0.9rem; }}
        .saldo-banner {{ background: #E8F5E9; color: #1B5E20; padding: 15px; border-radius: 10px; border: 2px solid #2E7D32; text-align: center; margin-bottom: 20px; font-size: 1.4rem; font-weight: 800; }}
        .alert-naranja {{ background: #FFF3E0; color: #E65100; padding: 15px; border-radius: 10px; border: 2px solid #FFB74D; margin-bottom: 10px; font-weight: bold; text-align: center; }}
        .alert-roja {{ background: #FFEBEE; color: #B71C1C; padding: 15px; border-radius: 10px; border: 2px solid #E57373; margin-bottom: 10px; font-weight: bold; text-align: center; animation: pulse 2s infinite; }}
        @keyframes pulse {{ 0% {{ opacity: 1; }} 50% {{ opacity: 0.6; }} 100% {{ opacity: 1; }} }}
        div[data-testid="stRadio"] label {{ text-transform: uppercase; font-weight: 700; font-size: 0.85rem; }}
        </style>""", unsafe_allow_html=True)
    if st.session_state.get('logged_in') and st.session_state.get('email') != 'osvaldolira@laconcepcion.cl':
        st.markdown("<style>header {visibility: hidden;} #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display:none;}</style>", unsafe_allow_html=True)

# =============================================================================
# 4. MÓDULOS DEL SISTEMA
# =============================================================================

def modulo_dashboard():
    ind = obtener_indicadores()
    conn = conectar_db()
    
    # LÓGICA DE ALERTAS RRHH v11.2.0
    mes_actual = hora_chile().strftime('%m')
    anio_actual = hora_chile().year
    ultimo_dia_mes = (hora_chile().replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    
    # Trabajadores activos
    t_activos = pd.read_sql_query("SELECT id FROM personal WHERE estado='Activo'", conn)
    n_activos = len(t_activos)
    
    # Imputaciones del mes actual
    imputados_hoy = pd.read_sql_query(f"SELECT trabajador_id FROM pagos_rrhh WHERE mes='{mes_actual}' AND anio={anio_actual}", conn)
    n_faltantes_hoy = n_activos - len(imputados_hoy)
    
    # Alerta Preventiva (Último día)
    if hora_chile().date() == ultimo_dia_mes.date() and n_faltantes_hoy > 0:
        st.markdown(f'<div class="alert-naranja">🟠 CIERRE DE MES: Faltan {n_faltantes_hoy} trabajadores por imputar sueldos en RRHH.</div>', unsafe_allow_html=True)
    
    # Alerta Crítica (Mes vencido sin datos completos)
    if hora_chile().day <= 10: # Primeros 10 días del mes
        mes_pasado_dt = hora_chile().replace(day=1) - timedelta(days=1)
        mes_p = mes_pasado_dt.strftime('%m')
        anio_p = mes_pasado_dt.year
        imputados_p = pd.read_sql_query(f"SELECT trabajador_id FROM pagos_rrhh WHERE mes='{mes_p}' AND anio={anio_p}", conn)
        faltan_p = n_activos - len(imputados_p)
        if faltan_p > 0:
            st.markdown(f'<div class="alert-roja">🔴 ALERTA CRÍTICA: Mes anterior incompleto. Faltan {faltan_p} trabajadores por imputar.</div>', unsafe_allow_html=True)

    st.markdown(f'<div class="banner-econ">📈 INDICADORES ECONÓMICOS: UF: {ind["uf"]} | UTM: {ind["utm"]} | DÓLAR: {ind["dolar"]} | EURO: {ind["euro"]}</div>', unsafe_allow_html=True)
    st.markdown("<h1 style='text-align: center; color: #1B5E20;'>🚜 ERP AGRICOLA LA CONCEPCIÓN</h1>", unsafe_allow_html=True)
    
    df_f = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente' AND nro_documento NOT LIKE '%_P'", conn)
    df_p_c = pd.read_sql_query("SELECT SUM(litros) as l FROM petroleo WHERE tipo='Carga' OR (tipo='Ajuste Manual' AND litros > 0)", conn)
    df_p_s = pd.read_sql_query("SELECT SUM(litros) as l FROM petroleo WHERE tipo='Salida' OR (tipo='Ajuste Manual' AND litros < 0)", conn)
    saldo_pet = (df_p_c['l'].fillna(0).iloc[0]) - abs(df_p_s['l'].fillna(0).iloc[0])
    
    m1, m2, m3, m4, m5 = st.columns(5)
    with m1: st.metric("💰 DEUDA TOTAL", f"${f_puntos(df_f['monto_total'].sum())}")
    pdia = hoy.replace(day=1); dcrit = df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < pdia]['monto_total'].sum()
    with m2: st.markdown(f"<div class='stMetric'><small>🔥 MESES ANTERIORES</small><br><span style='color:#d32f2f; font-size:1.8rem; font-weight:700;'>${f_puntos(dcrit)}</span></div>", unsafe_allow_html=True)
    vcount = len(df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < hoy])
    with m3: st.markdown(f"<div class='stMetric'><small>⚠️ VENCIDAS</small><br><span style='color:#1976d2; font-size:1.8rem; font-weight:700;'>{vcount} docs</span></div>", unsafe_allow_html=True)
    with m4: st.metric("📄 PENDIENTES", f"{len(df_f)}")
    with m5: st.metric("⛽ PETRÓLEO NETO", f"{f_decimal(saldo_pet)} L")
    
    st.divider(); c_izq, c_der = st.columns([1.6, 1])
    with c_izq:
        st.markdown("### 📊 GASTOS POR CUARTEL")
        q = """SELECT UPPER(TRIM(cc)) as cc, SUM(val) as total FROM (SELECT centro_costo as cc, valor_imputado as val FROM movimientos WHERE tipo LIKE 'Salida%' UNION ALL SELECT centro_costo as cc, monto_imputado as val FROM facturas WHERE nro_documento LIKE '%_P' UNION ALL SELECT centro_costo as cc, valor_imputado as val FROM petroleo WHERE tipo = 'Salida' UNION ALL SELECT centro_costo as cc, monto as val FROM ajustes_costos UNION ALL SELECT centro_costo as cc, monto_imputado as val FROM facturas WHERE nro_documento LIKE '%_RRHH') WHERE cc != '' AND cc != 'BODEGA' GROUP BY cc"""
        dfc = pd.read_sql_query(q, conn)
        if not dfc.empty: st.dataframe(dfc.style.format({"total": "${:,.0f}"}), use_container_width=True)
    with c_der:
        st.markdown("### 📅 PROYECCIÓN PAGOS")
        for i in range(4):
            fp = (datetime.now().replace(day=1) + timedelta(days=i*31)).replace(day=1)
            totalm = df_f[(pd.to_datetime(df_f['fecha_vencimiento']).dt.month == fp.month) & (pd.to_datetime(df_f['fecha_vencimiento']).dt.year == fp.year)]['monto_total'].sum() if not df_f.empty else 0
            st.markdown(f"<div style='background:white; padding:10px; border-radius:8px; margin-bottom:5px; border-right: 5px solid #1976d2; display:flex; justify-content:space-between;'><b>{fp.strftime('%B %Y').upper()}</b> <span>${f_puntos(totalm)}</span></div>", unsafe_allow_html=True)
    conn.close()

def modulo_rrhh():
    st.header("👥 RECURSOS HUMANOS"); conn = conectar_db()
    t1, t2, t3 = st.tabs(["📋 FICHAS PERSONAL", "💸 CARGA REMUNERACIONES", "📜 HISTORIAL PAGOS"])
    
    with t1:
        with st.form("f_ficha"):
            c1, c2, c3 = st.columns(3)
            n, r, car = c1.text_input("Nombre Completo"), c2.text_input("RUT"), c3.text_input("Cargo")
            if st.form_submit_button("GUARDAR TRABAJADOR"):
                conn.execute("INSERT INTO personal (nombre, rut, cargo) VALUES (?,?,?)", (n, r, car))
                conn.commit(); registrar_accion("RRHH", f"Nuevo trabajador {n}"); guardar_en_drive(); st.rerun()
        df_p = pd.read_sql_query("SELECT * FROM personal", conn)
        st.dataframe(df_p, use_container_width=True)

    with t2:
        df_activos = pd.read_sql_query("SELECT id, nombre FROM personal WHERE estado='Activo'", conn)
        if not df_activos.empty:
            with st.form("f_pago"):
                t_sel = st.selectbox("Trabajador", df_activos['id'].astype(str) + " - " + df_activos['nombre'])
                tid = int(t_sel.split(" - ")[0]); tnom = t_sel.split(" - ")[1]
                c1, c2, c3 = st.columns(3)
                mes = c1.selectbox("Mes", ["01","02","03","04","05","06","07","08","09","10","11","12"], index=int(hora_chile().month)-1)
                anio = c2.number_input("Año", value=hora_chile().year)
                tipo = c3.selectbox("Tipo", ["Sueldo Mensual", "Bono", "Finiquito", "Anticipo"])
                licencia = st.checkbox("TRABAJADOR CON LICENCIA MÉDICA (Costo $0)")
                liq = st.number_input("Sueldo Líquido ($)", 0.0) if not licencia else 0.0
                leyes = st.number_input("Leyes Sociales (Previred $)", 0.0) if not licencia else 0.0
                if st.form_submit_button("REGISTRAR Y PRORRATEAR"):
                    total = liq + leyes
                    conn.execute("INSERT INTO pagos_rrhh (trabajador_id, mes, anio, liquido, leyes_sociales, costo_empresa, tipo, fecha_registro) VALUES (?,?,?,?,?,?,?,?)", 
                                 (tid, mes, anio, liq, leyes, total, tipo, hoy))
                    # PRORRATEO AUTOMÁTICO v11.2.0
                    doc_id = f"RRHH_{tid}_{mes}{anio}"
                    for cc, porc in PRORRATEO_RRHH.items():
                        conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, monto_total, tipo, centro_costo, monto_imputado, estado) VALUES (?,?,?,?,?,?,?,?)",
                                     (doc_id+"_RRHH", tnom, f"{anio}-{mes}-01", 0, 'RRHH', cc, total*porc, 'Pagado'))
                    conn.commit(); registrar_accion("RRHH PAGO", f"{tnom} Mes {mes}"); guardar_en_drive(); st.rerun()
        else: st.warning("Debe registrar trabajadores en la pestaña Fichas.")

    with t3:
        df_h = pd.read_sql_query("SELECT p.nombre, h.mes, h.anio, h.liquido, h.leyes_sociales, h.costo_empresa, h.tipo FROM pagos_rrhh h JOIN personal p ON h.trabajador_id = p.id ORDER BY h.anio DESC, h.mes DESC", conn)
        st.dataframe(df_h.style.format({"liquido": "${:,.0f}", "leyes_sociales": "${:,.0f}", "costo_empresa": "${:,.0f}"}), use_container_width=True)
        st.download_button("📥 PDF HISTORIAL RRHH", generar_pdf_blob(df_h, "HISTORIAL REMUNERACIONES RRHH"), "rrhh.pdf")
    conn.close()

def modulo_petroleo():
    st.header("⛽ GESTIÓN DE PETRÓLEO"); conn = conectar_db()
    df_p_c = pd.read_sql_query("SELECT SUM(litros) as l FROM petroleo WHERE tipo='Carga' OR (tipo='Ajuste Manual' AND litros > 0)", conn)
    df_p_s = pd.read_sql_query("SELECT SUM(litros) as l FROM petroleo WHERE tipo='Salida' OR (tipo='Ajuste Manual' AND litros < 0)", conn)
    saldo_actual = (df_p_c['l'].fillna(0).iloc[0]) - abs(df_p_s['l'].fillna(0).iloc[0])
    st.markdown(f'<div class="saldo-banner">🛢️ SALDO ACTUAL EN TANQUE: {f_decimal(saldo_actual)} LITROS</div>', unsafe_allow_html=True)
    tabs_opts = ["📥 CARGA", "🚜 SALIDA", "📊 HISTORIAL"]
    if st.session_state['email'] == 'osvaldolira@laconcepcion.cl': tabs_opts.append("⚙️ AJUSTE MANUAL")
    t_sel = st.tabs(tabs_opts)
    with t_sel[0]:
        with st.form("p_c"):
            l, mt, f = st.number_input("Litros Carga", 0.0), st.number_input("Total Bruto ($)", 0.0), st.date_input("Fecha Carga", hoy)
            if st.form_submit_button("REGISTRAR CARGA"):
                neto = (mt / 1.19) - (l * IMPUESTO_ESPECIFICO_LITRO)
                conn.execute("INSERT INTO petroleo (tipo, litros, monto_total_compra, fecha) VALUES (?,?,?,?)", ("Carga", l, neto, f))
                conn.commit(); registrar_accion("CARGA PETROLEO", f"{l} Lts"); guardar_en_drive(); st.rerun()
    with t_sel[1]:
        with st.form("p_s"):
            ls, fs = st.number_input("Litros Salida", 0.0), st.date_input("Fecha Salida", hoy)
            v, r = st.text_input("Vehículo"), st.text_input("Responsable")
            ccs = [cc for cc in CENTROS_COSTO if st.checkbox(cc, key=f"ps_{cc}")]
            if st.form_submit_button("REGISTRAR SALIDA"):
                df_calc = pd.read_sql_query("SELECT SUM(litros) as l, SUM(monto_total_compra) as m FROM petroleo WHERE tipo='Carga'", conn)
                pmp = (df_calc['m'].iloc[0] / df_calc['l'].iloc[0]) if df_calc['l'].iloc[0] > 0 else 0
                if ccs and ls > 0:
                    for c in ccs: conn.execute("INSERT INTO petroleo (tipo, litros, vehiculo, responsable, centro_costo, fecha, valor_imputado) VALUES (?,?,?,?,?,?,?)", ("Salida", ls/len(ccs), v, r, c.upper(), fs, (ls/len(ccs)*pmp)))
                    conn.commit(); registrar_accion("SALIDA PETROLEO", f"{ls} Lts"); guardar_en_drive(); st.rerun()
    with t_sel[2]:
        dfp = pd.read_sql_query("SELECT id, fecha, tipo, litros, vehiculo, responsable, centro_costo, valor_imputado FROM petroleo ORDER BY id DESC", conn)
        st.dataframe(dfp.style.format({"litros": "{:,.2f}", "valor_imputado": "${:,.0f}"}), use_container_width=True)
        st.download_button("📥 PDF HISTORIAL", generar_pdf_blob(dfp, "HISTORIAL PETROLEO", modo_petroleo=True, saldo_petroleo=saldo_actual), "petroleo.pdf")
        if st.session_state['email'] == 'osvaldolira@laconcepcion.cl':
            idp = st.selectbox("ID borrar", dfp['id']); clv = st.text_input("Clave Master", type="password", key="cl_p")
            if st.button("🗑️ ELIMINAR"):
                if clv == CLAVE_MAESTRA: conn.execute("DELETE FROM petroleo WHERE id=?", (idp,)); conn.commit(); registrar_accion("DEL PETROLEO", f"ID {idp}"); guardar_en_drive(); st.rerun()
    conn.close()

def modulo_compras():
    st.header("📦 COMPRAS E HISTORIAL"); conn = conectar_db()
    tabs_opts = ["➕ INSUMOS", "💸 GASTOS VARIOS", "🔍 HISTORIAL"]
    if st.session_state['email'] == 'osvaldolira@laconcepcion.cl': tabs_opts.append("🛠️ MODIFICAR / ELIMINAR")
    t_sel = st.tabs(tabs_opts)
    with t_sel[0]:
        c1, c2 = st.columns(2); nro, prov, fe, fv = c1.text_input("N° Factura"), c1.text_input("Proveedor"), c2.date_input("Fecha Emisión"), c2.date_input("Vencimiento")
        dfi = pd.read_sql_query("SELECT id, producto FROM inventario", conn)
        ps = st.selectbox("Insumo", dfi['id'].astype(str) + " - " + dfi['producto']) if not dfi.empty else None
        ct, pr = st.number_input("Cantidad", 0.0), st.number_input("Precio Neto Unit.", 0.0)
        if st.button("➕ AGREGAR"):
            if 'car' not in st.session_state: st.session_state['car'] = []
            st.session_state['car'].append({'id': int(ps.split(" - ")[0]), 'n': ps.split(" - ")[1], 'c': ct, 'p': pr, 't': ct*pr}); st.rerun()
        if st.session_state.get('car'):
            st.table(pd.DataFrame(st.session_state['car']))
            if st.button("💾 GUARDAR FACTURA COMPLETA"):
                total_bruto = pd.DataFrame(st.session_state['car'])['t'].sum() * 1.19
                conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total) VALUES (?,?,?,?,?)", (nro, prov, fe, fv, total_bruto))
                for i in st.session_state['car']:
                    cur = conn.execute("SELECT stock, precio_medio FROM inventario WHERE id=?", (i['id'],)).fetchone()
                    npmp = ((cur[0]*cur[1]) + (i['c']*i['p'])) / (cur[0]+i['c']) if (cur[0]+i['c']) > 0 else i['p']
                    conn.execute("UPDATE inventario SET stock = stock + ?, precio_medio = ? WHERE id = ?", (i['c'], npmp, i['id']))
                conn.commit(); st.session_state['car'] = []; registrar_accion("COMPRA", nro); guardar_en_drive(); st.rerun()
    with t_sel[1]:
        pg, ng, fg1, fg2 = st.text_input("Proveedor Gasto", key="pg"), st.text_input("N° Doc", key="ng"), st.date_input("Fecha Gasto", hoy), st.date_input("Vence", hoy)
        selcc = [cc for cc in CENTROS_COSTO if st.checkbox(cc, key=f"gv_{cc}")]
        mt = st.number_input("Monto Bruto ($)", 0.0); iva = st.radio("Imputar Bruto?", ["SI", "NO (NETO)"])
        if st.button("💾 GUARDAR GASTO VARIO"):
            imp = mt if iva == "SI" else mt/1.19
            conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo) VALUES (?,?,?,?,?,?)", (ng, pg, fg1, fg2, mt, 'Gasto Vario'))
            for c in selcc: conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, centro_costo, monto_imputado) VALUES (?,?,?,?,?,?,?,?)", (ng+"_P", pg, fg1, fg2, 0, 'Gasto Vario', c.upper(), imp/len(selcc)))
            conn.commit(); registrar_accion("GASTO VARIO", ng); guardar_en_drive(); st.rerun()
    with t_sel[2]:
        dfh = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_compra, monto_total FROM facturas WHERE monto_total > 0 AND nro_documento NOT LIKE '%_P' ORDER BY id DESC", conn)
        st.dataframe(dfh.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
    if st.session_state['email'] == 'osvaldolira@laconcepcion.cl':
        with t_sel[3]:
            idm = st.selectbox("ID Factura", dfh['id']); clvm = st.text_input("Clave Master", type="password")
            if st.button("🗑️ ELIMINAR DOCUMENTO"):
                if clvm == CLAVE_MAESTRA:
                    conn.execute("DELETE FROM facturas WHERE id=?", (idm,))
                    conn.commit(); registrar_accion("DEL COMPRA", str(idm)); guardar_en_drive(); st.rerun()
    conn.close()

def modulo_espino():
    st.header("🏡 EL ESPINO - GESTIÓN DE GASTOS"); conn = conectar_db()
    t1, t2 = st.tabs(["➕ REGISTRO", "📜 HISTORIAL"])
    with t1:
        with st.form("esp_f"):
            f, d, it, mt = st.date_input("Fecha", hoy), st.text_input("Doc"), st.text_input("Descripción"), st.number_input("Monto ($)", 0.0)
            if st.form_submit_button("💾 GUARDAR"):
                conn.execute("INSERT INTO gastos_espino (fecha, documento, item, monto) VALUES (?,?,?,?)", (f, d, it, mt))
                conn.commit(); registrar_accion("EL ESPINO", it); guardar_en_drive(); st.rerun()
    with t2:
        dfh = pd.read_sql_query("SELECT * FROM gastos_espino ORDER BY fecha DESC", conn)
        st.dataframe(dfh.style.format({"monto": "${:,.0f}"}), use_container_width=True)
        st.download_button("📥 PDF EL ESPINO", generar_pdf_blob(dfh.drop(columns=['id']), "GASTOS EL ESPINO", orden_asc=True), "espino.pdf")
    conn.close()

def modulo_libro_campo():
    st.header("📒 LIBRO DE CAMPO"); conn = conectar_db()
    t1, t2 = st.tabs(["📥 INGRESO", "📜 HISTORIAL"])
    with t1:
        with st.form("lc_form"):
            c1, c2, c3 = st.columns(3)
            f, ordn, cc = st.date_input("Fecha App", hoy), st.text_input("N° Orden"), st.selectbox("Sector", CENTROS_COSTO)
            esp, prod, nap = st.text_input("Especie"), st.text_input("Producto"), st.number_input("N° App", 1)
            ing, dos, vol = st.text_input("Ingrediente"), st.number_input("Dosis", 0.0), st.number_input("Volumen", 0.0)
            cet, cag = st.number_input("Carencia Etiq", 0), st.number_input("Carencia Agenda", 0)
            cmay = max(cet, cag); fv = f + timedelta(days=cmay)
            if st.form_submit_button("💾 GUARDAR"):
                conn.execute("INSERT INTO libro_campo (fecha, n_orden, sector, especie, producto, n_aplicacion, ingrediente, dosis, vol_total, car_etiqueta, car_agenda, car_mayor, fecha_viable) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (f, ordn, cc, esp, prod, nap, ing, dos, vol, cet, cag, cmay, fv))
                conn.commit(); registrar_accion("LIBRO CAMPO", prod); guardar_en_drive(); st.rerun()
    with t2:
        dflc = pd.read_sql_query("SELECT * FROM libro_campo ORDER BY fecha DESC", conn)
        st.dataframe(dflc, use_container_width=True)
    conn.close()

def modulo_tesoreria():
    st.header("💸 TESORERÍA Y PAGOS"); conn = conectar_db()
    t1, t2, t3 = st.tabs(["🔴 PENDIENTES", "🏢 DEUDA PROVEEDOR", "📜 HISTORIAL AUDITABLE"])
    with t1:
        dfp = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' AND nro_documento NOT LIKE '%_P' AND monto_total > 0 ORDER BY fecha_vencimiento ASC", conn)
        st.warning(f"### DEUDA PENDIENTE GLOBAL: ${f_puntos(dfp['monto_total'].sum())}")
        def highlight_v(row):
            isv = pd.to_datetime(row['fecha_vencimiento']).date() < hoy
            return ['background-color: #FFCDD2; color: #B71C1C; font-weight: bold' if isv else '' for _ in row]
        st.dataframe(dfp.style.apply(highlight_v, axis=1).format({"monto_total": "${:,.0f}"}), use_container_width=True)
        st.divider(); idp = st.selectbox("ID Pago", dfp['id']); metp = st.selectbox("Método", ["Transferencia", "Efectivo", "Cheque"])
        if st.button("💰 PAGAR"):
            conn.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (metp, hoy, idp))
            conn.commit(); registrar_accion("PAGO", f"ID {idp}"); guardar_en_drive(); st.rerun()
    with t3:
        c1, c2, c3 = st.columns([2, 1, 1.5]); bsq = c1.text_input("🔍 Buscar")
        met = c2.selectbox("💳 Método", ["TODOS", "Transferencia", "Efectivo", "Cheque"])
        fi, ff = c3.date_input("Desde", hoy - timedelta(days=30)), c3.date_input("Hasta", hoy)
        qh = f"SELECT nro_documento, proveedor, monto_total, metodo_pago, fecha_pago FROM facturas WHERE estado='Pagado' AND nro_documento NOT LIKE '%_P' AND fecha_pago BETWEEN '{fi}' AND '{ff}'"
        if bsq: qh += f" AND (nro_documento LIKE '%{bsq}%' OR proveedor LIKE '%{bsq}%')"
        if met != "TODOS": qh += f" AND metodo_pago='{met}'"
        dfh = pd.read_sql_query(qh, conn); st.dataframe(dfh.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
        st.download_button("📥 PDF RESULTADOS", generar_pdf_blob(dfh, "AUDITORÍA DE PAGOS", total_manual=dfh['monto_total'].sum()), "auditoria_pagos.pdf")
    conn.close()

def modulo_bodega():
    st.header("🏠 GESTIÓN DE BODEGA"); conn = conectar_db()
    t1, t2, t3 = st.tabs(["📊 STOCK", "🔄 SALIDA", "🔍 CONSULTA CC"])
    with t1:
        dfs = pd.read_sql_query("SELECT id, producto, familia, stock, precio_medio FROM inventario", conn); st.dataframe(dfs.style.format({"stock": "{:,.2f}", "precio_medio": "${:,.0f}"}), use_container_width=True)
    with t2:
        dfi = pd.read_sql_query("SELECT id, producto, precio_medio FROM inventario", conn); ps = st.selectbox("Insumo", dfi['id'].astype(str) + " - " + dfi['producto']); ct = st.number_input("Cant", 0.0); ccs = [cc for cc in CENTROS_COSTO if st.checkbox(cc, key=f"mb_{cc}")]
        if st.button("REGISTRAR EGRESO"):
            iid = int(ps.split(" - ")[0]); pmp = dfi[dfi['id']==iid]['precio_medio'].iloc[0]
            if ct > 0 and ccs:
                for c in ccs: conn.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado) VALUES (?,?,?,?,?,?)", ("Salida", ct/len(ccs), hoy, c.upper(), (ct/len(ccs)*pmp)))
                conn.execute("UPDATE inventario SET stock = stock - ? WHERE id = ?", (ct, iid)); conn.commit(); registrar_accion("SALIDA BODEGA", ps); guardar_en_drive(); st.rerun()
    conn.close()

def modulo_costos():
    st.header("💰 COSTOS CONSOLIDADOS"); conn = conectar_db()
    q = """SELECT UPPER(TRIM(cc)) as cc, SUM(CASE WHEN fuente = 'BODEGA' THEN val ELSE 0 END) as Insumos, SUM(CASE WHEN fuente = 'FACTURA' THEN val ELSE 0 END) as Gastos, SUM(CASE WHEN fuente = 'PETROLEO' THEN val ELSE 0 END) as Petroleo, SUM(val) as Total FROM (SELECT centro_costo as cc, valor_imputado as val, 'BODEGA' as fuente FROM movimientos UNION ALL SELECT centro_costo as cc, monto_imputado as val, 'FACTURA' as fuente FROM facturas WHERE nro_documento LIKE '%_P' OR nro_documento LIKE '%_RRHH' UNION ALL SELECT centro_costo as cc, valor_imputado as val, 'PETROLEO' as fuente FROM petroleo WHERE tipo = 'Salida') WHERE cc != '' GROUP BY cc"""
    dfr = pd.read_sql_query(q, conn)
    st.dataframe(dfr.style.format({c: ("${:,.0f}" if c != 'cc' else str) for c in dfr.columns if c != 'cc'}), use_container_width=True)
    conn.close()

def modulo_seguridad():
    st.header("🕵️ SEGURIDAD Y AUDITORÍA"); conn = conectar_db()
    c1, c2 = st.columns(2); fi = c1.date_input("Bitácora Desde", hoy - timedelta(days=7)); ff = c2.date_input("Bitácora Hasta", hoy)
    dfb = pd.read_sql_query(f"SELECT usuario, accion, detalle, fecha_hora FROM bitacora WHERE DATE(fecha_hora) BETWEEN '{fi}' AND '{ff}' ORDER BY id DESC", conn)
    st.dataframe(dfb, use_container_width=True)
    st.download_button("📥 PDF BITÁCORA", generar_pdf_blob(dfb, f"HISTORIAL SEGURIDAD ({fi} a {ff})"), "seguridad.pdf")
    conn.close()

def login_page():
    inyectar_css(); st.markdown("<h1 style='text-align: center; color: #1B5E20; margin-top: 50px;'>🚜 ERP AGRICOLA LA CONCEPCIÓN</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        with st.form("login"):
            e, p = st.text_input("Usuario"), st.text_input("Clave", type="password")
            if st.form_submit_button("ACCEDER"):
                conn = conectar_db(); cursor = conn.cursor(); cursor.execute("SELECT email FROM usuarios WHERE email=? AND password=?", (e, hash_password(p)))
                if cursor.fetchone(): st.session_state['logged_in'], st.session_state['email'] = True, e; st.rerun()
                else: st.error("Acceso Denegado")

st.set_page_config(page_title="ERP AGRICOLA v11.2.0", layout="wide")
inicializar_db()
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if not st.session_state['logged_in']: descargar_de_drive(); login_page()
else:
    anclaje_sesion_definitivo()
    if 'init' not in st.session_state: descargar_de_drive(); st.session_state['init'] = True
    inyectar_css()
    with st.sidebar:
        st.markdown("## 🚜 ERP AGRICOLA LA CONCEPCIÓN")
        st.markdown(f"👤 <span class='sidebar-user'>{st.session_state['email']}</span>", unsafe_allow_html=True)
        m_opts = { "🏠 DASHBOARD": "DASHBOARD", "⛽ PETRÓLEO": "Petróleo", "📦 COMPRAS": "Compras", "💸 TESORERÍA": "Tesoreria", "👥 RRHH": "RRHH", "🏠 BODEGA": "Bodega", "🏡 EL ESPINO": "Espino", "📒 LIBRO DE CAMPO": "Libro de Campo", "💰 COSTOS": "Costos" }
        if st.session_state['email'] == 'osvaldolira@laconcepcion.cl': m_opts["🕵️ SEGURIDAD"] = "Seguridad"
        menu = m_opts[st.radio("MENÚ", list(m_opts.keys()))]; st.divider()
        if st.session_state['email'] == 'osvaldolira@laconcepcion.cl' and st.button("🚀 SINCRONIZAR DRIVE"): guardar_en_drive()
        if st.button("🚪 CERRAR SESIÓN"): st.session_state.clear(); st.rerun()
    if menu == "DASHBOARD": modulo_dashboard()
    elif menu == "Petróleo": modulo_petroleo()
    elif menu == "Compras": modulo_compras()
    elif menu == "Tesoreria": modulo_tesoreria()
    elif menu == "RRHH": modulo_rrhh()
    elif menu == "Bodega": modulo_bodega()
    elif menu == "Espino": modulo_espino()
    elif menu == "Libro de Campo": modulo_libro_campo()
    elif menu == "Costos": modulo_costos()
    elif menu == "Seguridad": modulo_seguridad()
