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

# --- 2. MOTOR DE CONEXIÓN DRIVE ---
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
    if not drive:
        st.error("❌ Error de autenticación.")
        return
    try:
        query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
        lista = drive.ListFile({'q': query}).GetList()
        
        if lista:
            f = lista[0]
            f.SetContentFile(NOMBRE_DB)
            # Actualizamos el archivo (esto no consume cuota del robot si el dueño es usted)
            f.Upload(param={'supportsAllDrives': True})
            st.success("✅ Sincronización exitosa.")
        else:
            st.warning("⚠️ No se encontró el archivo en Drive. Súbalo manualmente una vez con el nombre erp_concepcion_v6.db")
            # Intento de creación por si acaso
            f = drive.CreateFile({'title': NOMBRE_DB, 'parents': [{'id': ID_CARPETA_DRIVE}]})
            f.SetContentFile(NOMBRE_DB)
            f.Upload(param={'supportsAllDrives': True})
    except Exception as e:
        st.error(f"❌ Error de Cuota: {e}")

def descargar_de_drive():
    drive = obtener_drive()
    if drive:
        try:
            query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
            lista = drive.ListFile({'q': query}).GetList()
            if lista: lista[0].GetContentFile(NOMBRE_DB)
        except: pass

# --- 3. BASE DE DATOS ---
def conectar_db():
    return sqlite3.connect(NOMBRE_DB, check_same_thread=False)

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
    
    users = [('osvaldolira@laconcepcion.cl', hash_password('9083')),
             ('secretaria@laconcepcion.cl', hash_password('1234')),
             ('secretarialaconcepcion@gmail.com', hash_password('5678'))]
    for email, pw in users:
        cursor.execute("SELECT * FROM usuarios WHERE email=?", (email,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO usuarios (email, password) VALUES (?,?)", (email, pw))
    conn.commit(); conn.close()

# --- 4. UTILIDADES ---
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

# --- 5. INTERFAZ ---
def inyectar_css():
    st.markdown("""<style>
        .main { background-color: #f4f7f6; }
        .stMetric { background-color: white; padding: 20px; border-radius: 12px; border-left: 6px solid #2E7D32; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }
        h1, h2, h3 { color: #1B5E20; font-family: 'Arial'; }
        .stButton>button { border-radius: 8px; background-color: #2E7D32; color: white; font-weight: bold; }
        </style>""", unsafe_allow_html=True)

def login_page():
    inyectar_css()
    st.markdown("<h1 style='text-align: center; color: #1B5E20; margin-top: 50px;'>🚜 ERP La Concepción</h1>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 1.2, 1])
    with col2:
        with st.form("login_form"):
            e, p = st.text_input("Email"), st.text_input("Clave", type="password")
            if st.form_submit_button("ACCEDER"):
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("SELECT email FROM usuarios WHERE email=? AND password=?", (e, hash_password(p)))
                if cursor.fetchone():
                    st.session_state['logged_in'], st.session_state['email'] = True, e; st.rerun()
                else: st.error("Fallo.")
                conn.close()

def modulo_dashboard():
    inyectar_css()
    st.markdown("<h1>🚜 Dashboard Agrícola</h1>", unsafe_allow_html=True)
    conn = conectar_db(); df_f = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente'", conn); conn.close()
    t_d = df_f['monto_total'].sum() if not df_f.empty else 0
    v_a = df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < hoy.replace(day=1)]['monto_total'].sum() if not df_f.empty else 0
    v_h = len(df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < hoy]) if not df_f.empty else 0
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("DEUDA TOTAL", f"${f_puntos(t_d)}")
    with c2: st.markdown("MESES ANTERIORES"); st.markdown(f"<h2 style='color:red;'>${f_puntos(v_a)}</h2>", unsafe_allow_html=True)
    with c3: st.markdown("VENCIDOS HOY"); st.markdown(f"<h2 style='color:orange;'>{v_h}</h2>", unsafe_allow_html=True)
    c4.metric("PENDIENTES", f"{len(df_f)}")
    st.divider()
    modulo_costos()

def modulo_compras():
    st.header("📦 Compras")
    t1, t2, t3 = st.tabs(["➕ Insumos", "💸 Gasto Vario", "🔍 Historial"])
    conn = conectar_db()
    with t1:
        c1, c2 = st.columns(2); nro, prov = c1.text_input("N° Factura"), c1.text_input("Proveedor"); fe, fv = c2.date_input("Emisión"), c2.date_input("Vencimiento")
        df_inv = pd.read_sql_query("SELECT id, producto, stock, precio_medio FROM inventario ORDER BY producto", conn)
        ps = st.selectbox("Insumo", df_inv['id'].astype(str) + " - " + df_inv['producto']) if not df_inv.empty else None
        ct, pr = st.number_input("Cant", 0.0), st.number_input("Neto", 0.0)
        if st.button("Añadir") and ps:
            if 'car' not in st.session_state: st.session_state['car'] = []
            st.session_state['car'].append({'id': int(ps.split(" - ")[0]), 'n': ps.split(" - ")[1], 'c': ct, 'p': pr, 't': ct*pr}); st.rerun()
        if st.session_state.get('car'):
            df_car = pd.DataFrame(st.session_state['car']); st.table(df_car)
            if st.button("💾 GUARDAR"):
                total_f = df_car['t'].sum()*1.19
                conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total) VALUES (?,?,?,?,?)", (nro, prov, fe, fv, total_f))
                for i in st.session_state['car']:
                    cur = conn.execute("SELECT stock, precio_medio FROM inventario WHERE id=?", (i['id'],)).fetchone()
                    n_pmp = ((cur[0]*cur[1]) + (i['c']*i['p'])) / (cur[0]+i['c']) if (cur[0]+i['c']) > 0 else i['p']
                    conn.execute("UPDATE inventario SET stock = stock + ?, precio_medio = ? WHERE id = ?", (i['c'], n_pmp, i['id']))
                conn.commit(); guardar_en_drive(); st.session_state['car'] = []; st.rerun()
    with t2:
        prov_g, nro_g = st.text_input("Proveedor ", key="pg"), st.text_input("N° Doc ", key="ng")
        fe_g, fv_g = st.date_input("Compra", hoy, key="fg1"), st.date_input("Vence", hoy, key="fg2")
        detalles_g = st.text_area("Concepto"); ccs_sel = []
        cols = st.columns(3)
        for i, cc in enumerate(CENTROS_COSTO):
            if cols[i % 3].checkbox(cc, key=f"gv_{cc}"): ccs_sel.append(cc)
        m_n = st.number_input("Neto Total", 0.0); iva = st.radio("IVA al costo?", ["SÍ", "NO"])
        if st.button("💾 GUARDAR GASTO") and len(ccs_sel) > 0:
            imp = (m_n / len(ccs_sel)) if iva == "SÍ" else (m_n / len(ccs_sel)) / 1.19
            conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, concepto) VALUES (?,?,?,?,?,?,?)", (nro_g, prov_g, fe_g, fv_g, m_n*1.19, 'Gasto Vario', detalles_g))
            for c in ccs_sel: conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, centro_costo, monto_imputado, concepto) VALUES (?,?,?,?,?,?,?,?,?)", (nro_g+"_P", prov_g, fe_g, fv_g, 0, 'Gasto Vario', c.upper(), imp, detalles_g))
            conn.commit(); guardar_en_drive(); st.rerun()
    with t3:
        f1, f2 = st.date_input("Desde", hoy-timedelta(days=30)), st.date_input("Hasta", hoy)
        df_h = pd.read_sql_query(f"SELECT id, nro_documento, proveedor, fecha_compra, monto_total, estado, tipo FROM facturas WHERE monto_total > 0 AND fecha_compra BETWEEN '{f1}' AND '{f2}' ORDER BY fecha_compra DESC", conn)
        st.dataframe(df_h.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
    conn.close()

def modulo_tesoreria():
    st.header("💸 Tesorería")
    conn = conectar_db()
    df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' AND monto_total > 0 ORDER BY fecha_vencimiento ASC", conn)
    st.info(f"### DEUDA PENDIENTE: ${f_puntos(df_p['monto_total'].sum() if not df_p.empty else 0)}")
    if not df_p.empty:
        def style_v(row): return ['background-color: #ffcccc' if pd.to_datetime(row['fecha_vencimiento']).date() < hoy else '' for _ in row]
        st.dataframe(df_p.style.apply(style_v, axis=1).format({"monto_total": "${:,.0f}"}), use_container_width=True)
        id_p = st.selectbox("ID Factura", df_p['id']); met = st.selectbox("Medio", ["Transferencia", "Efectivo", "Cheque"])
        if st.button("💰 PAGAR"):
            conn.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (met, hoy, id_p)); conn.commit(); guardar_en_drive(); st.rerun()
    conn.close()

