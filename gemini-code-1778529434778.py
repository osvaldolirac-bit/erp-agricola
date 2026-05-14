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
    # Tabla Facturas: Compras y Gastos
    cursor.execute("""CREATE TABLE IF NOT EXISTS facturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nro_documento TEXT, proveedor TEXT, 
        fecha_compra DATE, fecha_vencimiento DATE, monto_neto REAL, monto_total REAL, 
        estado TEXT DEFAULT 'Pendiente', tipo TEXT DEFAULT 'Factura', 
        metodo_pago TEXT, fecha_pago DATE, concepto TEXT)""")
    # Tabla Inventario: Catálogo y Stock
    cursor.execute("""CREATE TABLE IF NOT EXISTS inventario (
        id INTEGER PRIMARY KEY AUTOINCREMENT, producto TEXT, familia TEXT, 
        stock REAL DEFAULT 0, stock_minimo REAL DEFAULT 0)""")
    # Tabla Movimientos: Historial de aplicaciones
    cursor.execute("""CREATE TABLE IF NOT EXISTS movimientos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, producto_id INTEGER, tipo TEXT, 
        cantidad REAL, centro_costo TEXT, fecha DATE)""")
    conn.commit()
    conn.close()

# --- 3. SINCRONIZACIÓN GOOGLE DRIVE (SISTEMA SECRETS) ---
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
    except Exception as e:
        st.error(f"❌ Error al sincronizar: {e}")
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

# --- 4. GENERADOR DE REPORTES PDF ---
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
        # Encabezados
        cols = df.columns
        w = 190 / len(cols)
        for col in cols: pdf.cell(w, 8, str(col).upper(), border=1, align="C")
        pdf.ln()
        # Datos
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
        # Total al final
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(w * (len(cols)-1), 8, "TOTAL REPORTE:", border=1, align="R")
        pdf.cell(w, 8, f"${f_puntos(suma_total)}", border=1, align="L")
        return pdf.output(dest="S").encode("latin-1")
    except: return None

# --- 5. MÓDULO DASHBOARD ---
def modulo_dashboard():
    st.header("📊 Dashboard de Gestión")
    conn = conectar_db()
    df_f = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente'", conn)
    conn.close()
    
    hoy = datetime.now().date()
    inicio_mes = hoy.replace(day=1)
    
    total_deuda = df_f['monto_total'].sum() if not df_f.empty else 0
    atrasado = 0
    num_vencidos = 0
    
    if not df_f.empty:
        df_f['fv'] = pd.to_datetime(df_f['fecha_vencimiento']).dt.date
        atrasado = df_f[df_f['fv'] < inicio_mes]['monto_total'].sum()
        num_vencidos = len(df_f[df_f['fv'] < hoy])

    c1, c2, c3 = st.columns(3)
    c1.metric("Deuda Total Pendiente", f"${f_puntos(total_deuda)}")
    c2.metric("N° Documentos", len(df_f))
    c3.metric("Documentos Vencidos", num_vencidos)

    st.markdown("---")
    st.subheader("⚠️ ZONA DE ALERTA")
    ca1, ca2 = st.columns(2)
    ca1.metric("Monto Vencido (Meses Anteriores)", f"${f_puntos(atrasado)}", delta="¡Urgente!", delta_color="inverse")
    ca2.info("💡 Los montos vencidos corresponden a facturas con fecha de vencimiento previa al mes actual.")
    
    st.markdown("---")
    st.subheader("📅 Proyección de Pagos (Próximos 4 meses)")
    cols_proy = st.columns(4)
    meses_nom = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]
    for i in range(4):
        f_target = (datetime.now().replace(day=1) + timedelta(days=i*31)).replace(day=1)
        m, a = f_target.month, f_target.year
        val_m = 0
        if not df_f.empty:
            df_f['dt'] = pd.to_datetime(df_f['fecha_vencimiento'])
            val_m = df_f[(df_f['dt'].dt.month == m) & (df_f['dt'].dt.year == a)]['monto_total'].sum()
        cols_proy[i].metric(f"{meses_nom[m-1]} {a}", f"${f_puntos(val_m)}")

