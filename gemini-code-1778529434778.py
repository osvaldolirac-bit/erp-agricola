import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import os
import hashlib
import io
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
METODOS_PAGO = ["TRANSFERENCIA", "CHEQUE", "EFECTIVO", "TARJETA", "OTRO"]

# --- 2. MOTOR DRIVE (ANTI-QUOTA) ---
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
    if not drive: return
    try:
        query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
        lista = drive.ListFile({'q': query}).GetList()
        if lista:
            f = lista[0]
            f.SetContentFile(NOMBRE_DB)
            f.Upload(param={'supportsAllDrives': True})
            st.success("✅ Respaldo en Drive actualizado.")
    except Exception as e: st.error(f"Error Sincronización: {e}")

def descargar_de_drive():
    drive = obtener_drive()
    if drive:
        try:
            query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
            lista = drive.ListFile({'q': query}).GetList()
            if lista: lista[0].GetContentFile(NOMBRE_DB)
        except: pass

# --- 3. BASE DE DATOS Y SEGURIDAD ---
def conectar_db():
    return sqlite3.connect(NOMBRE_DB, check_same_thread=False)

def hash_pw(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def inicializar_db():
    conn = conectar_db(); cursor = conn.cursor()
    # Tablas
    cursor.execute("CREATE TABLE IF NOT EXISTS facturas (id INTEGER PRIMARY KEY AUTOINCREMENT, nro_documento TEXT, proveedor TEXT, fecha_compra DATE, fecha_vencimiento DATE, monto_total REAL, estado TEXT DEFAULT 'Pendiente', tipo TEXT DEFAULT 'Factura', metodo_pago TEXT, fecha_pago DATE, centro_costo TEXT, monto_imputado REAL DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS inventario (id INTEGER PRIMARY KEY AUTOINCREMENT, producto TEXT, familia TEXT, stock REAL DEFAULT 0, precio_medio REAL DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS movimientos (id INTEGER PRIMARY KEY AUTOINCREMENT, producto_id INTEGER, tipo TEXT, cantidad REAL, centro_costo TEXT, fecha DATE, valor_imputado REAL DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, password TEXT)")
    
    # Inserción de usuarios originales
    users = [
        ('osvaldolira@laconcepcion.cl', hash_pw('9083')),
        ('secretaria@laconcepcion.cl', hash_pw('1234')),
        ('secretarialaconcepcion@gmail.com', hash_pw('5678'))
    ]
    for email, pw in users:
        cursor.execute("INSERT OR IGNORE INTO usuarios (email, password) VALUES (?,?)", (email, pw))
    conn.commit(); conn.close()

# --- 4. UTILIDADES ---
def f_puntos(v):
    try: return f"{int(round(float(v))):,}".replace(",", ".")
    except: return "0"

def generar_pdf(df, titulo):
    pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, f"LA CONCEPCIÓN - {titulo}", ln=True, align="C")
    pdf.set_font("Arial", "B", 8); pdf.ln(5)
    cols = df.columns; w = 190 / len(cols)
    for col in cols: pdf.cell(w, 8, str(col).upper(), border=1)
    pdf.ln(); pdf.set_font("Arial", "", 7)
    for _, row in df.iterrows():
        for item in row: pdf.cell(w, 7, str(item)[:20], border=1)
        pdf.ln()
    return pdf.output(dest="S").encode("latin-1")

# --- 5. MÓDULOS ---

def modulo_dashboard():
    st.title("🏠 Dashboard")
    conn = conectar_db()
    df_p = pd.read_sql_query("SELECT monto_total, fecha_vencimiento FROM facturas WHERE estado='Pendiente' AND tipo='Factura'", conn)
    deuda_t = df_p['monto_total'].sum() if not df_p.empty else 0
    vencidos = df_p[pd.to_datetime(df_p['fecha_vencimiento']).dt.date < hoy] if not df_p.empty else pd.DataFrame()
    
    c1, c2, c3 = st.columns(3)
    c1.metric("DEUDA TOTAL", f"${f_puntos(deuda_t)}")
    c2.metric("DOCS. VENCIDOS", len(vencidos), delta=f"${f_puntos(vencidos['monto_total'].sum())}" if not vencidos.empty else "0", delta_color="inverse")
    
    st.subheader("📅 Proyección de Pagos (4 Meses)")
    if not df_p.empty:
        df_p['mes'] = pd.to_datetime(df_p['fecha_vencimiento']).dt.strftime('%Y-%m')
        proy = df_p.groupby('mes')['monto_total'].sum().reset_index().sort_values('mes').head(4)
        st.bar_chart(proy.set_index('mes'))
    conn.close()

