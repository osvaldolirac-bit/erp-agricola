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

# --- 3. UTILIDADES ---
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

# --- DRIVE INTEGRACIÓN ---
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

# --- ESTILOS ---
def inyectar_css():
    st.markdown("""<style>
        .main { background-color: #f4f7f6; }
        .stMetric { background-color: white; padding: 20px; border-radius: 12px; border-left: 6px solid #2E7D32; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }
        h1, h2, h3 { color: #1B5E20; font-family: 'Arial'; }
        .stButton>button { border-radius: 8px; background-color: #2E7D32; color: white; font-weight: bold; }
        </style>""", unsafe_allow_html=True)

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
                    cursor.execute("INSERT INTO log_accesos (email, fecha_hora) VALUES (?,?)", (e, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                    conn.commit(); conn.close()
                    st.session_state['logged_in'] = True; st.session_state['email'] = e; st.rerun()
                else: conn.close(); st.error("Email o clave incorrectos.")

# --- MÓDULOS ---
def modulo_dashboard():
    inyectar_css()
    st.markdown("<h1>🚜 ERP Agrícola La Concepción</h1>", unsafe_allow_html=True)
    st.subheader(f"Usuario: {st.session_state['email']}")
    conn = conectar_db()
    df_f_reales = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente' AND nro_documento NOT LIKE '%_P'", conn)
    df_p_c = pd.read_sql_query("SELECT SUM(litros) as l FROM petroleo WHERE tipo='Carga'", conn); df_p_s = pd.read_sql_query("SELECT SUM(litros) as l FROM petroleo WHERE tipo='Salida'", conn)
    saldo_pet = (df_p_c['l'].fillna(0).iloc[0]) - (df_p_s['l'].fillna(0).iloc[0])
    query_c = "SELECT UPPER(TRIM(centro_costo)) as cc, SUM(monto_imputado) as total_neto FROM (SELECT centro_costo, valor_imputado as monto_imputado FROM movimientos WHERE tipo LIKE 'Salida%' UNION ALL SELECT centro_costo, monto_imputado FROM facturas WHERE tipo = 'Gasto Vario' AND centro_costo != '' UNION ALL SELECT centro_costo, valor_imputado as monto_imputado FROM petroleo WHERE tipo = 'Salida') WHERE cc IS NOT NULL AND cc != '' GROUP BY cc"
    df_c = pd.read_sql_query(query_c, conn)
    if st.session_state['email'] == 'osvaldolira@laconcepcion.cl':
        with st.expander("👁️ Bitácora de Accesos Recientes"):
            df_logs = pd.read_sql_query("SELECT email, fecha_hora FROM log_accesos ORDER BY fecha_hora DESC LIMIT 10", conn)
            st.table(df_logs)
    t_d = df_f_reales['monto_total'].sum() if not df_f_reales.empty else 0
    v_a = df_f_reales[pd.to_datetime(df_f_reales['fecha_vencimiento']).dt.date < hoy.replace(day=1)]['monto_total'].sum() if not df_f_reales.empty else 0
    v_h = len(df_f_reales[pd.to_datetime(df_f_reales['fecha_vencimiento']).dt.date < hoy]) if not df_f_reales.empty else 0
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("DEUDA TOTAL", f"${f_puntos(t_d)}")
    with c2: st.markdown("MESES ANTERIORES"); st.markdown(f"<h2 style='color:red;'>${f_puntos(v_a)}</h2>", unsafe_allow_html=True)
    with c3: st.markdown("VENCIDOS HOY"); st.markdown(f"<h2 style='color:orange;'>{v_h}</h2>", unsafe_allow_html=True)
    c4.metric("DOCS. PENDIENTES", f"{len(df_f_reales)}"); c5.metric("SALDO PETRÓLEO", f"{f_decimal(saldo_pet)} Lts")
    st.divider()
    col1, col2 = st.columns([1.5, 1])
    with col1:
        st.subheader("💰 Resumen Costos por Cuartel")
        if not df_c.empty:
            df_total = pd.DataFrame([{"cc": "TOTAL GENERAL", "total_neto": df_c["total_neto"].sum()}])
            df_res = pd.concat([df_c, df_total], ignore_index=True)
            def bold_t(row): return ['font-weight: bold; background-color: #E8F5E9' if row['cc'] == "TOTAL GENERAL" else '' for _ in row]
            st.dataframe(df_res.style.apply(bold_t, axis=1).format({"total_neto": "${:,.0f}"}), use_container_width=True)
    conn.close()

def modulo_petroleo():
    st.header("⛽ Gestión de Petróleo")
    tp1, tp2, tp3 = st.tabs(["📥 Carga", "🚜 Salida", "📊 Historial"]); conn = conectar_db()
    df_c = pd.read_sql_query("SELECT SUM(litros) as l, SUM(monto_total_compra) as m FROM petroleo WHERE tipo='Carga'", conn); df_s = pd.read_sql_query("SELECT SUM(litros) as l FROM petroleo WHERE tipo='Salida'", conn)
    saldo = (df_c['l'].fillna(0).iloc[0]) - (df_s['l'].fillna(0).iloc[0]); pmp_p = (df_c['m'].fillna(0).iloc[0] / df_c['l'].fillna(1).iloc[0]) if df_c['l'].fillna(0).iloc[0] > 0 else 0
    st.sidebar.metric("LITROS EN ESTANQUE", f"{f_decimal(saldo)} Lts")
    with tp1:
        with st.form("p_carga"):
            lts = st.number_input("Litros Comprados", 0.0); prov = st.text_input("Proveedor"); mt_t = st.number_input("Total ($)", 0.0); fec = st.date_input("Fecha", hoy)
            if st.form_submit_button("💾 REGISTRAR"):
                conn.execute("INSERT INTO petroleo (tipo, litros, proveedor, monto_total_compra, fecha) VALUES (?,?,?,?,?)", ("Carga", lts, prov, mt_t, fec)); conn.commit(); guardar_en_drive(); st.rerun()
    with tp2:
        with st.form("p_salida"):
            lts_s = st.number_input("Litros", 0.0); vehi = st.text_input("Vehículo"); resp = st.text_input("Responsable"); fec_s = st.date_input("Fecha Despacho", hoy)
            st.markdown("### Seleccione Cuartel(es):")
            cols = st.columns(3); ccs_p = []
            for i, cc_n in enumerate(CENTROS_COSTO):
                if cols[i%3].checkbox(cc_n, key=f"p_cc_{cc_n}"): ccs_p.append(cc_n)
            if st.form_submit_button("⛽ REGISTRAR SALIDA"):
                if lts_s > 0 and ccs_p and lts_s <= saldo:
                    l_rep = lts_s / len(ccs_p); v_rep = (lts_s * pmp_p) / len(ccs_p)
                    for c in ccs_p: conn.execute("INSERT INTO petroleo (tipo, litros, vehiculo, responsable, centro_costo, fecha, valor_imputado) VALUES (?,?,?,?,?,?,?)", ("Salida", l_rep, vehi, resp, c.upper(), fec_s, v_rep))
                    conn.commit(); guardar_en_drive(); st.rerun()
    with tp3:
        df_p = pd.read_sql_query("SELECT fecha, tipo, litros, proveedor, monto_total_compra as monto, vehiculo, responsable, centro_costo FROM petroleo ORDER BY id DESC", conn)
        st.dataframe(df_p.style.format({"litros": "{:,.2f}", "monto": "${:,.0f}"}), use_container_width=True)
    conn.close()

def modulo_compras():
    st.header("📦 Compras e Historial")
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
                conn.commit(); guardar_en_drive(); st.session_state['car'] = []; st.rerun()
    with t2:
        c1, c2 = st.columns(2); prov_g, nro_g = c1.text_input("Proveedor ", key="pg"), c2.text_input("N° Doc ", key="ng")
        cf1, cf2 = st.columns(2); fe_g, fv_g = cf1.date_input("Fecha Compra", hoy, key="fg1"), cf2.date_input("Fecha Vencimiento", hoy, key="fg2")
        detalles_g = st.text_area("Concepto", height=70); ccs_sel = []; cols = st.columns(3)
        for i, cc in enumerate(CENTROS_COSTO):
            if cols[i % 3].checkbox(cc, key=f"gv_{cc}"): ccs_sel.append(cc)
        m_total_con_iva = st.number_input("Monto Total Documento (con IVA)", 0.0)
        iva_costo = st.radio("¿Imputar el TOTAL al Centro de Costo?", ["SÍ", "NO (Imputar solo el NETO)"])
        if st.button("💾 GUARDAR GASTO VARIO"):
            if m_total_con_iva > 0:
                monto_imputar = m_total_con_iva if iva_costo == "SÍ" else (m_total_con_iva / 1.19)
                if len(ccs_sel) > 0:
                    imp_indiv = monto_imputar / len(ccs_sel)
                    conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, concepto) VALUES (?,?,?,?,?,?,?)", (nro_g, prov_g, fe_g, fv_g, m_total_con_iva, 'Gasto Vario', detalles_g))
                    for c in ccs_sel: conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, centro_costo, monto_imputado, concepto) VALUES (?,?,?,?,?,?,?,?,?)", (nro_g+"_P", prov_g, fe_g, fv_g, 0, 'Gasto Vario', c.upper(), imp_indiv, detalles_g))
                else:
                    conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, concepto, centro_costo, monto_imputado) VALUES (?,?,?,?,?,?,?,?,?)", (nro_g, prov_g, fe_g, fv_g, m_total_con_iva, 'Gasto Vario', detalles_g, "CONTABILIDAD GENERAL", 0))
                conn.commit(); guardar_en_drive(); st.rerun()
    with t3:
        f1, f2 = st.date_input("Desde", datetime(2020, 1, 1).date()), st.date_input("Hasta", datetime(2030, 12, 31).date())
        df_h = pd.read_sql_query(f"SELECT id, nro_documento, proveedor, fecha_compra, monto_total, estado, tipo FROM facturas WHERE monto_total > 0 AND fecha_compra BETWEEN '{f1}' AND '{f2}' ORDER BY id DESC", conn)
        st.dataframe(df_h.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
        if not df_h.empty:
            st.divider(); st.subheader("🛠️ Gestión de Documentos")
            id_doc = st.selectbox("ID de documento a gestionar", df_h['id']); sel_doc = df_h[df_h['id'] == id_doc]
            if not sel_doc.empty:
                item_doc = sel_doc.iloc[0]; c_edit1, c_edit2 = st.columns(2)
                n_nro = c_edit1.text_input("Nuevo N° Doc", value=item_doc['nro_documento'])
                n_prov = c_edit2.text_input("Nuevo Proveedor", value=item_doc['proveedor'])
                n_monto = st.number_input("Nuevo Monto Total", value=float(item_doc['monto_total']))
                cl = st.text_input("Clave de Autorización", type="password")
                col_b1, col_b2 = st.columns(2)
                if col_b1.button("✏️ MODIFICAR DOCUMENTO") and cl == CLAVE_MAESTRA:
                    conn.execute("UPDATE facturas SET nro_documento=?, proveedor=?, monto_total=? WHERE id=?", (n_nro, n_prov, n_monto, id_doc))
                    n_imp_count = conn.execute("SELECT COUNT(*) FROM facturas WHERE nro_documento=? AND proveedor=?", (item_doc['nro_documento']+"_P", item_doc['proveedor'])).fetchone()[0]
                    if n_imp_count > 0:
                        n_imp_valor = n_monto / n_imp_count
                        conn.execute("UPDATE facturas SET nro_documento=?, proveedor=?, monto_imputado=? WHERE nro_documento=? AND proveedor=?", (n_nro+"_P", n_prov, n_imp_valor, item_doc['nro_documento']+"_P", item_doc['proveedor']))
                    conn.commit(); guardar_en_drive(); st.rerun()
                if col_b2.button("🗑️ ELIMINAR DOCUMENTO") and cl == CLAVE_MAESTRA:
                    conn.execute("DELETE FROM facturas WHERE id=?", (id_doc,))
                    conn.execute("DELETE FROM facturas WHERE nro_documento=? AND proveedor=?", (item_doc['nro_documento']+"_P", item_doc['proveedor']))
                    conn.commit(); guardar_en_drive(); st.rerun()
    conn.close()

def modulo_tesoreria():
    st.header("💸 Tesorería")
    tp1, tp2, tp3 = st.tabs(["🔴 Pendientes", "🏢 Proveedor", "📅 Rango de Vencimiento"]); conn = conectar_db()
    with tp1:
        df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' AND nro_documento NOT LIKE '%_P' AND monto_total > 0 ORDER BY fecha_vencimiento ASC", conn)
        st.info(f"### DEUDA PENDIENTE: ${f_puntos(df_p['monto_total'].sum() if not df_p.empty else 0)}")
        if not df_p.empty:
            def style_vencidos(row): return ['background-color: #ffcccc' if pd.to_datetime(row['fecha_vencimiento']).date() < hoy else '' for _ in row]
            st.dataframe(df_p.style.apply(style_vencidos, axis=1).format({"monto_total": "${:,.0f}"}), use_container_width=True)
            
            # --- CORRECCIÓN V10.8.28: BOTÓN PDF PENDIENTES ---
            st.download_button("📥 Generar PDF de Pendientes", generar_pdf_blob(df_p.drop(columns=['id']), "LISTADO DE CUENTAS POR PAGAR (PENDIENTES)", True), "pendientes_tesoreria.pdf")
            
            st.divider(); id_p = st.selectbox("ID Factura", df_p['id']); met = st.selectbox("Medio", ["Transferencia", "Efectivo", "Cheque"])
            if st.button("💰 MARCAR PAGADO"):
                conn.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (met, hoy, id_p)); conn.commit(); guardar_en_drive(); st.rerun()
    with tp2:
        df_provs = pd.read_sql_query("SELECT DISTINCT proveedor FROM facturas WHERE estado='Pendiente' AND monto_total > 0", conn)
        if not df_provs.empty:
            p_sel = st.selectbox("Seleccione Proveedor", df_provs['proveedor'])
            df_det = pd.read_sql_query(f"SELECT nro_documento, fecha_vencimiento, monto_total FROM facturas WHERE proveedor='{p_sel}' AND estado='Pendiente' AND nro_documento NOT LIKE '%_P' AND monto_total > 0", conn)
            st.success(f"### DEUDA CON {p_sel}: ${f_puntos(df_det['monto_total'].sum())}"); st.dataframe(df_det.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
    conn.close()

def modulo_bodega():
    st.header("🚜 Bodega")
    tb1, tb2, tb3, tb4 = st.tabs(["📊 Stock", "🔄 Movimientos", "➕ Nuevo Insumo", "🔍 Consulta CC"]); conn = conectar_db()
    with tb1:
        df_s = pd.read_sql_query("SELECT id, producto, familia, stock, precio_medio FROM inventario ORDER BY producto ASC", conn)
        st.dataframe(df_s.drop(columns=['id']).style.format({"stock": "{:,.2f}", "precio_medio": "${:,.0f}"}), use_container_width=True)
        col_pdf1, col_pdf2 = st.columns(2)
        if not df_s.empty:
            with col_pdf1: st.download_button("📥 PDF Stock Valorizado (Admin)", generar_pdf_blob(df_s.drop(columns=['id']), "INVENTARIO VALORIZADO - ADMIN", True), "stock_admin.pdf")
            with col_pdf2: st.download_button("📥 PDF Stock para Trabajador", generar_pdf_blob(df_s.drop(columns=['id']), "INVENTARIO - LISTADO TRABAJO", False), "stock_trabajador.pdf")
        st.divider(); st.subheader("🛠️ Gestión de Insumos")
        id_gest = st.selectbox("Seleccione ID del Insumo a gestionar", df_s['id']) if not df_s.empty else None
        if id_gest:
            item = df_s[df_s['id'] == id_gest].iloc[0]; c1, c2 = st.columns(2)
            nuevo_nom = c1.text_input("Nuevo Nombre", value=item['producto']); nueva_fam = c2.selectbox("Nueva Familia", FAMILIAS_PRODUCTOS, index=FAMILIAS_PRODUCTOS.index(item['familia']) if item['familia'] in FAMILIAS_PRODUCTOS else 0)
            c3, c4 = st.columns(2); nuevo_stock = c3.number_input("Ajuste Stock", value=float(item['stock'])); nuevo_pmp = c4.number_input("Ajuste PMP", value=float(item['precio_medio']))
            cl = st.text_input("Clave de Autorización", type="password")
            if st.button("✏️ MODIFICAR INSUMO") and cl == CLAVE_MAESTRA:
                conn.execute("UPDATE inventario SET producto=?, familia=?, stock=?, precio_medio=? WHERE id=?", (nuevo_nom, nueva_fam, nuevo_stock, nuevo_pmp, id_gest)); conn.commit(); guardar_en_drive(); st.rerun()
    with tb2:
        tipo = st.radio("Acción", ["Salida (Campo)", "Entrada"])
        df_i = pd.read_sql_query("SELECT id, producto, precio_medio FROM inventario", conn)
        ps = st.selectbox("Insumo", df_i['id'].astype(str) + " - " + df_i['producto']) if not df_i.empty else None; ct = st.number_input("Cantidad", 0.0); ccs_sel_bod = []
        if tipo == "Salida (Campo)":
            cols_m = st.columns(3)
            for i, cc_name in enumerate(CENTROS_COSTO):
                if cols_m[i % 3].checkbox(cc_name, key=f"mov_bod_{cc_name}"): ccs_sel_bod.append(cc_name)
        if st.button("REGISTRAR") and ps:
            iid = int(ps.split(" - ")[0]); pmp = df_i[df_i['id'] == iid]['precio_medio'].values[0]
            if tipo == "Salida (Campo)" and ccs_sel_bod:
                for c in ccs_sel_bod: conn.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado) VALUES (?,?,?,?,?,?)", (iid, tipo, ct/len(ccs_sel_bod), hoy, c.upper(), (ct*pmp)/len(ccs_sel_bod)))
                conn.execute("UPDATE inventario SET stock = stock - ? WHERE id = ?", (ct, iid))
            else: conn.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (ct, iid))
            conn.commit(); guardar_en_drive(); st.rerun()
    with tb3:
        with st.form("nuevo_p"):
            n_p = st.text_input("Nombre"); f_p = st.selectbox("Familia", FAMILIAS_PRODUCTOS); s_p = st.number_input("Stock Inicial", 0.0); p_p = st.number_input("PMP", 0.0)
            if st.form_submit_button("CREAR"): conn.execute("INSERT INTO inventario (producto, familia, stock, precio_medio) VALUES (?,?,?,?)", (n_p, f_p, s_p, p_p)); conn.commit(); guardar_en_drive(); st.rerun()
    with tb4:
        cc_sel_bod = st.selectbox("Cuartel", CENTROS_COSTO)
        df_cc_bod = pd.read_sql_query(f"SELECT m.fecha, i.producto, m.tipo, m.cantidad, m.valor_imputado FROM movimientos m JOIN inventario i ON m.producto_id = i.id WHERE UPPER(TRIM(m.centro_costo)) = '{cc_sel_bod.upper()}' ORDER BY m.fecha DESC", conn)
        st.dataframe(df_cc_bod.style.format({"cantidad": "{:,.2f}", "valor_imputado": "${:,.0f}"}), use_container_width=True)
    conn.close()

