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

# --- 2. MOTOR DE BASE DE DATOS ---
def conectar_db():
    return sqlite3.connect(NOMBRE_DB)

def inicializar_db():
    conn = conectar_db()
    cursor = conn.cursor()
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
    conn.commit()
    conn.close()

# --- 3. UTILIDADES ---
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
        st.success("✅ Respaldo en Drive OK.")
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

def generar_pdf_blob(df, titulo, es_valorizado=False):
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, "AGRICOLA LA CONCEPCIÓN", ln=True, align="C")
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 10, titulo, ln=True, align="C")
        pdf.ln(5); pdf.set_font("Helvetica", "B", 8)
        cols = df.columns; w = 190 / len(cols)
        for col in cols: pdf.cell(w, 8, str(col).upper(), border=1, align="C")
        pdf.ln(); pdf.set_font("Helvetica", "", 7); total_acum = 0
        for _, row in df.iterrows():
            if es_valorizado and "stock" in df.columns.str.lower():
                total_acum += (row['stock'] * row['precio_medio'])
            for i, item in enumerate(row):
                col_name = df.columns[i].lower()
                if not es_valorizado and any(x in col_name for x in ["monto", "total", "valor", "imputado"]):
                    try: total_acum += float(item)
                    except: pass
                if isinstance(item, (int, float)):
                    if any(x in col_name for x in ["cantidad", "stock", "precio", "imputado"]):
                        val = f"{float(item):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    else: val = f_puntos(item)
                else: val = str(item)
                pdf.cell(w, 7, val[:25], border=1)
            pdf.ln()
        pdf.set_font("Helvetica", "B", 9); pdf.cell(w * (len(cols)-1), 8, "TOTAL FINAL REPORTE:", border=1, align="R")
        pdf.cell(w, 8, f"${f_puntos(total_acum)}", border=1, align="L")
        return pdf.output(dest="S").encode("latin-1")
    except: return None

# --- 4. MÓDULOS ---

def modulo_dashboard():
    st.header("📊 Tablero Maestro")
    conn = conectar_db()
    df_f = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente'", conn)
    
    query_c = """
    SELECT UPPER(TRIM(centro_costo)) as cc, SUM(val) as total_neto FROM (
        SELECT centro_costo, valor_imputado as val FROM movimientos WHERE tipo LIKE 'Salida%'
        UNION ALL
        SELECT centro_costo, monto_imputado as val FROM facturas WHERE tipo = 'Gasto Vario'
    ) WHERE centro_costo IS NOT NULL AND centro_costo != '' GROUP BY cc
    """
    df_c = pd.read_sql_query(query_c, conn)
    conn.close()
    
    total_deuda = df_f['monto_total'].sum() if not df_f.empty else 0
    inicio_mes = hoy.replace(day=1)
    val_meses_ant = df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < inicio_mes]['monto_total'].sum() if not df_f.empty else 0
    val_vencidos_hoy = len(df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < hoy]) if not df_f.empty else 0
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Deuda Total", f"${f_puntos(total_deuda)}")
    
    with c2:
        st.markdown("Meses Anteriores")
        st.markdown(f"<h2 style='color: #FF0000; margin-top:-15px;'>${f_puntos(val_meses_ant)}</h2>", unsafe_allow_html=True)
    with c3:
        st.markdown("Vencidos Hoy")
        st.markdown(f"<h2 style='color: #FF8C00; margin-top:-15px;'>{val_vencidos_hoy}</h2>", unsafe_allow_html=True)
    c4.metric("Docs. Pendientes", len(df_f))

    st.markdown("---")
    col_izq, col_der = st.columns([1.2, 1])
    with col_izq:
        st.subheader("📅 Proyección de Pagos (4 Meses)")
        cols_p = st.columns(4); meses_n = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]
        for i in range(4):
            ft = (datetime.now().replace(day=1) + timedelta(days=i*31)).replace(day=1)
            m, a = ft.month, ft.year
            v = df_f[(pd.to_datetime(df_f['fecha_vencimiento']).dt.month == m) & (pd.to_datetime(df_f['fecha_vencimiento']).dt.year == a)]['monto_total'].sum() if not df_f.empty else 0
            cols_p[i].metric(f"{meses_n[m-1]} {a}", f"${f_puntos(v)}")
    with col_der:
        st.subheader("💰 Resumen Costos por Cuartel")
        if not df_c.empty:
            st.dataframe(df_c.style.format({"total_neto": "${:,.0f}"}), use_container_width=True)
        else: st.info("Sin costos registrados.")