def modulo_compras():
    st.header("📦 Compras")
    t1, t2, t3 = st.tabs(["➕ Insumos", "💸 Gasto Vario", "🔍 Historial"])
    conn = conectar_db()
    
    with t1:
        c1, c2 = st.columns(2)
        nro, prov = c1.text_input("N° Factura"), c1.text_input("Proveedor")
        f_c, f_v = c2.date_input("Emisión"), c2.date_input("Vencimiento")
        df_inv = pd.read_sql_query("SELECT id, producto FROM inventario", conn)
        ps = st.selectbox("Insumo", df_inv['id'].astype(str) + " - " + df_inv['producto']) if not df_inv.empty else None
        cant, neto = st.number_input("Cantidad", 0.0), st.number_input("Precio Neto Unitario", 0.0)
        if st.button("💾 Guardar Factura Insumo"):
            total = (cant * neto) * 1.19
            conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total) VALUES (?,?,?,?,?)", (nro, prov, f_c, f_v, total))
            if ps:
                pid = int(ps.split(" - ")[0]); cur = conn.execute("SELECT stock, precio_medio FROM inventario WHERE id=?", (pid,)).fetchone()
                nuevo_pmp = ((cur[0]*cur[1]) + (cant*neto)) / (cur[0]+cant) if (cur[0]+cant) > 0 else neto
                conn.execute("UPDATE inventario SET stock=stock+?, precio_medio=? WHERE id=?", (cant, nuevo_pmp, pid))
            conn.commit(); guardar_en_drive(); st.rerun()

    with t2:
        st.subheader("Gasto Directo a Cuartel (Checkboxes)")
        g_prov, g_neto = st.text_input("Proveedor ", key="g_p"), st.number_input("Monto Neto Total", 0.0, key="g_m")
        cols = st.columns(3)
        ccs_g = [cc for i, cc in enumerate(CENTROS_COSTO) if cols[i%3].checkbox(cc, key=f"cg_{cc}")]
        if st.button("💾 Registrar Gasto Vario") and ccs_g:
            monto_p = g_neto / len(ccs_g)
            for c in ccs_g:
                conn.execute("INSERT INTO facturas (proveedor, monto_total, tipo, centro_costo, monto_imputado, estado, fecha_compra) VALUES (?,?,?,?,?,?,?)", (g_prov, 0, 'Gasto Vario', c, monto_p, 'Imputado', hoy))
            conn.commit(); guardar_en_drive(); st.rerun()

    with t3:
        st.subheader("🔍 Historial con Gestión")
        c1, c2 = st.columns(2)
        d_h, h_h = c1.date_input("Desde", hoy-timedelta(days=30)), c2.date_input("Hasta", hoy)
        df_h = pd.read_sql_query(f"SELECT * FROM facturas WHERE fecha_compra BETWEEN '{d_h}' AND '{h_h}' ORDER BY id DESC", conn)
        st.dataframe(df_h, use_container_width=True)
        if not df_h.empty:
            st.download_button("📥 PDF Historial", generar_pdf(df_h, "HISTORIAL COMPRAS"), "hist.pdf")
            st.divider()
            id_sel = st.selectbox("ID Factura", df_h['id'])
            pw = st.text_input("Clave (2908)", type="password", key="pw_c")
            if st.button("🗑️ Eliminar") and pw == CLAVE_MAESTRA:
                conn.execute("DELETE FROM facturas WHERE id=?", (id_sel,)); conn.commit(); guardar_en_drive(); st.rerun()
            if st.button("✏️ Modificar Monto") and pw == CLAVE_MAESTRA:
                nuevo_m = st.number_input("Nuevo Total", 0.0)
                conn.execute("UPDATE facturas SET monto_total=? WHERE id=?", (nuevo_m, id_sel)); conn.commit(); guardar_en_drive(); st.rerun()
    conn.close()

def modulo_bodega():
    st.header("🚜 Bodega")
    t1, t2, t3, t4 = st.tabs(["📊 Stock", "🔄 Salidas", "🔍 Consulta Cuartel", "➕ Nuevo Item"])
    conn = conectar_db()
    with t1:
        df_s = pd.read_sql_query("SELECT * FROM inventario", conn)
        st.dataframe(df_s, use_container_width=True)
        if not df_s.empty: st.download_button("📥 PDF Stock", generar_pdf(df_s, "STOCK"), "stock.pdf")
    with t2:
        df_i = pd.read_sql_query("SELECT id, producto, stock, precio_medio FROM inventario WHERE stock > 0", conn)
        if not df_i.empty:
            ps = st.selectbox("Insumo", df_i['id'].astype(str) + " - " + df_i['producto'])
            cant_s = st.number_input("Cantidad", 0.0); cols = st.columns(3)
            ccs_s = [cc for i, cc in enumerate(CENTROS_COSTO) if cols[i%3].checkbox(cc, key=f"bs_{cc}")]
            if st.button("✅ Registrar Salida") and ccs_s:
                pid = int(ps.split(" - ")[0]); pmp = df_i[df_i['id']==pid]['precio_medio'].values[0]
                val_p = (cant_s * pmp) / len(ccs_s)
                for c in ccs_s: conn.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, centro_costo, valor_imputado, fecha) VALUES (?,?,?,?,?,?)", (pid, 'Salida', cant_s/len(ccs_s), c, val_p, hoy))
                conn.execute("UPDATE inventario SET stock=stock-? WHERE id=?", (cant_s, pid))
                conn.commit(); guardar_en_drive(); st.rerun()
    with t3:
        st.subheader("🔍 Consulta por Cuartel")
        cc_sel = st.selectbox("Cuartel", CENTROS_COSTO)
        df_q = pd.read_sql_query(f"SELECT * FROM movimientos WHERE centro_costo='{cc_sel}'", conn)
        st.dataframe(df_q, use_container_width=True)
        if not df_q.empty: st.download_button("📥 PDF Consulta", generar_pdf(df_q, f"MOV_{cc_sel}"), "cons.pdf")
    with t4:
        with st.form("ni"):
            n, f = st.text_input("Nombre"), st.selectbox("Familia", FAMILIAS_PRODUCTOS)
            p_ini = st.number_input("PMP Inicial", 0.0)
            if st.form_submit_button("Crear Insumo"):
                conn.execute("INSERT INTO inventario (producto, familia, precio_medio, stock) VALUES (?,?,?,0)", (n, f, p_ini))
                conn.commit(); st.rerun()
    conn.close()

