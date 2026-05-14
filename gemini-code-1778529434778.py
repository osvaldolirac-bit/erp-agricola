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

# --- 1. CONFIGURACIÓN GENERAL ---
ID_CARPETA_DRIVE = "12tjxWa_RVRP5YuYd2sypjBO8bPuyMqo6" 
NOMBRE_DB = 'erp_concepcion_v6.db'
CLAVE_SEGURIDAD = "2908"

# Listas Maestras para Bodega
FAMILIAS_PRODUCTOS = [
    "FERTILIZANTE", "FERTILIZANTE FOLIAR", "HERBICIDA", "INSECTICIDA", 
    "FUNGICIDA", "BIO ESTIMULANTE", "ACARICIDA", "REGULADOR DE CRECIMIENTO",
    "ADHERENTE / MOJANTE", "OTROS"
]

CENTROS_COSTO = [
    "CEREZOS CORTE1", "CEREZOS CORTE2", "CIRUELOS", "NOGALES APARICION", 
    "NOGALES CRUZ DEL SUR", "OTROS"
]

# --- 2. UTILIDADES Y BASE DE DATOS ---
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

# --- 3. SINCRONIZACIÓN GOOGLE DRIVE (SECRETS) ---
def obtener_drive():
    try:
        if "gcp_service_account" not in st.secrets:
            return None
        info = dict(st.secrets["gcp_service_account"])
        if "private_key" in info:
            info["private_key"] = info["private_key"].replace("\\n", "\n")
        scope = ['https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(info, scope)
        gauth = GoogleAuth()
        gauth.credentials = creds
        return GoogleDrive(gauth)
    except:
        return None

def guardar_en_drive():
    try:
        drive = obtener_drive()
        if not drive: return False
        query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
        lista = drive.ListFile({'q': query}).GetList()
        f = lista[0] if lista else drive.CreateFile({'title': NOMBRE_DB, 'parents': [{'id': ID_CARPETA_DRIVE}]})
        f.SetContentFile(NOMBRE_DB)
        f.Upload()
        st.success(f"✅ Sincronizado en Drive ({datetime.now().strftime('%H:%M:%S')})")
        return True
    except:
        return False

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
        pdf.set_font("Helvetica", "B", 9)
        cols = df.columns
        w = 190 / len(cols)
        for col in cols: pdf.cell(w, 8, str(col).upper(), border=1, align="C")
        pdf.ln()
        pdf.set_font("Helvetica", "", 8)
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

# --- 5. MÓDULOS DEL SISTEMA ---

def modulo_dashboard():
    st.header("📊 Dashboard Financiero")
    conn = conectar_db()
    df_f = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente'", conn)
    conn.close()
    
    hoy = datetime.now().date()
    inicio_mes_actual = hoy.replace(day=1)
    
    total_pendiente = df_f['monto_total'].sum() if not df_f.empty else 0
    deuda_atrasada_prev = 0
    num_vencidos = 0
    if not df_f.empty:
        df_f['fv_date'] = pd.to_datetime(df_f['fecha_vencimiento']).dt.date
        deuda_atrasada_prev = df_f[df_f['fv_date'] < inicio_mes_actual]['monto_total'].sum()
        num_vencidos = len(df_f[df_f['fv_date'] < hoy])

    c1, c2 = st.columns(2)
    c1.metric("Deuda Total Pendiente", f"${f_puntos(total_pendiente)}")
    c2.metric("Documentos en Cartera", len(df_f))

    st.markdown("---")
    st.subheader("⚠️ ESTADO DE ALERTA (Críticos)")
    ca1, ca2 = st.columns(2)
    ca1.metric("Monto Vencido Meses Anteriores", f"${f_puntos(deuda_atrasada_prev)}", delta="¡Urgente!", delta_color="inverse")
    ca2.metric("Documentos Vencidos (Hoy)", num_vencidos, delta="Revisar Pagos", delta_color="inverse")
    
    st.markdown("---")
    st.subheader("📅 Proyección Mensual de Compromisos")
    cols_m = st.columns(4)
    meses_n = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]
    for i in range(4):
        target_date = (datetime.now().replace(day=1) + timedelta(days=i*31)).replace(day=1)
        m, a = target_date.month, target_date.year
        val_m = 0
        if not df_f.empty:
            df_f['dt'] = pd.to_datetime(df_f['fecha_vencimiento'])
            val_m = df_f[(df_f['dt'].dt.month == m) & (df_f['dt'].dt.year == a)]['monto_total'].sum()
        cols_m[i].metric(f"{meses_n[m-1]} {a}", f"${f_puntos(val_m)}")