def modulo_compras():
    st.header("📦 Compras y Gastos")
    t1, t2, t3 = st.tabs(["➕ Factura Insumos", "💸 Gasto Vario Proporcional", "🔍 Historial / Gestión"])
    
    with t1:
        c1, c2 = st.columns(2); nro, prov = c1.text_input("N° Factura"), c1.text_input("Proveedor"); fe, fv = c2.date_input("Emisión"), c2.date_input("Vencimiento")
        conn = conectar_db()
        df_inv = pd.read_sql_query("SELECT id, producto, stock, precio_medio FROM inventario ORDER BY producto", conn); conn.close()
        if not df_inv.empty:
            cp1, cp2, cp3, cp4 = st.columns([3,1,1,1]); ps = cp1.selectbox("Insumo", df_inv['id'].astype(str) + " - " + df_inv['producto']); ct, pr = cp2.number_input("Cant", min_value=0.01), cp3.number_input("Neto Un", min_value=0.0)
            if cp4.button("Añadir ➕", key="add_ins"):
                if 'car' not in st.session_state: st.session_state['car'] = []
                st.session_state['car'].append({'id': int(ps.split(" - ")[0]), 'n': ps.split(" - ")[1], 'c': ct, 'p': pr, 't': ct*pr}); st.rerun()
        if st.session_state.get('car'):
            df_car = pd.DataFrame(st.session_state['car']); st.table(df_car); total_f = st.number_input("Total Factura (IVA)", value=float(df_car['t'].sum()*1.19))
            if st.button("💾 GUARDAR FACTURA"):
                conn = conectar_db(); cur = conn.cursor()
                cur.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total) VALUES (?,?,?,?,?)", (nro, prov, fe, fv, total_f))
                for i in st.session_state['car']:
                    item = df_inv[df_inv['id'] == i['id']].iloc[0]
                    n_pmp = ((item['stock']*item['precio_medio']) + (i['c']*i['p'])) / (item['stock']+i['c']) if (item['stock']+i['c']) > 0 else i['p']
                    cur.execute("UPDATE inventario SET stock = stock + ?, precio_medio = ? WHERE id = ?", (i['c'], n_pmp, i['id']))
                conn.commit(); conn.close(); guardar_en_drive(); st.session_state['car'] = []; st.rerun()

    with t2:
        st.subheader("Gasto Vario con Prorrateo Automático")
        c1, c2 = st.columns(2); prov_g, nro_g = c1.text_input("Proveedor ", key="pg"), c2.text_input("N° Documento ", key="ng")
        detalles_g = st.text_area("Detalles / Concepto del Gasto", height=70)
        
        st.markdown("### 🏷️ ¿A qué cuarteles aplica este gasto?")
        ccs_seleccionados = []
        # Mostrar todos los CC con checkboxes en columnas
        cols_cc = st.columns(3)
        for idx, cc_name in enumerate(CENTROS_COSTO):
            if cols_cc[idx % 3].checkbox(cc_name, key=f"cb_{cc_name}"):
                ccs_seleccionados.append(cc_name)
        
        st.markdown("---")
        c_m1, c_m2 = st.columns(2)
        monto_neto_total = c_m1.number_input("Monto Neto Total ($)", min_value=0.0)
        iva_al_costo = c_m2.radio("¿Cargar IVA al costo de los cuarteles?", ["SÍ", "NO"])
        
        if len(ccs_seleccionados) > 0 and monto_neto_total > 0:
            monto_por_cc = monto_neto_total / len(ccs_seleccionados)
            imputacion_por_cc = monto_por_cc if iva_al_costo == "SÍ" else monto_por_cc / 1.19
            st.info(f"Se imputarán **${f_puntos(imputacion_por_cc)}** netos a cada uno de los {len(ccs_seleccionados)} cuarteles marcados.")
            
            if st.button("💾 GUARDAR GASTO PRORRATEADO"):
                conn = conectar_db()
                total_con_iva = monto_neto_total * 1.19
                # Documento principal para tesorería
                conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, concepto) VALUES (?,?,?,?,?,?,?)", 
                             (nro_g, prov_g, hoy, hoy, total_con_iva, 'Gasto Vario', detalles_g))
                # Imputaciones automáticas
                for cc in ccs_seleccionados:
                    conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, centro_costo, monto_imputado, concepto) VALUES (?,?,?,?,?,?,?,?,?)", 
                                 (nro_g + "_AUTO", prov_g, hoy, hoy, 0, 'Gasto Vario', cc.upper(), imputacion_por_cc, detalles_g))
                conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
        else:
            st.warning("Seleccione al menos un cuartel e ingrese el monto para procesar.")

    with t3:
        conn = conectar_db()
        rf = conn.execute("SELECT MIN(fecha_compra), MAX(fecha_compra) FROM facturas").fetchone()
        fmin = pd.to_datetime(rf[0]).date() if rf[0] else hoy-timedelta(days=365)
        fmax = pd.to_datetime(rf[1]).date() if rf[1] else hoy
        cf1, cf2 = st.columns(2)
        h1, h2 = cf1.date_input("Desde", fmin), cf2.date_input("Hasta", fmax)
        
        df_h = pd.read_sql_query(f"SELECT id, nro_documento, proveedor, fecha_compra, monto_total, estado, tipo, concepto FROM facturas WHERE monto_total > 0 AND fecha_compra BETWEEN '{h1}' AND '{h2}' ORDER BY fecha_compra DESC", conn)
        st.dataframe(df_h, use_container_width=True)
        if not df_h.empty:
            st.download_button("📥 PDF Historial", generar_pdf_blob(df_h, "HISTORIAL COMPRAS"), "historial.pdf")
            st.divider()
            id_sel = st.selectbox("ID Gestionar", df_h['id']); row = df_h[df_h['id'] == id_sel].iloc[0]
            mn, mm = st.text_input("Nuevo N° Doc", row['nro_documento']), st.number_input("Nuevo Monto Total", value=float(row['monto_total']))
            cl = st.text_input("Clave", type="password", key="cl_h")
            col1, col2 = st.columns(2)
            if col1.button("✏️ MODIFICAR") and cl == CLAVE_SEGURIDAD:
                conn.execute("UPDATE facturas SET nro_documento=?, monto_total=? WHERE id=?", (mn, mm, id_sel)); conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
            if col2.button("🗑️ ELIMINAR") and cl == CLAVE_SEGURIDAD:
                conn.execute("DELETE FROM facturas WHERE id=?", (id_sel,)); conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
        conn.close()

