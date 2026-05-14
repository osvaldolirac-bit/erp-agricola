import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import os
import json
from fpdf import FPDF
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. CONFIGURACIÓN Y LISTAS ---
ID_CARPETA_DRIVE = "12tjxWa_RVRP5YuYd2sypjBO8bPuyMqo6" 
NOMBRE_DB = 'erp_concepcion_v6.db'
CLAVE_SEGURIDAD = "2908"

FAMILIAS_PRODUCTOS = [
    "FERTILIZANTE", "FERTILIZANTE FOLIAR", "HERBICIDA", "INSECTICIDA", 
    "FUNGICIDA", "BIO ESTIMULANTE", "ACARICIDA", "REGULADOR DE CRECIMIENTO",
    "ADHERENTE / MOJANTE", "OTROS"
]

CENTROS_COSTO = [
    "CEREZOS CORTE1", "CEREZOS CORTE2", "CIRUELOS", "NOGALES APARICION", 
    "NOGALES CRUZ DEL SUR", "OTROS"
]

# --- 2. MOTOR DE BASE DE DATOS Y UTILIDADES ---
def f_puntos(v):
    try: return f"{int(v):,}".replace(",", ".")
    except: return "0"

def conectar_db():
    return sqlite3.connect(NOMBRE_DB)

