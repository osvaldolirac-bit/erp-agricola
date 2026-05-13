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
    st.error("Error: Revisa requirements.txt")

# --- CONFIGURACIÓN ---
ID_CARPETA_DRIVE = "1V7IwdbJPzxQ-hJQaVqOWejHHA1mNbgLo" 
NOMBRE_DB = 'erp_concepcion_v6.db'
JSON_KEY = 'secretos.json'
CLAVE_SEGURIDAD = "2908" # <-- El candado de la bodega

# --- UTILIDADES ---
def f_puntos(v):
    try: return f"{int(v):,}".replace(",", ".")
    except: return "0"

def conectar_db(): return sqlite3.connect(NOMBRE_DB)

# --- SINCRONIZACIÓN DRIVE ---
def obtener_drive():
    if not os.path.exists(JSON_KEY): return None
    try:
        scope = ['https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name(JSON_KEY, scope)
        gauth = GoogleAuth()
        gauth.credentials = creds
        return GoogleDrive(gauth)
    except: return None

def guardar_en_drive():
    try:
        drive = obtener_drive()
        if not drive: return False
        query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
        lista = drive.ListFile({'q': query}).GetList()
        f = lista[0] if lista else drive.CreateFile({'title': NOMBRE_DB, 'parents': [{'id': ID_CARPETA_DRIVE}]})
        f.SetContentFile(NOMBRE_DB)
        f.Upload()
        st.success("✅ Datos sincronizados en la nube")
        return True
    except: return False

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
    c2.metric("Facturas Vencidas", vencidas, delta_color="inverse")
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
    t1, t2, t3 = st.tabs(["➕ Factura Insumos", "💸 Gasto Vario", "🔍 Historial / Gestionar"])
    with t1:
        c1, c2 = st.columns(2)
        nro, prov = c1.text_input("N° Factura"), c1.text_input("Proveedor")
        f_c, f_v = c2.date_input("Emisión"), c2.date_input("Vencimiento")
        conn = conectar_db(); df_inv = pd.read_sql_query("SELECT id, producto FROM inventario ORDER BY producto", conn); conn.close()
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
                conn.commit(); conn.close(); guardar_en_drive(); st.session_state['carrito'] = []; st.rerun()

    with t2:
        with st.form("gv"):
            gp, gd = st.text_input("Proveedor"), st.text_input("N° Doc")
            gm, gf = st.number_input("Monto Total"), st.date_input("Fecha Emisión")
            g_con = st.text_area("Concepto/Detalle")
            if st.form_submit_button("💾 GUARDAR GASTO"):
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, concepto, estado) VALUES (?,?,?,?,?,?,?,?)", (gd, gp, gf, gf, gm, 'Gasto Vario', g_con, 'Pendiente'))
                conn.commit(); conn.close(); guardar_en_drive(); st.rerun()

    with t3:
        # --- HISTORIAL Y GESTIÓN ---
        conn = conectar_db()
        df_range = pd.read_sql_query("SELECT MIN(fecha_compra) as min_f, MAX(fecha_compra) as max_f FROM facturas", conn)
        default_ini = datetime.now().date() - timedelta(days=60)
        default_fin = datetime.now().date()
        if not df_range.empty and df_range['min_f'].iloc[0]:
            try:
                default_ini = pd.to_datetime(df_range['min_f'].iloc[0]).date()
                default_fin = pd.to_datetime(df_range['max_f'].iloc[0]).date()
            except: pass
        
        c_f1, c_f2 = st.columns(2)
        f_i = c_f1.date_input("Desde", value=default_ini, key="h_d")
        f_f = c_f2.date_input("Hasta", value=default_fin, key="h_h")
        
        df_h = pd.read_sql_query(f"SELECT id, nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, concepto, estado FROM facturas WHERE fecha_compra BETWEEN '{f_i}' AND '{f_f}' ORDER BY fecha_compra DESC", conn)
        st.dataframe(df_h, use_container_width=True)
        
        if not df_h.empty:
            st.download_button("📥 PDF Historial", descargar_pdf(df_h, "HISTORIAL"), "historial.pdf")
            st.divider()
            st.subheader("⚙️ Gestión de Documento")
            sel_id = st.selectbox("ID a gestionar", df_h['id'])
            row = df_h[df_h['id'] == sel_id].iloc[0]
            
            c_m, c_e = st.columns(2)
            
            with c_m:
                with st.expander("📝 MODIFICAR DATOS"):
                    m_nro = st.text_input("N° Doc", value=row['nro_documento'])
                    m_prov = st.text_input("Proveedor", value=row['proveedor'])
                    # NUEVOS CAMPOS DE FECHA EN EDICIÓN
                    m_f_c = st.date_input("Nueva Fecha Compra", value=pd.to_datetime(row['fecha_compra']).date())
                    m_f_v = st.date_input("Nueva Fecha Venc.", value=pd.to_datetime(row['fecha_vencimiento']).date())
                    m_monto = st.number_input("Monto", value=float(row['monto_total']))
                    m_con = st.text_area("Concepto", value=str(row['concepto']) if row['concepto'] else "")
                    
                    # CLAVE DE SEGURIDAD PARA MODIFICAR
                    clave_m = st.text_input("Clave de Seguridad", type="password", key="cl_m")
                    if st.button("💾 ACTUALIZAR"):
                        if clave_m == CLAVE_SEGURIDAD:
                            conn.execute("UPDATE facturas SET nro_documento=?, proveedor=?, fecha_compra=?, fecha_vencimiento=?, monto_total=?, concepto=? WHERE id=?", 
                                         (m_nro, m_prov, m_f_c, m_f_v, m_monto, m_con, sel_id))
                            conn.commit(); guardar_en_drive(); st.success("¡Listo! Documento actualizado."); st.rerun()
                        else:
                            st.error("❌ Clave incorrecta")
            
            with c_e:
                with st.expander("🗑️ ELIMINAR"):
                    st.warning(f"¿Eliminar ID {sel_id}?")
                    # CLAVE DE SEGURIDAD PARA ELIMINAR
                    clave_e = st.text_input("Clave de Seguridad", type="password", key="cl_e")
                    if st.button("🔥 ELIMINAR AHORA"):
                        if clave_e == CLAVE_SEGURIDAD:
                            conn.execute("DELETE FROM facturas WHERE id=?", (sel_id,))
                            conn.commit(); guardar_en_drive(); st.success("Documento eliminado"); st.rerun()
                        else:
                            st.error("❌ Clave incorrecta")
        conn.close()