def modulo_tesoreria():
    st.header("💸 Tesorería")
    tp1, tp2, tp3 = st.tabs(["🔴 Pendientes General", "🏢 Por Proveedor", "📅 Rango de Vencimiento"])
    conn = conectar_db()
    def estilo_vencido(row): return ['background-color: #ffcccc' if pd.to_datetime(row['fecha_vencimiento']).date() < hoy else '' for _ in row]

    with tp1:
        df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' AND monto_total > 0 ORDER BY fecha_vencimiento ASC", conn)
        st.info(f"### 💰 DEUDA TOTAL PENDIENTE: ${f_puntos(df_p['monto_total'].sum() if not df_p.empty else 0)}")
        if not df_p.empty:
            st.dataframe(df_p.style.apply(estilo_vencido, axis=1).format({"monto_total": "${:,.0f}"}), use_container_width=True)
            id_p = st.selectbox("ID Pago", df_p['id']); met = st.selectbox("Medio", ["Transferencia", "Cheque", "Efectivo"])
            if st.button("💰 MARCAR PAGADO"):
                conn.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", (met, hoy, id_p)); conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
    with tp2:
        df_pr = pd.read_sql_query("SELECT DISTINCT proveedor FROM facturas WHERE estado='Pendiente' AND monto_total > 0", conn)
        if not df_pr.empty:
            p_sel = st.selectbox("Proveedor", df_pr['proveedor']); df_f = pd.read_sql_query(f"SELECT nro_documento, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' AND proveedor='{p_sel}' AND monto_total > 0 ORDER BY fecha_vencimiento ASC", conn)
            st.success(f"### 🏢 DEUDA CON {p_sel}: ${f_puntos(df_f['monto_total'].sum())}")
            st.dataframe(df_f.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
    with tp3:
        f1 = st.date_input("Vence Desde", datetime(2000, 1, 1)); f2 = st.date_input("Vence Hasta", datetime(2030, 12, 31))
        df_r = pd.read_sql_query(f"SELECT nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' AND monto_total > 0 AND fecha_vencimiento BETWEEN '{f1}' AND '{f2}' ORDER BY fecha_vencimiento ASC", conn)
        st.success(f"### 📅 DEUDA TOTAL EN RANGO: ${f_puntos(df_r['monto_total'].sum() if not df_r.empty else 0)}")
        if not df_r.empty: st.dataframe(df_r.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
    conn.close()

def modulo_bodega():
    st.header("🚜 Bodega")
    tb1, tb2, tb3, tb4 = st.tabs(["📊 Stock", "🔄 Movimientos", "➕ Nuevo Producto", "🔍 Consulta CC"])
    with tb1:
        conn = conectar_db(); df_s = pd.read_sql_query("SELECT id, producto, familia, stock, precio_medio FROM inventario ORDER BY producto ASC", conn)
        st.dataframe(df_s.style.format({"precio_medio": "${:,.2f}"}), use_container_width=True)
        if not df_s.empty:
            c1, c2 = st.columns(2); c1.download_button("📥 PDF Campo", generar_pdf_blob(df_s.drop(columns=['precio_medio']), "STOCK BODEGA"), "stock.pdf"); c2.download_button("💰 PDF Admin", generar_pdf_blob(df_s, "VALORIZACIÓN BODEGA", es_valorizado=True), "valor.pdf")
            st.divider(); id_ins = st.selectbox("ID Insumo", df_s['id']); item = df_s[df_s['id'] == id_ins].iloc[0]
            n_n, n_p = st.text_input("Nombre ", item['producto']), st.number_input("PMP ", value=float(item['precio_medio'])); cl = st.text_input("Clave ", type="password", key="cl_bod")
            if st.button("ACTUALIZAR BODEGA") and cl == CLAVE_SEGURIDAD:
                conn.execute("UPDATE inventario SET producto=?, precio_medio=? WHERE id=?", (n_n, n_p, id_ins)); conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
    with tb2:
        tipo = st.radio("Acción ", ["Salida (Campo)", "Entrada"])
        with st.form("form_mov"):
            conn = conectar_db(); df_i = pd.read_sql_query("SELECT id, producto, precio_medio FROM inventario", conn); conn.close()
            ps = st.selectbox("Producto ", df_i['id'].astype(str) + " - " + df_i['producto']); ct, cc = st.number_input("Cant ", min_value=0.01), st.selectbox("CC ", CENTROS_COSTO)
            if st.form_submit_button("REGISTRAR"):
                item = df_i[df_i['id'] == int(ps.split(" - ")[0])].iloc[0]; val_imp = ct * item['precio_medio'] if "Salida" in tipo else 0
                conn = conectar_db(); cur = conn.cursor(); cc_limpio = cc.strip().upper()
                cur.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado) VALUES (?,?,?,?,?,?)", (item['id'], tipo, ct, hoy, cc_limpio, val_imp))
                f = 1 if "Entrada" in tipo else -1; cur.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (ct*f, item['id']))
                conn.commit(); conn.close(); guardar_en_drive(); st.rerun()
    with tb4:
        cc_sel = st.selectbox("Consultar Cuartel ", CENTROS_COSTO); conn = conectar_db()
        df_cc = pd.read_sql_query(f"SELECT m.fecha, i.producto, m.tipo, m.cantidad, m.valor_imputado FROM movimientos m JOIN inventario i ON m.producto_id = i.id WHERE UPPER(TRIM(m.centro_costo)) = '{cc_sel.strip().upper()}' ORDER BY m.fecha DESC", conn); conn.close()
        if not df_cc.empty: st.dataframe(df_cc, use_container_width=True)

