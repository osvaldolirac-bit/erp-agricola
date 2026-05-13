import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import os

# --- LIBRERÍAS DE PERSISTENCIA Y REPORTES ---
try:
    from fpdf import FPDF
    from pydrive2.auth import GoogleAuth
    from pydrive2.drive import GoogleDrive
    from oauth2client.service_account import ServiceAccountCredentials
    PERSISTENCE_READY = True
except ImportError:
    PERSISTENCE_READY = False

# --- CONFIGURACIÓN DE PERSISTENCIA ---
ID_CARPETA_DRIVE = "1V7IwdbJPzxQ-hJQaVqOWejHHA1mNbgLo" 
NOMBRE_DB = 'erp_concepcion_v6.db'
JSON_KEY = 'secretos.json'

# --- FUNCIONES DE SINCRONIZACIÓN DRIVE ---
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

# --- CONFIGURACIÓN INICIAL ---
st.set_page_config(page_title="AGRICOLA LA CONCEPCION ERP", page_icon="🚜", layout="wide")

if 'db_sincronizada' not in st.session_state:
    if descargar_de_drive():
        st.toast("✅ Datos sincronizados desde Google Drive", icon="☁️")
    st.session_state['db_sincronizada'] = True

CLAVE_SEGURIDAD = "2908"

def f_puntos(v):
    try: return f"{int(v):,}".replace(",", ".")
    except: return "0"