def modulo_costos():
    st.header("💰 Costos Totales")
    conn = conectar_db()
    query = """
    SELECT UPPER(TRIM(centro_costo)) as cc, 
           SUM(CASE WHEN fuente = 'BODEGA' THEN val ELSE 0 END) as insumos, 
           SUM(CASE WHEN fuente = 'FACTURA' THEN val ELSE 0 END) as gastos, 
           SUM(CASE WHEN fuente = 'PETROLEO' THEN val ELSE 0 END) as combustible, 
           SUM(val) as total 
    FROM (
        SELECT centro_costo, valor_imputado as val, 'BODEGA' as fuente FROM movimientos WHERE tipo LIKE 'Salida%' AND centro_costo != ''
        UNION ALL 
        SELECT centro_costo, monto_imputado as val, 'FACTURA' as fuente FROM facturas WHERE tipo = 'Gasto Vario' AND centro_costo != '' AND centro_costo != 'CONTABILIDAD GENERAL'
        UNION ALL 
        SELECT centro_costo, valor_imputado as val, 'PETROLEO' as fuente FROM petroleo WHERE tipo = 'Salida' AND centro_costo != ''
    ) GROUP BY cc
    """
    df_t = pd.read_sql_query(query, conn); conn.close()
    if not df_t.empty: st.dataframe(df_t.style.format({"insumos": "${:,.0f}", "gastos": "${:,.0f}", "combustible": "${:,.0f}", "total": "${:,.0f}"}), use_container_width=True)

# --- NAVEGACIÓN ---
st.set_page_config(page_title="ERP LA CONCEPCIÓN v10.8.28", layout="wide")
inicializar_db()
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if not st.session_state['logged_in']: login_page()
else:
    if 'init' not in st.session_state: descargar_de_drive(); st.session_state['init'] = True
    with st.sidebar:
        st.title("MENÚ")
        if obtener_drive(): st.markdown("🟢 **Drive: CONECTADO**")
        menu = st.radio("", ["🏠 Dashboard", "⛽ PETRÓLEO", "📦 Compras", "💸 Tesorería", "🚜 Bodega", "💰 COSTOS"])
        if st.button("🚀 Sincronizar"): guardar_en_drive()
        if st.button("🚪 Salir"): st.session_state.clear(); st.rerun()
    if menu == "🏠 Dashboard": modulo_dashboard()
    elif menu == "⛽ PETRÓLEO": modulo_petroleo()
    elif menu == "📦 Compras": modulo_compras()
    elif menu == "💸 Tesorería": modulo_tesoreria()
    elif menu == "🚜 Bodega": modulo_bodega()
    elif menu == "💰 COSTOS": modulo_costos()
