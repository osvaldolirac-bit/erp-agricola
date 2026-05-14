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

# --- 1. CONFIGURACIÓN ---
ID_CARPETA_DRIVE = "12tjxWa_RVRP5YuYd2sypjBO8bPuyMqo6" 
NOMBRE_DB = 'erp_concepcion_v6.db'
CLAVE_MAESTRA = "2908" 
hoy = datetime.now().date()

FAMILIAS_PRODUCTOS = ["FERTILIZANTE", "FERTILIZANTE FOLIAR", "HERBICIDA", "INSECTICIDA", "FUNGICIDA", "BIO ESTIMULANTE", "ACARICIDA", "REGULADOR DE CRECIMIENTO", "ADHERENTE / MOJANTE", "OTROS"]
CENTROS_COSTO = ["CEREZOS CORTE1", "CEREZOS CORTE2", "CIRUELOS", "NOGALES APARICION", "NOGALES CRUZ DEL SUR", "OTROS"]
METODOS_PAGO = ["TRANSFERENCIA", "CHEQUE", "EFECTIVO", "TARJETA", "OTRO"]

# --- 2. MOTOR DRIVE (Sincronización) ---
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

# --- 3. BASE DE DATOS ---
def conectar_db():
    return sqlite3.connect(NOMBRE_DB, check_same_thread=False)