def modulo_tesoreria():
    st.header("Cuentas por Pagar")
    tp1, tp2, tp3 = st.tabs(["🔴 Pendientes", "🏢 Por Proveedor", "📅 Por Vencimiento"])
    conn = conectar_db()
    with tp1:
        df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' ORDER BY fecha_vencimiento ASC", conn)
        if not df_p.empty:
            def style_v(row):
                v = pd.to_datetime(row['fecha_vencimiento']).date()
                return ['background-color: #ffcccc' if v < datetime.now().date() else '' for _ in row]
            st.dataframe(df_p.style.apply(style_v, axis=1).format({"monto_total": "${:,.0f}"}), use_container_width=True)
            c1, c2 = st.columns(2); id_p = c1.selectbox("ID Pago", df_p['id']); met = c2.selectbox("Medio", ["Transferencia", "Cheque", "Efectivo"])
            if st.button("💰 PAGAR"):
                conn.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (met, datetime.now().date(), id_p))
                conn.commit(); guardar_en_drive(); st.rerun()
    with tp2:
        provs = pd.read_sql_query("SELECT DISTINCT proveedor FROM facturas WHERE estado='Pendiente'", conn)
        if not provs.empty:
            ps = st.selectbox("Proveedor", provs['proveedor'])
            df_pr = pd.read_sql_query(f"SELECT nro_documento, fecha_vencimiento, monto_total FROM facturas WHERE proveedor='{ps}' AND estado='Pendiente' ORDER BY fecha_vencimiento ASC", conn)
            st.table(df_pr)
    with tp3:
        v1, v2 = st.date_input("Desde V."), st.date_input("Hasta V.", datetime.now().date()+timedelta(days=30))
        df_v = pd.read_sql_query(f"SELECT nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' AND fecha_vencimiento BETWEEN '{v1}' AND '{v2}' ORDER BY fecha_vencimiento ASC", conn)
        st.dataframe(df_v, use_container_width=True)
    conn.close()

def modulo_bodega():
    st.header("Inventario")
    tb1, tb2, tb3, tb4 = st.tabs(["📊 Stock", "🔍 Consultas CC", "🔄 Movimiento", "➕ Nuevo Insumo"])
    FAMILIAS = ["FERTILIZANTE", "FERTILIZANTE FOLIAR", "HERBICIDA", "INSECTICIDA", "FUNGICIDA", "BIO ESTIMULANTE", "OTROS"]
    CENTROS = ["CEREZOS CORTE1", "CEREZOS CORTE2", "CIRUELOS", "NOGALES APARICION", "NOGALES CRUZ DEL SUR", "OTROS"]
    with tb1:
        conn = conectar_db(); df = pd.read_sql_query("SELECT id, producto, familia, stock, stock_minimo FROM inventario ORDER BY producto ASC", conn); conn.close()
        st.dataframe(df, use_container_width=True)
    with tb3:
        tipo = st.radio("Tipo", ["Salida (Campo)", "Entrada"])
        with st.form("m"):
            conn = conectar_db(); prs = pd.read_sql_query("SELECT id, producto FROM inventario ORDER BY producto", conn); conn.close()
            ps = st.selectbox("Insumo", prs['id'].astype(str) + " - " + prs['producto'])
            cm = st.number_input("Cant.", min_value=0.1)
            cc = st.selectbox("Cuartel", CENTROS) if tipo == "Salida (Campo)" else None
            if st.form_submit_button("REGISTRAR"):
                ip = int(ps.split(" - ")[0]); conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo) VALUES (?,?,?,?,?)", (ip, tipo, cm, datetime.now().date(), cc))
                f = 1 if tipo == "Entrada" else -1
                cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (cm*f, ip))
                conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
    with tb4:
        with st.form("n"):
            nn = st.text_input("Nombre"); ff = st.selectbox("Familia", FAMILIAS); sm = st.number_input("Mínimo", min_value=0.0)
            if st.form_submit_button("CREAR"):
                conn = conectar_db(); conn.execute("INSERT INTO inventario (producto, familia, stock, stock_minimo) VALUES (?,?,?,?)", (nn, ff, 0, sm)); conn.commit(); conn.close(); guardar_en_drive(); st.rerun()

# --- NAVEGACIÓN ---
with st.sidebar:
    st.title("LA CONCEPCIÓN ERP")
    st.success("☁️ Drive: ACTIVA" if os.path.exists(JSON_KEY) else "⚠️ Drive: DESCONECTADO")
    menu = st.radio("Navegación", ["🏠 Dashboard", "📦 Compras", "💸 Tesorería", "🚜 Bodega"])

if menu == "🏠 Dashboard": modulo_dashboard()
elif menu == "📦 Compras": modulo_compras()
elif menu == "💸 Tesorería": modulo_tesoreria()
elif menu == "🚜 Bodega": modulo_bodega()
