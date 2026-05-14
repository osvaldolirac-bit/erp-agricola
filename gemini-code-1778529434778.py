import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import os
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

# --- 2. MOTOR DE BASE DE DATOS Y MIGRACIONES ---
def conectar_db():
    return sqlite3.connect(NOMBRE_DB)

def inicializar_db():
    conn = conectar_db()
    cursor = conn.cursor()
    # Tabla Facturas
    cursor.execute("""CREATE TABLE IF NOT EXISTS facturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nro_documento TEXT, proveedor TEXT, 
        fecha_compra DATE, fecha_vencimiento DATE, monto_neto REAL, monto_total REAL, 
        estado TEXT DEFAULT 'Pendiente', tipo TEXT DEFAULT 'Factura', 
        metodo_pago TEXT, fecha_pago DATE, concepto TEXT, centro_costo TEXT, monto_imputado REAL DEFAULT 0)""")
    # Tabla Inventario
    cursor.execute("""CREATE TABLE IF NOT EXISTS inventario (
        id INTEGER PRIMARY KEY AUTOINCREMENT, producto TEXT, familia TEXT, 
        stock REAL DEFAULT 0, stock_minimo REAL DEFAULT 0, precio_medio REAL DEFAULT 0)""")
    # Tabla Movimientos
    cursor.execute("""CREATE TABLE IF NOT EXISTS movimientos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, producto_id INTEGER, tipo TEXT, 
        cantidad REAL, centro_costo TEXT, fecha DATE, valor_imputado REAL DEFAULT 0)""")
    
    # Migración de columnas (Seguridad v7.9)
    cursor.execute("PRAGMA table_info(facturas)")
    cols_f = [c[1] for c in cursor.fetchall()]
    if 'centro_costo' not in cols_f: cursor.execute("ALTER TABLE facturas ADD COLUMN centro_costo TEXT")
    if 'monto_imputado' not in cols_f: cursor.execute("ALTER TABLE facturas ADD COLUMN monto_imputado REAL DEFAULT 0")
    
    cursor.execute("PRAGMA table_info(inventario)")
    cols_i = [c[1] for c in cursor.fetchall()]
    if 'precio_medio' not in cols_i: cursor.execute("ALTER TABLE inventario ADD COLUMN precio_medio REAL DEFAULT 0")
    
    cursor.execute("PRAGMA table_info(movimientos)")
    cols_m = [c[1] for c in cursor.fetchall()]
    if 'valor_imputado' not in cols_m: cursor.execute("ALTER TABLE movimientos ADD COLUMN valor_imputado REAL DEFAULT 0")
    
    conn.commit()
    conn.close()

# --- 3. UTILIDADES (DRIVE, FORMATOS, PDF) ---
def f_puntos(v):
    try: return f"{int(v):,}".replace(",", ".")
    except: return "0"

