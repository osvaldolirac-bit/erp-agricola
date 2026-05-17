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
        conn.execute("INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)", 
                     (user, accion, detalle, fecha))
        conn.commit()
        conn.close()
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
        st.success("✅ Respaldo en Drive Sincronizado.")

def descargar_de_drive():
    drive = obtener_drive()
    if drive:
        query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
        lista = drive.ListFile({'q': query}).GetList()
        if lista: lista[0].GetContentFile(NOMBRE_DB)

def sanear_y_recalcular():
    """Limpieza de huérfanos y neteo de petróleo retroactivo"""
    try:
        conn = conectar_db()
        conn.execute("""DELETE FROM facturas WHERE nro_documento LIKE '%_P' 
                        AND REPLACE(nro_documento, '_P', '') NOT IN (SELECT nro_documento FROM facturas WHERE nro_documento NOT LIKE '%_P')""")
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
    conn.commit(); conn.close()
    sanear_y_recalcular()

# --- 3. UTILIDADES Y PDF ---
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
            df_pdf = df_pdf[[c for c in df_pdf.columns if not any(x in c.lower() for x in ["precio", "valor", "monto", "pmp", "ajuste"])]]
        elif "Ajustes" in df_pdf.columns:
            df_pdf = df_pdf.drop(columns=['Ajustes'])
        cols = df_pdf.columns; w = 190 / len(cols)
        for col in cols: pdf.cell(w, 8, str(col).upper(), border=1, align="C")
        pdf.ln(); pdf.set_font("Helvetica", "", 7); total_acum = 0
        for _, row in df_pdf.iterrows():
            for i, item in enumerate(row):
                col_name = df_pdf.columns[i].lower()
                if any(x in col_name for x in ["monto", "total", "valor", "imputado"]):
                    try: total_acum += float(item)
                    except: pass
                val = f_decimal(item) if any(x in col_name for x in ["cantidad", "stock", "litros"]) else (f_puntos(item) if any(x in col_name for x in ["monto", "total", "precio", "valor", "pmp"]) else str(item))
                pdf.cell(w, 7, val[:25], border=1)
            pdf.ln()
        if total_acum > 0 and incluir_precios:
            pdf.set_font("Helvetica", "B", 9); pdf.cell(w * (len(cols)-1), 8, "TOTAL FINAL:", border=1, align="R")
            pdf.cell(w, 8, f"${f_puntos(total_acum)}", border=1, align="L")
        return pdf.output(dest="S").encode("latin-1")
    except: return None

def inyectar_css():
    st.markdown("""<style>
        .main { background-color: #f4f7f6; }
        .stMetric { background-color: white; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border-left: 5px solid #2E7D32; }
        .card-critico { border-left: 5px solid #d32f2f !important; }
        .card-vencida { border-left: 5px solid #f57c00 !important; }
        .card-pendiente { border-left: 5px solid #1976d2 !important; }
        .card-petroleo { border-left: 5px solid #455a64 !important; }
        .stButton>button { border-radius: 8px; font-weight: bold; }
        </style>""", unsafe_allow_html=True)
    if st.session_state.get('logged_in') and st.session_state.get('email') != 'osvaldolira@laconcepcion.cl':
        st.markdown("""<style>header {visibility: hidden;} #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display:none;}</style>""", unsafe_allow_html=True)

# --- 4. MÓDULOS DEL SISTEMA ---

