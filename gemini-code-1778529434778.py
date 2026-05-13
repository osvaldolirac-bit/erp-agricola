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
    st.error("Faltan librerías. Revisa requirements.txt")

# --- CONFIGURACIÓN DRIVE ---
ID_CARPETA_DRIVE = "1V7IwdbJPzxQ-hJQaVqOWejHHA1mNbgLo" 
NOMBRE_DB = 'erp_concepcion_v6.db'
JSON_KEY = 'secretos.json'

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

# --- CONFIG PÁGINA ---
st.set_page_config(page_title="AGRICOLA LA CONCEPCION ERP", page_icon="🚜", layout="wide")

if 'db_sincronizada' not in st.session_state:
    descargar_de_drive()
    st.session_state['db_sincronizada'] = True

CLAVE_SEGURIDAD = "2908"

def f_puntos(v):
    try: return f"{int(v):,}".replace(",", ".")
    except: return "0"

# --- PDF MEJORADO ---
def generar_pdf(df, titulo):
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

# --- BASE DE DATOS ---
def conectar_db(): return sqlite3.connect(NOMBRE_DB)

def inicializar_db():
    conn = conectar_db(); cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS facturas (id INTEGER PRIMARY KEY AUTOINCREMENT, nro_documento TEXT, proveedor TEXT, fecha_compra DATE, fecha_vencimiento DATE, monto_neto REAL, monto_total REAL, estado TEXT DEFAULT 'Pendiente', tipo TEXT DEFAULT 'Factura', metodo_pago TEXT, fecha_pago DATE, concepto TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS detalle_facturas (id INTEGER PRIMARY KEY AUTOINCREMENT, factura_id INTEGER, producto_id INTEGER, cantidad REAL, precio_neto REAL, total_linea REAL)")
    cursor.execute("CREATE TABLE IF NOT EXISTS inventario (id INTEGER PRIMARY KEY AUTOINCREMENT, producto TEXT, familia TEXT, stock REAL DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS movimientos (id INTEGER PRIMARY KEY AUTOINCREMENT, producto_id INTEGER, tipo TEXT, cantidad REAL, centro_costo TEXT, fecha DATE, factura_id INTEGER)")
    conn.commit(); conn.close()

inicializar_db()
if 'carrito' not in st.session_state: st.session_state['carrito'] = []

# --- SIDEBAR ---
with st.sidebar:
    st.title("LA CONCEPCIÓN ERP")
    st.success("☁️ Drive: Activo" if os.path.exists(JSON_KEY) else "⚠️ Error Drive")
    menu = st.radio("Menú", ["🏠 Dashboard", "📦 Compras", "💸 Tesorería", "🚜 Bodega"])
    if st.button("🗑️ Vaciar Carrito"): st.session_state['carrito'] = []; st.rerun()

# --- 1. DASHBOARD ---
if menu == "🏠 Dashboard":
    st.header("📊 Dashboard Financiero")
    conn = conectar_db(); df_f = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente'", conn); conn.close()
    
    c1, c2, c3 = st.columns(3)
    total_deuda = df_f['monto_total'].sum() if not df_f.empty else 0
    c1.metric("Deuda Total", f"${f_puntos(total_deuda)}")
    
    vencidas = 0
    if not df_f.empty:
        hoy = datetime.now().date()
        vencidas = df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < hoy].shape[0]
    c2.metric("Vencidas", vencidas, delta_color="inverse")
    c3.metric("Documentos", len(df_f))

    st.subheader("📅 Proyección 4 Meses")
    cols_p = st.columns(4)
    meses = ["Enero","Febrero","Marzo","Abril","Mayo","Junio","Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]
    for i in range(4):
        f = datetime.now() + timedelta(days=i*30)
        m, a = f.month, f.year
        val = 0
        if not df_f.empty:
            df_f['fv'] = pd.to_datetime(df_f['fecha_vencimiento'])
            val = df_f[(df_f['fv'].dt.month == m) & (df_f['fv'].dt.year == a)]['monto_total'].sum()
        cols_p[i].metric(f"{meses[m-1]} {a}", f"${f_puntos(val)}")

# --- 2. COMPRAS ---
elif menu == "📦 Compras":
    st.header("Ingreso de Compras")
    t1, t2, t3 = st.tabs(["➕ Factura Insumos", "💸 Gasto Vario", "🔍 Historial"])
    
    with t1:
        c1, c2 = st.columns(2)
        nro, prov = c1.text_input("N° Factura"), c1.text_input("Proveedor")
        f_c, f_v = c2.date_input("Fecha Emisión"), c2.date_input("Vencimiento")
        
        conn = conectar_db(); df_inv = pd.read_sql_query("SELECT id, producto FROM inventario", conn); conn.close()
        if not df_inv.empty:
            cp1, cp2, cp3, cp4 = st.columns([3,1,1,1])
            p_sel = cp1.selectbox("Insumo", df_inv['id'].astype(str) + " - " + df_inv['producto'])
            cant, prec = cp2.number_input("Cant.", min_value=0.1), cp3.number_input("Neto", min_value=0.0)
            if cp4.button("➕"):
                st.session_state['carrito'].append({'id': int(p_sel.split(" - ")[0]), 'nombre': p_sel.split(" - ")[1], 'cantidad': cant, 'precio': prec, 'total': cant * prec})
                st.rerun()

        if st.session_state['carrito']:
            df_c = pd.DataFrame(st.session_state['carrito'])
            st.table(df_c[['nombre', 'cantidad', 'precio', 'total']])
            neto = df_c['total'].sum()
            st.write(f"**Neto:** ${f_puntos(neto)} | **IVA:** ${f_puntos(neto*0.19)}")
            m_total = st.number_input("Total Final Factura", value=float(neto*1.19))
            if st.button("💾 GUARDAR FACTURA"):
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_neto, monto_total) VALUES (?,?,?,?,?,?)", (nro, prov, f_c, f_v, neto, m_total))
                fid = cursor.lastrowid
                for i in st.session_state['carrito']:
                    cursor.execute("INSERT INTO detalle_facturas (factura_id, producto_id, cantidad, precio_neto, total_linea) VALUES (?,?,?,?,?)", (fid, i['id'], i['cantidad'], i['precio'], i['total']))
                    cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (i['cantidad'], i['id']))
                conn.commit(); conn.close(); guardar_en_drive(); st.session_state['carrito'] = []; st.rerun()

    with t2:
        with st.form("gv"):
            st.subheader("Registrar Gasto Directo")
            g1, g2 = st.columns(2)
            gp, gd = g1.text_input("Proveedor"), g1.text_input("N° Documento")
            gm, gf = g2.number_input("Monto Total"), g2.date_input("Fecha")
            # RESTAURADO: CUADRO DE DETALLE
            g_con = st.text_area("Concepto o Detalle del Gasto")
            if st.form_submit_button("💾 GUARDAR GASTO"):
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, concepto) VALUES (?,?,?,?,?,?,?)", (gd, gp, gf, gf, gm, 'Gasto Vario', g_con))
                conn.commit(); conn.close(); guardar_en_drive(); st.rerun()

    with t3:
        conn = conectar_db(); df_hist = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_compra, monto_total, tipo FROM facturas ORDER BY id DESC", conn); conn.close()
        st.dataframe(df_hist, use_container_width=True)
        if st.button("📥 Descargar Historial PDF"):
            st.download_button("Descargar", generar_pdf(df_hist, "HISTORIAL DE COMPRAS"), "historial.pdf")

