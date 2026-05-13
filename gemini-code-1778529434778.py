import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import os

# --- LIBRERÍAS DE PERSISTENCIA ---
try:
    from fpdf import FPDF
    from pydrive2.auth import GoogleAuth
    from pydrive2.drive import GoogleDrive
    from oauth2client.service_account import ServiceAccountCredentials
    PERSISTENCE_READY = True
except ImportError:
    PERSISTENCE_READY = False

# --- CONFIGURACIÓN DE PERSISTENCIA (Sincronización Drive) ---
ID_CARPETA_DRIVE = "1V7IwdbJPzxQ-hJQaVqOWejHHA1mNbgLo" # Tu ID de carpeta integrado
NOMBRE_DB = 'erp_concepcion_v6.db'
JSON_KEY = 'secretos.json'

def obtener_drive():
    scope = ['https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(JSON_KEY, scope)
    gauth = GoogleAuth()
    gauth.credentials = creds
    return GoogleDrive(gauth)

def descargar_de_drive():
    if not os.path.exists(JSON_KEY): return False
    try:
        drive = obtener_drive()
        query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
        lista = drive.ListFile({'q': query}).GetList()
        if lista:
            lista[0].GetContentFile(NOMBRE_DB)
            return True
    except Exception as e:
        print(f"Error descarga Drive: {e}")
        return False
    return False

def guardar_en_drive():
    if not os.path.exists(JSON_KEY): return False
    try:
        drive = obtener_drive()
        query = f"'{ID_CARPETA_DRIVE}' in parents and title='{NOMBRE_DB}' and trashed=false"
        lista = drive.ListFile({'q': query}).GetList()
        if lista:
            f = lista[0]
        else:
            f = drive.CreateFile({'title': NOMBRE_DB, 'parents': [{'id': ID_CARPETA_DRIVE}]})
        f.SetContentFile(NOMBRE_DB)
        f.Upload()
        return True
    except Exception as e:
        print(f"Error subida Drive: {e}")
        return False

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="AGRICOLA LA CONCEPCION ERP", page_icon="🚜", layout="wide")

# RECUPERACIÓN AUTOMÁTICA AL INICIAR
if 'db_sincronizada' not in st.session_state:
    if descargar_de_drive():
        st.toast("✅ Base de datos recuperada de Google Drive", icon="☁️")
    else:
        st.toast("⚠️ Trabajando con base de datos local", icon="💻")
    st.session_state['db_sincronizada'] = True

# --- SEGURIDAD Y FORMATO ---
CLAVE_SEGURIDAD = "2908"

def f_puntos(valor):
    try: return f"{int(valor):,}".replace(",", ".")
    except: return "0"

# --- FUNCIONES BASE DE DATOS ---
def conectar_db(): return sqlite3.connect(NOMBRE_DB)

