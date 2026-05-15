import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
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
inicio_mes = hoy.replace(day=1)

FAMILIAS_PRODUCTOS = ["FERTILIZANTE", "FERTILIZANTE FOLIAR", "HERBICIDA", "INSECTICIDA", "FUNGICIDA", "BIO ESTIMULANTE", "ACARICIDA", "REGULADOR DE CRECIMIENTO", "ADHERENTE / MOJANTE", "OTROS"]
CENTROS_COSTO = ["CEREZOS CORTE1", "CEREZOS CORTE2", "CIRUELOS", "NOGALES APARICION", "NOGALES CRUZ DEL SUR", "OTROS"]
METODOS_PAGO = ["TRANSFERENCIA", "CHEQUE", "EFECTIVO", "TARJETA", "OTRO"]

# --- 2. MOTOR DRIVE ---
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
            st.success("✅ Sincronizado")
    except: pass

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
    cursor.execute("CREATE TABLE IF NOT EXISTS facturas (id INTEGER PRIMARY KEY AUTOINCREMENT, nro_documento TEXT, proveedor TEXT, fecha_compra DATE, fecha_vencimiento DATE, monto_total REAL, estado TEXT DEFAULT 'Pendiente', tipo TEXT DEFAULT 'Factura', metodo_pago TEXT, fecha_pago DATE, centro_costo TEXT, monto_imputado REAL DEFAULT 0, concepto TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS inventario (id INTEGER PRIMARY KEY AUTOINCREMENT, producto TEXT, familia TEXT, stock REAL DEFAULT 0, precio_medio REAL DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS movimientos (id INTEGER PRIMARY KEY AUTOINCREMENT, producto_id INTEGER, tipo TEXT, cantidad REAL, centro_costo TEXT, fecha DATE, valor_imputado REAL DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, password TEXT)")
    conn.commit(); conn.close()

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

# --- 4. MÓDULOS ---

def modulo_dashboard():
    st.title("🏠 Dashboard")
    conn = conectar_db()
    df_p = pd.read_sql_query("SELECT monto_total, fecha_vencimiento FROM facturas WHERE estado='Pendiente'", conn)
    conn.close()
    t_deuda = 0; m_rojo = 0; d_rojo = 0; m_naranja = 0; d_naranja = 0
    if not df_p.empty:
        t_deuda = df_p['monto_total'].sum()
        df_p['fecha_vencimiento'] = pd.to_datetime(df_p['fecha_vencimiento'], errors='coerce').dt.date
        df_p = df_p.dropna(subset=['fecha_vencimiento'])
        v_ant = df_p[df_p['fecha_vencimiento'] < inicio_mes]
        m_rojo = v_ant['monto_total'].sum(); d_rojo = len(v_ant)
        v_mes = df_p[(df_p['fecha_vencimiento'] >= inicio_mes) & (df_p['fecha_vencimiento'] < hoy)]
        m_naranja = v_mes['monto_total'].sum(); d_naranja = len(v_mes)
    c1, c2, c3 = st.columns(3)
    c1.metric("DEUDA TOTAL", f"${f_puntos(t_deuda)}")
    with c2:
        st.markdown(f"<p style='color:red; font-weight:bold;'>MESES ANTERIORES</p><h2 style='color:red;'>${f_puntos(m_rojo)}</h2><small>Docs: {d_rojo}</small>", unsafe_allow_html=True)
    with c3:
        st.markdown(f"<p style='color:orange; font-weight:bold;'>VENCIDOS DEL MES</p><h2 style='color:orange;'>${f_puntos(m_naranja)}</h2><small>Docs: {d_naranja}</small>", unsafe_allow_html=True)
    st.divider(); modulo_costos()

