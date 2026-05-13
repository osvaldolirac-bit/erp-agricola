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

# --- LISTAS MAESTRAS (CAMPOS FIJOS) ---
FAMILIAS_INSUMOS = ["FERTILIZANTE", "FERTILIZANTE FOLIAR", "HERBICIDA", "INSECTICIDA", "FUNGICIDA", "BIO ESTIMULANTE", "OTROS"]
CENTROS_COSTO = ["CEREZOS CORTE1", "CEREZOS CORTE2", "CIRUELOS", "NOGALES APARICION", "NOGALES CRUZ DEL SUR", "OTROS"]

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

# --- GENERADOR DE PDF ---
def descargar_pdf(df, titulo):
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", "B", 16)
        pdf.cell(0, 10, "AGRICOLA LA CONCEPCIÓN", ln=True, align="C")
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 10, titulo, ln=True, align="C")
        pdf.ln(5)
        pdf.set_font("Arial", "B", 8)
        cols = df.columns
        w = 190 / len(cols)
        for col in cols: pdf.cell(w, 8, str(col), border=1, align="C")
        pdf.ln()
        pdf.set_font("Arial", "", 7)
        for _, row in df.iterrows():
            for item in row:
                val = f_puntos(item) if isinstance(item, (int, float)) else str(item)
                pdf.cell(w, 7, val[:20], border=1)
            pdf.ln()
        return pdf.output(dest="S").encode("latin-1")
    except: return None

# --- INICIALIZACIÓN Y MIGRACIÓN ---
st.set_page_config(page_title="AGRICOLA LA CONCEPCION ERP", page_icon="🚜", layout="wide")

if 'db_sincronizada' not in st.session_state:
    descargar_de_drive()
    st.session_state['db_sincronizada'] = True

def inicializar_db():
    conn = conectar_db(); cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS facturas (id INTEGER PRIMARY KEY AUTOINCREMENT, nro_documento TEXT, proveedor TEXT, fecha_compra DATE, fecha_vencimiento DATE, monto_neto REAL, monto_total REAL, estado TEXT DEFAULT 'Pendiente', tipo TEXT DEFAULT 'Factura', metodo_pago TEXT, fecha_pago DATE)")
    cursor.execute("CREATE TABLE IF NOT EXISTS detalle_facturas (id INTEGER PRIMARY KEY AUTOINCREMENT, factura_id INTEGER, producto_id INTEGER, cantidad REAL, precio_neto REAL, total_linea REAL)")
    cursor.execute("CREATE TABLE IF NOT EXISTS inventario (id INTEGER PRIMARY KEY AUTOINCREMENT, producto TEXT, familia TEXT, stock REAL DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS movimientos (id INTEGER PRIMARY KEY AUTOINCREMENT, producto_id INTEGER, tipo TEXT, cantidad REAL, centro_costo TEXT, fecha DATE, factura_id INTEGER)")
    
    cursor.execute("PRAGMA table_info(facturas)")
    columnas = [info[1] for info in cursor.fetchall()]
    if 'concepto' not in columnas:
        cursor.execute("ALTER TABLE facturas ADD COLUMN concepto TEXT")
    
    conn.commit(); conn.close()

inicializar_db()
if 'carrito' not in st.session_state: st.session_state['carrito'] = []