def obtener_drive():
    try:
        if "gcp_service_account" not in st.secrets: return None
        info = dict(st.secrets["gcp_service_account"])
        if "private_key" in info: info["private_key"] = info["private_key"].replace("\\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(info, ['https://www.googleapis.com/auth/drive'])
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
        st.success("✅ Sincronizado en Drive")
        return True
    except: return False

def descargar_de_drive():
    try:
        drive = obtener_drive()
        if not drive: return False
        query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
        lista = drive.ListFile({'q': query}).GetList()
        if lista: lista[0].GetContentFile(NOMBRE_DB)
        return True
    except: return False

def descargar_pdf(df, titulo, es_valorizado=False):
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
        total_acumulado = 0
        for _, row in df.iterrows():
            if es_valorizado and "stock" in df.columns.str.lower():
                total_acumulado += (row['stock'] * row['precio_medio'])
            for i, item in enumerate(row):
                col_name = df.columns[i].lower()
                if not es_valorizado and any(x in col_name for x in ["monto", "total", "valor_imputado", "imputado"]):
                    try: total_acumulado += float(item)
                    except: pass
                if isinstance(item, (int, float)):
                    if any(x in col_name for x in ["cantidad", "stock", "precio_medio", "valor_imputado"]):
                        val = f"{float(item):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    else: val = f_puntos(item)
                else: val = str(item)
                pdf.cell(w, 7, val[:25], border=1)
            pdf.ln()
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(w * (len(cols)-1), 8, "TOTAL REPORTE:", border=1, align="R")
        pdf.cell(w, 8, f"${f_puntos(total_acumulado)}", border=1, align="L")
        return pdf.output(dest="S").encode("latin-1")
    except: return None

# --- 4. MÓDULOS DEL SISTEMA ---

def modulo_dashboard():
    st.header("📊 Dashboard de Control Maestro")
    conn = conectar_db()
    df_f = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente'", conn)
    df_ins = pd.read_sql_query("SELECT centro_costo, SUM(valor_imputado) as insumos FROM movimientos WHERE tipo LIKE 'Salida%' GROUP BY centro_costo", conn)
    df_gas = pd.read_sql_query("SELECT centro_costo, SUM(monto_imputado) as gastos FROM facturas WHERE tipo='Gasto Vario' GROUP BY centro_costo", conn)
    conn.close()
    
    total_deuda = df_f['monto_total'].sum() if not df_f.empty else 0
    atrasado = df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < hoy.replace(day=1)]['monto_total'].sum() if not df_f.empty else 0
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Deuda Total", f"${f_puntos(total_deuda)}")
    c2.metric("Atrasado Meses Prev.", f"${f_puntos(atrasado)}", delta="Crítico", delta_color="inverse")
    c3.metric("Vencidos Hoy", len(df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < hoy]) if not df_f.empty else 0)
    c4.metric("Pendientes", len(df_f))

    st.markdown("---")
    col_izq, col_der = st.columns(2)
    with col_izq:
        st.subheader("📅 Proyección de Pagos")
        cols_p = st.columns(4); meses_n = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]
        for i in range(4):
            ft = (datetime.now().replace(day=1) + timedelta(days=i*31)).replace(day=1)
            m, a = ft.month, ft.year
            v = df_f[(pd.to_datetime(df_f['fecha_vencimiento']).dt.month == m) & (pd.to_datetime(df_f['fecha_vencimiento']).dt.year == a)]['monto_total'].sum() if not df_f.empty else 0
            cols_p[i].metric(f"{meses_n[m-1]} {a}", f"${f_puntos(v)}")
    with col_der:
        st.subheader("💰 Costos por Cuartel (Neto)")
        df_c = pd.merge(df_ins, df_gas, on='centro_costo', how='outer').fillna(0)
        df_c['TOTAL'] = df_c['insumos'] + df_c['gastos']
        if not df_c.empty:
            st.dataframe(df_c.style.format({"insumos": "${:,.0f}", "gastos": "${:,.0f}", "TOTAL": "${:,.0f}"}), use_container_width=True)
            st.bar_chart(df_c.set_index('centro_costo')['TOTAL'])

def modulo_compras():
    st.header("📦 Compras e Insumos")
    t1, t2, t3 = st.tabs(["➕ Factura Insumos", "💸 Gasto Vario", "🔍 Historial / Gestión"])
    with t1:
        c1, c2 = st.columns(2)
        nro, prov = c1.text_input("N° Factura"), c1.text_input("Proveedor")
        fe, fv = c2.date_input("Emisión"), c2.date_input("Vencimiento")
        conn = conectar_db()
        df_inv = pd.read_sql_query("SELECT id, producto, stock, precio_medio FROM inventario ORDER BY producto", conn)
        conn.close()
        if not df_inv.empty:
            cp1, cp2, cp3, cp4 = st.columns([3,1,1,1])
            ps = cp1.selectbox("Insumo", df_inv['id'].astype(str) + " - " + df_inv['producto'])
            ct, pr = cp2.number_input("Cant", min_value=0.1), cp3.number_input("Neto Un", min_value=0.0)
            if cp4.button("➕"):
                if 'car' not in st.session_state: st.session_state['car'] = []
                st.session_state['car'].append({'id': int(ps.split(" - ")[0]), 'n': ps.split(" - ")[1], 'c': ct, 'p': pr, 't': ct*pr})
                st.rerun()
        if st.session_state.get('car'):
            df_car = pd.DataFrame(st.session_state['car']); st.table(df_car)
            total_f = st.number_input("Total Factura (IVA)", value=float(df_car['t'].sum()*1.19))
            if st.button("💾 GUARDAR FACTURA"):
                conn = conectar_db(); cur = conn.cursor()
                cur.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total) VALUES (?,?,?,?,?)", (nro, prov, fe, fv, total_f))
                for i in st.session_state['car']:
                    item = df_inv[df_inv['id'] == i['id']].iloc[0]
                    nuevo_pmp = ((item['stock']*item['precio_medio']) + (i['c']*i['p'])) / (item['stock']+i['c']) if (item['stock']+i['c']) > 0 else i['p']
                    cur.execute("UPDATE inventario SET stock = stock + ?, precio_medio = ? WHERE id = ?", (i['c'], nuevo_pmp, i['id']))
                conn.commit(); conn.close(); guardar_en_drive(); st.session_state['car'] = []; st.rerun()
    with t2:
        with st.form("gv"):
            p, n, m = st.text_input("Proveedor"), st.text_input("N° Doc"), st.number_input("Monto Total")
            cc = st.selectbox("CC Destino", CENTROS_COSTO); iva = st.radio("¿Imputar IVA al costo?", ["SÍ (Total)", "NO (Neto)"])
            if st.form_submit_button("💾 GUARDAR GASTO"):
                m_imp = m if iva == "SÍ (Total)" else m / 1.19
                conn = conectar_db(); conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, centro_costo, monto_imputado) VALUES (?,?,?,?,?,?,?,?)", (n, p, hoy, hoy, m, 'Gasto Vario', cc, m_imp))
                conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
    with t3:
        conn = conectar_db(); rf = conn.execute("SELECT MIN(fecha_compra), MAX(fecha_compra) FROM facturas").fetchone()
        fmin = pd.to_datetime(rf[0]).date() if rf[0] else hoy-timedelta(days=365); fmax = pd.to_datetime(rf[1]).date() if rf[1] else hoy
        cf1, cf2 = st.columns(2); h1, h2 = cf1.date_input("Desde", fmin), cf2.date_input("Hasta", fmax)
        df_h = pd.read_sql_query(f"SELECT id, nro_documento, proveedor, fecha_compra, monto_total, tipo FROM facturas WHERE fecha_compra BETWEEN '{h1}' AND '{h2}' ORDER BY fecha_compra DESC", conn)
        st.dataframe(df_h, use_container_width=True)
        if not df_h.empty:
            st.download_button("📥 PDF Historial", descargar_pdf(df_h, "HISTORIAL COMPRAS"), "compras.pdf")
            st.divider(); id_sel = st.selectbox("ID Gestionar", df_h['id']); row = df_h[df_h['id'] == id_sel].iloc[0]
            with st.expander("📝 MODIFICAR / 🗑️ ELIMINAR"):
                mn, mm = st.text_input("Nuevo N°", row['nro_documento']), st.number_input("Nuevo Monto", value=float(row['monto_total'])); cl = st.text_input("Clave", type="password", key="mcomp")
                cb1, cb2 = st.columns(2)
                if cb1.button("ACTUALIZAR") and cl == CLAVE_SEGURIDAD: conn.execute("UPDATE facturas SET nro_documento=?, monto_total=? WHERE id=?", (mn, mm, id_sel)); conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
                if cb2.button("BORRAR") and cl == CLAVE_SEGURIDAD: conn.execute("DELETE FROM facturas WHERE id=?", (id_sel,)); conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
        conn.close()