def modulo_dashboard():
    st.markdown("<h1 style='text-align: center; color: #1B5E20;'>🚜 DASHBOARD PRINCIPAL</h1>", unsafe_allow_html=True)
    conn = conectar_db()
    df_f = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente' AND nro_documento NOT LIKE '%_P'", conn)
    df_p_c = pd.read_sql_query("SELECT SUM(litros) as l FROM petroleo WHERE tipo='Carga'", conn)
    df_p_s = pd.read_sql_query("SELECT SUM(litros) as l FROM petroleo WHERE tipo='Salida'", conn)
    saldo_pet = (df_p_c['l'].fillna(0).iloc[0]) - (df_p_s['l'].fillna(0).iloc[0])
    
    m1, m2, m3, m4, m5 = st.columns(5)
    with m1: st.metric("💰 DEUDA TOTAL", f"${f_puntos(df_f['monto_total'].sum())}")
    
    primer_dia_mes = hoy.replace(day=1)
    deuda_critica = df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < primer_dia_mes]['monto_total'].sum()
    with m2: st.markdown(f"<div class='stMetric card-critico'><small>🔥 MESES ANTERIORES</small><br><b>${f_puntos(deuda_critica)}</b><br><small style='color:red;'>CRÍTICO</small></div>", unsafe_allow_html=True)
    
    vencidas = len(df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < hoy])
    with m3: st.markdown(f"<div class='stMetric card-vencida'><small>⚠️ VENCIDAS</small><br><b>{vencidas}</b><br><small>DOCS</small></div>", unsafe_allow_html=True)
    
    with m4: st.markdown(f"<div class='stMetric card-pendiente'><small>📄 PENDIENTES</small><br><b>{len(df_f)}</b><br><small>PAGOS</small></div>", unsafe_allow_html=True)
    
    with m5: st.markdown(f"<div class='stMetric card-petroleo'><small>⛽ PETRÓLEO</small><br><b>{f_decimal(saldo_pet)}L</b><br><small>NETO</small></div>", unsafe_allow_html=True)
    
    st.divider(); c_izq, c_der = st.columns([1.6, 1])
    with c_izq:
        st.subheader("💰 Gastos Netos por Cuartel")
        df_c = pd.read_sql_query("""SELECT UPPER(TRIM(cc)) as cc, SUM(val) as total FROM (
            SELECT centro_costo as cc, valor_imputado as val FROM movimientos WHERE tipo LIKE 'Salida%' 
            UNION ALL SELECT centro_costo as cc, monto_imputado as val FROM facturas WHERE nro_documento LIKE '%_P'
            UNION ALL SELECT centro_costo as cc, valor_imputado as val FROM petroleo WHERE tipo = 'Salida'
            UNION ALL SELECT centro_costo as cc, monto as val FROM ajustes_costos
        ) WHERE cc != '' GROUP BY cc""", conn)
        if not df_c.empty:
            df_c = pd.concat([df_c, pd.DataFrame([{'cc': 'TOTAL GENERAL', 'total': df_c['total'].sum()}])], ignore_index=True)
            st.dataframe(df_c.style.format({"total": "${:,.0f}"}), use_container_width=True)
    with c_der:
        st.subheader("📅 Proyección 4 Meses")
        meses_n = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
        for i in range(4):
            f_p = (datetime.now().replace(day=1) + timedelta(days=i*31)).replace(day=1)
            total_m = df_f[(pd.to_datetime(df_f['fecha_vencimiento']).dt.month == f_p.month) & (pd.to_datetime(df_f['fecha_vencimiento']).dt.year == f_p.year)]['monto_total'].sum() if not df_f.empty else 0
            st.markdown(f"<div style='background:white; padding:10px; border-radius:8px; margin-bottom:5px; border-right: 5px solid #1976d2; display:flex; justify-content:space-between;'><b>{meses_n[f_p.month-1]} {f_p.year}</b> <span>${f_puntos(total_m)}</span></div>", unsafe_allow_html=True)
    conn.close()

def modulo_petroleo():
    st.header("⛽ Gestión de Petróleo")
    t1, t2, t3 = st.tabs(["📥 Carga", "🚜 Salida", "📊 Historial"]); conn = conectar_db()
    with t1:
        with st.form("p_c"):
            lts, mt, f = st.number_input("Litros", 0.0), st.number_input("Total Factura Bruto ($)", 0.0), st.date_input("Fecha", hoy)
            if st.form_submit_button("REGISTRAR CARGA"):
                neto = (mt / 1.19) - (lts * IMPUESTO_ESPECIFICO_LITRO)
                conn.execute("INSERT INTO petroleo (tipo, litros, monto_total_compra, fecha) VALUES (?,?,?,?)", ("Carga", lts, neto, f))
                conn.commit(); guardar_en_drive(); st.rerun()
    with t2:
        with st.form("p_s"):
            lts_s, veh, res, ccs_sel = st.number_input("Litros Salida", 0.0), st.text_input("Vehículo"), st.text_input("Responsable"), []
            cols = st.columns(3)
            for i, cc in enumerate(CENTROS_COSTO):
                if cols[i%3].checkbox(cc, key=f"ps_{cc}"): ccs_sel.append(cc)
            if st.form_submit_button("REGISTRAR SALIDA"):
                df_calc = pd.read_sql_query("SELECT SUM(litros) as l, SUM(monto_total_compra) as m FROM petroleo WHERE tipo='Carga'", conn)
                pmp_n = (df_calc['m'].iloc[0] / df_calc['l'].iloc[0]) if df_calc['l'].iloc[0] > 0 else 0
                for c in ccs_sel:
                    conn.execute("INSERT INTO petroleo (tipo, litros, vehiculo, responsable, centro_costo, fecha, valor_imputado) VALUES (?,?,?,?,?,?,?)", ("Salida", lts_s/len(ccs_sel), veh, res, c.upper(), hoy, (lts_s/len(ccs_sel)*pmp_n)))
                conn.commit(); st.rerun()
    with t3:
        df_p = pd.read_sql_query("SELECT id, fecha, tipo, litros, centro_costo, vehiculo, valor_imputado FROM petroleo ORDER BY id DESC", conn)
        st.dataframe(df_p.style.format({"litros": "{:,.2f}", "valor_imputado": "${:,.0f}"}), use_container_width=True)
        st.download_button("📥 PDF Historial", generar_pdf_blob(df_p, "HISTORIAL PETROLEO"), "petroleo.pdf")
        id_p = st.selectbox("ID a borrar", df_p['id']); cl = st.text_input("Master", type="password", key="cl_p")
        if st.button("🗑️ ELIMINAR") and cl == CLAVE_MAESTRA:
            conn.execute("DELETE FROM petroleo WHERE id=?", (id_p,)); conn.commit(); st.rerun()
    conn.close()

