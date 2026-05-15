import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import os
import hashlib
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

# --- 2. MOTOR DE BASE DE DATOS Y SEGURIDAD ---
def conectar_db():
    return sqlite3.connect(NOMBRE_DB)

def hash_password(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

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
    cursor.execute("""CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, password TEXT)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS log_accesos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, fecha_hora DATETIME)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS petroleo (
        id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT, litros REAL, proveedor TEXT, 
        monto_total_compra REAL, vehiculo TEXT, responsable TEXT, centro_costo TEXT, fecha DATE, valor_imputado REAL)""")
    
    usuarios = [
        ('osvaldolira@laconcepcion.cl', hash_password('9083')),
        ('secretaria@laconcepcion.cl', hash_password('9111')),
        ('secretarialaconcepcion2@gmail.com', hash_password('5678'))
    ]
    cursor.execute("DELETE FROM usuarios") 
    for email, pw in usuarios:
        cursor.execute("INSERT INTO usuarios (email, password) VALUES (?,?)", (email, pw))
    conn.commit(); conn.close()

# --- 3. UTILIDADES ---
def f_puntos(v):
    try: return f"{int(round(float(v))):,}".replace(",", ".")
    except: return "0"

def f_decimal(v):
    try: return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return "0,00"

def generar_pdf_blob(df, titulo, incluir_precios=True):
    try:
        pdf = FPDF(); pdf.add_page(); pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, "AGRICOLA LA CONCEPCIÓN", ln=True, align="C")
        pdf.set_font("Helvetica", "B", 12); pdf.cell(0, 10, titulo, ln=True, align="C")
        pdf.ln(5); pdf.set_font("Helvetica", "B", 8)
        columnas_finales = df.columns
        if not incluir_precios:
            columnas_finales = [c for c in df.columns if "precio" not in c.lower() and "valor" not in c.lower() and "monto" not in c.lower()]
        df_pdf = df[columnas_finales]
        cols = df_pdf.columns; w = 190 / len(cols)
        for col in cols: pdf.cell(w, 8, str(col).upper(), border=1, align="C")
        pdf.ln(); pdf.set_font("Helvetica", "", 7); total_acum = 0
        for _, row in df_pdf.iterrows():
            for i, item in enumerate(row):
                col_name = df_pdf.columns[i].lower()
                if any(x in col_name for x in ["monto", "total", "valor", "imputado"]):
                    try: total_acum += float(item)
                    except: pass
                if any(x in col_name for x in ["cantidad", "stock", "litros"]): val = f_decimal(item)
                elif any(x in col_name for x in ["monto", "total", "precio", "valor"]): val = f_puntos(item)
                else: val = str(item)
                pdf.cell(w, 7, val[:25], border=1)
            pdf.ln()
        if incluir_precios and total_acum > 0:
            pdf.set_font("Helvetica", "B", 9); pdf.cell(w * (len(cols)-1), 8, "TOTAL FINAL:", border=1, align="R")
            pdf.cell(w, 8, f"${f_puntos(total_acum)}", border=1, align="L")
        return pdf.output(dest="S").encode("latin-1")
    except: return None

# --- DRIVE ---
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
    if drive:
        query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
        lista = drive.ListFile({'q': query}).GetList()
        f = lista[0] if lista else drive.CreateFile({'title': NOMBRE_DB, 'parents': [{'id': ID_CARPETA_DRIVE}]})
        f.SetContentFile(NOMBRE_DB); f.Upload()
        st.success("✅ Respaldo en Drive sincronizado.")

def descargar_de_drive():
    drive = obtener_drive()
    if drive:
        query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
        lista = drive.ListFile({'q': query}).GetList()
        if lista: lista[0].GetContentFile(NOMBRE_DB)

