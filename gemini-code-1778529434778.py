import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
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
            st.success("✅ Respaldo en Drive actualizado")
    except: pass

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

def hash_pw(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def inicializar_db():
    conn = conectar_db(); cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS facturas (id INTEGER PRIMARY KEY AUTOINCREMENT, nro_documento TEXT, proveedor TEXT, fecha_compra DATE, fecha_vencimiento DATE, monto_total REAL, estado TEXT DEFAULT 'Pendiente', tipo TEXT DEFAULT 'Factura', metodo_pago TEXT, fecha_pago DATE, centro_costo TEXT, monto_imputado REAL DEFAULT 0, concepto TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS inventario (id INTEGER PRIMARY KEY AUTOINCREMENT, producto TEXT, familia TEXT, stock REAL DEFAULT 0, precio_medio REAL DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS movimientos (id INTEGER PRIMARY KEY AUTOINCREMENT, producto_id INTEGER, tipo TEXT, cantidad REAL, centro_costo TEXT, fecha DATE, valor_imputado REAL DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, password TEXT)")
    users = [('osvaldolira@laconcepcion.cl', hash_pw('9083')), ('secretaria@laconcepcion.cl', hash_pw('1234')), ('secretarialaconcepcion@gmail.com', hash_pw('5678'))]
    for e, p in users: cursor.execute("INSERT OR IGNORE INTO usuarios (email, password) VALUES (?,?)", (e, p))
    conn.commit(); conn.close()

def f_puntos(v):
    try: return f"{int(round(float(v))):,}".replace(",", ".")
    except: return "0"

def generar_pdf(df, titulo):
    pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, f"LA CONCEPCIÓN - {titulo}", ln=True, align="C")
    pdf.set_font("Arial", "B", 8); pdf.ln(5)
    cols = df.columns; w = 190 / len(cols)
    for col in cols: pdf.cell(w, 8, str(col).upper()[:15], border=1)
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
        st.markdown(f"<p style='color:red; font-weight:bold;'>CRÍTICO (MESES ANTERIORES)</p><h2 style='color:red;'>${f_puntos(m_rojo)}</h2><small>Docs: {d_rojo}</small>", unsafe_allow_html=True)
    with c3:
        st.markdown(f"<p style='color:orange; font-weight:bold;'>VENCIDO EN EL MES</p><h2 style='color:orange;'>${f_puntos(m_naranja)}</h2><small>Docs: {d_naranja}</small>", unsafe_allow_html=True)
    st.divider(); modulo_costos()

def modulo_bodega():
    st.header("🚜 Gestión de Bodega")
    t1, t2, t3, t4 = st.tabs(["📊 Stock", "🔄 Movimientos", "🔍 Consulta Cuartel", "➕ Nuevo Insumo"])
    conn = conectar_db()
    with t1:
        df_s = pd.read_sql_query("SELECT id, producto, familia, stock, precio_medio FROM inventario", conn); st.dataframe(df_s, use_container_width=True)
        if not df_s.empty: st.download_button("📥 PDF Stock", generar_pdf(df_s, "STOCK"), "stock.pdf")
    
    with t2:
        st.subheader("Registrar Movimiento")
        df_inv = pd.read_sql_query("SELECT id, producto, stock, precio_medio FROM inventario", conn)
        ops_bod = [f"{r['id']} - {r['producto']}" for _, r in df_inv.iterrows()]
        
        # Barra de Selección de Insumo
        ps = st.selectbox("1. Seleccione Producto / Insumo", ops_bod, key="bm_ps_final") if ops_bod else None
        
        if ps:
            cant = st.number_input("2. Ingrese Cantidad Total", 0.0, key="bm_ca_final")
            op_tipo = st.radio("3. Tipo de Operación", ["Entrada (Recibir Insumo)", "Salida (Despacho a Campo)"], horizontal=True)
            
            if "Entrada" in op_tipo:
                p_unit = st.number_input("Precio Unitario Neto ($)", 0.0, key="bm_pu_final")
                if st.button("Confirmar Entrada"):
                    pid = int(ps.split(" - ")[0])
                    cur = conn.execute("SELECT stock, precio_medio FROM inventario WHERE id=?", (pid,)).fetchone()
                    n_pmp = ((cur[0]*cur[1]) + (cant*p_unit)) / (cur[0]+cant) if (cur[0]+cant) > 0 else p_unit
                    conn.execute("UPDATE inventario SET stock=stock+?, precio_medio=? WHERE id=?", (cant, n_pmp, pid))
                    conn.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, centro_costo, fecha, valor_imputado) VALUES (?,?,?,?,?,?)", (pid, 'Entrada', cant, 'BODEGA', hoy, p_unit*cant))
                    conn.commit(); guardar_en_drive(); st.rerun()
            else:
                st.write("Seleccione Centros de Costo para repartir:")
                cols_cc = st.columns(3)
                # FIX: Lista dinámica de seleccionados
                seleccionados = [cc for i, cc in enumerate(CENTROS_COSTO) if cols_cc[i%3].checkbox(cc, key=f"bm_cc_chk_v2_{cc}")]
                
                if st.button("Confirmar Salida Multi-CC") and ccs_s := seleccionados:
                    pid = int(ps.split(" - ")[0])
                    pmp = df_inv[df_inv['id']==pid]['precio_medio'].values[0]
                    v_total = cant * pmp
                    v_por_cc = v_total / len(ccs_s)
                    cant_por_cc = cant / len(ccs_s)
                    
                    # Insertar un registro por cada centro de costo seleccionado
                    for c in ccs_s:
                        conn.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, centro_costo, valor_imputado, fecha) VALUES (?,?,?,?,?,?)", 
                                     (pid, 'Salida', cant_por_cc, c, v_por_cc, hoy))
                    
                    conn.execute("UPDATE inventario SET stock=stock-? WHERE id=?", (cant, pid))
                    conn.commit(); guardar_en_drive(); st.rerun()
        else:
            st.warning("No hay productos. Cree uno en la pestaña '+'")

    with t3:
        cc_sel = st.selectbox("Cuartel", CENTROS_COSTO)
        df_q = pd.read_sql_query(f"SELECT * FROM movimientos WHERE centro_costo='{cc_sel}'", conn); st.dataframe(df_q, use_container_width=True)
    with t4:
        with st.form("ni_bod"):
            n, f, p = st.text_input("Nombre"), st.selectbox("Familia", FAMILIAS_PRODUCTOS), st.number_input("PMP Inicial", 0.0)
            if st.form_submit_button("Crear Insumo"):
                conn.execute("INSERT INTO inventario (producto, familia, precio_medio, stock) VALUES (?,?,?,0)", (n, f, p)); conn.commit(); st.rerun()
    conn.close()

