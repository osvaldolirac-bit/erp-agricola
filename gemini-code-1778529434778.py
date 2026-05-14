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

# --- 2. MOTOR DE CONEXIÓN DRIVE (ANTI-QUOTA) ---
def obtener_drive():
    try:
        if "gcp_service_account" not in st.secrets: return None
        info = dict(st.secrets["gcp_service_account"])
        if "private_key" in info: info["private_key"] = info["private_key"].replace("\\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(info, ['https://www.googleapis.com/auth/drive'])
        gauth = GoogleAuth(); gauth.credentials = creds
        return GoogleDrive(gauth)
    except Exception as e:
        st.error(f"Error de conexión Drive: {e}")
        return None

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
            st.success("✅ ¡Base de Datos respaldada exitosamente en su Google Drive!")
        else:
            st.error("❌ Archivo no encontrado. Por favor, suba el archivo erp_concepcion_v6.db manualmente una vez.")
    except Exception as e: st.error(f"Error al sincronizar: {e}")

def descargar_de_drive():
    drive = obtener_drive()
    if drive:
        try:
            query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
            lista = drive.ListFile({'q': query}).GetList()
            if lista: lista[0].GetContentFile(NOMBRE_DB)
        except: pass

# --- 3. GESTIÓN DE BASE DE DATOS ---
def conectar_db():
    return sqlite3.connect(NOMBRE_DB, check_same_thread=False)

def inicializar_db():
    conn = conectar_db(); cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS facturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nro_documento TEXT, proveedor TEXT, 
        fecha_compra DATE, fecha_vencimiento DATE, monto_neto REAL DEFAULT 0, monto_total REAL DEFAULT 0, 
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

# --- 4. UTILIDADES Y REPORTES PDF ---
def f_puntos(v):
    try: return f"{int(round(float(v))):,}".replace(",", ".")
    except: return "0"

def generar_pdf_blob(df, titulo):
    try:
        pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial", "B", 14)
        pdf.cell(0, 10, f"AGRICOLA LA CONCEPCIÓN - {titulo}", ln=True, align="C")
        pdf.set_font("Arial", "B", 8); pdf.ln(5)
        cols = df.columns; w = 190 / len(cols)
        for col in cols: pdf.cell(w, 8, str(col).upper(), border=1, align="C")
        pdf.ln(); pdf.set_font("Arial", "", 7)
        for _, row in df.iterrows():
            for item in row: pdf.cell(w, 7, str(item)[:22], border=1)
            pdf.ln()
        return pdf.output(dest="S").encode("latin-1")
    except Exception as e:
        st.error(f"Error generando PDF: {e}")
        return None

# --- 5. MÓDULOS PRINCIPALES ---

def modulo_dashboard():
    st.title("🏠 Dashboard Agrícola")
    conn = conectar_db()
    # Métricas de Deuda
    df_p = pd.read_sql_query("SELECT monto_total FROM facturas WHERE estado='Pendiente' AND tipo='Factura'", conn)
    deuda = df_f = df_p['monto_total'].sum() if not df_p.empty else 0
    
    c1, c2, c3 = st.columns(3)
    c1.metric("DEUDA TOTAL", f"${f_puntos(deuda)}")
    
    st.divider()
    st.subheader("📊 Distribución de Costos por Cuartel")
    q_costos = """ 
        SELECT UPPER(centro_costo) as Cuartel, SUM(valor_imputado) as Total, 'BODEGA' as Origen FROM movimientos GROUP BY Cuartel
        UNION ALL
        SELECT UPPER(centro_costo) as Cuartel, SUM(monto_imputado) as Total, 'GASTO DIRECTO' as Origen FROM facturas WHERE tipo='Gasto Vario' GROUP BY Cuartel 
    """
    df_c = pd.read_sql_query(q_costos, conn)
    if not df_c.empty:
        resumen = df_c.groupby('Cuartel')['Total'].sum().reset_index()
        st.dataframe(resumen.style.format({"Total": "${:,.0f}"}), use_container_width=True)
    else: st.info("No hay datos de costos imputados.")
    conn.close()

def modulo_compras():
    st.header("📦 Compras y Egresos")
    t1, t2, t3 = st.tabs(["➕ Nueva Factura", "💸 Gasto Vario", "🔍 Historial"])
    conn = conectar_db()
    
    with t1:
        col1, col2 = st.columns(2)
        nro = col1.text_input("N° Documento")
        prov = col1.text_input("Proveedor")
        f_comp = col2.date_input("Fecha Compra", hoy)
        f_venc = col2.date_input("Fecha Vencimiento", hoy + timedelta(days=30))
        
        df_inv = pd.read_sql_query("SELECT id, producto, stock, precio_medio FROM inventario", conn)
        ps = st.selectbox("Insumo a Ingresar", df_inv['id'].astype(str) + " - " + df_inv['producto']) if not df_inv.empty else None
        cant = st.number_input("Cantidad Comprada", 0.0)
        neto_u = st.number_input("Precio Neto Unitario", 0.0)
        
        if st.button("💾 Grabar Factura e Inventario"):
            total_fac = (cant * neto_u) * 1.19
            conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo) VALUES (?,?,?,?,?,?)", (nro, prov, f_comp, f_venc, total_fac, 'Factura'))
            if ps:
                pid = int(ps.split(" - ")[0])
                # Cálculo de PMP
                cur = conn.execute("SELECT stock, precio_medio FROM inventario WHERE id=?", (pid,)).fetchone()
                nuevo_pmp = ((cur[0]*cur[1]) + (cant*neto_u)) / (cur[0]+cant) if (cur[0]+cant) > 0 else neto_u
                conn.execute("UPDATE inventario SET stock = stock + ?, precio_medio = ? WHERE id = ?", (cant, nuevo_pmp, pid))
            conn.commit(); guardar_en_drive(); st.rerun()

    with t2:
        st.subheader("Gasto Vario (Sin Stock)")
        g_prov = st.text_input("Proveedor Gasto", key="gp")
        g_monto = st.number_input("Monto Neto Total", 0.0, key="gm")
        g_cuarteles = st.multiselect("Cuarteles a Imputar", CENTROS_COSTO)
        if st.button("💾 Registrar y Prorratear") and g_cuarteles:
            monto_p = g_monto / len(g_cuarteles)
            for c in g_cuarteles:
                conn.execute("INSERT INTO facturas (proveedor, monto_total, tipo, centro_costo, monto_imputado, estado, fecha_compra) VALUES (?,?,?,?,?,?,?)", (g_prov, 0, 'Gasto Vario', c, monto_p, 'Costo Imputado', hoy))
            conn.commit(); guardar_en_drive(); st.rerun()

    with t3:
        df_h = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_compra, monto_total, tipo FROM facturas ORDER BY id DESC", conn)
        st.dataframe(df_h, use_container_width=True)
        if not df_h.empty: st.download_button("📥 Exportar Historial PDF", generar_pdf_blob(df_h, "HISTORIAL COMPRAS"), "historial.pdf")
    conn.close()