def inicializar_db():
    conn = conectar_db(); cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS facturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nro_documento TEXT, proveedor TEXT, 
        fecha_compra DATE, fecha_vencimiento DATE, monto_neto REAL, monto_total REAL, 
        estado TEXT DEFAULT 'Pendiente', tipo TEXT DEFAULT 'Factura',
        metodo_pago TEXT, fecha_pago DATE)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS detalle_facturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, factura_id INTEGER, producto_id INTEGER, 
        cantidad REAL, precio_neto REAL, total_linea REAL)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS inventario (
        id INTEGER PRIMARY KEY AUTOINCREMENT, producto TEXT, familia TEXT, stock REAL DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS movimientos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, producto_id INTEGER, tipo TEXT, 
        cantidad REAL, centro_costo TEXT, bodega TEXT, fecha DATE, factura_id INTEGER)''')
    conn.commit(); conn.close()

def eliminar_factura(id_f):
    conn = conectar_db(); cursor = conn.cursor()
    detalles = cursor.execute("SELECT producto_id, cantidad FROM detalle_facturas WHERE factura_id=?", (id_f,)).fetchall()
    for p_id, cant in detalles:
        cursor.execute("UPDATE inventario SET stock = stock - ? WHERE id = ?", (cant, p_id))
    cursor.execute("DELETE FROM movimientos WHERE factura_id=?", (id_f,))
    cursor.execute("DELETE FROM detalle_facturas WHERE factura_id=?", (id_f,))
    cursor.execute("DELETE FROM facturas WHERE id=?", (id_f,))
    conn.commit(); conn.close()
    guardar_en_drive() # Sincronizar el borrado

inicializar_db()
if 'carrito' not in st.session_state: st.session_state['carrito'] = []

# --- SIDEBAR ---
with st.sidebar:
    st.title("LA CONCEPCIÓN ERP")
    if os.path.exists(JSON_KEY):
        st.success("☁️ Conectado a Google Drive")
    else:
        st.error("⚠️ Sin archivo secretos.json")
    
    st.markdown("---")
    menu = st.radio("Navegación", ["🏠 Dashboard", "📦 Compras", "💸 Tesorería", "🚜 Bodega"])
    st.markdown("---")
    if st.button("🗑️ Vaciar Carrito Insumos"):
        st.session_state['carrito'] = []; st.rerun()

# --- 1. DASHBOARD ---
if menu == "🏠 Dashboard":
    st.header("📊 Estado Financiero")
    conn = conectar_db(); df_f = pd.read_sql_query("SELECT * FROM facturas WHERE estado='Pendiente'", conn); conn.close()
    c1, c2 = st.columns(2)
    total_deuda = df_f['monto_total'].sum() if not df_f.empty else 0
    c1.metric("Deuda por Pagar", f"${f_puntos(total_deuda)}")
    vencidos = 0
    if not df_f.empty:
        hoy = datetime.now().date()
        vencidos = df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < hoy].shape[0]
    c2.metric("Documentos Vencidos", vencidos, delta_color="inverse")

# --- 2. COMPRAS ---
elif menu == "📦 Compras":
    st.header("Ingreso de Documentos")
    t1, t2, t3 = st.tabs(["➕ Nueva Factura", "💸 Gasto Directo", "🔍 Historial"])
    
    with t1:
        c1, c2 = st.columns(2)
        nro = c1.text_input("N° Documento")
        prov = c1.text_input("Proveedor")
        f_c = c2.date_input("Fecha Emisión", datetime.now())
        f_v = c2.date_input("Fecha Vencimiento", datetime.now() + timedelta(days=30))
        
        conn = conectar_db()
        df_inv = pd.read_sql_query("SELECT id, producto FROM inventario ORDER BY producto", conn)
        conn.close()
        
        if not df_inv.empty:
            st.subheader("Detalle de Insumos")
            cp1, cp2, cp3, cp4 = st.columns([3,1,1,1])
            p_sel = cp1.selectbox("Seleccionar Insumo", df_inv['id'].astype(str) + " - " + df_inv['producto'])
            cant = cp2.number_input("Cantidad", min_value=0.1)
            prec = cp3.number_input("Precio Neto", min_value=0.0)
            if cp4.button("➕ Añadir"):
                st.session_state['carrito'].append({
                    'id': int(p_sel.split(" - ")[0]),
                    'nombre': p_sel.split(" - ")[1],
                    'cantidad': cant,
                    'precio': prec,
                    'total': cant * prec
                })
                st.rerun()

        if st.session_state['carrito']:
            df_c = pd.DataFrame(st.session_state['carrito'])
            st.table(df_c[['nombre', 'cantidad', 'precio', 'total']])
            monto_neto = df_c['total'].sum()
            iva = monto_neto * 0.19
            total_calc = monto_neto + iva
            
            st.write(f"**Neto:** ${f_puntos(monto_neto)} | **IVA:** ${f_puntos(iva)} | **Total Sugerido:** ${f_puntos(total_calc)}")
            monto_final = st.number_input("Monto Total Final (Ajuste Manual)", value=float(total_calc))
            
            if st.button("💾 CONFIRMAR Y GUARDAR FACTURA"):
                if nro and prov:
                    conn = conectar_db(); cursor = conn.cursor()
                    cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_neto, monto_total, tipo) VALUES (?,?,?,?,?,?,?)",
                                 (nro, prov, f_c, f_v, monto_neto, monto_final, 'Factura'))
                    f_id = cursor.lastrowid
                    for i in st.session_state['carrito']:
                        cursor.execute("INSERT INTO detalle_facturas (factura_id, producto_id, cantidad, precio_neto, total_linea) VALUES (?,?,?,?,?)",
                                     (f_id, i['id'], i['cantidad'], i['precio'], i['total']))
                        cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (i['cantidad'], i['id']))
                    conn.commit(); conn.close()
                    guardar_en_drive() # SINCRONIZACIÓN AUTOMÁTICA
                    st.session_state['carrito'] = []
                    st.success("✅ Factura guardada y respaldada en Drive")
                    st.rerun()

    with t2:
        with st.form("gasto_v"):
            st.subheader("Gasto Rápido (Sin Inventario)")
            g1, g2 = st.columns(2)
            g_prov = g1.text_input("Proveedor/Beneficiario")
            g_doc = g1.text_input("N° Boleta/Comprobante")
            g_monto = g2.number_input("Monto Total", min_value=0.0)
            g_fecha = g2.date_input("Fecha Gasto")
            if st.form_submit_button("💾 GUARDAR GASTO"):
                if g_prov and g_monto > 0:
                    conn = conectar_db(); cursor = conn.cursor()
                    cursor.execute("INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, estado) VALUES (?,?,?,?,?,?,?)",
                                 (g_doc, g_prov, g_fecha, g_fecha, g_monto, 'Gasto Vario', 'Pendiente'))
                    conn.commit(); conn.close()
                    guardar_en_drive() # SINCRONIZACIÓN AUTOMÁTICA
                    st.success("✅ Gasto registrado y respaldado")
                    st.rerun()

    with t3:
        conn = conectar_db()
        df_h = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_compra, monto_total, tipo, estado FROM facturas ORDER BY id DESC", conn)
        conn.close()
        st.dataframe(df_h, use_container_width=True)
        st.divider()
        c_del1, c_del2, c_del3 = st.columns([1,1,2])
        id_borrar = c_del1.number_input("ID a eliminar", min_value=0, step=1)
        pass_del = c_del2.text_input("Clave de Seguridad", type="password")
        if c_del3.button("❌ ELIMINAR REGISTRO"):
            if pass_del == CLAVE_SEGURIDAD:
                eliminar_factura(id_borrar)
                st.warning(f"Registro {id_borrar} eliminado")
                st.rerun()

# --- 3. TESORERIA ---
elif menu == "💸 Tesorería":
    st.header("Cuentas por Pagar")
    conn = conectar_db()
    df_p = pd.read_sql_query("SELECT id, nro_documento, proveedor, fecha_vencimiento, monto_total FROM facturas WHERE estado='Pendiente'", conn)
    if not df_p.empty:
        st.dataframe(df_p.style.format({"monto_total": "${:,.0f}"}), use_container_width=True)
        c1, c2, c3 = st.columns(3)
        id_p = c1.selectbox("ID a Pagar", df_p['id'])
        metodo = c2.selectbox("Método de Pago", ["Transferencia", "Cheque", "Efectivo", "Tarjeta"])
        if c3.button("💰 MARCAR COMO PAGADO"):
            cursor = conn.cursor()
            cursor.execute("UPDATE facturas SET estado='Pagado', metodo_pago=?, fecha_pago=? WHERE id=?", 
                         (metodo, datetime.now().date(), id_p))
            conn.commit(); conn.close()
            guardar_en_drive() # SINCRONIZACIÓN
            st.success(f"Documento {id_p} pagado")
            st.rerun()
    else:
        st.info("No hay cuentas pendientes.")
    conn.close()

# --- 4. BODEGA ---
elif menu == "🚜 Bodega":
    st.header("Control de Inventario")
    tb1, tb2, tb3 = st.tabs(["📊 Stock Actual", "🔄 Movimientos", "➕ Configurar Insumos"])
    
    with tb1:
        conn = conectar_db()
        df_s = pd.read_sql_query("SELECT id, producto, familia, stock FROM inventario", conn)
        conn.close()
        st.dataframe(df_s, use_container_width=True)
        
    with tb2:
        with st.form("mov"):
            conn = conectar_db(); prods = pd.read_sql_query("SELECT id, producto FROM inventario", conn); conn.close()
            p_m = st.selectbox("Insumo", prods['id'].astype(str) + " - " + prods['producto'])
            t_m = st.radio("Tipo Movimiento", ["Salida (Uso en Campo)", "Entrada (Ajuste)"])
            c_m = st.number_input("Cantidad", min_value=0.1)
            cc_m = st.text_input("Centro de Costo / Cuartel")
            if st.form_submit_button("REGISTRAR MOVIMIENTO"):
                id_prod = int(p_m.split(" - ")[0])
                conn = conectar_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo) VALUES (?,?,?,?,?)",
                             (id_prod, t_m, c_m, datetime.now().date(), cc_m))
                factor = 1 if t_m == "Entrada (Ajuste)" else -1
                cursor.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (c_m * factor, id_prod))
                conn.commit(); conn.close()
                guardar_en_drive() # SINCRONIZACIÓN
                st.success("Movimiento registrado")
                st.rerun()

    with tb3:
        with st.form("nuevo_p"):
            st.subheader("Crear Nuevo Insumo")
            nom_p = st.text_input("Nombre del Producto")
            fam_p = st.selectbox("Familia", ["Fertilizante", "Herbicida", "Insecticida", "Fungicidas", "Bio estimulante", "Petróleo", "Otros"])
            if st.form_submit_button("➕ CREAR PRODUCTO"):
                if nom_p:
                    conn = conectar_db(); cursor = conn.cursor()
                    cursor.execute("INSERT INTO inventario (producto, familia, stock) VALUES (?,?,0)", (nom_p, fam_p))
                    conn.commit(); conn.close()
                    guardar_en_drive() # SINCRONIZACIÓN
                    st.success(f"Producto {nom_p} creado")
                    st.rerun()
