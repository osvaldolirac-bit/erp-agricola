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
IMPUESTO_ESPECIFICO_LITRO = 75 
hoy = datetime.now().date()

FAMILIAS_PRODUCTOS = ["FERTILIZANTE", "FERTILIZANTE FOLIAR", "HERBICIDA", "INSECTICIDA", "FUNGICIDA", "BIO ESTIMULANTE", "ACARICIDA", "REGULADOR DE CRECIMIENTO", "ADHERENTE / MOJANTE", "OTROS"]
CENTROS_COSTO = ["CEREZOS CORTE1", "CEREZOS CORTE2", "CIRUELOS", "NOGALES APARICION", "NOGALES CRUZ DEL SUR", "EL ESPINO", "OTROS"]

# --- 2. MOTOR DE BASE DE DATOS ---
def conectar_db():
    return sqlite3.connect(NOMBRE_DB)

def hash_password(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def registrar_accion(accion, detalle):
    user = st.session_state.get('email', 'Desconocido')
    fecha = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        conn = conectar_db()
        conn.execute("INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)", (user, accion, detalle, fecha))
        conn.commit(); conn.close()
    except: pass

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
        st.success("✅ Respaldo sincronizado en Drive.")

def descargar_de_drive():
    drive = obtener_drive()
    if drive:
        query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
        lista = drive.ListFile({'q': query}).GetList()
        if lista: lista[0].GetContentFile(NOMBRE_DB)

def sanear_y_recalcular():
    try:
        conn = conectar_db()
        conn.execute("DELETE FROM facturas WHERE nro_documento LIKE '%_P' AND REPLACE(nro_documento, '_P', '') NOT IN (SELECT nro_documento FROM facturas WHERE nro_documento NOT LIKE '%_P')")
        salidas = conn.execute("SELECT id, litros, valor_imputado FROM petroleo WHERE tipo='Salida'").fetchall()
        for s_id, lts, val in salidas:
            if lts > 0 and (val / lts) > 600:
                neto = (val / 1.19) - (lts * IMPUESTO_ESPECIFICO_LITRO)
                conn.execute("UPDATE petroleo SET valor_imputado = ? WHERE id = ?", (neto, s_id))
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
    usuarios = [('osvaldolira@laconcepcion.cl', hash_password('9083')), ('secretaria@laconcepcion.cl', hash_password('9111'))]
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    if cursor.fetchone()[0] == 0:
        for u, p in usuarios: cursor.execute("INSERT INTO usuarios (email, password) VALUES (?,?)", (u, p))
    conn.commit(); conn.close(); sanear_y_recalcular()

# --- 3. UTILIDADES Y PDF ---
def f_puntos(v):
    try: return f"{int(round(float(v))):,}".replace(",", ".")
    except: return "0"

def f_decimal(v):
    try: return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return "0,00"

def generar_pdf_blob(df, titulo, incluir_precios=True, total_manual=None, modo_petroleo=False):
    try:
        pdf = FPDF(); pdf.add_page(); pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, "AGRICOLA LA CONCEPCIÓN", ln=True, align="C")
        pdf.set_font("Helvetica", "B", 12); pdf.cell(0, 10, titulo, ln=True, align="C")
        pdf.ln(5); pdf.set_font("Helvetica", "B", 8)
        df_pdf = df.copy()
        
        # Lógica de sumatoria automática para PDF
        t_sum = total_manual
        if t_sum is None and 'monto_total' in df_pdf.columns: t_sum = df_pdf['monto_total'].sum()
        if t_sum is None and 'Total' in df_pdf.columns: t_sum = df_pdf['Total'].sum()

        if modo_petroleo:
            cols_drop = [c for c in df_pdf.columns if any(x in c.lower() for x in ["imputado", "valor", "monto", "precio"])]
            df_pdf = df_pdf.drop(columns=cols_drop)
            incluir_precios = False
        elif not incluir_precios:
            df_pdf = df_pdf[[c for c in df_pdf.columns if not any(x in c.lower() for x in ["precio", "valor", "monto", "pmp", "ajuste"])]]
        elif "Ajustes" in df_pdf.columns:
            df_pdf = df_pdf.drop(columns=['Ajustes'])
        
        cols = df_pdf.columns; w = 190 / len(cols)
        for col in cols: pdf.cell(w, 8, str(col).upper(), border=1, align="C")
        pdf.ln(); pdf.set_font("Helvetica", "", 7)
        for _, row in df_pdf.iterrows():
            for i, item in enumerate(row):
                col_n = df_pdf.columns[i].lower()
                if any(x in col_n for x in ["gastos", "insumos", "petroleo", "total", "monto_total"]): val = f_puntos(item)
                elif any(x in col_n for x in ["cantidad", "stock", "litros"]): val = f_decimal(item)
                elif any(x in col_n for x in ["monto", "precio", "valor", "pmp"]): val = f_puntos(item)
                else: val = str(item)
                pdf.cell(w, 7, val[:25], border=1)
            pdf.ln()
            
        if incluir_precios and t_sum is not None:
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(w * (len(cols)-1), 8, "TOTAL FINAL:", border=1, align="R")
            pdf.cell(w, 8, f"${f_puntos(t_sum)}", border=1, align="L")
        return pdf.output(dest="S").encode("latin-1")
    except: return None

