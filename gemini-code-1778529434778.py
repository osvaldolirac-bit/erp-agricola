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

# --- 1. CONFIGURACIÓN Y CONSTANTES ---
ID_CARPETA_DRIVE = "12tjxWa_RVRP5YuYd2sypjBO8bPuyMqo6" 
NOMBRE_DB = 'erp_concepcion_v6.db'
CLAVE_SEGURIDAD = "2908"

# Fecha Global
hoy = datetime.now().date()

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

# --- 3. SINCRONIZACIÓN GOOGLE DRIVE ---
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
        st.success(f"✅ Sincronizado en Drive ({datetime.now().strftime('%H:%M:%S')})")
        return True
    except: return False

def descargar_de_drive():
    try:
        drive = obtener_drive()
        if not drive: return False
        query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
        lista = drive.ListFile({'q': query}).GetList()
        if lista: lista[0].GetContentFile(NOMBRE_DB); return True
    except: return False

# --- 4. GENERADOR DE PDF ---
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
                if "monto" in df.columns[i].lower() or "total" in df.columns[i].lower():
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
    st.header("📊 Dashboard Financiero")
    conn = conectar_db(); df_f = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente'", conn); conn.close()
    inicio_mes = hoy.replace(day=1)
    total_deuda = df_f['monto_total'].sum() if not df_f.empty else 0
    atrasado = 0
    if not df_f.empty:
        df_f['fv'] = pd.to_datetime(df_f['fecha_vencimiento']).dt.date
        atrasado = df_f[df_f['fv'] < inicio_mes]['monto_total'].sum()
    
    c1, c2 = st.columns(2)
    c1.metric("Deuda Pendiente", f"${f_puntos(total_deuda)}")
    c2.metric("Vencido Meses Prev.", f"${f_puntos(atrasado)}", delta="Urgente", delta_color="inverse")

    st.subheader("📅 Proyección Mensual")
    cols = st.columns(4); meses_n = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]
    for i in range(4):
        f_t = (datetime.now().replace(day=1) + timedelta(days=i*31)).replace(day=1)
        m, a = f_t.month, f_t.year
        v = 0
        if not df_f.empty:
            df_f['dt'] = pd.to_datetime(df_f['fecha_vencimiento'])
            v = df_f[(df_f['dt'].dt.month == m) & (df_f['dt'].dt.year == a)]['monto_total'].sum()
        cols[i].metric(f"{meses_n[m-1]} {a}", f"${f_puntos(v)}")

def modulo_compras():
    st.header("📦 Compras")
    t1, t2, t3 = st.tabs(["➕ Factura Insumos", "💸 Gasto Vario", "🔍 Historial / Modificar"])
    with t1:
        c1, c2 = st.columns(2)
        nro, prov = c1.text_input("N° Documento"), c1.text_input("Proveedor")
        f_e, f_v = c2.date_input("Emisión"), c2.date_input("Vencimiento")
        conn = conectar_db(); df_i = pd.read_sql_query("SELECT id, producto FROM inventario ORDER BY producto", conn); conn.close()
        if not df_i.empty:
            ci1, ci2, ci3, ci4 = st.columns([3,1,1,1])
            p_s = ci1.selectbox("Insumo", df_i['id'].astype(str) + " - " + df_i['producto'])
            cant, prec = ci2.number_input("Cant", min_value=0.1), ci3.number_input("Neto Un", min_value=0.0)
            if ci4.button("➕"):
                if 'car' not in st.session_state: st.session_state['car'] = []
                st.session_state['car'].append({'id': int(p_s.split(" - ")[0]), 'n': p_s.split(" - ")[1], 'c': cant, 'p': prec, 't': cant*prec})
                st.rerun()
        if st.session_state.get('car'):
            df_c = pd.DataFrame(st.session_state['car']); st.table(df_c)
            total = st.number_input("Total Factura (IVA)", value=float(df_c['t'].sum()*1.19))
            if st.button("💾 GUARDAR"):
                conn = conectar_db(); cur = conn.cursor()
                cur.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total) VALUES (?,?,?,?,?)", (nro, prov, f_e, f_v, total))
                for i in st.session_state['car']: cur.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (i['c'], i['id']))
                conn.commit(); conn.close(); guardar_en_drive(); st.session_state['car'] = []; st.rerun()
    with t2:
        with st.form("gv"):
            p, n, m = st.text_input("Proveedor"), st.text_input("N° Doc"), st.number_input("Monto")
            if st.form_submit_button("💾 GUARDAR GASTO"):
                conn = conectar_db(); conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo) VALUES (?,?,?,?,?,?)", (n, p, hoy, hoy, m, 'Gasto Vario'))
                conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
    with t3:
        conn = conectar_db(); df_h = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_compra, monto_total, tipo FROM facturas ORDER BY fecha_compra DESC", conn)
        st.dataframe(df_h, use_container_width=True)
        if not df_h.empty:
            st.divider()
            # SECCIÓN DE MODIFICACIÓN/ELIMINACIÓN
            c_ed1, c_ed2 = st.columns(2)
            id_sel = c_ed1.selectbox("ID a Gestionar", df_h['id'])
            row = df_h[df_h['id'] == id_sel].iloc[0]
            with st.expander("📝 MODIFICAR DOCUMENTO"):
                new_nro = st.text_input("Nuevo N° Doc", row['nro_documento'])
                new_monto = st.number_input("Nuevo Monto", value=float(row['monto_total']))
                cl_m = st.text_input("Clave Seguridad", type="password", key="m")
                if st.button("ACTUALIZAR"):
                    if cl_m == CLAVE_SEGURIDAD:
                        conn.execute("UPDATE facturas SET nro_documento=?, monto_total=? WHERE id=?", (new_nro, new_monto, id_sel))
                        conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
                    else: st.error("Clave Incorrecta")
            with st.expander("🗑️ ELIMINAR"):
                cl_e = st.text_input("Clave Seguridad", type="password", key="e")
                if st.button("ELIMINAR DEFINITIVO"):
                    if cl_e == CLAVE_SEGURIDAD:
                        conn.execute("DELETE FROM facturas WHERE id=?", (id_sel,))
                        conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
                    else: st.error("Clave Incorrecta")
        conn.close()