def modulo_bodega():
    st.header("🚜 Gestión de Bodega")
    t1, t2, t3 = st.tabs(["📊 Inventario", "🔄 Salida Campo", "➕ Crear Insumo"])
    conn = conectar_db()
    with t1:
        df_s = pd.read_sql_query("SELECT id, producto, familia, stock, precio_medio FROM inventario", conn)
        st.dataframe(df_s.style.format({"stock": "{:,.2f}", "precio_medio": "${:,.0f}"}), use_container_width=True)
        if not df_s.empty: st.download_button("📥 Descargar Stock PDF", generar_pdf_blob(df_s, "STOCK BODEGA"), "stock.pdf")

    with t2:
        df_i = pd.read_sql_query("SELECT id, producto, stock, precio_medio FROM inventario WHERE stock > 0", conn)
        if not df_i.empty:
            ps = st.selectbox("Insumo a retirar", df_i['id'].astype(str) + " - " + df_i['producto'])
            cant_s = st.number_input("Cantidad a sacar", 0.0)
            destinos = st.multiselect("Cuarteles Destino", CENTROS_COSTO)
            if st.button("✅ Confirmar Salida y Prorratear") and destinos:
                pid = int(ps.split(" - ")[0])
                pmp = df_i[df_i['id']==pid]['precio_medio'].values[0]
                val_total = cant_s * pmp
                val_p = val_total / len(destinos)
                for d in destinos:
                    conn.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, centro_costo, valor_imputado, fecha) VALUES (?,?,?,?,?,?)", (pid, 'Salida', cant_s/len(destinos), d, val_p, hoy))
                conn.execute("UPDATE inventario SET stock = stock - ? WHERE id = ?", (cant_s, pid))
                conn.commit(); guardar_en_drive(); st.rerun()

    with t3:
        with st.form("nuevo_item"):
            n = st.text_input("Nombre Insumo")
            f = st.selectbox("Familia", FAMILIAS_PRODUCTOS)
            if st.form_submit_button("💾 Crear Insumo"):
                conn.execute("INSERT INTO inventario (producto, familia) VALUES (?,?)", (n, f))
                conn.commit(); st.rerun()
    conn.close()