# --- ESTILOS ---
def inyectar_css():
    st.markdown("""<style>
        .main { background-color: #f4f7f6; }
        .stMetric { background-color: white; padding: 20px; border-radius: 12px; border-left: 6px solid #2E7D32; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }
        h1, h2, h3 { color: #1B5E20; font-family: 'Arial'; }
        .stButton>button { border-radius: 8px; background-color: #2E7D32; color: white; font-weight: bold; }
        </style>""", unsafe_allow_html=True)

# --- LOGIN ---
def login_page():
    inyectar_css()
    st.markdown("<h1 style='text-align: center; color: #1B5E20; margin-top: 50px;'>🚜 ERP La Concepción</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        with st.form("login_form"):
            e = st.text_input("Email Corporativo")
            p = st.text_input("Contraseña", type="password")
            if st.form_submit_button("ACCEDER AL SISTEMA"):
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("SELECT email FROM usuarios WHERE email=? AND password=?", (e, hash_password(p)))
                if cursor.fetchone():
                    cursor.execute("INSERT INTO log_accesos (email, fecha_hora) VALUES (?,?)", (e, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                    conn.commit(); conn.close()
                    st.session_state['logged_in'] = True; st.session_state['email'] = e; st.rerun()
                else: conn.close(); st.error("Email o clave incorrectos.")

# --- MÓDULOS ---
def modulo_dashboard():
    inyectar_css()
    st.markdown("<h1>🚜 ERP Agrícola La Concepción</h1>", unsafe_allow_html=True)
    conn = conectar_db(); df_f = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente'", conn)
    df_p_c = pd.read_sql_query("SELECT SUM(litros) as l FROM petroleo WHERE tipo='Carga'", conn); df_p_s = pd.read_sql_query("SELECT SUM(litros) as l FROM petroleo WHERE tipo='Salida'", conn)
    saldo_pet = (df_p_c['l'].fillna(0).iloc[0]) - (df_p_s['l'].fillna(0).iloc[0])
    query_c = "SELECT UPPER(TRIM(centro_costo)) as cc, SUM(monto_imputado) as total_neto FROM (SELECT centro_costo, valor_imputado as monto_imputado FROM movimientos WHERE tipo LIKE 'Salida%' UNION ALL SELECT centro_costo, monto_imputado FROM facturas WHERE tipo = 'Gasto Vario' AND centro_costo != '' UNION ALL SELECT centro_costo, valor_imputado as monto_imputado FROM petroleo WHERE tipo = 'Salida') WHERE cc IS NOT NULL AND cc != '' GROUP BY cc"
    df_c = pd.read_sql_query(query_c, conn)
    t_d = df_f['monto_total'].sum() if not df_f.empty else 0
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("DEUDA TOTAL", f"${f_puntos(t_d)}"); c4.metric("DOCS. PENDIENTES", f"{len(df_f)}"); c5.metric("SALDO PETRÓLEO", f"{f_decimal(saldo_pet)} Lts")
    st.divider()
    col1, col2 = st.columns([1.5, 1])
    with col1:
        st.subheader("💰 Resumen Costos por Cuartel")
        if not df_c.empty:
            df_res = pd.concat([df_c, pd.DataFrame([{"cc": "TOTAL GENERAL", "total_neto": df_c["total_neto"].sum()}])], ignore_index=True)
            st.dataframe(df_res.style.format({"total_neto": "${:,.0f}"}), use_container_width=True)
    with col2:
        st.subheader("📅 Proyección Mensual (4 Meses)")
        meses = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]
        for i in range(4):
            ft = (datetime.now().replace(day=1) + timedelta(days=i*31)).replace(day=1)
            v = df_f[(pd.to_datetime(df_f['fecha_vencimiento']).dt.month == ft.month) & (pd.to_datetime(df_f['fecha_vencimiento']).dt.year == ft.year)]['monto_total'].sum() if not df_f.empty else 0
            st.markdown(f"<div style='background:white; padding:12px; border-radius:10px; margin-bottom:8px; display:flex; justify-content:space-between; border:1px solid #ddd;'><b>{meses[ft.month-1]} {ft.year}</b> <span style='color:#2E7D32;'>${f_puntos(v)}</span></div>", unsafe_allow_html=True)
    conn.close()

def modulo_petroleo():
    st.header("⛽ Gestión de Petróleo")
    tp1, tp2, tp3 = st.tabs(["📥 Carga", "🚜 Salida", "📊 Historial"]); conn = conectar_db()
    df_c = pd.read_sql_query("SELECT SUM(litros) as l, SUM(monto_total_compra) as m FROM petroleo WHERE tipo='Carga'", conn); df_s = pd.read_sql_query("SELECT SUM(litros) as l FROM petroleo WHERE tipo='Salida'", conn)
    saldo = (df_c['l'].fillna(0).iloc[0]) - (df_s['l'].fillna(0).iloc[0]); pmp_p = (df_c['m'].fillna(0).iloc[0] / df_c['l'].fillna(1).iloc[0])
    st.sidebar.metric("LITROS EN ESTANQUE", f"{f_decimal(saldo)} Lts")
    with tp1:
        with st.form("p_carga"):
            lts = st.number_input("Litros", 0.0); prov = st.text_input("Proveedor"); mt = st.number_input("Total ($)", 0.0); fec = st.date_input("Fecha", hoy)
            if st.form_submit_button("💾 REGISTRAR"):
                conn.execute("INSERT INTO petroleo (tipo, litros, proveedor, monto_total_compra, fecha) VALUES (?,?,?,?,?)", ("Carga", lts, prov, mt, fec)); conn.commit(); guardar_en_drive(); st.rerun()
    with tp2:
        with st.form("p_salida"):
            lts_s = st.number_input("Litros", 0.0); vehi = st.text_input("Vehículo"); ccs_p = []
            cols = st.columns(3)
            for i, cc_n in enumerate(CENTROS_COSTO):
                if cols[i%3].checkbox(cc_n, key=f"p_cc_{cc_n}"): ccs_p.append(cc_n)
            if st.form_submit_button("⛽ REGISTRAR"):
                if lts_s <= saldo and ccs_p:
                    for c in ccs_p: conn.execute("INSERT INTO petroleo (tipo, litros, vehiculo, centro_costo, fecha, valor_imputado) VALUES (?,?,?,?,?,?)", ("Salida", lts_s/len(ccs_p), vehi, c.upper(), hoy, (lts_s*pmp_p)/len(ccs_p)))
                    conn.commit(); guardar_en_drive(); st.rerun()
    with tp3:
        st.dataframe(pd.read_sql_query("SELECT * FROM petroleo ORDER BY id DESC", conn), use_container_width=True)
    conn.close()

def modulo_compras():
    st.header("📦 Compras e Historial")
    t1, t2, t3 = st.tabs(["➕ Insumos", "💸 Gasto Vario", "🔍 Historial"]); conn = conectar_db()
    with t1:
        c1, c2 = st.columns(2); nro, prov = c1.text_input("N° Factura"), c1.text_input("Proveedor"); fe, fv = c2.date_input("Emisión"), c2.date_input("Vencimiento")
        df_inv = pd.read_sql_query("SELECT id, producto, precio_medio FROM inventario", conn)
        ps = st.selectbox("Insumo", df_inv['id'].astype(str) + " - " + df_inv['producto']) if not df_inv.empty else None
        ct, pr = st.number_input("Cant", 0.0), st.number_input("Neto", 0.0)
        if st.button("Añadir ➕") and ps:
            if 'car' not in st.session_state: st.session_state['car'] = []
            st.session_state['car'].append({'id': int(ps.split(" - ")[0]), 'n': ps.split(" - ")[1], 'c': ct, 'p': pr, 't': ct*pr}); st.rerun()
        if st.session_state.get('car'):
            st.table(pd.DataFrame(st.session_state['car'])); total_f = st.number_input("Total (IVA)", value=float(pd.DataFrame(st.session_state['car'])['t'].sum()*1.19))
            if st.button("💾 GUARDAR FACTURA"):
                conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total) VALUES (?,?,?,?,?)", (nro, prov, fe, fv, total_f))
                for i in st.session_state['car']:
                    conn.execute("UPDATE inventario SET stock = stock + ?, precio_medio = (stock*precio_medio + ?)/(stock+?) WHERE id = ?", (i['c'], i['t'], i['c'], i['id']))
                conn.commit(); guardar_en_drive(); st.session_state['car'] = []; st.rerun()
    with t2:
        prov_g, nro_g = st.text_input("Proveedor ", key="pg"), st.text_input("N° Doc ", key="ng")
        detalles_g = st.text_area("Concepto"); ccs_sel = []
        cols = st.columns(3)
        for i, cc in enumerate(CENTROS_COSTO):
            if cols[i%3].checkbox(cc, key=f"gv_{cc}"): ccs_sel.append(cc)
        m_n = st.number_input("Neto Total", 0.0); iva = st.radio("IVA al costo?", ["SÍ", "NO"])
        if st.button("💾 GUARDAR GASTO"):
            if m_n > 0:
                total_con_iva = m_n * 1.19
                # LÓGICA DE IVA SOLUCIONADA: Si IVA al costo es NO, imputamos el NETO. Si es SÍ, el TOTAL.
                monto_a_imputar = total_con_iva if iva == "SÍ" else m_n
                if ccs_sel:
                    imp_individual = monto_a_imputar / len(ccs_sel)
                    conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, concepto) VALUES (?,?,?,?,?,?,?)", (nro_g, prov_g, hoy, hoy, total_con_iva, 'Gasto Vario', detalles_g))
                    for c in ccs_sel: conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, centro_costo, monto_imputado, concepto) VALUES (?,?,?,?,?,?,?,?,?)", (nro_g+"_P", prov_g, hoy, hoy, 0, 'Gasto Vario', c.upper(), imp_individual, detalles_g))
                else:
                    conn.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, concepto, centro_costo, monto_imputado) VALUES (?,?,?,?,?,?,?,?,?)", (nro_g, prov_g, hoy, hoy, total_con_iva, 'Gasto Vario', detalles_g, "", 0))
                conn.commit(); guardar_en_drive(); st.rerun()
    with t3:
        f1, f2 = st.date_input("Desde", datetime(2020, 1, 1).date()), st.date_input("Hasta", datetime(2030, 12, 31).date())
        df_h = pd.read_sql_query(f"SELECT * FROM facturas WHERE monto_total > 0 AND fecha_compra BETWEEN '{f1}' AND '{f2}' ORDER BY id DESC", conn)
        st.dataframe(df_h, use_container_width=True)
        if not df_h.empty:
            id_doc = st.selectbox("ID a gestionar", df_h['id'])
            sel = df_h[df_h['id'] == id_doc]
            if not sel.empty:
                item = sel.iloc[0]; n_nro = st.text_input("N° Doc", item['nro_documento']); n_m = st.number_input("Monto", value=float(item['monto_total']))
                cl = st.text_input("Clave", type="password")
                b1, b2 = st.columns(2)
                if b1.button("✏️ MODIFICAR") and cl == CLAVE_MAESTRA:
                    conn.execute("UPDATE facturas SET nro_documento=?, monto_total=? WHERE id=?", (n_nro, n_m, id_doc)); conn.commit(); guardar_en_drive(); st.rerun()
                if b2.button("🗑️ ELIMINAR") and cl == CLAVE_MAESTRA:
                    # ELIMINACIÓN LIMPIA: Se borra el documento Y sus imputaciones de costo asociadas
                    conn.execute("DELETE FROM facturas WHERE id=?", (id_doc,))
                    conn.execute("DELETE FROM facturas WHERE nro_documento=? AND proveedor=?", (item['nro_documento']+"_P", item['proveedor']))
                    conn.commit(); guardar_en_drive(); st.rerun()
    conn.close()