def modulo_bodega():
    st.header("🚜 Bodega")
    tb1, tb2 = st.tabs(["📊 Stock", "🔄 Salidas/Entradas"])
    conn = conectar_db()
    with tb1:
        df_s = pd.read_sql_query("SELECT id, producto, familia, stock, precio_medio FROM inventario ORDER BY producto ASC", conn)
        st.dataframe(df_s.style.format({"stock": "{:,.2f}", "precio_medio": "${:,.0f}"}), use_container_width=True)
    with tb2:
        tipo = st.radio("Acción", ["Salida (Campo)", "Entrada"])
        df_i = pd.read_sql_query("SELECT id, producto, precio_medio FROM inventario", conn)
        ps = st.selectbox("Producto", df_i['id'].astype(str) + " - " + df_i['producto']); ct = st.number_input("Cantidad", 0.01)
        ccs_mov = []
        if tipo == "Salida (Campo)":
            cols_m = st.columns(3)
            for i, cc_n in enumerate(CENTROS_COSTO):
                if cols_m[i % 3].checkbox(cc_n, key=f"mov_{cc_n}"): ccs_mov.append(cc_n)
        if st.button("REGISTRAR"):
            item = df_i[df_i['id'] == int(ps.split(" - ")[0])].iloc[0]
            if tipo == "Salida (Campo)" and len(ccs_mov) > 0:
                val_p, cant_p = (ct * item['precio_medio'] / len(ccs_mov)), (ct / len(ccs_mov))
                for c in ccs_mov: conn.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado) VALUES (?,?,?,?,?,?)", (item['id'], tipo, cant_p, hoy, c.upper(), val_p))
                conn.execute("UPDATE inventario SET stock = stock - ? WHERE id = ?", (ct, item['id']))
            elif tipo == "Entrada":
                conn.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (ct, item['id']))
            conn.commit(); guardar_en_drive(); st.rerun()
    conn.close()

