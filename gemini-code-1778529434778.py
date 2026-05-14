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

# --- 2. MOTOR DRIVE (ANTI-QUOTA REFORZADO) ---
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
            st.success("✅ Sincronización exitosa con Drive.")
    except Exception as e: st.error(f"Error Sincronización: {e}")

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
    
    pwh = hashlib.sha256(str.encode('9083')).hexdigest()
    cursor.execute("INSERT OR IGNORE INTO usuarios (email, password) VALUES (?,?)", ('osvaldolira@laconcepcion.cl', pwh))
    conn.commit(); conn.close()

# --- 4. UTILIDADES Y PDF ---
def f_puntos(v):
    try: return f"{int(round(float(v))):,}".replace(",", ".")
    except: return "0"

def generar_pdf_blob(df, titulo):
    pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, f"LA CONCEPCIÓN - {titulo}", ln=True, align="C")
    pdf.set_font("Arial", "B", 8)
    cols = df.columns; w = 190 / len(cols)
    for col in cols: pdf.cell(w, 8, str(col)[:15], border=1)
    pdf.ln(); pdf.set_font("Arial", "", 7)
    for _, row in df.iterrows():
        for item in row: pdf.cell(w, 7, str(item)[:20], border=1)
        pdf.ln()
    return pdf.output(dest="S").encode("latin-1")

# --- 5. MÓDULOS DEL SISTEMA ---

def modulo_dashboard():
    st.title("🚜 Dashboard Agrícola")
    conn = conectar_db()
    df_f = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente' AND tipo='Factura'", conn)
    t_d = df_f['monto_total'].sum() if not df_f.empty else 0
    
    c1, c2, c3 = st.columns(3)
    c1.metric("DEUDA PENDIENTE", f"${f_puntos(t_deuda)}")
    st.divider()
    
    st.subheader("💰 Costos Acumulados por Cuartel")
    q = """ SELECT UPPER(centro_costo) as Cuartel, SUM(valor_imputado) as Total FROM movimientos GROUP BY Cuartel
            UNION ALL
            SELECT UPPER(centro_costo) as Cuartel, SUM(monto_imputado) as Total FROM facturas WHERE tipo='Gasto Vario' GROUP BY Cuartel """
    df_c = pd.read_sql_query(q, conn)
    if not df_c.empty:
        res = df_c.groupby('Cuartel')['Total'].sum().reset_index()
        st.dataframe(res.style.format({"Total": "${:,.0f}"}), use_container_width=True)
    conn.close()

def modulo_compras():
    st.header("📦 Compras y Gastos")
    t1, t2, t3 = st.tabs(["➕ Factura Insumos", "💸 Gasto Directo", "🔍 Historial"])
    conn = conectar_db()
    
    with t1:
        c1, c2 = st.columns(2)
        nro, prov = c1.text_input("N° Factura"), c1.text_input("Proveedor")
        f_c, f_v = c2.date_input("Fecha Factura"), c2.date_input("Fecha Vencimiento")
        
        df_inv = pd.read_sql_query("SELECT id, producto, stock, precio_medio FROM inventario", conn)
        ps = st.selectbox("Insumo", df_inv['id'].astype(str) + " - " + df_inv['producto']) if not df_inv.empty else None
        cant, neto = st.number_input("Cantidad", 0.0), st.number_input("Neto Unitario", 0.0)
        
        if st.button("💾 Guardar Factura e Inventario"):
            total = (cant * neto) * 1.19
            conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total) VALUES (?,?,?,?,?)", (nro, prov, f_c, f_v, total))
            if ps:
                pid = int(ps.split(" - ")[0])
                cur = conn.execute("SELECT stock, precio_medio FROM inventario WHERE id=?", (pid,)).fetchone()
                nuevo_pmp = ((cur[0]*cur[1]) + (cant*neto)) / (cur[0]+cant) if (cur[0]+cant) > 0 else neto
                conn.execute("UPDATE inventario SET stock = stock + ?, precio_medio = ? WHERE id = ?", (cant, nuevo_pmp, pid))
            conn.commit(); guardar_en_drive(); st.rerun()

    with t2:
        st.subheader("Gasto Directo (Prorrateo)")
        g_prov, g_neto = st.text_input("Proveedor ", key="g1"), st.number_input("Monto Neto Total", 0.0)
        ccs = st.multiselect("Cuarteles a Imputar", CENTROS_COSTO)
        if st.button("💾 Registrar y Imputar Gasto") and ccs:
            p_neto = g_neto / len(ccs)
            for c in ccs:
                conn.execute("INSERT INTO facturas (proveedor, monto_total, tipo, centro_costo, monto_imputado, estado) VALUES (?,?,?,?,?,?)", (g_prov, 0, 'Gasto Vario', c, p_neto, 'PAGADO'))
            conn.commit(); guardar_en_drive(); st.rerun()

    with t3:
        df_h = pd.read_sql_query("SELECT * FROM facturas ORDER BY id DESC", conn)
        st.dataframe(df_h, use_container_width=True)
        if not df_h.empty:
            st.download_button("📥 PDF Historial", generar_pdf_blob(df_h, "HISTORIAL"), "historial.pdf")
    conn.close()