# --- 3. TESORERIA ---
elif menu == "💸 Tesorería":
    st.header("Cuentas por Pagar")
    tp1, tp2, tp3 = st.tabs(["🔴 Pendientes", "🏢 Por Proveedor", "📅 Rango de Fechas"])
    
    conn = conectar_db()
    with tp1:
        df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente'", conn)
        if not df_p.empty:
            # RESTAURADO: COLOR ROJO PARA VENCIDOS
            def color_vencido(row):
                venc = pd.to_datetime(row['fecha_vencimiento']).date()
                return ['background-color: #ffcccc' if venc < datetime.now().date() else '' for _ in row]
            
            st.dataframe(df_p.style.apply(color_vencido, axis=1).format({"monto_total": "${:,.0f}"}), use_container_width=True)
            st.write(f"**Deuda Pendiente Total:** ${f_puntos(df_p['monto_total'].sum())}")
            
            c1, c2 = st.columns(2)
            id_pag = c1.selectbox("ID a Pagar", df_p['id'])
            met = c2.selectbox("Método", ["Transferencia", "Cheque", "Efectivo"])
            if st.button("💰 PAGAR"):
                conn.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (met, datetime.now().date(), id_pag))
                conn.commit(); guardar_en_drive(); st.rerun()
        if st.button("📥 PDF Pendientes"):
            st.download_button("Descargar", generar_pdf(df_p, "PENDIENTES DE PAGO"), "pendientes.pdf")

    with tp2:
        # RESTAURADO: FILTRO PROVEEDOR
        prov_sel = st.selectbox("Seleccionar Proveedor", pd.read_sql_query("SELECT DISTINCT proveedor FROM facturas WHERE estado='Pendiente'", conn))
        df_prov = pd.read_sql_query(f"SELECT nro_documento, fecha_vencimiento, monto_total FROM facturas WHERE proveedor='{prov_sel}' AND estado='Pendiente'", conn)
        st.table(df_prov)
        st.metric(f"Total {prov_sel}", f"${f_puntos(df_prov['monto_total'].sum())}")

    with tp3:
        # RESTAURADO: FILTRO RANGO FECHAS
        c_f1, c_f2 = st.columns(2)
        f1, f2 = c_f1.date_input("Desde"), c_f2.date_input("Hasta")
        df_r = pd.read_sql_query(f"SELECT nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' AND fecha_vencimiento BETWEEN '{f1}' AND '{f2}'", conn)
        st.dataframe(df_r, use_container_width=True)
        st.metric("Total Rango", f"${f_puntos(df_r['monto_total'].sum())}")
    conn.close()