# --- 6. MÓDULO COMPRAS ---
def modulo_compras():
    st.header("📦 Compras e Insumos")
    t1, t2, t3 = st.tabs(["➕ Factura de Insumos", "💸 Gasto Vario", "🔍 Historial / Gestionar"])
    
    with t1:
        c1, c2 = st.columns(2)
        nro = c1.text_input("N° Documento")
        prov = c1.text_input("Proveedor")
        f_emision = c2.date_input("Fecha Emisión")
        f_vence = c2.date_input("Fecha Vencimiento")
        
        st.divider()
        conn = conectar_db()
        df_i = pd.read_sql_query("SELECT id, producto FROM inventario ORDER BY producto", conn)
        conn.close()
        
        if not df_i.empty:
            ci1, ci2, ci3, ci4 = st.columns([3,1,1,1])
            p_sel = ci1.selectbox("Insumo", df_i['id'].astype(str) + " - " + df_i['producto'])
            cant = ci2.number_input("Cantidad", min_value=0.1)
            neto_un = ci3.number_input("Neto Unitario", min_value=0.0)
            if ci4.button("➕"):
                if 'carrito' not in st.session_state: st.session_state['carrito'] = []
                st.session_state['carrito'].append({
                    'id': int(p_sel.split(" - ")[0]), 'producto': p_sel.split(" - ")[1],
                    'cantidad': cant, 'precio': neto_un, 'total': cant * neto_un
                })
                st.rerun()

        if 'carrito' in st.session_state and st.session_state['carrito']:
            df_car = pd.DataFrame(st.session_state['carrito'])
            st.table(df_car)
            neto_total = df_car['total'].sum()
            monto_final = st.number_input("Monto Total Factura (con IVA/Impuestos)", value=float(neto_total * 1.19))
            if st.button("💾 GUARDAR FACTURA Y CARGAR STOCK"):
                conn = conectar_db(); cur = conn.cursor()
                cur.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_neto, monto_total) VALUES (?,?,?,?,?,?)", (nro, prov, f_emision, f_vence, neto_total, monto_final))
                for item in st.session_state['carrito']:
                    cur.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (item['cantidad'], item['id']))
                conn.commit(); conn.close(); guardar_en_drive()
                st.session_state['carrito'] = []; st.rerun()

    with t2:
        with st.form("gasto_vario"):
            gv_prov = st.text_input("Proveedor/Beneficiario")
            gv_nro = st.text_input("N° Boleta/Comprobante")
            gv_monto = st.number_input("Monto Total", min_value=0.0)
            gv_fecha = st.date_input("Fecha del Gasto")
            gv_concepto = st.text_area("Concepto / Detalle")
            if st.form_submit_button("💾 GUARDAR GASTO"):
                conn = conectar_db(); cur = conn.cursor()
                cur.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, concepto) VALUES (?,?,?,?,?,?,?)", (gv_nro, gv_prov, gv_fecha, gv_fecha, gv_monto, 'Gasto Vario', gv_concepto))
                conn.commit(); conn.close(); guardar_en_drive(); st.rerun()

    with t3:
        conn = conectar_db()
        df_h = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_compra, monto_total, tipo, estado FROM facturas ORDER BY fecha_compra DESC", conn)
        st.dataframe(df_h, use_container_width=True)
        if not df_h.empty:
            st.download_button("📥 Descargar Reporte PDF", descargar_pdf(df_h, "HISTORIAL DE COMPRAS"), "historial.pdf")
            st.divider()
            c_ed1, c_ed2 = st.columns(2)
            id_edit = c_ed1.selectbox("Seleccione ID para gestionar", df_h['id'])
            clave = c_ed2.text_input("Clave de Seguridad", type="password")
            if st.button("🗑️ ELIMINAR REGISTRO"):
                if clave == CLAVE_SEGURIDAD:
                    conn.execute("DELETE FROM facturas WHERE id=?", (id_edit,))
                    conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
                else: st.error("Clave Incorrecta")
        conn.close()

