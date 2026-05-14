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
METODOS_PAGO = ["TRANSFERENCIA", "CHEQUE", "EFECTIVO", "TARJETA", "OTRO"]

# --- 2. MOTOR DRIVE (ANTI-QUOTA) ---
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
            st.success("✅ Sincronizado con Drive.")
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
    conn.commit(); conn.close()

# --- 4. UTILIDADES ---
def f_puntos(v):
    try: return f"{int(round(float(v))):,}".replace(",", ".")
    except: return "0"

def generar_pdf(df, titulo):
    pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, f"LA CONCEPCIÓN - {titulo}", ln=True, align="C")
    pdf.set_font("Arial", "B", 8); pdf.ln(5)
    cols = df.columns; w = 190 / len(cols)
    for col in cols: pdf.cell(w, 8, str(col).upper(), border=1)
    pdf.ln(); pdf.set_font("Arial", "", 7)
    for _, row in df.iterrows():
        for item in row: pdf.cell(w, 7, str(item)[:20], border=1)
        pdf.ln()
    return pdf.output(dest="S").encode("latin-1")

# --- 5. MÓDULOS ---

def modulo_dashboard():
    st.title("🏠 Dashboard")
    conn = conectar_db()
    df_p = pd.read_sql_query("SELECT monto_total, fecha_vencimiento FROM facturas WHERE estado='Pendiente' AND tipo='Factura'", conn)
    
    deuda_t = df_p['monto_total'].sum() if not df_p.empty else 0
    vencidos = df_p[pd.to_datetime(df_p['fecha_vencimiento']).dt.date < hoy] if not df_p.empty else pd.DataFrame()
    
    c1, c2, c3 = st.columns(3)
    c1.metric("DEUDA TOTAL", f"${f_puntos(deuda_t)}")
    c2.metric("DOCUMENTOS VENCIDOS", len(vencidos), delta=f"${f_puntos(vencidos['monto_total'].sum())}" if not vencidos.empty else "0", delta_color="inverse")
    
    st.subheader("📅 Proyección de Pagos (Próximos 4 Meses)")
    if not df_p.empty:
        df_p['mes'] = pd.to_datetime(df_p['fecha_vencimiento']).dt.strftime('%Y-%m')
        proy = df_p.groupby('mes')['monto_total'].sum().reset_index().sort_values('mes').head(4)
        st.bar_chart(proy.set_index('mes'))
    
    st.divider()
    modulo_costos()
    conn.close()