def modulo_tesoreria():
    st.header("💸 Tesorería")
    tp1, tp2, tp3 = st.tabs(["🔴 Pendientes", "🏢 Proveedor", "📅 Rango"]); conn = conectar_db()
    with tp1:
        df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente' AND monto_total > 0", conn)
        st.dataframe(df_p, use_container_width=True)
        id_p = st.selectbox("ID Pago", df_p['id']) if not df_p.empty else None
        if st.button("💰 PAGAR") and id_p:
            conn.execute("UPDATE facturas SET estado='Pagado', fecha_pago=? WHERE id=?", (hoy, id_p)); conn.commit(); guardar_en_drive(); st.rerun()
    with tp2:
        p_sel = st.selectbox("Proveedor", pd.read_sql_query("SELECT DISTINCT proveedor FROM facturas", conn))
        st.dataframe(pd.read_sql_query(f"SELECT * FROM facturas WHERE proveedor='{p_sel}'", conn), use_container_width=True)
    with tp3:
        f1, f2 = st.date_input("Vence desde", hoy), st.date_input("Vence hasta", hoy+timedelta(30))
        st.dataframe(pd.read_sql_query(f"SELECT * FROM facturas WHERE fecha_vencimiento BETWEEN '{f1}' AND '{f2}'", conn), use_container_width=True)
    conn.close()