def modulo_tesoreria():
    st.header("💸 Cuentas por Pagar")
    conn = conectar_db()
    df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' AND monto_total > 0", conn)
    if not df_p.empty:
        st.dataframe(df_p.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
        id_p = st.selectbox("ID Pago", df_p['id']); met = st.selectbox("Medio", ["Transferencia", "Cheque", "Efectivo"])
        if st.button("💰 PAGAR DOCUMENTO"):
            conn.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (met, hoy, id_p))
            conn.commit(); guardar_en_drive(); st.rerun()
    else: st.success("No hay facturas pendientes.")
    conn.close()

def modulo_bodega():
    st.header("🚜 Gestión de Bodega e Insumos")
    t1, t2, t3 = st.tabs(["📊 Existencias", "🔄 Salida a Campo", "➕ Nuevo Insumo"])
    conn = conectar_db()
    
    with t1:
        df_s = pd.read_sql_query("SELECT * FROM inventario", conn)
        st.dataframe(df_s, use_container_width=True)
        if not df_s.empty: st.download_button("📥 PDF Stock", generar_pdf_blob(df_s, "EXISTENCIAS"), "stock.pdf")

    with t2:
        df_i = pd.read_sql_query("SELECT id, producto, stock, precio_medio FROM inventario WHERE stock > 0", conn)
        if not df_i.empty:
            ps = st.selectbox("Insumo a sacar", df_i['id'].astype(str) + " - " + df_i['producto'])
            cant_s = st.number_input("Cantidad Salida", 0.0)
            ccs_s = st.multiselect("Cuarteles Destino", CENTROS_COSTO)
            if st.button("✅ Registrar Salida y Prorratear Costo") and ccs_s:
                pid = int(ps.split(" - ")[0])
                pmp = df_i[df_i['id']==pid]['precio_medio'].values[0]
                val_total = cant_s * pmp
                for c in ccs_s:
                    conn.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, centro_costo, valor_imputado, fecha) VALUES (?,?,?,?,?,?)", (pid, 'Salida', cant_s/len(ccs_s), c, val_total/len(ccs_s), hoy))
                conn.execute("UPDATE inventario SET stock = stock - ? WHERE id = ?", (cant_s, pid))
                conn.commit(); guardar_en_drive(); st.rerun()
    
    with t3:
        with st.form("ni"):
            n, f = st.text_input("Nombre Insumo"), st.selectbox("Familia", FAMILIAS_PRODUCTOS)
            if st.form_submit_button("Crear Insumo"):
                conn.execute("INSERT INTO inventario (producto, familia) VALUES (?,?)", (n, f))
                conn.commit(); st.rerun()
    conn.close()

# --- 6. NAVEGACIÓN ---
st.set_page_config(page_title="ERP Agrícola v16.0", layout="wide")
inicializar_db()

if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False

if not st.session_state['logged_in']:
    st.title("🚜 Acceso Sistema")
    u = st.text_input("Usuario")
    p = st.text_input("Clave", type="password")
    if st.button("Ingresar"):
        if p == CLAVE_MAESTRA or p == "9083":
            st.session_state['logged_in'] = True; st.rerun()
else:
    if 'init' not in st.session_state: descargar_de_drive(); st.session_state['init'] = True
    with st.sidebar:
        st.title("MENÚ")
        if obtener_drive(): st.success("🟢 Drive Conectado")
        m = st.radio("Módulos", ["Dashboard", "Compras", "Tesorería", "Bodega"])
        if st.button("🚀 Sincronizar Ahora"): guardar_en_drive()
        if st.button("Salir"): st.session_state.clear(); st.rerun()
    
    if m == "Dashboard": modulo_dashboard()
    elif m == "Compras": modulo_compras()
    elif m == "Tesorería": modulo_tesoreria()
    elif m == "Bodega": modulo_bodega()