def inicializar_db():
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS facturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nro_documento TEXT, proveedor TEXT, 
        fecha_compra DATE, fecha_vencimiento DATE, monto_neto REAL, monto_total REAL, 
        estado TEXT DEFAULT 'Pendiente', tipo TEXT DEFAULT 'Factura', 
        metodo_pago TEXT, fecha_pago DATE, concepto TEXT)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS inventario (
        id INTEGER PRIMARY KEY AUTOINCREMENT, producto TEXT, familia TEXT, 
        stock REAL DEFAULT 0, stock_minimo REAL DEFAULT 0)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS movimientos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, producto_id INTEGER, tipo TEXT, 
        cantidad REAL, centro_costo TEXT, fecha DATE)""")
    conn.commit()
    conn.close()

# --- 3. CONEXIÓN DRIVE (SECRETS) ---
def obtener_drive():
    try:
        if "gcp_service_account" not in st.secrets: return None
        info = dict(st.secrets["gcp_service_account"])
        if "private_key" in info: info["private_key"] = info["private_key"].replace("\\n", "\n")
        scope = ['https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(info, scope)
        gauth = GoogleAuth(); gauth.credentials = creds
        return GoogleDrive(gauth)
    except: return None

def guardar_en_drive():
    try:
        drive = obtener_drive()
        if not drive: return False
        query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
        lista = drive.ListFile({'q': query}).GetList()
        f = lista[0] if lista else drive.CreateFile({'title': NOMBRE_DB, 'parents': [{'id': ID_CARPETA_DRIVE}]})
        f.SetContentFile(NOMBRE_DB); f.Upload()
        st.success(f"✅ Sincronizado ({datetime.now().strftime('%H:%M:%S')})")
        return True
    except Exception as e:
        st.error(f"❌ Error Drive: {e}")
        return False

def descargar_de_drive():
    try:
        drive = obtener_drive()
        if not drive: return False
        query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
        lista = drive.ListFile({'q': query}).GetList()
        if lista: lista[0].GetContentFile(NOMBRE_DB); return True
    except: return False

# --- 4. REPORTES PDF ---
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
        for col in cols: pdf.cell(w, 8, str(col).upper(), border=1, align="C")
        pdf.ln()
        pdf.set_font("Helvetica", "", 7)
        suma_total = 0
        for _, row in df.iterrows():
            for i, item in enumerate(row):
                if "monto" in df.columns[i].lower():
                    try: suma_total += float(item)
                    except: pass
                val = f_puntos(item) if isinstance(item, (int, float)) else str(item)
                pdf.cell(w, 7, val[:25], border=1)
            pdf.ln()
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(w * (len(cols)-1), 8, "TOTAL REPORTE:", border=1, align="R")
        pdf.cell(w, 8, f"${f_puntos(suma_total)}", border=1, align="L")
        return pdf.output(dest="S").encode("latin-1")
    except: return None

# --- 5. MÓDULOS ---
def modulo_dashboard():
    st.header("📊 Resumen General")
    conn = conectar_db(); df_f = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente'", conn); conn.close()
    hoy = datetime.now().date(); inicio_mes = hoy.replace(day=1)
    
    atrasado = 0; vencidos_hoy = 0
    if not df_f.empty:
        df_f['fv'] = pd.to_datetime(df_f['fecha_vencimiento']).dt.date
        atrasado = df_f[df_f['fv'] < inicio_mes]['monto_total'].sum()
        vencidos_hoy = len(df_f[df_f['fv'] < hoy])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Deuda Total", f"${f_puntos(df_f['monto_total'].sum())}")
    c2.metric("Atrasado (Meses Prev.)", f"${f_puntos(atrasado)}", delta="Crítico", delta_color="inverse")
    c3.metric("Docs. Vencidos", vencidos_hoy, delta="Alerta", delta_color="inverse")
    c4.metric("Docs. Pendientes", len(df_f))

    st.subheader("📅 Proyección de Pagos")
    cols = st.columns(4); meses = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]
    for i in range(4):
        f = (datetime.now().replace(day=1) + timedelta(days=i*31)).replace(day=1)
        m, a = f.month, f.year
        v = 0
        if not df_f.empty:
            df_f['dt'] = pd.to_datetime(df_f['fecha_vencimiento'])
            v = df_f[(df_f['dt'].dt.month == m) & (df_f['dt'].dt.year == a)]['monto_total'].sum()
        cols[i].metric(f"{meses[m-1]} {a}", f"${f_puntos(v)}")

def modulo_compras():
    st.header("📦 Compras")
    t1, t2, t3 = st.tabs(["➕ Factura Insumos", "💸 Gasto Vario", "🔍 Historial"])
    with t1:
        c1, c2 = st.columns(2)
        nro, prov = c1.text_input("N° Factura"), c1.text_input("Proveedor")
        f_c, f_v = c2.date_input("Emisión"), c2.date_input("Vencimiento")
        conn = conectar_db(); df_inv = pd.read_sql_query("SELECT id, producto FROM inventario ORDER BY producto", conn); conn.close()
        if not df_inv.empty:
            cp1, cp2, cp3, cp4 = st.columns([3,1,1,1])
            p_sel = cp1.selectbox("Insumo", df_inv['id'].astype(str) + " - " + df_inv['producto'])
            cant, prec = cp2.number_input("Cant.", min_value=0.1), cp3.number_input("Neto Un.", min_value=0.0)
            if cp4.button("➕"):
                if 'car' not in st.session_state: st.session_state['car'] = []
                st.session_state['car'].append({'id': int(p_sel.split(" - ")[0]), 'n': p_sel.split(" - ")[1], 'c': cant, 'p': prec, 't': cant*prec})
                st.rerun()
        if st.session_state.get('car'):
            df_c = pd.DataFrame(st.session_state['car'])
            st.table(df_c); neto = df_c['t'].sum()
            total = st.number_input("Total Final", value=float(neto*1.19))
            if st.button("💾 GUARDAR"):
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_neto, monto_total) VALUES (?,?,?,?,?,?)", (nro, prov, f_c, f_v, neto, total))
                for i in st.session_state['car']: cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (i['c'], i['id']))
                conn.commit(); conn.close(); guardar_en_drive(); st.session_state['car'] = []; st.rerun()
    with t2:
        with st.form("gv"):
            gp, gd = st.text_input("Proveedor"), st.text_input("N° Doc")
            gm, gf = st.number_input("Monto Total"), st.date_input("Fecha")
            if st.form_submit_button("💾 GUARDAR GASTO"):
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, estado) VALUES (?,?,?,?,?,?,?)", (gd, gp, gf, gf, gm, 'Gasto Vario', 'Pendiente'))
                conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
    with t3:
        conn = conectar_db(); df_h = pd.read_sql_query("SELECT * FROM facturas ORDER BY fecha_compra DESC", conn); conn.close()
        st.dataframe(df_h, use_container_width=True)
        if not df_h.empty:
            st.download_button("📥 PDF Historial", descargar_pdf(df_h, "HISTORIAL"), "historial.pdf")
            sel_id = st.selectbox("ID a borrar", df_h['id']); cl = st.text_input("Clave", type="password")
            if st.button("🗑️ ELIMINAR") and cl == CLAVE_SEGURIDAD:
                conn = conectar_db(); conn.execute("DELETE FROM facturas WHERE id=?", (sel_id,)); conn.commit(); conn.close(); guardar_en_drive(); st.rerun()

def modulo_tesoreria():
    st.header("💸 Pagos")
    conn = conectar_db(); df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' ORDER BY fecha_vencimiento ASC", conn); conn.close()
    if not df_p.empty:
        def style_v(row):
            return ['background-color: #ffcccc' if pd.to_datetime(row['fecha_vencimiento']).date() < datetime.now().date() else '' for _ in row]
        st.dataframe(df_p.style.apply(style_v, axis=1).format({"monto_total": "${:,.0f}"}), use_container_width=True)
        st.metric("Total Pendiente", f"${f_puntos(df_p['monto_total'].sum())}")
        st.download_button("📥 PDF Pagos", descargar_pdf(df_p, "PENDIENTES"), "pagos.pdf")
        c1, c2 = st.columns(2); id_p = c1.selectbox("ID Pago", df_p['id']); met = c2.selectbox("Medio", ["Transferencia", "Cheque", "Efectivo"])
        if st.button("💰 PAGAR"):
            conn = conectar_db(); conn.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (met, datetime.now().date(), id_p)); conn.commit(); conn.close(); guardar_en_drive(); st.rerun()

def modulo_bodega():
    st.header("🚜 Bodega")
    t1, t2 = st.tabs(["📊 Stock", "🔄 Movimiento"])
    with t1:
        conn = conectar_db(); df = pd.read_sql_query("SELECT * FROM inventario ORDER BY producto ASC", conn); conn.close()
        st.dataframe(df, use_container_width=True)
        with st.expander("➕ NUEVO INSUMO"):
            with st.form("ni"):
                n, f = st.text_input("Nombre"), st.selectbox("Familia", FAMILIAS_PRODUCTOS)
                if st.form_submit_button("CREAR"):
                    conn = conectar_db(); conn.execute("INSERT INTO inventario (producto, familia, stock) VALUES (?,?,0)", (n, f)); conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
    with t2:
        tipo = st.radio("Tipo", ["Salida (Campo)", "Entrada"])
        with st.form("m"):
            conn = conectar_db(); prs = pd.read_sql_query("SELECT id, producto FROM inventario ORDER BY producto", conn); conn.close()
            ps = st.selectbox("Insumo", prs['id'].astype(str) + " - " + prs['producto'])
            cant = st.number_input("Cantidad", min_value=0.1)
            cc = st.selectbox("Cuartel", CENTROS_COSTO) if "Salida" in tipo else "BODEGA"
            if st.form_submit_button("REGISTRAR"):
                ip = int(ps.split(" - ")[0]); conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo) VALUES (?,?,?,?,?)", (ip, tipo, cant, datetime.now().date(), cc))
                f = 1 if "Entrada" in tipo else -1
                cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (cant*f, ip))
                conn.commit(); conn.close(); guardar_en_drive(); st.rerun()

# --- 6. NAVEGACIÓN ---
st.set_page_config(page_title="AGRICOLA LA CONCEPCION ERP", page_icon="🚜", layout="wide")
if 'sync' not in st.session_state: descargar_de_drive(); st.session_state['sync'] = True
inicializar_db()

with st.sidebar:
    st.title("LA CONCEPCIÓN ERP")
    if "gcp_service_account" in st.secrets:
        st.success("☁️ Drive: CONECTADO")
        if st.button("🚀 Sincronizar Ahora"): guardar_en_drive()
    else: st.warning("⚠️ Drive: DESCONECTADO")
    m = st.radio("Menú", ["🏠 Dashboard", "📦 Compras", "💸 Tesorería", "🚜 Bodega"])

if m == "🏠 Dashboard": modulo_dashboard()
elif m == "📦 Compras": modulo_compras()
elif m == "💸 Tesorería": modulo_tesoreria()
elif m == "🚜 Bodega": modulo_bodega()