def modulo_compras():
    st.header("📦 Compras y Gastos")
    t1, t2, t3 = st.tabs(["➕ Insumos", "💸 Gasto Vario", "🔍 Historial"])
    conn = conectar_db()
    with t1:
        c1, c2 = st.columns(2)
        nro, prov = c1.text_input("N° Factura"), c1.text_input("Proveedor")
        f_c, f_v = c2.date_input("Emisión"), c2.date_input("Vencimiento")
        df_inv = pd.read_sql_query("SELECT id, producto FROM inventario", conn)
        ops = [f"{r['id']} - {r['producto']}" for _, r in df_inv.iterrows()]
        ps = st.selectbox("Insumo para Factura", ops, key="compra_sel_v2") if ops else None
        cant, neto = st.number_input("Cantidad", 0.0), st.number_input("Neto Unitario", 0.0)
        if st.button("Guardar Factura Insumo"):
            total = (cant * neto) * 1.19
            conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, concepto) VALUES (?,?,?,?,?,?)", (nro, prov, f_c, f_v, total, f"Factura Insumos"))
            if ps:
                pid = int(ps.split(" - ")[0])
                cur = conn.execute("SELECT stock, precio_medio FROM inventario WHERE id=?", (pid,)).fetchone()
                n_pmp = ((cur[0]*cur[1]) + (cant*neto)) / (cur[0]+cant) if (cur[0]+cant) > 0 else neto
                conn.execute("UPDATE inventario SET stock=stock+?, precio_medio=? WHERE id=?", (cant, n_pmp, pid))
            conn.commit(); guardar_en_drive(); st.rerun()
    with t2:
        gv_prov, gv_neto = st.text_input("Proveedor ", key="gp_v2"), st.number_input("Monto Neto ($)", 0.0, key="gm_v2")
        gv_det = st.text_area("Detalle del Gasto")
        iva_c = st.radio("¿IVA es costo?", ["Sí", "No"], horizontal=True)
        cols = st.columns(3)
        ccs_g = [cc for i, cc in enumerate(CENTROS_COSTO) if cols[i%3].checkbox(cc, key=f"cg_v2_{cc}")]
        if st.button("Grabar Gasto") and ccs_g:
            m_imp = (gv_neto * 1.19) if iva_c == "Sí" else gv_neto
            m_p = m_imp / len(ccs_g)
            for c in ccs_g:
                conn.execute("INSERT INTO facturas (proveedor, monto_total, tipo, centro_costo, monto_imputado, estado, fecha_compra, concepto) VALUES (?,?,?,?,?,?,?,?)", (gv_prov, gv_neto*1.19, 'Gasto Vario', c, m_p, 'Pendiente', hoy, gv_det))
            conn.commit(); guardar_en_drive(); st.rerun()
    conn.close()

def modulo_tesoreria():
    st.header("💸 Tesorería")
    conn = conectar_db()
    df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' ORDER BY fecha_vencimiento ASC", conn)
    if not df_p.empty:
        st.dataframe(df_p, use_container_width=True)
        id_p = st.selectbox("ID Pago", df_p['id']); met = st.selectbox("Método", METODOS_PAGO)
        if st.button("Marcar Pagado"):
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
st.set_page_config(page_title="ERP LA CONCEPCIÓN v48", layout="wide")
inicializar_db()
if 'auth' not in st.session_state: st.session_state['auth'] = False
if not st.session_state['auth']:
    st.title("🚜 ERP LA CONCEPCIÓN")
    u, p = st.text_input("Email Corporativo"), st.text_input("Contraseña", type="password")
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
