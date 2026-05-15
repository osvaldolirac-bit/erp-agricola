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

# --- 1. CONFIGURACIÓN ---
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
            st.success("✅ Datos sincronizados en Drive")
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

# --- 4. MÓDULOS ---

def modulo_dashboard():
    st.title("🏠 Dashboard")
    conn = conectar_db()
    df_p = pd.read_sql_query("SELECT monto_total, fecha_vencimiento FROM facturas WHERE estado='Pendiente'", conn)
    conn.close()
    t_deuda = 0; m_rojo = 0; m_naranja = 0
    if not df_p.empty:
        t_deuda = df_p['monto_total'].sum()
        df_p['fecha_vencimiento'] = pd.to_datetime(df_p['fecha_vencimiento'], errors='coerce').dt.date
        df_p = df_p.dropna(subset=['fecha_vencimiento'])
        m_rojo = df_p[df_p['fecha_vencimiento'] < inicio_mes]['monto_total'].sum()
        m_naranja = df_p[(df_p['fecha_vencimiento'] >= inicio_mes) & (df_p['fecha_vencimiento'] < hoy)]['monto_total'].sum()
    
    c1, c2, c3 = st.columns(3)
    c1.metric("DEUDA TOTAL", f"${int(t_deuda):,}".replace(",", "."))
    c2.metric("CRÍTICO (VENCIDO)", f"${int(m_rojo):,}".replace(",", "."))
    c3.metric("POR VENCER", f"${int(m_naranja):,}".replace(",", "."))

def modulo_bodega():
    st.header("🚜 Gestión de Bodega")
    t1, t2, t3, t4 = st.tabs(["🔄 Movimientos", "📊 Stock", "🔍 Consultas", "➕ Nuevo Item"])
    conn = conectar_db()
    
    with t1:
        st.subheader("Registrar Movimiento")
        df_inv = pd.read_sql_query("SELECT id, producto, stock, precio_medio FROM inventario", conn)
        ops = [f"{r['id']} - {r['producto']}" for _, r in df_inv.iterrows()]
        
        # Selector de Insumo
        ps = st.selectbox("Seleccione Insumo", ops, key="final_ps") if ops else None
        cant = st.number_input("Cantidad", 0.0, key="final_ca")
        op = st.radio("Operación", ["Entrada", "Salida"], horizontal=True)
        
        if op == "Entrada":
            p_neto = st.number_input("Precio Neto Unitario", 0.0)
            if st.button("📥 Confirmar Entrada"):
                pid = int(ps.split(" - ")[0])
                cur = conn.execute("SELECT stock, precio_medio FROM inventario WHERE id=?", (pid,)).fetchone()
                n_pmp = ((cur[0]*cur[1]) + (cant*p_neto)) / (cur[0]+cant) if (cur[0]+cant) > 0 else p_neto
                conn.execute("UPDATE inventario SET stock=stock+?, precio_medio=? WHERE id=?", (cant, n_pmp, pid))
                conn.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, centro_costo, fecha, valor_imputado) VALUES (?,?,?,?,?,?)", (pid, 'Entrada', cant, 'BODEGA', hoy, p_neto*cant))
                conn.commit(); guardar_en_drive(); st.rerun()
        else:
            st.write("Seleccione Centros de Costo:")
            cols = st.columns(3)
            # Captura explícita de seleccionados
            seleccionados = []
            for i, cc in enumerate(CENTROS_COSTO):
                if cols[i%3].checkbox(cc, key=f"fchk_{cc}"):
                    seleccionados.append(cc)
            
            if st.button("🔄 Confirmar Salida") and seleccionados:
                pid = int(ps.split(" - ")[0])
                pmp = df_inv[df_inv['id']==pid]['precio_medio'].values[0]
                num_cc = len(seleccionados)
                val_cc = (cant * pmp) / num_cc
                cant_cc = cant / num_cc
                for c_dest in seleccionados:
                    conn.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, centro_costo, valor_imputado, fecha) VALUES (?,?,?,?,?,?)", (pid, 'Salida', cant_cc, c_dest, val_cc, hoy))
                conn.execute("UPDATE inventario SET stock=stock-? WHERE id=?", (cant, pid))
                conn.commit(); guardar_en_drive(); st.rerun()

    with t2:
        st.dataframe(pd.read_sql_query("SELECT * FROM inventario", conn), use_container_width=True)
    with t3:
        cc_f = st.selectbox("Ver Cuartel", CENTROS_COSTO)
        st.dataframe(pd.read_sql_query(f"SELECT * FROM movimientos WHERE centro_costo='{cc_f}'", conn), use_container_width=True)
    with t4:
        with st.form("ni"):
            n, f, p = st.text_input("Nombre"), st.selectbox("Familia", FAMILIAS_PRODUCTOS), st.number_input("Precio Inicial", 0.0)
            if st.form_submit_button("Crear"):
                conn.execute("INSERT INTO inventario (producto, familia, precio_medio, stock) VALUES (?,?,?,0)", (n, f, p))
                conn.commit(); st.rerun()
    conn.close()

# --- 5. NAVEGACIÓN ---
st.set_page_config(page_title="ERP AGRICOLA v52", layout="wide")
inicializar_db()
if 'auth' not in st.session_state: st.session_state['auth'] = False
if not st.session_state['auth']:
    st.title("🚜 Acceso ERP")
    u, p = st.text_input("Email"), st.text_input("Contraseña", type="password")
    if st.button("Entrar") and (p == CLAVE_MAESTRA or p == "9083"): st.session_state['auth'] = True; st.rerun()
else:
    if 'init' not in st.session_state: descargar_de_drive(); st.session_state['init'] = True
    with st.sidebar:
        if obtener_drive(): st.success("🟢 Nube Conectada")
        menu = st.radio("MENÚ", ["🏠 Dashboard", "🚜 Bodega"])
        if st.button("🚀 Sincronizar"): guardar_en_drive()
        if st.button("🚪 Salir"): st.session_state['auth'] = False; st.rerun()
    if menu == "🏠 Dashboard": modulo_dashboard()
    elif menu == "🚜 Bodega": modulo_bodega()
