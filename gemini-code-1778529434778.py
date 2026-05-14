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
hoy = datetime.now().date()

FAMILIAS_PRODUCTOS = ["FERTILIZANTE", "FERTILIZANTE FOLIAR", "HERBICIDA", "INSECTICIDA", "FUNGICIDA", "BIO ESTIMULANTE", "ACARICIDA", "REGULADOR DE CRECIMIENTO", "ADHERENTE / MOJANTE", "OTROS"]
CENTROS_COSTO = ["CEREZOS CORTE1", "CEREZOS CORTE2", "CIRUELOS", "NOGALES APARICION", "NOGALES CRUZ DEL SUR", "OTROS"]

# --- 2. MOTOR DE BASE DE DATOS Y MIGRACIONES ---
def conectar_db():
    return sqlite3.connect(NOMBRE_DB)

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
    
    # Asegurar columnas de la v7
    cursor.execute("PRAGMA table_info(facturas)")
    cols = [c[1] for c in cursor.fetchall()]
    if 'centro_costo' not in cols: cursor.execute("ALTER TABLE facturas ADD COLUMN centro_costo TEXT")
    if 'monto_imputado' not in cols: cursor.execute("ALTER TABLE facturas ADD COLUMN monto_imputado REAL DEFAULT 0")
    
    cursor.execute("PRAGMA table_info(inventario)")
    if 'precio_medio' not in [c[1] for c in cursor.fetchall()]: cursor.execute("ALTER TABLE inventario ADD COLUMN precio_medio REAL DEFAULT 0")
    
    cursor.execute("PRAGMA table_info(movimientos)")
    if 'valor_imputado' not in [c[1] for c in cursor.fetchall()]: cursor.execute("ALTER TABLE movimientos ADD COLUMN valor_imputado REAL DEFAULT 0")
    
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

def descargar_pdf(df, titulo):
    try:
        pdf = FPDF(); pdf.add_page(); pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, "AGRICOLA LA CONCEPCIÓN", ln=True, align="C")
        pdf.set_font("Helvetica", "B", 12); pdf.cell(0, 10, titulo, ln=True, align="C")
        pdf.ln(5); pdf.set_font("Helvetica", "B", 8)
        cols = df.columns; w = 190 / len(cols)
        for col in cols: pdf.cell(w, 8, str(col).upper(), border=1, align="C")
        pdf.ln(); pdf.set_font("Helvetica", "", 7); suma_total = 0
        es_bodega_o_costo = any(x in str(df.columns).lower() for x in ["cantidad", "stock", "imputado", "valor", "precio"])
        for _, row in df.iterrows():
            for i, item in enumerate(row):
                col_name = df.columns[i].lower()
                if any(x in col_name for x in ["monto", "total", "cantidad", "stock", "valor", "imputado", "precio"]):
                    try: suma_total += float(item)
                    except: pass
                if isinstance(item, (int, float)):
                    if any(x in col_name for x in ["cantidad", "stock", "valor", "imputado", "precio"]) and not "total" in col_name:
                        val = f"{float(item):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    else: val = f_puntos(item)
                else: val = str(item)
                pdf.cell(w, 7, val[:25], border=1)
            pdf.ln()
        pdf.set_font("Helvetica", "B", 9); pdf.cell(w * (len(cols)-1), 8, "TOTAL REPORTE:", border=1, align="R")
        val_f = f"{float(suma_total):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if es_bodega_o_costo else f"${f_puntos(suma_total)}"
        pdf.cell(w, 8, val_f, border=1, align="L")
        return pdf.output(dest="S").encode("latin-1")
    except: return None

# --- 4. MÓDULOS ---

def modulo_dashboard():
    st.header("📊 Dashboard de Control Maestro")
    conn = conectar_db(); df_f = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente'", conn); conn.close()
    inicio_mes = hoy.replace(day=1)
    total_d = df_f['monto_total'].sum() if not df_f.empty else 0
    atrasado_prev = 0
    num_vencidos = 0
    if not df_f.empty:
        df_f['fv'] = pd.to_datetime(df_f['fecha_vencimiento']).dt.date
        atrasado_prev = df_f[df_f['fv'] < inicio_mes]['monto_total'].sum()
        num_vencidos = len(df_f[df_f['fv'] < hoy])
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Deuda Total", f"${f_puntos(total_d)}")
    c2.metric("Atrasado Meses Anteriores", f"${f_puntos(atrasado_prev)}", delta="Crítico", delta_color="inverse")
    c3.metric("Docs. Vencidos (Hoy)", num_vencidos, delta="Alerta", delta_color="inverse")
    c4.metric("Total Pendientes", len(df_f))
    if atrasado_prev > 0: st.error(f"🚨 Priorizar pagos de meses anteriores: ${f_puntos(atrasado_prev)}")
    
    st.markdown("---")
    st.subheader("📅 Proyección Mensual de Pagos")
    cols_p = st.columns(4); meses_n = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]
    for i in range(4):
        ft = (datetime.now().replace(day=1) + timedelta(days=i*31)).replace(day=1)
        m, a = ft.month, ft.year
        v = df_f[(pd.to_datetime(df_f['fecha_vencimiento']).dt.month == m) & (pd.to_datetime(df_f['fecha_vencimiento']).dt.year == a)]['monto_total'].sum() if not df_f.empty else 0
        cols_p[i].metric(f"{meses_n[m-1]} {a}", f"${f_puntos(v)}")