def modulo_tesoreria():
    st.header("💸 Tesorería")
    tp1, tp2, tp3 = st.tabs(["🔴 Pendientes General", "🏢 Por Proveedor", "📅 Por Rango"])
    conn = conectar_db()
    
    with tp1:
        df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' ORDER BY fecha_vencimiento ASC", conn)
        if not df_p.empty:
            st.dataframe(df_p.format({"monto_total": "${:,.0f}"}), use_container_width=True)
            st.metric("Deuda Total", f"${f_puntos(df_p['monto_total'].sum())}")
            st.download_button("📥 PDF Pendientes", descargar_pdf(df_p, "PENDIENTES GENERALES"), "pendientes.pdf")
            c1, c2 = st.columns(2); id_p = c1.selectbox("ID Pago", df_p['id']); met = c2.selectbox("Medio", ["Transferencia", "Cheque", "Efectivo"])
            if st.button("💰 PAGAR"):
                conn.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (met, hoy, id_p))
                conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
    
    with tp2:
        # CONSULTA POR PROVEEDOR
        df_prov = pd.read_sql_query("SELECT DISTINCT proveedor FROM facturas WHERE estado='Pendiente'", conn)
        if not df_prov.empty:
            prov_sel = st.selectbox("Seleccione Proveedor", df_prov['proveedor'])
            df_filtro = pd.read_sql_query(f"SELECT nro_documento, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' AND proveedor='{prov_sel}'", conn)
            st.dataframe(df_filtro, use_container_width=True)
            st.metric(f"Deuda con {prov_sel}", f"${f_puntos(df_filtro['monto_total'].sum())}")
            st.download_button(f"📥 PDF {prov_sel}", descargar_pdf(df_filtro, f"PENDIENTES: {prov_sel}"), f"pago_{prov_sel}.pdf")
        else: st.info("No hay deudas pendientes.")

    with tp3:
        f1, f2 = st.date_input("Desde"), st.date_input("Hasta", hoy + timedelta(days=30))
        df_r = pd.read_sql_query(f"SELECT nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' AND fecha_vencimiento BETWEEN '{f1}' AND '{f2}'", conn)
        st.dataframe(df_r, use_container_width=True)
    conn.close()

def modulo_bodega():
    st.header("🚜 Bodega")
    tb1, tb2 = st.tabs(["📊 Stock", "🔄 Movimientos"])
    with tb1:
        conn = conectar_db(); df = pd.read_sql_query("SELECT * FROM inventario ORDER BY producto ASC", conn); conn.close()
        st.dataframe(df, use_container_width=True)
        with st.expander("➕ NUEVO INSUMO"):
            with st.form("ni"):
                n, f = st.text_input("Nombre"), st.selectbox("Familia", FAMILIAS_PRODUCTOS)
                if st.form_submit_button("CREAR"):
                    conn = conectar_db(); conn.execute("INSERT INTO inventario (producto, familia, stock) VALUES (?,?,0)", (n, f)); conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
    with tb2:
        t_m = st.radio("Tipo", ["Salida (Campo)", "Entrada"])
        with st.form("m"):
            conn = conectar_db(); df_i = pd.read_sql_query("SELECT id, producto FROM inventario ORDER BY producto", conn); conn.close()
            ps = st.selectbox("Insumo", df_i['id'].astype(str) + " - " + df_i['producto'])
            ct = st.number_input("Cantidad", min_value=0.1)
            cc = st.selectbox("Cuartel", CENTROS_COSTO) if t_m == "Salida (Campo)" else "BODEGA"
            if st.form_submit_button("REGISTRAR"):
                ip = int(ps.split(" - ")[0]); conn = conectar_db(); cur = conn.cursor()
                cur.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo) VALUES (?,?,?,?,?)", (ip, t_m, ct, hoy, cc))
                f = 1 if "Entrada" in t_m else -1
                cur.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (ct*f, ip))
                conn.commit(); conn.close(); guardar_en_drive(); st.rerun()

# --- NAVEGACIÓN ---
st.set_page_config(page_title="AGRICOLA LA CONCEPCION ERP", page_icon="🚜", layout="wide")
if 'sinc' not in st.session_state: descargar_de_drive(); st.session_state['sinc'] = True
inicializar_db()
with st.sidebar:
    st.title("LA CONCEPCIÓN ERP")
    if "gcp_service_account" in st.secrets: st.success("☁️ Drive: CONECTADO")
    menu = st.radio("Menú", ["🏠 Dashboard", "📦 Compras", "💸 Tesorería", "🚜 Bodega"])
    if st.button("🚀 Sincronizar"): guardar_en_drive()

if menu == "🏠 Dashboard": modulo_dashboard()
elif menu == "📦 Compras": modulo_compras()
elif menu == "💸 Tesorería": modulo_tesoreria()
elif menu == "🚜 Bodega": modulo_bodega()