def modulo_compras():
    st.header("📦 Compras e Insumos")
    t1, t2, t3 = st.tabs(["➕ Factura Insumo", "💸 Gasto Vario", "🔍 Historial"])
    conn = conectar_db()
    
    with t1:
        c1, c2 = st.columns(2)
        nro, prov = c1.text_input("N° Factura"), c1.text_input("Proveedor")
        f_c, f_v = c2.date_input("Fecha Emisión"), c2.date_input("Vencimiento")
        df_inv = pd.read_sql_query("SELECT id, producto FROM inventario", conn)
        ps = st.selectbox("Seleccione Insumo", df_inv['id'].astype(str) + " - " + df_inv['producto']) if not df_inv.empty else None
        cant, neto = st.number_input("Cantidad", 0.0), st.number_input("Precio Neto Unitario", 0.0)
        
        if st.button("💾 Guardar Factura"):
            total = (cant * neto) * 1.19
            conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo) VALUES (?,?,?,?,?,?)", (nro, prov, f_c, f_v, total, 'Factura'))
            if ps:
                pid = int(ps.split(" - ")[0])
                cur = conn.execute("SELECT stock, precio_medio FROM inventario WHERE id=?", (pid,)).fetchone()
                nuevo_pmp = ((cur[0]*cur[1]) + (cant*neto)) / (cur[0]+cant) if (cur[0]+cant) > 0 else neto
                conn.execute("UPDATE inventario SET stock=stock+?, precio_medio=? WHERE id=?", (cant, nuevo_pmp, pid))
            conn.commit(); guardar_en_drive(); st.rerun()

    with t2:
        st.subheader("Gasto Directo a Cuartel (Prorrateado)")
        g_prov = st.text_input("Proveedor Gasto", key="g_p")
        g_neto = st.number_input("Monto Neto Total", 0.0, key="g_m")
        st.write("Seleccione Cuarteles (Checkboxes):")
        cols_c = st.columns(3)
        ccs_check = []
        for i, cc in enumerate(CENTROS_COSTO):
            if cols_c[i % 3].checkbox(cc, key=f"cg_{cc}"): ccs_check.append(cc)
        
        if st.button("💾 Grabar Gasto") and ccs_check:
            monto_p = g_neto / len(ccs_check)
            for c in ccs_check:
                conn.execute("INSERT INTO facturas (proveedor, monto_total, tipo, centro_costo, monto_imputado, estado, fecha_compra) VALUES (?,?,?,?,?,?,?)", (g_prov, 0, 'Gasto Vario', c, monto_p, 'Imputado', hoy))
            conn.commit(); guardar_en_drive(); st.rerun()

    with t3:
        st.subheader("Historial y Rango de Fechas")
        c1, c2 = st.columns(2)
        f_desde = c1.date_input("Desde", hoy - timedelta(days=30))
        f_hasta = c2.date_input("Hasta", hoy)
        df_h = pd.read_sql_query(f"SELECT * FROM facturas WHERE fecha_compra BETWEEN '{f_desde}' AND '{f_hasta}' ORDER BY id DESC", conn)
        st.dataframe(df_h, use_container_width=True)
        
        if not df_h.empty:
            st.download_button("📥 Descargar Historial PDF", generar_pdf(df_h, "HISTORIAL"), "historial.pdf")
            st.divider()
            id_sel = st.selectbox("ID para Acción", df_h['id'])
            pw_check = st.text_input("Clave Maestra para Modificar/Eliminar", type="password")
            col_b1, col_b2 = st.columns(2)
            if col_b1.button("🗑️ Eliminar Registro") and pw_check == CLAVE_MAESTRA:
                conn.execute("DELETE FROM facturas WHERE id=?", (id_sel,))
                conn.commit(); guardar_en_drive(); st.rerun()
            if col_b2.button("✏️ Modificar (Monto)") and pw_check == CLAVE_MAESTRA:
                nuevo_m = st.number_input("Nuevo Monto Total", 0.0)
                conn.execute("UPDATE facturas SET monto_total=? WHERE id=?", (nuevo_m, id_sel))
                conn.commit(); guardar_en_drive(); st.rerun()
    conn.close()

def modulo_bodega():
    st.header("🚜 Bodega")
    t1, t2, t3, t4 = st.tabs(["📊 Stock", "🔄 Salidas", "📥 Entradas", "➕ Nuevo Item"])
    conn = conectar_db()
    
    with t1:
        df_s = pd.read_sql_query("SELECT id, producto, familia, stock, precio_medio FROM inventario", conn)
        st.dataframe(df_s, use_container_width=True)
        if not df_s.empty: st.download_button("📥 PDF Inventario", generar_pdf(df_s, "STOCK"), "stock.pdf")

    with t2:
        df_i = pd.read_sql_query("SELECT id, producto, stock, precio_medio FROM inventario WHERE stock > 0", conn)
        if not df_i.empty:
            ps = st.selectbox("Insumo", df_i['id'].astype(str) + " - " + df_i['producto'], key="b_s1")
            cant_s = st.number_input("Cantidad a sacar", 0.0, key="b_s2")
            st.write("Destinos (Checkboxes):")
            cols_s = st.columns(3)
            ccs_s = []
            for i, cc in enumerate(CENTROS_COSTO):
                if cols_s[i % 3].checkbox(cc, key=f"sal_{cc}"): ccs_s.append(cc)
            
            if st.button("✅ Confirmar Salida") and ccs_s:
                pid = int(ps.split(" - ")[0])
                pmp = df_i[df_i['id']==pid]['precio_medio'].values[0]
                val_total = cant_s * pmp
                for c in ccs_s:
                    conn.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, centro_costo, valor_imputado, fecha) VALUES (?,?,?,?,?,?)", (pid, 'Salida', cant_s/len(ccs_s), c, val_total/len(ccs_s), hoy))
                conn.execute("UPDATE inventario SET stock=stock-? WHERE id=?", (cant_s, pid))
                conn.commit(); guardar_en_drive(); st.rerun()

    with t3:
        st.subheader("Entrada Manual de Stock")
        df_e = pd.read_sql_query("SELECT id, producto FROM inventario", conn)
        if not df_e.empty:
            ps_e = st.selectbox("Producto", df_e['id'].astype(str) + " - " + df_e['producto'], key="b_e1")
            cant_e = st.number_input("Cantidad Entrada", 0.0, key="b_e2")
            if st.button("📥 Sumar a Stock"):
                conn.execute("UPDATE inventario SET stock=stock+? WHERE id=?", (cant_e, int(ps_e.split(" - ")[0])))
                conn.commit(); guardar_en_drive(); st.rerun()

    with t4:
        with st.form("ni"):
            n, f = st.text_input("Nombre"), st.selectbox("Familia", FAMILIAS_PRODUCTOS)
            p_ini = st.number_input("PMP Inicial (Neto)", 0.0)
            if st.form_submit_button("Crear Insumo"):
                conn.execute("INSERT INTO inventario (producto, familia, precio_medio, stock) VALUES (?,?,?,0)", (n, f, p_ini))
                conn.commit(); st.rerun()

    st.divider()
    st.subheader("🔍 Consulta por Cuartel")
    cc_q = st.selectbox("Ver movimientos de:", CENTROS_COSTO)
    df_q = pd.read_sql_query(f"SELECT * FROM movimientos WHERE centro_costo='{cc_q}'", conn)
    st.dataframe(df_q, use_container_width=True)
    conn.close()

