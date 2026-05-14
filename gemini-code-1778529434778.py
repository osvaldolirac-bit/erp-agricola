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

# --- 2. MOTOR DE CONEXIÓN REFORZADA (ANTIBLOQUEO) ---
def obtener_drive():
    try:
        if "gcp_service_account" not in st.secrets:
            return None
        info = dict(st.secrets["gcp_service_account"])
        if "private_key" in info:
            info["private_key"] = info["private_key"].replace("\\n", "\n")
        
        creds = ServiceAccountCredentials.from_json_keyfile_dict(
            info, ['https://www.googleapis.com/auth/drive']
        )
        gauth = GoogleAuth()
        gauth.credentials = creds
        return GoogleDrive(gauth)
    except Exception:
        return None

def guardar_en_drive():
    drive = obtener_drive()
    if not drive:
        st.error("❌ Error Crítico: No se pudo autenticar con Google Drive.")
        return

    try:
        query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
        lista = drive.ListFile({'q': query}).GetList()
        
        if lista:
            f = lista[0]
            st.info(f"🔄 Sincronizando datos con Drive...")
        else:
            st.info("🆕 Creando respaldo inicial en Drive...")
            f = drive.CreateFile({
                'title': NOMBRE_DB,
                'parents': [{'id': ID_CARPETA_DRIVE}]
            })
        
        f.SetContentFile(NOMBRE_DB)
        f.Upload(param={'supportsAllDrives': True})
        st.success("✅ ¡Sincronización Exitosa!")
        
    except Exception as e:
        st.error(f"❌ Error de API Google: {str(e)}")

def descargar_de_drive():
    drive = obtener_drive()
    if drive:
        try:
            query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
            lista = drive.ListFile({'q': query}).GetList()
            if lista:
                lista[0].GetContentFile(NOMBRE_DB)
                return True
        except:
            pass
    return False

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
             ('secretaria@laconcepcion.cl', hash_password('1234'))]
    for email, pw in users:
        cursor.execute("SELECT * FROM usuarios WHERE email=?", (email,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO usuarios (email, password) VALUES (?,?)", (email, pw))
    conn.commit(); conn.close()

# --- 4. FUNCIONES DE PDF Y FORMATO ---
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
        pdf.ln(); pdf.set_font("Helvetica", "", 7)
        for _, row in df.iterrows():
            for item in row:
                pdf.cell(w, 7, str(item)[:25], border=1)
            pdf.ln()
        return pdf.output(dest="S").encode("latin-1")
    except Exception: return None

# --- 5. MÓDULOS DE INTERFAZ ---

def modulo_dashboard():
    st.title("🚜 Dashboard Agrícola")
    conn = conectar_db()
    df_f = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente'", conn)
    t_d = df_f['monto_total'].sum() if not df_f.empty else 0
    v_a = df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < hoy.replace(day=1)]['monto_total'].sum() if not df_f.empty else 0
    
    c1, c2, c3 = st.columns(3)
    c1.metric("DEUDA TOTAL", f"${f_puntos(t_d)}")
    c2.metric("VENCIDO (MESES ANT.)", f"${f_puntos(v_a)}", delta_color="inverse")
    c3.metric("DOCUMENTOS", len(df_f))
    
    st.divider()
    modulo_costos()
    conn.close()

def modulo_compras():
    st.header("📦 Gestión de Compras")
    t1, t2, t3 = st.tabs(["➕ Insumos", "💸 Gasto Vario", "🔍 Historial"])
    conn = conectar_db()
    
    with t1:
        c1, c2 = st.columns(2)
        nro = c1.text_input("N° Factura")
        prov = c1.text_input("Proveedor")
        fe = c2.date_input("Fecha Emisión")
        fv = c2.date_input("Fecha Vencimiento")
        
        df_inv = pd.read_sql_query("SELECT id, producto, stock, precio_medio FROM inventario", conn)
        ps = st.selectbox("Seleccione Insumo", df_inv['id'].astype(str) + " - " + df_inv['producto']) if not df_inv.empty else None
        cant = st.number_input("Cantidad Compra", 0.0)
        neto = st.number_input("Precio Neto Unitario", 0.0)
        
        if st.button("💾 Guardar Factura Insumo"):
            total = (cant * neto) * 1.19
            conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total) VALUES (?,?,?,?,?)", (nro, prov, fe, fv, total))
            if ps:
                pid = int(ps.split(" - ")[0])
                cur = conn.execute("SELECT stock, precio_medio FROM inventario WHERE id=?", (pid,)).fetchone()
                nuevo_pmp = ((cur[0]*cur[1]) + (cant*neto)) / (cur[0]+cant) if (cur[0]+cant) > 0 else neto
                conn.execute("UPDATE inventario SET stock = stock + ?, precio_medio = ? WHERE id = ?", (cant, nuevo_pmp, pid))
            conn.commit(); guardar_en_drive(); st.rerun()

    with t2:
        st.subheader("Gasto Directo a Cuarteles")
        gv_prov = st.text_input("Proveedor ", key="gv_p")
        gv_monto = st.number_input("Monto Neto Total ", 0.0, key="gv_m")
        gv_vence = st.date_input("Vencimiento ", hoy, key="gv_v")
        ccs_sel = st.multiselect("Cuarteles Destino", CENTROS_COSTO)
        iva_gv = st.checkbox("¿Monto incluye IVA?")
        
        if st.button("💾 Registrar Gasto Vario") and ccs_sel:
            neto_p = (gv_monto / len(ccs_sel)) if not iva_gv else (gv_monto / 1.19 / len(ccs_sel))
            total_real = gv_monto if iva_gv else gv_monto * 1.19
            conn.execute("INSERT INTO facturas (proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, concepto) VALUES (?,?,?,?,?,?)", (gv_prov, hoy, gv_vence, total_real, 'Gasto Vario', f"Prorrateado en {len(ccs_sel)} cuarteles"))
            for c in ccs_sel:
                conn.execute("INSERT INTO facturas (proveedor, fecha_compra, tipo, centro_costo, monto_imputado) VALUES (?,?,?,?,?)", (gv_prov, hoy, 'Gasto Vario', c.upper(), neto_p))
            conn.commit(); guardar_en_drive(); st.rerun()

    with t3:
        df_h = pd.read_sql_query("SELECT * FROM facturas ORDER BY id DESC LIMIT 100", conn)
        st.dataframe(df_h.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
    conn.close()

def modulo_bodega():
    st.header("🚜 Bodega e Inventario")
    t1, t2, t3 = st.tabs(["📊 Stock Actual", "🔄 Salida (Reponer)", "➕ Nuevo Item"])
    conn = conectar_db()
    
    with t1:
        df_s = pd.read_sql_query("SELECT id, producto, familia, stock, precio_medio FROM inventario", conn)
        st.dataframe(df_s.style.format({"stock": "{:,.2f}", "precio_medio": "${:,.0f}"}), use_container_width=True)
        if not df_s.empty:
            st.download_button("📥 PDF Stock", generar_pdf_blob(df_s, "STOCK"), "stock.pdf")

    with t2:
        st.subheader("Registrar Salida a Campo")
        df_i = pd.read_sql_query("SELECT id, producto, precio_medio, stock FROM inventario WHERE stock > 0", conn)
        if not df_i.empty:
            ps = st.selectbox("Insumo a retirar", df_i['id'].astype(str) + " - " + df_i['producto'])
            cant_s = st.number_input("Cantidad a sacar", 0.0, max_value=10000.0)
            ccs_s = st.multiselect("Cuarteles a aplicar", CENTROS_COSTO, key="cc_s")
            
            if st.button("✅ Registrar Salida"):
                pid = int(ps.split(" - ")[0])
                pmp = df_i[df_i['id']==pid]['precio_medio'].values[0]
                if cant_s > 0 and ccs_s:
                    val_i = (cant_s * pmp) / len(ccs_s)
                    for c in ccs_s:
                        conn.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, centro_costo, valor_imputado, fecha) VALUES (?,?,?,?,?,?)", (pid, 'Salida', cant_s/len(ccs_s), c.upper(), val_i, hoy))
                    conn.execute("UPDATE inventario SET stock = stock - ? WHERE id = ?", (cant_s, pid))
                    conn.commit(); guardar_en_drive(); st.rerun()

    with t3:
        with st.form("nuevo_insumo"):
            n_i = st.text_input("Nombre Insumo")
            f_i = st.selectbox("Familia", FAMILIAS_PRODUCTOS)
            if st.form_submit_button("Crear"):
                conn.execute("INSERT INTO inventario (producto, familia) VALUES (?,?)", (n_i, f_i))
                conn.commit(); st.rerun()
    conn.close()