# --- 4. BODEGA ---
elif menu == "🚜 Bodega":
    st.header("Inventario y Bodega")
    tb1, tb2, tb3 = st.tabs(["📊 Stock", "🔍 Consultas", "🔄 Movimiento", "➕ Nuevo Insumo"])
    
    with tb1:
        conn = conectar_db(); df_s = pd.read_sql_query("SELECT id, producto, familia, stock FROM inventario", conn); conn.close()
        # RESTAURADO: BUSCADOR DE PRODUCTOS
        search = st.text_input("🔍 Buscar Insumo")
        if search: df_s = df_s[df_s['producto'].str.contains(search, case=False)]
        st.dataframe(df_s, use_container_width=True)
        if st.button("📥 PDF Stock"):
            st.download_button("Descargar", generar_pdf(df_s, "INVENTARIO DE BODEGA"), "stock.pdf")

    with tb2:
        # RESTAURADO: CONSULTA POR CENTRO DE COSTO
        conn = conectar_db()
        cc_list = pd.read_sql_query("SELECT DISTINCT centro_costo FROM movimientos", conn)
        cc_sel = st.selectbox("Seleccionar Centro de Costo / Cuartel", cc_list)
        df_cc = pd.read_sql_query(f"SELECT m.fecha, i.producto, m.tipo, m.cantidad FROM movimientos m JOIN inventario i ON m.producto_id = i.id WHERE m.centro_costo='{cc_sel}'", conn)
        conn.close()
        st.dataframe(df_cc, use_container_width=True)

    with tb3:
        with st.form("mov"):
            conn = conectar_db(); prods = pd.read_sql_query("SELECT id, producto FROM inventario", conn); conn.close()
            ps = st.selectbox("Insumo", prods['id'].astype(str) + " - " + prods['producto'])
            tm, cm = st.radio("Tipo", ["Salida (Uso)", "Entrada"]), st.number_input("Cantidad", min_value=0.1)
            cc = st.text_input("Centro de Costo")
            if st.form_submit_button("REGISTRAR"):
                id_p = int(ps.split(" - ")[0])
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo) VALUES (?,?,?,?,?)", (id_p, tm, cm, datetime.now().date(), cc))
                f = 1 if tm == "Entrada" else -1
                cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (cm*f, id_p))
                conn.commit(); conn.close(); guardar_en_drive(); st.rerun()

    with tb3: # Es la pestaña 4, pero comparto el bloque
        with st.form("ni"):
            st.subheader("Crear Producto")
            n = st.text_input("Nombre"); f = st.selectbox("Familia", ["Fertilizante", "Herbicida", "Petróleo", "Otros"])
            if st.form_submit_button("CREAR"):
                conn = conectar_db(); conn.execute("INSERT INTO inventario (producto, familia, stock) VALUES (?,?,0)", (n, f)); conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