def modulo_costos():
    st.header("💰 Gestión de Costos Consolidados")
    conn = conectar_db()
    query_t = """
    SELECT UPPER(TRIM(centro_costo)) as cc, 
           SUM(CASE WHEN fuente = 'BODEGA' THEN val ELSE 0 END) as insumos,
           SUM(CASE WHEN fuente = 'FACTURA' THEN val ELSE 0 END) as gastos,
           SUM(val) as total
    FROM (
        SELECT centro_costo, valor_imputado as val, 'BODEGA' as fuente FROM movimientos WHERE tipo LIKE 'Salida%'
        UNION ALL
        SELECT centro_costo, monto_imputado as val, 'FACTURA' as fuente FROM facturas WHERE tipo = 'Gasto Vario'
    ) WHERE centro_costo IS NOT NULL AND centro_costo != '' GROUP BY cc
    """
    df_t = pd.read_sql_query(query_t, conn); conn.close()
    st.dataframe(df_t.style.format({"insumos": "${:,.0f}", "gastos": "${:,.0f}", "total": "${:,.0f}"}), use_container_width=True)
    if not df_t.empty: st.download_button("📥 PDF Costos", generar_pdf_blob(df_t, "COSTOS CONSOLIDADOS"), "costos.pdf")

# --- 5. NAVEGACIÓN ---
st.set_page_config(page_title="LA CONCEPCIÓN ERP v8.9", layout="wide")
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