def modulo_compras():
    st.header("📦 Compras y Gastos")
    t1, t2, t3 = st.tabs(["➕ Insumos", "💸 Gasto Vario", "🔍 Historial"])
    conn = conectar_db()
    with t1:
        c1, c2 = st.columns(2)
        nro, prov = c1.text_input("N° Factura"), c1.text_input("Proveedor")
        f_c, f_v = c2.date_input("Emisión"), c2.date_input("Vencimiento")
        df_inv = pd.read_sql_query("SELECT id, producto FROM inventario", conn)
        ops = [f"{row['id']} - {row['producto']}" for _, row in df_inv.iterrows()]
        ps = st.selectbox("Seleccione Insumo", ops) if ops else None
        cant, neto = st.number_input("Cantidad", 0.0), st.number_input("Neto Unitario", 0.0)
        if st.button("Guardar Factura Insumo"):
            total = (cant * neto) * 1.19
            insumo_nombre = ps.split(" - ")[1] if ps else ""
            conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, concepto) VALUES (?,?,?,?,?,?)", (nro, prov, f_c, f_v, total, f"Compra: {insumo_nombre}"))
            if ps:
                pid = int(ps.split(" - ")[0]); cur = conn.execute("SELECT stock, precio_medio FROM inventario WHERE id=?", (pid,)).fetchone()
                n_pmp = ((cur[0]*cur[1]) + (cant*neto)) / (cur[0]+cant) if (cur[0]+cant) > 0 else neto
                conn.execute("UPDATE inventario SET stock=stock+?, precio_medio=? WHERE id=?", (cant, n_pmp, pid))
            conn.commit(); guardar_en_drive(); st.rerun()
    with t2:
        gv_prov, gv_neto = st.text_input("Proveedor ", key="g_p"), st.number_input("Monto Neto ($)", 0.0, key="g_m")
        gv_det = st.text_area("Detalle del Gasto")
        iva_costo = st.radio("¿IVA es costo para el CC?", ["Sí", "No"], horizontal=True)
        cols = st.columns(3)
        ccs_g = [cc for i, cc in enumerate(CENTROS_COSTO) if cols[i%3].checkbox(cc, key=f"cg_{cc}")]
        if st.button("Grabar Gasto") and ccs_g:
            m_imp = (gv_neto * 1.19) if "Sí" in iva_costo else gv_neto
            m_por_cc = m_imp / len(ccs_g)
            for c in ccs_g:
                conn.execute("INSERT INTO facturas (proveedor, monto_total, tipo, centro_costo, monto_imputado, estado, fecha_compra, concepto) VALUES (?,?,?,?,?,?,?,?)", (gv_prov, gv_neto*1.19, 'Gasto Vario', c, m_por_cc, 'Pendiente', hoy, gv_det))
            conn.commit(); guardar_en_drive(); st.rerun()
    with t3:
        df_h = pd.read_sql_query("SELECT * FROM facturas ORDER BY id DESC LIMIT 50", conn)
        st.dataframe(df_h, use_container_width=True)
        if not df_h.empty:
            st.download_button("📥 PDF Historial", generar_pdf(df_h, "HISTORIAL"), "hist.pdf")
    conn.close()