def modulo_compras():
    st.header("📦 Compras e Insumos")
    t1, t2, t3 = st.tabs(["➕ Factura Insumos", "💸 Gasto Vario", "🔍 Historial / Gestionar"])
    with t1:
        c1, c2 = st.columns(2)
        nro, prov = c1.text_input("N° Factura"), c1.text_input("Proveedor")
        fe, fv = c2.date_input("Emisión"), c2.date_input("Vencimiento")
        conn = conectar_db(); df_inv = pd.read_sql_query("SELECT id, producto, stock, precio_medio FROM inventario ORDER BY producto", conn); conn.close()
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
            total = st.number_input("Total Factura (IVA)", value=float(df_car['t'].sum()*1.19))
            if st.button("💾 GUARDAR FACTURA"):
                conn = conectar_db(); cur = conn.cursor()
                cur.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total) VALUES (?,?,?,?,?)", (nro, prov, fe, fv, total))
                for i in st.session_state['car']:
                    item = df_inv[df_inv['id'] == i['id']].iloc[0]
                    nuevo_pmp = ((item['stock']*item['precio_medio']) + (i['c']*i['p'])) / (item['stock']+i['c']) if (item['stock']+i['c']) > 0 else i['p']
                    cur.execute("UPDATE inventario SET stock = stock + ?, precio_medio = ? WHERE id = ?", (i['c'], nuevo_pmp, i['id']))
                conn.commit(); conn.close(); guardar_en_drive(); st.session_state['car'] = []; st.rerun()
    with t2:
        with st.form("gv"):
            p, n, m = st.text_input("Proveedor"), st.text_input("N° Doc"), st.number_input("Monto Total")
            cc = st.selectbox("Imputar a Cuartel (CC)", CENTROS_COSTO)
            iva = st.radio("¿Imputar con IVA al Costo?", ["SÍ (Total)", "NO (Solo Neto)"])
            if st.form_submit_button("💾 GUARDAR GASTO"):
                m_imp = m if iva == "SÍ (Total)" else m / 1.19
                conn = conectar_db(); conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, centro_costo, monto_imputado) VALUES (?,?,?,?,?,?,?,?)", (n, p, hoy, hoy, m, 'Gasto Vario', cc, m_imp))
                conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
    with t3:
        conn = conectar_db(); rf = conn.execute("SELECT MIN(fecha_compra), MAX(fecha_compra) FROM facturas").fetchone()
        fmin = pd.to_datetime(rf[0]).date() if rf[0] else hoy - timedelta(days=365)
        fmax = pd.to_datetime(rf[1]).date() if rf[1] else hoy
        cf1, cf2 = st.columns(2); h1, h2 = cf1.date_input("Desde", fmin), cf2.date_input("Hasta", fmax)
        df_h = pd.read_sql_query(f"SELECT id, nro_documento, proveedor, fecha_compra, monto_total, tipo FROM facturas WHERE fecha_compra BETWEEN '{h1}' AND '{h2}' ORDER BY fecha_compra DESC", conn)
        st.dataframe(df_h, use_container_width=True)
        if not df_h.empty:
            st.download_button("📥 PDF Historial", descargar_pdf(df_h, "HISTORIAL COMPRAS"), "compras.pdf")
            id_sel = st.selectbox("ID Gestionar", df_h['id']); row = df_h[df_h['id'] == id_sel].iloc[0]
            with st.expander("📝 MODIFICAR / 🗑️ ELIMINAR"):
                mn, mm = st.text_input("Nuevo N°", row['nro_documento']), st.number_input("Nuevo Monto", value=float(row['monto_total']))
                cl = st.text_input("Clave", type="password", key="mcomp")
                colb1, colb2 = st.columns(2)
                if colb1.button("ACTUALIZAR") and cl == CLAVE_SEGURIDAD:
                    conn.execute("UPDATE facturas SET nro_documento=?, monto_total=? WHERE id=?", (mn, mm, id_sel)); conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
                if colb2.button("BORRAR DEFINITIVO") and cl == CLAVE_SEGURIDAD:
                    conn.execute("DELETE FROM facturas WHERE id=?", (id_sel,)); conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
        conn.close()

