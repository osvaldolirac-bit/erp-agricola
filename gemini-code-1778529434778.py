import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
import hashlib
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. CONFIGURACIÓN ---
ID_CARPETA_DRIVE = "12tjxWa_RVRP5YuYd2sypjBO8bPuyMqo6" 
NOMBRE_DB = 'erp_concepcion_v6.db'
CLAVE_MAESTRA = "2908" 
hoy = datetime.now().date()

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
    except: pass

# --- 3. BASE DE DATOS ---
def conectar_db():
    return sqlite3.connect(NOMBRE_DB, check_same_thread=False)

def inicializar_db():
    conn = conectar_db(); cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS facturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        nro_documento TEXT, 
        proveedor TEXT, 
        fecha_compra DATE, 
        fecha_vencimiento DATE, 
        monto_total REAL, 
        estado TEXT DEFAULT 'Pendiente', 
        tipo TEXT DEFAULT 'Factura', 
        metodo_pago TEXT, 
        fecha_pago DATE, 
        centro_costo TEXT, 
        monto_imputado REAL DEFAULT 0)""")
    cursor.execute("CREATE TABLE IF NOT EXISTS inventario (id INTEGER PRIMARY KEY AUTOINCREMENT, producto TEXT, familia TEXT, stock REAL DEFAULT 0, precio_medio REAL DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS movimientos (id INTEGER PRIMARY KEY AUTOINCREMENT, producto_id INTEGER, tipo TEXT, cantidad REAL, centro_costo TEXT, fecha DATE, valor_imputado REAL DEFAULT 0)")
    conn.commit(); conn.close()

def f_puntos(v):
    try: return f"{int(round(float(v))):,}".replace(",", ".")
    except: return "0"

# --- 4. MÓDULOS ---

def modulo_dashboard():
    st.title("🏠 Panel de Control")
    conn = conectar_db()
    # Deuda: Facturas pendientes + Gastos varios no pagados
    df_deuda = pd.read_sql_query("SELECT monto_total FROM facturas WHERE estado='Pendiente'", conn)
    total_deuda = df_deuda['monto_total'].sum() if not df_deuda.empty else 0
    
    # Próximos Vencimientos
    df_venc = pd.read_sql_query("SELECT proveedor, monto_total, fecha_vencimiento FROM facturas WHERE estado='Pendiente' AND tipo='Factura' ORDER BY fecha_vencimiento ASC LIMIT 5", conn)
    
    c1, c2 = st.columns(2)
    c1.metric("DEUDA TOTAL POR PAGAR", f"${f_puntos(total_deuda)}")
    
    st.subheader("🗓️ Próximos Vencimientos (Facturas)")
    if not df_venc.empty:
        st.table(df_venc)
    else:
        st.info("No hay facturas pendientes de pago.")
    conn.close()

def modulo_compras():
    st.header("📦 Compras y Gastos")
    t1, t2 = st.tabs(["➕ Insumos (Factura)", "💸 Gasto Vario (Directo CC)"])
    conn = conectar_db()
    
    with t1:
        st.subheader("Ingreso de Factura para Inventario")
        c1, c2 = st.columns(2)
        nro = c1.text_input("N° Factura")
        prov = c1.text_input("Proveedor")
        f_c = c2.date_input("Fecha Emisión", key="f_em")
        f_v = c2.date_input("Fecha Vencimiento", key="f_ve")
        
        df_inv = pd.read_sql_query("SELECT id, producto FROM inventario", conn)
        ps = st.selectbox("Insumo", df_inv['id'].astype(str) + " - " + df_inv['producto']) if not df_inv.empty else None
        cant = st.number_input("Cantidad", 0.0)
        neto = st.number_input("Precio Neto Unitario", 0.0)
        
        if st.button("💾 Guardar Factura"):
            total_f = (cant * neto) * 1.19
            conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo) VALUES (?,?,?,?,?,?)", 
                         (nro, prov, f_c, f_v, total_f, 'Factura'))
            if ps:
                pid = int(ps.split(" - ")[0])
                conn.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (cant, pid))
            conn.commit(); guardar_en_drive(); st.success("Factura ingresada"); st.rerun()

    with t2:
        st.subheader("Imputación Directa a Centro de Costo")
        g_prov = st.text_input("Proveedor/Glosa", key="g_p")
        g_monto_neto = st.number_input("Monto Neto ($)", 0.0, key="g_m")
        
        iva_a_costo = st.radio("¿El IVA se carga al Centro de Costo?", ["Sí (IVA es costo)", "No (Solo Neto al costo)"])
        
        st.write("Repartir en:")
        cols = st.columns(3)
        ccs_g = [cc for i, cc in enumerate(CENTROS_COSTO) if cols[i%3].checkbox(cc, key=f"cg_{cc}")]
        
        if st.button("💾 Registrar Gasto Vario") and ccs_g:
            monto_total_con_iva = g_monto_neto * 1.19
            # Lógica de imputación solicitada
            imputar = monto_total_con_iva if "Sí" in iva_a_costo else g_monto_neto
            monto_por_cc = imputar / len(ccs_g)
            
            for c in ccs_g:
                conn.execute("""INSERT INTO facturas 
                    (proveedor, monto_total, tipo, centro_costo, monto_imputado, estado, fecha_compra) 
                    VALUES (?,?,?,?,?,?,?)""", 
                    (g_prov, monto_total_con_iva, 'Gasto Vario', c, monto_por_cc, 'Pendiente', hoy))
            conn.commit(); guardar_en_drive(); st.success("Gasto imputado y pendiente de pago"); st.rerun()
    conn.close()

def modulo_tesoreria():
    st.header("💰 Tesorería (Cuentas por Pagar)")
    conn = conectar_db()
    df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, monto_total, fecha_vencimiento, tipo FROM facturas WHERE estado='Pendiente'", conn)
    
    if not df_p.empty:
        st.subheader("Pagos Pendientes")
        # Mostrar nro documento para facturas y 'Gasto' para los otros
        df_p['Documento'] = df_p['nro_documento'].fillna(df_p['tipo'])
        sel = st.selectbox("Seleccione Documento a Pagar", df_p['id'].astype(str) + " - " + df_p['proveedor'] + " ($" + df_p['monto_total'].apply(f_puntos) + ")")
        
        c1, c2 = st.columns(2)
        metodo = c1.selectbox("Método de Pago", METODOS_PAGO)
        fecha_p = c2.date_input("Fecha de Pago", hoy)
        
        if st.button("💸 Confirmar Pago"):
            id_pago = int(sel.split(" - ")[0])
            conn.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (metodo, fecha_p, id_pago))
            conn.commit(); guardar_en_drive(); st.success("Pago registrado"); st.rerun()
        
        st.dataframe(df_p[['Documento', 'proveedor', 'monto_total', 'fecha_vencimiento']])
    else:
        st.info("No hay pagos pendientes.")
    conn.close()

def modulo_costos():
    st.header("📊 Reporte de Costos")
    conn = conectar_db()
    # Suma de salidas de bodega + Gastos varios imputados
    q = """ 
        SELECT centro_costo, SUM(valor_imputado) as total FROM movimientos GROUP BY centro_costo
        UNION ALL
        SELECT centro_costo, SUM(monto_imputado) as total FROM facturas WHERE tipo='Gasto Vario' GROUP BY centro_costo
    """
    df = pd.read_sql_query(q, conn)
    if not df.empty:
        res = df.groupby('centro_costo')['total'].sum().reset_index()
        res.columns = ['Centro de Costo', 'Total Acumulado']
        st.table(res.style.format({"Total Acumulado": "${:,.0f}"}))
    conn.close()

# --- 5. APP PRINCIPAL ---
st.set_page_config(page_title="AGRICOLA v28", layout="wide")
inicializar_db()

if 'auth' not in st.session_state: st.session_state['auth'] = False

if not st.session_state['auth']:
    st.title("🚜 Acceso ERP")
    clave = st.text_input("Clave Maestra", type="password")
    if st.button("Entrar") and clave == CLAVE_MAESTRA:
        st.session_state['auth'] = True; st.rerun()
else:
    with st.sidebar:
        st.image("https://cdn-icons-png.flaticon.com/512/2371/2371833.png", width=100)
        menu = st.radio("Menú Principal", ["🏠 Dashboard", "📦 Compras/Gastos", "💰 Tesorería", "📊 Costos"])
        if st.button("🚪 Salir"): st.session_state['auth'] = False; st.rerun()
    
    if menu == "🏠 Dashboard": modulo_dashboard()
    elif menu == "📦 Compras/Gastos": modulo_compras()
    elif menu == "💰 Tesorería": modulo_tesoreria()
    elif menu == "📊 Costos": modulo_costos()
