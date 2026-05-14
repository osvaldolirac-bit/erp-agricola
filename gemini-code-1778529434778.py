import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
from fpdf import FPDF
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. CONFIGURACIÓN Y CONSTANTES ---
ID_CARPETA_DRIVE = "12tjxWa_RVRP5YuYd2sypjBO8bPuyMqo6" 
NOMBRE_DB = 'erp_concepcion_v6.db'
CLAVE_SEGURIDAD = "2908"
hoy = datetime.now().date()

FAMILIAS_PRODUCTOS = ["FERTILIZANTE", "FERTILIZANTE FOLIAR", "HERBICIDA", "INSECTICIDA", "FUNGICIDA", "BIO ESTIMULANTE", "ACARICIDA", "REGULADOR DE CRECIMIENTO", "ADHERENTE / MOJANTE", "OTROS"]
CENTROS_COSTO = ["CEREZOS CORTE1", "CEREZOS CORTE2", "CIRUELOS", "NOGALES APARICION", "NOGALES CRUZ DEL SUR", "OTROS"]

# --- 2. MOTOR DE BASE DE DATOS (CON MIGRACIÓN INTEGRADA) ---
def conectar_db():
    return sqlite3.connect(NOMBRE_DB)

def inicializar_db():
    conn = conectar_db(); cursor = conn.cursor()
    # Tablas base
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
    
    # MIGRACIÓN V7: Agregar columnas de costos si no existen
    cursor.execute("PRAGMA table_info(facturas)")
    cols_fact = [c[1] for c in cursor.fetchall()]
    if 'centro_costo' not in cols_fact: cursor.execute("ALTER TABLE facturas ADD COLUMN centro_costo TEXT")
    if 'monto_imputado' not in cols_fact: cursor.execute("ALTER TABLE facturas ADD COLUMN monto_imputado REAL DEFAULT 0")

    cursor.execute("PRAGMA table_info(inventario)")
    if 'precio_medio' not in [c[1] for c in cursor.fetchall()]:
        cursor.execute("ALTER TABLE inventario ADD COLUMN precio_medio REAL DEFAULT 0")

    cursor.execute("PRAGMA table_info(movimientos)")
    if 'valor_imputado' not in [c[1] for c in cursor.fetchall()]:
        cursor.execute("ALTER TABLE movimientos ADD COLUMN valor_imputado REAL DEFAULT 0")

    conn.commit(); conn.close()

# --- 3. UTILIDADES (DRIVE, PUNTOS, PDF) ---
def f_puntos(v):
    try: return f"{int(v):,}".replace(",", ".")
    except: return "0"

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
    try:
        drive = obtener_drive()
        if not drive: return False
        query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
        lista = drive.ListFile({'q': query}).GetList()
        f = lista[0] if lista else drive.CreateFile({'title': NOMBRE_DB, 'parents': [{'id': ID_CARPETA_DRIVE}]})
        f.SetContentFile(NOMBRE_DB); f.Upload()
        st.success(f"✅ Sincronizado en Drive")
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

def descargar_pdf(df, titulo, es_costo=False):
    try:
        pdf = FPDF(); pdf.add_page(); pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, "AGRICOLA LA CONCEPCIÓN - " + titulo, ln=True, align="C"); pdf.ln(5)
        pdf.set_font("Helvetica", "B", 8); cols = df.columns; w = 190 / len(cols)
        for col in cols: pdf.cell(w, 8, str(col).upper(), border=1, align="C")
        pdf.ln(); pdf.set_font("Helvetica", "", 7); total_suma = 0
        for _, row in df.iterrows():
            for i, item in enumerate(row):
                if any(x in df.columns[i].lower() for x in ["total", "monto", "valor", "cantidad", "stock"]):
                    try: total_suma += float(item)
                    except: pass
                val = f_puntos(item) if isinstance(item, (int, float)) and not es_costo else str(item)
                if es_costo and isinstance(item, (int, float)): val = f"{item:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                pdf.cell(w, 7, val[:25], border=1)
            pdf.ln()
        pdf.set_font("Helvetica", "B", 9); pdf.cell(w*(len(cols)-1), 8, "TOTAL:", border=1, align="R")
        pdf.cell(w, 8, f_puntos(total_suma) if not es_costo else f"{total_suma:,.0f}", border=1)
        return pdf.output(dest="S").encode("latin-1")
    except: return None

# --- 4. MÓDULOS DEL SISTEMA ---