def modulo_tesoreria():
    st.header("💸 Tesorería")
    tp1, tp2, tp3 = st.tabs(["🔴 Pendientes", "🏢 Por Proveedor", "📅 Rango Vencimiento"])
    conn = conectar_db()
    def color_vence(row): 
        return ['background-color: #ffcccc' if pd.to_datetime(row['fecha_vencimiento']).date() < hoy else '' for _ in row]
    with tp1:
        df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' ORDER BY fecha_vencimiento ASC", conn)
        if not df_p.empty:
            st.dataframe(df_p.style.apply(color_vence, axis=1).format({"monto_total": "${:,.0f}"}), use_container_width=True)
            id_p = st.selectbox("ID Pago", df_p['id']); met = st.selectbox("Medio", ["Transferencia", "Cheque", "Efectivo"])
            if st.button("💰 PAGAR"): conn.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (met, hoy, id_p)); conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
    with tp2:
        df_provs = pd.read_sql_query("SELECT DISTINCT proveedor FROM facturas WHERE estado='Pendiente'", conn)
        if not df_provs.empty:
            p_sel = st.selectbox("Proveedor", df_provs['proveedor'])
            df_f = pd.read_sql_query(f"SELECT nro_documento, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' AND proveedor='{p_sel}'", conn)
            st.dataframe(df_f.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
            st.download_button("📥 PDF Proveedor", descargar_pdf(df_f, f"DEUDA: {p_sel}"), "deuda_prov.pdf")
    with tp3:
        f1, f2 = st.date_input("Vence Desde", hoy), st.date_input("Vence Hasta", hoy + timedelta(days=30))
        df_r = pd.read_sql_query(f"SELECT nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' AND fecha_vencimiento BETWEEN '{f1}' AND '{f2}'", conn)
        if not df_r.empty: st.dataframe(df_r.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
    conn.close()

def modulo_bodega():
    st.header("🚜 Bodega")
    tb1, tb2, tb3, tb4 = st.tabs(["📊 Stock", "🔄 Movimientos", "➕ Nuevo", "🔍 Consulta CC"])
    with tb1:
        conn = conectar_db(); df_s = pd.read_sql_query("SELECT id, producto, familia, stock, precio_medio FROM inventario ORDER BY producto ASC", conn)
        st.dataframe(df_s.style.format({"precio_medio": "${:,.2f}"}), use_container_width=True)
        if not df_s.empty:
            c1, c2 = st.columns(2)
            c1.download_button("📥 PDF Trabajadores", descargar_pdf(df_s.drop(columns=['precio_medio']), "STOCK BODEGA"), "stock_campo.pdf")
            c2.download_button("💰 PDF Administración", descargar_pdf(df_s, "VALORIZACIÓN BODEGA", es_valorizado=True), "stock_admin.pdf")
            st.divider(); id_ins = st.selectbox("ID Insumo", df_s['id']); row = df_s[df_s['id'] == id_ins].iloc[0]; mi_nom = st.text_input("Nombre", row['producto']); mi_pmp = st.number_input("Precio PMP", value=float(row['precio_medio'])); cl = st.text_input("Clave", type="password", key="mb")
            if st.button("ACTUALIZAR") and cl == CLAVE_SEGURIDAD: conn.execute("UPDATE inventario SET producto=?, precio_medio=? WHERE id=?", (mi_nom, mi_pmp, id_ins)); conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
        conn.close()
    with tb2:
        tipo = st.radio("Tipo", ["Salida (Campo)", "Entrada"])
        with st.form("mov"):
            conn = conectar_db(); df_i = pd.read_sql_query("SELECT id, producto, precio_medio FROM inventario", conn); conn.close()
            ps = st.selectbox("Insumo", df_i['id'].astype(str) + " - " + df_i['producto']); ct, cc = st.number_input("Cant", min_value=0.1), st.selectbox("CC", CENTROS_COSTO)
            if st.form_submit_button("REGISTRAR"):
                item = df_i[df_i['id'] == int(ps.split(" - ")[0])].iloc[0]; valor_imp = ct * item['precio_medio'] if "Salida" in tipo else 0; conn = conectar_db(); cur = conn.cursor(); cur.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado) VALUES (?,?,?,?,?,?)", (item['id'], tipo, ct, hoy, cc, valor_imp)); f = 1 if "Entrada" in tipo else -1; cur.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (ct*f, item['id'])); conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
    with tb4:
        cc_sel = st.selectbox("Cuartel", CENTROS_COSTO); conn = conectar_db()
        df_cc = pd.read_sql_query(f"SELECT m.fecha, i.producto, m.tipo, m.cantidad, m.valor_imputado FROM movimientos m JOIN inventario i ON m.producto_id = i.id WHERE m.centro_costo = '{cc_sel}' ORDER BY m.fecha DESC", conn); conn.close()
        if not df_cc.empty: st.dataframe(df_cc, use_container_width=True); st.download_button(f"📥 PDF {cc_sel}", descargar_pdf(df_cc, f"MOVIMIENTOS: {cc_sel}"), "mov_cc.pdf")

def modulo_costos():
    st.header("💰 Gestión de Costos")
    conn = conectar_db(); df_i = pd.read_sql_query("SELECT centro_costo, SUM(valor_imputado) as insumos FROM movimientos WHERE tipo LIKE 'Salida%' GROUP BY centro_costo", conn); df_g = pd.read_sql_query("SELECT centro_costo, SUM(monto_imputado) as gastos FROM facturas WHERE tipo='Gasto Vario' GROUP BY centro_costo", conn); conn.close()
    df_t = pd.merge(df_i, df_g, on='centro_costo', how='outer').fillna(0); df_t['COSTO TOTAL'] = df_t['insumos'] + df_t['gastos']
    st.dataframe(df_t.style.format({"insumos": "${:,.0f}", "gastos": "${:,.0f}", "COSTO TOTAL": "${:,.0f}"}), use_container_width=True)

# --- 5. NAVEGACIÓN ---
st.set_page_config(page_title="LA CONCEPCIÓN ERP v7.9", page_icon="🚜", layout="wide")
if 'init' not in st.session_state: descargar_de_drive(); st.session_state['init'] = True
inicializar_db()
with st.sidebar:
    st.title("LA CONCEPCIÓN")
    if "gcp_service_account" in st.secrets: st.markdown("🟢 **Drive: CONECTADO**")
    menu = st.radio("Módulos", ["🏠 Dashboard", "📦 Compras", "💸 Tesorería", "🚜 Bodega", "💰 COSTOS"])
    if st.button("🚀 Sincronizar Ahora"): guardar_en_drive()

if menu == "🏠 Dashboard": modulo_dashboard()
elif menu == "📦 Compras": modulo_compras()
elif menu == "💸 Tesorería": modulo_tesoreria()
elif menu == "🚜 Bodega": modulo_bodega()
elif menu == "💰 COSTOS": modulo_costos()