# --- 7. MÓDULO TESORERÍA ---
def modulo_tesoreria():
    st.header("💸 Cuentas por Pagar")
    tp1, tp2, tp3 = st.tabs(["🔴 Pendientes", "🏢 Por Proveedor", "📅 Por Vencimiento"])
    conn = conectar_db()
    
    with tp1:
        df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' ORDER BY fecha_vencimiento ASC", conn)
        if not df_p.empty:
            def col_vence(row):
                v = pd.to_datetime(row['fecha_vencimiento']).date()
                return ['background-color: #ffcccc' if v < datetime.now().date() else '' for _ in row]
            st.dataframe(df_p.style.apply(col_vence, axis=1).format({"monto_total": "${:,.0f}"}), use_container_width=True)
            st.metric("Total Deuda Pendiente", f"${f_puntos(df_p['monto_total'].sum())}")
            st.download_button("📥 Descargar PDF Pendientes", descargar_pdf(df_p, "CUENTAS POR PAGAR PENDIENTES"), "pendientes.pdf")
            st.divider()
            cp1, cp2, cp3 = st.columns(3)
            id_paga = cp1.selectbox("ID a Pagar", df_p['id'])
            medio = cp2.selectbox("Medio de Pago", ["Transferencia", "Cheque", "Efectivo", "Tarjeta"])
            if cp3.button("💰 MARCAR COMO PAGADO"):
                conn.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (medio, datetime.now().date(), id_paga))
                conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
    
    with tp3:
        f1, f2 = st.date_input("Desde"), st.date_input("Hasta", hoy + timedelta(days=30))
        df_r = pd.read_sql_query(f"SELECT nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' AND fecha_vencimiento BETWEEN '{f1}' AND '{f2}'", conn)
        st.dataframe(df_r, use_container_width=True)
        if not df_r.empty:
            st.download_button("📥 PDF Rango Selección", descargar_pdf(df_r, f"VENCIMIENTOS {f1} AL {f2}"), "rango_vence.pdf")
    conn.close()

# --- 8. MÓDULO BODEGA ---
def modulo_bodega():
    st.header("🚜 Gestión de Bodega")
    tb1, tb2 = st.tabs(["📊 Stock Actual", "🔄 Movimientos (Aplicaciones)"])
    
    with tb1:
        conn = conectar_db()
        df_s = pd.read_sql_query("SELECT * FROM inventario ORDER BY producto ASC", conn)
        st.dataframe(df_s, use_container_width=True)
        st.divider()
        with st.expander("➕ REGISTRAR NUEVO INSUMO EN CATÁLOGO"):
            with st.form("ni"):
                n_nom = st.text_input("Nombre del Producto")
                n_fam = st.selectbox("Familia", FAMILIAS_PRODUCTOS)
                n_min = st.number_input("Stock Mínimo Alerta", value=0.0)
                if st.form_submit_button("REGISTRAR PRODUCTO"):
                    conn.execute("INSERT INTO inventario (producto, familia, stock, stock_minimo) VALUES (?,?,?,?)", (n_nom, n_fam, 0, n_min))
                    conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
        conn.close()

    with tb2:
        tipo_m = st.radio("Tipo", ["Salida (Aplicación)", "Entrada (Ajuste)"])
        with st.form("mov_bod"):
            conn = conectar_db()
            df_i = pd.read_sql_query("SELECT id, producto FROM inventario ORDER BY producto", conn)
            sel_i = st.selectbox("Insumo", df_i['id'].astype(str) + " - " + df_i['producto'])
            m_cant = st.number_input("Cantidad", min_value=0.1)
            m_cc = st.selectbox("Cuartel / Centro de Costo", CENTROS_COSTO) if tipo_m == "Salida (Aplicación)" else "BODEGA"
            if st.form_submit_button("REGISTRAR MOVIMIENTO"):
                id_prod = int(sel_i.split(" - ")[0])
                cur = conn.cursor()
                cur.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo) VALUES (?,?,?,?,?)", (id_prod, tipo_m, m_cant, hoy, m_cc))
                factor = 1 if "Entrada" in tipo_m else -1
                cur.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (m_cant * factor, id_prod))
                conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
            conn.close()

# --- 9. INICIALIZACIÓN Y NAVEGACIÓN ---
st.set_page_config(page_title="AGRICOLA LA CONCEPCION ERP", page_icon="🚜", layout="wide")

if 'sincronizado' not in st.session_state:
    descargar_de_drive()
    st.session_state['sincronizado'] = True

inicializar_db()

with st.sidebar:
    st.title("LA CONCEPCIÓN ERP")
    if "gcp_service_account" in st.secrets:
        st.success("☁️ Drive: CONECTADO")
        if st.button("🚀 Sincronizar Ahora"):
            guardar_en_drive()
    else:
        st.warning("⚠️ Drive: DESCONECTADO")
    
    menu = st.radio("Navegación Principal", ["🏠 Dashboard", "📦 Compras", "💸 Tesorería", "🚜 Bodega"])

# Lanzar módulos
if menu == "🏠 Dashboard": modulo_dashboard()
elif menu == "📦 Compras": modulo_compras()
elif menu == "💸 Tesorería": modulo_tesoreria()
elif menu == "🚜 Bodega": modulo_bodega()