def inyectar_css():
    st.markdown("""<style>
        .main { background-color: #f4f7f6; }
        .stMetric { background-color: white; padding: 15px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); border-left: 6px solid #2E7D32; }
        .metric-big { font-size: 2.8rem !important; font-weight: 800; color: #1B5E20; }
        .metric-red { color: #d32f2f !important; font-size: 2.2rem !important; font-weight: 700; }
        .metric-blue { color: #1976d2 !important; font-size: 2.2rem !important; font-weight: 700; }
        .metric-std { font-size: 2.0rem !important; font-weight: 600; }
        .card-critico { border-left-color: #d32f2f !important; }
        .card-vencida { border-left-color: #1976d2 !important; }
        .stButton>button { border-radius: 8px; font-weight: bold; }
        </style>""", unsafe_allow_html=True)
    if st.session_state.get('logged_in') and st.session_state.get('email') != 'osvaldolira@laconcepcion.cl':
        st.markdown("<style>header {visibility: hidden;} #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display:none;}</style>", unsafe_allow_html=True)

# --- 4. DASHBOARD ---
def modulo_dashboard():
    st.markdown("<h1 style='text-align: center; color: #1B5E20;'>🚜 DASHBOARD PRINCIPAL</h1>", unsafe_allow_html=True)
    conn = conectar_db()
    df_f = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente' AND nro_documento NOT LIKE '%_P'", conn)
    df_p_c = pd.read_sql_query("SELECT SUM(litros) as l FROM petroleo WHERE tipo='Carga'", conn)
    df_p_s = pd.read_sql_query("SELECT SUM(litros) as l FROM petroleo WHERE tipo='Salida'", conn)
    saldo_pet = (df_p_c['l'].fillna(0).iloc[0]) - (df_p_s['l'].fillna(0).iloc[0])
    
    m1, m2, m3, m4, m5 = st.columns(5)
    with m1: st.markdown(f"<div class='stMetric'><small>💰 DEUDA TOTAL</small><br><span class='metric-big'>${f_puntos(df_f['monto_total'].sum())}</span></div>", unsafe_allow_html=True)
    
    p_dia = hoy.replace(day=1)
    d_critica = df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < p_dia]['monto_total'].sum()
    with m2: st.markdown(f"<div class='stMetric card-critico'><small>🔥 MESES ANTERIORES</small><br><span class='metric-red'>${f_puntos(d_critica)}</span><br><small style='color:red;'>CRÍTICO</small></div>", unsafe_allow_html=True)
    
    v_count = len(df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < hoy])
    with m3: st.markdown(f"<div class='stMetric card-vencida'><small>⚠️ VENCIDAS</small><br><span class='metric-blue'>{v_count}</span><br><small style='color:#1976d2;'>DOCUMENTOS</small></div>", unsafe_allow_html=True)
    
    with m4: st.markdown(f"<div class='stMetric'><small>📄 PENDIENTES</small><br><span class='metric-std'>{len(df_f)}</span><br><small>EN CARTERA</small></div>", unsafe_allow_html=True)
    with m5: st.markdown(f"<div class='stMetric'><small>⛽ PETRÓLEO</small><br><span class='metric-std'>{f_decimal(saldo_pet)}L</span><br><small>SALDO NETO</small></div>", unsafe_allow_html=True)
    
    st.divider(); c_izq, c_der = st.columns([1.6, 1])
    with c_izq:
        st.markdown("### <span style='color:#D4AF37;'>📊 Gastos Netos por Cuartel</span>", unsafe_allow_html=True)
        query = """SELECT UPPER(TRIM(cc)) as cc, SUM(val) as total FROM (SELECT centro_costo as cc, valor_imputado as val FROM movimientos WHERE tipo LIKE 'Salida%' UNION ALL SELECT centro_costo as cc, monto_imputado as val FROM facturas WHERE nro_documento LIKE '%_P' UNION ALL SELECT centro_costo as cc, valor_imputado as val FROM petroleo WHERE tipo = 'Salida' UNION ALL SELECT centro_costo as cc, monto as val FROM ajustes_costos) WHERE cc != '' AND cc != 'BODEGA' GROUP BY cc"""
        df_c = pd.read_sql_query(query, conn)
        if not df_c.empty:
            df_c = pd.concat([df_c, pd.DataFrame([{'cc': 'TOTAL GENERAL', 'total': df_c['total'].sum()}])], ignore_index=True)
            st.dataframe(df_c.style.format({"total": "${:,.0f}"}), use_container_width=True)
    with c_der:
        st.markdown("### <span style='color:#1976d2;'>📅 Proyección 4 Meses</span>", unsafe_allow_html=True)
        for i in range(4):
            f_p = (datetime.now().replace(day=1) + timedelta(days=i*31)).replace(day=1)
            total_m = df_f[(pd.to_datetime(df_f['fecha_vencimiento']).dt.month == f_p.month) & (pd.to_datetime(df_f['fecha_vencimiento']).dt.year == f_p.year)]['monto_total'].sum() if not df_f.empty else 0
            st.markdown(f"<div style='background:white; padding:10px; border-radius:8px; margin-bottom:5px; border-right: 5px solid #1976d2; display:flex; justify-content:space-between;'><b>{f_p.strftime('%B %Y').upper()}</b> <span>${f_puntos(total_m)}</span></div>", unsafe_allow_html=True)
    conn.close()