# --- MODULOS ---

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
    t1, t2, t3 = st.tabs(["➕ Factura Insumos", "💸 Gasto Vario", "🔍 Historial"])
    with t1:
        c1, c2 = st.columns(2)
        nro, prov = c1.text_input("N° Factura"), c1.text_input("Proveedor")
        f_c, f_v = c2.date_input("Emisión"), c2.date_input("Vencimiento")
        conn = conectar_db(); df_inv = pd.read_sql_query("SELECT id, producto FROM inventario", conn); conn.close()
        if not df_inv.empty:
            cp1, cp2, cp3, cp4 = st.columns([3,1,1,1])
            p_sel = cp1.selectbox("Producto", df_inv['id'].astype(str) + " - " + df_inv['producto'])
            cant, prec = cp2.number_input("Cant.", min_value=0.1), cp3.number_input("Neto Un.", min_value=0.0)
            if cp4.button("➕"):
                st.session_state['carrito'].append({'id': int(p_sel.split(" - ")[0]), 'nombre': p_sel.split(" - ")[1], 'cantidad': cant, 'precio': prec, 'total': cant * prec})
                st.rerun()
        if st.session_state['carrito']:
            df_c = pd.DataFrame(st.session_state['carrito'])
            st.table(df_c[['nombre', 'cantidad', 'precio', 'total']])
            neto = df_c['total'].sum()
            m_final = st.number_input("Total Final Factura", value=float(neto*1.19))
            if st.button("💾 GUARDAR FACTURA"):
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_neto, monto_total) VALUES (?,?,?,?,?,?)", (nro, prov, f_c, f_v, neto, m_final))
                fid = cursor.lastrowid
                for i in st.session_state['carrito']:
                    cursor.execute("INSERT INTO detalle_facturas (factura_id, producto_id, cantidad, precio_neto, total_linea) VALUES (?,?,?,?,?)", (fid, i['id'], i['cantidad'], i['precio'], i['total']))
                    cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (i['cantidad'], i['id']))
                conn.commit(); conn.close(); guardar_en_drive(); st.session_state['carrito'] = []; st.success("✅ Guardado"); st.rerun()
    with t2:
        with st.form("gv"):
            st.subheader("Gasto Directo"); g1, g2 = st.columns(2)
            gp, gd = g1.text_input("Proveedor"), g1.text_input("N° Doc")
            gm, gf = g2.number_input("Monto"), g2.date_input("Fecha")
            g_con = st.text_area("Concepto/Detalle")
            if st.form_submit_button("💾 GUARDAR GASTO"):
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, concepto, estado) VALUES (?,?,?,?,?,?,?,?)", (gd, gp, gf, gf, gm, 'Gasto Vario', g_con, 'Pendiente'))
                conn.commit(); conn.close(); guardar_en_drive(); st.success("✅ Gasto Registrado"); st.rerun()
    with t3:
        c_h1, c_h2 = st.columns(2)
        f_ini, f_fin = c_h1.date_input("Desde", datetime.now()-timedelta(days=60)), c_h2.date_input("Hasta", datetime.now())
        conn = conectar_db(); df_h = pd.read_sql_query(f"SELECT id, nro_documento, proveedor, fecha_compra, monto_total, tipo, concepto FROM facturas WHERE fecha_compra BETWEEN '{f_ini}' AND '{f_fin}' ORDER BY fecha_compra DESC", conn); conn.close()
        st.dataframe(df_h, use_container_width=True)
        if not df_h.empty:
            pdf = descargar_pdf(df_h, "HISTORIAL COMPRAS"); st.download_button("📥 PDF Historial", pdf, "historial.pdf")
        st.divider(); cb1, cb2, cb3 = st.columns([1,1,2])
        id_b = cb1.number_input("ID a Borrar", min_value=0, step=1); pw = cb2.text_input("Clave", type="password")
        if cb3.button("❌ ELIMINAR"):
            if pw == CLAVE_SEGURIDAD:
                conn = conectar_db(); cursor = conn.cursor(); cursor.execute("DELETE FROM facturas WHERE id=?", (id_b,)); conn.commit(); conn.close(); guardar_en_drive(); st.rerun()

def modulo_tesoreria():
    st.header("Cuentas por Pagar")
    tp1, tp2, tp3 = st.tabs(["🔴 Pendientes", "🏢 Proveedor", "📅 Vencimiento"])
    conn = conectar_db()
    with tp1:
        df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente'", conn)
        if not df_p.empty:
            def style_v(row):
                v = pd.to_datetime(row['fecha_vencimiento']).date()
                return ['background-color: #ffcccc' if v < datetime.now().date() else '' for _ in row]
            st.dataframe(df_p.style.apply(style_v, axis=1).format({"monto_total": "${:,.0f}"}), use_container_width=True)
            st.write(f"**Total Deuda:** ${f_puntos(df_p['monto_total'].sum())}")
            c1, c2 = st.columns(2); id_p = c1.selectbox("ID Pago", df_p['id']); met = c2.selectbox("Medio", ["Transferencia", "Cheque", "Efectivo"])
            if st.button("💰 PAGAR"):
                conn.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (met, datetime.now().date(), id_p))
                conn.commit(); guardar_en_drive(); st.rerun()
            pdf = descargar_pdf(df_p, "PENDIENTES"); st.download_button("📥 PDF Pendientes", pdf, "pendientes.pdf")
    with tp2:
        pro_list = pd.read_sql_query("SELECT DISTINCT proveedor FROM facturas WHERE estado='Pendiente'", conn)
        if not pro_list.empty:
            p_sel = st.selectbox("Elegir Proveedor", pro_list)
            df_pro = pd.read_sql_query(f"SELECT nro_documento, fecha_vencimiento, monto_total FROM facturas WHERE proveedor='{p_sel}' AND estado='Pendiente'", conn)
            st.table(df_pro); st.metric(f"Total {p_sel}", f"${f_puntos(df_pro['monto_total'].sum())}")
    with tp3:
        f1, f2 = st.columns(2); v1, v2 = f1.date_input("Desde V.", datetime.now()), f2.date_input("Hasta V.", datetime.now()+timedelta(days=30))
        df_v = pd.read_sql_query(f"SELECT nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' AND fecha_vencimiento BETWEEN '{v1}' AND '{v2}'", conn)
        st.dataframe(df_v, use_container_width=True); st.metric("Total Rango", f"${f_puntos(df_v['monto_total'].sum())}")
    conn.close()