def modulo_tesoreria():
    st.header("💸 Tesorería")
    t1, t2 = st.tabs(["💰 Pago Documentos", "🔍 Historial Pagos"])
    conn = conectar_db()
    with t1:
        df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' AND tipo='Factura' ORDER BY fecha_vencimiento ASC", conn)
        if not df_p.empty:
            st.dataframe(df_p, use_container_width=True)
            id_p = st.selectbox("ID Factura", df_p['id']); metodo = st.selectbox("Método", METODOS_PAGO)
            if st.button("💰 Confirmar Pago"):
                conn.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (metodo, hoy, id_p)); conn.commit(); guardar_en_drive(); st.rerun()
            st.download_button("📥 PDF Deuda", generar_pdf(df_p, "DEUDA"), "deuda.pdf")
    with t2:
        c1, c2 = st.columns(2); d_p, h_p = c1.date_input("Desde ", hoy-timedelta(days=30)), c2.date_input("Hasta ", hoy)
        df_h_p = pd.read_sql_query(f"SELECT * FROM facturas WHERE estado='Pagado' AND fecha_pago BETWEEN '{d_p}' AND '{h_p}'", conn)
        st.dataframe(df_h_p, use_container_width=True)
        if not df_h_p.empty: st.download_button("📥 PDF Pagos", generar_pdf(df_h_p, "PAGOS"), "pagos.pdf")
    conn.close()

def modulo_costos():
    st.header("📊 COSTOS")
    conn = conectar_db()
    q = """ SELECT UPPER(centro_costo) as Cuartel, SUM(valor_imputado) as Total FROM movimientos GROUP BY Cuartel
            UNION ALL
            SELECT UPPER(centro_costo) as Cuartel, SUM(monto_imputado) as Total FROM facturas WHERE tipo='Gasto Vario' GROUP BY Cuartel """
    df_c = pd.read_sql_query(q, conn)
    if not df_c.empty:
        res = df_c.groupby('Cuartel')['Total'].sum().reset_index()
        st.table(res.style.format({"Total": "${:,.0f}"}))
    conn.close()

# --- 6. NAVEGACIÓN Y LOGIN ---
st.set_page_config(page_title="ERP LA CONCEPCIÓN v25.0", layout="wide")
inicializar_db()

if 'auth' not in st.session_state: st.session_state['auth'] = False

if not st.session_state['auth']:
    st.markdown("<h1 style='text-align: center;'>🚜 ERP LA CONCEPCIÓN</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        u_ingreso = st.text_input("Email Corporativo")
        p_ingreso = st.text_input("Contraseña / Clave Maestra", type="password")
        if st.button("ENTRAR"):
            conn = conectar_db(); cursor = conn.cursor()
            cursor.execute("SELECT * FROM usuarios WHERE email=? AND password=?", (u_ingreso, hash_pw(p_ingreso)))
            if cursor.fetchone() or p_ingreso == CLAVE_MAESTRA:
                st.session_state['auth'] = True; st.rerun()
            else: st.error("Acceso Denegado")
            conn.close()
else:
    if 'init' not in st.session_state: descargar_de_drive(); st.session_state['init'] = True
    with st.sidebar:
        st.title("MENÚ")
        menu = st.radio("", ["🏠 Dashboard", "📦 Compras", "🚜 Bodega", "💸 Tesorería", "📊 COSTOS"])
        if st.button("🚀 Sincronizar"): guardar_en_drive()
        if st.button("🚪 Salir"): st.session_state['auth'] = False; st.rerun()
    
    if menu == "🏠 Dashboard": modulo_dashboard()
    elif menu == "📦 Compras": modulo_compras()
    elif menu == "🚜 Bodega": modulo_bodega()
    elif menu == "💸 Tesorería": modulo_tesoreria()
    elif menu == "📊 COSTOS": modulo_costos()