# --- 5. PETRÓLEO ---
def modulo_petroleo():
    st.header("⛽ Gestión de Petróleo")
    t1, t2, t3 = st.tabs(["📥 Carga", "🚜 Salida", "📊 Historial"]); conn = conectar_db()
    with t1:
        with st.form("f_carga"):
            l, mt, f = st.number_input("Litros", 0.0), st.number_input("Total Bruto ($)", 0.0), st.date_input("Fecha", hoy)
            if st.form_submit_button("REGISTRAR CARGA"):
                neto = (mt / 1.19) - (l * IMPUESTO_ESPECIFICO_LITRO)
                conn.execute("INSERT INTO petroleo (tipo, litros, monto_total_compra, fecha) VALUES (?,?,?,?)", ("Carga", l, neto, f))
                conn.commit(); guardar_en_drive(); st.rerun()
    with t2:
        with st.form("f_salida"):
            l_s, v, r = st.number_input("Litros Salida", 0.0), st.text_input("Vehículo"), st.text_input("Responsable")
            ccs_sel = [cc for cc in CENTROS_COSTO if st.checkbox(cc, key=f"ps_{cc}")]
            if st.form_submit_button("REGISTRAR SALIDA"):
                df_calc = pd.read_sql_query("SELECT SUM(litros) as l, SUM(monto_total_compra) as m FROM petroleo WHERE tipo='Carga'", conn)
                pmp = (df_calc['m'].iloc[0] / df_calc['l'].iloc[0]) if df_calc['l'].iloc[0] > 0 else 0
                for c in ccs_sel:
                    conn.execute("INSERT INTO petroleo (tipo, litros, vehiculo, responsable, centro_costo, fecha, valor_imputado) VALUES (?,?,?,?,?,?,?)", (l_s/len(ccs_sel), v, r, c.upper(), hoy, (l_s/len(ccs_sel)*pmp)))
                conn.commit(); st.rerun()
    with t3:
        df_p = pd.read_sql_query("SELECT id, fecha, tipo, litros, vehiculo, responsable, centro_costo, valor_imputado FROM petroleo ORDER BY id DESC", conn)
        st.dataframe(df_p.style.format({"litros": "{:,.2f}", "valor_imputado": "${:,.0f}"}), use_container_width=True)
        st.download_button("📥 PDF Historial Operativo", generar_pdf_blob(df_p, "HISTORIAL PETROLEO", modo_petroleo=True), "petroleo_operativo.pdf")
        id_p = st.selectbox("ID borrar", df_p['id']); cl = st.text_input("Master", type="password", key="cl_p")
        if st.button("🗑️ ELIMINAR") and cl == CLAVE_MAESTRA: conn.execute("DELETE FROM petroleo WHERE id=?", (id_p,)); conn.commit(); st.rerun()
    conn.close()