def modulo_tesoreria():
    st.header("💸 Cuentas por Pagar")
    conn = conectar_db()
    df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' AND tipo='Factura' ORDER BY fecha_vencimiento ASC", conn)
    if not df_p.empty:
        st.dataframe(df_p.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
        id_fac = st.selectbox("ID a Pagar", df_p['id'])
        metodo = st.selectbox("Método de Pago", ["Transferencia", "Cheque", "Efectivo"])
        if st.button("💰 Marcar como Pagado"):
            conn.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (metodo, hoy, id_fac))
            conn.commit(); guardar_en_drive(); st.rerun()
    else: st.success("✅ No existen facturas pendientes de pago.")
    conn.close()

def modulo_costos():
    st.header("💰 COSTOS DETALLADOS")
    conn = conectar_db()
    # Consulta avanzada que une movimientos de bodega y gastos varios de facturas
    q = """ 
        SELECT centro_costo as Cuartel, fecha as Fecha, 'Bodega' as Tipo, valor_imputado as Valor FROM movimientos 
        UNION ALL
        SELECT centro_costo as Cuartel, fecha_compra as Fecha, 'Gasto Vario' as Tipo, monto_imputado as Valor FROM facturas WHERE tipo='Gasto Vario'
    """
    df = pd.read_sql_query(q, conn)
    if not df.empty:
        c_sel = st.selectbox("Filtrar por Cuartel", ["TODOS"] + CENTROS_COSTO)
        if c_sel != "TODOS": df = df[df['Cuartel'] == c_sel]
        st.dataframe(df.style.format({"Valor": "${:,.0f}"}), use_container_width=True)
        st.metric("COSTO TOTAL", f"${f_puntos(df['Valor'].sum())}")
        st.download_button("📥 Descargar Reporte Costos PDF", generar_pdf_blob(df, f"REPORTE COSTOS {c_sel}"), "costos.pdf")
    conn.close()

# --- 6. NAVEGACIÓN Y LOGIN ---
st.set_page_config(page_title="ERP Agrícola v20.0", layout="wide")
inicializar_db()

if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False

if not st.session_state['logged_in']:
    st.markdown("<h1 style='text-align: center;'>🚜 ERP LA CONCEPCIÓN</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        pw = st.text_input("Clave Maestra", type="password")
        if st.button("ENTRAR AL SISTEMA"):
            if pw == CLAVE_MAESTRA or pw == "9083":
                st.session_state['logged_in'] = True; st.rerun()
            else: st.error("Acceso denegado.")
else:
    if 'init' not in st.session_state: descargar_de_drive(); st.session_state['init'] = True
    with st.sidebar:
        st.title("🚜 MENÚ ERP")
        if obtener_drive(): st.success("🟢 Nube Conectada")
        menu = st.radio("Seleccione Módulo:", ["🏠 Dashboard", "📦 Compras", "💸 Tesorería", "🚜 Bodega", "💰 COSTOS"])
        st.divider()
        if st.button("🚀 Sincronizar Nube"): guardar_en_drive()
        if st.button("🚪 Cerrar Sesión"): st.session_state.clear(); st.rerun()
    
    if menu == "🏠 Dashboard": modulo_dashboard()
    elif menu == "📦 Compras": modulo_compras()
    elif menu == "💸 Tesorería": modulo_tesoreria()
    elif menu == "🚜 Bodega": modulo_bodega()
    elif menu == "💰 COSTOS": modulo_costos()