def modulo_compras():
    st.header("📦 Compras e Insumos")
    t1, t2, t3 = st.tabs(["➕ Factura Insumos", "💸 Gasto Vario", "🔍 Historial / Gestionar"])
    
    with t1:
        c1, c2 = st.columns(2)
        nro, prov = c1.text_input("N° Factura"), c1.text_input("Proveedor")
        f_c, f_v = c2.date_input("Emisión"), c2.date_input("Vencimiento")
        conn = conectar_db()
        df_inv = pd.read_sql_query("SELECT id, producto FROM inventario ORDER BY producto", conn)
        conn.close()
        
        if not df_inv.empty:
            cp1, cp2, cp3, cp4 = st.columns([3,1,1,1])
            p_sel = cp1.selectbox("Insumo", df_inv['id'].astype(str) + " - " + df_inv['producto'])
            cant, prec = cp2.number_input("Cant.", min_value=0.1), cp3.number_input("Neto Un.", min_value=0.0)
            if cp4.button("➕ Agregar"):
                if 'carrito' not in st.session_state: st.session_state['carrito'] = []
                st.session_state['carrito'].append({'id': int(p_sel.split(" - ")[0]), 'nombre': p_sel.split(" - ")[1], 'cantidad': cant, 'precio': prec, 'total': cant * prec})
                st.rerun()
        
        if st.session_state.get('carrito'):
            df_c = pd.DataFrame(st.session_state['carrito'])
            st.table(df_c[['nombre', 'cantidad', 'precio', 'total']])
            neto = df_c['total'].sum()
            m_final = st.number_input("Total Final Factura (con IVA)", value=float(neto*1.19))
            if st.button("💾 GUARDAR FACTURA COMPLETA"):
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_neto, monto_total) VALUES (?,?,?,?,?,?)", (nro, prov, f_c, f_v, neto, m_final))
                for i in st.session_state['carrito']:
                    cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (i['cantidad'], i['id']))
                conn.commit(); conn.close(); guardar_en_drive()
                st.session_state['carrito'] = []; st.rerun()

    with t2:
        with st.form("gasto_directo"):
            gp, gd = st.text_input("Proveedor"), st.text_input("N° Documento")
            gm, gf = st.number_input("Monto Total", min_value=0.0), st.date_input("Fecha Gasto")
            g_con = st.text_area("Concepto / Detalle")
            if st.form_submit_button("💾 GUARDAR GASTO VARIO"):
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, concepto, estado) VALUES (?,?,?,?,?,?,?,?)", (gd, gp, gf, gf, gm, 'Gasto Vario', g_con, 'Pendiente'))
                conn.commit(); conn.close(); guardar_en_drive(); st.rerun()

    with t3:
        conn = conectar_db()
        df_h = pd.read_sql_query("SELECT * FROM facturas ORDER BY fecha_compra DESC", conn)
        st.dataframe(df_h, use_container_width=True)
        if not df_h.empty:
            st.download_button("📥 PDF Historial", descargar_pdf(df_h, "HISTORIAL COMPRAS"), "historial.pdf")
            st.divider()
            sel_id = st.selectbox("ID a gestionar", df_h['id'])
            row = df_h[df_h['id'] == sel_id].iloc[0]
            cm1, cm2 = st.columns(2)
            with cm1:
                with st.expander("📝 MODIFICAR"):
                    m_nro = st.text_input("N° Doc", row['nro_documento'])
                    m_monto = st.number_input("Monto", value=float(row['monto_total']))
                    cl_m = st.text_input("Clave Seguridad", type="password", key="clm")
                    if st.button("CONFIRMAR CAMBIO"):
                        if cl_m == CLAVE_SEGURIDAD:
                            conn.execute("UPDATE facturas SET nro_documento=?, monto_total=? WHERE id=?", (m_nro, m_monto, sel_id))
                            conn.commit(); guardar_en_drive(); st.rerun()
            with cm2:
                with st.expander("🗑️ ELIMINAR"):
                    cl_e = st.text_input("Clave Seguridad", type="password", key="cle")
                    if st.button("CONFIRMAR BORRADO"):
                        if cl_e == CLAVE_SEGURIDAD:
                            conn.execute("DELETE FROM facturas WHERE id=?", (sel_id,))
                            conn.commit(); guardar_en_drive(); st.rerun()
        conn.close()