# --- 6. COMPRAS ---
def modulo_compras():
    st.header("📦 Compras y Gastos")
    t1, t2, t3 = st.tabs(["➕ Insumos", "💸 Gasto Vario", "🔍 Historial"]); conn = conectar_db()
    with t1:
        c1, c2 = st.columns(2); nro, prov, fe, fv = c1.text_input("N° Doc"), c1.text_input("Proveedor"), c2.date_input("Emisión"), c2.date_input("Vence")
        df_i = pd.read_sql_query("SELECT id, producto FROM inventario", conn)
        cp1, cp2, cp3, cp4 = st.columns([3,1,1,1])
        ps = cp1.selectbox("Insumo", df_i['id'].astype(str) + " - " + df_i['producto']) if not df_i.empty else None
        ct, pr = cp2.number_input("Cant", 0.0), cp3.number_input("Neto", 0.0)
        if cp4.button("➕"):
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
                conn.commit(); st.session_state['car'] = []; registrar_accion("COMPRA", nro); guardar_en_drive(); st.rerun()
    with t2:
        pg, ng, fg1, fg2 = st.text_input("Proveedor", key="pg"), st.text_input("N° Doc", key="ng"), st.date_input("Fecha Compra", hoy), st.date_input("Fecha Vencimiento", hoy)
        sel_cc = [cc for cc in CENTROS_COSTO if st.checkbox(cc, key=f"gv_{cc}")]
        mt = st.number_input("Total Bruto ($)", 0.0); iva = st.radio("¿Imputar TOTAL?", ["SÍ", "NO (NETO)"])
        if st.button("💾 GUARDAR GASTO"):
            imp = mt if iva == "SÍ" else mt/1.19
            if sel_cc:
                conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo) VALUES (?,?,?,?,?,?)", (ng, pg, fg1, fg2, mt, 'Gasto Vario'))
                for c in sel_cc: conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, centro_costo, monto_imputado) VALUES (?,?,?,?,?,?,?,?)", (ng+"_P", pg, fg1, fg2, 0, 'Gasto Vario', c.upper(), imp/len(sel_cc)))
            else: conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo) VALUES (?,?,?,?,?,?)", (ng, pg, fg1, fg2, mt, 'Gasto Vario'))
            conn.commit(); guardar_en_drive(); st.rerun()
    with t3:
        df_h = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_compra, monto_total FROM facturas WHERE monto_total > 0 AND nro_documento NOT LIKE '%_P' ORDER BY fecha_compra DESC", conn)
        st.dataframe(df_h.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
        st.download_button("📥 PDF Historial", generar_pdf_blob(df_h, "HISTORIAL COMPRAS"), "compras.pdf")
        id_del = st.selectbox("ID borrar", df_h['id']); cl = st.text_input("Master", type="password", key="cl_h")
        if st.button("🗑️ ELIMINAR") and cl == CLAVE_MAESTRA:
            f_sel = df_h[df_h['id']==id_del].iloc[0]
            conn.execute("DELETE FROM facturas WHERE id=?", (id_del,))
            conn.execute("DELETE FROM facturas WHERE nro_documento=? AND proveedor=?", (f_sel['nro_documento']+"_P", f_sel['proveedor']))
            conn.commit(); st.rerun()
    conn.close()

# --- 7. TESORERÍA ---
def modulo_tesoreria():
    st.header("💸 Tesorería y Pagos")
    t1, t2 = st.tabs(["🔴 Pendientes", "🏢 Por Proveedor"]); conn = conectar_db()
    with t1:
        df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' AND nro_documento NOT LIKE '%_P' AND monto_total > 0 ORDER BY fecha_vencimiento ASC", conn)
        st.warning(f"### DEUDA PENDIENTE: ${f_puntos(df_p['monto_total'].sum())}")
        
        # MEJORA: Vencidos en Rojo en la tabla
        def color_vencido(row):
            return ['color: red' if pd.to_datetime(row.fecha_vencimiento).date() < hoy else '' for _ in row]
        
        st.dataframe(df_p.style.apply(color_vencido, axis=1).format({"monto_total": "${:,.0f}"}), use_container_width=True)
        
        # MEJORA: PDF con Sumatoria
        st.download_button("📥 PDF Pendientes", generar_pdf_blob(df_p.drop(columns=['id']), "LISTADO PENDIENTES CON SUMATORIA"), "pendientes.pdf")
        
        id_pay = st.selectbox("Pagar ID", df_p['id']); met = st.selectbox("Método", ["Transferencia", "Efectivo", "Cheque"])
        if st.button("💰 PAGAR"): conn.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (met, hoy, id_pay)); conn.commit(); st.rerun()
    with t2:
        df_list = pd.read_sql_query("SELECT DISTINCT proveedor FROM facturas WHERE estado='Pendiente' AND monto_total > 0", conn)
        if not df_list.empty:
            pr = st.selectbox("Proveedor", df_list['proveedor'])
            df_pr = pd.read_sql_query(f"SELECT nro_documento, fecha_vencimiento, monto_total FROM facturas WHERE proveedor='{pr}' AND estado='Pendiente' AND nro_documento NOT LIKE '%_P'", conn)
            st.error(f"### DEUDA TOTAL {pr}: ${f_puntos(df_pr['monto_total'].sum())}")
            st.dataframe(df_pr.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
            st.download_button(f"📥 PDF Deuda {pr}", generar_pdf_blob(df_pr, f"DEUDA {pr}"), f"deuda_{pr}.pdf")
    conn.close()

# --- 8. BODEGA ---
def modulo_bodega():
    st.header("🏠 Gestión de Bodega")
    t1, t2, t3, t4 = st.tabs(["📊 Stock Actual", "🔄 Salida", "➕ Nuevo Registro", "🔍 Consulta CC"]); conn = conectar_db()
    with t1:
        df_s = pd.read_sql_query("SELECT id, producto, familia, stock, precio_medio FROM inventario", conn)
        st.dataframe(df_s.drop(columns=['id']).style.format({"stock": "{:,.2f}", "precio_medio": "${:,.0f}"}), use_container_width=True)
        st.download_button("📥 PDF Admin", generar_pdf_blob(df_s.drop(columns=['id']), "STOCK ADMIN", True), "admin_stock.pdf")
        st.download_button("📥 PDF Campo", generar_pdf_blob(df_s.drop(columns=['id']), "STOCK CAMPO", False), "campo_stock.pdf")
        st.divider(); 
        
        # MEJORA: Clave para Modificar/Eliminar
        col_ed1, col_ed2 = st.columns(2)
        id_g = col_ed1.selectbox("ID Insumo a Editar", df_s['id'])
        item = df_s[df_s['id']==id_g].iloc[0]
        n_nom = col_ed1.text_input("Nuevo Nombre", item['producto'])
        n_st = col_ed2.number_input("Ajustar Stock", value=float(item['stock']))
        clv = st.text_input("Clave de Autorización", type="password", key="cl_bod")
        
        c1, c2 = st.columns(2)
        if c1.button("✏️ APLICAR CAMBIOS") and clv == CLAVE_MAESTRA:
            conn.execute("UPDATE inventario SET producto=?, stock=? WHERE id=?", (n_nom, round(n_st, 2), id_g))
            conn.commit(); st.rerun()
        if c2.button("🗑️ ELIMINAR INSUMO") and clv == CLAVE_MAESTRA:
            conn.execute("DELETE FROM inventario WHERE id=?", (id_g,))
            conn.commit(); st.rerun()
            
    with t2:
        df_i = pd.read_sql_query("SELECT id, producto, precio_medio FROM inventario", conn)
        ps = st.selectbox("Insumo", df_i['id'].astype(str) + " - " + df_i['producto']); ct = st.number_input("Cant Salida", 0.0)
        sel_cc = [cc for cc in CENTROS_COSTO if st.checkbox(cc, key=f"mb_{cc}")]
        if st.button("REGISTRAR SALIDA"):
            iid = int(ps.split(" - ")[0]); pmp = df_i[df_i['id']==iid]['precio_medio'].iloc[0]
            if ct > 0 and sel_cc:
                c_p = round(ct/len(sel_cc), 2)
                for c in sel_cc: conn.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado) VALUES (?,?,?,?,?)", (iid, "Salida", c_p, hoy, c.upper(), (c_p*pmp)))
                conn.execute("UPDATE inventario SET stock = stock - ? WHERE id = ?", (round(ct, 2), iid)); conn.commit(); st.rerun()
    with t3:
        with st.form("nuevo_form"):
            n_p = st.text_input("Nombre"); n_f = st.selectbox("Familia", FAMILIAS_PRODUCTOS)
            n_s, n_pn = st.number_input("Stock Inicial", 0.0), st.number_input("PMP Neto", 0.0)
            if st.form_submit_button("➕ CREAR"):
                if n_p: conn.execute("INSERT INTO inventario (producto, familia, stock, precio_medio) VALUES (?,?,?,?)", (n_p, n_f, round(n_s, 2), n_pn)); conn.commit(); st.rerun()
    with t4:
        cc_q = st.selectbox("Cuartel", CENTROS_COSTO)
        df_cc = pd.read_sql_query(f"SELECT m.fecha, i.producto, m.cantidad, m.valor_imputado FROM movimientos m JOIN inventario i ON m.producto_id = i.id WHERE m.centro_costo = '{cc_q.upper()}' ORDER BY m.fecha DESC", conn)
        st.dataframe(df_cc.style.format({"cantidad": "{:,.2f}", "valor_imputado": "${:,.0f}"}), use_container_width=True)
        st.download_button(f"📥 PDF Consulta {cc_q}", generar_pdf_blob(df_cc, f"MOVIMIENTOS EN {cc_q}"), f"consulta_{cc_q}.pdf")
    conn.close()