def modulo_costos():
    st.header("💰 Resumen Costos por Cuartel")
    conn = conectar_db(); query = """
    SELECT UPPER(TRIM(centro_costo)) as cc, SUM(CASE WHEN fuente = 'BODEGA' THEN val ELSE 0 END) as insumos, SUM(CASE WHEN fuente = 'FACTURA' THEN val ELSE 0 END) as gastos, SUM(val) as total
    FROM (SELECT centro_costo, valor_imputado as val, 'BODEGA' as fuente FROM movimientos WHERE tipo LIKE 'Salida%' UNION ALL SELECT centro_costo, monto_imputado as val, 'FACTURA' as fuente FROM facturas WHERE tipo = 'Gasto Vario') WHERE cc != '' GROUP BY cc """
    df_t = pd.read_sql_query(query, conn); conn.close()
    if not df_t.empty:
        df_total = pd.DataFrame([{"cc": "TOTAL GENERAL", "insumos": df_t["insumos"].sum(), "gastos": df_t["gastos"].sum(), "total": df_t["total"].sum()}])
        df_res = pd.concat([df_t, df_total], ignore_index=True)
        st.dataframe(df_res.style.apply(lambda r: ['font-weight: bold; background-color: #f1f8e9' if r['cc'] == "TOTAL GENERAL" else '' for _ in r], axis=1).format({"insumos": "${:,.0f}", "gastos": "${:,.0f}", "total": "${:,.0f}"}), use_container_width=True)

# --- 6. NAVEGACIÓN ---
st.set_page_config(page_title="ERP v11.7", layout="wide")
inicializar_db()
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if not st.session_state['logged_in']: login_page()
else:
    if 'init' not in st.session_state: descargar_de_drive(); st.session_state['init'] = True
    with st.sidebar:
        st.title("🚜 MENÚ")
        if obtener_drive(): st.markdown("🟢 **Drive: CONECTADO**")
        else: st.markdown("🔴 **Drive: DESCONECTADO**")
        menu = st.radio("", ["🏠 Dashboard", "📦 Compras", "💸 Tesorería", "🚜 Bodega", "💰 COSTOS"])
        if st.button("🚀 Sincronizar"): guardar_en_drive()
        if st.button("🚪 Salir"): st.session_state.clear(); st.rerun()
    if menu == "🏠 Dashboard": modulo_dashboard()
    elif menu == "📦 Compras": modulo_compras()
    elif menu == "💸 Tesorería": modulo_tesoreria()
    elif menu == "🚜 Bodega": modulo_bodega()
    elif menu == "💰 COSTOS": modulo_costos()