def modulo_tesoreria():
    st.header("💸 Tesorería")
    tp1, tp2 = st.tabs(["🔴 Pendientes", "🏢 Por Proveedor"])
    conn = conectar_db()
    def cv(row): return ['background-color: #ffcccc' if pd.to_datetime(row['fecha_vencimiento']).date() < hoy else '' for _ in row]
    with tp1:
        df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' ORDER BY fecha_vencimiento ASC", conn)
        if not df_p.empty:
            st.dataframe(df_p.style.apply(cv, axis=1).format({"monto_total": "${:,.0f}"}), use_container_width=True)
            st.metric("Total Deuda", f"${f_puntos(df_p['monto_total'].sum())}")
            st.download_button("📥 PDF Pendientes", descargar_pdf(df_p, "PENDIENTES GENERALES"), "pendientes.pdf")
            c1, c2 = st.columns(2); id_p = c1.selectbox("ID Pago", df_p['id']); met = c2.selectbox("Medio", ["Transferencia", "Cheque", "Efectivo"])
            if st.button("💰 PAGAR"):
                conn.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (met, hoy, id_p)); conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
    with tp2:
        df_pr = pd.read_sql_query("SELECT DISTINCT proveedor FROM facturas WHERE estado='Pendiente'", conn)
        if not df_pr.empty:
            p_sel = st.selectbox("Seleccione Proveedor", df_pr['proveedor'])
            df_f = pd.read_sql_query(f"SELECT nro_documento, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' AND proveedor='{p_sel}'", conn)
            st.dataframe(df_f.style.apply(cv, axis=1).format({"monto_total": "${:,.0f}"}), use_container_width=True)
            st.download_button(f"📥 PDF {p_sel}", descargar_pdf(df_f, f"DEUDA: {p_sel}"), f"pago_{p_sel}.pdf")
    conn.close()

def modulo_bodega():
    st.header("🚜 Gestión de Bodega")
    tb1, tb2, tb3, tb4 = st.tabs(["📊 Stock Actual", "🔄 Movimientos", "➕ Nuevo Insumo", "🔍 Consultas por CC"])
    with tb1:
        conn = conectar_db(); df_s = pd.read_sql_query("SELECT id, producto, familia, stock, precio_medio FROM inventario ORDER BY producto ASC", conn)
        st.dataframe(df_s.style.format({"precio_medio": "${:,.2f}"}), use_container_width=True)
        if not df_s.empty:
            c_pdf1, c_pdf2 = st.columns(2)
            df_tra = df_s.drop(columns=['precio_medio']) # PDF TRABAJADORES SIN PRECIOS
            c_pdf1.download_button("📥 PDF Stock (Trabajadores)", descargar_pdf(df_tra, "STOCK BODEGA"), "stock_campo.pdf")
            c_pdf2.download_button("💰 PDF Valorización (Administración)", descargar_pdf(df_s, "VALORIZACIÓN DE BODEGA"), "stock_admin.pdf")
            
            st.divider(); st.subheader("⚙️ Gestión de Catálogo")
            id_ins = st.selectbox("ID Insumo a Gestionar", df_s['id']); row_i = df_s[df_s['id'] == id_ins].iloc[0]
            mi_nom = st.text_input("Editar Nombre", row_i['producto']); mi_fam = st.selectbox("Editar Familia", FAMILIAS_PRODUCTOS, index=FAMILIAS_PRODUCTOS.index(row_i['familia']) if row_i['familia'] in FAMILIAS_PRODUCTOS else 0)
            mi_pmp = st.number_input("Precio Medio (PMP)", value=float(row_i['precio_medio']))
            cl = st.text_input("Clave", type="password", key="mbod")
            cb1, cb2 = st.columns(2)
            if cb1.button("ACTUALIZAR") and cl == CLAVE_SEGURIDAD:
                conn.execute("UPDATE inventario SET producto=?, familia=?, precio_medio=? WHERE id=?", (mi_nom, mi_fam, mi_pmp, id_ins)); conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
            if cb2.button("BORRAR") and cl == CLAVE_SEGURIDAD:
                conn.execute("DELETE FROM inventario WHERE id=?", (id_ins,)); conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
        conn.close()
    with tb2:
        tipo = st.radio("Tipo", ["Salida (Campo)", "Entrada"])
        with st.form("mov"):
            conn = conectar_db(); df_i = pd.read_sql_query("SELECT id, producto, precio_medio FROM inventario", conn); conn.close()
            ps = st.selectbox("Insumo", df_i['id'].astype(str) + " - " + df_i['producto'])
            ct, cc = st.number_input("Cantidad", min_value=0.1), st.selectbox("Destino (CC)", CENTROS_COSTO)
            if st.form_submit_button("REGISTRAR"):
                item = df_i[df_i['id'] == int(ps.split(" - ")[0])].iloc[0]
                valor_imp = ct * item['precio_medio'] if "Salida" in tipo else 0
                conn = conectar_db(); cur = conn.cursor()
                cur.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado) VALUES (?,?,?,?,?,?)", (item['id'], tipo, ct, hoy, cc, valor_imp))
                f = 1 if "Entrada" in tipo else -1
                cur.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (ct*f, item['id']))
                conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
    with tb3:
        with st.form("ni"):
            n, f = st.text_input("Nombre"), st.selectbox("Familia", FAMILIAS_PRODUCTOS)
            if st.form_submit_button("💾 CREAR"):
                conn = conectar_db(); conn.execute("INSERT INTO inventario (producto, familia, stock) VALUES (?,?,0)", (n, f)); conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
    with tb4:
        cc_sel = st.selectbox("Consultar Cuartel", CENTROS_COSTO); conn = conectar_db()
        df_cc = pd.read_sql_query(f"SELECT m.fecha, i.producto, m.tipo, m.cantidad, m.valor_imputado FROM movimientos m JOIN inventario i ON m.producto_id = i.id WHERE m.centro_costo = '{cc_sel}' ORDER BY m.fecha DESC", conn); conn.close()
        if not df_cc.empty:
            st.dataframe(df_cc, use_container_width=True)
            st.download_button(f"📥 PDF {cc_sel}", descargar_pdf(df_cc, f"MOVIMIENTOS: {cc_sel}"), f"mov_{cc_sel}.pdf")

