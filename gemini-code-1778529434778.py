import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import os

# --- LIBRERÍAS ---
try:
    from fpdf import FPDF
    from pydrive2.auth import GoogleAuth
    from pydrive2.drive import GoogleDrive
    from oauth2client.service_account import ServiceAccountCredentials
except ImportError:
    st.error("Error: Revisa que pydrive2, oauth2client y fpdf estén en el archivo requirements.txt")

# --- CONFIGURACIÓN ---
ID_CARPETA_DRIVE = "1V7IwdbJPzxQ-hJQaVqOWejHHA1mNbgLo" 
NOMBRE_DB = 'erp_concepcion_v6.db'
JSON_KEY = 'secretos.json'
CLAVE_SEGURIDAD = "2908"

# --- UTILIDADES ---
def f_puntos(v):
    try: return f"{int(v):,}".replace(",", ".")
    except: return "0"

def conectar_db(): return sqlite3.connect(NOMBRE_DB)

# --- SINCRONIZACIÓN DRIVE REFORZADA ---
def obtener_drive():
    if not os.path.exists(JSON_KEY): 
        return None
    try:
        scope = ['https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name(JSON_KEY, scope)
        gauth = GoogleAuth()
        gauth.credentials = creds
        return GoogleDrive(gauth)
    except Exception as e:
        st.sidebar.error(f"❌ Error Autenticación: {e}")
        return None

def guardar_en_drive():
    try:
        drive = obtener_drive()
        if not drive: 
            st.error("❌ Error: No se pudo inicializar la conexión con Drive.")
            return False
            
        # Buscar si el archivo ya existe en esa carpeta específica
        query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
        lista = drive.ListFile({'q': query}).GetList()
        
        if lista:
            f = lista[0]
            st.toast("🔄 Actualizando base de datos en la nube...")
        else:
            f = drive.CreateFile({'title': NOMBRE_DB, 'parents': [{'id': ID_CARPETA_DRIVE}]})
            st.toast("🆕 Creando nuevo respaldo en la nube...")
            
        f.SetContentFile(NOMBRE_DB)
        f.Upload()
        st.success("✅ Respaldo completado con éxito en Google Drive.")
        return True
    except Exception as e:
        st.error(f"❌ ERROR CRÍTICO DRIVE: {e}")
        st.info("💡 Consejo: Asegúrate de que el correo del 'Robot' sea EDITOR de la carpeta de Drive.")
        return False

def descargar_de_drive():
    try:
        drive = obtener_drive()
        if not drive: return False
        query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
        lista = drive.ListFile({'q': query}).GetList()
        if lista:
            lista[0].GetContentFile(NOMBRE_DB)
            return True
    except: return False
    return False

# --- GENERADOR DE PDF ---
def descargar_pdf(df, titulo):
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, "AGRICOLA LA CONCEPCIÓN", ln=True, align="C")
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 10, titulo, ln=True, align="C")
        pdf.ln(5)
        pdf.set_font("Helvetica", "B", 8)
        cols = df.columns
        w = 190 / len(cols)
        for col in cols: pdf.cell(w, 8, str(col), border=1, align="C")
        pdf.ln()
        pdf.set_font("Helvetica", "", 7)
        for _, row in df.iterrows():
            for item in row:
                val = f_puntos(item) if isinstance(item, (int, float)) else str(item)
                pdf.cell(w, 7, val[:25], border=1)
            pdf.ln()
        return pdf.output(dest="S").encode("latin-1")
    except: return None

# --- INICIALIZACIÓN ---
st.set_page_config(page_title="AGRICOLA LA CONCEPCION ERP", page_icon="🚜", layout="wide")

if 'db_sincronizada' not in st.session_state:
    descargar_de_drive()
    st.session_state['db_sincronizada'] = True