def modulo_bodega():
    st.header("🚜 Bodega")
    tb1, tb2, tb3, tb4 = st.tabs(["📊 Stock", "🔄 Movimientos", "➕ Nuevo", "🔍 Consulta CC"]); conn = conectar_db()
    with tb1:
        df_s = pd.read_sql_query("SELECT id, producto, familia, stock, precio_medio FROM inventario", conn)
        st.dataframe(df_s.drop(columns=['id']), use_container_width=True)
        c1, c2 = st.columns(2)
        c1.download_button("📥 PDF Admin", generar_pdf_blob(df_s.drop(columns=['id']), "STOCK ADMIN", True), "stock_admin.pdf")
        c2.download_button("📥 PDF Trabajador", generar_pdf_blob(df_s.drop(columns=['id']), "STOCK LISTA", False), "stock_trabajador.pdf")
        st.divider(); id_g = st.selectbox("ID Insumo", df_s['id']); it = df_s[df_s['id']==id_g].iloc[0]
        n_nom = st.text_input("Nombre", it['producto']); n_st = st.number_input("Stock", value=float(it['stock']))
        cl = st.text_input("Clave Autorización", type="password")
        if st.button("✏️ EDITAR") and cl == CLAVE_MAESTRA:
            conn.execute("UPDATE inventario SET producto=?, stock=? WHERE id=?", (n_nom, n_st, id_g)); conn.commit(); guardar_en_drive(); st.rerun()
    with tb2:
        tipo = st.radio("Acción", ["Salida (Campo)", "Entrada"])
        df_i = pd.read_sql_query("SELECT id, producto, precio_medio FROM inventario", conn)
        ps = st.selectbox("Insumo", df_i['id'].astype(str) + " - " + df_i['producto']); ct = st.number_input("Cantidad", 0.0)
        ccs_mov = []
        if tipo == "Salida (Campo)":
            cols = st.columns(3)
            for i, cc_n in enumerate(CENTROS_COSTO):
                if cols[i%3].checkbox(cc_n, key=f"m_cc_{cc_n}"): ccs_mov.append(cc_n)
        if st.button("REGISTRAR"):
            iid = int(ps.split(" - ")[0]); pmp = df_i[df_i['id']==iid]['precio_medio'].values[0]
            if tipo == "Salida (Campo)" and ccs_mov:
                for c in ccs_mov: conn.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado) VALUES (?,?,?,?,?,?)", (iid, tipo, ct/len(ccs_mov), hoy, c.upper(), (ct*pmp)/len(ccs_mov)))
                conn.execute("UPDATE inventario SET stock = stock - ? WHERE id = ?", (ct, iid))
            else: conn.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (ct, iid))
            conn.commit(); guardar_en_drive(); st.rerun()
    with tb3:
        with st.form("n_i"):
            nom, fam, st_i, pr_i = st.text_input("Nombre"), st.selectbox("Familia", FAMILIAS_PRODUCTOS), st.number_input("Stock", 0.0), st.number_input("PMP", 0.0)
            if st.form_submit_button("CREAR"): conn.execute("INSERT INTO inventario (producto, familia, stock, precio_medio) VALUES (?,?,?,?)", (nom, fam, st_i, pr_i)); conn.commit(); guardar_en_drive(); st.rerun()
    with tb4:
        cc_s = st.selectbox("Cuartel", CENTROS_COSTO)
        df_cc = pd.read_sql_query(f"SELECT m.fecha, i.producto, m.tipo, m.cantidad, m.valor_imputado FROM movimientos m JOIN inventario i ON m.producto_id = i.id WHERE m.centro_costo = '{cc_s.upper()}'", conn)
        st.dataframe(df_cc, use_container_width=True)
        if not df_cc.empty: st.download_button("📥 PDF CC", generar_pdf_blob(df_cc, f"GASTOS {cc_s}"), f"costos_{cc_s}.pdf")
    conn.close()