def modulo_compras():
    st.header("📦 Compras y Gastos")
    t1, t2, t3 = st.tabs(["➕ Insumos", "💸 Gasto Vario", "🔍 Historial"]); conn = conectar_db()
    with t1:
        c1, c2 = st.columns(2); nro, prov, fe, fv = c1.text_input("N°"), c1.text_input("Proveedor"), c2.date_input("Emisión"), c2.date_input("Vence")
        df_i = pd.read_sql_query("SELECT id, producto FROM inventario", conn)
        cp1, cp2, cp3, cp4 = st.columns([3,1,1,1]); ps = cp1.selectbox("Insumo", df_i['id'].astype(str) + " - " + df_i['producto']) if not df_i.empty else None
        ct, pr = cp2.number_input("Cant", 0.0), cp3.number_input("Neto", 0.0)
        if cp4.button("➕"):
            if 'car' not in st.session_state: st.session_state['car'] = []
            st.session_state['car'].append({'id': int(ps.split(" - ")[0]), 'n': ps.split(" - ")[1], 'c': ct, 'p': pr, 't': ct*pr}); st.rerun()
        if st.session_state.get('car'):
            df_car = pd.DataFrame(st.session_state['car']); st.table(df_car)
            if st.button("💾 GUARDAR FACTURA INSUMOS"):
                total = df_car['t'].sum() * 1.19
                conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total) VALUES (?,?,?,?,?)", (nro, prov, fe, fv, total))
                for i in st.session_state['car']:
                    cur = conn.execute("SELECT stock, precio_medio FROM inventario WHERE id=?", (i['id'],)).fetchone()
                    n_pmp = ((cur[0]*cur[1]) + (i['c']*i['p'])) / (cur[0]+i['c']) if (cur[0]+i['c']) > 0 else i['p']
                    conn.execute("UPDATE inventario SET stock = stock + ?, precio_medio = ? WHERE id = ?", (i['c'], n_pmp, i['id']))
                conn.commit(); st.session_state['car'] = []; guardar_en_drive(); st.rerun()
    with t2:
        pg, ng, fg1, fg2 = st.text_input("Proveedor", key="pg"), st.text_input("N° Doc", key="ng"), st.date_input("Fecha Compra", hoy), st.date_input("Fecha Vencimiento", hoy)
        sel_cc = []
        cols = st.columns(3)
        for i, cc in enumerate(CENTROS_COSTO):
            if cols[i%3].checkbox(cc, key=f"gv_{cc}"): sel_cc.append(cc)
        mt = st.number_input("Total Bruto ($)", 0.0); iva = st.radio("¿Imputar TOTAL al CC?", ["SÍ", "NO (NETO)"])
        if st.button("💾 GUARDAR GASTO"):
            if conn.execute("SELECT COUNT(*) FROM facturas WHERE nro_documento=? AND proveedor=?", (ng, pg)).fetchone()[0] > 0: st.error("Duplicado"); return
            imp = mt if iva == "SÍ" else mt/1.19
            if sel_cc:
                conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo) VALUES (?,?,?,?,?,?)", (ng, pg, fg1, fg2, mt, 'Gasto Vario'))
                for c in sel_cc: conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, centro_costo, monto_imputado) VALUES (?,?,?,?,?,?,?,?)", (ng+"_P", pg, fg1, fg2, 0, 'Gasto Vario', c.upper(), imp/len(sel_cc)))
            else: conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo) VALUES (?,?,?,?,?,?)", (ng, pg, fg1, fg2, mt, 'Gasto Vario'))
            conn.commit(); guardar_en_drive(); st.rerun()
    with t3:
        df_h = pd.read_sql_query(f"SELECT id, nro_documento, proveedor, fecha_compra, monto_total FROM facturas WHERE monto_total > 0 AND nro_documento NOT LIKE '%_P' ORDER BY fecha_compra DESC", conn)
        st.dataframe(df_h.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
        st.download_button("📥 PDF Historial", generar_pdf_blob(df_h, "HISTORIAL COMPRAS"), "compras.pdf")
        id_del = st.selectbox("ID factura", df_h['id']); cl = st.text_input("Master", type="password", key="cl_h")
        if st.button("🗑️ ELIMINAR") and cl == CLAVE_MAESTRA:
            sel_f = df_h[df_h['id']==id_del].iloc[0]
            conn.execute("DELETE FROM facturas WHERE id=?", (id_del,))
            conn.execute("DELETE FROM facturas WHERE nro_documento=? AND proveedor=?", (sel_f['nro_documento']+"_P", sel_f['proveedor']))
            conn.commit(); st.rerun()
    conn.close()

def modulo_tesoreria():
    st.header("💸 Tesorería")
    t1, t2 = st.tabs(["🔴 Pendientes", "🏢 Por Proveedor"]); conn = conectar_db()
    with t1:
        df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' AND nro_documento NOT LIKE '%_P' AND monto_total > 0 ORDER BY fecha_vencimiento ASC", conn)
        st.warning(f"### DEUDA PENDIENTE: ${f_puntos(df_p['monto_total'].sum())}")
        st.dataframe(df_p.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
        st.download_button("📥 PDF Pendientes", generar_pdf_blob(df_p.drop(columns=['id']), "PENDIENTES"), "pendientes.pdf")
        id_pay = st.selectbox("ID Pago", df_p['id']); met = st.selectbox("Método", ["Transferencia", "Efectivo", "Cheque"])
        if st.button("💰 PAGAR"): conn.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (met, hoy, id_pay)); conn.commit(); st.rerun()
    with t2:
        df_list = pd.read_sql_query("SELECT DISTINCT proveedor FROM facturas WHERE estado='Pendiente' AND monto_total > 0", conn)
        if not df_list.empty:
            pr = st.selectbox("Proveedor", df_list['proveedor'])
            df_pr = pd.read_sql_query(f"SELECT nro_documento, fecha_vencimiento, monto_total FROM facturas WHERE proveedor='{pr}' AND estado='Pendiente' AND nro_documento NOT LIKE '%_P'", conn)
            st.error(f"### DEUDA TOTAL {pr}: ${f_puntos(df_pr['monto_total'].sum())}")
            st.dataframe(df_pr.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
            st.download_button(f"📥 PDF {pr}", generar_pdf_blob(df_pr, f"DEUDA: {pr}"), f"deuda_{pr}.pdf")
    conn.close()

def modulo_bodega():
    st.header("🏠 Bodega")
    t1, t2, t3, t4 = st.tabs(["📊 Stock", "🔄 Salida", "➕ Nuevo Registro", "🔍 Consulta CC"]); conn = conectar_db()
    with t1:
        df_s = pd.read_sql_query("SELECT id, producto, familia, stock, precio_medio FROM inventario", conn)
        st.dataframe(df_s.drop(columns=['id']).style.format({"stock": "{:,.2f}", "precio_medio": "${:,.0f}"}), use_container_width=True)
        c1, c2 = st.columns(2)
        with c1: st.download_button("📥 PDF Admin", generar_pdf_blob(df_s.drop(columns=['id']), "STOCK ADMIN", True), "stock_admin.pdf")
        with c2: st.download_button("📥 PDF Campo", generar_pdf_blob(df_s.drop(columns=['id']), "STOCK CAMPO", False), "stock_campo.pdf")
        st.divider(); id_g = st.selectbox("ID Insumo", df_s['id']); item = df_s[df_s['id']==id_g].iloc[0]
        n_nom = st.text_input("Editar Nombre", item['producto']); n_st = st.number_input("Editar Stock", value=float(item['stock']))
        cl = st.text_input("Clave Maestra", type="password", key="cl_b_master")
        if st.button("✏️ MODIFICAR") and cl == CLAVE_MAESTRA:
            conn.execute("UPDATE inventario SET producto=?, stock=? WHERE id=?", (n_nom, round(n_st, 2), id_g)); conn.commit(); st.rerun()
        if st.button("🗑️ ELIMINAR") and cl == CLAVE_MAESTRA:
            check = conn.execute("SELECT COUNT(*) FROM movimientos WHERE producto_id=?", (id_g,)).fetchone()[0]
            if check > 0: st.error("No se puede borrar, tiene movimientos."); return
            conn.execute("DELETE FROM inventario WHERE id=?", (id_g,)); conn.commit(); st.rerun()
    with t2:
        df_i = pd.read_sql_query("SELECT id, producto, precio_medio FROM inventario", conn)
        ps = st.selectbox("Insumo", df_i['id'].astype(str) + " - " + df_i['producto']); ct = st.number_input("Cant", 0.0)
        cols = st.columns(3); sel_cc = []
        for i, cc in enumerate(CENTROS_COSTO):
            if cols[i%3].checkbox(cc, key=f"mb_{cc}"): sel_cc.append(cc)
        if st.button("REGISTRAR SALIDA"):
            iid = int(ps.split(" - ")[0]); p = df_i[df_i['id']==iid]['precio_medio'].iloc[0]
            if ct > 0 and sel_cc:
                cant_r = round(ct/len(sel_cc), 2)
                for c in sel_cc: conn.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado) VALUES (?,?,?,?,?)", (iid, "Salida", cant_r, hoy, c.upper(), (cant_r*p)))
                conn.execute("UPDATE inventario SET stock = stock - ? WHERE id = ?", (round(ct, 2), iid)); conn.commit(); st.rerun()
    with t3:
        with st.form("nuevo_insumo_form"):
            n_prod = st.text_input("Nombre del Producto")
            n_fam = st.selectbox("Familia", FAMILIAS_PRODUCTOS)
            n_stk = st.number_input("Stock Inicial", 0.0)
            n_pmp = st.number_input("Precio Neto Inicial", 0.0)
            if st.form_submit_button("➕ CREAR PRODUCTO"):
                if n_prod:
                    conn.execute("INSERT INTO inventario (producto, familia, stock, precio_medio) VALUES (?,?,?,?)", (n_prod, n_fam, round(n_stk, 2), n_pmp))
                    conn.commit(); st.success("Creado!"); st.rerun()
    with t4:
        cc_q = st.selectbox("CC", CENTROS_COSTO)
        df_cc = pd.read_sql_query(f"SELECT m.fecha, i.producto, m.cantidad, m.valor_imputado FROM movimientos m JOIN inventario i ON m.producto_id = i.id WHERE m.centro_costo = '{cc_q.upper()}' ORDER BY m.fecha DESC", conn)
        st.dataframe(df_cc.style.format({"cantidad": "{:,.2f}", "valor_imputado": "${:,.0f}"}), use_container_width=True)
    conn.close()

def modulo_costos():
    st.header("💰 Informe de Costos")
    es_admin = (st.session_state.get('email') == 'osvaldolira@laconcepcion.cl')
    tabs = st.tabs(["📊 Resumen", "🔧 AJUSTE"]) if es_admin else st.tabs(["📊 Resumen"])
    conn = conectar_db()
    with tabs[0]:
        df_r = pd.read_sql_query("""SELECT UPPER(TRIM(cc)) as cc, SUM(CASE WHEN fuente = 'BODEGA' THEN val ELSE 0 END) as Insumos, SUM(CASE WHEN fuente = 'FACTURA' THEN val ELSE 0 END) as Gastos, SUM(CASE WHEN fuente = 'PETROLEO' THEN val ELSE 0 END) as Petroleo, SUM(CASE WHEN fuente = 'AJUSTE' THEN val ELSE 0 END) as Ajustes, SUM(val) as Total FROM (SELECT centro_costo as cc, valor_imputado as val, 'BODEGA' as fuente FROM movimientos UNION ALL SELECT centro_costo as cc, monto_imputado as val, 'FACTURA' as fuente FROM facturas WHERE nro_documento LIKE '%_P' UNION ALL SELECT centro_costo as cc, valor_imputado as val, 'PETROLEO' as fuente FROM petroleo WHERE tipo='Salida' UNION ALL SELECT centro_costo as cc, monto as val, 'AJUSTE' as fuente FROM ajustes_costos) WHERE cc != '' GROUP BY cc""", conn)
        if not df_r.empty:
            df_m = df_r.copy()
            if not es_admin: df_m = df_m.drop(columns=['Ajustes'])
            st.dataframe(df_m.style.format({c: "${:,.0f}" for c in df_m.columns if c != 'cc'}), use_container_width=True)
            st.download_button("📥 PDF Costos", generar_pdf_blob(df_r, "INFORME COSTOS"), "costos.pdf")
    if es_admin:
        with tabs[1]:
            cc_aj = st.selectbox("CC Ajuste", CENTROS_COSTO); m_aj = st.number_input("Monto (+/-)"); mot = st.text_input("Motivo")
            if st.button("💾 APLICAR") and st.text_input("Clave", type="password") == CLAVE_MAESTRA:
                conn.execute("INSERT INTO ajustes_costos (centro_costo, monto, fecha, motivo) VALUES (?,?,?,?)", (cc_aj.upper(), m_aj, hoy, mot)); conn.commit(); st.rerun()
    conn.close()

def modulo_seguridad():
    st.header("🕵️ Auditoría Pro")
    conn = conectar_db()
    t1, t2 = st.tabs(["📜 Bitácora Movimientos", "🔑 Historial Accesos"])
    with t1:
        df_b = pd.read_sql_query("SELECT * FROM bitacora ORDER BY id DESC", conn)
        st.dataframe(df_b, use_container_width=True)
        st.download_button("📥 PDF Bitácora", generar_pdf_blob(df_b, "BITACORA"), "bitacora.pdf")
    with t2:
        df_a = pd.read_sql_query("SELECT * FROM log_accesos ORDER BY id DESC", conn)
        st.dataframe(df_a, use_container_width=True)
        st.download_button("📥 PDF Accesos", generar_pdf_blob(df_a, "HISTORIAL ACCESOS"), "accesos.pdf")
    conn.close()

# --- 5. PÁGINA DE LOGIN ---
def login_page():
    inyectar_css()
    st.markdown("<h1 style='text-align: center; color: #1B5E20; margin-top: 50px;'>🚜 ERP La Concepción</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        with st.form("login_pro"):
            e, p = st.text_input("Email"), st.text_input("Contraseña", type="password")
            if st.form_submit_button("ACCEDER"):
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("SELECT email FROM usuarios WHERE email=? AND password=?", (e, hash_password(p)))
                if cursor.fetchone():
                    cursor.execute("INSERT INTO log_accesos (email, fecha_hora) VALUES (?,?)", (e, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                    conn.commit(); conn.close()
                    st.session_state['logged_in'], st.session_state['email'] = True, e; st.rerun()
                else: conn.close(); st.error("Acceso denegado")

# --- 6. NAVEGACIÓN PRINCIPAL ---
st.set_page_config(page_title="ERP LA CONCEPCIÓN v10.8.62", layout="wide")
inicializar_db()

if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False

if not st.session_state['logged_in']:
    login_page()
else:
    if 'init' not in st.session_state: descargar_de_drive(); st.session_state['init'] = True
    inyectar_css()
    with st.sidebar:
        st.title("ERP LA CONCEPCIÓN")
        st.markdown("<span style='color:green; font-weight:bold;'>🟢 CONECTADO</span>", unsafe_allow_html=True)
        st.divider()
        menu = st.radio("MENÚ", ["DASHBOARD", "Petróleo", "Compras", "Tesorería", "Bodega", "Costos"] + (["Seguridad"] if st.session_state['email'] == 'osvaldolira@laconcepcion.cl' else []))
        if st.session_state['email'] == 'osvaldolira@laconcepcion.cl' and st.button("🚀 Sincronizar Drive"): guardar_en_drive()
        if st.button("🚪 Cerrar Sesión"): st.session_state.clear(); st.rerun()
    
    if menu == "DASHBOARD": modulo_dashboard()
    elif menu == "Petróleo": modulo_petroleo()
    elif menu == "Compras": modulo_compras()
    elif menu == "Tesorería": modulo_tesoreria()
    elif menu == "Bodega": modulo_bodega()
    elif menu == "Costos": modulo_costos()
    elif menu == "Seguridad": modulo_seguridad()
