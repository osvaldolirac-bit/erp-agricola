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
    st.error("Error: Revisa que pydrive2, oauth2client y fpdf estén en requirements.txt")

# --- CONFIGURACIÓN DRIVE ---
ID_CARPETA_DRIVE = "1V7IwdbJPzxQ-hJQaVqOWejHHA1mNbgLo" 
NOMBRE_DB = 'erp_concepcion_v6.db'
JSON_KEY = 'secretos.json'
CLAVE_SEGURIDAD = "2908"

# --- LISTAS MAESTRAS ACTUALIZADAS ---
FAMILIAS_INSUMOS = ["FERTILIZANTE", "FERTILIZANTE FOLIAR", "HERBICIDA", "INSECTICIDA", "FUNGICIDA", "BIO ESTIMULANTE", "OTROS"]
CENTROS_COSTO = ["CEREZOS CORTE1", "CEREZOS CORTE2", "CIRUELOS", "NOGALES APARICION", "NOGALES CRUZ DEL SUR", "OTROS"]

# --- DATOS EXTRAÍDOS DEL PDF (PARA CARGA INICIAL) ---
PRODUCTOS_PDF = [
    ("ACABAN", "INSECTICIDA", 0.0, 5.0),
    ("ACETAMIPRID 20%", "INSECTICIDA", 0.5, 1.0),
    ("ACETAMIPRID 70%", "INSECTICIDA", 0.9, 5.0),
    ("ADMIRAL", "INSECTICIDA", 2.0, 1.0),
    ("AGROMIL", "FERTILIZANTE FOLIAR", 15.0, 10.0),
    ("KEYLATE ZINC", "FERTILIZANTE FOLIAR", 3.0, 10.0),
    ("MAP", "FERTILIZANTE", 141.0, 100.0),
    ("NITRATO DE CALCIO", "FERTILIZANTE", 325.0, 100.0),
    ("NITRATO DE POTASIO", "FERTILIZANTE", -190.0, 100.0),
    ("NUTRICHELATES ZINC", "FERTILIZANTE FOLIAR", 5.0, 10.0)
]

# --- UTILIDADES ---
def f_puntos(v):
    try: return f"{int(v):,}".replace(",", ".")
    except: return "0"

def conectar_db(): return sqlite3.connect(NOMBRE_DB)

# --- SINCRONIZACIÓN DRIVE ---
def obtener_drive():
    scope = ['https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(JSON_KEY, scope)
    gauth = GoogleAuth()
    gauth.credentials = creds
    return GoogleDrive(gauth)

def descargar_de_drive():
    if not os.path.exists(JSON_KEY): return False
    try:
        drive = obtener_drive()
        query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
        lista = drive.ListFile({'q': query}).GetList()
        if lista:
            lista[0].GetContentFile(NOMBRE_DB)
            return True
    except: return False
    return False

def guardar_en_drive():
    if not os.path.exists(JSON_KEY): return False
    try:
        drive = obtener_drive()
        query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
        lista = drive.ListFile({'q': query}).GetList()
        f = lista[0] if lista else drive.CreateFile({'title': NOMBRE_DB, 'parents': [{'id': ID_CARPETA_DRIVE}]})
        f.SetContentFile(NOMBRE_DB)
        f.Upload()
        return True
    except: return False

# --- INICIALIZACIÓN Y MIGRACIÓN ---
st.set_page_config(page_title="AGRICOLA LA CONCEPCION ERP", page_icon="🚜", layout="wide")

if 'db_sincronizada' not in st.session_state:
    descargar_de_drive()
    st.session_state['db_sincronizada'] = True

def inicializar_db():
    conn = conectar_db(); cursor = conn.cursor()
    # Tablas con columna stock_minimo añadida
    cursor.execute("CREATE TABLE IF NOT EXISTS facturas (id INTEGER PRIMARY KEY AUTOINCREMENT, nro_documento TEXT, proveedor TEXT, fecha_compra DATE, fecha_vencimiento DATE, monto_neto REAL, monto_total REAL, estado TEXT DEFAULT 'Pendiente', tipo TEXT DEFAULT 'Factura', metodo_pago TEXT, fecha_pago DATE, concepto TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS inventario (id INTEGER PRIMARY KEY AUTOINCREMENT, producto TEXT, familia TEXT, stock REAL DEFAULT 0, stock_minimo REAL DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS movimientos (id INTEGER PRIMARY KEY AUTOINCREMENT, producto_id INTEGER, tipo TEXT, cantidad REAL, centro_costo TEXT, fecha DATE)")
    
    # CARGA DE PRODUCTOS DEL PDF (Solo si la tabla está vacía)
    cursor.execute("SELECT count(*) FROM inventario")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("INSERT INTO inventario (producto, familia, stock, stock_minimo) VALUES (?,?,?,?)", PRODUCTOS_PDF)
        st.toast("🌱 Inventario inicial cargado desde el PDF")
    
    conn.commit(); conn.close()

inicializar_db()

# --- MÓDULO BODEGA (CON ALERTAS) ---
def modulo_bodega():
    st.header("Inventario de Bodega")
    tb1, tb2, tb3, tb4 = st.tabs(["📊 Stock", "🔍 Consultas CC", "🔄 Movimiento", "➕ Nuevo Insumo"])
    
    with tb1:
        conn = conectar_db(); df_s = pd.read_sql_query("SELECT id, producto, familia, stock, stock_minimo FROM inventario", conn); conn.close()
        
        # Alerta visual para stock bajo
        def alerta_stock(row):
            return ['background-color: #ffcccc' if row['stock'] < row['stock_minimo'] else '' for _ in row]
        
        st.dataframe(df_s.style.apply(alerta_stock, axis=1), use_container_width=True)
        st.caption("Filas en rojo indican stock por debajo del mínimo requerido.")

    with tb3:
        with st.form("mov_b"):
            conn = conectar_db(); prs = pd.read_sql_query("SELECT id, producto FROM inventario", conn); conn.close()
            p_m = st.selectbox("Elegir Insumo", prs['id'].astype(str) + " - " + prs['producto'])
            tm, cm = st.radio("Acción", ["Salida (Uso en Campo)", "Entrada"]), st.number_input("Cantidad", min_value=0.1)
            cc_m = st.selectbox("Centro de Costo (Cuartel)", CENTROS_COSTO)
            if st.form_submit_button("REGISTRAR"):
                ip = int(p_m.split(" - ")[0]); conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo) VALUES (?,?,?,?,?)", (ip, tm, cm, datetime.now().date(), cc_m))
                f = 1 if tm == "Entrada" else -1
                cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (cm*f, ip))
                conn.commit(); conn.close(); guardar_en_drive(); st.rerun()

    with tb4:
        with st.form("new_i"):
            st.subheader("Crear Producto Nuevo")
            nn = st.text_input("Nombre Comercial")
            ff = st.selectbox("Familia", FAMILIAS_INSUMOS)
            sm = st.number_input("Stock Mínimo (Alerta)", min_value=0.0)
            if st.form_submit_button("CREAR"):
                conn = conectar_db(); conn.execute("INSERT INTO inventario (producto, familia, stock, stock_minimo) VALUES (?,?,?,?)", (nn, ff, 0, sm)); conn.commit(); conn.close(); guardar_en_drive(); st.rerun()

# --- NAVEGACIÓN PRINCIPAL ---
# (Se asume el resto del código modular de la v6.45)
# ...