def modulo_costos():
    st.header("💰 Costos Totales")
    conn = conectar_db()
    query = "SELECT UPPER(TRIM(centro_costo)) as cc, SUM(CASE WHEN fuente = 'BODEGA' THEN val ELSE 0 END) as insumos, SUM(CASE WHEN fuente = 'FACTURA' THEN val ELSE 0 END) as gastos, SUM(CASE WHEN fuente = 'PETROLEO' THEN val ELSE 0 END) as combustible, SUM(val) as total FROM (SELECT centro_costo, valor_imputado as val, 'BODEGA' as fuente FROM movimientos WHERE tipo LIKE 'Salida%' AND centro_costo != '' UNION ALL SELECT centro_costo, monto_imputado as val, 'FACTURA' as fuente FROM facturas WHERE tipo = 'Gasto Vario' AND centro_costo != '' UNION ALL SELECT centro_costo, valor_imputado as val, 'PETROLEO' as fuente FROM petroleo WHERE tipo = 'Salida' AND centro_costo != '') GROUP BY cc"
    df_t = pd.read_sql_query(query, conn); conn.close()
    if not df_t.empty: st.dataframe(df_t.style.format({"insumos": "${:,.0f}", "gastos": "${:,.0f}", "combustible": "${:,.0f}", "total": "${:,.0f}"}), use_container_width=True)

# --- NAVEGACIÓN ---
st.set_page_config(page_title="ERP LA CONCEPCIÓN v10.8.16", layout="wide")
inicializar_db()
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if not st.session_state['logged_in']: login_page()
else:
    if 'init' not in st.session_state: descargar_de_drive(); st.session_state['init'] = True
    with st.sidebar:
        st.title("MENÚ")
        menu = st.radio("", ["🏠 Dashboard", "⛽ PETRÓLEO", "📦 Compras", "💸 Tesorería", "🚜 Bodega", "💰 COSTOS"])
        if st.button("🚀 Sincronizar"): guardar_en_drive()
        if st.button("🚪 Salir"): st.session_state.clear(); st.rerun()
    if menu == "🏠 Dashboard": modulo_dashboard()
    elif menu == "⛽ PETRÓLEO": modulo_petroleo()
    elif menu == "📦 Compras": modulo_compras()
    elif menu == "💸 Tesorería": modulo_tesoreria()
    elif menu == "🚜 Bodega": modulo_bodega()
    elif menu == "💰 COSTOS": modulo_costos()