def modulo_costos():
    st.header("💰 Gestión de Costos por Cuartel")
    conn = conectar_db()
    df_ins = pd.read_sql_query("SELECT centro_costo, SUM(valor_imputado) as total_insumos FROM movimientos WHERE tipo LIKE 'Salida%' GROUP BY centro_costo", conn)
    df_gas = pd.read_sql_query("SELECT centro_costo, SUM(monto_imputado) as total_gastos FROM facturas WHERE tipo='Gasto Vario' GROUP BY centro_costo", conn)
    conn.close()
    df_total = pd.merge(df_ins, df_gas, on='centro_costo', how='outer').fillna(0)
    df_total['COSTO NETO TOTAL'] = df_total['total_insumos'] + df_total['total_gastos']
    st.subheader("Resumen Económico Consolidado")
    st.dataframe(df_total.style.format({"total_insumos": "${:,.0f}", "total_gastos": "${:,.0f}", "COSTO NETO TOTAL": "${:,.0f}"}), use_container_width=True)
    c1, c2 = st.columns(2)
    with c1: st.subheader("Gasto en Insumos"); st.bar_chart(df_total.set_index('centro_costo')['total_insumos'])
    with c2: st.subheader("Gasto Operacional Directo"); st.bar_chart(df_total.set_index('centro_costo')['total_gastos'])
    if not df_total.empty: st.download_button("📥 Exportar Costos a PDF", descargar_pdf(df_total, "REPORTE DE COSTOS"), "costos.pdf")

# --- 5. NAVEGACIÓN ---
st.set_page_config(page_title="LA CONCEPCIÓN ERP v7.3", page_icon="🚜", layout="wide")
if 'init' not in st.session_state: descargar_de_drive(); st.session_state['init'] = True
inicializar_db()
with st.sidebar:
    st.title("LA CONCEPCIÓN")
    menu = st.radio("Módulos", ["🏠 Dashboard", "📦 Compras", "💸 Tesorería", "🚜 Bodega", "💰 COSTOS"])
    if st.button("🚀 Sincronizar Ahora"): guardar_en_drive()

if menu == "🏠 Dashboard": modulo_dashboard()
elif menu == "📦 Compras": modulo_compras()
elif menu == "💸 Tesorería": modulo_tesoreria()
elif menu == "🚜 Bodega": modulo_bodega()
elif menu == "💰 COSTOS": modulo_costos()