# --- 9. COSTOS ---
def modulo_costos():
    st.header("💰 Informe de Costos")
    es_admin = (st.session_state.get('email') == 'osvaldolira@laconcepcion.cl')
    t = st.tabs(["📊 Resumen", "🔧 AJUSTE"]) if es_admin else st.tabs(["📊 Resumen"])
    conn = conectar_db()
    with t[0]:
        q = """SELECT UPPER(TRIM(cc)) as cc, SUM(CASE WHEN fuente = 'BODEGA' THEN val ELSE 0 END) as Insumos, SUM(CASE WHEN fuente = 'FACTURA' THEN val ELSE 0 END) as Gastos, SUM(CASE WHEN fuente = 'PETROLEO' THEN val ELSE 0 END) as Petroleo, SUM(CASE WHEN fuente = 'AJUSTE' THEN val ELSE 0 END) as Ajustes, SUM(val) as Total FROM (SELECT centro_costo as cc, valor_imputado as val, 'BODEGA' as fuente FROM movimientos UNION ALL SELECT centro_costo as cc, monto_imputado as val, 'FACTURA' as fuente FROM facturas WHERE nro_documento LIKE '%_P' UNION ALL SELECT centro_costo as cc, valor_imputado as val, 'PETROLEO' as fuente FROM petroleo WHERE tipo='Salida' UNION ALL SELECT centro_costo as cc, monto as val, 'AJUSTE' as fuente FROM ajustes_costos) WHERE cc != '' AND cc != 'BODEGA' GROUP BY cc"""
        df_r = pd.read_sql_query(q, conn)
        if not df_r.empty:
            tot = df_r['Total'].sum(); df_m = df_r.copy()
            if not es_admin: df_m = df_m.drop(columns=['Ajustes'])
            st.dataframe(df_m.style.format({c: ("${:,.0f}" if c in ["Gastos", "Total", "Insumos", "Petroleo", "Ajustes"] else str) for c in df_m.columns if c != 'cc'}), use_container_width=True)
            st.download_button("📥 PDF Costos", generar_pdf_blob(df_r, "INFORME DE COSTOS", total_manual=tot), "costos.pdf")
    if es_admin:
        with t[1]:
            cc_aj, m_aj, mot = st.selectbox("CC", CENTROS_COSTO), st.number_input("Monto"), st.text_input("Motivo")
            if st.button("💾 APLICAR") and st.text_input("Clave", type="password") == CLAVE_MAESTRA: conn.execute("INSERT INTO ajustes_costos (centro_costo, monto, fecha, motivo) VALUES (?,?,?,?)", (cc_aj.upper(), m_aj, hoy, mot)); conn.commit(); st.rerun()
    conn.close()