def modulo_tesoreria():
    st.header("💸 Cuentas por Pagar")
    tp1, tp2, tp3 = st.tabs(["🔴 Pendientes", "🏢 Por Proveedor", "📅 Por Vencimiento"])
    conn = conectar_db()
    with tp1:
        df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' ORDER BY fecha_vencimiento ASC", conn)
        if not df_p.empty:
            def style_v(row):
                v = pd.to_datetime(row['fecha_vencimiento']).date()
                return ['background-color: #ffcccc' if v < datetime.now().date() else '' for _ in row]
            st.dataframe(df_p.style.apply(style_v, axis=1).format({"monto_total": "${:,.0f}"}), use_container_width=True)
            st.metric("Total Deuda en Pantalla", f"${f_puntos(df_p['monto_total'].sum())}")
            st.download_button("📥 PDF Pendientes", descargar_pdf(df_p, "PENDIENTES GENERALES"), "pendientes.pdf")
            st.divider()
            c1, c2 = st.columns(2)
            id_p = c1.selectbox("ID Pago", df_p['id'])
            met = c2.selectbox("Medio de Pago", ["Transferencia", "Cheque", "Efectivo", "Otro"])
            if st.button("💰 MARCAR COMO PAGADO"):
                conn.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (met, datetime.now().date(), id_p))
                conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
    with tp3:
        v1, v2 = st.date_input("Desde"), st.date_input("Hasta", datetime.now().date()+timedelta(days=30))
        df_v = pd.read_sql_query(f"SELECT nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' AND fecha_vencimiento BETWEEN '{v1}' AND '{v2}'", conn)
        st.dataframe(df_v, use_container_width=True)
        if not df_v.empty:
            st.download_button("📥 PDF Rango", descargar_pdf(df_v, f"RANGO {v1} al {v2}"), "vencimientos.pdf")
    conn.close()

def modulo_bodega():
    st.header("🚜 Gestión de Bodega")
    tb1, tb2 = st.tabs(["📊 Stock Actual", "🔄 Movimiento (Entrada/Salida)"])
    with tb1:
        conn = conectar_db()
        df = pd.read_sql_query("SELECT * FROM inventario ORDER BY producto ASC", conn)
        conn.close()
        st.dataframe(df, use_container_width=True)
        with st.expander("➕ AGREGAR NUEVO INSUMO AL CATÁLOGO"):
            with st.form("nuevo_insumo"):
                nn = st.text_input("Nombre del Producto")
                ff = st.selectbox("Familia / Categoría", FAMILIAS_PRODUCTOS)
                sm = st.number_input("Stock Mínimo Alerta", value=0.0)
                if st.form_submit_button("REGISTRAR EN CATÁLOGO"):
                    conn = conectar_db()
                    conn.execute("INSERT INTO inventario (producto, familia, stock, stock_minimo) VALUES (?,?,?,?)", (nn, ff, 0, sm))
                    conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
    with tb2:
        tipo = st.radio("Tipo de Operación", ["Salida (Aplicación en Campo)", "Entrada (Compra/Ajuste)"])
        with st.form("registro_mov"):
            conn = conectar_db()
            prs = pd.read_sql_query("SELECT id, producto FROM inventario ORDER BY producto", conn)
            conn.close()
            ps = st.selectbox("Seleccione Insumo", prs['id'].astype(str) + " - " + prs['producto'])
            cm = st.number_input("Cantidad", min_value=0.1)
            cc = st.selectbox("Destino / Cuartel", CENTROS_COSTO) if "Salida" in tipo else "BODEGA CENTRAL"
            if st.form_submit_button("REGISTRAR MOVIMIENTO"):
                ip = int(ps.split(" - ")[0])
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo) VALUES (?,?,?,?,?)", (ip, tipo, cm, datetime.now().date(), cc))
                f = 1 if "Entrada" in tipo else -1
                cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (cm*f, ip))
                conn.commit(); conn.close(); guardar_en_drive(); st.rerun()

# --- 6. INICIALIZACIÓN Y NAVEGACIÓN ---
st.set_page_config(page_title="AGRICOLA LA CONCEPCION ERP", page_icon="🚜", layout="wide")

if 'db_sincronizada' not in st.session_state:
    descargar_de_drive()
    st.session_state['db_sincronizada'] = True

inicializar_db()

with st.sidebar:
    st.title("LA CONCEPCIÓN ERP")
    if "gcp_service_account" in st.secrets:
        st.success("☁️ Drive: CONECTADO")
        if st.button("🚀 Sincronizar Ahora"): guardar_en_drive()
    else:
        st.warning("⚠️ Drive: DESCONECTADO")
    menu = st.radio("Menú de Navegación", ["🏠 Dashboard", "📦 Compras", "💸 Tesorería", "🚜 Bodega"])

if menu == "🏠 Dashboard": modulo_dashboard()
elif menu == "📦 Compras": modulo_compras()
elif menu == "💸 Tesorería": modulo_tesoreria()
elif menu == "🚜 Bodega": modulo_bodega()