def hash_pw(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def inicializar_db():
    conn = conectar_db(); cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS facturas (id INTEGER PRIMARY KEY AUTOINCREMENT, nro_documento TEXT, proveedor TEXT, fecha_compra DATE, fecha_vencimiento DATE, monto_total REAL, estado TEXT DEFAULT 'Pendiente', tipo TEXT DEFAULT 'Factura', metodo_pago TEXT, fecha_pago DATE, centro_costo TEXT, monto_imputado REAL DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS inventario (id INTEGER PRIMARY KEY AUTOINCREMENT, producto TEXT, familia TEXT, stock REAL DEFAULT 0, precio_medio REAL DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS movimientos (id INTEGER PRIMARY KEY AUTOINCREMENT, producto_id INTEGER, tipo TEXT, cantidad REAL, centro_costo TEXT, fecha DATE, valor_imputado REAL DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, password TEXT)")
    conn.commit(); conn.close()

def f_puntos(v):
    try: return f"{int(round(float(v))):,}".replace(",", ".")
    except: return "0"

# --- 4. MÓDULOS ---

def modulo_dashboard():
    st.title("🏠 Dashboard")
    conn = conectar_db()
    df_p = pd.read_sql_query("SELECT monto_total, fecha_vencimiento FROM facturas WHERE estado='Pendiente' AND tipo='Factura'", conn)
    deuda_t = df_p['monto_total'].sum() if not df_p.empty else 0
    c1, c2 = st.columns(2)
    c1.metric("DEUDA TOTAL FACTURAS", f"${f_puntos(deuda_t)}")
    conn.close()

def modulo_compras():
    st.header("📦 Compras y Gastos")
    t1, t2, t3 = st.tabs(["➕ Insumos (Factura)", "💸 Gasto Vario (Directo CC)", "🔍 Historial"])
    conn = conectar_db()
    
    with t1:
        st.subheader("Ingreso de Factura para Inventario")
        c1, c2 = st.columns(2)
        nro, prov = c1.text_input("N° Factura"), c1.text_input("Proveedor")
        f_c, f_v = c2.date_input("Emisión"), c2.date_input("Vencimiento")
        df_inv = pd.read_sql_query("SELECT id, producto FROM inventario", conn)
        ps = st.selectbox("Insumo", df_inv['id'].astype(str) + " - " + df_inv['producto']) if not df_inv.empty else None
        cant, neto = st.number_input("Cantidad", 0.0), st.number_input("Precio Neto Unitario", 0.0)
        if st.button("💾 Guardar Factura Insumo"):
            total_factura = (cant * neto) * 1.19
            conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total) VALUES (?,?,?,?,?)", (nro, prov, f_c, f_v, total_factura))
            if ps:
                pid = int(ps.split(" - ")[0]); cur = conn.execute("SELECT stock, precio_medio FROM inventario WHERE id=?", (pid,)).fetchone()
                nuevo_pmp = ((cur[0]*cur[1]) + (cant*neto)) / (cur[0]+cant) if (cur[0]+cant) > 0 else neto
                conn.execute("UPDATE inventario SET stock=stock+?, precio_medio=? WHERE id=?", (cant, nuevo_pmp, pid))
            conn.commit(); guardar_en_drive(); st.rerun()

    with t2:
        st.subheader("Imputación Directa a Centro de Costo")
        g_prov = st.text_input("Proveedor/Glosa", key="g_p")
        g_monto_neto = st.number_input("Monto Neto ($)", 0.0, key="g_m")
        
        # Lógica solicitada: ¿El IVA es costo o no?
        opcion_iva = st.radio(
            "Tratamiento del IVA para el Centro de Costo:",
            ["Neto (IVA recuperable - No va al costo)", "Total (IVA es COSTO para el CC)"],
            help="Seleccione si el IVA debe sumarse al valor del centro de costo o si solo se imputa el valor neto."
        )
        
        st.write("Seleccione Cuarteles para repartir el gasto:")
        cols = st.columns(3)
        ccs_g = [cc for i, cc in enumerate(CENTROS_COSTO) if cols[i%3].checkbox(cc, key=f"cg_{cc}")]
        
        if st.button("💾 Registrar Gasto en CC") and ccs_g:
            # Si el IVA es costo, imputamos Neto * 1.19. Si no, solo Neto.
            monto_a_imputar = g_monto_neto * 1.19 if "Total" in opcion_iva else g_monto_neto
            monto_por_cc = monto_a_imputar / len(ccs_g)
            
            for c in ccs_g:
                conn.execute("""INSERT INTO facturas 
                    (proveedor, monto_total, tipo, centro_costo, monto_imputado, estado, fecha_compra) 
                    VALUES (?,?,?,?,?,?,?)""", 
                    (g_prov, g_monto_neto * 1.19, 'Gasto Vario', c, monto_por_cc, 'Imputado', hoy))
            
            conn.commit(); guardar_en_drive()
            st.success(f"Registrado: ${f_puntos(monto_por_cc)} cargados a cada CC (Basado en {opcion_iva})")
            st.rerun()

    with t3:
        df_h = pd.read_sql_query(f"SELECT * FROM facturas ORDER BY id DESC LIMIT 50", conn)
        st.dataframe(df_h, use_container_width=True)
    conn.close()

def modulo_costos():
    st.header("📊 Reporte de Costos por Cuartel")
    conn = conectar_db()
    # Suma salidas de bodega + gastos varios imputados
    q = """ 
        SELECT centro_costo as Cuartel, SUM(valor_imputado) as Total FROM movimientos GROUP BY Cuartel
        UNION ALL
        SELECT centro_costo as Cuartel, SUM(monto_imputado) as Total FROM facturas WHERE tipo='Gasto Vario' GROUP BY Cuartel
    """
    df_c = pd.read_sql_query(q, conn)
    if not df_c.empty:
        res = df_c.groupby('Cuartel')['Total'].sum().reset_index()
        st.table(res.style.format({"Total": "${:,.0f}"}))
    else:
        st.info("No hay costos registrados aún.")
    conn.close()

# --- 5. EJECUCIÓN PRINCIPAL ---
st.set_page_config(page_title="ERP AGRICOLA v27.0", layout="wide")
inicializar_db()

if 'auth' not in st.session_state: st.session_state['auth'] = False

if not st.session_state['auth']:
    st.title("🚜 Acceso ERP")
    clave = st.text_input("Clave Maestra", type="password")
    if st.button("Entrar") and clave == CLAVE_MAESTRA:
        st.session_state['auth'] = True; st.rerun()
else:
    with st.sidebar:
        menu = st.radio("Navegación", ["🏠 Dashboard", "📦 Compras", "🚜 Bodega", "📊 COSTOS"])
        if st.button("🚪 Salir"): st.session_state['auth'] = False; st.rerun()
    
    if menu == "🏠 Dashboard": modulo_dashboard()
    elif menu == "📦 Compras": modulo_compras()
    elif menu == "📊 COSTOS": modulo_costos()
    # (Los demás módulos se mantienen igual que en las versiones previas)