# --- FUNCION MEJORADA PARA GENERAR PDF ---
def generar_pdf(df, titulo_reporte):
    try:
        pdf = FPDF()
        pdf.add_page()
        # Encabezado de la Empresa
        pdf.set_font("Arial", "B", 16)
        pdf.cell(0, 10, "AGRICOLA LA CONCEPCIÓN", ln=True, align="C")
        # Título del Reporte
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 10, titulo_reporte, ln=True, align="C")
        pdf.ln(5)
        # Fecha del Reporte
        pdf.set_font("Arial", "I", 8)
        pdf.cell(0, 5, f"Reporte generado el: {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True, align="R")
        pdf.ln(5)
        
        # Tabla
        pdf.set_font("Arial", "B", 8)
        cols = df.columns
        w = 190 / len(cols)
        for col in cols:
            pdf.cell(w, 8, str(col), border=1, align="C")
        pdf.ln()
        
        pdf.set_font("Arial", "", 7)
        for _, row in df.iterrows():
            for item in row:
                val = f_puntos(item) if isinstance(item, (int, float)) else str(item)
                pdf.cell(w, 7, val[:20], border=1)
            pdf.ln()
        return pdf.output(dest="S").encode("latin-1")
    except Exception as e:
        st.error(f"Error generando PDF: {e}")
        return None

# --- BASE DE DATOS ---
def conectar_db(): return sqlite3.connect(NOMBRE_DB)

def inicializar_db():
    conn = conectar_db(); cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS facturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nro_documento TEXT, proveedor TEXT, 
        fecha_compra DATE, fecha_vencimiento DATE, monto_neto REAL, monto_total REAL, 
        estado TEXT DEFAULT 'Pendiente', tipo TEXT DEFAULT 'Factura',
        metodo_pago TEXT, fecha_pago DATE)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS detalle_facturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, factura_id INTEGER, producto_id INTEGER, 
        cantidad REAL, precio_neto REAL, total_linea REAL)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS inventario (
        id INTEGER PRIMARY KEY AUTOINCREMENT, producto TEXT, familia TEXT, stock REAL DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS movimientos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, producto_id INTEGER, tipo TEXT, 
        cantidad REAL, centro_costo TEXT, bodega TEXT, fecha DATE, factura_id INTEGER)''')
    conn.commit(); conn.close()

def eliminar_factura(id_f):
    conn = conectar_db(); cursor = conn.cursor()
    detalles = cursor.execute("SELECT producto_id, cantidad FROM detalle_facturas WHERE factura_id=?", (id_f,)).fetchall()
    for p_id, cant in detalles:
        cursor.execute("UPDATE inventario SET stock = stock - ? WHERE id = ?", (cant, p_id))
    cursor.execute("DELETE FROM movimientos WHERE factura_id=?", (id_f,))
    cursor.execute("DELETE FROM detalle_facturas WHERE factura_id=?", (id_f,))
    cursor.execute("DELETE FROM facturas WHERE id=?", (id_f,))
    conn.commit(); conn.close()
    guardar_en_drive()

inicializar_db()
if 'carrito' not in st.session_state: st.session_state['carrito'] = []

# --- SIDEBAR ---
with st.sidebar:
    st.title("LA CONCEPCIÓN ERP")
    if os.path.exists(JSON_KEY):
        st.success("☁️ Sincronización Drive: ACTIVA")
    else:
        st.error("⚠️ Falta secretos.json")
    
    st.markdown("---")
    menu = st.radio("Navegación", ["🏠 Dashboard", "📦 Compras", "💸 Tesorería", "🚜 Bodega"])
    st.markdown("---")
    if st.button("🗑️ Vaciar Carrito"):
        st.session_state['carrito'] = []; st.rerun()

# --- 1. DASHBOARD ---
if menu == "🏠 Dashboard":
    st.header("📊 Resumen del Negocio")
    conn = conectar_db(); df_f = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente'", conn); conn.close()
    
    c1, c2, c3 = st.columns(3)
    total_deuda = df_f['monto_total'].sum() if not df_f.empty else 0
    c1.metric("Deuda Pendiente", f"${f_puntos(total_deuda)}")
    
    vencidas = 0
    if not df_f.empty:
        hoy = datetime.now().date()
        vencidas = df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < hoy].shape[0]
    c2.metric("Documentos Vencidos", vencidas, delta_color="inverse")
    c3.metric("Documentos por Pagar", len(df_f))

    # --- RESTAURACIÓN: PROYECCIÓN 4 MESES ---
    st.subheader("📅 Proyección de Pagos (Próximos 4 meses)")
    cols_m = st.columns(4)
    meses_nombres = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    
    for i in range(4):
        fecha_p = datetime.now() + timedelta(days=i*30)
        mes_idx = fecha_p.month
        anio_p = fecha_p.year
        
        monto_mes = 0
        if not df_f.empty:
            df_f['fv'] = pd.to_datetime(df_f['fecha_vencimiento'])
            monto_mes = df_f[(df_f['fv'].dt.month == mes_idx) & (df_f['fv'].dt.year == anio_p)]['monto_total'].sum()
        
        with cols_m[i]:
            st.metric(f"{meses_nombres[mes_idx-1]} {anio_p}", f"${f_puntos(monto_mes)}")

# --- 2. COMPRAS ---
elif menu == "📦 Compras":
    st.header("Gestión de Compras")
    t1, t2, t3 = st.tabs(["➕ Ingresar Factura", "💸 Gasto Vario", "🔍 Historial"])
    
    with t1:
        c1, c2 = st.columns(2)
        nro = c1.text_input("Número de Factura")
        prov = c1.text_input("Nombre Proveedor")
        f_c = c2.date_input("Fecha Factura", datetime.now())
        f_v = c2.date_input("Fecha Vencimiento", datetime.now() + timedelta(days=30))
        
        conn = conectar_db(); df_inv = pd.read_sql_query("SELECT id, producto FROM inventario ORDER BY producto", conn); conn.close()
        
        if not df_inv.empty:
            st.subheader("🛒 Carrito de Insumos")
            cp1, cp2, cp3, cp4 = st.columns([3,1,1,1])
            p_sel = cp1.selectbox("Producto", df_inv['id'].astype(str) + " - " + df_inv['producto'])
            cant = cp2.number_input("Cantidad", min_value=0.1)
            prec = cp3.number_input("Neto Unitario", min_value=0.0)
            if cp4.button("➕"):
                st.session_state['carrito'].append({
                    'id': int(p_sel.split(" - ")[0]), 'nombre': p_sel.split(" - ")[1],
                    'cantidad': cant, 'precio': prec, 'total': cant * prec
                })
                st.rerun()

        if st.session_state['carrito']:
            df_car = pd.DataFrame(st.session_state['carrito'])
            st.table(df_car[['nombre', 'cantidad', 'precio', 'total']])
            neto = df_car['total'].sum()
            total_sugerido = neto * 1.19
            st.info(f"Neto: ${f_puntos(neto)} | IVA: ${f_puntos(neto*0.19)} | Total Sugerido: ${f_puntos(total_sugerido)}")
            monto_final = st.number_input("Monto Total Final (con IVA)", value=float(total_sugerido))
            
            if st.button("💾 GUARDAR FACTURA COMPLETA"):
                if nro and prov:
                    conn = conectar_db(); cursor = conn.cursor()
                    cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_neto, monto_total, tipo) VALUES (?,?,?,?,?,?,?)",
                                 (nro, prov, f_c, f_v, neto, monto_final, 'Factura'))
                    fid = cursor.lastrowid
                    for i in st.session_state['carrito']:
                        cursor.execute("INSERT INTO detalle_facturas (factura_id, producto_id, cantidad, precio_neto, total_linea) VALUES (?,?,?,?,?)",
                                     (fid, i['id'], i['cantidad'], i['precio'], i['total']))
                        cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (i['cantidad'], i['id']))
                    conn.commit(); conn.close(); guardar_en_drive()
                    st.session_state['carrito'] = []; st.success("✅ Guardado y Sincronizado"); st.rerun()

    with t2:
        with st.form("gasto_v"):
            st.subheader("Registrar Gasto Vario")
            gd1, gd2 = st.columns(2)
            g_p = gd1.text_input("Proveedor")
            g_d = gd1.text_input("N° Documento")
            g_m = gd2.number_input("Monto Total", min_value=0.0)
            g_f = gd2.date_input("Fecha")
            if st.form_submit_button("💾 GUARDAR GASTO"):
                if g_p and g_m > 0:
                    conn = conectar_db(); cursor = conn.cursor()
                    cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, estado) VALUES (?,?,?,?,?,?,?)",
                                 (g_d, g_p, g_f, g_f, g_m, 'Gasto Vario', 'Pendiente'))
                    conn.commit(); conn.close(); guardar_en_drive(); st.success("✅ Gasto Guardado"); st.rerun()

    with t3:
        conn = conectar_db(); df_h = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_compra, monto_total, tipo, estado FROM facturas ORDER BY id DESC", conn); conn.close()
        st.dataframe(df_h, use_container_width=True)
        
        # --- RESTAURACIÓN: BOTÓN PDF HISTORIAL ---
        if not df_h.empty:
            pdf_hist = generar_pdf(df_h, "HISTORIAL DE COMPRAS Y GASTOS")
            st.download_button("📥 Descargar Historial en PDF", pdf_hist, "historial_compras.pdf", "application/pdf")
            
        st.divider()
        c_b1, c_b2, c_b3 = st.columns([1,1,2])
        id_b = c_b1.number_input("ID a Borrar", min_value=0, step=1)
        pw = c_b2.text_input("Clave", type="password")
        if c_b3.button("❌ ELIMINAR REGISTRO"):
            if pw == CLAVE_SEGURIDAD: eliminar_factura(id_b); st.rerun()

# --- 3. TESORERIA ---
elif menu == "💸 Tesorería":
    st.header("Cuentas por Pagar")
    conn = conectar_db()
    df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente'", conn)
    if not df_p.empty:
        st.dataframe(df_p.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
        
        # --- RESTAURACIÓN: BOTÓN PDF PENDIENTES ---
        pdf_pend = generar_pdf(df_p, "CUENTAS POR PAGAR PENDIENTES")
        st.download_button("📥 Descargar Reporte de Pagos en PDF", pdf_pend, "pagos_pendientes.pdf", "application/pdf")
        
        st.divider()
        cc1, cc2, cc3 = st.columns(3)
        id_pagar = cc1.selectbox("ID a Pagar", df_p['id'])
        metodo = cc2.selectbox("Método", ["Transferencia", "Cheque", "Efectivo"])
        if cc3.button("💰 MARCAR PAGADO"):
            cursor = conn.cursor()
            cursor.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (metodo, datetime.now().date(), id_pagar))
            conn.commit(); conn.close(); guardar_en_drive(); st.success("Pago registrado"); st.rerun()
    else: st.info("No hay pagos pendientes.")
    conn.close()

# --- 4. BODEGA ---
elif menu == "🚜 Bodega":
    st.header("Control de Inventario")
    tb1, tb2, tb3 = st.tabs(["📊 Stock Actual", "🔄 Movimientos", "➕ Nuevos Insumos"])
    
    with tb1:
        conn = conectar_db(); df_s = pd.read_sql_query("SELECT id, producto, familia, stock FROM inventario", conn); conn.close()
        st.dataframe(df_s, use_container_width=True)
        
        # --- RESTAURACIÓN: BOTÓN PDF STOCK ---
        if not df_s.empty:
            pdf_stock = generar_pdf(df_s, "INVENTARIO DE BODEGA")
            st.download_button("📥 Descargar Stock en PDF", pdf_stock, "inventario_bodega.pdf", "application/pdf")
    
    with tb2:
        with st.form("mov"):
            conn = conectar_db(); prods = pd.read_sql_query("SELECT id, producto FROM inventario", conn); conn.close()
            p_m = st.selectbox("Insumo", prods['id'].astype(str) + " - " + prods['producto'])
            tipo_m = st.radio("Tipo", ["Salida (Uso)", "Entrada (Ajuste)"])
            cant_m = st.number_input("Cantidad", min_value=0.1)
            cc_m = st.text_input("Centro Costo")
            if st.form_submit_button("REGISTRAR"):
                id_p = int(p_m.split(" - ")[0])
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo) VALUES (?,?,?,?,?)", (id_p, tipo_m, cant_m, datetime.now().date(), cc_m))
                f = 1 if tipo_m == "Entrada (Ajuste)" else -1
                cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (cant_m * f, id_p))
                conn.commit(); conn.close(); guardar_en_drive(); st.success("Sincronizado"); st.rerun()

    with tb3:
        with st.form("new"):
            st.subheader("Crear Producto")
            n_p = st.text_input("Nombre"); f_p = st.selectbox("Familia", ["Fertilizante", "Petróleo", "Herbicida", "Insecticida", "Fungicidas", "Bio estimulante", "Otros"])
            if st.form_submit_button("CREAR"):
                conn = conectar_db(); conn.execute("INSERT INTO inventario (producto, familia, stock) VALUES (?,?,0)", (n_p, f_p)); conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