def modulo_dashboard():
    st.header("📊 Dashboard")
    conn = conectar_db(); df_f = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente'", conn); conn.close()
    inicio_mes = hoy.replace(day=1)
    total_deuda = df_f['monto_total'].sum() if not df_f.empty else 0
    atrasado = df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < inicio_mes]['monto_total'].sum() if not df_f.empty else 0
    c1, c2, c3 = st.columns(3)
    c1.metric("Deuda Total", f"${f_puntos(total_deuda)}")
    c2.metric("Atrasado", f"${f_puntos(atrasado)}", delta="Crítico", delta_color="inverse")
    c3.metric("Docs. Vencidos Hoy", len(df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < hoy]) if not df_f.empty else 0)

def modulo_compras():
    st.header("📦 Compras")
    t1, t2, t3 = st.tabs(["➕ Insumos (PMP)", "💸 Gasto Vario", "🔍 Historial"])
    with t1:
        c1, c2 = st.columns(2)
        nro, prov = c1.text_input("N° Factura"), c1.text_input("Proveedor")
        f_e, f_v = c2.date_input("Emisión"), c2.date_input("Vencimiento")
        conn = conectar_db(); df_inv = pd.read_sql_query("SELECT id, producto, stock, precio_medio FROM inventario ORDER BY producto", conn); conn.close()
        if not df_inv.empty:
            cp1, cp2, cp3, cp4 = st.columns([3,1,1,1])
            ps = cp1.selectbox("Insumo", df_inv['id'].astype(str) + " - " + df_inv['producto'])
            ct, pr_neto = cp2.number_input("Cantidad", min_value=0.1), cp3.number_input("Neto Unitario", min_value=0.0)
            if cp4.button("➕"):
                if 'car' not in st.session_state: st.session_state['car'] = []
                st.session_state['car'].append({'id': int(ps.split(" - ")[0]), 'n': ps.split(" - ")[1], 'c': ct, 'p': pr_neto, 't': ct*pr_neto})
                st.rerun()
        if st.session_state.get('car'):
            df_car = pd.DataFrame(st.session_state['car']); st.table(df_car)
            total_fac = st.number_input("Monto Total Factura (IVA)", value=float(df_car['t'].sum()*1.19))
            if st.button("💾 GUARDAR COMPRA Y ACTUALIZAR PMP"):
                conn = conectar_db(); cur = conn.cursor()
                cur.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total) VALUES (?,?,?,?,?)", (nro, prov, f_e, f_v, total_fac))
                for i in st.session_state['car']:
                    # CÁLCULO PMP: (S_actual * PMP_actual + Cant_nueva * Prec_nuevo) / S_total
                    item = df_inv[df_inv['id'] == i['id']].iloc[0]
                    s_act, pmp_act = item['stock'], item['precio_medio']
                    nuevo_pmp = ((s_act * pmp_act) + (i['c'] * i['p'])) / (s_act + i['c'])
                    cur.execute("UPDATE inventario SET stock = stock + ?, precio_medio = ? WHERE id = ?", (i['c'], nuevo_pmp, i['id']))
                conn.commit(); conn.close(); guardar_en_drive(); st.session_state['car'] = []; st.rerun()

    with t2:
        with st.form("gv"):
            gv_p, gv_n = st.text_input("Proveedor"), st.text_input("N° Doc")
            gv_m, gv_cc = st.number_input("Monto Total"), st.selectbox("Imputar a CC", CENTROS_COSTO)
            imp_iva = st.radio("¿Imputar con IVA al Costo?", ["SÍ (Total)", "NO (Solo Neto)"])
            if st.form_submit_button("💾 GUARDAR GASTO"):
                m_imp = gv_m if imp_iva == "SÍ (Total)" else gv_m / 1.19
                conn = conectar_db(); conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, centro_costo, monto_imputado) VALUES (?,?,?,?,?,?,?,?)", (gv_n, gv_p, hoy, hoy, gv_m, 'Gasto Vario', gv_cc, m_imp))
                conn.commit(); conn.close(); guardar_en_drive(); st.rerun()

def modulo_tesoreria():
    st.header("💸 Tesorería")
    conn = conectar_db(); df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' ORDER BY fecha_vencimiento ASC", conn); conn.close()
    if not df_p.empty:
        def cv(row): return ['background-color: #ffcccc' if pd.to_datetime(row['fecha_vencimiento']).date() < hoy else '' for _ in row]
        st.dataframe(df_p.style.apply(cv, axis=1).format({"monto_total": "${:,.0f}"}), use_container_width=True)
        id_p = st.selectbox("ID Pago", df_p['id']); met = st.selectbox("Medio", ["Transferencia", "Cheque", "Efectivo"])
        if st.button("💰 PAGAR"):
            conn = conectar_db(); conn.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (met, hoy, id_p)); conn.commit(); conn.close(); guardar_en_drive(); st.rerun()