def modulo_bodega():
    st.header("Inventario")
    tb1, tb2, tb3, tb4 = st.tabs(["📊 Stock Actual", "🔍 Consultas CC", "🔄 Registrar Movimiento", "➕ Nuevo Insumo"])
    with tb1:
        conn = conectar_db(); df_s = pd.read_sql_query("SELECT id, producto, familia, stock FROM inventario", conn); conn.close()
        bus = st.text_input("🔍 Buscar Insumo")
        if bus: df_s = df_s[df_s['producto'].str.contains(bus, case=False)]
        st.dataframe(df_s, use_container_width=True)
        pdf = descargar_pdf(df_s, "STOCK BODEGA"); st.download_button("📥 PDF Stock", pdf, "stock.pdf")
    with tb2:
        conn = conectar_db()
        # --- CONSULTA POR CENTRO DE COSTO (CUARTEL) ---
        cc_list = pd.read_sql_query("SELECT DISTINCT centro_costo FROM movimientos WHERE centro_costo IS NOT NULL", conn)
        if not cc_list.empty:
            cc_s = st.selectbox("Seleccionar Cuartel para revisar gasto", cc_list)
            df_cc = pd.read_sql_query(f"SELECT m.fecha, i.producto, m.tipo, m.cantidad FROM movimientos m JOIN inventario i ON m.producto_id = i.id WHERE m.centro_costo='{cc_s}'", conn)
            st.dataframe(df_cc, use_container_width=True)
            st.info(f"Mostrando movimientos del sector: {cc_s}")
        else:
            st.warning("No hay movimientos registrados en ningún Centro de Costo aún.")
        conn.close()
    with tb3:
        with st.form("mov_b"):
            conn = conectar_db(); prs = pd.read_sql_query("SELECT id, producto FROM inventario", conn); conn.close()
            p_m = st.selectbox("Insumo", prs['id'].astype(str) + " - " + prs['producto'])
            tm, cm = st.radio("Acción", ["Salida (Uso en Campo)", "Entrada"]), st.number_input("Cant.", min_value=0.1)
            # --- CENTROS DE COSTO RESTAURADOS AQUÍ ---
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
            if st.form_submit_button("CREAR"):
                conn = conectar_db(); conn.execute("INSERT INTO inventario (producto, familia, stock) VALUES (?,?,0)", (nn, ff)); conn.commit(); conn.close(); guardar_en_drive(); st.rerun()

# --- NAVEGACIÓN ---
with st.sidebar:
    st.title("LA CONCEPCIÓN ERP")
    if os.path.exists(JSON_KEY): st.success("☁️ Drive: ACTIVA")
    else: st.error("⚠️ Falta secretos.json")
    menu = st.radio("Navegación", ["🏠 Dashboard", "📦 Compras", "💸 Tesorería", "🚜 Bodega"])
    if st.button("🗑️ Vaciar Carrito"): st.session_state['carrito'] = []; st.rerun()

# EJECUCIÓN
if menu == "🏠 Dashboard": modulo_dashboard()
elif menu == "📦 Compras": modulo_compras()
elif menu == "💸 Tesorería": modulo_tesoreria()
elif menu == "🚜 Bodega": modulo_bodega()