# --- 10. SEGURIDAD ---
def modulo_seguridad():
    st.header("🕵️ Auditoría")
    conn = conectar_db()
    t1, t2 = st.tabs(["📜 Bitácora", "🔑 Accesos"])
    with t1:
        df_b = pd.read_sql_query("SELECT * FROM bitacora ORDER BY id DESC", conn); st.dataframe(df_b, use_container_width=True)
        st.download_button("📥 PDF Bitácora", generar_pdf_blob(df_b, "BITACORA MOVIMIENTOS"), "bitacora.pdf")
    with t2:
        df_a = pd.read_sql_query("SELECT * FROM log_accesos ORDER BY id DESC", conn); st.dataframe(df_a, use_container_width=True)
        st.download_button("📥 PDF Accesos", generar_pdf_blob(df_a, "HISTORIAL ACCESOS"), "accesos.pdf")
    conn.close()

# --- LOGIN ---
def login_page():
    inyectar_css()
    st.markdown("<h1 style='text-align: center; color: #1B5E20; margin-top: 50px;'>🚜 ERP La Concepción</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        with st.form("login"):
            e, p = st.text_input("Email Corporativo"), st.text_input("Clave", type="password")
            if st.form_submit_button("ACCEDER"):
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("SELECT email FROM usuarios WHERE email=? AND password=?", (e, hash_password(p)))
                if cursor.fetchone():
                    cursor.execute("INSERT INTO log_accesos (email, fecha_hora) VALUES (?,?)", (e, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                    conn.commit(); conn.close()
                    st.session_state['logged_in'], st.session_state['email'] = True, e; st.rerun()
                else: conn.close(); st.error("Acceso incorrecto")

# --- NAVEGACIÓN ---
st.set_page_config(page_title="ERP LA CONCEPCIÓN v10.8.75", layout="wide")
inicializar_db()
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if not st.session_state['logged_in']: login_page()
else:
    if 'init' not in st.session_state: descargar_de_drive(); st.session_state['init'] = True
    inyectar_css()
    with st.sidebar:
        st.title("ERP LA CONCEPCIÓN")
        st.markdown("<span style='color:green; font-weight:bold;'>🟢 CONECTADO</span>", unsafe_allow_html=True)
        st.divider()
        m_opts = { "🏠 DASHBOARD": "DASHBOARD", "⛽ Petróleo": "Petróleo", "📦 Compras": "Compras", "💸 Tesorería": "Tesorería", "🏠 Bodega": "Bodega", "💰 Costos": "Costos" }
        if st.session_state['email'] == 'osvaldolira@laconcepcion.cl': m_opts["🕵️ Seguridad"] = "Seguridad"
        menu = m_opts[st.radio("MENÚ", list(m_opts.keys()))]
        st.divider()
        if st.session_state['email'] == 'osvaldolira@laconcepcion.cl' and st.button("🚀 Sincronizar"): guardar_en_drive()
        if st.button("🚪 Salir"): st.session_state.clear(); st.rerun()
    if menu == "DASHBOARD": modulo_dashboard()
    elif menu == "Petróleo": modulo_petroleo()
    elif menu == "Compras": modulo_compras()
    elif menu == "Tesorería": modulo_tesoreria()
    elif menu == "Bodega": modulo_bodega()
    elif menu == "Costos": modulo_costos()
    elif menu == "Seguridad": modulo_seguridad()