def modulo_tesoreria():
    st.header("💰 Tesorería y Pagos")
    conn = conectar_db()
    df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' AND tipo='Factura' ORDER BY fecha_vencimiento ASC", conn)
    
    if not df_p.empty:
        st.subheader("Facturas Pendientes")
        st.dataframe(df_p.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
        col1, col2 = st.columns(2)
        id_pagar = col1.selectbox("Seleccione ID a Pagar", df_p['id'])
        metodo = col2.selectbox("Método de Pago", METODOS_PAGO)
        if st.button("💰 Registrar Pago"):
            conn.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (metodo, hoy, id_pagar))
            conn.commit(); guardar_en_drive(); st.rerun()
    else:
        st.success("✅ No hay facturas pendientes de pago.")

    st.divider()
    st.subheader("📜 Historial de Pagos")
    df_h_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, monto_total, metodo_pago, fecha_pago FROM facturas WHERE estado='Pagado'", conn)
    st.dataframe(df_h_p, use_container_width=True)
    conn.close()

def modulo_costos():
    st.header("💰 Resumen de Costos")
    conn = conectar_db()
    q = """ SELECT UPPER(centro_costo) as Cuartel, SUM(valor_imputado) as Total, 'Insumo Bodega' as Tipo FROM movimientos GROUP BY Cuartel
            UNION ALL
            SELECT UPPER(centro_costo) as Cuartel, SUM(monto_imputado) as Total, 'Gasto Directo' as Tipo FROM facturas WHERE tipo='Gasto Vario' GROUP BY Cuartel """
    df_c = pd.read_sql_query(q, conn)
    if not df_c.empty:
        res = df_c.groupby('Cuartel')['Total'].sum().reset_index()
        st.table(res.style.format({"Total": "${:,.0f}"}))
        st.download_button("📥 Descargar Reporte Costos PDF", generar_pdf(res, "COSTOS"), "costos.pdf")
    else:
        st.warning("No hay datos de costos registrados.")
    conn.close()

# --- 6. NAVEGACIÓN ---
st.set_page_config(page_title="ERP Agrícola v22.0", layout="wide")
inicializar_db()
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False

if not st.session_state['logged_in']:
    st.title("🚜 ERP LA CONCEPCIÓN")
    p = st.text_input("Clave Maestra", type="password")
    if st.button("Entrar"):
        if p == CLAVE_MAESTRA or p == "9083": st.session_state['logged_in'] = True; st.rerun()
else:
    if 'init' not in st.session_state: descargar_de_drive(); st.session_state['init'] = True
    with st.sidebar:
        st.title("MENÚ")
        if obtener_drive(): st.success("Nube Conectada")
        menu = st.radio("", ["🏠 Dashboard", "📦 Compras", "🚜 Bodega", "💰 Tesorería", "📊 COSTOS"])
        if st.button("🚀 Sincronizar Ahora"): guardar_en_drive()
        if st.button("🚪 Salir"): st.session_state.clear(); st.rerun()
    
    if menu == "🏠 Dashboard": modulo_dashboard()
    elif menu == "📦 Compras": modulo_compras()
    elif menu == "🚜 Bodega": modulo_bodega()
    elif menu == "💰 Tesorería": modulo_tesoreria()
    elif menu == "📊 COSTOS": modulo_costos()