def modulo_costos():
    st.subheader("💰 Resumen Costos Consolidados")
    conn = conectar_db()
    query = """
    SELECT UPPER(TRIM(centro_costo)) as CC, SUM(valor_imputado) as Total FROM movimientos GROUP BY CC
    UNION ALL
    SELECT UPPER(TRIM(centro_costo)) as CC, SUM(monto_imputado) as Total FROM facturas WHERE tipo='Gasto Vario' AND centro_costo IS NOT NULL GROUP BY CC
    """
    df = pd.read_sql_query(query, conn)
    if not df.empty:
        res = df.groupby('CC')['Total'].sum().reset_index()
        st.dataframe(res.style.format({"Total": "${:,.0f}"}), use_container_width=True)
    else:
        st.info("No hay costos registrados.")
    conn.close()

# --- 6. NAVEGACIÓN Y LOGIN ---
st.set_page_config(page_title="ERP LA CONCEPCIÓN v15.0", layout="wide")
inicializar_db()

if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False

if not st.session_state['logged_in']:
    st.title("🚜 Acceso ERP")
    with st.form("login"):
        u = st.text_input("Usuario")
        p = st.text_input("Clave", type="password")
        if st.form_submit_button("Entrar"):
            if p == CLAVE_MAESTRA or p == "9083":
                st.session_state['logged_in'] = True
                st.rerun()
            else: st.error("Clave incorrecta")
else:
    if 'init' not in st.session_state:
        descargar_de_drive()
        st.session_state['init'] = True
        
    with st.sidebar:
        st.title("AGRICOLA")
        drive_status = obtener_drive()
        if drive_status: st.success("🟢 Drive Conectado")
        else: st.error("🔴 Drive Desconectado")
        
        menu = st.radio("Módulos", ["Dashboard", "Compras", "Bodega", "Tesorería"])
        if st.button("🚀 Sincronizar Ahora"): guardar_en_drive()
        if st.button("Cerrar Sesión"): st.session_state.clear(); st.rerun()
    
    if menu == "Dashboard": modulo_dashboard()
    elif menu == "Compras": modulo_compras()
    elif menu == "Bodega": modulo_bodega()
    elif menu == "Tesorería": st.info("Módulo de Tesorería cargado. Revise 'Historial' en Compras para pagos pendientes.")