def modulo_bodega():
    st.header("🚜 Bodega")
    tb1, tb2 = st.tabs(["📊 Stock y Precios", "🔄 Movimientos"])
    with tb1:
        conn = conectar_db(); df_s = pd.read_sql_query("SELECT id, producto, familia, stock, precio_medio FROM inventario ORDER BY producto ASC", conn); conn.close()
        st.dataframe(df_s.style.format({"precio_medio": "${:,.2f}"}), use_container_width=True)
        with st.expander("⚙️ Valorizar Inventario Actual (Ajuste Inicial)"):
            id_aj = st.selectbox("Producto", df_s['id'].astype(str) + " - " + df_s['producto'])
            p_aj = st.number_input("Nuevo Precio Medio (Neto)", min_value=0.0)
            if st.button("ACTUALIZAR VALOR"):
                conn = conectar_db(); conn.execute("UPDATE inventario SET precio_medio = ? WHERE id = ?", (p_aj, int(id_aj.split(" - ")[0]))); conn.commit(); conn.close(); st.rerun()

    with tb2:
        tipo = st.radio("Tipo", ["Salida (Campo)", "Entrada"])
        with st.form("mov"):
            conn = conectar_db(); df_i = pd.read_sql_query("SELECT id, producto, precio_medio FROM inventario", conn); conn.close()
            ps = st.selectbox("Insumo", df_i['id'].astype(str) + " - " + df_i['producto'])
            ct, cc = st.number_input("Cantidad", min_value=0.1), st.selectbox("Centro Costo", CENTROS_COSTO)
            if st.form_submit_button("REGISTRAR"):
                item = df_i[df_i['id'] == int(ps.split(" - ")[0])].iloc[0]
                # COSTO IMPUTADO = Cantidad * Precio Medio Actual
                valor_imp = ct * item['precio_medio'] if tipo == "Salida (Campo)" else 0
                conn = conectar_db(); cur = conn.cursor()
                cur.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado) VALUES (?,?,?,?,?,?)", (item['id'], tipo, ct, hoy, cc, valor_imp))
                f = 1 if tipo == "Entrada" else -1
                cur.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (ct*f, item['id']))
                conn.commit(); conn.close(); guardar_en_drive(); st.rerun()

def modulo_costos():
    st.header("💰 Gestión de Costos por CC")
    conn = conectar_db()
    # 1. Costos por Insumos (Salidas de Bodega)
    df_ins = pd.read_sql_query("SELECT centro_costo, SUM(valor_imputado) as total_insumos FROM movimientos WHERE tipo='Salida (Campo)' GROUP BY centro_costo", conn)
    # 2. Costos por Gastos Varios
    df_gas = pd.read_sql_query("SELECT centro_costo, SUM(monto_imputado) as total_gastos FROM facturas WHERE tipo='Gasto Vario' GROUP BY centro_costo", conn)
    conn.close()
    
    # Unir ambos
    df_total = pd.merge(df_ins, df_gas, on='centro_costo', how='outer').fillna(0)
    df_total['COSTO TOTAL NETO'] = df_total['total_insumos'] + df_total['total_gastos']
    
    st.subheader("Resumen Consolidado")
    st.dataframe(df_total.style.format({"total_insumos": "${:,.0f}", "total_gastos": "${:,.0f}", "COSTO TOTAL NETO": "${:,.0f}"}), use_container_width=True)
    
    c1, c2 = st.columns(2)
    with c1: st.subheader("Insumos por CC"); st.bar_chart(df_total.set_index('centro_costo')['total_insumos'])
    with c2: st.subheader("Gastos por CC"); st.bar_chart(df_total.set_index('centro_costo')['total_gastos'])
    
    if st.button("📥 Descargar Reporte de Costos PDF"):
        st.download_button("Descargar", descargar_pdf(df_total, "REPORTE DE COSTOS", es_costo=True), "costos.pdf")

# --- 5. NAVEGACIÓN ---
st.set_page_config(page_title="LA CONCEPCIÓN ERP v7.0", layout="wide")
if 'init' not in st.session_state: descargar_de_drive(); st.session_state['init'] = True
inicializar_db()

with st.sidebar:
    st.title("LA CONCEPCIÓN")
    menu = st.radio("Módulos", ["🏠 Dashboard", "📦 Compras", "💸 Tesorería", "🚜 Bodega", "💰 COSTOS"])
    if st.button("🚀 Sincronizar Drive"): guardar_en_drive()

if menu == "🏠 Dashboard": modulo_dashboard()
elif menu == "📦 Compras": modulo_compras()
elif menu == "💸 Tesorería": modulo_tesoreria()
elif menu == "🚜 Bodega": modulo_bodega()
elif menu == "💰 COSTOS": modulo_costos()