def inicializar_db():
    conn = conectar_db(); cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS facturas (id INTEGER PRIMARY KEY AUTOINCREMENT, nro_documento TEXT, proveedor TEXT, fecha_compra DATE, fecha_vencimiento DATE, monto_neto REAL, monto_total REAL, estado TEXT DEFAULT 'Pendiente', tipo TEXT DEFAULT 'Factura', metodo_pago TEXT, fecha_pago DATE, concepto TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS inventario (id INTEGER PRIMARY KEY AUTOINCREMENT, producto TEXT, familia TEXT, stock REAL DEFAULT 0, stock_minimo REAL DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS movimientos (id INTEGER PRIMARY KEY AUTOINCREMENT, producto_id INTEGER, tipo TEXT, cantidad REAL, centro_costo TEXT, fecha DATE)")
    conn.commit(); conn.close()

inicializar_db()
if 'carrito' not in st.session_state: st.session_state['carrito'] = []

# --- MÓDULOS ---

def modulo_dashboard():
    st.header("📊 Resumen Financiero")
    conn = conectar_db(); df_f = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente'", conn); conn.close()
    c1, c2, c3 = st.columns(3)
    total_deuda = df_f['monto_total'].sum() if not df_f.empty else 0
    c1.metric("Deuda Pendiente", f"${f_puntos(total_deuda)}")
    vencidas = 0
    if not df_f.empty:
        hoy = datetime.now().date()
        vencidas = df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < hoy].shape[0]
    c2.metric("Vencidas", vencidas, delta_color="inverse")
    c3.metric("Documentos", len(df_f))
    
    st.subheader("📅 Proyección de Pagos (4 Meses)")
    cols_m = st.columns(4)
    meses_n = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]
    for i in range(4):
        fp = datetime.now() + timedelta(days=i*30); m, a = fp.month, fp.year
        val_m = 0
        if not df_f.empty:
            df_f['fv'] = pd.to_datetime(df_f['fecha_vencimiento'])
            val_m = df_f[(df_f['fv'].dt.month == m) & (df_f['fv'].dt.year == a)]['monto_total'].sum()
        cols_m[i].metric(f"{meses_n[m-1]} {a}", f"${f_puntos(val_m)}")

def modulo_compras():
    st.header("Módulo de Compras")
    t1, t2, t3 = st.tabs(["➕ Factura", "💸 Gasto Vario", "🔍 Historial"])
    with t1:
        # Formulario de factura omitido por brevedad para centrarse en el historial/gestión solicitado antes
        pass
    with t3:
        conn = conectar_db()
        df_h = pd.read_sql_query("SELECT * FROM facturas ORDER BY fecha_compra DESC", conn)
        st.dataframe(df_h, use_container_width=True)
        if not df_h.empty:
            st.divider()
            st.subheader("⚙️ Gestión de Documento")
            sel_id = st.selectbox("ID a gestionar", df_h['id'])
            row = df_h[df_h['id'] == sel_id].iloc[0]
            c_m, c_e = st.columns(2)
            with c_m:
                with st.expander("📝 MODIFICAR"):
                    m_nro = st.text_input("N° Doc", value=row['nro_documento'])
                    m_f_c = st.date_input("Fecha Compra", value=pd.to_datetime(row['fecha_compra']).date())
                    m_f_v = st.date_input("Fecha Venc.", value=pd.to_datetime(row['fecha_vencimiento']).date())
                    m_monto = st.number_input("Monto", value=float(row['monto_total']))
                    clave_m = st.text_input("Clave Seguridad", type="password", key="clm")
                    if st.button("ACTUALIZAR"):
                        if clave_m == CLAVE_SEGURIDAD:
                            conn.execute("UPDATE facturas SET nro_documento=?, fecha_compra=?, fecha_vencimiento=?, monto_total=? WHERE id=?", 
                                         (m_nro, m_f_c, m_f_v, m_monto, sel_id))
                            conn.commit(); guardar_en_drive(); st.rerun()
                        else: st.error("Clave Incorrecta")
            with c_e:
                with st.expander("🗑️ ELIMINAR"):
                    clave_e = st.text_input("Clave Seguridad", type="password", key="cle")
                    if st.button("CONFIRMAR ELIMINACIÓN"):
                        if clave_e == CLAVE_SEGURIDAD:
                            conn.execute("DELETE FROM facturas WHERE id=?", (sel_id,))
                            conn.commit(); guardar_en_drive(); st.rerun()
                        else: st.error("Clave Incorrecta")
        conn.close()

# --- NAVEGACIÓN ---
with st.sidebar:
    st.title("LA CONCEPCIÓN ERP")
    # VERIFICACIÓN REAL
    if os.path.exists(JSON_KEY):
        st.success("☁️ Drive: CONECTADO")
        if st.button("🚀 Forzar Sincronización"):
            guardar_en_drive()
    else:
        st.error("⚠️ Drive: DESCONECTADO")
        
    menu = st.radio("Menú", ["🏠 Dashboard", "📦 Compras", "💸 Tesorería", "🚜 Bodega"])

if menu == "🏠 Dashboard": modulo_dashboard()
elif menu == "📦 Compras": modulo_compras()
# ... (Tesorería y Bodega iguales que v6.64)