def modulo_bodega():
    st.header("🚜 Gestión de Bodega")
    t1, t2, t3, t4 = st.tabs(["📊 Stock", "🔄 Movimientos", "🔍 Consulta Cuartel", "➕ Nuevo Item"])
    conn = conectar_db()
    
    with t1:
        df_s = pd.read_sql_query("SELECT id, producto, familia, stock, precio_medio FROM inventario", conn)
        st.dataframe(df_s, use_container_width=True)
        if not df_s.empty: st.download_button("📥 PDF Stock", generar_pdf(df_s, "STOCK"), "stock.pdf")
    
    with t2:
        st.subheader("Registrar Movimiento de Producto")
        df_inv = pd.read_sql_query("SELECT id, producto, stock, precio_medio FROM inventario", conn)
        ops = [f"{row['id']} - {row['producto']}" for _, row in df_inv.iterrows()]
        
        ps = st.selectbox("Seleccione Producto", ops, key="mov_prod") if ops else None
        cant = st.number_input("Cantidad", 0.0, key="mov_cant")
        
        es_salida = st.checkbox("¿Es una SALIDA a campo?")
        
        if es_salida:
            st.info("Seleccione los Centros de Costo destino:")
            cols_cc = st.columns(3)
            ccs_s = [cc for i, cc in enumerate(CENTROS_COSTO) if cols_cc[i%3].checkbox(cc, key=f"mov_cc_{cc}")]
            
            if st.button("Confirmar Salida") and ps and ccs_s:
                pid = int(ps.split(" - ")[0])
                # PMP para el costo
                pmp = df_inv[df_inv['id']==pid]['precio_medio'].values[0]
                val_p = (cant * pmp) / len(ccs_s)
                for c in ccs_s:
                    conn.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, centro_costo, valor_imputado, fecha) VALUES (?,?,?,?,?,?)", (pid, 'Salida', cant/len(ccs_s), c, val_p, hoy))
                conn.execute("UPDATE inventario SET stock = stock - ? WHERE id = ?", (cant, pid))
                conn.commit(); guardar_en_drive(); st.rerun()
        else:
            if st.button("Confirmar Entrada (Ajuste)"):
                pid = int(ps.split(" - ")[0])
                conn.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (cant, pid))
                conn.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, centro_costo, fecha) VALUES (?,?,?,?,?)", (pid, 'Entrada Ajuste', cant, 'BODEGA', hoy))
                conn.commit(); guardar_en_drive(); st.rerun()

    with t3:
        cc_sel = st.selectbox("Filtrar Cuartel", CENTROS_COSTO)
        df_q = pd.read_sql_query(f"SELECT * FROM movimientos WHERE centro_costo='{cc_sel}'", conn)
        st.dataframe(df_q, use_container_width=True)
    
    with t4:
        with st.form("ni"):
            n, f, p = st.text_input("Nombre"), st.selectbox("Familia", FAMILIAS_PRODUCTOS), st.number_input("PMP Inicial", 0.0)
            if st.form_submit_button("Crear Insumo"):
                conn.execute("INSERT INTO inventario (producto, familia, precio_medio, stock) VALUES (?,?,?,0)", (n, f, p))
                conn.commit(); st.rerun()
    conn.close()

def modulo_tesoreria():
    st.header("💸 Tesorería")
    conn = conectar_db()
    df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' ORDER BY fecha_vencimiento ASC", conn)
    if not df_p.empty:
        st.dataframe(df_p, use_container_width=True)
        id_p = st.selectbox("ID Pago", df_p['id']); met = st.selectbox("Método", METODOS_PAGO)
        if st.button("Marcar como Pagado"):
            conn.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (met, hoy, id_p))
            conn.commit(); guardar_en_drive(); st.rerun()
    conn.close()

def modulo_costos():
    st.header("📊 COSTOS")
    conn = conectar_db()
    q = "SELECT centro_costo, SUM(valor_imputado) as Total FROM movimientos GROUP BY centro_costo UNION ALL SELECT centro_costo, SUM(monto_imputado) as Total FROM facturas WHERE tipo='Gasto Vario' GROUP BY centro_costo"
    df = pd.read_sql_query(q, conn)
    if not df.empty:
        res = df.groupby('centro_costo')['Total'].sum().reset_index()
        st.table(res.style.format({"Total": "${:,.0f}"}))
    conn.close()

# --- 5. NAVEGACIÓN ---
st.set_page_config(page_title="ERP AGRICOLA v40", layout="wide")
inicializar_db()
if 'auth' not in st.session_state: st.session_state['auth'] = False
if not st.session_state['auth']:
    st.title("🚜 Acceso ERP")
    u, p = st.text_input("Email"), st.text_input("Contraseña", type="password")
    if st.button("Entrar") and (p == CLAVE_MAESTRA or p == "9083"): st.session_state['auth'] = True; st.rerun()
else:
    if 'init' not in st.session_state: descargar_de_drive(); st.session_state['init'] = True
    with st.sidebar:
        if obtener_drive(): st.success("🟢 Conectado")
        menu = st.radio("MENÚ", ["🏠 Dashboard", "📦 Compras", "🚜 Bodega", "💸 Tesorería", "📊 Costos"])
        if st.button("🚀 Sincronizar"): guardar_en_drive()
        if st.button("🚪 Salir"): st.session_state['auth'] = False; st.rerun()
    if menu == "🏠 Dashboard": modulo_dashboard()
    elif menu == "📦 Compras": modulo_compras()
    elif menu == "🚜 Bodega": modulo_bodega()
    elif menu == "💸 Tesorería": modulo_tesoreria()
    elif menu == "📊 Costos": modulo_costos()
