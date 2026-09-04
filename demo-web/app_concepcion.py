import streamlit as st
import streamlit.components.v1 as components
import sqlite3
import pandas as pd
from datetime import datetime, timedelta, date
import calendar
import os
import base64
import hashlib
import html as html_lib
import manual_contenido
from erp_correo_html import smtp_from_header
from erp_rut import validar_rut_campo
from erp_pdf_ui import boton_descarga_pdf
from erp_petroleo_planilla import defaults_planilla_petroleo, generar_pdf_planilla_maestra_petroleo
from erp_flujo_financiero import (
    armar_flujo_financiero,
    cargar_ingresos_cc,
    df_flujo_para_pdf,
    fila_total_flujo_mensual,
    guardar_ingresos_cc,
    iter_meses_rango,
    meses_flujo_desde_hoy,
    migrar_flujo_financiero,
    resumen_desde_matriz_costos,
    cargar_notas_ingresos_cc,
    cargar_saldo_caja_inicial,
    guardar_saldo_caja_inicial,
    _mes_label,
)
from erp_ui_nav import nav_seccion, nav_temporada
from erp_login_remember import (
    aplicar_usuario_recordado_en_formulario,
    guardar_usuario_recordado,
    limpiar_login_usuario_corrupto,
    preparar_usuario_recordado,
    reiniciar_lectura_recordado,
    _email_valido,
)
from erp_maquinaria import (
    TIPOS_MAQUINARIA_APLICACION,
    TIPOS_MAQUINARIA_PETROLEO,
    TIPOS_MAQUINARIA_TRACTOR,
    aplicar_badge_menu_maquinaria,
    enriquecer_columna_maquinaria,
    estilo_historial_maquinaria,
    inyectar_css_tabs_maquinaria,
    migrar_maestra_maquinaria,
    opciones_filtro_maquinaria,
    render_admin_tab_maestra_maquinaria,
    render_panel_cerrar_casos_maquinaria,
    render_select_maquinaria,
    render_tab_asignacion_faena_diaria,
    render_widget_petroleo_maquinaria,
    _codigos_maquinaria_en_reparacion,
)
from erp_contratistas import (
    excluir_contratista_de_maestra_proveedores,
    fechas_consulta_contratistas_cc,
    listar_contratistas,
    migrar_contratistas_contacto,
    query_cuenta_corriente_contratista,
    query_imputaciones_contratistas_cc,
    sql_filtro_tipo_gasto_contratista,
    tipo_gasto_canonico_contratista,
)
from erp_inventario_ia import (
    guardar_ingrediente_producto,
    migrar_inventario_ingrediente_activo,
    poblar_ingredientes_inventario,
    resolver_ingrediente_activo,
)
from erp_proveedores import (
    enviar_correo_pago_proveedor_si_corresponde,
    mensaje_avisos_pago_proveedor,
    migrar_maestra_proveedores,
    render_admin_tab_maestra_proveedores,
    render_info_contacto_proveedor,
    render_select_proveedor,
)
from erp_whatsapp import enviar_whatsapp_pago_si_corresponde
from pppl_catalogo_sag import buscar_referencia_sag, requiere_autorizacion_pppl, etiqueta_estado_auditoria
from fpdf import FPDF
import requests
import io
import xml.etree.ElementTree as ET
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import time
import fcntl
import re
import json
import unicodedata

# 1. CONFIGURACIÓN DE PÁGINA (wide en escritorio; sidebar auto colapsa en móvil)
_LOGO_FAVICON = "/root/static/logo_concepcion.png"
st.set_page_config(
    page_title="ERP La Concepcion",
    page_icon=_LOGO_FAVICON if os.path.exists(_LOGO_FAVICON) else "🍒",
    layout="wide",
    initial_sidebar_state="auto",
)

# 2. ANULADOR DE BLOQUEOS (OBLIGA A MOSTRAR LA FLECHA Y EL HEADER)
st.markdown(
    """
    <style>
        /* Desbloquea el header y lo obliga a ser visible */
        header {
            visibility: visible !important;
            display: block !important;
            height: auto !important;
        }
        /* Desbloquea la flecha superior izquierda y la obliga a aparecer */
        .stSidebarCollapsedControl {
            display: flex !important;
            visibility: visible !important;
            background-color: #2e7d32 !important;
            border-radius: 4px !important;
        }
        .stSidebarCollapsedControl svg {
            fill: white !important;
            color: white !important;
        }
    </style>
    """,
    unsafe_allow_html=True
)

# 3. PARCHE DE TRACCIÓN PARA LA FLECHA DE NAVEGACIÓN (SIEMPRE VISIBLE)
st.markdown(
    """
    <style>
        /* Fuerza a que el botón nativo de apertura de la sidebar sea visible y tenga color verde */
        .stSidebarCollapsedControl button {
            background-color: #2e7d32 !important;
            color: white !important;
            border-radius: 4px !important;
            display: flex !important;
        }
        .stSidebarCollapsedControl svg {
            fill: white !important;
        }
    </style>
    """,
    unsafe_allow_html=True
)

# =============================================================================
# 1. CONFIGURACIÓN, CONSTANTES Y MOTOR HORARIO (CHILE UTC-4)
# =============================================================================
NOMBRE_DB = os.environ.get("ERP_DB") or os.environ.get("ERP_DEMO_DB") or "erp_concepcion_v6.db"
SECRETS_PATH = os.environ.get("ERP_SECRETS") or os.environ.get("ERP_DEMO_SECRETS") or "/root/.streamlit/secrets.toml"
NOMBRE_ERP = "ERP Agrícola La Concepción"
TENANT_SLUG = "concepcion"
TENANT_NOMBRE = "La Concepción"
LOGO_DIR = "/root/static"
CLAVE_MAESTRA = "2908" 
IMPUESTO_ESPECIFICO_LITRO = 75 
CORREOS_TESORERIA_DEFAULT = (
    "osvaldolirac@gmail.com",
    "secretaria@laconcepcion.cl",
    "secretarialaconcepcion2@gmail.com",
)
ROLES_USUARIO = ("admin", "operador", "certificacion", "lector")
SUPER_ADMIN_EMAILS = frozenset({"osvaldolira@laconcepcion.cl"})
PROD_URL = "https://erpmaster.cl"
PROD_URL_ALT = "https://erpmaster.cl/laconcepcion"
AGRICOLA_LOGIN_URL = os.environ.get("ERP_AGRICOLA_LOGIN_URL", "https://erpmaster.cl/agricola/login")
PERFILES_USUARIO_TXT = {
    "admin": "Administrador",
    "operador": "Operador",
    "certificacion": "Certificación GlobalGAP",
    "lector": "Lector",
}
MENU_COMPLETO = [
    ("🏠 DASHBOARD", "DASHBOARD"),
    ("📦 COMPRAS", "Compras"),
    ("💸 TESORERÍA", "Tesoreria"),
    ("📈 FLUJO FINANCIERO", "Flujo financiero"),
    ("💰 COSTOS", "Costos"),
    ("👥 RRHH", "RRHH"),
    ("🏡 EL ESPINO", "Espino"),
    ("📒 LIBRO DE CAMPO", "Libro de Campo"),
    ("⛽ PETRÓLEO", "Petróleo"),
    ("💧 RIEGO", "Riego"),
    ("🏠 BODEGA", "Bodega"),
    ("🚜 MAQUINARIA", "Maquinaria"),
    ("🌿 GLOBALGAP", "GlobalGAP"),
    ("🎫 SOPORTE", "Soporte"),
    ("📖 MANUAL", "Manual"),
]
MENU_CERTIFICACION = [
    ("🌿 GLOBALGAP", "GlobalGAP"),
    ("📒 LIBRO DE CAMPO", "Libro de Campo"),
    ("🏠 BODEGA", "Bodega"),
]

def ruta_logo_empresa():
    try:
        from demo_web.services.branding import logo_path_for_pdf

        found = logo_path_for_pdf()
        if found:
            return found
    except Exception:
        pass
    slug = ""
    try:
        from demo_web.services.branding import resolve_tenant_slug

        slug = resolve_tenant_slug()
    except Exception:
        pass
    if slug == "espino":
        return None
    for nombre in ("logo_concepcion.png", "logo_concepcion.jpg", "logo_concepcion.jpeg", "logo_concepcion.svg"):
        ruta = os.path.join(LOGO_DIR, nombre)
        if os.path.exists(ruta):
            return ruta
    return None

def logo_img_html(ancho=220, clase="logo-empresa"):
    ruta = ruta_logo_empresa()
    if not ruta:
        return ""
    alt = (TENANT_NOMBRE or NOMBRE_ERP or "ERP Agrícola").strip()
    try:
        with open(ruta, "rb") as f:
            data = f.read()
        if ruta.endswith(".svg"):
            b64 = base64.b64encode(data).decode()
            src = f"data:image/svg+xml;base64,{b64}"
        else:
            mime = "image/png" if ruta.endswith(".png") else "image/jpeg"
            b64 = base64.b64encode(data).decode()
            src = f"data:{mime};base64,{b64}"
        return (
            f'<img src="{src}" class="{clase}" '
            f'style="max-width:{ancho}px;width:100%;height:auto;display:block;margin:0 auto;" '
            f'alt="{html_lib.escape(alt)}" />'
        )
    except Exception:
        return ""

def _uri_icono_cierre_sesion():
    candidatos = (
        "/root/static/icon_logout_transparent.png",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "icon_logout_transparent.png"),
        "/root/static/icon_logout.png",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "icon_logout.png"),
    )
    for path in candidatos:
        uri = _archivo_a_data_uri(path)
        if uri:
            return uri
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" fill="none">'
        '<rect x="7" y="5" width="21" height="38" rx="2.5" stroke="#C62828" stroke-width="2.6"/>'
        '<rect x="10.5" y="9" width="14.5" height="30" rx="1.2" fill="#E53935"/>'
        '<circle cx="22" cy="24" r="1.7" fill="#FFCDD2"/>'
        '<path d="M31 24h13M42 24l-5.5-5.5M42 24l-5.5 5.5" stroke="#C62828" '
        'stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>'
        '</svg>'
    )
    return f"data:image/svg+xml;base64,{base64.b64encode(svg.encode('utf-8')).decode()}"

LOGIN_BG_FILES = ("bg_cerezo.png", "bg_cerezas.png", "bg_bodega.png")

def _ruta_login_bg_dir():
    candidatos = [
        "/root/static/login",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "login"),
    ]
    for d in candidatos:
        if os.path.isdir(d) and os.path.exists(os.path.join(d, LOGIN_BG_FILES[0])):
            return d
    return candidatos[0]

def _archivo_a_data_uri(path):
    if not path or not os.path.exists(path):
        return ""
    try:
        with open(path, "rb") as f:
            data = f.read()
        mime = "image/png" if path.lower().endswith(".png") else "image/jpeg"
        return f"data:{mime};base64,{base64.b64encode(data).decode()}"
    except Exception:
        return ""

def _ruta_bg_maquinaria():
    candidatos = (
        "/root/static/bg_maquinaria.jpg",
        "/root/static/bg_maquinaria.png",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "bg_maquinaria.jpg"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "bg_maquinaria.png"),
    )
    for path in candidatos:
        if os.path.exists(path):
            return path
    return candidatos[0]

def inyectar_fondo_maquinaria():
    uri = _archivo_a_data_uri(_ruta_bg_maquinaria())
    if not uri:
        return
    st.markdown(
        f"""
        <div class="maq-bg-marker"></div>
        <div class="maq-bg-photo" aria-hidden="true" style="
            position:fixed; inset:0; z-index:0; pointer-events:none;
            background-image:url('{uri}');
            background-size:cover; background-position:center; background-repeat:no-repeat;
            opacity:0.48;
        "></div>
        <div class="maq-bg-scrim" aria-hidden="true" style="
            position:fixed; inset:0; z-index:0; pointer-events:none;
            background:linear-gradient(180deg, rgba(248,251,248,0.35) 0%, rgba(243,246,244,0.55) 100%);
        "></div>
        <style>
        .stApp:has(.maq-bg-marker) [data-testid="stAppViewContainer"],
        .stApp:has(.maq-bg-marker) [data-testid="stAppViewContainer"] > .main,
        .stApp:has(.maq-bg-marker) [data-testid="stAppViewContainer"] .main .block-container {{
            background: transparent !important;
        }}
        .stApp:has(.maq-bg-marker) [data-testid="stSidebar"],
        .stApp:has(.maq-bg-marker) [data-testid="stSidebar"] > div:first-child {{
            background: linear-gradient(180deg, #FFFFFF 0%, #F7FBF7 100%) !important;
        }}
        .stApp:has(.maq-bg-marker) [data-testid="stAppViewContainer"] > .main {{
            position: relative !important;
            z-index: 1 !important;
        }}
        .stApp:has(.maq-bg-marker) [data-testid="stSidebar"] {{
            position: relative !important;
            z-index: 2 !important;
        }}
        .stApp:has(.maq-bg-marker) .main [data-testid="stTabs"] [data-baseweb="tab-list"] {{
            width: 100% !important;
            max-width: 100% !important;
        }}
        .stApp:has(.maq-bg-marker) .main [data-testid="stTabs"] > div:last-child,
        .stApp:has(.maq-bg-marker) .main [data-testid="stTabs"] [data-baseweb="tab-panel"] {{
            width: 100% !important;
            max-width: 100% !important;
        }}
        .stApp:has(.maq-bg-marker) .main [data-testid="stTabs"]:has([data-baseweb="tab"]:nth-child(2)[aria-selected="true"]) > div:first-child,
        .stApp:has(.maq-bg-marker) .main [data-testid="stTabs"]:has([data-baseweb="tab"]:nth-child(2)[aria-selected="true"]) [data-baseweb="tab-list"] {{
            width: 33.33% !important;
            max-width: 33.33% !important;
            min-width: 280px !important;
        }}
        .stApp:has(.maq-bg-marker) .main [data-testid="stTabs"]:has([data-baseweb="tab"]:nth-child(2)[aria-selected="true"]) [data-baseweb="tab"] {{
            padding: 0.45rem 0.6rem !important;
            font-size: 0.82rem !important;
            white-space: nowrap !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

def _ruta_bg_dashboard():
    candidatos = (
        "/root/static/bg_dashboard.jpg",
        "/root/static/bg_dashboard.png",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "bg_dashboard.jpg"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "bg_dashboard.png"),
    )
    for path in candidatos:
        if os.path.exists(path):
            return path
    return candidatos[0]

def inyectar_fondo_dashboard():
    uri = _archivo_a_data_uri(_ruta_bg_dashboard())
    if not uri:
        return
    st.markdown(
        f"""
        <div class="dash-bg-marker"></div>
        <div class="dash-bg-photo" aria-hidden="true" style="
            position:fixed; inset:0; z-index:0; pointer-events:none;
            background-image:url('{uri}');
            background-size:cover; background-position:center; background-repeat:no-repeat;
            opacity:0.48;
        "></div>
        <div class="dash-bg-scrim" aria-hidden="true" style="
            position:fixed; inset:0; z-index:0; pointer-events:none;
            background:linear-gradient(180deg, rgba(248,251,248,0.35) 0%, rgba(243,246,244,0.55) 100%);
        "></div>
        <style>
        .stApp:has(.dash-bg-marker),
        .stApp:has(.dash-bg-marker) [data-testid="stAppViewContainer"],
        .stApp:has(.dash-bg-marker) [data-testid="stAppViewContainer"] > .main,
        .stApp:has(.dash-bg-marker) [data-testid="stAppViewContainer"] .main .block-container {{
            background: transparent !important;
        }}
        .stApp:has(.dash-bg-marker) [data-testid="stAppViewContainer"] > .main {{
            position: relative !important;
            z-index: 1 !important;
        }}
        .stApp:has(.dash-top-stack) [data-testid="stAppViewContainer"] .main .block-container {{
            padding-top: 0 !important;
        }}
        .stApp:has(.dash-top-stack) .main [data-testid="stVerticalBlock"] {{
            gap: 0.25rem !important;
        }}
        .stApp:has(.dash-bg-marker) [data-testid="stSidebar"] {{
            position: relative !important;
            z-index: 2 !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

def _ruta_bg_libro_campo():
    candidatos = (
        "/root/static/bg_libro_campo.jpg",
        "/root/static/bg_libro_campo.png",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "bg_libro_campo.jpg"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "bg_libro_campo.png"),
    )
    for path in candidatos:
        if os.path.exists(path):
            return path
    return candidatos[0]

def inyectar_fondo_libro_campo():
    uri = _archivo_a_data_uri(_ruta_bg_libro_campo())
    if not uri:
        return
    st.markdown(
        f"""
        <div class="lc-bg-marker"></div>
        <div class="lc-bg-photo" aria-hidden="true" style="
            position:fixed; inset:0; z-index:0; pointer-events:none;
            background-image:url('{uri}');
            background-size:cover; background-position:center; background-repeat:no-repeat;
            opacity:0.48;
        "></div>
        <div class="lc-bg-scrim" aria-hidden="true" style="
            position:fixed; inset:0; z-index:0; pointer-events:none;
            background:linear-gradient(180deg, rgba(248,251,248,0.35) 0%, rgba(243,246,244,0.55) 100%);
        "></div>
        <style>
        .stApp:has(.lc-bg-marker),
        .stApp:has(.lc-bg-marker) [data-testid="stAppViewContainer"],
        .stApp:has(.lc-bg-marker) [data-testid="stAppViewContainer"] > .main,
        .stApp:has(.lc-bg-marker) [data-testid="stAppViewContainer"] .main .block-container {{
            background: transparent !important;
        }}
        .stApp:has(.lc-bg-marker) [data-testid="stAppViewContainer"] > .main {{
            position: relative !important;
            z-index: 1 !important;
        }}
        .stApp:has(.lc-bg-marker) [data-testid="stSidebar"] {{
            position: relative !important;
            z-index: 2 !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

def inyectar_css_login_pantalla():
    bg_dir = _ruta_login_bg_dir()
    uris = [_archivo_a_data_uri(os.path.join(bg_dir, n)) for n in LOGIN_BG_FILES]
    st.markdown(
        f"""
        <style>
        header[data-testid="stHeader"] {{ visibility: hidden !important; height: 0 !important; min-height: 0 !important; }}
        footer {{ visibility: hidden !important; }}
        [data-testid="stAppViewContainer"]:has(.login-bg-marker) > .main {{
            background: transparent !important;
        }}
        [data-testid="stAppViewContainer"]:has(.login-bg-marker) .main .block-container {{
            padding: 0 1.25rem 0 !important;
            max-width: 100% !important;
        }}
        [data-testid="stAppViewContainer"]:has(.login-bg-marker) [data-testid="stMainBlockContainer"] {{
            gap: 0 !important;
        }}
        .login-bg-grid {{
            position: fixed; inset: 0; z-index: 0;
            display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
            pointer-events: none;
        }}
        .login-bg-grid > div {{
            background-size: cover; background-position: center; min-height: 100vh;
            border-right: 1px solid rgba(0, 0, 0, 0.12);
        }}
        .login-bg-grid > div:nth-child(1) {{ background-image: url("{uris[0]}"); }}
        .login-bg-grid > div:nth-child(2) {{ background-image: url("{uris[1]}"); }}
        .login-bg-grid > div:nth-child(3) {{ background-image: url("{uris[2]}"); }}
        .login-bg-grid > div:last-child {{ border-right: none; }}
        .login-scrim {{
            position: fixed; inset: 0; z-index: 1; pointer-events: none;
            background: linear-gradient(180deg, rgba(0,0,0,0.35) 0%, rgba(0,0,0,0.25) 45%, rgba(0,0,0,0.45) 100%);
        }}
        .login-hero-fixed {{
            position: fixed; z-index: 5; left: 50%; top: 50%;
            transform: translate(-50%, -50%); text-align: center;
            width: min(560px, 92vw); pointer-events: none;
            color: #ffffff !important;
            text-shadow: 0 2px 16px rgba(0, 0, 0, 0.55);
        }}
        .login-hero-fixed .logo-login {{
            filter: drop-shadow(0 8px 24px rgba(0,0,0,0.35));
            margin-bottom: 1.25rem !important;
        }}
        .login-logo-corner {{
            position: fixed; z-index: 6; top: 0.55rem; left: 0.2rem;
            pointer-events: none; max-width: min(380px, 42vw);
        }}
        .login-logo-corner .logo-login {{
            display: block !important;
            width: 100% !important;
            max-width: 380px !important;
            height: auto !important;
            margin: 0 !important;
            filter: drop-shadow(0 4px 16px rgba(0, 0, 0, 0.35));
        }}
        [data-testid="stAppViewContainer"]:has(.login-bg-marker) .login-hero-fixed h1,
        .login-hero-fixed h1 {{
            color: #ffffff !important;
            -webkit-text-fill-color: #ffffff !important;
            font-size: clamp(2rem, 5.5vw, 2.85rem) !important;
            font-weight: 800 !important;
            letter-spacing: 0.03em !important;
            line-height: 1.15 !important;
            text-shadow: 0 2px 20px rgba(0, 0, 0, 0.65) !important;
            margin-bottom: 0.55rem !important;
        }}
        [data-testid="stAppViewContainer"]:has(.login-bg-marker) .login-hero-fixed p,
        .login-hero-fixed p {{
            color: #ffffff !important;
            -webkit-text-fill-color: #ffffff !important;
            font-size: clamp(1.1rem, 2.5vw, 1.35rem) !important;
            font-weight: 500 !important;
            text-shadow: 0 2px 14px rgba(0, 0, 0, 0.55) !important;
            margin: 0 0 0.9rem !important;
            opacity: 1 !important;
        }}
        .login-hero-fixed .prod-badge, .login-hero-fixed .demo-badge {{
            display: inline-block; margin-top: 0.25rem;
            padding: 0.4rem 1rem; border-radius: 999px;
            background: rgba(255, 255, 255, 0.18); color: #ffffff !important;
            font-size: 0.9rem; font-weight: 700; border: 1px solid rgba(255, 255, 255, 0.55);
            box-shadow: 0 4px 16px rgba(0,0,0,0.25);
            text-shadow: none;
        }}
        [data-testid="stAppViewContainer"]:has(.login-bg-marker) [data-testid="stHorizontalBlock"] {{
            position: fixed !important; top: 0.45rem !important; right: 0.45rem !important;
            width: min(340px, calc(100vw - 1rem)) !important; max-width: calc(100vw - 1rem) !important;
            z-index: 1000 !important; gap: 0.75rem !important;
            align-items: flex-end !important; margin: 0 !important;
            left: auto !important; transform: none !important;
        }}
        [data-testid="stAppViewContainer"]:has(.login-bg-marker) [data-testid="stHorizontalBlock"] > div:first-child {{
            display: none !important;
        }}
        [data-testid="stAppViewContainer"]:has(.login-bg-marker) [data-testid="stHorizontalBlock"] > div:last-child {{
            width: auto !important; flex: 0 0 auto !important; min-width: 0 !important;
            display: flex !important; flex-direction: column !important; align-items: flex-end !important;
        }}
        [data-testid="stAppViewContainer"]:has(.login-bg-marker) [data-testid="stHorizontalBlock"] [data-testid="stButton"] {{
            width: auto !important;
        }}
        [data-testid="stAppViewContainer"]:has(.login-bg-marker) [class*="st-key-login_toggle"] [data-testid="stButton"] > button,
        [data-testid="stAppViewContainer"]:has(.login-bg-marker) [class*="st-key-login_toggle"] button[kind="primary"],
        [data-testid="stAppViewContainer"]:has(.login-bg-marker) [class*="st-key-login_toggle"] button[data-testid="stBaseButton-primary"] {{
            width: auto !important; min-width: 11rem !important;
            padding: 0.9rem 2rem !important; min-height: 3.5rem !important;
            border-radius: 999px !important;
            background: linear-gradient(135deg, #43A047, #1B5E20) !important;
            background-color: #1B5E20 !important;
            border: 2px solid rgba(255, 255, 255, 0.55) !important;
            box-shadow: 0 10px 32px rgba(0, 0, 0, 0.45), 0 0 0 1px rgba(27, 94, 32, 0.35) !important;
            color: #ffffff !important;
        }}
        [data-testid="stAppViewContainer"]:has(.login-bg-marker) [class*="st-key-login_toggle"] [data-testid="stButton"] > button:hover,
        [data-testid="stAppViewContainer"]:has(.login-bg-marker) [class*="st-key-login_toggle"] button[kind="primary"]:hover {{
            background: linear-gradient(135deg, #4CAF50, #2E7D32) !important;
            background-color: #2E7D32 !important;
            color: #ffffff !important;
            box-shadow: 0 12px 36px rgba(0, 0, 0, 0.5) !important;
        }}
        [data-testid="stAppViewContainer"]:has(.login-bg-marker) [class*="st-key-login_toggle"] [data-testid="stButton"] > button p,
        [data-testid="stAppViewContainer"]:has(.login-bg-marker) [class*="st-key-login_toggle"] [data-testid="stButton"] > button span,
        [data-testid="stAppViewContainer"]:has(.login-bg-marker) [class*="st-key-login_toggle"] [data-testid="stButton"] > button div {{
            color: #ffffff !important;
            -webkit-text-fill-color: #ffffff !important;
            font-size: 1.35rem !important;
            font-weight: 800 !important;
            letter-spacing: 0.05em !important;
        }}
        [data-testid="stAppViewContainer"]:has(.login-bg-marker) [data-testid="stHorizontalBlock"] [data-testid="stForm"] {{
            background: rgba(255,255,255,0.94) !important;
            backdrop-filter: blur(14px);
            border: 1px solid rgba(255,255,255,0.65) !important;
            border-radius: 16px !important;
            padding: 1.25rem 1.35rem 1.1rem !important;
            box-shadow: 0 16px 48px rgba(0,0,0,0.28) !important;
            width: min(320px, calc(100vw - 1.5rem)) !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

def _login_fondo_html(hero_inner_html, logo_html=""):
    logo_block = f'<div class="login-logo-corner">{logo_html}</div>' if logo_html else ""
    return f"""
    <div class="login-bg-marker"></div>
    <div class="login-bg-grid" aria-hidden="true"><div></div><div></div><div></div></div>
    <div class="login-scrim" aria-hidden="true"></div>
    {logo_block}
    <div class="login-hero-fixed">{hero_inner_html}</div>
    """

TEMAS_MODULO = {
    "DASHBOARD": {"color": "#1B5E20", "claro": "#E8F5E9", "sub": "Panel de control y métricas operativas"},
    "Petróleo": {"color": "#E65100", "claro": "#FFF3E0", "sub": "Control de cargas, salidas y saldo en estanque"},
    "Riego": {"color": "#0277BD", "claro": "#E1F5FE", "sub": "Registro de riego y fertilización por huerto"},
    "Compras": {"color": "#6A1B9A", "claro": "#F3E5F5", "sub": "Insumos, gastos operacionales e historial de compras"},
    "Tesoreria": {"color": "#C62828", "claro": "#FFEBEE", "sub": "Deudas pendientes, pagos y auditoría"},
    "Flujo financiero": {"color": "#006064", "claro": "#E0F7FA", "sub": "Ingresos, egresos proyectados y EERR de la temporada"},
    "RRHH": {"color": "#1565C0", "claro": "#E3F2FD", "sub": "Personal, remuneraciones y liquidaciones"},
    "Bodega": {"color": "#EF6C00", "claro": "#FFF8E1", "sub": "Stock, salidas e inventario por cuartel"},
    "Espino": {"color": "#558B2F", "claro": "#F1F8E9", "sub": "Registro y seguimiento de gastos El Espino"},
    "Libro de Campo": {"color": "#2E7D32", "claro": "#E8F5E9", "sub": "Aplicaciones fitosanitarias y registro agrícola"},
    "Maquinaria": {"color": "#5D4037", "claro": "#EFEBE9", "sub": "Mantenciones y bitácora de equipos"},
    "Costos": {"color": "#0D47A1", "claro": "#E3F2FD", "sub": "Consolidado de costos por cuartel"},
    "Administracion": {"color": "#37474F", "claro": "#ECEFF1", "sub": "Usuarios, permisos y bitácora del sistema"},
    "GlobalGAP": {"color": "#00695C", "claro": "#E0F2F1", "sub": "Certificación, trazabilidad y cumplimiento IFA"},
    "Manual": {"color": "#455A64", "claro": "#ECEFF1", "sub": "Guía de uso del sistema"},
}

def hora_chile():
    """Retorna la hora actual ajustada a Chile Continental (UTC-4)"""
    return datetime.utcnow() - timedelta(hours=4)

def parse_modulos_usuario(mod_str):
    if mod_str is None or not str(mod_str).strip():
        return None
    return [m.strip() for m in str(mod_str).split(",") if m.strip()]

def _slug_email_modulos(email):
    return re.sub(r"[^a-zA-Z0-9_]", "_", str(email or ""))

def _sync_checkboxes_modulos_operador(ue_mod, mod_act, menu_completo):
    """Precarga checkboxes al cambiar operador (Streamlit no refresca value= solo)."""
    slug = _slug_email_modulos(ue_mod)
    todos = [key for _, key in menu_completo]
    activos = todos if mod_act is None else mod_act
    if st.session_state.get("_seg_mod_loaded_for") != ue_mod:
        st.session_state["_seg_mod_loaded_for"] = ue_mod
        pref = "seg_chk_mod_"
        slug_pref = f"{pref}{slug}_"
        for sk in list(st.session_state.keys()):
            if isinstance(sk, str) and sk.startswith(pref) and not sk.startswith(slug_pref):
                del st.session_state[sk]
        for _lbl, mkey in menu_completo:
            st.session_state[f"{pref}{slug}_{mkey}"] = mkey in activos
    return slug

def _invalidar_sync_modulos_operador():
    st.session_state.pop("_seg_mod_loaded_for", None)

def construir_menu_rol(rol, modulos_txt=None):
    if rol == "admin":
        opts = {lbl: key for lbl, key in MENU_COMPLETO if key != "Soporte"}
        opts["⚙️ ADMINISTRACIÓN"] = "Administracion"
        return opts
    if rol == "certificacion":
        return dict(MENU_CERTIFICACION)
    asignados = parse_modulos_usuario(modulos_txt)
    if not asignados:
        return dict(MENU_COMPLETO)
    opts = {lbl: key for lbl, key in MENU_COMPLETO if key in asignados}
    if "Manual" not in opts.values():
        opts["📖 MANUAL"] = "Manual"
    if "Soporte" not in opts.values():
        opts["🎫 SOPORTE"] = "Soporte"
    return opts if opts else dict(MENU_COMPLETO)

def construir_menu_usuario(email, rol, conn=None):
    cerrar = False
    if conn is None:
        conn = conectar_db()
        cerrar = True
    if rol in ("operador", "lector"):
        row = conn.execute("SELECT modulos FROM usuarios WHERE email=?", (email,)).fetchone()
        modulos_txt = row[0] if row else None
        opts = construir_menu_rol(rol, modulos_txt)
    else:
        opts = construir_menu_rol(rol)
    if cerrar:
        conn.close()
    return opts

def es_admin():
    return st.session_state.get("rol") == "admin"

def es_super_admin():
    email = (st.session_state.get("email") or "").strip().lower()
    return email in SUPER_ADMIN_EMAILS

def es_certificacion():
    return st.session_state.get("rol") == "certificacion"

def es_solo_lectura():
    return _sesion_requiere_solo_lectura()


def _sesion_requiere_solo_lectura():
    """True si la sesión actual no puede escribir en la BD (lector o casilla solo lectura)."""
    try:
        if not st.session_state.get("logged_in"):
            return False
        if st.session_state.get("rol") == "admin":
            return False
        if st.session_state.get("rol") == "lector":
            return True
        return bool(st.session_state.get("solo_lectura"))
    except Exception:
        return False


def _ruta_db_abs():
    return os.path.abspath(NOMBRE_DB)

def sincronizar_perfil_sesion():
    """Recarga rol y solo_lectura desde la BD en cada request (evita sesión obsoleta)."""
    if not st.session_state.get("logged_in"):
        return
    email = st.session_state.get("email", "")
    if not email:
        return
    conn = sqlite3.connect(NOMBRE_DB, timeout=30)
    try:
        row = conn.execute(
            "SELECT COALESCE(rol,'operador'), COALESCE(solo_lectura,0) FROM usuarios WHERE lower(email)=lower(?)",
            (email,),
        ).fetchone()
    finally:
        conn.close()
    if row:
        rol_db = row[0] if row[0] in ROLES_USUARIO else "operador"
        st.session_state["rol"] = rol_db
        st.session_state["solo_lectura"] = bool(row[1]) or rol_db == "lector"
    else:
        st.session_state["rol"] = "operador"
        st.session_state["solo_lectura"] = False

def texto_perfil_sidebar(rol):
    rol_txt = PERFILES_USUARIO_TXT.get(rol, rol)
    if es_solo_lectura() and rol not in ("lector", "admin"):
        rol_txt = f"{rol_txt} · solo lectura"
    return rol_txt

def puede_gestionar_pppl():
    if es_solo_lectura():
        return False
    return st.session_state.get("rol") in ("admin", "certificacion")

def puede_acceder_modulo(modulo_key):
    email = st.session_state.get("email", "")
    rol = st.session_state.get("rol", "operador")
    opts = construir_menu_usuario(email, rol)
    return modulo_key in opts.values()

class _FechaHoy:
    """date dinámico Chile: gunicorn no debe congelar el día al importar el módulo."""

    __slots__ = ()

    def _v(self):
        return hora_chile().date()

    def __repr__(self):
        return repr(self._v())

    def __str__(self):
        return str(self._v())

    def __format__(self, spec):
        return format(self._v(), spec)

    def __hash__(self):
        return hash(self._v())

    def __reduce__(self):
        d = self._v()
        return (type(d), (d.year, d.month, d.day))

    def __eq__(self, other):
        return self._v() == other

    def __ne__(self, other):
        return self._v() != other

    def __lt__(self, other):
        return self._v() < other

    def __le__(self, other):
        return self._v() <= other

    def __gt__(self, other):
        return self._v() > other

    def __ge__(self, other):
        return self._v() >= other

    def __add__(self, other):
        return self._v() + other

    def __radd__(self, other):
        return other + self._v()

    def __sub__(self, other):
        return self._v() - other

    def __rsub__(self, other):
        return other - self._v()

    def __getattr__(self, name):
        return getattr(self._v(), name)


hoy = _FechaHoy()

FAMILIAS_PRODUCTOS_DEFAULT = [
    "FERTILIZANTE", "FERTILIZANTE FOLIAR", "HERBICIDA", "INSECTICIDA", "FUNGICIDA",
    "BIO ESTIMULANTE", "ACARICIDA", "REGULADOR DE CRECIMIENTO", "ADHERENTE / MOJANTE", "OTROS",
]
UNIDADES_MEDIDA_INSUMO = ["gr", "kg", "lt", "ml"]
DEFAULT_UNIDAD_INSUMO = "kg"


def _convertir_um(valor, desde, hacia):
    if desde == hacia:
        return float(valor)
    v = float(valor)
    if desde == "kg" and hacia == "gr":
        return v * 1000.0
    if desde == "gr" and hacia == "kg":
        return v * 0.001
    if desde == "lt" and hacia == "ml":
        return v * 1000.0
    if desde == "ml" and hacia == "lt":
        return v * 0.001
    return v


def _sql_um_movimiento(alias_m="m", alias_i="i"):
    return f"COALESCE({alias_m}.unidad_medida, {alias_i}.unidad_medida, '{DEFAULT_UNIDAD_INSUMO}')"


def _um_producto_inventario(conn, producto):
    row = conn.execute(
        "SELECT COALESCE(unidad_medida, ?) FROM inventario WHERE UPPER(TRIM(producto))=UPPER(TRIM(?))",
        (DEFAULT_UNIDAD_INSUMO, str(producto or "").strip()),
    ).fetchone()
    return str(row[0]) if row else DEFAULT_UNIDAD_INSUMO

RAZONES_SOCIALES_COMPRAS = ["La Concepción", "El Espino", "Carlos Lira"]
CENTROS_COSTO = ["CEREZOS CORTE 1", "CEREZOS CORTE 2", "CIRUELOS", "NOGALES APARICION", "NOGALES CRUZ DEL SUR", "EL ESPINO", "OTROS"]
METODOS_PAGO_TESORERIA = ["Transferencia", "Efectivo", "Cheque", "Tarjeta bancaria"]
TIPOS_EVENTO_MAQ = ["Calibración Nebulizador", "Cambio de Aceite", "Reparación Mecánica", "Ajuste Eléctrico", "Neumáticos", "Mantención Preventiva", "Otro"]
GAP_CAPITULOS = ["AFB", "CB", "FV", "RRHH", "AGUA", "AUDITORIA"]
GAP_ESPECIES = ["LA CONCEPCION", "CARLOS LIRA", "EL ESPINO"]
GAP_ESPECIE_CUARTELES = {
    "LA CONCEPCION": ["CEREZOS CORTE 1", "CEREZOS CORTE 2"],
    "CARLOS LIRA": ["CIRUELOS"],
    "EL ESPINO": ["NOGALES APARICION", "NOGALES CRUZ DEL SUR"],
}
LIBRO_CAMPO_ESPECIES = ["Cerezos", "Ciruelos", "Nogales"]
GAP_ESPECIE_GENERAL = "General"
ETIQUETAS_MAQ = ["Abierto", "En Observación", "En Reparación", "Cerrado conforme", "Cerrado desconforme"]
GANTT_PRIORIDADES = ["Alta", "Media", "Baja"]
GANTT_ESTADOS = ["Pendiente", "En curso", "Completada", "Suspendida"]
GANTT_UMBRALES_DEF = {"critico": 30, "alto": 15, "medio": 5}

PRORRATEO_CC_DEFAULT = {
    "CEREZOS CORTE 1": 7.94,
    "CEREZOS CORTE 2": 7.94,
    "CIRUELOS": 32.71,
    "NOGALES APARICION": 32.71,
    "NOGALES CRUZ DEL SUR": 18.70,
}
CUARTELES_PRORRATEO = list(PRORRATEO_CC_DEFAULT.keys())
CUARTELES_IMPUTACION_DIRECTA = ["EL ESPINO", "OTROS"]
CUARTELES_OFICIALES = [
    "CEREZOS CORTE 1", "CEREZOS CORTE 2", "CIRUELOS", "EL ESPINO",
    "NOGALES APARICION", "NOGALES CRUZ DEL SUR", "OTROS",
]
TEMPORADAS_COSTOS = [
    ("2026-2027", datetime(2026, 5, 1).date(), datetime(2027, 4, 30).date()),
    ("2027-2028", datetime(2027, 5, 1).date(), datetime(2028, 4, 30).date()),
    ("2028-2029", datetime(2028, 5, 1).date(), datetime(2029, 4, 30).date()),
]

TIPO_GASTO_SIN_CLASIFICAR = "Sin clasificar"
TIPOS_GASTO_COMPRAS = [
    TIPO_GASTO_SIN_CLASIFICAR,
    "Energía eléctrica",
    "Servicios maq. externa",
    "Repuestos y talleres",
    "Gastos administración y asesorías",
    "Arriendos",
    "Servicios básicos",
    "Agua predial",
    "Agroquímicos",
    "Insumos",
    "Plantas",
    "Laboratorios/análisis",
    "Activos/amortización",
]
TIPOS_GASTO_HISTORIAL_COMPRAS = TIPOS_GASTO_COMPRAS + [
    "Contratistas externos",
    "Petróleo",
]
TIPOS_GASTO_SISTEMA = {"RRHH de la casa"}
TIPOS_GASTO_ALTA = [t for t in TIPOS_GASTO_COMPRAS if t != TIPO_GASTO_SIN_CLASIFICAR]
RUBROS_MATRIZ_COSTOS = [
    "Insumos",
    "Agroquímicos",
    "Plantas",
    "Energía eléctrica",
    "Servicios maq. externa",
    "Repuestos y talleres",
    "Gastos administración y asesorías",
    "Arriendos",
    "Servicios básicos",
    "Agua predial",
    "Laboratorios/análisis",
    "Activos/amortización",
    TIPO_GASTO_SIN_CLASIFICAR,
    "Petróleo",
    "RRHH de la casa",
    "Contratistas",
    "Ajustes",
]
RUBROS_MATRIZ_FILAS_CIERRE = ("TOTAL GASTO", "PRESUPUESTO", "SALDO")

# Rubros de facturas con IVA 19%: en Costos valor neto (÷1.19); Compras historial sigue en bruto.
RUBROS_COSTOS_NETO_IVA = frozenset({
    "Agroquímicos",
    "Repuestos y talleres",
    "Energía eléctrica",
})
# Alias legacy (scripts / migraciones)
RUBROS_COSTOS_NETO_ESPINO = RUBROS_COSTOS_NETO_IVA
IVA_COSTOS_FACTOR = 1.19

FAMILIAS_AGROQUIMICOS_MATRIZ = {
    "ACARICIDA",
    "ADHERENTE / MOJANTE",
    "BIO ESTIMULANTE",
    "FUNGICIDA",
    "HERBICIDA",
    "INSECTICIDA",
    "REGULADOR DE CRECIMIENTO",
    "FERTILIZANTE FOLIAR",
}

def _familia_es_agroquimico(familia):
    return str(familia or "").upper().strip() in FAMILIAS_AGROQUIMICOS_MATRIZ

def _rubro_costo_desde_producto(conn, producto, familia):
    """Rubro CC para salidas de bodega: siempre Agroquímicos."""
    return "Agroquímicos"

def _dataframe_movimientos_detalle_cc(conn, cc_u, fi_s=None, ff_s=None):
    filtro = "UPPER(TRIM(m.centro_costo)) = ? AND ABS(COALESCE(m.valor_imputado, 0)) > 0.01"
    params = [cc_u]
    if fi_s and ff_s:
        filtro += " AND m.fecha BETWEEN ? AND ?"
        params.extend([fi_s, ff_s])
    df = pd.read_sql_query(
        f"""SELECT m.fecha as Fecha,
                   COALESCE(i.producto, 'Producto') as producto,
                   i.familia as familia,
                   COALESCE(i.producto, 'Producto') || ' (' || printf('%.2f', m.cantidad) || ')' as Detalle,
                   m.valor_imputado as Monto
            FROM movimientos m LEFT JOIN inventario i ON m.producto_id = i.id
            WHERE {filtro}""",
        conn,
        params=params,
    )
    if df.empty:
        return pd.DataFrame(columns=["Fecha", "Rubro", "Detalle", "Monto"])
    df["Rubro"] = [
        _rubro_costo_desde_producto(conn, r["producto"], r["familia"])
        for _, r in df.iterrows()
    ]
    return df[["Fecha", "Rubro", "Detalle", "Monto"]]

TEMPORADAS_ESPINO = [
    ("2026", datetime(2025, 11, 1).date(), datetime(2026, 12, 31).date()),
    ("2027", datetime(2027, 1, 1).date(), datetime(2027, 12, 31).date()),
    ("2028", datetime(2028, 1, 1).date(), datetime(2028, 12, 31).date()),
]

def _temporada_vigente_costos():
    for nombre, fi, ff in TEMPORADAS_COSTOS:
        if fi <= hoy <= ff:
            return nombre, fi, ff
    return TEMPORADAS_COSTOS[0]
CLIMATE_ESTACION = {
    "id": 3539,
    "codigo": 3539,
    "nombre": "Huelquén",
    "region": "Metropolitana",
    "lat": -33.767,
    "lon": -70.733,
}
UMBRAL_HORA_FRIO = 7.2
UMBRAL_CALOR_DIA = 18.0
HORAS_POR_PORCION = 24
# Ancla informe Agroclima «Temporada 2026» — acumulado desde 1-may (actualizar periódicamente).
AGROCLIMA_BASE_MAY1 = (5, 1)
AGROCLIMA_ANCLA_OFICIAL = {
    3539: {"fecha": date(2026, 6, 29), "horas_desde_may1": 443.0},
}

# DATA EL ESPINO INTEGRAL (81 registros — PDF historial 13/06/2026)
DATA_ESP_HISTORICA = [
    ('2025-11-12', '719', 'Alisud Auditoria GG', 1094530),
    ('2025-12-12', 'S/N', 'Carlos Zavala Anticipo sueldo', 0),
    ('2025-12-20', 'S/N', 'Alejandra Leviman', 150000),
    ('2025-12-20', 'S/N', 'Duilio Pruzzo Diferencia en gastos', 6051696),
    ('2025-12-20', 'S/N', 'Carlos Zavala Aguinaldo', 100000),
    ('2025-12-20', 'S/N', 'Alejandra Levimar Aguinaldo', 100000),
    ('2025-12-24', 'S/N', 'Duilio Pruzzo Reembolso Impuesto', 178083),
    ('2025-12-27', 'S/N', 'Alejandra Leviman', 125000),
    ('2025-12-29', 'S/N', 'Carlos Zavala Sueldo', 620000),
    ('2026-01-02', '2217085', 'Podastick Max 3.8 L, Konan 240 SC 1L', 146757),
    ('2026-01-03', 'S/N', 'Alejandra Leviman', 259257),
    ('2026-01-06', 'S/N', 'Duilio Pruzzo', 256100),
    ('2026-01-06', 'S/N', 'Carlos Zavala Sueldo', 0),
    ('2026-01-10', 'S/N', 'Alejandra Leviman', 137500),
    ('2026-01-13', 'Coagra', 'Productos del agro', 196493),
    ('2026-01-14', 'S/N', 'Carlos Lira V. Reembolso Imposiciones CZ', 140556),
    ('2026-01-16', 'CZ', 'Suple', 0),
    ('2026-01-17', 'S/N', 'Danixa Amaza', 25000),
    ('2026-01-17', 'S/N', 'Alejandra Leviman', 137500),
    ('2026-01-20', '349898', 'Serrucho Podar c/gancho', 8328),
    ('2026-01-20', '6323030', 'Podastik Max fitosanitarios', 28575),
    ('2026-01-25', 'S/N', 'Danixa Aplicación arañita', 50000),
    ('2026-01-26', '2224579', 'Konan 240 SC 1lt', 79183),
    ('2026-01-28', '2225756', 'Konan / Acaban SC', 232576),
    ('2026-01-30', 'S/N', 'Carlos Zavala', 620000),
    ('2026-01-30', 'S/N', 'Duilio Pruzzo', 0),
    ('2026-02-05', 'S/N', 'Danixa Amaza', 50000),
    ('2026-02-10', 'S/N', 'Carlos Zavala Imposiciones', 143483),
    ('2026-02-11', 'GD Coagra', 'Acaban 1lt', 89969),
    ('2026-02-12', 'S/N', 'Caceres M SPA', 1532084),
    ('2026-02-19', '13785', 'FerreMás Pala', 10690),
    ('2026-03-02', '14895', 'Marcelo Caro Pernos varios', 11500),
    ('2026-03-03', 'DAB', 'Cinta plana amarratec', 11942),
    ('2026-03-03', '2237580', 'Coagra Urea granulada', 198417),
    ('2026-03-06', '6966966', 'Electrocom Contractor', 220326),
    ('2026-03-09', '7826141', 'Ferretería codo hidráulico', 5750),
    ('2026-03-09', '349613', 'Equipos Riego Sonda nivel', 77571),
    ('2026-03-09', '54846', 'Autosystem Cable libre halógeno', 45346),
    ('2026-03-10', 'S/N', 'Alejandra Leviman', 112500),
    ('2026-03-10', '6854929', 'Electrocom Cable RV-K', 100399),
    ('2026-03-10', '23648', 'Soc. Los Olivos Pernos Hex', 16950),
    ('2026-03-11', 'S/N', 'Punto Hidraulico Mufa', 29750),
    ('2026-03-11', 'S/N', 'Gustavo Contador mensual', 315000),
    ('2026-03-11', 'S/N', 'Carlos Lira V.', 243882),
    ('2026-03-11', '349905', 'Equipos Riego Motor 4"', 167171),
    ('2026-03-11', '1427603', 'Vitel Cable reviflex', 108469),
    ('2026-03-11', '6954495', 'Electrocom Tubo curvable', 27703),
    ('2026-03-11', 'S/N', 'Imposiciones CZ feb', 143483),
    ('2026-03-12', '21049', 'FP.cl Cinta aislante', 7960),
    ('2026-03-12', 'S/N', 'Juan Zuñiga Pozo', 4830000),
    ('2026-03-13', 'S/N', 'Héctor Zura', 300000),
    ('2026-03-14', '6991256', 'Electrocom Rele térmico', 27839),
    ('2026-03-15', 'S/N', 'Alejandra Leviman', 125000),
    ('2026-03-18', 'CGE', 'Consumo Eléctrico', 309600),
    ('2026-03-30', 'S/N', 'Carlos Zavala Sueldo Marzo', 620000),
    ('2026-04-02', 'S/N', 'Alejandra Leviman sueldo', 112500),
    ('2026-04-07', 'S/N', 'CGE feb y marzo', 924000),
    ('2026-04-10', 'S/N', 'CZ Imposiciones Marzo', 143483),
    ('2026-04-13', '28803', 'Topagro Fascinate 150 SL', 143032),
    ('2026-04-17', '2248987', 'Coagra Sulfato zinc', 149190),
    ('2026-04-30', 'S/N', 'Cáceres Heladas', 4545184),
    ('2026-04-30', 'S/N', 'Carlos Zavala Sueldo', 620000),
    ('2026-05-08', 'BCI', 'Comisión tarjeta', 13368),
    ('2026-05-12', 'S/N', 'CZ Imposiciones Abril', 143914),
    ('2026-05-15', '19509', 'Sendai Datalogger', 58362),
    ('2026-05-17', 'S/N', 'abono Arriendo María Paola Torres ortiz', 7000000),
    ('2026-05-17', '39280236', 'saldo arriendo Maria Paola Torres Ortiz temporada 2026', 6433506),
    ('2026-05-25', '6509132', 'CGE', 446200),
    ('2026-05-27', 'sueldo', 'Carlos Zavala', 620000),
    ('2026-06-01', '40430486', 'Anibal Alvarez Flores, hechura de zanja conexion pozo n', 280000),
    ('2026-06-02', 'efectivo', 'Amarras Plásticas', 16800),
    ('2026-06-02', '359603', 'DAB, llave bola, tee, serrucho poda', 49222),
    ('2026-06-05', '1339', 'Los castaños, 25 kg cobre nordox', 452287),
    ('2026-06-05', '303', 'MACAL, Biolife Psychro 7 bolsas de 250 gr', 325603),
    ('2026-06-09', 'INT-20260609-02', 'DUILIO GASTO MAQUINARIA 10/12/2025 AL 05/06/2026', 1470000),
    ('2026-06-09', 'INT-20260609-01', 'CZ IMPOSICIONES MAYO 2026', 143914),
    ('2026-06-10', 'INT-20260610-01', 'Carlos Zavala, Finiquito, indemnización 530.000 vacacio', 916480),
    ('2026-06-12', 'INT-20260612-01', 'TRASLADO DE BOMBA PARA REPARACIÓN', 250000),
    ('2026-06-12', 'INT-20260612-02', 'CAMBIO DE BOMBA CLV', 410000),
    ('2026-06-12', '25573', 'gasto Notaria por finiquito CZ', 5000),
    ('2026-06-13', 'INT-20260613-01', 'Alejandra Levimán', 87500),
]

def migrar_gastos_espino(cursor):
    """Sincroniza gastos El Espino con el historial oficial (PDF). Idempotente."""
    cursor.execute(
        "UPDATE gastos_espino SET fecha='2026-05-08' WHERE fecha='2025-05-08' AND documento='BCI'"
    )
    db_rows = list(
        cursor.execute("SELECT id, fecha, documento, item, CAST(ROUND(monto) AS INTEGER) FROM gastos_espino").fetchall()
    )
    reclamados = set()

    def _reclamar(rid, item=None):
        reclamados.add(rid)
        if item is not None:
            cursor.execute("UPDATE gastos_espino SET item=? WHERE id=?", (item, rid))

    for fecha, documento, item, monto in DATA_ESP_HISTORICA:
        monto_i = int(round(float(monto)))
        match_id = None
        for rid, f, d, it, m in db_rows:
            if rid in reclamados:
                continue
            if f == fecha and d == documento and it == item and m == monto_i:
                match_id = rid
                break
        if match_id:
            _reclamar(match_id)
            continue
        hermanos_doc = [
            r for r in DATA_ESP_HISTORICA
            if r[0] == fecha and r[1] == documento and int(round(float(r[3]))) == monto_i
        ]
        if len(hermanos_doc) == 1:
            for rid, f, d, it, m in db_rows:
                if rid in reclamados:
                    continue
                if f == fecha and d == documento and m == monto_i:
                    _reclamar(rid, item)
                    match_id = rid
                    break
        if match_id:
            continue
        hermanos_fecha = [
            r for r in DATA_ESP_HISTORICA
            if r[0] == fecha and int(round(float(r[3]))) == monto_i
        ]
        if len(hermanos_fecha) == 1:
            for rid, f, d, it, m in db_rows:
                if rid in reclamados:
                    continue
                if f == fecha and m == monto_i:
                    cursor.execute(
                        "UPDATE gastos_espino SET documento=?, item=? WHERE id=?",
                        (documento, item, rid),
                    )
                    _reclamar(rid)
                    match_id = rid
                    break
        if match_id:
            continue
        cursor.execute(
            "INSERT INTO gastos_espino (fecha, documento, item, monto) VALUES (?,?,?,?)",
            (fecha, documento, item, monto),
        )
        nuevo_id = cursor.lastrowid
        db_rows.append((nuevo_id, fecha, documento, item, monto_i))
        _reclamar(nuevo_id)

    canon_pares = {(r[0], int(round(float(r[3])))) for r in DATA_ESP_HISTORICA}
    for rid, f, d, it, m in db_rows:
        if rid in reclamados:
            continue
        if (f, m) in canon_pares:
            cursor.execute("DELETE FROM gastos_espino WHERE id=?", (rid,))

# =============================================================================
# 2. MOTOR DE BASE DE DATOS Y ALERTA SMTP
# =============================================================================

def _migrar_inventario_unidad_medida(conn):
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(inventario)").fetchall()]
        if cols and "unidad_medida" not in cols:
            conn.execute("ALTER TABLE inventario ADD COLUMN unidad_medida TEXT DEFAULT 'kg'")
            conn.commit()
    except Exception:
        pass

def _migrar_movimientos_unidad_medida(conn):
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(movimientos)").fetchall()]
        if cols and "unidad_medida" not in cols:
            conn.execute("ALTER TABLE movimientos ADD COLUMN unidad_medida TEXT")
            conn.commit()
        conn.execute(
            """UPDATE movimientos SET unidad_medida = (
                   SELECT COALESCE(i.unidad_medida, 'kg') FROM inventario i
                   WHERE i.id = movimientos.producto_id
               )
               WHERE unidad_medida IS NULL OR TRIM(unidad_medida) = ''"""
        )
        conn.commit()
    except Exception:
        pass

def _migrar_libro_campo_unidad_gasto(conn):
    try:
        conn.execute(
            f"""UPDATE libro_campo SET unidad_gasto = (
                   SELECT COALESCE(i.unidad_medida, '{DEFAULT_UNIDAD_INSUMO}') FROM inventario i
                   WHERE UPPER(TRIM(i.producto)) = UPPER(TRIM(libro_campo.producto))
               )
               WHERE unidad_gasto IS NULL OR TRIM(unidad_gasto) = ''"""
        )
        conn.commit()
    except Exception:
        pass


def _cantidades_cercanas_lc(a, b, tol_rel=0.02, tol_abs=0.05):
    a, b = float(a), float(b)
    ref = max(abs(a), abs(b), tol_abs)
    return abs(a - b) <= max(tol_abs, ref * tol_rel)


def _migrar_libro_campo_gasto_a_kg(conn):
    """Deprecated: usar _unificar_imputaciones_kg."""
    _unificar_imputaciones_kg(conn)


def _unificar_imputaciones_kg(conn):
    """Convierte imputaciones legacy gr→kg en inventario, movimientos y libro de campo."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (clave TEXT PRIMARY KEY, valor TEXT)")
    cur = conn.cursor()
    if cur.execute("SELECT 1 FROM schema_meta WHERE clave='unificar_imputaciones_kg_v2'").fetchone():
        return

    def _a_kg_local(valor, um):
        um_l = (um or DEFAULT_UNIDAD_INSUMO).strip().lower()
        v = float(valor or 0)
        if um_l in ("gr", "g", "gramos"):
            return round(v / 1000.0, 4), DEFAULT_UNIDAD_INSUMO
        if um_l == "ml":
            return round(v / 1000.0, 4), "lt"
        return round(v, 4), um_l if um_l in ("kg", "lt") else DEFAULT_UNIDAD_INSUMO

    for iid, stock, um in cur.execute(
        """SELECT id, stock, unidad_medida FROM inventario
           WHERE LOWER(TRIM(COALESCE(unidad_medida, ''))) IN ('gr', 'g', 'gramos')"""
    ):
        nuevo, um_n = _a_kg_local(stock, um)
        cur.execute("UPDATE inventario SET stock=?, unidad_medida=? WHERE id=?", (nuevo, um_n, iid))

    for mid, cant, um in cur.execute(
        """SELECT id, cantidad, unidad_medida FROM movimientos
           WHERE LOWER(TRIM(COALESCE(unidad_medida, ''))) IN ('gr', 'g', 'gramos')"""
    ):
        nuevo, um_n = _a_kg_local(cant, um)
        cur.execute("UPDATE movimientos SET cantidad=?, unidad_medida=? WHERE id=?", (nuevo, um_n, mid))

    for mid, cant in cur.execute(
        """SELECT id, cantidad FROM movimientos
           WHERE tipo='Salida'
             AND LOWER(TRIM(COALESCE(unidad_medida, 'kg'))) = 'kg'
             AND cantidad >= 1000"""
    ):
        cur.execute(
            "UPDATE movimientos SET cantidad=?, unidad_medida=? WHERE id=?",
            (round(float(cant) / 1000.0, 4), DEFAULT_UNIDAD_INSUMO, mid),
        )

    for lid, gasto, um in cur.execute(
        """SELECT id, gasto_total, unidad_gasto FROM libro_campo
           WHERE gasto_total IS NOT NULL AND gasto_total > 0"""
    ):
        um_l = (um or "").strip().lower()
        if um_l in ("gr", "g", "gramos"):
            nuevo, um_n = _a_kg_local(gasto, um)
        elif um_l in ("", "kg") and float(gasto) >= 1000:
            nuevo, um_n = round(float(gasto) / 1000.0, 4), DEFAULT_UNIDAD_INSUMO
        else:
            nuevo, um_n = round(float(gasto), 4), DEFAULT_UNIDAD_INSUMO
        cur.execute(
            "UPDATE libro_campo SET gasto_total=?, unidad_gasto=? WHERE id=?",
            (nuevo, um_n, lid),
        )

    lc_rows = cur.execute(
        """SELECT id, fecha, sector, producto, gasto_total FROM libro_campo
           WHERE gasto_total IS NOT NULL AND gasto_total > 0"""
    ).fetchall()
    mov_rows = cur.execute(
        """SELECT m.id, m.fecha, m.centro_costo, i.producto, m.cantidad
           FROM movimientos m JOIN inventario i ON i.id = m.producto_id
           WHERE m.tipo = 'Salida'"""
    ).fetchall()

    for lid, f_lc, sector, prod, g_lc in lc_rows:
        g_lc = float(g_lc)
        for mid, f_mov, cc, prod_m, g_mov in mov_rows:
            if prod.strip().upper() != prod_m.strip().upper():
                continue
            if sector.strip().upper() != cc.strip().upper():
                continue
            if abs((pd.to_datetime(f_lc).date() - pd.to_datetime(f_mov).date()).days) > 14:
                continue
            g_mov = float(g_mov)
            if _cantidades_cercanas_lc(g_lc, g_mov):
                continue
            if _cantidades_cercanas_lc(g_lc / 1000.0, g_mov):
                cur.execute(
                    "UPDATE libro_campo SET gasto_total=?, unidad_gasto=? WHERE id=?",
                    (round(g_lc / 1000.0, 4), DEFAULT_UNIDAD_INSUMO, lid),
                )
                break
            if _cantidades_cercanas_lc(g_lc, g_mov / 1000.0):
                cur.execute(
                    "UPDATE movimientos SET cantidad=?, unidad_medida=? WHERE id=?",
                    (round(g_mov / 1000.0, 4), DEFAULT_UNIDAD_INSUMO, mid),
                )

    cur.execute(
        """UPDATE inventario SET unidad_medida=? WHERE unidad_medida IS NULL OR TRIM(unidad_medida)=''""",
        (DEFAULT_UNIDAD_INSUMO,),
    )
    cur.execute(
        """UPDATE movimientos SET unidad_medida=? WHERE unidad_medida IS NULL OR TRIM(unidad_medida)=''""",
        (DEFAULT_UNIDAD_INSUMO,),
    )
    cur.execute(
        """UPDATE libro_campo SET unidad_gasto=? WHERE unidad_gasto IS NULL OR TRIM(unidad_gasto)=''""",
        (DEFAULT_UNIDAD_INSUMO,),
    )
    cur.execute(
        "INSERT INTO schema_meta (clave, valor) VALUES ('unificar_imputaciones_kg_v2', '1')"
    )
    normalizar_cuarteles_db(conn)
    conn.commit()


def _migrar_familias_producto(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS familias_producto (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            orden INTEGER DEFAULT 0
        )"""
    )
    conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (clave TEXT PRIMARY KEY, valor TEXT)")
    cur = conn.cursor()
    if not cur.execute("SELECT 1 FROM schema_meta WHERE clave='familias_producto_v1'").fetchone():
        for i, fam in enumerate(FAMILIAS_PRODUCTOS_DEFAULT):
            cur.execute(
                "INSERT OR IGNORE INTO familias_producto (nombre, orden) VALUES (?, ?)",
                (fam, i),
            )
        cur.execute("INSERT INTO schema_meta (clave, valor) VALUES ('familias_producto_v1', '1')")
    existentes = {r[0] for r in conn.execute("SELECT nombre FROM familias_producto").fetchall()}
    max_ord = conn.execute("SELECT COALESCE(MAX(orden), -1) FROM familias_producto").fetchone()[0]
    for (fam,) in conn.execute(
        "SELECT DISTINCT TRIM(familia) FROM inventario WHERE familia IS NOT NULL AND TRIM(familia) != ''"
    ).fetchall():
        if fam and fam not in existentes:
            max_ord += 1
            conn.execute(
                "INSERT OR IGNORE INTO familias_producto (nombre, orden) VALUES (?, ?)",
                (fam, max_ord),
            )
            existentes.add(fam)
    conn.commit()


def listar_familias_producto(conn):
    if not es_solo_lectura():
        _migrar_familias_producto(conn)
    rows = conn.execute(
        "SELECT nombre FROM familias_producto ORDER BY orden, nombre COLLATE NOCASE"
    ).fetchall()
    if rows:
        return [r[0] for r in rows]
    return list(FAMILIAS_PRODUCTOS_DEFAULT)


def contar_productos_familia(conn, nombre):
    return conn.execute(
        "SELECT COUNT(*) FROM inventario WHERE UPPER(TRIM(familia))=UPPER(TRIM(?))",
        (str(nombre or "").strip(),),
    ).fetchone()[0]


def _admin_tab_familias_producto(conn):
    st.markdown("#### Familias de productos")
    st.caption(
        "Catálogo usado en **Compras** y **Bodega**. "
        "No puede eliminar una familia que tenga productos en inventario; reasígnelos antes."
    )
    familias = listar_familias_producto(conn)
    df_fam = pd.DataFrame(
        [{"Familia": f, "Productos": contar_productos_familia(conn, f)} for f in familias]
    )
    st.dataframe(df_fam, use_container_width=True, hide_index=True)
    with st.form("seg_fam_nueva", clear_on_submit=True):
        nueva = st.text_input("Nueva familia")
        if st.form_submit_button("➕ CREAR FAMILIA"):
            nom = nueva.strip().upper()
            if not nom:
                st.error("Ingrese un nombre para la familia.")
            elif conn.execute(
                "SELECT 1 FROM familias_producto WHERE UPPER(TRIM(nombre))=?",
                (nom,),
            ).fetchone():
                st.error(f"La familia «{nom}» ya existe.")
            else:
                orden = conn.execute(
                    "SELECT COALESCE(MAX(orden), -1) + 1 FROM familias_producto"
                ).fetchone()[0]
                conn.execute(
                    "INSERT INTO familias_producto (nombre, orden) VALUES (?, ?)",
                    (nom, orden),
                )
                conn.commit()
                registrar_accion("FAMILIA PRODUCTO", f"Nueva: {nom}")
                st.success(f"Familia «{nom}» creada.")
                st.rerun()
    st.divider()
    if familias:
        with st.form("seg_fam_editar"):
            sel = st.selectbox("Familia a renombrar", familias, key="seg_fam_edit_sel")
            nuevo_nom = st.text_input("Nuevo nombre", value=sel, key="seg_fam_edit_nom")
            if st.form_submit_button("✏️ GUARDAR CAMBIO"):
                nom_nuevo = nuevo_nom.strip().upper()
                if not nom_nuevo:
                    st.error("Ingrese el nuevo nombre.")
                elif nom_nuevo == sel.strip().upper():
                    st.warning("El nombre no cambió.")
                elif conn.execute(
                    "SELECT 1 FROM familias_producto WHERE UPPER(TRIM(nombre))=? AND UPPER(TRIM(nombre))!=?",
                    (nom_nuevo, sel.strip().upper()),
                ).fetchone():
                    st.error(f"Ya existe otra familia llamada «{nom_nuevo}».")
                else:
                    n_prod = contar_productos_familia(conn, sel)
                    conn.execute(
                        "UPDATE familias_producto SET nombre=? WHERE UPPER(TRIM(nombre))=?",
                        (nom_nuevo, sel.strip().upper()),
                    )
                    conn.execute(
                        "UPDATE inventario SET familia=? WHERE UPPER(TRIM(familia))=?",
                        (nom_nuevo, sel.strip().upper()),
                    )
                    conn.commit()
                    registrar_accion(
                        "FAMILIA PRODUCTO",
                        f"Renombrada: {sel} → {nom_nuevo} ({n_prod} producto(s) actualizados)",
                    )
                    st.success(f"Familia renombrada a «{nom_nuevo}» ({n_prod} producto(s) actualizados).")
                    st.rerun()
        st.divider()
        with st.form("seg_fam_eliminar"):
            sel_del = st.selectbox("Familia a eliminar", familias, key="seg_fam_del_sel")
            n_prod = contar_productos_familia(conn, sel_del)
            if n_prod > 0:
                st.error(
                    f"⚠️ No se puede eliminar «{sel_del}»: hay **{n_prod}** producto(s) en inventario. "
                    "Cambie la familia de esos productos en Bodega antes de eliminar."
                )
            else:
                st.info(f"La familia «{sel_del}» no tiene productos asociados y puede eliminarse.")
            confirm_del = st.checkbox(
                "Confirmo eliminar esta familia de forma permanente",
                key="seg_fam_del_confirm",
            )
            if st.form_submit_button("🗑️ ELIMINAR FAMILIA"):
                if n_prod > 0:
                    st.error(
                        f"No se eliminó: {n_prod} producto(s) siguen usando la familia «{sel_del}»."
                    )
                elif not confirm_del:
                    st.error("Debe marcar la casilla de confirmación.")
                else:
                    conn.execute(
                        "DELETE FROM familias_producto WHERE UPPER(TRIM(nombre))=?",
                        (sel_del.strip().upper(),),
                    )
                    conn.commit()
                    registrar_accion("FAMILIA PRODUCTO", f"Eliminada: {sel_del}")
                    st.success(f"Familia «{sel_del}» eliminada.")
                    st.rerun()
    else:
        st.info("No hay familias registradas. Cree la primera arriba.")


def _resumen_costos_para_flujo(conn, temporada, fi, ff):
    """Misma matriz y rango de consulta que el módulo Costos (temporada vigente incluida)."""
    prorrateo = cargar_prorrateo_cc(conn)
    es_vigente = fi <= hoy <= ff
    fi_cons, ff_cons = _rango_fechas_costos_consulta(conn, fi, ff, es_vigente)
    if es_vigente:
        matriz = _armar_matriz_costos_vista_b(
            conn, fi_cons, ff_cons, CUARTELES_OFICIALES, prorrateo, temporada,
            fi_rrhh=fi, ff_rrhh=ff,
        )
    else:
        matriz = _armar_matriz_costos_vista_b(
            conn, fi, ff, CUARTELES_OFICIALES, prorrateo, temporada,
        )
    return resumen_desde_matriz_costos(matriz, CUARTELES_OFICIALES)


def _admin_form_ingresos_temporada(conn, temporada, fi, ff, key_prefix):
    from erp_flujo_financiero import cargar_ingresos_cc

    meses = list(iter_meses_rango(fi, ff))
    if not meses:
        st.info("Sin meses en esta temporada.")
        return
    es_vigente = fi <= hoy <= ff
    vigente_txt = " · **temporada en curso**" if es_vigente else ""
    st.caption(
        f"Período **{fi.strftime('%d-%m-%Y')}** → **{ff.strftime('%d-%m-%Y')}**{vigente_txt}. "
        f"**{len(meses)} meses** · ingreso del campo = suma de todos los CC."
    )
    meses_txt = ", ".join(_mes_label(a, m) for a, m in meses)
    st.info(f"**Meses de la temporada {temporada}:** {meses_txt}")

    ing_cc_act = cargar_ingresos_cc(conn, temporada)
    notas_act = cargar_notas_ingresos_cc(conn, temporada)
    caja_ini_act = cargar_saldo_caja_inicial(conn, temporada)
    with st.form(f"adm_flujo_ingresos_{key_prefix}"):
        caja_ini = st.number_input(
            "Saldo caja inicial de la temporada ($)",
            min_value=0.0,
            value=float(caja_ini_act),
            step=100000.0,
            help="Se suma al ingreso del mes en curso en el módulo Flujo financiero.",
            key=f"adm_flujo_caja_ini_{key_prefix}",
        )
        st.caption("Opcional: nota explicativa bajo cada monto de ingreso.")
        hdr = st.columns(len(meses))
        for col, (anio, mes) in zip(hdr, meses):
            col.markdown(
                f"<div style='text-align:center;font-weight:700;padding:6px;"
                f"background:#E3F2FD;border-radius:6px;'>{_mes_label(anio, mes)}</div>",
                unsafe_allow_html=True,
            )
        ing_cc = {}
        notas_cc = {}
        for cc in CUARTELES_OFICIALES:
            st.markdown(f"**{cc.title()}**")
            cols_c = st.columns(len(meses))
            for col, (anio, mes) in zip(cols_c, meses):
                with col:
                    key_base = f"{key_prefix}_{cc}_{anio}_{mes}"
                    ing_cc[(cc, anio, mes)] = st.number_input(
                        _mes_label(anio, mes),
                        min_value=0.0,
                        value=float(ing_cc_act.get((cc, anio, mes), 0.0)),
                        step=100000.0,
                        key=f"adm_flujo_cc_{key_base}",
                        label_visibility="collapsed",
                    )
                    notas_cc[(cc, anio, mes)] = st.text_input(
                        "Nota",
                        value=notas_act.get((cc, anio, mes), ""),
                        key=f"adm_flujo_nota_{key_base}",
                        label_visibility="collapsed",
                        placeholder="Nota…",
                    )
        if st.form_submit_button(f"💾 GUARDAR INGRESOS {temporada}"):
            guardar_ingresos_cc(conn, temporada, ing_cc, notas_cc)
            guardar_saldo_caja_inicial(conn, temporada, caja_ini)
            registrar_accion("FLUJO INGRESOS", temporada)
            st.session_state["adm_flujo_guardado_msg"] = (
                f"Ingresos guardados para temporada {temporada}."
            )


def _admin_tab_ingresos_flujo(conn):
    st.markdown("#### Ingresos — Flujo financiero")
    st.caption(
        "Cargue **ingresos proyectados por centro de costo** para cada **temporada agrícola**. "
        "El ingreso total del campo en cada mes es la **suma** de los CC."
    )
    msg_ok = st.session_state.pop("adm_flujo_guardado_msg", None)
    if msg_ok:
        st.success(msg_ok)
    nombres_temp = [t[0] for t in TEMPORADAS_COSTOS]
    idx_def = next(
        (i for i, t in enumerate(TEMPORADAS_COSTOS) if t[1] <= hoy <= t[2]),
        0,
    )
    temporada = st.selectbox(
        "Temporada",
        nombres_temp,
        index=idx_def,
        key="adm_flujo_temp",
    )
    fi, ff = next((t[1], t[2]) for t in TEMPORADAS_COSTOS if t[0] == temporada)
    _admin_form_ingresos_temporada(
        conn, temporada, fi, ff, temporada.replace("-", "_"),
    )


def _admin_tab_metas_costos(conn):
    st.markdown("#### Presupuesto y producción por cuartel")
    st.caption(
        "Metas por **temporada agrícola** usadas en el módulo **Costos**: presupuesto ($) y kg estimados a producir. "
        "Los usuarios ven estos valores en cada cuartel; solo administración los edita aquí."
    )
    nombres_temp = [t[0] for t in TEMPORADAS_COSTOS]
    idx_def = next(
        (i for i, t in enumerate(TEMPORADAS_COSTOS) if t[1] <= hoy <= t[2]),
        0,
    )
    temporada = st.selectbox("Temporada", nombres_temp, index=idx_def, key="adm_meta_temp")
    fi, ff = next((t[1], t[2]) for t in TEMPORADAS_COSTOS if t[0] == temporada)
    st.caption(f"Período: **{fi.strftime('%d-%m-%Y')}** al **{ff.strftime('%d-%m-%Y')}**")

    with st.form("adm_metas_costos_form"):
        entradas = {}
        for cc in CUARTELES_OFICIALES:
            st.markdown(f"**{cc.title()}**")
            c1, c2 = st.columns(2)
            ppto_val = _obtener_ppto_temporada(conn, temporada, cc)
            kg_val = _obtener_kg_estimado_temporada(conn, temporada, cc)
            entradas[cc] = (
                c1.number_input(
                    "Presupuesto ($)",
                    min_value=0.0,
                    value=float(ppto_val),
                    step=100000.0,
                    key=f"adm_ppto_{temporada}_{cc}",
                ),
                c2.number_input(
                    "Kg estimados a producir",
                    min_value=0.0,
                    value=float(kg_val),
                    step=100.0,
                    format="%.2f",
                    key=f"adm_kg_{temporada}_{cc}",
                ),
            )
            st.markdown("")
        if st.form_submit_button("💾 GUARDAR METAS DE LA TEMPORADA"):
            for cc, (nuevo_ppto, nuevo_kg) in entradas.items():
                _guardar_ppto_temporada(conn, temporada, cc, nuevo_ppto)
                _guardar_kg_estimado_temporada(conn, temporada, cc, nuevo_kg)
            registrar_accion(
                "METAS COSTOS",
                f"{temporada}: {len(CUARTELES_OFICIALES)} cuarteles actualizados",
            )
            st.success(f"Metas guardadas para temporada {temporada}.")
            st.rerun()


_RE_STMT_ESCRITURA = re.compile(
    r"^\s*(INSERT\b|UPDATE\b|DELETE\b|DROP\b|ALTER\b|CREATE\b|REPLACE\s+INTO\b|"
    r"INSERT\s+OR\s+REPLACE\b|INSERT\s+OR\s+IGNORE\b|ATTACH\b|DETACH\b|REINDEX\b|VACUUM\b|"
    r"PRAGMA\s+\w+\s*=)",
    re.I | re.M,
)


def _sql_es_modificacion(sql):
    """True solo para sentencias que modifican la BD (no funciones como REPLACE())."""
    if not sql:
        return False
    texto = re.sub(r"/\*.*?\*/", "", str(sql), flags=re.S)
    texto = re.sub(r"--[^\n\r]*", "", texto)
    for parte in texto.split(";"):
        stmt = parte.strip()
        if stmt and _RE_STMT_ESCRITURA.match(stmt):
            return True
    return False


def _sql_es_schema_ddl(sql):
    """CREATE/ALTER/INDEX de esquema: permitido en lector para no tumbar pestañas."""
    s = (sql or "").lstrip().upper()
    return bool(
        s.startswith("CREATE TABLE")
        or s.startswith("CREATE INDEX")
        or s.startswith("CREATE UNIQUE INDEX")
        or s.startswith("ALTER TABLE")
    )


_MSG_SOLO_LECTURA = "Modo solo lectura: no se permiten cambios en la base de datos."


def rechazar_escritura_solo_lectura():
    """Corta el flujo si un lector intentó ejecutar una acción de guardado."""
    if not _sesion_requiere_solo_lectura():
        return
    st.error("Modo solo lectura: no puede registrar ni modificar datos.")
    st.stop()


def _conn_es_solo_lectura(conn):
    return bool(getattr(conn, "_erp_solo_lectura", False))


def ejecutar_escritura(conn, sql, params=()):
    """INSERT/UPDATE/DELETE centralizado: falla en modo lector."""
    if _conn_es_solo_lectura(conn) or _sesion_requiere_solo_lectura():
        rechazar_escritura_solo_lectura()
    return conn.execute(sql, params)


class _CursorSoloLectura:
    """Envuelve cursor para aplicar las mismas reglas que _ConnSoloLectura."""

    def __init__(self, cur, bloquear=True):
        self._cur = cur
        self._bloquear = bloquear

    def __getattr__(self, name):
        return getattr(self._cur, name)

    def execute(self, sql, parameters=(), /, *args, **kwargs):
        if self._bloquear and _sql_es_modificacion(sql) and not _sql_es_schema_ddl(sql):
            raise sqlite3.OperationalError(_MSG_SOLO_LECTURA)
        if args or kwargs:
            return self._cur.execute(sql, parameters, *args, **kwargs)
        return self._cur.execute(sql, parameters)

    def executemany(self, sql, seq_of_parameters=(), /, *args, **kwargs):
        if self._bloquear and _sql_es_modificacion(sql) and not _sql_es_schema_ddl(sql):
            raise sqlite3.OperationalError(_MSG_SOLO_LECTURA)
        if args or kwargs:
            return self._cur.executemany(sql, seq_of_parameters, *args, **kwargs)
        return self._cur.executemany(sql, seq_of_parameters)


class _ConnSoloLectura:
    """Bloquea INSERT/UPDATE/DELETE cuando la sesión está en modo solo lectura."""

    def __init__(self, conn):
        self._conn = conn
        self._erp_solo_lectura = True

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def execute(self, sql, parameters=(), /, *args, **kwargs):
        if _sql_es_modificacion(sql) and not _sql_es_schema_ddl(sql):
            raise sqlite3.OperationalError(_MSG_SOLO_LECTURA)
        if args or kwargs:
            return self._conn.execute(sql, parameters, *args, **kwargs)
        return self._conn.execute(sql, parameters)

    def executemany(self, sql, seq_of_parameters=(), /, *args, **kwargs):
        if _sql_es_modificacion(sql) and not _sql_es_schema_ddl(sql):
            raise sqlite3.OperationalError(_MSG_SOLO_LECTURA)
        if args or kwargs:
            return self._conn.executemany(sql, seq_of_parameters, *args, **kwargs)
        return self._conn.executemany(sql, seq_of_parameters)

    def executescript(self, sql):
        if _sql_es_modificacion(sql) and not _sql_es_schema_ddl(sql):
            raise sqlite3.OperationalError(_MSG_SOLO_LECTURA)
        return self._conn.executescript(sql)

    def commit(self):
        return None

    def cursor(self):
        return _CursorSoloLectura(self._conn.cursor(), bloquear=True)


def _migrar_imputaciones_p_desincronizadas(conn):
    """Recalcula filas _P cuando el monto bruto fue corregido sin actualizar centros de costo."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (clave TEXT PRIMARY KEY, valor TEXT)")
    cur = conn.cursor()
    if cur.execute("SELECT 1 FROM schema_meta WHERE clave='imputaciones_p_resync_v1'").fetchone():
        return
    filas = cur.execute(
        """SELECT nro_documento, proveedor, monto_total FROM facturas
           WHERE monto_total > 0 AND nro_documento NOT LIKE '%_P'
           AND tipo IN ('Gasto Operacional', 'Gasto Operacional Petróleo', 'Gasto Vario', 'Gasto Vario Petróleo')"""
    ).fetchall()
    reparados = 0
    for doc, prov, monto in filas:
        rows_p = cur.execute(
            "SELECT id, monto_imputado FROM facturas WHERE nro_documento=? AND proveedor=?",
            (doc + "_P", prov),
        ).fetchall()
        if not rows_p:
            continue
        sum_imp = sum(float(r[1] or 0) for r in rows_p)
        monto_f = float(monto or 0)
        if sum_imp <= 0 or monto_f <= 0:
            continue
        ref_neto = monto_f / 1.19
        if sum_imp < ref_neto * 0.98:
            ratio = ref_neto / sum_imp
            for id_p, m_imp in rows_p:
                cur.execute(
                    "UPDATE facturas SET monto_imputado=? WHERE id=?",
                    (float(m_imp or 0) * ratio, id_p),
                )
            reparados += 1
    cur.execute(
        "INSERT INTO schema_meta (clave, valor) VALUES ('imputaciones_p_resync_v1', ?)",
        (str(reparados),),
    )
    conn.commit()


def _migrar_pagos_rrhh_huerfanos(conn):
    """Elimina liquidaciones de trabajadores que ya no están en el maestro de personal."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (clave TEXT PRIMARY KEY, valor TEXT)")
    cur = conn.cursor()
    if cur.execute("SELECT 1 FROM schema_meta WHERE clave='pagos_rrhh_huerfanos_v1'").fetchone():
        return
    cur.execute("DELETE FROM costos_mano_obra WHERE trabajador_id NOT IN (SELECT id FROM personal)")
    cur.execute("DELETE FROM pagos_rrhh WHERE trabajador_id NOT IN (SELECT id FROM personal)")
    cur.execute("INSERT INTO schema_meta (clave, valor) VALUES ('pagos_rrhh_huerfanos_v1', '1')")
    conn.commit()


def _saldo_pendiente_factura(monto_total, monto_pagado):
    return max(0.0, float(monto_total or 0) - float(monto_pagado or 0))


def _dias_vencido_factura(fecha_vencimiento):
    """Días respecto al vencimiento: positivo=vencido, negativo=falta por vencer, 0=vence hoy."""
    try:
        fv = pd.to_datetime(fecha_vencimiento).date()
        return int((hora_chile().date() - fv).days)
    except Exception:
        pass
    return pd.NA


def _migrar_facturas_abonos(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (clave TEXT PRIMARY KEY, valor TEXT)")
    cur = conn.cursor()
    if cur.execute("SELECT 1 FROM schema_meta WHERE clave='facturas_abonos_v1'").fetchone():
        return
    cur.execute("PRAGMA table_info(facturas)")
    cols = [c[1] for c in cur.fetchall()]
    if "monto_pagado" not in cols:
        cur.execute("ALTER TABLE facturas ADD COLUMN monto_pagado REAL DEFAULT 0")
    cur.execute(
        """CREATE TABLE IF NOT EXISTS facturas_abonos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            factura_id INTEGER NOT NULL,
            fecha DATE NOT NULL,
            monto REAL NOT NULL,
            metodo_pago TEXT,
            usuario TEXT,
            fecha_registro TEXT,
            FOREIGN KEY(factura_id) REFERENCES facturas(id)
        )"""
    )
    cur.execute(
        """UPDATE facturas SET monto_pagado = monto_total
           WHERE estado='Pagado' AND nro_documento NOT LIKE '%_P'
             AND COALESCE(monto_pagado, 0) < monto_total - 0.01"""
    )
    f_reg = hora_chile().strftime("%Y-%m-%d %H:%M:%S")
    for fid, mt, met, fp in cur.execute(
        """SELECT id, monto_total, metodo_pago, fecha_pago FROM facturas
           WHERE estado='Pagado' AND nro_documento NOT LIKE '%_P' AND fecha_pago IS NOT NULL"""
    ):
        if cur.execute("SELECT 1 FROM facturas_abonos WHERE factura_id=?", (fid,)).fetchone():
            continue
        cur.execute(
            """INSERT INTO facturas_abonos (factura_id, fecha, monto, metodo_pago, usuario, fecha_registro)
               VALUES (?,?,?,?,?,?)""",
            (fid, fp, float(mt or 0), met or "", "MIGRACION", f_reg),
        )
    cur.execute("INSERT INTO schema_meta (clave, valor) VALUES ('facturas_abonos_v1', '1')")
    conn.commit()


def _sincronizar_abonos_huerfanos_tesoreria(conn):
    """Pagos totales legacy en facturas sin fila en facturas_abonos → historial completo."""
    f_reg = hora_chile().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.cursor()
    pendientes = cur.execute(
        """SELECT f.id,
                  COALESCE(NULLIF(f.monto_pagado, 0), f.monto_total) AS monto,
                  f.metodo_pago, f.fecha_pago
           FROM facturas f
           WHERE f.estado='Pagado' AND f.nro_documento NOT LIKE '%_P'
             AND f.fecha_pago IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM facturas_abonos a WHERE a.factura_id = f.id)"""
    ).fetchall()
    for fid, monto, met, fp in pendientes:
        cur.execute(
            """INSERT INTO facturas_abonos (factura_id, fecha, monto, metodo_pago, usuario, fecha_registro)
               VALUES (?,?,?,?,?,?)""",
            (fid, fp, float(monto or 0), met or "", "SINCRONIZACION", f_reg),
        )
    if pendientes:
        conn.commit()


def _migrar_arriendos_paola_mayo2026_pagados(conn):
    """Históricos LC mal sincronizados: sacarlos de Tesorería pendiente."""
    from demo_web.services.tesoreria_reparar_lc import reparar_tesoreria_lc_pendientes

    reparar_tesoreria_lc_pendientes(
        conn,
        hora_chile_fn=hora_chile,
        ensure_abonos_fn=lambda c: (_ensure_banco_pago_cols(c), _migrar_facturas_abonos(c)),
    )


def _ensure_banco_pago_cols(conn):
    """Agrega columna banco a facturas_abonos / facturas (idempotente)."""
    for table in ("facturas_abonos", "facturas"):
        try:
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        except Exception:
            continue
        if "banco" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN banco TEXT DEFAULT ''")


def _registrar_abono_factura(conn, factura_id, fecha, monto, metodo, usuario, banco=""):
    row = conn.execute(
        """SELECT monto_total, COALESCE(monto_pagado, 0), proveedor, nro_documento
           FROM facturas WHERE id=?""",
        (factura_id,),
    ).fetchone()
    if not row:
        return False, "Documento no encontrado."
    monto_total, monto_pagado, proveedor, nro_doc = row
    if str(nro_doc or "").endswith("_P"):
        return False, "No aplica abono a imputaciones internas."
    saldo = _saldo_pendiente_factura(monto_total, monto_pagado)
    if saldo <= 0.01:
        return False, "El documento ya está pagado."
    monto = float(monto)
    if monto <= 0:
        return False, "El monto debe ser mayor a cero."
    if monto > saldo + 0.01:
        return False, f"El abono excede el saldo pendiente (${f_puntos(saldo)})."
    nuevo_pagado = float(monto_pagado) + monto
    nuevo_estado = "Pagado" if nuevo_pagado >= float(monto_total) - 0.01 else "Pendiente"
    f_reg = hora_chile().strftime("%Y-%m-%d %H:%M:%S")
    _ensure_banco_pago_cols(conn)
    banco = (banco or "").strip()
    conn.execute(
        """INSERT INTO facturas_abonos (factura_id, fecha, monto, metodo_pago, banco, usuario, fecha_registro)
           VALUES (?,?,?,?,?,?,?)""",
        (factura_id, str(fecha), monto, metodo, banco, usuario, f_reg),
    )
    conn.execute(
        """UPDATE facturas SET monto_pagado=?, fecha_pago=?, metodo_pago=?, banco=?, estado=? WHERE id=?""",
        (nuevo_pagado, str(fecha), metodo, banco, nuevo_estado, factura_id),
    )
    return True, {
        "proveedor": proveedor,
        "nro_documento": nro_doc,
        "monto": monto,
        "saldo_restante": _saldo_pendiente_factura(monto_total, nuevo_pagado),
        "estado": nuevo_estado,
    }


def _fecha_minima_historial_tesoreria(conn):
    row = conn.execute(
        """SELECT MIN(fecha) FROM (
               SELECT a.fecha AS fecha
               FROM facturas_abonos a
               JOIN facturas f ON f.id = a.factura_id
               WHERE f.nro_documento NOT LIKE '%_P'
               UNION ALL
               SELECT f.fecha_pago AS fecha
               FROM facturas f
               WHERE f.estado='Pagado' AND f.nro_documento NOT LIKE '%_P'
                 AND f.fecha_pago IS NOT NULL
           )"""
    ).fetchone()
    if row and row[0]:
        try:
            return pd.to_datetime(row[0]).date()
        except Exception:
            pass
    return hoy - timedelta(days=365)


def _query_historial_abonos_tesoreria(conn, fi, ff, bsq="", met="TODOS"):
    base = "f.nro_documento NOT LIKE '%_P'"
    filtros_abono = [base, f"a.fecha BETWEEN '{fi}' AND '{ff}'"]
    filtros_legacy = [
        base,
        "f.estado='Pagado'",
        "f.fecha_pago IS NOT NULL",
        f"f.fecha_pago BETWEEN '{fi}' AND '{ff}'",
        "NOT EXISTS (SELECT 1 FROM facturas_abonos a2 WHERE a2.factura_id = f.id)",
    ]
    if bsq.strip():
        s = bsq.strip().replace("'", "''")
        filtro_bsq = (
            f"(f.nro_documento LIKE '%{s}%' OR f.proveedor LIKE '%{s}%' "
            f"OR IFNULL(f.razon_social,'') LIKE '%{s}%')"
        )
        filtros_abono.append(filtro_bsq)
        filtros_legacy.append(filtro_bsq)
    if met != "TODOS":
        filtros_abono.append(f"a.metodo_pago='{met}'")
        filtros_legacy.append(f"f.metodo_pago='{met}'")
    where_abono = " AND ".join(filtros_abono)
    where_legacy = " AND ".join(filtros_legacy)
    return pd.read_sql_query(
        f"""SELECT f.nro_documento, f.proveedor,
                   IFNULL(f.razon_social, 'La Concepción') AS razon_social,
                   a.monto AS monto_total, a.metodo_pago,
                   IFNULL(a.banco, '') AS banco, a.fecha AS fecha_pago
            FROM facturas_abonos a
            JOIN facturas f ON f.id = a.factura_id
            WHERE {where_abono}
            UNION ALL
            SELECT f.nro_documento, f.proveedor,
                   IFNULL(f.razon_social, 'La Concepción') AS razon_social,
                   COALESCE(NULLIF(f.monto_pagado, 0), f.monto_total) AS monto_total,
                   f.metodo_pago, IFNULL(f.banco, '') AS banco, f.fecha_pago AS fecha_pago
            FROM facturas f
            WHERE {where_legacy}
            ORDER BY fecha_pago DESC, proveedor ASC, metodo_pago ASC, nro_documento ASC""",
        conn,
    )


def _cargar_facturas_pendientes_saldo(conn):
    """CxP neta pendiente: bruto − abonos − imputado Costos (igual que Flujo)."""
    from demo_web.services.lc_excluir_espino import sql_and_excluir_razon_social_espino
    from demo_web.services.tesoreria_cxp import (
        saldo_cxp_neto,
        sql_imputado_costos_subquery,
        sql_solo_cxp_tesoreria,
    )

    imp_sql = sql_imputado_costos_subquery("f")
    excl_espino = sql_and_excluir_razon_social_espino("razon_social", alias="f")
    df = pd.read_sql_query(
        f"""SELECT f.id, f.nro_documento, f.proveedor,
                  IFNULL(f.razon_social, 'La Concepción') AS razon_social,
                  f.fecha_vencimiento, f.monto_total, COALESCE(f.monto_pagado, 0) AS monto_pagado,
                  f.estado, f.metodo_pago, f.fecha_pago, f.concepto, f.tipo,
                  {imp_sql} AS imputado_costos
           FROM facturas f
           WHERE f.estado='Pendiente' AND f.monto_total > 0
             {sql_solo_cxp_tesoreria('f')}
             {excl_espino}""",
        conn,
    )
    if df.empty:
        df["saldo"] = pd.Series(dtype=float)
        df["dias_vencido"] = pd.Series(dtype="Int64")
        return df
    df["saldo"] = df.apply(
        lambda r: saldo_cxp_neto(r["monto_total"], r["monto_pagado"], r["imputado_costos"]),
        axis=1,
    )
    df = df[df["saldo"] > 0.01].copy()
    df["dias_vencido"] = df["fecha_vencimiento"].apply(_dias_vencido_factura)
    return df


def _conectar_db_solo_lectura():
    conn = sqlite3.connect(
        f"file:{_ruta_db_abs()}?mode=ro",
        uri=True,
        timeout=30,
    )
    conn.execute("PRAGMA busy_timeout=30000")
    return _ConnSoloLectura(conn)


def _aplicar_migraciones_db(conn):
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        pass
    _migrar_inventario_unidad_medida(conn)
    migrar_inventario_ingrediente_activo(conn)
    _migrar_movimientos_unidad_medida(conn)
    _migrar_libro_campo_unidad_gasto(conn)
    _unificar_imputaciones_kg(conn)
    _migrar_costos_kg_estimado(conn)
    try:
        normalizar_cuarteles_db(conn)
        conn.commit()
    except Exception:
        pass
    _migrar_familias_producto(conn)
    migrar_maestra_maquinaria(conn)
    migrar_contratistas_contacto(conn)
    migrar_maestra_proveedores(conn)
    _migrar_imputaciones_p_desincronizadas(conn)
    _migrar_pagos_rrhh_huerfanos(conn)
    _migrar_facturas_abonos(conn)
    _sincronizar_abonos_huerfanos_tesoreria(conn)
    _migrar_arriendos_paola_mayo2026_pagados(conn)
    _migrar_tipo_gasto_operacional(conn)
    try:
        from erp_soporte import migrar_tickets_soporte
        migrar_tickets_soporte(conn)
    except Exception:
        pass
    try:
        from erp_respaldo import email_default_desde_secrets, migrar_config_respaldo
        migrar_config_respaldo(conn, email_default_desde_secrets(SECRETS_PATH))
    except Exception:
        pass
    try:
        migrar_flujo_financiero(conn)
    except Exception:
        pass
    try:
        from erp_caja_chica import migrar_caja_chica
        migrar_caja_chica(conn)
    except Exception:
        pass


def conectar_db():
    if _sesion_requiere_solo_lectura():
        return _conectar_db_solo_lectura()
    conn = sqlite3.connect(NOMBRE_DB, timeout=30)
    _aplicar_migraciones_db(conn)
    return conn

def _db_init_lock_path():
    db_path = os.path.abspath(NOMBRE_DB)
    return os.path.join(os.path.dirname(db_path) or ".", ".erp_db_init.lock")

def hash_password(password):
    return hashlib.sha256(str(password or "").strip().encode()).hexdigest()

def f_puntos(v):
    try: return f"{int(round(float(v))):,}".replace(",", ".")
    except: return "0"

def f_peso(v):
    """Montos en pesos CLP: miles con punto, sin decimales (ej. $1.234.567)."""
    return f"${f_puntos(v)}"

def _fmt_styler_peso(v):
    """Formateador pandas Styler para columnas monetarias."""
    return f_peso(v)

def f_decimal(v):
    try: return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return "0,00"

def f_cantidad(v):
    """Cantidades bodega / Libro de Campo (2 decimales, coma decimal)."""
    try: return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return "0,00"

def f_dosis_lc(v):
    """Dosis por 100 L agua — Libro de Campo (3 decimales, coma decimal)."""
    try: return f"{float(v):,.3f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return "0,000"

def _petroleo_neto_desde_bruto(bruto, litros):
    try:
        return (float(bruto) / 1.19) - (float(litros) * IMPUESTO_ESPECIFICO_LITRO)
    except Exception:
        return 0.0

def _petroleo_saldo_estanque(conn):
    """Saldo físico y costo neto del estanque recorriendo movimientos en orden cronológico."""
    rows = conn.execute(
        """SELECT id, tipo, litros, monto_total_compra FROM petroleo
           WHERE tipo IN ('Carga', 'Salida') ORDER BY fecha, id"""
    ).fetchall()
    litros_saldo = 0.0
    costo_neto = 0.0
    for _, tipo, litros, monto in rows:
        l = float(litros or 0)
        if tipo == "Carga":
            costo_neto += _petroleo_neto_desde_bruto(monto, l)
            litros_saldo += l
        else:
            pmp = costo_neto / litros_saldo if litros_saldo > 0 else 0.0
            costo_neto -= l * pmp
            litros_saldo -= l
    return litros_saldo, costo_neto

def _petroleo_pmp_neto(conn):
    """PMP neto $/L = costo neto remanente del estanque / litros remanentes."""
    try:
        litros_saldo, costo_neto = _petroleo_saldo_estanque(conn)
        if litros_saldo <= 0:
            return 0.0
        return costo_neto / litros_saldo
    except Exception:
        return 0.0

def _recalcular_imputacion_salidas_petroleo(conn):
    """Recalcula valor_imputado neto de cada salida según PMP del estanque al momento del despacho."""
    rows = conn.execute(
        """SELECT id, tipo, litros, monto_total_compra FROM petroleo
           WHERE tipo IN ('Carga', 'Salida') ORDER BY fecha, id"""
    ).fetchall()
    litros_saldo = 0.0
    costo_neto = 0.0
    for id_, tipo, litros, monto in rows:
        l = float(litros or 0)
        if tipo == "Carga":
            costo_neto += _petroleo_neto_desde_bruto(monto, l)
            litros_saldo += l
        else:
            pmp = costo_neto / litros_saldo if litros_saldo > 0 else 0.0
            valor = l * pmp
            conn.execute("UPDATE petroleo SET valor_imputado=? WHERE id=?", (valor, id_))
            costo_neto -= valor
            litros_saldo -= l

def registrar_accion(accion, detalle):
    if es_solo_lectura():
        return
    user = st.session_state.get('email', 'Desconocido')
    fecha_h = hora_chile().strftime('%Y-%m-%d %H:%M:%S')
    try:
        conn = conectar_db()
        conn.execute("INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)", (user, accion, detalle, fecha_h))
        conn.commit(); conn.close()
        st.cache_data.clear() 
    except: pass

def _migrar_mail_tesoreria_usuarios(cursor, defaults_correos):
    cursor.execute("PRAGMA table_info(usuarios)")
    cols = [c[1] for c in cursor.fetchall()]
    if "mail_tesoreria" not in cols:
        cursor.execute("ALTER TABLE usuarios ADD COLUMN mail_tesoreria INTEGER DEFAULT 0")
    if cursor.execute("SELECT 1 FROM schema_meta WHERE clave='mail_tesoreria_usuarios_v1'").fetchone():
        return
    try:
        for (em,) in cursor.execute("SELECT email FROM correos_tesoreria").fetchall():
            cursor.execute(
                "UPDATE usuarios SET mail_tesoreria=1 WHERE lower(email)=lower(?)",
                (em,),
            )
    except sqlite3.OperationalError:
        pass
    for em in defaults_correos:
        cursor.execute(
            "UPDATE usuarios SET mail_tesoreria=1 WHERE lower(email)=lower(?)",
            (em.strip(),),
        )
    cursor.execute("INSERT INTO schema_meta (clave, valor) VALUES ('mail_tesoreria_usuarios_v1', '1')")

def _migrar_mail_petroleo_bitacora_usuarios(cursor):
    cursor.execute("PRAGMA table_info(usuarios)")
    cols = [c[1] for c in cursor.fetchall()]
    if "mail_petroleo_bitacora" not in cols:
        cursor.execute(
            "ALTER TABLE usuarios ADD COLUMN mail_petroleo_bitacora INTEGER DEFAULT 0"
        )

def _ensure_mail_petroleo_bitacora_usuarios(conn):
    cur = conn.cursor()
    _migrar_mail_petroleo_bitacora_usuarios(cur)
    conn.commit()

def obtener_destinatarios_petroleo_bitacora(conn):
    try:
        _ensure_mail_petroleo_bitacora_usuarios(conn)
        return [
            r[0]
            for r in conn.execute(
                "SELECT email FROM usuarios WHERE COALESCE(mail_petroleo_bitacora, 0)=1 ORDER BY email"
            ).fetchall()
        ]
    except sqlite3.OperationalError:
        return []

def _ensure_mail_tesoreria_usuarios(conn):
    cur = conn.cursor()
    _migrar_mail_tesoreria_usuarios(cur, CORREOS_TESORERIA_DEFAULT)
    conn.commit()

def obtener_destinatarios_tesoreria(conn):
    try:
        _ensure_mail_tesoreria_usuarios(conn)
        return [
            r[0]
            for r in conn.execute(
                "SELECT email FROM usuarios WHERE COALESCE(mail_tesoreria, 0)=1 ORDER BY email"
            ).fetchall()
        ]
    except sqlite3.OperationalError:
        return []

def _migrar_solo_lectura_usuarios(cursor):
    cursor.execute("PRAGMA table_info(usuarios)")
    cols = [c[1] for c in cursor.fetchall()]
    if "solo_lectura" not in cols:
        cursor.execute("ALTER TABLE usuarios ADD COLUMN solo_lectura INTEGER DEFAULT 0")
    cursor.execute("UPDATE usuarios SET solo_lectura=1 WHERE rol='lector'")

def _ensure_solo_lectura_usuarios(conn):
    cur = conn.cursor()
    _migrar_solo_lectura_usuarios(cur)
    conn.commit()

def _form_mail_tesoreria_usuarios(conn, incluir_vigencia=False):
    _ensure_mail_tesoreria_usuarios(conn)
    _ensure_solo_lectura_usuarios(conn)
    st.caption(
        "Marque **Mail respaldo** para quien debe recibir aviso al registrar pagos en Tesorería "
        "(requiere SMTP en secrets). **Solo lectura** impide registrar o modificar datos en todos los módulos."
    )
    if incluir_vigencia:
        rows = conn.execute(
            """SELECT email, rol, COALESCE(mail_tesoreria, 0), fecha_expira, COALESCE(solo_lectura, 0)
               FROM usuarios ORDER BY email"""
        ).fetchall()
        hc = st.columns([2.4, 1.0, 1.1, 1.0, 1.0])
        hc[0].markdown("**Usuario**")
        hc[1].markdown("**Perfil**")
        hc[2].markdown("**Vigencia**")
        hc[3].markdown("**Mail respaldo**")
        hc[4].markdown("**Solo lectura**")
    else:
        rows = conn.execute(
            """SELECT email, rol, COALESCE(mail_tesoreria, 0), COALESCE(solo_lectura, 0)
               FROM usuarios ORDER BY email"""
        ).fetchall()
        hc = st.columns([2.6, 1.1, 1.1, 1.1])
        hc[0].markdown("**Usuario**")
        hc[1].markdown("**Perfil**")
        hc[2].markdown("**Mail respaldo**")
        hc[3].markdown("**Solo lectura**")
    if not rows:
        st.info("No hay usuarios registrados.")
        return []
    with st.form("seg_mail_teso"):
        for row in rows:
            if incluir_vigencia:
                email, rol, flag, fexp, solo_lect = row
                vig = "Permanente" if not fexp else str(fexp)
                c1, c2, c3, c4, c5 = st.columns([2.4, 1.0, 1.1, 1.0, 1.0])
                c1.caption(email)
                c2.caption(rol)
                c3.caption(vig)
                with c4:
                    st.checkbox("Sí", value=bool(flag), key=f"mail_teso_{email}")
                with c5:
                    es_admin_usr = rol == "admin"
                    st.checkbox(
                        "Sí",
                        value=bool(solo_lect) or rol == "lector",
                        disabled=es_admin_usr,
                        key=f"solo_lect_{email}",
                    )
            else:
                email, rol, flag, solo_lect = row
                c1, c2, c3, c4 = st.columns([2.6, 1.1, 1.1, 1.1])
                c1.caption(email)
                c2.caption(rol)
                with c3:
                    st.checkbox("Sí", value=bool(flag), key=f"mail_teso_{email}")
                with c4:
                    es_admin_usr = rol == "admin"
                    st.checkbox(
                        "Sí",
                        value=bool(solo_lect) or rol == "lector",
                        disabled=es_admin_usr,
                        key=f"solo_lect_{email}",
                    )
        if st.form_submit_button("💾 GUARDAR PREFERENCIAS"):
            for row in rows:
                email = row[0]
                rol = row[1]
                val = 1 if st.session_state.get(f"mail_teso_{email}", False) else 0
                conn.execute("UPDATE usuarios SET mail_tesoreria=? WHERE email=?", (val, email))
                if rol != "admin":
                    sl = 1 if (rol == "lector" or st.session_state.get(f"solo_lect_{email}", False)) else 0
                    conn.execute("UPDATE usuarios SET solo_lectura=? WHERE email=?", (sl, email))
            conn.commit()
            registrar_accion("PREFERENCIAS USUARIOS", "Mail Tesorería / solo lectura actualizados")
            st.success("Preferencias de usuarios actualizadas.")
            st.rerun()
    return [r[0] for r in rows]

def _generar_folio_interno(conn, tabla, fecha):
    prefijo_dia = f"INT-{str(fecha).replace('-', '')}-"
    cursor = conn.cursor()
    cursor.execute(f"SELECT documento FROM {tabla} WHERE documento LIKE ?", (prefijo_dia + "%",))
    idx = len(cursor.fetchall()) + 1
    return f"{prefijo_dia}{idx:02d}"

def _ingrediente_pppl_producto(conn, producto):
    return resolver_ingrediente_activo(conn, producto)

def _panel_corregir_gastos_historial(conn, dfh, tabla, etiqueta_modulo, key_prefix):
    if dfh.empty or st.session_state.get("email") != "osvaldolira@laconcepcion.cl":
        return
    st.divider()
    st.markdown("#### ✏️ Corregir movimientos")
    ids = [int(x) for x in dfh["id"].tolist()]
    sel_key = f"{key_prefix}_corr_sel"
    if sel_key not in st.session_state or st.session_state[sel_key] not in ids:
        st.session_state[sel_key] = ids[0]

    def _fmt_movimiento(mid):
        row = dfh[dfh["id"] == mid].iloc[0]
        doc = str(row.get("documento") or "—")
        return f"ID {mid} · {row['fecha']} · {doc} · {row['item']} · ${f_puntos(row['monto'])}"

    ide = st.selectbox(
        "Movimiento a corregir",
        ids,
        format_func=_fmt_movimiento,
        key=sel_key,
    )
    isel = dfh[dfh["id"] == ide].iloc[0]
    doc_ini = str(isel.get("documento") or "").strip()
    sin_doc_ini = (not doc_ini) or doc_ini.startswith("INT-")
    fk = f"{key_prefix}_cf_{ide}"

    st.caption(f"Editando movimiento **ID {ide}** — {isel['item']}")

    with st.form(f"{key_prefix}_corr_form_{ide}", clear_on_submit=False):
        nf = st.date_input(
            "Fecha",
            value=pd.to_datetime(isel["fecha"]).date(),
            key=f"{fk}_f",
        )
        sin_doc_corr = st.checkbox(
            "Sin documento oficial (asignar folio interno)",
            value=sin_doc_ini,
            key=f"{fk}_sindoc",
        )
        if sin_doc_corr:
            doc_hint = doc_ini if doc_ini.startswith("INT-") else "Se generará folio interno al guardar"
            ndoc = st.text_input("N° Documento", value=doc_hint, disabled=True, key=f"{fk}_doc")
        else:
            ndoc = st.text_input(
                "N° Documento / Factura / Boleta",
                value=doc_ini,
                key=f"{fk}_doc",
            )
        nd = st.text_input("Detalle / Item de gasto", value=str(isel["item"]), key=f"{fk}_item")
        nm = st.number_input(
            "Monto total liquidado ($)",
            value=float(isel["monto"]),
            min_value=0.0,
            key=f"{fk}_monto",
        )
        clave = st.text_input("Clave maestra", type="password", key=f"{fk}_clave")
        if st.form_submit_button("💾 GUARDAR CORRECCIÓN"):
            if clave != CLAVE_MAESTRA:
                st.error("❌ Clave maestra incorrecta.")
            elif nd.strip() == "" or nm <= 0:
                st.error("❌ Detalle y monto son obligatorios.")
            elif sin_doc_corr:
                d_final = doc_ini if doc_ini.startswith("INT-") else _generar_folio_interno(conn, tabla, nf)
                conn.execute(
                    f"UPDATE {tabla} SET fecha=?, documento=?, item=?, monto=? WHERE id=?",
                    (str(nf), d_final, nd.strip(), nm, ide),
                )
                conn.commit()
                registrar_accion(etiqueta_modulo, f"Corrección ID {ide} — {d_final} — {nd.strip()}")
                st.success(f"✅ Movimiento corregido. Folio: {d_final}")
                st.rerun()
            elif not str(ndoc or "").strip():
                st.error("❌ Ingrese N° documento o marque folio interno.")
            else:
                d_final = str(ndoc).strip()
                conn.execute(
                    f"UPDATE {tabla} SET fecha=?, documento=?, item=?, monto=? WHERE id=?",
                    (str(nf), d_final, nd.strip(), nm, ide),
                )
                conn.commit()
                registrar_accion(etiqueta_modulo, f"Corrección ID {ide} — {d_final} — {nd.strip()}")
                st.success("✅ Movimiento corregido. Los datos quedaron en el formulario.")
                st.rerun()

def _fecha_minima_facturas_compras(conn):
    row = conn.execute(
        "SELECT MIN(fecha_compra) FROM facturas WHERE monto_total > 0 AND nro_documento NOT LIKE '%_P'"
    ).fetchone()
    if row and row[0]:
        try:
            return pd.to_datetime(row[0]).date()
        except Exception:
            pass
    return hoy - timedelta(days=365)


def _normalizar_tipo_gasto(val):
    tg = str(val or "").strip()
    return tg if tg else TIPO_GASTO_SIN_CLASIFICAR


def _rubro_matriz_desde_tipo_gasto(tg):
    """Mapea tipo_gasto de factura al rubro de la matriz CC."""
    tg = _normalizar_tipo_gasto(tg)
    if tg in ("Contratistas", "Contratistas externos"):
        return "Contratistas"
    if tg == "RRHH de la casa":
        return None
    if tg in RUBROS_MATRIZ_COSTOS:
        return tg
    return TIPO_GASTO_SIN_CLASIFICAR


def _actualizar_tipo_gasto_factura(conn, doc, prov, tipo_gasto):
    tg = _normalizar_tipo_gasto(tipo_gasto)
    conn.execute(
        "UPDATE facturas SET tipo_gasto=? WHERE proveedor=? AND (nro_documento=? OR nro_documento=?)",
        (tg, prov, doc, doc + "_P"),
    )


def _sincronizar_imputaciones_p_factura(
    conn, doc_old, prov_old, doc_new, prov_new, monto_viejo, monto_nuevo, nfe, nfv, nconcepto, nrazon,
    tipo_gasto=None,
):
    """Actualiza filas _P y recalcula monto_imputado proporcional al cambio de monto bruto."""
    rows = conn.execute(
        "SELECT id, monto_imputado FROM facturas WHERE nro_documento=? AND proveedor=?",
        (doc_old + "_P", prov_old),
    ).fetchall()
    if not rows:
        return 0
    try:
        mv = float(monto_viejo or 0)
        mn = float(monto_nuevo or 0)
    except (TypeError, ValueError):
        mv, mn = 0.0, 0.0
    ratio = (mn / mv) if mv > 0 else 1.0
    tg = _normalizar_tipo_gasto(tipo_gasto) if tipo_gasto else None
    for id_p, m_imp in rows:
        nuevo_imp = float(m_imp or 0) * ratio
        if tg:
            conn.execute(
                "UPDATE facturas SET nro_documento=?, proveedor=?, fecha_compra=?, fecha_vencimiento=?, "
                "concepto=?, razon_social=?, monto_imputado=?, tipo_gasto=? WHERE id=?",
                (doc_new + "_P", prov_new, str(nfe), str(nfv), nconcepto.strip(), nrazon, nuevo_imp, tg, id_p),
            )
        else:
            conn.execute(
                "UPDATE facturas SET nro_documento=?, proveedor=?, fecha_compra=?, fecha_vencimiento=?, "
                "concepto=?, razon_social=?, monto_imputado=? WHERE id=?",
                (doc_new + "_P", prov_new, str(nfe), str(nfv), nconcepto.strip(), nrazon, nuevo_imp, id_p),
            )
    return len(rows)


def _panel_corregir_compras_historial(conn, dfh):
    if dfh is None or dfh.empty or st.session_state.get("email") != "osvaldolira@laconcepcion.cl":
        return
    st.divider()
    st.markdown("#### ✏️ Corregir / eliminar facturas")
    ids = [int(x) for x in dfh["ID"].tolist()]
    sel_key = "comp_corr_sel"
    if sel_key not in st.session_state or st.session_state[sel_key] not in ids:
        st.session_state[sel_key] = ids[0]

    def _fmt_factura(fid):
        row = dfh[dfh["ID"] == fid].iloc[0]
        razon = str(row.get("RAZÓN SOCIAL") or "—").strip() or "—"
        return (
            f"ID {fid} · {row.get('N° DOCUMENTO', '—')} · {row.get('PROVEEDOR', '—')} · "
            f"{razon} · ${f_puntos(row.get('MONTO BRUTO', 0))}"
        )

    idm = st.selectbox(
        "Factura a corregir",
        ids,
        format_func=_fmt_factura,
        key=sel_key,
    )
    fila = conn.execute(
        "SELECT id, nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, concepto, tipo, razon_social, tipo_gasto "
        "FROM facturas WHERE id=?",
        (idm,),
    ).fetchone()
    if not fila:
        st.warning("No se encontró la factura seleccionada.")
        return

    fk = f"comp_cf_{idm}"
    razon_ini = str(fila[8] or RAZONES_SOCIALES_COMPRAS[0]).strip()
    if razon_ini not in RAZONES_SOCIALES_COMPRAS:
        razon_ini = RAZONES_SOCIALES_COMPRAS[0]
    doc_ini = str(fila[1] or "")
    prov_ini = str(fila[2] or "")
    tipo_gasto_ini = _normalizar_tipo_gasto(fila[9] if len(fila) > 9 else None)
    if tipo_gasto_ini == "Contratistas":
        tipo_gasto_ini = "Contratistas externos"
    if tipo_gasto_ini in TIPOS_GASTO_SISTEMA:
        tipo_gasto_ini = TIPO_GASTO_SIN_CLASIFICAR
    if tipo_gasto_ini not in TIPOS_GASTO_HISTORIAL_COMPRAS:
        tipo_gasto_ini = TIPO_GASTO_SIN_CLASIFICAR

    st.caption(f"Editando factura **ID {idm}** — {doc_ini}")

    with st.form(f"comp_corr_form_{idm}", clear_on_submit=False):
        c1, c2 = st.columns(2)
        nrazon = c1.selectbox(
            "Razón social",
            RAZONES_SOCIALES_COMPRAS,
            index=RAZONES_SOCIALES_COMPRAS.index(razon_ini),
            key=f"{fk}_razon",
        )
        nprov = render_select_proveedor(
            conn,
            key=f"{fk}_prov",
            label="Proveedor",
            valor_actual=prov_ini,
        )
        ndoc = c2.text_input("N° Documento", value=doc_ini, key=f"{fk}_doc")
        nfe = c2.date_input(
            "Fecha compra",
            value=pd.to_datetime(fila[3]).date() if fila[3] else hoy,
            key=f"{fk}_fe",
        )
        nfv = c2.date_input(
            "Fecha vencimiento",
            value=pd.to_datetime(fila[4]).date() if fila[4] else hoy,
            key=f"{fk}_fv",
        )
        nmonto = st.number_input(
            "Monto bruto ($)",
            value=float(fila[5] or 0),
            min_value=0.0,
            key=f"{fk}_monto",
        )
        nconcepto = st.text_input(
            "Detalle / concepto",
            value=str(fila[6] or ""),
            key=f"{fk}_concepto",
        )
        ntipo_gasto = st.selectbox(
            "Tipo de gasto (matriz CC)",
            TIPOS_GASTO_HISTORIAL_COMPRAS,
            index=TIPOS_GASTO_HISTORIAL_COMPRAS.index(tipo_gasto_ini),
            key=f"{fk}_tg",
            help="Clasificación para la matriz de costos. Incluye Insumos y Contratistas externos para corregir históricos.",
        )
        clave = st.text_input("Clave maestra", type="password", key=f"{fk}_clave")
        b1, b2 = st.columns(2)
        guardar = b1.form_submit_button("💾 GUARDAR CORRECCIÓN")
        eliminar = b2.form_submit_button("🗑️ ELIMINAR FACTURA")

    if guardar:
        if clave != CLAVE_MAESTRA:
            st.error("❌ Clave maestra incorrecta.")
        elif not str(nprov or "").strip() or not str(ndoc or "").strip():
            st.error("❌ Proveedor y N° documento son obligatorios.")
        elif nmonto <= 0:
            st.error("❌ El monto bruto debe ser superior a $0.")
        else:
            doc_old, prov_old = doc_ini, prov_ini
            doc_new = str(ndoc).strip()
            prov_new = str(nprov).strip()
            tg_guardar = tipo_gasto_canonico_contratista(ntipo_gasto)
            row_ct = conn.execute(
                "SELECT COALESCE(contratista_id, 0) FROM facturas WHERE id=?",
                (idm,),
            ).fetchone()
            if row_ct and int(row_ct[0] or 0) != 0:
                tg_guardar = "Contratistas"
            conn.execute(
                "UPDATE facturas SET nro_documento=?, proveedor=?, fecha_compra=?, fecha_vencimiento=?, "
                "monto_total=?, concepto=?, razon_social=?, tipo_gasto=? WHERE id=?",
                (doc_new, prov_new, str(nfe), str(nfv), nmonto, nconcepto.strip(), nrazon, tg_guardar, idm),
            )
            _actualizar_tipo_gasto_factura(conn, doc_new, prov_new, tg_guardar)
            n_imp = _sincronizar_imputaciones_p_factura(
                conn, doc_old, prov_old, doc_new, prov_new,
                float(fila[5] or 0), nmonto, nfe, nfv, nconcepto, nrazon, tg_guardar,
            )
            conn.commit()
            det_bit = f"Corrección ID {idm} — {doc_new} — {nrazon}"
            if n_imp:
                det_bit += f" | {n_imp} imputación(es) _P recalculada(s)"
            registrar_accion("COMPRA", det_bit)
            msg = "✅ Factura corregida."
            if n_imp:
                msg += f" Se actualizaron {n_imp} imputación(es) en centros de costo."
            st.success(msg)
            st.rerun()

    if eliminar:
        if clave != CLAVE_MAESTRA:
            st.error("❌ Clave maestra incorrecta.")
        else:
            conn.execute("DELETE FROM facturas WHERE id=?", (idm,))
            conn.execute(
                "DELETE FROM facturas WHERE nro_documento=? AND proveedor=?",
                (doc_ini + "_P", prov_ini),
            )
            conn.commit()
            registrar_accion("BORRADO", doc_ini)
            st.success(f"✅ Factura {doc_ini} eliminada.")
            st.rerun()

def _panel_corregir_movimientos_bodega_cuartel(conn, df_mov, cuartel, key_prefix):
    if df_mov is None or df_mov.empty or not es_admin():
        return
    st.divider()
    st.markdown("#### ✏️ Corregir / eliminar salida de bodega")
    st.caption("Al **eliminar** o **reducir** cantidad, el stock se repone en inventario automáticamente.")
    ids = [int(x) for x in df_mov["ID"].tolist()]
    sel_key = f"{key_prefix}_mov_sel"
    if sel_key not in st.session_state or st.session_state[sel_key] not in ids:
        st.session_state[sel_key] = ids[-1]

    def _fmt_mov(mid):
        row = df_mov[df_mov["ID"] == mid].iloc[0]
        return (
            f"ID {mid} · {row['FECHA']} · {row['PRODUCTO']} · "
            f"{f_cantidad(row['CANTIDAD'])} {row['UM']} · ${f_puntos(row['VALOR_IMPUTADO'])}"
        )

    ide = st.selectbox("Movimiento de salida", ids, format_func=_fmt_mov, key=sel_key)
    isel = df_mov[df_mov["ID"] == ide].iloc[0]
    fk = f"{key_prefix}_mov_{ide}"
    pid = int(isel["PRODUCTO_ID"])
    inv_row = conn.execute(
        "SELECT stock, COALESCE(unidad_medida, ?) FROM inventario WHERE id=?",
        (DEFAULT_UNIDAD_INSUMO, pid),
    ).fetchone()
    stock_inv = float(inv_row[0] or 0) if inv_row else 0.0
    um_inv = str(inv_row[1] if inv_row else DEFAULT_UNIDAD_INSUMO)
    cant_bd = float(isel["CANTIDAD"])
    st.caption(
        f"Editando salida **ID {ide}** — {isel['PRODUCTO']} · "
        f"stock disponible **{f_cantidad(stock_inv)} {um_inv}** · cuartel **{cuartel}**"
    )

    with st.form(f"{key_prefix}_mov_form_{ide}", clear_on_submit=False):
        nf = st.date_input("Fecha", value=pd.to_datetime(isel["FECHA"]).date(), key=f"{fk}_f")
        c_cant, c_um = st.columns(2)
        nc = c_cant.number_input(
            "Cantidad",
            value=float(cant_bd),
            min_value=0.0,
            step=0.01,
            format="%.2f",
            key=f"{fk}_c",
        )
        c_um.text_input("Unidad de medida", value=um_inv, disabled=True, key=f"{fk}_um")
        nv = st.number_input(
            "Valor imputado ($)",
            value=float(isel["VALOR_IMPUTADO"] or 0),
            min_value=0.0,
            key=f"{fk}_v",
        )
        clave = st.text_input("Clave maestra", type="password", key=f"{fk}_clave")
        b1, b2 = st.columns(2)
        guardar = b1.form_submit_button("💾 GUARDAR CORRECCIÓN")
        eliminar = b2.form_submit_button("🗑️ ELIMINAR SALIDA")

    if guardar:
        if clave != CLAVE_MAESTRA:
            st.error("❌ Clave maestra incorrecta.")
        elif nc <= 0:
            st.error("❌ La cantidad debe ser mayor a cero.")
        else:
            old_c = cant_bd
            delta_stock = old_c - float(nc)
            if delta_stock < 0:
                if stock_inv + delta_stock < -1e-9:
                    st.error(
                        f"❌ Stock insuficiente para aumentar la salida "
                        f"(disponible: {f_cantidad(stock_inv)} {um_inv})."
                    )
                    return
            conn.execute(
                "UPDATE movimientos SET fecha=?, cantidad=?, valor_imputado=?, unidad_medida=? WHERE id=?",
                (str(nf), float(nc), nv, um_inv, ide),
            )
            if delta_stock != 0:
                conn.execute(
                    "UPDATE inventario SET stock = stock + ? WHERE id=?",
                    (delta_stock, pid),
                )
            conn.commit()
            registrar_accion("BODEGA", f"Corrección salida ID {ide} cuartel {cuartel} ({nc} {um_inv})")
            st.success(f"✅ Salida corregida: **{f_cantidad(nc)} {um_inv}**. Stock actualizado.")
            st.rerun()

    if eliminar:
        if clave != CLAVE_MAESTRA:
            st.error("❌ Clave maestra incorrecta.")
        else:
            pid = int(isel["PRODUCTO_ID"])
            cant = float(isel["CANTIDAD"])
            conn.execute("DELETE FROM movimientos WHERE id=?", (ide,))
            conn.execute(
                "UPDATE inventario SET stock = stock + ? WHERE id=?",
                (cant, pid),
            )
            conn.commit()
            registrar_accion("BODEGA", f"Eliminada salida ID {ide} — stock +{cant} {isel['UM']}")
            st.success(f"✅ Salida eliminada. Se repusieron {f_cantidad(cant)} {isel['UM']} en bodega.")
            st.rerun()

def _smtp_adjuntar_html(msg, cuerpo_html):
    msg.attach(MIMEText(cuerpo_html, "html", "utf-8"))

def _alerta_acceso_marca():
    return (NOMBRE_ERP or "ERP Agrícola La Concepción").strip()


def _alerta_acceso_scope():
    slug = (TENANT_SLUG or "concepcion").strip().lower() or "concepcion"
    return f"agricola-{slug}"


def _alerta_acceso_pie():
    nombre = (TENANT_NOMBRE or "").strip()
    if nombre:
        return f"Correo automático de seguridad — {nombre}."
    return f"Correo automático de seguridad — {_alerta_acceso_marca()}."


def enviar_correo_alerta(usuario_intruso, exitoso=True):
    """Despacha una alerta SMTP de alta velocidad (espejo) v11.5.4"""
    from erp_correo_html import alerta_acceso_fallo_en_cooldown, omitir_alerta_acceso, plantilla_correo_html
    if omitir_alerta_acceso(usuario_intruso):
        return
    scope = _alerta_acceso_scope()
    if (not exitoso) and alerta_acceso_fallo_en_cooldown(usuario_intruso, minutos=15, scope=scope):
        return

    try:
        if "gmail_smtp" not in st.secrets:
            return
        conf = st.secrets["gmail_smtp"]
        
        emisor = conf["correo_emisor"]
        clave = conf["clave_application"] if "clave_application" in conf else conf["clave_aplicacion"]
        receptor = conf["correo_receptor"]
        
        f_h = hora_chile().strftime('%Y-%m-%d %H:%M:%S')
        marca = _alerta_acceso_marca()
        
        msg = MIMEMultipart()
        msg['From'] = smtp_from_header(emisor)
        msg['To'] = receptor
        
        if exitoso:
            msg['Subject'] = f"🚨 ALERTA: Acceso Detectado en {marca}"
            tipo_alerta = "Inicio de Sesión Exitoso"
            tipo_tema = "alerta_ingreso_ok"
            titulo = "🚜 Acceso detectado"
            detalle_msg = "Se ha registrado un inicio de sesión exitoso en la plataforma de un usuario secundario."
        else:
            msg['Subject'] = f"🔥 ADVERTENCIA: Intento de Acceso RECHAZADO en {marca}"
            tipo_alerta = "Intento de Acceso Fallido / Clave Incorrecta"
            tipo_tema = "alerta_ingreso_fallo"
            titulo = "🔥 Intento de acceso rechazado"
            detalle_msg = "Se ha bloqueado un intento fallido de inicio de sesión. Alguien ingresó credenciales incorrectas."
        
        interior = f"""
            <p>{detalle_msg}</p>
            <hr style='border: 0; border-top: 1px solid #eee;'>
            <p><b>⚠️ Tipo de Evento:</b> {tipo_alerta}</p>
            <p><b>👤 Correo Ingresado:</b> <span style='font-weight: bold;'>{usuario_intruso}</span></p>
            <p><b>📅 Fecha y Hora Oficial:</b> {f_h} (Chile UTC-4)</p>
            <p><b>🌐 Entorno de Ejecución:</b> Servidor VPS Producción</p>
        """
        cuerpo = plantilla_correo_html(
            tipo_tema,
            titulo,
            interior,
            nombre_erp=marca,
            pie=_alerta_acceso_pie(),
        )
        _smtp_adjuntar_html(msg, cuerpo)
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(emisor, clave)
        server.sendmail(emisor, receptor, msg.as_string())
        server.quit()
    except Exception as e:
        try:
            conn = conectar_db()
            f_h = hora_chile().strftime('%Y-%m-%d %H:%M:%S')
            conn.execute("INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)", 
                         ("SISTEMA", "FALLO_SMTP", str(e)[:150], f_h))
            conn.commit(); conn.close()
        except:
            pass

def _conf_smtp_prod():
    try:
        if "gmail_smtp" not in st.secrets:
            return None
        conf = st.secrets["gmail_smtp"]
        clave = conf.get("clave_application") or conf.get("clave_aplicacion")
        if not clave:
            return None
        emisor = conf["correo_emisor"]
        return {
            "emisor": emisor,
            "from_header": smtp_from_header(emisor),
            "clave": clave,
            "receptor_admin": conf.get("correo_receptor", conf["correo_emisor"]),
        }
    except Exception:
        return None

def _enviar_correo_html(asunto, cuerpo_html, destinatarios, cc=None):
    conf = _conf_smtp_prod()
    if not conf:
        return False
    destinatarios = [d.strip() for d in destinatarios if d and str(d).strip()]
    if not destinatarios:
        return False
    try:
        msg = MIMEMultipart()
        msg["From"] = conf["from_header"]
        msg["To"] = ", ".join(destinatarios)
        msg["Subject"] = asunto
        todos = list(destinatarios)
        if cc and cc.strip() and cc.strip() not in todos:
            msg["Cc"] = cc.strip()
            todos.append(cc.strip())
        _smtp_adjuntar_html(msg, cuerpo_html)
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(conf["emisor"], conf["clave"])
        server.sendmail(conf["emisor"], todos, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        try:
            conn = conectar_db()
            f_h = hora_chile().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)",
                (st.session_state.get("email", "SISTEMA"), "FALLO_SMTP", str(e)[:150], f_h),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass
        return False

def _invitacion_marca():
    return (NOMBRE_ERP or "ERP Agrícola La Concepción").strip()


def _invitacion_nombre_corto():
    return (TENANT_NOMBRE or "La Concepción").strip()


def _invitacion_enlaces_html():
    slug = (TENANT_SLUG or "concepcion").strip().lower()
    links = [AGRICOLA_LOGIN_URL]
    if slug == "concepcion" and PROD_URL_ALT and PROD_URL_ALT not in links:
        links.append(PROD_URL_ALT)
    return "\n".join(
        f"<p style='margin: 4px 0;'><a href='{url}' style='color: #5E35B1; font-weight: bold;'>{url}</a></p>"
        for url in links
    )


def enviar_correo_invitacion_concepcion(email_nuevo, clave_plana, rol, admin_email):
    from erp_correo_html import plantilla_correo_html

    f_h = hora_chile().strftime("%d-%m-%Y %H:%M")
    perfil_txt = PERFILES_USUARIO_TXT.get(rol, rol)
    marca = _invitacion_marca()
    nombre_corto = _invitacion_nombre_corto()
    admin_txt = admin_email or f"Administrador {marca}"
    interior = f"""
            <p style='color: #1F2933; line-height: 1.55;'>Estimado/a colaborador/a,</p>
            <p style='color: #1F2933; line-height: 1.55;'>Ha sido invitado/a a <b>integrar el equipo de {marca}</b>.
            A partir de ahora podrá acceder a la plataforma de gestión del campo para registrar operaciones,
            consultar información y trabajar según el perfil asignado por administración.</p>
            <div style='background: #F3E5F5; border: 1px solid #CE93D8; border-radius: 10px; padding: 18px 20px; margin: 20px 0;'>
                <p style='margin: 0 0 10px; font-weight: 800; color: #5E35B1; font-size: 15px;'>📋 Sus datos de acceso</p>
                <p style='margin: 6px 0;'><b>Usuario:</b> <span style='color: #4527A0; font-weight: bold;'>{email_nuevo}</span></p>
                <p style='margin: 6px 0;'><b>Contraseña:</b> <span style='color: #4527A0; font-weight: bold;'>{clave_plana}</span></p>
                <p style='margin: 6px 0;'><b>Perfil asignado:</b> {perfil_txt}</p>
                <p style='margin: 6px 0;'><b>Vigencia:</b> Acceso permanente al equipo</p>
                <p style='margin: 10px 0 0;'><b>Enlaces de acceso:</b></p>
                {_invitacion_enlaces_html()}
            </div>
            <p style='color: #1F2933; line-height: 1.55;'><b>Primeros pasos sugeridos:</b> ingrese con sus credenciales, elija <b>{nombre_corto}</b> si el acceso es multi-empresa,
            revise el menú lateral según su perfil y consulte el módulo <b>Manual</b> para una guía rápida de uso.</p>
            <p style='text-align: center; margin: 24px 0;'>
                <a href='{AGRICOLA_LOGIN_URL}' style='display: inline-block; background: linear-gradient(135deg, #5E35B1, #7E57C2); color: white; text-decoration: none; padding: 12px 28px; border-radius: 10px; font-weight: 800;'>ACCEDER A {marca.upper()}</a>
            </p>
            <p style='font-size: 13px; color: #5F6B7A; margin: 6px 0;'><b>Invitación emitida por:</b> {admin_txt}</p>
            <p style='font-size: 13px; color: #5F6B7A; margin: 6px 0;'><b>Fecha:</b> {f_h} (Chile UTC-4)</p>
            <p style='font-size: 13px; color: #5F6B7A; margin: 6px 0;'><b>Entorno:</b> Producción — {nombre_corto}</p>
    """
    cuerpo = plantilla_correo_html(
        "invitacion",
        f"🍒 Bienvenido al equipo {marca}",
        interior,
        nombre_erp=marca,
        pie=f"Mensaje automático al crear su usuario en {marca}. Ante dudas, contacte al administrador.",
    )
    ok_invitado = _enviar_correo_html(
        f"🍒 Invitación — Integración a {marca}",
        cuerpo,
        [email_nuevo],
    )
    return ok_invitado


def reenviar_correo_invitacion_concepcion(email_usuario, admin_email):
    """Genera clave nueva, actualiza usuario y reenvía invitación (admin no ve la clave)."""
    from erp_correo_html import generar_clave_invitacion

    email_usuario = (email_usuario or "").strip().lower()
    if not email_usuario:
        return False
    conn = conectar_db()
    try:
        row = conn.execute("SELECT rol FROM usuarios WHERE email=?", (email_usuario,)).fetchone()
        if not row:
            return False
        clave = generar_clave_invitacion()
        conn.execute(
            "UPDATE usuarios SET password=? WHERE email=?",
            (hash_password(clave), email_usuario),
        )
        conn.commit()
        ok = enviar_correo_invitacion_concepcion(email_usuario, clave, row[0], admin_email)
        if ok:
            registrar_accion("INVITACION REENVIADA", email_usuario)
        return ok
    finally:
        conn.close()

def anclaje_sesion_definitivo():
    if st.session_state.get('logged_in') and not es_solo_lectura():
        try:
            conn = conectar_db()
            tag = f"acceso_v1154_{st.session_state['email']}_{hora_chile().strftime('%Y%m%d')}"
            if tag not in st.session_state:
                f_h = hora_chile().strftime('%Y-%m-%d %H:%M:%S')
                conn.execute(
                    "INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)",
                    (st.session_state['email'], "ACCESO", "Sesión Detectada (v11.5.4)", f_h),
                )
                conn.commit()
                st.session_state[tag] = True
            from erp_sesiones_usuarios import registrar_pulse_usuario
            registrar_pulse_usuario(
                conn,
                st.session_state.get("email", ""),
                st.session_state.get("modulo_activo", ""),
            )
            conn.close()
        except Exception:
            pass


def _ensure_prorrateo_cc(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS prorrateo_cc (
            centro_costo TEXT PRIMARY KEY,
            porcentaje REAL NOT NULL,
            superficie_ha REAL DEFAULT 0
        )"""
    )
    cols = {r[1] for r in conn.execute("PRAGMA table_info(prorrateo_cc)").fetchall()}
    if "superficie_ha" not in cols:
        try:
            conn.execute("ALTER TABLE prorrateo_cc ADD COLUMN superficie_ha REAL DEFAULT 0")
        except Exception:
            pass
    _sembrar_prorrateo_cc(conn)


def _sembrar_prorrateo_cc(conn):
    if _conn_es_solo_lectura(conn) or _sesion_requiere_solo_lectura():
        return
    for cc, pct in PRORRATEO_CC_DEFAULT.items():
        ha = float(pct)  # semilla: 1 % ≈ 1 ha hasta que el cliente ajuste superficies reales
        conn.execute(
            "INSERT OR IGNORE INTO prorrateo_cc (centro_costo, porcentaje, superficie_ha) VALUES (?,?,?)",
            (cc, float(pct), ha),
        )
    # Rellenar ha vacías en filas ya existentes
    for cc, pct in PRORRATEO_CC_DEFAULT.items():
        row = conn.execute(
            "SELECT COALESCE(superficie_ha, 0) FROM prorrateo_cc WHERE centro_costo=?",
            (cc,),
        ).fetchone()
        if row and float(row[0] or 0) <= 0:
            conn.execute(
                "UPDATE prorrateo_cc SET superficie_ha=? WHERE centro_costo=?",
                (float(pct), cc),
            )

def cargar_prorrateo_cc(conn):
    """Pesos 0–1 para imputación. Acepta filas en % (suma~100) o fracción (suma~1)."""
    _ensure_prorrateo_cc(conn)
    rows = conn.execute(
        "SELECT centro_costo, porcentaje FROM prorrateo_cc ORDER BY centro_costo"
    ).fetchall()
    if rows:
        raw = {str(r[0]): float(r[1] or 0) for r in rows}
    else:
        raw = {k: float(v) for k, v in PRORRATEO_CC_DEFAULT.items()}
    raw = {k: v for k, v in raw.items() if v > 0}
    total = sum(raw.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in raw.items()}


def cargar_prorrateo_cc_pct(conn):
    """Porcentajes del campo (0–100) para pantalla de administración."""
    _ensure_prorrateo_cc(conn)
    rows = conn.execute(
        "SELECT centro_costo, porcentaje FROM prorrateo_cc ORDER BY centro_costo"
    ).fetchall()
    if rows:
        return {str(r[0]): float(r[1]) for r in rows}
    return dict(PRORRATEO_CC_DEFAULT)

def cargar_superficies_cc(conn):
    _ensure_prorrateo_cc(conn)
    rows = conn.execute(
        "SELECT centro_costo, COALESCE(superficie_ha, 0) FROM prorrateo_cc ORDER BY centro_costo"
    ).fetchall()
    out = {str(r[0]): float(r[1] or 0) for r in rows}
    for cc, pct in PRORRATEO_CC_DEFAULT.items():
        out.setdefault(cc, float(pct))
    return out

def guardar_prorrateo_superficies_cc(conn, datos):
    """datos: {cc: {'porcentaje': float, 'superficie_ha': float}}"""
    _ensure_prorrateo_cc(conn)
    for cc, vals in datos.items():
        conn.execute(
            "INSERT INTO prorrateo_cc (centro_costo, porcentaje, superficie_ha) VALUES (?,?,?) "
            "ON CONFLICT(centro_costo) DO UPDATE SET "
            "porcentaje=excluded.porcentaje, superficie_ha=excluded.superficie_ha",
            (cc, float(vals["porcentaje"]), float(vals.get("superficie_ha") or 0)),
        )
    conn.commit()

def _clasificar_cc_seleccionados(seleccionados):
    sel = [str(c).strip().upper() for c in seleccionados if c]
    directos = [c for c in sel if c in CUARTELES_IMPUTACION_DIRECTA]
    prorr = [c for c in sel if c in CUARTELES_PRORRATEO]
    invalid = [c for c in sel if c not in directos and c not in prorr]
    return directos, prorr, invalid

def _reparto_por_cc(conn, total, seleccionados):
    """Reparte monto/cantidad entre CC seleccionados. Retorna ([(cc, parte), ...], error)."""
    try:
        total = float(total)
    except (TypeError, ValueError):
        return None, "Total inválido."
    if total <= 0:
        return None, "El total debe ser mayor a cero."
    directos, prorr, invalid = _clasificar_cc_seleccionados(seleccionados)
    if invalid:
        return None, f"Centro de costo no válido: {invalid[0]}"
    if not directos and not prorr:
        return None, "Seleccione al menos un cuartel."
    if directos and prorr:
        return None, (
            "No mezcle cuarteles del campo (Corte 1, Corte 2, Ciruelos, Nogales) "
            "con El Espino u Otros en el mismo movimiento."
        )
    if directos:
        parte = total / len(directos)
        return [(c, parte) for c in directos], None
    pesos = cargar_prorrateo_cc(conn)
    sub = {c: pesos.get(c, 0.0) for c in prorr}
    suma = sum(sub.values())
    if suma <= 0:
        parte = total / len(prorr)
        return [(c, parte) for c in prorr], None
    return [(c, total * sub[c] / suma) for c in prorr], None

def normalizar_cuarteles_db(conn=None):
    """Unifica nombres históricos CORTE1/CORTE2 → CORTE 1/CORTE 2 (solo UPDATE, sin borrar)."""
    mapping = {
        "CEREZOS CORTE1": "CEREZOS CORTE 1",
        "CEREZOS CORTE2": "CEREZOS CORTE 2",
    }
    own_conn = conn is None
    try:
        if own_conn:
            conn = conectar_db()
        for old, new in mapping.items():
            for table, col in [
                ("movimientos", "centro_costo"),
                ("petroleo", "centro_costo"),
                ("facturas", "centro_costo"),
                ("ajustes_costos", "centro_costo"),
                ("costos_mano_obra", "centro_costo"),
                ("libro_campo", "sector"),
            ]:
                try:
                    conn.execute(
                        f"UPDATE {table} SET {col}=? WHERE UPPER(TRIM({col}))=?",
                        (new, old),
                    )
                except Exception:
                    pass
        if own_conn:
            conn.commit()
            conn.close()
    except Exception:
        if own_conn and conn is not None:
            try:
                conn.close()
            except Exception:
                pass

def inicializar_db():
    lock_path = _db_init_lock_path()
    os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
    with open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        conn = conectar_db()
        cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS facturas (id INTEGER PRIMARY KEY AUTOINCREMENT, nro_documento TEXT, proveedor TEXT, fecha_compra DATE, fecha_vencimiento DATE, monto_neto REAL, monto_total REAL, estado TEXT DEFAULT 'Pendiente', tipo TEXT DEFAULT 'Factura', metodo_pago TEXT, fecha_pago DATE, concepto TEXT, centro_costo TEXT, monto_imputado REAL DEFAULT 0)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS inventario (id INTEGER PRIMARY KEY AUTOINCREMENT, producto TEXT, familia TEXT, stock REAL DEFAULT 0, stock_minimo REAL DEFAULT 0, precio_medio REAL DEFAULT 0, unidad_medida TEXT DEFAULT 'kg', ingrediente_activo TEXT DEFAULT '')""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS movimientos (id INTEGER PRIMARY KEY AUTOINCREMENT, producto_id INTEGER, tipo TEXT, cantidad REAL, centro_costo TEXT, fecha DATE, valor_imputado REAL DEFAULT 0)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, password TEXT)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS petroleo (id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT, litros REAL, proveedor TEXT, monto_total_compra REAL, vehiculo TEXT, responsable TEXT, centro_costo TEXT, fecha DATE, valor_imputado REAL)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS bitacora (id INTEGER PRIMARY KEY AUTOINCREMENT, usuario TEXT, accion TEXT, detalle TEXT, fecha_hora DATETIME)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS ajustes_costos (id INTEGER PRIMARY KEY AUTOINCREMENT, centro_costo TEXT, monto REAL, fecha DATE, motivo TEXT)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS costos_ppto_temporada (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        temporada TEXT NOT NULL,
        centro_costo TEXT NOT NULL,
        monto_ppto REAL DEFAULT 0,
        UNIQUE(temporada, centro_costo)
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS costos_kg_estimado_temporada (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        temporada TEXT NOT NULL,
        centro_costo TEXT NOT NULL,
        kg_estimado REAL DEFAULT 0,
        UNIQUE(temporada, centro_costo)
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS prorrateo_cc (
        centro_costo TEXT PRIMARY KEY,
        porcentaje REAL NOT NULL
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS gastos_espino (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha DATE, documento TEXT, item TEXT, monto REAL)""")
    
    cursor.execute("""CREATE TABLE IF NOT EXISTS libro_campo (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        fecha DATE, 
        n_aplicacion INTEGER, 
        sector TEXT, 
        especie TEXT, 
        producto TEXT, 
        ingrediente TEXT, 
        dosis REAL, 
        unidad_dosis TEXT, 
        gasto_total REAL, 
        vol_total REAL, 
        tractor TEXT, 
        maquina TEXT, 
        aplicadores TEXT,
        fecha_viable DATE,
        n_orden TEXT DEFAULT '',
        est_fenologico TEXT DEFAULT '',
        motivo TEXT DEFAULT '',
        car_etiqueta INTEGER DEFAULT 0,
        car_agenda INTEGER DEFAULT 0,
        car_mayor INTEGER DEFAULT 0,
        unidad_gasto TEXT DEFAULT ''
    )""")
    
    cursor.execute("""CREATE TABLE IF NOT EXISTS bitacora_maquinaria (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cod_registro TEXT UNIQUE,
        id_maquinaria TEXT,
        tipo_evento TEXT,
        detalle_mantenimiento TEXT,
        encargado_taller TEXT,
        responsable_interno TEXT,
        fecha_evento DATE,
        etiqueta_ingreso TEXT
    )""")
    
    cursor.execute("CREATE TABLE IF NOT EXISTS personal (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT, rut TEXT UNIQUE, cargo TEXT, fecha_contrato DATE, estado TEXT DEFAULT 'Activo')")
    cursor.execute("PRAGMA table_info(personal)")
    columnas = [col[1] for col in cursor.fetchall()]
    if 'fecha_contrato' not in columnas:
        try: cursor.execute("ALTER TABLE personal ADD COLUMN fecha_contrato DATE")
        except: pass
        
    cursor.execute("""CREATE TABLE IF NOT EXISTS remuneraciones_fichas (trabajador_id INTEGER PRIMARY KEY, sueldo_pactado REAL, monto_prestamo REAL DEFAULT 0, cuotas_prestamo INTEGER DEFAULT 0, cuotas_pagadas INTEGER DEFAULT 0, suple_fijo REAL DEFAULT 0, FOREIGN KEY(trabajador_id) REFERENCES personal(id))""")
    cursor.execute("PRAGMA table_info(remuneraciones_fichas)")
    cols_rf = [col[1] for col in cursor.fetchall()]
    if 'cuotas_pagadas' not in cols_rf:
        try: cursor.execute("ALTER TABLE remuneraciones_fichas ADD COLUMN cuotas_pagadas INTEGER DEFAULT 0")
        except: pass
    if 'primera_cuota_mes' not in cols_rf:
        try: cursor.execute("ALTER TABLE remuneraciones_fichas ADD COLUMN primera_cuota_mes TEXT")
        except: pass
    if 'primera_cuota_anio' not in cols_rf:
        try: cursor.execute("ALTER TABLE remuneraciones_fichas ADD COLUMN primera_cuota_anio INTEGER")
        except: pass
    cursor.execute("""CREATE TABLE IF NOT EXISTS costos_mano_obra (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trabajador_id INTEGER,
        centro_costo TEXT,
        monto REAL,
        mes TEXT,
        anio INTEGER,
        fecha_registro DATE
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS pagos_rrhh (id INTEGER PRIMARY KEY AUTOINCREMENT, trabajador_id INTEGER, mes TEXT, anio INTEGER, liquido REAL, leyes_sociales REAL, costo_empresa REAL, tipo TEXT, fecha_registro DATE, descuento_prestamo REAL DEFAULT 0)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS provision_liquido_mes (
        trabajador_id INTEGER NOT NULL,
        mes TEXT NOT NULL,
        anio INTEGER NOT NULL,
        liquido_provision REAL DEFAULT 0,
        PRIMARY KEY (trabajador_id, mes, anio)
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS remuneracion_mes (
        trabajador_id INTEGER NOT NULL,
        mes TEXT NOT NULL,
        anio INTEGER NOT NULL,
        liquido_ganado REAL DEFAULT 0,
        suple REAL DEFAULT 0,
        descuento_prestamo REAL DEFAULT 0,
        liquido_provision REAL DEFAULT 0,
        PRIMARY KEY (trabajador_id, mes, anio)
    )""")
    cursor.execute("PRAGMA table_info(pagos_rrhh)")
    cols_prrhh = [c[1] for c in cursor.fetchall()]
    if "descuento_prestamo" not in cols_prrhh:
        try:
            cursor.execute("ALTER TABLE pagos_rrhh ADD COLUMN descuento_prestamo REAL DEFAULT 0")
        except Exception:
            pass
    cursor.execute("PRAGMA table_info(usuarios)")
    cols_usr = [c[1] for c in cursor.fetchall()]
    if "rol" not in cols_usr:
        try: cursor.execute("ALTER TABLE usuarios ADD COLUMN rol TEXT DEFAULT 'operador'")
        except: pass
    cursor.execute("PRAGMA table_info(usuarios)")
    cols_usr = [c[1] for c in cursor.fetchall()]
    if "modulos" not in cols_usr:
        try: cursor.execute("ALTER TABLE usuarios ADD COLUMN modulos TEXT DEFAULT ''")
        except: pass
    _migrar_solo_lectura_usuarios(cursor)
    usuarios = [
        ('osvaldolira@laconcepcion.cl', hash_password('9083'), 'admin'),
        ('secretaria@laconcepcion.cl', hash_password('9111'), 'operador'),
        ('certificacion@laconcepcion.cl', hash_password('9091'), 'certificacion'),
    ]
    for u, p, r in usuarios:
        cursor.execute("INSERT OR IGNORE INTO usuarios (email, password, rol) VALUES (?,?,?)", (u, p, r))
    cursor.execute("UPDATE usuarios SET rol='admin', password=? WHERE email='osvaldolira@laconcepcion.cl'", (hash_password('9083'),))
    cursor.execute("UPDATE usuarios SET rol='operador' WHERE email='secretaria@laconcepcion.cl'")
    cursor.execute("UPDATE usuarios SET rol='certificacion', password=? WHERE email='certificacion@laconcepcion.cl'", (hash_password('9091'),))
    if conn.execute("SELECT COUNT(*) FROM gastos_espino").fetchone()[0] == 0:
        cursor.executemany("INSERT INTO gastos_espino (fecha, documento, item, monto) VALUES (?,?,?,?)", DATA_ESP_HISTORICA)
    migrar_gastos_espino(cursor)
    migrar_globalgap(cursor)
    migrar_gantt(cursor)
    cursor.execute("CREATE TABLE IF NOT EXISTS schema_meta (clave TEXT PRIMARY KEY, valor TEXT)")
    if not cursor.execute("SELECT 1 FROM schema_meta WHERE clave='petroleo_carga_bruto_v1'").fetchone():
        cursor.execute(
            "UPDATE petroleo SET monto_total_compra = (monto_total_compra + litros * ?) * 1.19 WHERE lower(tipo) = 'carga'",
            (IMPUESTO_ESPECIFICO_LITRO,),
        )
        cursor.execute("INSERT INTO schema_meta (clave, valor) VALUES ('petroleo_carga_bruto_v1', '1')")
    if not cursor.execute("SELECT 1 FROM schema_meta WHERE clave='petroleo_salida_neto_v2'").fetchone():
        _recalcular_imputacion_salidas_petroleo(conn)
        cursor.execute("INSERT INTO schema_meta (clave, valor) VALUES ('petroleo_salida_neto_v2', '1')")
    if not cursor.execute("SELECT 1 FROM schema_meta WHERE clave='rrhh_descuento_prestamo_v1'").fetchone():
        _migrar_descuento_prestamo_historico(conn)
        cursor.execute("INSERT INTO schema_meta (clave, valor) VALUES ('rrhh_descuento_prestamo_v1', '1')")
    if not cursor.execute("SELECT 1 FROM schema_meta WHERE clave='rrhh_remuneracion_mes_v1'").fetchone():
        _migrar_remuneracion_mes_inicial(conn)
        cursor.execute("INSERT INTO schema_meta (clave, valor) VALUES ('rrhh_remuneracion_mes_v1', '1')")
    _migrar_tipo_gasto_operacional(conn)
    _migrar_mail_tesoreria_usuarios(cursor, CORREOS_TESORERIA_DEFAULT)
    normalizar_cuarteles_db(conn)
    migrar_flujo_financiero(conn)
    conn.commit()
    conn.close()

def migrar_globalgap(cursor):
    cursor.execute("""CREATE TABLE IF NOT EXISTS gap_pppl (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        producto TEXT UNIQUE,
        ingrediente_activo TEXT,
        dias_carencia INTEGER DEFAULT 0,
        mercado TEXT DEFAULT 'General',
        vigente INTEGER DEFAULT 1,
        notas TEXT
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS gap_documentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo TEXT,
        titulo TEXT,
        version TEXT,
        fecha_vigencia DATE,
        responsable TEXT,
        notas TEXT,
        fecha_registro DATE
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS gap_checklist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        capitulo TEXT,
        codigo TEXT UNIQUE,
        descripcion TEXT,
        orden INTEGER DEFAULT 0
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS gap_evaluacion (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        checklist_id INTEGER,
        estado TEXT DEFAULT 'Pendiente',
        evidencia TEXT,
        responsable TEXT,
        fecha_revision DATE,
        usuario TEXT,
        FOREIGN KEY(checklist_id) REFERENCES gap_checklist(id)
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS gap_nc (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo TEXT,
        capitulo TEXT,
        descripcion TEXT,
        causa TEXT,
        accion_correctiva TEXT,
        plazo DATE,
        estado TEXT DEFAULT 'Abierta',
        cuartel TEXT,
        fecha_apertura DATE,
        fecha_cierre DATE
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS gap_capacitaciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trabajador_id INTEGER,
        tema TEXT,
        horas REAL,
        instructor TEXT,
        fecha DATE,
        vigencia_hasta DATE,
        evidencia TEXT,
        FOREIGN KEY(trabajador_id) REFERENCES personal(id)
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS gap_cosecha (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        n_lote TEXT,
        cuartel TEXT,
        especie TEXT,
        variedad TEXT,
        fecha_cosecha DATE,
        kg REAL,
        cuadrilla TEXT,
        ultima_app_n INTEGER,
        fecha_viable_cosecha DATE,
        destino TEXT
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS gap_agua (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        punto_muestreo TEXT,
        laboratorio TEXT,
        fecha_muestra DATE,
        e_coli TEXT,
        coliformes TEXT,
        ph REAL,
        ce REAL,
        conforme INTEGER DEFAULT 1,
        accion TEXT
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS gap_calibracion (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        equipo TEXT,
        fecha DATE,
        presion REAL,
        l_ha_medido REAL,
        desviacion_pct REAL,
        tecnico TEXT,
        proxima_fecha DATE,
        notas TEXT
    )""")
    cursor.execute("PRAGMA table_info(inventario)")
    cols_inv = [c[1] for c in cursor.fetchall()]
    if "pppl_aprobado" not in cols_inv:
        try: cursor.execute("ALTER TABLE inventario ADD COLUMN pppl_aprobado INTEGER DEFAULT 0")
        except: pass
    if "dias_carencia" not in cols_inv:
        try: cursor.execute("ALTER TABLE inventario ADD COLUMN dias_carencia INTEGER DEFAULT 0")
        except: pass
    if "unidad_medida" not in cols_inv:
        try: cursor.execute("ALTER TABLE inventario ADD COLUMN unidad_medida TEXT DEFAULT 'kg'")
        except: pass
    cursor.execute("PRAGMA table_info(movimientos)")
    cols_mov = [c[1] for c in cursor.fetchall()]
    if "unidad_medida" not in cols_mov:
        try: cursor.execute("ALTER TABLE movimientos ADD COLUMN unidad_medida TEXT")
        except: pass
    cursor.execute("PRAGMA table_info(libro_campo)")
    cols_lc = [c[1] for c in cursor.fetchall()]
    if "lote_producto" not in cols_lc:
        try: cursor.execute("ALTER TABLE libro_campo ADD COLUMN lote_producto TEXT DEFAULT ''")
        except: pass
    if "operador_certificado" not in cols_lc:
        try: cursor.execute("ALTER TABLE libro_campo ADD COLUMN operador_certificado INTEGER DEFAULT 0")
        except: pass
    cursor.execute("PRAGMA table_info(facturas)")
    cols_fac = [c[1] for c in cursor.fetchall()]
    if "razon_social" not in cols_fac:
        try: cursor.execute("ALTER TABLE facturas ADD COLUMN razon_social TEXT DEFAULT 'La Concepción'")
        except: pass
    if "tipo_gasto" not in cols_fac:
        try:
            cursor.execute(f"ALTER TABLE facturas ADD COLUMN tipo_gasto TEXT DEFAULT '{TIPO_GASTO_SIN_CLASIFICAR}'")
        except Exception:
            pass
    if "contratista_id" not in cols_fac:
        try:
            cursor.execute("ALTER TABLE facturas ADD COLUMN contratista_id INTEGER")
        except Exception:
            pass
    cursor.execute(
        f"""UPDATE facturas SET tipo_gasto=? WHERE tipo_gasto IS NULL OR TRIM(tipo_gasto)=''""",
        (TIPO_GASTO_SIN_CLASIFICAR,),
    )
    cursor.execute("""CREATE TABLE IF NOT EXISTS contratistas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rut TEXT,
        razon_social TEXT NOT NULL,
        rubro TEXT,
        contacto TEXT,
        cc_habitual TEXT,
        estado TEXT DEFAULT 'Activo',
        notas TEXT,
        email TEXT DEFAULT '',
        mail_pago INTEGER DEFAULT 0,
        celular TEXT DEFAULT '',
        whatsapp_pago INTEGER DEFAULT 0
    )""")
    _sembrar_prorrateo_cc(cursor.connection)
    if cursor.execute("SELECT COUNT(*) FROM gap_checklist").fetchone()[0] == 0:
        items = [
            ("AFB", "AFB-01", "Mapa actualizado del campo con cuarteles, bodegas, baños y puntos de agua", 1),
            ("AFB", "AFB-02", "Historial de uso de suelo y cultivos (mínimo 3 años)", 2),
            ("AFB", "AFB-03", "Registros de capacitación y bienestar de trabajadores", 3),
            ("AFB", "AFB-04", "Instalaciones sanitarias y agua potable para personal", 4),
            ("AFB", "AFB-05", "Procedimiento de trazabilidad lote-cuartel-fecha", 5),
            ("CB", "CB-01", "Lista PPPL / productos fitosanitarios autorizados SAG", 10),
            ("CB", "CB-02", "Registro completo de aplicaciones fitosanitarias", 11),
            ("CB", "CB-03", "Calibración de equipos de aplicación por temporada", 12),
            ("CB", "CB-04", "Almacenamiento seguro de fitosanitarios y triple lavado", 13),
            ("CB", "CB-05", "Plan y registro de fertilizaciones por cuartel", 14),
            ("FV", "FV-01", "Respeto de PHI / plazos de carencia antes de cosecha", 20),
            ("FV", "FV-02", "Registro de cosecha por lote trazable", 21),
            ("FV", "FV-03", "Higiene en cosecha y manipulación de fruta", 22),
            ("AGUA", "AGUA-01", "Análisis de calidad de agua de riego vigente", 30),
            ("AUDITORIA", "AUD-01", "Autoevaluación GlobalGAP completa y firmada", 40),
            ("AUDITORIA", "AUD-02", "Registro de no conformidades y acciones correctivas", 41),
        ]
        cursor.executemany(
            "INSERT INTO gap_checklist (capitulo, codigo, descripcion, orden) VALUES (?,?,?,?)",
            items,
        )
    migrar_especie_globalgap(cursor)

def migrar_especie_globalgap(cursor):
    for tabla in (
        "gap_pppl", "gap_documentos", "gap_evaluacion", "gap_nc",
        "gantt_proyectos",
    ):
        cursor.execute(f"PRAGMA table_info({tabla})")
        cols = [c[1] for c in cursor.fetchall()]
        if "especie" not in cols:
            try:
                cursor.execute(f"ALTER TABLE {tabla} ADD COLUMN especie TEXT DEFAULT 'Cerezos'")
            except Exception:
                pass
    cursor.execute(
        "UPDATE gap_pppl SET especie=? WHERE especie IS NULL OR especie=''",
        (GAP_ESPECIE_GENERAL,),
    )
    cursor.execute(
        "UPDATE gantt_proyectos SET especie=? WHERE nombre LIKE '%Certificación%' OR nombre LIKE '%Maquinaria%'",
        (GAP_ESPECIE_GENERAL,),
    )
    cursor.execute(
        "UPDATE gantt_proyectos SET especie='Cerezos' WHERE nombre LIKE '%Cerezas%'"
    )

def inicio_gestion_gantt(ref=None):
    """Próximo lunes de arranque: si hoy es domingo, mañana lunes."""
    ref = ref or hoy
    if ref.weekday() == 6:
        return ref + timedelta(days=1)
    dias = (7 - ref.weekday()) % 7
    if dias == 0:
        dias = 7
    return ref + timedelta(days=dias)

def fecha_cosecha_planificada(anio=None):
    anio = anio or inicio_gestion_gantt().year
    fc = datetime(anio, 11, 8).date()
    if fc < inicio_gestion_gantt():
        fc = datetime(anio + 1, 11, 8).date()
    return fc

def fecha_cosecha_ciruelos_planificada():
    return datetime(2027, 1, 20).date()

def plantilla_calendario_gantt():
    inicio = inicio_gestion_gantt()
    cosecha = fecha_cosecha_planificada(inicio.year)
    cierre = cosecha + timedelta(days=30)
    cosecha_cir = fecha_cosecha_ciruelos_planificada()
    cierre_cir = cosecha_cir + timedelta(days=25)
    return {
        "Temporada Cerezas 2026": {
            "desc": "Plan operativo cosecha y labores pre/post",
            "fi": str(inicio),
            "ff": str(cierre),
            "cc": "CEREZOS CORTE 1",
            "resp": "Jefe de Campo",
            "esp": "Cerezos",
            "tareas": [
                ("Calibración nebulizadores", inicio, inicio + timedelta(days=12), 0, "Taller", "Media"),
                ("Monitoreo sanitario y labores culturales", inicio, inicio + timedelta(days=60), 0, "Cuadrilla A", "Alta"),
                ("Aplicación fungicida pre-cosecha", cosecha - timedelta(days=45), cosecha - timedelta(days=15), 0, "Aplicador certificado", "Alta"),
                ("Preparación logística cosecha", cosecha - timedelta(days=14), cosecha - timedelta(days=1), 0, "Supervisor cosecha", "Alta"),
                ("Cosecha Corte 1", cosecha, cosecha + timedelta(days=14), 0, "Supervisor cosecha", "Alta"),
                ("Cierre libro de campo temporada", cosecha + timedelta(days=15), cierre, 0, "Secretaría", "Media"),
            ],
        },
        "Temporada Ciruelos 2026": {
            "desc": "Plan operativo cosecha y labores ciruelos",
            "fi": str(inicio),
            "ff": str(cierre_cir),
            "cc": "CIRUELOS",
            "resp": "Jefe de Campo",
            "esp": "Ciruelos",
            "tareas": [
                ("Calibración equipos ciruelos", inicio, inicio + timedelta(days=12), 0, "Taller", "Media"),
                ("Monitoreo sanitario y labores culturales ciruelos", inicio, inicio + timedelta(days=90), 0, "Cuadrilla B", "Alta"),
                ("Aplicación sanitaria pre-cosecha", cosecha_cir - timedelta(days=45), cosecha_cir - timedelta(days=15), 0, "Aplicador certificado", "Alta"),
                ("Preparación logística cosecha ciruelos", cosecha_cir - timedelta(days=14), cosecha_cir - timedelta(days=1), 0, "Supervisor cosecha", "Alta"),
                ("Cosecha ciruelos", cosecha_cir, cosecha_cir + timedelta(days=18), 0, "Supervisor cosecha", "Alta"),
                ("Cierre trazabilidad lote", cosecha_cir + timedelta(days=12), cierre_cir, 0, "Certificación", "Media"),
            ],
        },
        "Certificación GlobalGAP": {
            "desc": "Hitos de cumplimiento y auditoría",
            "fi": str(inicio),
            "ff": str(cosecha + timedelta(days=21)),
            "cc": "OTROS",
            "resp": "Certificación",
            "esp": GAP_ESPECIE_GENERAL,
            "tareas": [
                ("Actualización PPPL y documentos", inicio, inicio + timedelta(days=30), 0, "Certificación", "Media"),
                ("Autoevaluación checklist IFA", inicio + timedelta(days=7), inicio + timedelta(days=90), 0, "Certificación", "Alta"),
                ("Simulacro auditoría interna", cosecha - timedelta(days=60), cosecha - timedelta(days=30), 0, "Certificación", "Alta"),
            ],
        },
        "Mantención Maquinaria": {
            "desc": "Calibraciones y mantenciones preventivas",
            "fi": str(inicio),
            "ff": str(cosecha),
            "cc": "OTROS",
            "resp": "Taller",
            "esp": GAP_ESPECIE_GENERAL,
            "tareas": [
                ("Mantención preventiva tractores", inicio, inicio + timedelta(days=40), 0, "Mecánico", "Media"),
                ("Calibración equipos pulverización", cosecha - timedelta(days=75), cosecha - timedelta(days=55), 0, "Taller", "Alta"),
            ],
        },
    }

def sincronizar_calendario_gantt(cursor):
    """Alinea proyectos demo al calendario real: inicio próximo lunes, cosecha 8-nov."""
    ver_objetivo = 4
    row = cursor.execute("SELECT valor FROM gantt_config WHERE clave='calendario_v'").fetchone()
    if row and int(row[0]) >= ver_objetivo:
        return
    plantilla = plantilla_calendario_gantt()
    for nombre, data in plantilla.items():
        row_p = cursor.execute("SELECT id FROM gantt_proyectos WHERE nombre=?", (nombre,)).fetchone()
        if row_p:
            pid = row_p[0]
            cursor.execute(
                "UPDATE gantt_proyectos SET descripcion=?, fecha_inicio=?, fecha_fin=?, centro_costo=?, responsable=?, especie=? WHERE id=?",
                (data["desc"], data["fi"], data["ff"], data["cc"], data["resp"], data["esp"], pid),
            )
            cursor.execute("DELETE FROM gantt_tareas WHERE proyecto_id=?", (pid,))
        else:
            cursor.execute(
                "INSERT INTO gantt_proyectos (nombre, descripcion, fecha_inicio, fecha_fin, centro_costo, responsable, especie) VALUES (?,?,?,?,?,?,?)",
                (nombre, data["desc"], data["fi"], data["ff"], data["cc"], data["resp"], data["esp"]),
            )
            pid = cursor.lastrowid
        for act, fi, ff, av, resp, pri in data["tareas"]:
            cursor.execute(
                "INSERT INTO gantt_tareas (proyecto_id, actividad, fecha_inicio, fecha_fin, avance_pct, responsable, prioridad, estado) VALUES (?,?,?,?,?,?,?,?)",
                (pid, act, str(fi), str(ff), float(av), resp, pri, "En curso"),
            )
    cursor.execute("INSERT OR REPLACE INTO gantt_config (clave, valor) VALUES ('calendario_v', ?)", (ver_objetivo,))

def cuarteles_gap_especie(especie):
    return GAP_ESPECIE_CUARTELES.get(especie, []) + ["OTROS"]

def seleccionar_especie_gap():
    st.markdown(
        """
        <div class="gap-especie-marker"></div>
        <div class="gap-especie-panel">
            <div class="gap-especie-titulo">🌱 ESPECIE / CULTIVO</div>
            <div class="gap-especie-sub">Seleccione con qué cultivo trabajará en todo GlobalGAP</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    labels = {"Cerezos": "🍒 CEREZOS", "Ciruelos": "🟣 CIRUELOS"}
    return st.radio(
        "Cultivo activo",
        GAP_ESPECIES,
        horizontal=True,
        key="gap_especie",
        label_visibility="collapsed",
        format_func=lambda x: labels.get(x, x.upper()),
    )

def migrar_gantt(cursor):
    cursor.execute("""CREATE TABLE IF NOT EXISTS gantt_proyectos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT UNIQUE,
        descripcion TEXT,
        fecha_inicio DATE,
        fecha_fin DATE,
        centro_costo TEXT,
        responsable TEXT,
        estado TEXT DEFAULT 'Activo'
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS gantt_tareas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        proyecto_id INTEGER,
        actividad TEXT,
        fecha_inicio DATE,
        fecha_fin DATE,
        avance_pct REAL DEFAULT 0,
        responsable TEXT,
        prioridad TEXT DEFAULT 'Media',
        estado TEXT DEFAULT 'En curso',
        notas TEXT,
        FOREIGN KEY(proyecto_id) REFERENCES gantt_proyectos(id)
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS gantt_config (
        clave TEXT PRIMARY KEY,
        valor REAL
    )""")
    for clave, valor in GANTT_UMBRALES_DEF.items():
        cursor.execute("INSERT OR IGNORE INTO gantt_config (clave, valor) VALUES (?,?)", (clave, valor))
    sincronizar_calendario_gantt(cursor)

def obtener_umbrales_gantt(conn=None):
    cerrar = False
    if conn is None:
        conn = conectar_db()
        cerrar = True
    rows = conn.execute("SELECT clave, valor FROM gantt_config").fetchall()
    umbrales = dict(GANTT_UMBRALES_DEF)
    for clave, valor in rows:
        if clave in umbrales:
            umbrales[clave] = float(valor)
    if cerrar:
        conn.close()
    return umbrales

def gantt_avance_esperado(fecha_inicio, fecha_fin, ref=None):
    ref = ref or hoy
    fi = pd.to_datetime(fecha_inicio).date()
    ff = pd.to_datetime(fecha_fin).date()
    if fi > ff:
        ff = fi
    if ref <= fi:
        return 0.0
    if ref >= ff:
        return 100.0
    total = max((ff - fi).days, 1)
    return round((ref - fi).days / total * 100, 1)

def gantt_evaluar_alerta(avance_real, avance_esperado, fecha_fin, umbrales=None, estado=None):
    umbrales = umbrales or GANTT_UMBRALES_DEF
    avance_real = float(avance_real or 0)
    if str(estado or "").strip() == "Completada":
        avance_real = max(avance_real, 100.0)
    desfase = round(avance_esperado - avance_real, 1)
    ff = pd.to_datetime(fecha_fin).date()
    if avance_real >= 100:
        return {"nivel": "Completada", "color": "#2E7D32", "desfase": 0, "idx": 0}
    if ff < hoy:
        return {"nivel": "Vencida", "color": "#B71C1C", "desfase": desfase, "idx": 100}
    if desfase >= umbrales["critico"]:
        return {"nivel": "Crítico", "color": "#B71C1C", "desfase": desfase, "idx": 90}
    if desfase >= umbrales["alto"]:
        return {"nivel": "Alto", "color": "#E65100", "desfase": desfase, "idx": 70}
    if desfase >= umbrales["medio"]:
        return {"nivel": "Medio", "color": "#F9A825", "desfase": desfase, "idx": 50}
    if desfase > 0:
        return {"nivel": "Bajo", "color": "#1565C0", "desfase": desfase, "idx": 25}
    return {"nivel": "En ritmo", "color": "#2E7D32", "desfase": desfase, "idx": 10}

def cargar_tareas_gantt(conn, proyecto_id=None, especie=None):
    q = """
        SELECT t.id, p.nombre as proyecto, t.actividad, t.fecha_inicio, t.fecha_fin,
               t.avance_pct, t.responsable, t.prioridad, t.estado, t.notas, p.centro_costo,
               COALESCE(p.especie, 'Cerezos') as especie
        FROM gantt_tareas t
        JOIN gantt_proyectos p ON p.id = t.proyecto_id
        WHERE p.estado = 'Activo'
    """
    if especie:
        q += f" AND (COALESCE(p.especie,'Cerezos') = '{especie}' OR COALESCE(p.especie,'Cerezos') = '{GAP_ESPECIE_GENERAL}')"
    if proyecto_id:
        q += f" AND t.proyecto_id = {int(proyecto_id)}"
    q += " ORDER BY t.fecha_inicio, t.id"
    df = pd.read_sql_query(q, conn)
    if df.empty:
        return df
    umbrales = obtener_umbrales_gantt(conn)
    esperados, niveles, desfases, colores, indices = [], [], [], [], []
    for _, row in df.iterrows():
        esp = gantt_avance_esperado(row["fecha_inicio"], row["fecha_fin"])
        al = gantt_evaluar_alerta(row["avance_pct"], esp, row["fecha_fin"], umbrales, estado=row.get("estado"))
        esperados.append(esp)
        niveles.append(al["nivel"])
        desfases.append(al["desfase"])
        colores.append(al["color"])
        indices.append(al["idx"])
    df["avance_esperado"] = esperados
    df["nivel_alerta"] = niveles
    df["desfase_pct"] = desfases
    df["color_alerta"] = colores
    df["indice_alerta"] = indices
    return df

def render_gantt_html(df, ref=None):
    ref = ref or hoy
    if df.empty:
        return '<div class="gantt-empty">Sin actividades para mostrar en el cronograma.</div>'
    fi_min = pd.to_datetime(df["fecha_inicio"]).min().date()
    ff_max = pd.to_datetime(df["fecha_fin"]).max().date()
    total_dias = max((ff_max - fi_min).days, 1)
    hoy_pct = min(100, max(0, (ref - fi_min).days / total_dias * 100)) if fi_min <= ref <= ff_max else (100 if ref > ff_max else 0)
    meses = []
    cursor = fi_min.replace(day=1)
    while cursor <= ff_max:
        meses.append(cursor)
        if cursor.month == 12:
            cursor = cursor.replace(year=cursor.year + 1, month=1)
        else:
            cursor = cursor.replace(month=cursor.month + 1)
    escala = ""
    for m in meses:
        pos = (m - fi_min).days / total_dias * 100
        if 0 <= pos <= 100:
            escala += f'<span class="gantt-mes" style="left:{pos:.1f}%">{m.strftime("%b %y")}</span>'
    filas = ""
    for _, row in df.iterrows():
        ini = pd.to_datetime(row["fecha_inicio"]).date()
        fin = pd.to_datetime(row["fecha_fin"]).date()
        left = (ini - fi_min).days / total_dias * 100
        width = max((fin - ini).days / total_dias * 100, 1.5)
        av = min(100, max(0, float(row["avance_pct"] or 0)))
        nombre = html_lib.escape(str(row["actividad"]))
        proy = html_lib.escape(str(row["proyecto"]))
        color = row.get("color_alerta", "#1565C0")
        nivel = html_lib.escape(str(row.get("nivel_alerta", "")))
        filas += f"""
        <div class="gantt-row">
            <div class="gantt-task-meta">
                <div class="gantt-task-name">{nombre}</div>
                <div class="gantt-task-sub">{proy} · {nivel}</div>
            </div>
            <div class="gantt-track">
                <div class="gantt-bar" style="left:{left:.1f}%;width:{width:.1f}%;border-color:{color};" title="{nivel}">
                    <div class="gantt-fill" style="width:{av:.1f}%;background:{color};"></div>
                    <span class="gantt-pct">{av:.0f}%</span>
                </div>
            </div>
        </div>"""
    return f"""<div class="gantt-wrap">
        <div class="gantt-scale">{escala}<div class="gantt-today" style="left:{hoy_pct:.1f}%"></div></div>
        <div class="gantt-head"><span>Actividad</span><span>Cronograma</span></div>
        {filas}
    </div>"""

GANTT_CSS_IFRAME = """
body { margin:0; padding:8px 4px; font-family:'DM Sans','Segoe UI',sans-serif; color:#1F2933; }
.gantt-wrap { background:#fff; border:1px solid #DDE5DF; border-radius:14px; padding:1rem 1rem 0.5rem; }
.gantt-head, .gantt-row { display:grid; grid-template-columns:240px 1fr; gap:0.75rem; align-items:center; }
.gantt-head { font-size:0.75rem; font-weight:800; color:#5F6B7A; text-transform:uppercase; letter-spacing:0.04em; margin-bottom:0.5rem; }
.gantt-scale { position:relative; height:28px; margin-left:240px; border-bottom:1px solid #DDE5DF; margin-bottom:0.75rem; }
.gantt-mes { position:absolute; top:0; font-size:0.68rem; color:#5F6B7A; font-weight:700; transform:translateX(-50%); }
.gantt-today { position:absolute; top:0; bottom:-8px; width:2px; background:#C62828; z-index:3; }
.gantt-today::after { content:'Hoy'; position:absolute; top:-16px; left:-10px; font-size:0.62rem; color:#C62828; font-weight:800; }
.gantt-row { padding:0.45rem 0; border-top:1px solid #EEF2EE; }
.gantt-task-name { font-weight:700; font-size:0.86rem; }
.gantt-task-sub { font-size:0.72rem; color:#5F6B7A; margin-top:0.15rem; }
.gantt-track { position:relative; height:34px; background:#F3F6F4; border-radius:8px; }
.gantt-bar { position:absolute; top:5px; height:24px; border-radius:6px; border:2px solid #90A4AE; background:#fff; overflow:hidden; min-width:36px; }
.gantt-fill { height:100%; opacity:0.85; }
.gantt-pct { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; font-size:0.68rem; font-weight:800; color:#1F2933; text-shadow:0 0 4px #fff; }
.gantt-empty { text-align:center; color:#5F6B7A; padding:2rem; border:1px dashed #DDE5DF; border-radius:14px; }
"""

def mostrar_gantt(df):
    html_body = render_gantt_html(df)
    alto = max(200, 90 + (0 if df is None or df.empty else len(df)) * 54)
    doc = (
        f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<style>{GANTT_CSS_IFRAME}</style></head><body>{html_body}</body></html>"
    )
    components.html(doc, height=alto, scrolling=False)

def producto_pppl_aprobado(conn, nombre_producto):
    if not nombre_producto or not str(nombre_producto).strip():
        return False
    nom = str(nombre_producto).strip().upper()
    row = conn.execute(
        "SELECT 1 FROM gap_pppl WHERE UPPER(producto)=? AND vigente=1",
        (nom,),
    ).fetchone()
    if row:
        return True
    row = conn.execute(
        "SELECT pppl_aprobado FROM inventario WHERE UPPER(producto)=?",
        (nom,),
    ).fetchone()
    return bool(row and row[0])

def dias_carencia_producto(conn, nombre_producto, fallback=0):
    nom = str(nombre_producto).strip().upper()
    row = conn.execute(
        "SELECT dias_carencia FROM gap_pppl WHERE UPPER(producto)=? AND vigente=1",
        (nom,),
    ).fetchone()
    if row and row[0]:
        return int(row[0])
    row = conn.execute(
        "SELECT dias_carencia FROM inventario WHERE UPPER(producto)=?",
        (nom,),
    ).fetchone()
    if row and row[0]:
        return int(row[0])
    return int(fallback or 0)

def _estado_auditoria_pppl_item(conn, inv_id, producto, familia, pppl_bodega, phi_bodega):
    ref = buscar_referencia_sag(producto, familia)
    if ref is None:
        return "NO_REQUIERE", None, None, None, None
    nom_u = str(producto or "").strip().upper()
    gap = conn.execute(
        "SELECT ingrediente_activo, dias_carencia, vigente FROM gap_pppl WHERE UPPER(producto)=?",
        (nom_u,),
    ).fetchone()
    en_gap = bool(gap and gap[2])
    phi_gap = int(gap[1] or 0) if gap else 0
    phi_ref = int(ref.dias_carencia)
    if en_gap and pppl_bodega and phi_bodega == phi_gap and phi_gap > 0:
        return "AUTORIZADO", ref, gap[0], phi_gap, ref.confianza
    if en_gap and (not pppl_bodega or phi_bodega != phi_gap):
        return "DESINCronizado", ref, gap[0] if gap else ref.ingrediente_activo, phi_gap or phi_ref, ref.confianza
    if ref.confianza == "baja":
        return "SIN_REFERENCIA", ref, ref.ingrediente_activo, phi_ref, ref.confianza
    return "PENDIENTE", ref, ref.ingrediente_activo, phi_ref, ref.confianza

def _auditar_bodega_pppl(conn):
    filas = []
    for inv_id, producto, familia, pppl_bodega, phi_bodega in conn.execute(
        """SELECT id, producto, familia, COALESCE(pppl_aprobado,0), COALESCE(dias_carencia,0)
           FROM inventario ORDER BY familia, producto"""
    ):
        estado, ref, ing, phi_sug, conf = _estado_auditoria_pppl_item(
            conn, inv_id, producto, familia, bool(pppl_bodega), int(phi_bodega or 0),
        )
        filas.append({
            "id": inv_id,
            "PRODUCTO": producto,
            "FAMILIA": familia,
            "ESTADO_COD": estado,
            "ESTADO": etiqueta_estado_auditoria(estado),
            "PPPL_BODEGA": "Sí" if pppl_bodega else "No",
            "PHI_BODEGA": int(phi_bodega or 0),
            "PHI_SUGERIDO": phi_sug if ref else "—",
            "INGREDIENTE_SAG": ing or resolver_ingrediente_activo(conn, producto, familia) or "—",
            "CONFIANZA": conf or "—",
            "NOTAS_SAG": (ref.notas if ref else "") or "",
        })
    return pd.DataFrame(filas)

def _upsert_pppl_desde_bodega(conn, inv_id, especie=GAP_ESPECIE_GENERAL):
    row = conn.execute(
        "SELECT id, producto, familia FROM inventario WHERE id=?",
        (int(inv_id),),
    ).fetchone()
    if not row:
        return False, "Producto no encontrado"
    ref = buscar_referencia_sag(row[1], row[2])
    if ref is None:
        return False, "No requiere PPPL"
    nom = str(row[1]).strip()
    phi = int(ref.dias_carencia)
    ing = str(ref.ingrediente_activo or "").strip()
    notas = ref.notas or "Autorizado desde auditoría bodega / referencia SAG"
    gap = conn.execute("SELECT id FROM gap_pppl WHERE UPPER(producto)=?", (nom.upper(),)).fetchone()
    if gap:
        conn.execute(
            """UPDATE gap_pppl SET ingrediente_activo=?, dias_carencia=?, mercado=?, vigente=1,
               notas=?, especie=? WHERE id=?""",
            (ing, phi, ref.mercado, notas, especie, gap[0]),
        )
    else:
        conn.execute(
            """INSERT INTO gap_pppl (producto, ingrediente_activo, dias_carencia, mercado, vigente, notas, especie)
               VALUES (?,?,?,?,1,?,?)""",
            (nom, ing, phi, ref.mercado, notas, especie),
        )
    conn.execute(
        "UPDATE inventario SET pppl_aprobado=1, dias_carencia=?, ingrediente_activo=? WHERE id=?",
        (phi, ing, int(inv_id)),
    )
    conn.commit()
    registrar_accion("PPPL SYNC BODEGA", nom)
    return True, nom

def _sincronizar_pppl_bodega(conn, df_audit, incluir_baja=False, especie=GAP_ESPECIE_GENERAL):
    ok, omitidos, errores = [], [], []
    candidatos = df_audit[df_audit["ESTADO_COD"].isin(["PENDIENTE", "DESINCronizado", "SIN_REFERENCIA"])]
    for _, r in candidatos.iterrows():
        if r["ESTADO_COD"] == "SIN_REFERENCIA" and not incluir_baja:
            omitidos.append(r["PRODUCTO"])
            continue
        if r["CONFIANZA"] == "baja" and not incluir_baja and r["ESTADO_COD"] != "DESINCronizado":
            omitidos.append(r["PRODUCTO"])
            continue
        try:
            success, msg = _upsert_pppl_desde_bodega(conn, r["id"], especie=especie)
            if success:
                ok.append(msg)
            else:
                errores.append(f"{r['PRODUCTO']}: {msg}")
        except Exception as exc:
            errores.append(f"{r['PRODUCTO']}: {exc}")
    return ok, omitidos, errores

def _render_auditoria_pppl_bodega(conn, key_prefix="bod_pppl", especie=GAP_ESPECIE_GENERAL):
    st.markdown("#### Auditoría PPPL / SAG — productos de bodega")
    st.caption(
        "Cruza inventario con referencia **SAG / GlobalGAP** (catálogo interno + PHI por familia). "
        "Genera la lista **PPPL** oficial y marca autorización en bodega con días de carencia (PHI)."
    )
    df_aud = _auditar_bodega_pppl(conn)
    if df_aud.empty:
        st.info("No hay productos en bodega.")
        return
    fito = df_aud[df_aud["ESTADO_COD"] != "NO_REQUIERE"]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Fitosanitarios", len(fito))
    c2.metric("Autorizados", len(fito[fito["ESTADO_COD"] == "AUTORIZADO"]))
    c3.metric("Pendientes", len(fito[fito["ESTADO_COD"] == "PENDIENTE"]))
    c4.metric("Desincronizados", len(fito[fito["ESTADO_COD"] == "DESINCronizado"]))
    c5.metric("Revisar SAG", len(fito[fito["ESTADO_COD"] == "SIN_REFERENCIA"]))
    show = df_aud.drop(columns=["id"]).set_index("PRODUCTO")
    estado_por_prod = df_aud.set_index("PRODUCTO")["ESTADO_COD"]

    def _estilo_auditoria_visible(row):
        est = estado_por_prod.get(row.name, "")
        estilos = {
            "AUTORIZADO": "background-color:#E8F5E9;color:#2E7D32;font-weight:600",
            "PENDIENTE": "background-color:#FFF8E1;color:#F57F17;font-weight:600",
            "DESINCronizado": "background-color:#FFF3E0;color:#E65100;font-weight:600",
            "SIN_REFERENCIA": "background-color:#FFEBEE;color:#C62828;font-weight:600",
            "NO_REQUIERE": "background-color:#F5F5F5;color:#616161",
        }
        css = estilos.get(est, "")
        return [css] * len(row) if css else [""] * len(row)

    st.dataframe(
        show.drop(columns=["ESTADO_COD"]).style.apply(_estilo_auditoria_visible, axis=1),
        use_container_width=True,
    )
    if puede_gestionar_pppl():
        st.markdown("##### Generar / sincronizar PPPL")
        b1, b2 = st.columns(2)
        if b1.button("✅ Autorizar pendientes (ref. SAG alta/media)", key=f"{key_prefix}_sync_ok", use_container_width=True):
            ok, omit, err = _sincronizar_pppl_bodega(conn, df_aud, incluir_baja=False, especie=especie)
            if ok:
                st.success(f"PPPL actualizado para **{len(ok)}** producto(s): {', '.join(ok[:8])}{'…' if len(ok) > 8 else ''}")
            if omit:
                st.info(f"Omitidos ({len(omit)}): referencia baja o sin match SAG — revisar manualmente.")
            if err:
                st.error("\n".join(err[:5]))
            if ok:
                st.rerun()
        if b2.button("⚠️ Incluir también referencia baja (PHI familia)", key=f"{key_prefix}_sync_all", use_container_width=True):
            ok, omit, err = _sincronizar_pppl_bodega(conn, df_aud, incluir_baja=True, especie=especie)
            if ok:
                st.success(f"PPPL generado para **{len(ok)}** producto(s). Revise PHI en etiqueta SAG.")
                st.rerun()
            elif err:
                st.error("\n".join(err[:5]))
            else:
                st.info("No hay productos pendientes para sincronizar.")
        with st.expander("Edición manual de un producto"):
            df_edit = df_aud[df_aud["ESTADO_COD"] != "NO_REQUIERE"]
            if df_edit.empty:
                st.caption("No hay fitosanitarios en bodega.")
            else:
                with st.form(f"{key_prefix}_manual"):
                    sel_id = st.selectbox(
                        "Producto",
                        df_edit["id"].tolist(),
                        format_func=lambda i: df_edit.loc[df_edit["id"] == i, "PRODUCTO"].iloc[0],
                        key=f"{key_prefix}_sel",
                    )
                    fila = df_edit[df_edit["id"] == sel_id].iloc[0]
                    ref = buscar_referencia_sag(fila["PRODUCTO"], fila["FAMILIA"])
                    pppl_ok = st.checkbox("Aprobado PPPL en bodega", value=fila["PPPL_BODEGA"] == "Sí")
                    phi_def = int(fila["PHI_SUGERIDO"]) if str(fila["PHI_SUGERIDO"]).isdigit() else (ref.dias_carencia if ref else 0)
                    dias_phi = st.number_input("Días carencia (PHI)", 0, 365, phi_def)
                    ing_man = st.text_input("Ingrediente activo", value=fila["INGREDIENTE_SAG"] if fila["INGREDIENTE_SAG"] != "—" else (ref.ingrediente_activo if ref else ""))
                    notas_man = st.text_input("Notas / resolución SAG", value=fila.get("NOTAS_SAG", ""))
                    sync_gap = st.checkbox("Registrar también en PPPL GlobalGAP", value=True)
                    if st.form_submit_button("GUARDAR"):
                        conn.execute(
                            "UPDATE inventario SET pppl_aprobado=?, dias_carencia=?, ingrediente_activo=? WHERE id=?",
                            (1 if pppl_ok else 0, int(dias_phi), ing_man.strip(), int(sel_id)),
                        )
                        if sync_gap and pppl_ok:
                            nom = str(fila["PRODUCTO"]).strip()
                            gap = conn.execute("SELECT id FROM gap_pppl WHERE UPPER(producto)=?", (nom.upper(),)).fetchone()
                            if gap:
                                conn.execute(
                                    """UPDATE gap_pppl SET ingrediente_activo=?, dias_carencia=?, vigente=1, notas=?, especie=?
                                       WHERE id=?""",
                                    (ing_man.strip(), int(dias_phi), notas_man.strip(), especie, gap[0]),
                                )
                            else:
                                conn.execute(
                                    """INSERT INTO gap_pppl (producto, ingrediente_activo, dias_carencia, mercado, vigente, notas, especie)
                                       VALUES (?,?,?,?,1,?,?)""",
                                    (nom, ing_man.strip(), int(dias_phi), "General", notas_man.strip(), especie),
                                )
                        conn.commit()
                        registrar_accion("BODEGA PPPL MANUAL", fila["PRODUCTO"])
                        st.success("Producto actualizado.")
                        st.rerun()

def resumen_globalgap(conn, especie="Cerezos"):
    total_chk = conn.execute("SELECT COUNT(*) FROM gap_checklist").fetchone()[0]
    cumple = conn.execute(
        "SELECT COUNT(*) FROM gap_evaluacion WHERE estado='Cumple' AND COALESCE(especie,'Cerezos')=?",
        (especie,),
    ).fetchone()[0]
    cuarteles = cuarteles_gap_especie(especie)
    placeholders = ",".join("?" * len(cuarteles))
    nc_abiertas = conn.execute(
        f"SELECT COUNT(*) FROM gap_nc WHERE estado='Abierta' AND (COALESCE(especie,'Cerezos')=? OR cuartel IN ({placeholders}))",
        (especie, *cuarteles),
    ).fetchone()[0]
    pppl = conn.execute(
        "SELECT COUNT(*) FROM gap_pppl WHERE vigente=1 AND COALESCE(especie,'General') IN (?, ?)",
        (GAP_ESPECIE_GENERAL, especie),
    ).fetchone()[0]
    cap_venc = conn.execute(
        f"SELECT COUNT(*) FROM gap_capacitaciones WHERE vigencia_hasta < '{hoy}'"
    ).fetchone()[0]
    agua_venc = conn.execute(
        f"SELECT COUNT(*) FROM gap_agua WHERE fecha_muestra < '{hoy - timedelta(days=365)}'"
    ).fetchone()[0]
    pct = int(round((cumple / total_chk) * 100)) if total_chk else 0
    return {
        "pct": pct,
        "cumple": cumple,
        "total_chk": total_chk,
        "nc_abiertas": nc_abiertas,
        "pppl": pppl,
        "cap_venc": cap_venc,
        "agua_venc": agua_venc,
    }

# =============================================================================
# 3. UTILIDADES PDF E INDICADORES + INYECTOR CSS SEGREGADO QUIRÚRGICO v11.5.4
# =============================================================================

def _fecha_cache_diario():
    return str(hora_chile().date())

def _ruta_cache_diario(clave):
    base = os.path.dirname(os.path.abspath(NOMBRE_DB)) or "."
    return os.path.join(base, f".erp_cache_{clave}.json")

def _leer_cache_diario(clave):
    try:
        path = _ruta_cache_diario(clave)
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as fh:
            blob = json.load(fh)
        if blob.get("fecha") != _fecha_cache_diario():
            return None
        return blob.get("data")
    except Exception:
        return None

def _escribir_cache_diario(clave, data):
    try:
        path = _ruta_cache_diario(clave)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "fecha": _fecha_cache_diario(),
                    "actualizado": hora_chile().strftime("%Y-%m-%d %H:%M:%S"),
                    "data": data,
                },
                fh,
                ensure_ascii=False,
            )
    except Exception:
        pass

def _cache_diario_get(clave, fetcher):
    """Primera consulta del día: red. Resto del día: memoria o disco."""
    fecha = _fecha_cache_diario()
    sess_key = f"_cache_diario_{clave}_{fecha}"
    if sess_key in st.session_state:
        return st.session_state[sess_key]
    disk = _leer_cache_diario(clave)
    if disk is not None:
        st.session_state[sess_key] = disk
        return disk
    data = fetcher()
    if data is not None:
        _escribir_cache_diario(clave, data)
        st.session_state[sess_key] = data
    return data

def _indicadores_desde_mindicador():
    r = requests.get("https://mindicador.cl/api", timeout=8)
    r.raise_for_status()
    data = r.json()
    return {
        "uf": float(data["uf"]["valor"]),
        "utm": float(data["utm"]["valor"]),
        "dolar": float(data["dolar"]["valor"]),
        "euro": float(data["euro"]["valor"]),
        "fecha": str(data.get("fecha", ""))[:10],
        "fuente": "mindicador.cl",
    }

def _indicadores_desde_findic():
    r = requests.get("https://findic.cl/api/", timeout=8)
    r.raise_for_status()
    data = r.json()
    return {
        "uf": float(data["uf"]["valor"]),
        "utm": float(data["utm"]["valor"]),
        "dolar": float(data["dolar"]["valor"]),
        "euro": float(data["euro"]["valor"]),
        "fecha": str(data.get("fecha", ""))[:10],
        "fuente": "findic.cl",
    }

def _fetch_indicadores_vivo():
    for fetcher, nombre in (
        (_indicadores_desde_mindicador, "mindicador.cl"),
        (_indicadores_desde_findic, "findic.cl"),
    ):
        try:
            raw = fetcher()
            return {
                "uf": _fmt_clp(raw["uf"]),
                "utm": _fmt_clp(raw["utm"]),
                "dolar": _fmt_clp(raw["dolar"]),
                "euro": _fmt_clp(raw["euro"]),
                "fecha": raw.get("fecha", ""),
                "fuente": raw.get("fuente", nombre),
                "offline": False,
                "dolar_raw": float(raw["dolar"]),
            }
        except Exception:
            continue
    return {
        "uf": "—", "utm": "—", "dolar": "—", "euro": "—",
        "fecha": "", "fuente": "", "offline": True, "dolar_raw": None,
    }

def _fmt_clp(valor):
    entero, dec = f"{float(valor):,.2f}".split(".")
    return f"${entero.replace(',', '.')},{dec}"

def obtener_indicadores():
    return _cache_diario_get("indicadores", _fetch_indicadores_vivo) or {
        "uf": "—", "utm": "—", "dolar": "—", "euro": "—",
        "fecha": "", "fuente": "", "offline": True, "dolar_raw": None,
    }

def obtener_valor_dolar():
    """Valor numérico del dólar observado (CLP por 1 USD), misma fuente que el dashboard."""
    ind = obtener_indicadores()
    raw = ind.get("dolar_raw")
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    return None

def _fmt_usd(valor, dec=3):
    try:
        entero, frac = f"{float(valor):,.{dec}f}".split(".")
        return f"US${entero.replace(',', '.')},{frac}"
    except Exception:
        return "—"

def inicio_temporada_frio(fecha=None):
    fecha = fecha or hoy
    anio = fecha.year if fecha.month >= 5 else fecha.year - 1
    return datetime(anio, 5, 15).date()

def fin_temporada_frio(fecha=None):
    fecha = fecha or hoy
    anio = fecha.year if fecha.month >= 5 else fecha.year - 1
    return datetime(anio, 7, 31).date()

def fin_acumulado_clima(fecha=None):
    """Acumulado hasta hoy (incluye lecturas del día en curso)."""
    fecha = fecha or hoy
    return min(fecha, fin_temporada_frio(fecha))

def rango_temporada_frio(fecha=None):
    fecha = fecha or hoy
    inicio = inicio_temporada_frio(fecha)
    fin = fin_acumulado_clima(fecha)
    if fin < inicio:
        return inicio, inicio
    return inicio, fin

def _filtrar_df_temporada_frio(df, fecha=None):
    inicio, fin = rango_temporada_frio(fecha)
    work = df.dropna(subset=["temp"]).copy()
    if work.empty:
        return work
    work["fecha_hora"] = pd.to_datetime(work["fecha_hora"])
    work["fecha"] = work["fecha_hora"].dt.date
    return work[(work["fecha"] >= inicio) & (work["fecha"] <= fin)]

def _peso_intervalo_horas(work):
    work = work.dropna(subset=["temp"]).copy()
    if len(work) < 2:
        return 1.0
    work = work.sort_values("fecha_hora")
    work["fecha_hora"] = pd.to_datetime(work["fecha_hora"])
    diffs = work["fecha_hora"].diff().dropna().dt.total_seconds() / 3600.0
    med = float(diffs.median())
    if med <= 0.35:
        return 0.25
    if med <= 0.75:
        return 0.5
    return 1.0

def _inicio_base_may1(fecha=None):
    fecha = fecha or hoy
    anio = fecha.year if fecha.month >= 5 else fecha.year - 1
    return datetime(anio, *AGROCLIMA_BASE_MAY1).date()

def _horas_frio_openmeteo_rango(est, d0, d1, umbral_frio=UMBRAL_HORA_FRIO):
    """Solo para calibración interna contra ancla Agroclima (no mostrar como fuente)."""
    if d1 < d0:
        return 0.0
    try:
        df, _ = _fetch_openmeteo_hourly(est["lat"], est["lon"], d0, d1)
        df = _openmeteo_a_intervalos_15min(df)
    except Exception:
        return 0.0
    df = df.dropna(subset=["temp"]).copy()
    if df.empty:
        return 0.0
    df["fecha_hora"] = pd.to_datetime(df["fecha_hora"])
    ini = datetime.combine(d0, datetime.min.time())
    fin_dt = datetime.combine(d1, datetime.max.time())
    df = df[(df["fecha_hora"] >= ini) & (df["fecha_hora"] <= fin_dt)]
    return _calcular_horas_frio_acumuladas(df, umbral_frio)

def _acumulado_oficial_desde_may1(est, hasta, ancla):
    base = _inicio_base_may1(hasta)
    if hasta < base:
        return 0.0
    ancla_fecha = ancla["fecha"]
    ancla_horas = float(ancla["horas_desde_may1"])
    om_ancla = _horas_frio_openmeteo_rango(est, base, ancla_fecha)
    factor = (ancla_horas / om_ancla) if om_ancla > 0 else 1.0
    if hasta <= ancla_fecha:
        om = _horas_frio_openmeteo_rango(est, base, hasta)
        return round(om * factor, 1)
    extra = _horas_frio_openmeteo_rango(est, ancla_fecha + timedelta(days=1), hasta)
    return round(ancla_horas + extra * factor, 1)

def _horas_frio_rango_agroclima(est, inicio, fin):
    df_ag, fuente_ag = _fetch_agromet_hourly(est["id"], inicio, fin)
    if df_ag is not None and not df_ag.empty and len(df_ag) >= 48:
        work = _filtrar_df_temporada_frio(df_ag)
        if not work.empty and work["fecha"].min() <= inicio + timedelta(days=3):
            return _calcular_horas_frio_acumuladas(work), (fuente_ag or "Agromet / Agroclima")
    ancla = AGROCLIMA_ANCLA_OFICIAL.get(est["codigo"])
    if not ancla:
        return None, None
    base = _inicio_base_may1(fin)
    prev = inicio - timedelta(days=1)
    acum_fin = _acumulado_oficial_desde_may1(est, fin, ancla)
    acum_prev = _acumulado_oficial_desde_may1(est, prev, ancla) if prev >= base else 0.0
    return round(acum_fin - acum_prev, 1), "Informe Agroclima · est. Huelquén"

def _temp_max_dia_estacion(est, dia=None):
    dia = dia or hoy
    df_ag, _ = _fetch_agromet_hourly(est["id"], dia, dia)
    if df_ag is not None and not df_ag.empty:
        work = df_ag.dropna(subset=["temp"]).copy()
        work["fecha_hora"] = pd.to_datetime(work["fecha_hora"])
        work["fecha"] = work["fecha_hora"].dt.date
        if dia in set(work["fecha"]):
            return float(work.loc[work["fecha"] == dia, "temp"].max())
    df_er, _ = _fetch_estadored_15min(est["codigo"])
    if df_er is not None and not df_er.empty:
        work = df_er.dropna(subset=["temp"]).copy()
        work["fecha_hora"] = pd.to_datetime(work["fecha_hora"])
        work["fecha"] = work["fecha_hora"].dt.date
        if dia in set(work["fecha"]):
            return float(work.loc[work["fecha"] == dia, "temp"].max())
    return None

def _metricas_clima_estacion(est, inicio=None, fin=None):
    """Métricas diarias de la estación (temp. máx. hoy/ayer)."""
    temp_max_hoy = _temp_max_dia_estacion(est, hoy)
    ayer = hoy - timedelta(days=1)
    temp_max_ayer = _temp_max_dia_estacion(est, ayer)
    if temp_max_hoy is None and temp_max_ayer is None:
        return None, None
    return {
        "temp_max_hoy": temp_max_hoy,
        "temp_max_ayer": temp_max_ayer,
        "dia_caluroso_hoy": temp_max_hoy is not None and temp_max_hoy > UMBRAL_CALOR_DIA,
        "dia_caluroso_ayer": temp_max_ayer is not None and temp_max_ayer > UMBRAL_CALOR_DIA,
    }, "Agromet / Agroclima"

def _calcular_horas_frio_acumuladas(work, umbral_frio=UMBRAL_HORA_FRIO):
    if work is None or work.empty:
        return 0.0
    work = work.sort_values("fecha_hora")
    peso = _peso_intervalo_horas(work)
    frio = (work["temp"] >= 0) & (work["temp"] <= umbral_frio)
    return round(float(frio.sum() * peso), 1)

def calcular_clima_invernal(df, umbral_frio=UMBRAL_HORA_FRIO, umbral_calor=UMBRAL_CALOR_DIA):
    if df is None or df.empty:
        return None
    work = _filtrar_df_temporada_frio(df)
    if work.empty:
        return None
    horas_frio = _calcular_horas_frio_acumuladas(work, umbral_frio)
    ayer = hoy - timedelta(days=1)
    temp_max_ayer = None
    dia_caluroso_ayer = False
    if ayer in set(work["fecha"]):
        temp_max_ayer = float(work.loc[work["fecha"] == ayer, "temp"].max())
        dia_caluroso_ayer = temp_max_ayer > umbral_calor
    return {
        "horas_frio": horas_frio,
        "temp_max_ayer": temp_max_ayer,
        "dia_caluroso_ayer": dia_caluroso_ayer,
    }

def _parse_agromet_xml(xml_text):
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return None
    filas = []
    for nodo in root.iter():
        tag = nodo.tag.lower().split("}")[-1]
        if tag not in {"registro", "dato", "row", "data"} and "registro" not in tag:
            continue
        attrs = nodo.attrib
        fecha = attrs.get("fecha") or attrs.get("fecha_hora") or attrs.get("date")
        temp = attrs.get("temp_promedio_aire") or attrs.get("temp_promedio") or attrs.get("temperatura")
        if fecha and temp is not None:
            try:
                filas.append({"fecha_hora": fecha, "temp": float(str(temp).replace(",", "."))})
            except ValueError:
                continue
    return pd.DataFrame(filas) if filas else None

def _fetch_agromet_hourly(station_id, date_start, date_end):
    try:
        url = "https://www.agromet.cl/ext/aux/getGraphData.php"
        params = {
            "ema_ia_id": station_id,
            "dateFrom": date_start.strftime("%Y-%m-%d+%H:%M:%S"),
            "dateTo": date_end.strftime("%Y-%m-%d+%H:%M:%S"),
            "portada": "false",
        }
        r = requests.get(url, params=params, timeout=25, verify=False)
        if r.status_code != 200 or not r.text.strip().startswith("<"):
            return None, None
        df = _parse_agromet_xml(r.text)
        if df is not None and not df.empty:
            return df, "Agromet / Agroclima"
    except Exception:
        pass
    return None, None

def _fetch_openmeteo_hourly(lat, lon, date_start, date_end):
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": str(date_start),
        "end_date": str(date_end),
        "hourly": "temperature_2m",
        "timezone": "America/Santiago",
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    payload = r.json()
    return pd.DataFrame({
        "fecha_hora": payload["hourly"]["time"],
        "temp": payload["hourly"]["temperature_2m"],
    }), "Open-Meteo (coordenadas estación)"

def _openmeteo_a_intervalos_15min(df):
    work = df.dropna(subset=["temp"]).copy()
    work["fecha_hora"] = pd.to_datetime(work["fecha_hora"])
    filas = []
    for _, row in work.iterrows():
        base = row["fecha_hora"]
        for minutos in (0, 15, 30, 45):
            filas.append({"fecha_hora": base + pd.Timedelta(minutes=minutos), "temp": row["temp"]})
    return pd.DataFrame(filas)

def _fetch_estadored_15min(codigo):
    try:
        url = f"https://estadored.agroclima.cl/Home/Detalle?Codigo={codigo}"
        r = requests.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return None, None
        filas = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, flags=re.S | re.I):
            if "Fecha / Hora" in tr or "<thead" in tr:
                continue
            celdas = re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S | re.I)
            if len(celdas) < 4:
                continue
            texto = [re.sub(r"<[^>]+>", "", c).strip() for c in celdas]
            try:
                fecha_hora = datetime.strptime(texto[2], "%d-%m-%Y %H:%M")
                temp = float(texto[3].replace(",", "."))
                filas.append({"fecha_hora": fecha_hora, "temp": temp})
            except (ValueError, IndexError):
                continue
        if not filas:
            return None, None
        df = pd.DataFrame(filas).drop_duplicates(subset=["fecha_hora"]).sort_values("fecha_hora")
        return df, "EstadoRed Agroclima (15 min)"
    except Exception:
        return None, None

def _construir_df_clima(est, inicio, fin):
    """Histórico Open-Meteo (15 min sintético) + lecturas reales EstadoRed Agroclima."""
    df_ag, fuente = _fetch_agromet_hourly(est["id"], inicio, fin)
    if df_ag is not None and not df_ag.empty:
        df = df_ag.copy()
        fuente_out = fuente
    else:
        df_est, fuente_est = _fetch_estadored_15min(est["codigo"])
        try:
            df_om, fuente_om = _fetch_openmeteo_hourly(est["lat"], est["lon"], inicio, fin)
            df_om = _openmeteo_a_intervalos_15min(df_om)
        except Exception:
            df_om = None
            fuente_om = None
        if df_om is not None and df_est is not None and not df_est.empty:
            corte = pd.to_datetime(df_est["fecha_hora"].min())
            df_om = df_om.copy()
            df_om["fecha_hora"] = pd.to_datetime(df_om["fecha_hora"])
            df_om = df_om[df_om["fecha_hora"] < corte]
            df = pd.concat([df_om, df_est], ignore_index=True)
            fuente_out = f"EstadoRed Agroclima + {fuente_om or 'histórico'}"
        elif df_est is not None and not df_est.empty:
            df = df_est
            fuente_out = fuente_est
        elif df_om is not None and not df_om.empty:
            df = df_om
            fuente_out = fuente_om
        else:
            return None, None
    df = df.sort_values("fecha_hora").copy()
    df["fecha_hora"] = pd.to_datetime(df["fecha_hora"])
    fin_dt = datetime.combine(fin, datetime.max.time())
    inicio_dt = datetime.combine(inicio, datetime.min.time())
    df = df[(df["fecha_hora"] >= inicio_dt) & (df["fecha_hora"] <= fin_dt)]
    return df, fuente_out

def _fetch_clima_agroclima_vivo():
    est = CLIMATE_ESTACION
    metricas, fuente = _metricas_clima_estacion(est)
    if not metricas:
        return None
    return {
        **metricas,
        "estacion": est["nombre"],
        "estacion_id": est["codigo"],
        "estacion_agromet_id": est["id"],
        "region": est["region"],
        "fecha_hoy": hoy.strftime("%d-%m-%Y"),
        "fuente": fuente,
        "actualizado": hora_chile().strftime("%d-%m-%Y %H:%M"),
        "umbral_calor": UMBRAL_CALOR_DIA,
    }

def obtener_clima_agroclima():
    return _cache_diario_get("clima_agroclima", _fetch_clima_agroclima_vivo)

def _fmt_temp_clima(valor):
    if valor is None:
        return "—"
    return f"{float(valor):,.1f} °C".replace(",", "X").replace(".", ",").replace("X", ".")

def encabezado_dashboard_con_clima():
    st.session_state["modulo_activo"] = "DASHBOARD"
    aplicar_tema_modulo("DASHBOARD")
    tema = TEMAS_MODULO.get("DASHBOARD", {})
    color = tema.get("color", "#1B5E20")
    subtitulo = tema.get("sub", "")
    claro = tema.get("claro", "#E8F5E9")

    hr_css = (
        f"height:5px;border:none;border-radius:6px;margin:0;"
        f"background:linear-gradient(90deg,{color},{claro});"
    )
    titulo = "ERP AGRICOLA LA CONCEPCIÓN"
    sub_html = ""
    if subtitulo:
        sub_html = (
            f'<p style="text-align:left;color:#5F6B7A;font-size:0.92rem;'
            f'margin:0 0 0.2rem;">{subtitulo}</p>'
        )

    st.markdown(
        f"""<div class="dash-top-stack">
            <div class="dash-enc-simple">
                <hr style="{hr_css}margin:0 0 0.35rem;">
                <p style="text-align:left;font-size:2rem;font-weight:800;color:{color};
                    margin:0 0 0.15rem;line-height:1.15;">{titulo}</p>
                {sub_html}
                <p style="margin:0;"><span class="modulo-badge">DASHBOARD</span></p>
            </div>
        </div>""",
        unsafe_allow_html=True,
    )


def _render_widget_usuarios_dashboard_al_final(conn):
    """Donut de actividad de usuarios al pie del dashboard."""
    try:
        from erp_sesiones_usuarios import html_widget_actividad_usuarios
        widget_html = html_widget_actividad_usuarios(conn)
        if widget_html:
            st.divider()
            st.markdown(
                f'<div class="dash-us-widget-bottom">{widget_html}</div>',
                unsafe_allow_html=True,
            )
    except Exception:
        pass

def ruta_logo_pdf():
    try:
        from demo_web.services.branding import logo_path_for_pdf

        return logo_path_for_pdf()
    except Exception:
        pass
    slug = (TENANT_SLUG or "").strip().lower()
    if slug == "espino" or "espino" in (NOMBRE_DB or "").lower():
        return None
    for nombre in ("logo_concepcion.jpg", "logo_concepcion.png", "logo_concepcion.jpeg"):
        ruta = os.path.join(LOGO_DIR, nombre)
        if os.path.exists(ruta):
            return ruta
    return None

def _pdf_marca_empresa():
    return str(NOMBRE_ERP or "ERP Agrícola").upper()

def _pdf_razon_social_default():
    try:
        from demo_web.services.tenant_scope import razon_social_default
        return razon_social_default()
    except Exception:
        return "La Concepción"

def encabezado_pdf(pdf, titulo, modo_petroleo=False, saldo_petroleo=None):
    logo = ruta_logo_pdf()
    if logo:
        try:
            pdf.image(logo, x=10, y=8, w=40)
        except Exception:
            logo = None
    if not logo:
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_xy(10, 10)
        pdf.cell(80, 6, _pdf_txt(_pdf_marca_empresa()))
    fh = hora_chile().strftime("%d/%m/%Y %H:%M")
    pdf.set_font("Helvetica", "", 8)
    pdf.set_xy(215, 10)
    pdf.cell(72, 5, f"Generado: {fh}", align="R")
    if modo_petroleo and saldo_petroleo is not None:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_xy(175, 16)
        pdf.cell(112, 6, f"SALDO ESTANQUE: {f_decimal(saldo_petroleo)} L", align="R")
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_xy(10, 30)
    pdf.cell(277, 9, _pdf_txt(str(titulo)), align="C", ln=1)
    pdf.ln(6)

def _pdf_preparar_df(df):
    df_p = df.copy()
    cols_quitar = [c for c in df_p.columns if str(c).strip().lower() == "id"]
    if cols_quitar:
        df_p = df_p.drop(columns=cols_quitar)
    return df_p

def _pdf_es_columna_texto(col_n):
    col = str(col_n).lower()
    return any(
        t in col
        for t in (
            "detalle", "concepto", "descrip", "proveedor", "producto", "vehiculo",
            "responsable", "documento", "item", "observ", "nombre", "nota", "concept",
            "servicio", "contratista",
        )
    )

def _pdf_es_columna_cantidad(col_n):
    col = str(col_n).lower()
    return any(
        x in col
        for x in ("cantidad", "stock", "dosis", "total_prod", "total producto", "unidades")
    )

def _pdf_es_columna_volumen(col_n):
    col = str(col_n).lower()
    return any(x in col for x in ("litros", "volumen", "total_agua", "vol agua"))

def _pdf_es_columna_etiqueta(col_n):
    if _pdf_es_columna_texto(col_n):
        return True
    col = str(col_n).lower().strip()
    return col in (
        "rubro", "cuartel", "producto", "especie", "variedad", "fecha", "tipo", "estado",
        "vehiculo", "responsable", "proveedor", "documento", "nro_documento", "metodo",
        "lote", "ing activo", "ing. activo", "unidad", "maquinaria", "tractor", "aplicador",
        "observ", "motivo", "nota", "contacto", "rut", "email", "cargo", "nombre",
        "indicador", "valor", "codigo", "capitulo", "descripcion", "evidencia", "mercado",
        "vigente", "titulo", "version", "estado eval", "estado_eval", "app", "n°",
        "mes", "año", "anio", "phi", "familia", "um", "tipo evento", "tipo compra",
        "tipo gasto", "encargado", "etiqueta", "usuario", "accion", "fecha_hora",
        "correlativo", "corr", "folio int",
    ) or col.startswith(("fecha", "op.", "n°"))

def _pdf_es_columna_moneda(col_n, item):
    if _pdf_es_columna_etiqueta(col_n) or _pdf_es_columna_cantidad(col_n) or _pdf_es_columna_volumen(col_n):
        return False
    try:
        float(item)
    except (TypeError, ValueError):
        return False
    return True

def _pdf_formatear_celda(item, col_n, truncar=True):
    if _pdf_es_columna_etiqueta(col_n):
        txt = str(item)
        return txt[:55] if truncar else txt
    if _pdf_es_columna_cantidad(col_n) or _pdf_es_columna_volumen(col_n):
        return f_cantidad(item)
    try:
        float(item)
        return f_puntos(item)
    except (TypeError, ValueError):
        txt = str(item)
        return txt[:55] if truncar else txt

def _pdf_pesos_columnas(df_p, ancho_total=270):
    cols = list(df_p.columns)
    pesos = []
    for col in cols:
        cl = str(col).lower()
        if any(x in cl for x in ("servicio", "concepto", "detalle", "descripcion", "contratista", "proveedor")):
            pesos.append(4.0)
        elif "documento" in cl:
            pesos.append(2.0)
        elif "correlativo" in cl or cl in ("corr", "corr.", "folio int", "folio_interno"):
            pesos.append(1.8)
        elif "fecha" in cl:
            pesos.append(1.6)
        elif any(x in cl for x in ("monto", "pagado", "generado", "saldo", "debe", "haber", "abonado")):
            pesos.append(1.5)
        else:
            pesos.append(1.0)
    total = sum(pesos) or 1.0
    return [ancho_total * p / total for p in pesos]

def _pdf_lineas_celda(pdf, ancho, texto, h_line=4, font_size=6, bold=False):
    x, y = pdf.get_x(), pdf.get_y()
    pdf.set_font("Helvetica", "B" if bold else "", font_size)
    lines = pdf.multi_cell(ancho, h_line, _pdf_txt(str(texto)), split_only=True)
    pdf.set_xy(x, y)
    return max(1, len(lines) if lines else 1)

def _pdf_dibujar_fila_tabla(pdf, valores, cols, anchos, estilo_celda_fn, row, h_line=4, header=False, font_size_header=7, font_size_body=6):
    x0 = pdf.get_x()
    y0 = pdf.get_y()
    font_size = font_size_header if header else font_size_body
    n_lines = 1
    if header:
        # Medir con el título de columna (valores vienen vacíos en cabecera).
        textos = [str(c).upper() for c in cols]
    else:
        textos = [_pdf_formatear_celda(v, c, truncar=False) for v, c in zip(valores, cols)]
    for txt, w in zip(textos, anchos):
        n_lines = max(n_lines, _pdf_lineas_celda(pdf, w, txt, h_line, font_size, bold=header))
    row_h = n_lines * h_line
    if y0 + row_h > pdf.page_break_trigger - 8:
        pdf.add_page()
        x0, y0 = pdf.get_x(), pdf.get_y()

    pdf.set_draw_color(0, 0, 0)
    x = x0
    for val, col, w in zip(valores, cols, anchos):
        txt = _pdf_formatear_celda(val, col, truncar=False)
        align = _pdf_alinear_celda(col, val)
        estilo = estilo_celda_fn(row, col, val) if estilo_celda_fn and not header else None
        if header:
            pdf.set_font("Helvetica", "B", font_size)
            pdf.set_fill_color(236, 239, 241)
            pdf.set_text_color(33, 33, 33)
            pdf.rect(x, y0, w, row_h, style="DF")
            pdf.set_xy(x, y0)
            pdf.multi_cell(w, h_line, _pdf_txt(str(col).upper()), border=0, align="C")
        elif estilo:
            fill, text, bold = estilo
            pdf.set_fill_color(*fill)
            pdf.set_text_color(*text)
            pdf.set_font("Helvetica", "B" if bold else "", font_size)
            pdf.rect(x, y0, w, row_h, style="DF")
            pdf.set_xy(x, y0)
            pdf.multi_cell(w, h_line, _pdf_txt(txt), border=0, align=align)
        else:
            _pdf_reset_estilo(pdf)
            pdf.set_font("Helvetica", "", font_size)
            pdf.rect(x, y0, w, row_h, style="D")
            pdf.set_xy(x, y0)
            pdf.multi_cell(w, h_line, _pdf_txt(txt), border=0, align=align)
        x += w
    pdf.set_xy(x0, y0 + row_h)

def _pdf_reset_estilo(pdf):
    pdf.set_fill_color(255, 255, 255)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 6)

def _pdf_alinear_celda(col_n, item):
    if _pdf_es_columna_etiqueta(col_n):
        return "L"
    if _pdf_es_columna_cantidad(col_n) or _pdf_es_columna_volumen(col_n):
        return "R"
    try:
        float(item)
        return "R"
    except (TypeError, ValueError):
        return "L"

def _pdf_colores_celda_matriz_costos(rubro, col_n, valor):
    rubro_u = str(rubro or "").strip().upper()
    col_l = str(col_n or "").lower().strip()
    if rubro_u == "PRESUPUESTO":
        return (227, 242, 253), (13, 71, 161), True
    if rubro_u == "TOTAL GASTO":
        return (255, 248, 225), (245, 127, 23), True
    if rubro_u == "SALDO":
        if col_l == "rubro":
            return (245, 245, 245), (97, 97, 97), True
        try:
            m = float(valor or 0)
        except (TypeError, ValueError):
            m = 0.0
        if m < -0.5:
            return (255, 235, 238), (198, 40, 40), True
        if m > 0.5:
            return (232, 245, 233), (46, 125, 50), True
        return (245, 245, 245), (97, 97, 97), True
    return None

def _pdf_estilo_matriz_costos(row, col, val):
    rubro_col = next((c for c in row.index if str(c).lower().strip() == "rubro"), None)
    rubro = row[rubro_col] if rubro_col else ""
    return _pdf_colores_celda_matriz_costos(rubro, col, val)

def _pdf_estilo_tesoreria_vencida(row, col, val):
    for c in row.index:
        if "vencim" in str(c).lower():
            try:
                if pd.to_datetime(row[c]).date() < hoy:
                    return (255, 205, 210), (183, 28, 28), True
            except Exception:
                pass
    return None

def _pdf_estilo_gantt_alerta(row, col, val):
    alerta_col = next(
        (c for c in row.index if str(c).upper() in ("ALERTA", "NIVEL_ALERTA", "NIVEL ALERTA")),
        None,
    )
    if not alerta_col:
        return None
    nivel = str(row.get(alerta_col, "")).strip()
    mapa = {
        "Vencida": ((255, 235, 238), (183, 28, 28)),
        "Crítico": ((255, 235, 238), (183, 28, 28)),
        "Alto": ((255, 243, 224), (230, 81, 0)),
        "Medio": ((255, 248, 225), (249, 168, 37)),
        "Bajo": ((227, 242, 253), (21, 101, 192)),
        "En ritmo": ((232, 245, 233), (46, 125, 50)),
        "Completada": ((232, 245, 233), (46, 125, 50)),
    }
    if nivel in mapa:
        fill, text = mapa[nivel]
        return fill, text, True
    return None

def _pdf_estilo_gap_checklist(row, col, val):
    estado_col = next((c for c in row.index if str(c).lower().strip() == "estado"), None)
    if not estado_col:
        return None
    estado = str(row.get(estado_col, "")).strip()
    mapa = {
        "Cumple": ((232, 245, 233), (46, 125, 50)),
        "No cumple": ((255, 235, 238), (198, 40, 40)),
        "Pendiente": ((255, 248, 225), (245, 127, 23)),
    }
    if estado in mapa:
        fill, text = mapa[estado]
        return fill, text, True
    return None

def _pdf_estilo_gap_nc(row, col, val):
    estado_col = next((c for c in row.index if str(c).lower().strip() == "estado"), None)
    if not estado_col:
        return None
    estado = str(row.get(estado_col, "")).strip()
    if estado == "Abierta":
        return (255, 235, 238), (198, 40, 40), True
    if estado == "Cerrada":
        return (232, 245, 233), (46, 125, 50), True
    return None

def _pdf_estilo_gap_vigente(row, col, val):
    vig_col = next((c for c in row.index if str(c).lower().strip() == "vigente"), None)
    if not vig_col:
        return None
    v = str(row.get(vig_col, "")).strip().lower()
    if v in ("0", "false", "no", "inactivo"):
        return (255, 235, 238), (198, 40, 40), True
    return None

def _pdf_estilo_cap_vencida(row, col, val):
    for c in row.index:
        if "vigenc" in str(c).lower():
            try:
                if pd.to_datetime(row[c]).date() < hoy:
                    return (255, 248, 225), (245, 127, 23), True
            except Exception:
                pass
    return None

def _pdf_estilo_gap_agua(row, col, val):
    for c in row.index:
        if "fecha" in str(c).lower() or "muestra" in str(c).lower():
            try:
                if pd.to_datetime(row[c]).date() < hoy - timedelta(days=365):
                    return (255, 248, 225), (245, 127, 23), True
            except Exception:
                pass
    return None

def _pdf_estilo_stock_pppl(row, col, val):
    pppl_col = next((c for c in row.index if str(c).upper().strip() == "PPPL"), None)
    if not pppl_col:
        return None
    try:
        if int(float(row.get(pppl_col) or 0)) == 0:
            return (255, 248, 225), (245, 127, 23), True
    except (TypeError, ValueError):
        pass
    return None

def _pdf_dibujar_celda(pdf, w, h, texto, align, estilo):
    if estilo:
        fill, text, bold = estilo
        pdf.set_fill_color(*fill)
        pdf.set_text_color(*text)
        pdf.set_font("Helvetica", "B" if bold else "", 6)
        pdf.multi_cell(w, h, _pdf_txt(str(texto)), border=1, align=align, fill=True)
    else:
        _pdf_reset_estilo(pdf)
        pdf.multi_cell(w, h, _pdf_txt(str(texto)), border=1, align=align)

def generar_pdf_matriz_costos(df, titulo):
    return generar_pdf_blob(df, titulo, incluir_precios=False, estilo_celda_fn=_pdf_estilo_matriz_costos)

def _petroleo_eventos_historial(df):
    if df is None or df.empty:
        return []
    df_p = df.copy()
    df_p["fecha"] = pd.to_datetime(df_p["fecha"])
    if "id" not in df_p.columns:
        df_p["id"] = range(1, len(df_p) + 1)
    df_p = df_p.sort_values(["fecha", "id"])
    eventos = []
    mask_carga = df_p["tipo"].astype(str).str.lower() != "salida"
    for _, row in df_p[mask_carga].iterrows():
        eventos.append(("carga", row, row["fecha"], int(row["id"])))
    for _, grp in df_p[df_p["tipo"] == "Salida"].groupby(["fecha", "vehiculo", "responsable"], sort=False):
        eventos.append(("salida", grp, grp["fecha"].iloc[0], int(grp["id"].min())))
    eventos.sort(key=lambda x: (x[2], x[3]))
    return [(k, d, f) for k, d, f, _ in eventos]

def render_historial_petroleo_agrupado(df, mostrar_resumen=True):
    eventos = _petroleo_eventos_historial(df)
    if not eventos:
        st.info("No hay movimientos para los filtros seleccionados.")
        return
    n_sal = sum(1 for k, _, _ in eventos if k == "salida")
    n_car = sum(1 for k, _, _ in eventos if k == "carga")
    total_mov = len(eventos)
    if mostrar_resumen:
        st.caption(
            f"**{total_mov}** movimiento(s) · **{n_car}** entrada(s) · **{n_sal}** salida(s) · "
            f"más reciente arriba (N° {total_mov}), más antiguo abajo (N° 1)"
        )
    for num, (kind, data, _) in reversed(list(enumerate(eventos, start=1))):
        if kind == "carga":
            row = data
            bruto = row.get("monto_total_compra", 0) or 0
            st.markdown(
                f"""
                <div class="lc-evento-banner" style="background:linear-gradient(135deg,#E8F5E9,#C8E6C9);border-color:#2E7D32;">
                    <strong>Movimiento {num:03d} — ENTRADA</strong> &nbsp;|&nbsp;
                    {pd.to_datetime(row['fecha']).strftime('%Y-%m-%d')} &nbsp;|&nbsp;
                    {f_decimal(row.get('litros', 0))} L &nbsp;|&nbsp;
                    Total bruto compra: ${f_puntos(bruto)}
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            grp = data
            total_l = float(grp["litros"].sum())
            total_neto = float(grp["valor_imputado"].fillna(0).sum())
            st.markdown(
                f"""
                <div class="lc-evento-banner" style="background:linear-gradient(135deg,#FFF3E0,#FFF8E1);border-color:#FFB74D;">
                    <strong>Movimiento {num:03d} — SALIDA</strong> &nbsp;|&nbsp;
                    {pd.to_datetime(grp['fecha'].iloc[0]).strftime('%Y-%m-%d')} &nbsp;|&nbsp;
                    {grp['vehiculo'].iloc[0] or '—'} &nbsp;|&nbsp;
                    {grp['responsable'].iloc[0] or '—'} &nbsp;|&nbsp;
                    <strong>Total: {f_decimal(total_l)} L</strong> &nbsp;|&nbsp;
                    <strong>Neto imputado: ${f_puntos(total_neto)}</strong> &nbsp;|&nbsp;
                    {len(grp)} cuartel(es)
                </div>
                """,
                unsafe_allow_html=True,
            )
            df_det = grp[["centro_costo", "litros", "valor_imputado"]].copy()
            df_det = df_det.rename(columns={"centro_costo": "CUARTEL", "litros": "LITROS", "valor_imputado": "VALOR NETO IMP."})
            df_det["LITROS"] = df_det["LITROS"].apply(f_decimal)
            df_det["VALOR NETO IMP."] = df_det["VALOR NETO IMP."].apply(lambda x: f"${f_puntos(x)}")
            with st.container(border=True):
                st.dataframe(df_det, use_container_width=True, hide_index=True)

def generar_pdf_petroleo_historial(df, saldo_petroleo=None):
    try:
        eventos = _petroleo_eventos_historial(df)
        if not eventos:
            return None
        pdf = FPDF(orientation="L", unit="mm", format="A4")
        pdf.set_margins(10, 12, 10)
        pdf.set_auto_page_break(auto=True, margin=14)
        pdf.add_page()
        encabezado_pdf(pdf, "HISTORIAL DE PETRÓLEO", modo_petroleo=True, saldo_petroleo=saldo_petroleo)
        cols_det = ["CUARTEL", "LITROS", "VALOR NETO IMP."]
        widths = [85, 35, 45]
        total_mov = len(eventos)
        for num, (kind, data, _) in reversed(list(enumerate(eventos, start=1))):
            pdf.set_font("Helvetica", "B", 7)
            if kind == "carga":
                pdf.set_fill_color(232, 245, 233)
                row = data
                banner = _pdf_txt(
                    f"Movimiento {num:03d} — ENTRADA  |  {pd.to_datetime(row['fecha']).strftime('%Y-%m-%d')}  |  "
                    f"{f_decimal(row.get('litros', 0))} L  |  "
                    f"Total bruto compra: ${f_puntos(row.get('monto_total_compra', 0) or 0)}"
                )
            else:
                pdf.set_fill_color(255, 243, 224)
                grp = data
                total_l = float(grp["litros"].sum())
                total_neto = float(grp["valor_imputado"].fillna(0).sum())
                banner = _pdf_txt(
                    f"Movimiento {num:03d} — SALIDA  |  {pd.to_datetime(grp['fecha'].iloc[0]).strftime('%Y-%m-%d')}  |  "
                    f"{grp['vehiculo'].iloc[0] or '-'}  |  {grp['responsable'].iloc[0] or '-'}  |  "
                    f"Total: {f_decimal(total_l)} L  |  Neto imputado: ${f_puntos(total_neto)}  |  {len(grp)} cuartel(es)"
                )
            pdf.cell(0, 7, banner[:220], ln=1, fill=True)
            if kind == "salida":
                pdf.set_font("Helvetica", "B", 6)
                for col, w in zip(cols_det, widths):
                    pdf.cell(w, 6, _pdf_txt(col), border=1, align="C")
                pdf.ln()
                pdf.set_font("Helvetica", "", 6)
                for _, row in data.iterrows():
                    pdf.cell(widths[0], 6, _pdf_txt(str(row["centro_costo"]))[:45], border=1)
                    pdf.cell(widths[1], 6, _pdf_txt(f_decimal(row["litros"])), border=1, align="R")
                    pdf.cell(widths[2], 6, _pdf_txt(f"${f_puntos(row.get('valor_imputado', 0) or 0)}"), border=1, align="R")
                    pdf.ln()
            pdf.ln(2)
        return _pdf_output_bytes(pdf)
    except Exception:
        return None

def generar_pdf_blob(df, titulo, incluir_precios=True, total_manual=None, modo_petroleo=False, orden_asc=True, saldo_petroleo=None, campo_suma_forzado=None, estilo_celda_fn=None, font_size_header=7, font_size_body=6, h_line_header=8, h_line_body=4):
    try:
        pdf = FPDF(orientation="L"); pdf.add_page()
        encabezado_pdf(pdf, titulo, modo_petroleo, saldo_petroleo)
        df_p = _pdf_preparar_df(df)
        if orden_asc and 'fecha' in [c.lower() for c in df_p.columns]:
            cf = [c for c in df_p.columns if c.lower() == 'fecha'][0]; df_p[cf] = pd.to_datetime(df_p[cf]); df_p = df_p.sort_values(by=cf, ascending=True); df_p[cf] = df_p[cf].dt.date
        
        t_sum = total_manual if total_manual else 0
        if total_manual is None:
            if campo_suma_forzado and campo_suma_forzado in df_p.columns:
                t_sum = df_p[campo_suma_forzado].sum()
            else:
                for c in df_p.columns:
                    if len(df_p) and _pdf_es_columna_moneda(c, df_p[c].iloc[0]):
                        try:
                            t_sum += df_p[c].sum()
                        except Exception:
                            pass

        if modo_petroleo:
            df_p = df_p.drop(columns=[c for c in df_p.columns if any(x in c.lower() for x in ["imputado", "valor", "monto", "precio"])])
            incluir_precios = False
        cols = list(df_p.columns)
        anchos = _pdf_pesos_columnas(df_p)

        _pdf_dibujar_fila_tabla(
            pdf,
            [""] * len(cols),
            cols,
            anchos,
            estilo_celda_fn,
            None,
            h_line=h_line_header,
            header=True,
            font_size_header=font_size_header,
            font_size_body=font_size_body,
        )

        for _, row in df_p.iterrows():
            _pdf_dibujar_fila_tabla(
                pdf,
                [row[c] for c in cols],
                cols,
                anchos,
                estilo_celda_fn,
                row,
                h_line=h_line_body,
                font_size_header=font_size_header,
                font_size_body=font_size_body,
            )

        if incluir_precios and t_sum > 0:
            col_suma = campo_suma_forzado if campo_suma_forzado in cols else cols[-1]
            idx_suma = cols.index(col_suma)
            pdf.set_font("Helvetica", "B", max(8, int(font_size_body) + 1))
            pdf.set_fill_color(232, 245, 233)
            pdf.set_text_color(27, 94, 32)
            pdf.cell(sum(anchos[:idx_suma]), 8, "TOTAL CORRESPONDIENTE:", border=1, align="R", fill=True)
            pdf.cell(anchos[idx_suma], 8, f"${f_puntos(t_sum)}", border=1, align="R", fill=True)
            if idx_suma + 1 < len(anchos):
                pdf.cell(sum(anchos[idx_suma + 1:]), 8, "", border=1, fill=True)
        return _pdf_output_bytes(pdf)
    except Exception:
        return None

def _pdf_output_bytes(pdf):
    """fpdf 1.x devuelve str; fpdf 2.x devuelve bytearray."""
    raw = pdf.output(dest="S")
    if isinstance(raw, str):
        return raw.encode("latin-1")
    return bytes(raw)

def _pdf_txt(val):
    try:
        s = str(val).replace("—", "-").replace("–", "-").replace("−", "-")
        s = unicodedata.normalize("NFKD", s)
        s = "".join(ch for ch in s if not unicodedata.combining(ch))
        return s.encode("latin-1", "replace").decode("latin-1")
    except Exception:
        return ""

def generar_pdf_libro_campo(df, titulo="LIBRO DE CAMPO"):
    try:
        if df is None or df.empty:
            return None
        df_p = df.copy()
        col_app = next((c for c in df_p.columns if "APP" in str(c).upper()), df_p.columns[0])
        df_p = df_p.sort_values(by=[col_app], ascending=False)

        pdf = FPDF(orientation="L", unit="mm", format="A4")
        pdf.set_margins(10, 12, 10)
        pdf.set_auto_page_break(auto=True, margin=14)
        pdf.add_page()
        if hasattr(pdf, "set_title"):
            pdf.set_title(_pdf_txt(str(titulo)))
        encabezado_pdf(pdf, titulo)

        cols_prod = ["PRODUCTO", "LOTE", "ING ACTIVO", "DOSIS 100L", "UNIDAD", "TOTAL PROD", "FECHA VIABLE PHI"]
        widths = [52, 24, 38, 20, 30, 22, 30]
        ancho_tabla = sum(widths)

        for n_app, grp in df_p.groupby(col_app, sort=False):
            grp = grp.reset_index(drop=True)
            base = grp.iloc[0]
            pdf.set_font("Helvetica", "B", 7)
            pdf.set_fill_color(232, 245, 233)
            op_cert = base.get("OP. CERT.", "")
            if op_cert in (1, "1", True):
                op_cert = "Si"
            elif op_cert in (0, "0", False, "No"):
                op_cert = "No"
            banner = _pdf_txt(
                f"N° {base[col_app]}  |  {base.get('FECHA', '')}  |  {base.get('CUARTEL', '')}  |  "
                f"{base.get('ESPECIE', '')}  |  Agua: {f_decimal(base.get('VOL AGUA LT', 0))} L  |  "
                f"{base.get('MAQUINARIA', '')}  |  {base.get('TRACTOR', '')}  |  "
                f"{base.get('APLICADOR', '')}  |  Op.Cert: {op_cert}"
            )
            pdf.cell(0, 7, banner[:220], ln=1, fill=True)

            pdf.set_font("Helvetica", "B", 6)
            for col, w in zip(cols_prod, widths):
                etiqueta = col.replace("FECHA VIABLE PHI", "PHI VIABLE")
                pdf.cell(w, 6, _pdf_txt(etiqueta), border=1, align="C")
            pdf.ln()

            pdf.set_font("Helvetica", "", 6)
            for _, row in grp.iterrows():
                for col, w in zip(cols_prod, widths):
                    val = row.get(col, "")
                    if col == "DOSIS 100L":
                        val = f_dosis_lc(val)
                    elif col == "TOTAL PROD":
                        val = f_cantidad(val)
                    elif col == "FECHA VIABLE PHI":
                        val = str(val)[:10]
                    pdf.cell(w, 6, _pdf_txt(str(val))[:42], border=1)
                pdf.ln()
            pdf.ln(2)

        pdf.set_font("Helvetica", "I", 6)
        pdf.cell(ancho_tabla, 5, _pdf_txt(f"Total: {df_p[col_app].nunique()} evento(s), {len(df_p)} producto(s)"), ln=1)
        return _pdf_output_bytes(pdf)
    except Exception:
        return None

def render_historial_tesoreria_agrupado(df, mostrar_resumen=True):
    if df is None or df.empty:
        st.info("No hay pagos para los filtros seleccionados.")
        return
    df_p = df.copy()
    df_p = df_p.sort_values(["fecha_pago", "proveedor", "metodo_pago", "nro_documento"], ascending=[True, True, True, True])
    grupos = list(df_p.groupby(["proveedor", "fecha_pago", "metodo_pago"], sort=False))
    total_pagos = len(grupos)
    if mostrar_resumen:
        st.caption(
            f"**{total_pagos}** pago(s) registrado(s) · **{len(df_p)}** documento(s) · "
            f"más reciente arriba (N° {total_pagos}), más antiguo abajo (N° 1)"
        )
    for num, ((prov, f_pago, metodo), grp) in reversed(list(enumerate(grupos, start=1))):
        total = float(grp["monto_total"].sum())
        st.markdown(
            f"""
            <div class="lc-evento-banner">
                <strong>Pago {num:03d}</strong> &nbsp;|&nbsp;
                {prov} &nbsp;|&nbsp;
                {f_pago} &nbsp;|&nbsp;
                {metodo} &nbsp;|&nbsp;
                Total: ${f_puntos(total)} &nbsp;|&nbsp;
                {len(grp)} documento(s)
            </div>
            """,
            unsafe_allow_html=True,
        )
        df_det = grp[["nro_documento", "razon_social", "monto_total"]].copy()
        df_det = df_det.rename(columns={"nro_documento": "DOCUMENTO", "razon_social": "RAZÓN SOCIAL", "monto_total": "MONTO"})
        df_det["MONTO"] = df_det["MONTO"].apply(lambda x: f"${f_puntos(x)}")
        with st.container(border=True):
            st.dataframe(df_det, use_container_width=True, hide_index=True)

def generar_pdf_tesoreria_pagos(df):
    try:
        if df is None or df.empty:
            return None
        df_p = df.copy()
        df_p = df_p.sort_values(["fecha_pago", "proveedor", "metodo_pago", "nro_documento"], ascending=[True, True, True, True])
        grupos = list(df_p.groupby(["proveedor", "fecha_pago", "metodo_pago"], sort=False))

        pdf = FPDF(orientation="L", unit="mm", format="A4")
        pdf.set_margins(10, 12, 10)
        pdf.set_auto_page_break(auto=True, margin=14)
        pdf.add_page()
        encabezado_pdf(pdf, "HISTORIAL DE PAGOS")

        cols_det = ["DOCUMENTO", "RAZÓN SOCIAL", "MONTO"]
        widths = [90, 55, 50]
        ancho_tabla = sum(widths)

        for num, ((prov, f_pago, metodo), grp) in reversed(list(enumerate(grupos, start=1))):
            total = float(grp["monto_total"].sum())
            pdf.set_font("Helvetica", "B", 7)
            pdf.set_fill_color(232, 245, 233)
            banner = _pdf_txt(
                f"Pago {num:03d}  |  {prov}  |  {f_pago}  |  {metodo}  |  "
                f"Total: ${f_puntos(total)}  |  {len(grp)} documento(s)"
            )
            pdf.cell(0, 7, banner[:220], ln=1, fill=True)

            pdf.set_font("Helvetica", "B", 6)
            for col, w in zip(cols_det, widths):
                pdf.cell(w, 6, _pdf_txt(col), border=1, align="C")
            pdf.ln()

            pdf.set_font("Helvetica", "", 6)
            for _, row in grp.iterrows():
                pdf.cell(widths[0], 6, _pdf_txt(str(row["nro_documento"]))[:45], border=1)
                pdf.cell(widths[1], 6, _pdf_txt(str(row.get("razon_social") or _pdf_razon_social_default()))[:28], border=1)
                pdf.cell(widths[2], 6, _pdf_txt(f"${f_puntos(row['monto_total'])}"), border=1, align="R")
                pdf.ln()
            pdf.ln(2)

        pdf.set_font("Helvetica", "I", 6)
        pdf.cell(
            ancho_tabla, 5,
            _pdf_txt(f"Total: {len(grupos)} pago(s), {len(df_p)} documento(s)"),
            ln=1,
        )
        return _pdf_output_bytes(pdf)
    except Exception:
        return None

CSS_FORZAR_TEMA_CLARO = """
        html { color-scheme: light !important; }
        .stApp, .stApp[data-theme="dark"] {
            color-scheme: light !important;
            background: linear-gradient(180deg, #F8FBF8 0%, #F3F6F4 220px, #F3F6F4 100%) !important;
            color: #1F2933 !important;
        }
        [data-testid="stAppViewContainer"], [data-testid="stAppViewContainer"] .main,
        [data-testid="stAppViewContainer"] .main .block-container {
            background: transparent !important;
            color: #1F2933 !important;
        }
        [data-testid="stSidebar"], section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, #FFFFFF 0%, #F7FBF7 100%) !important;
            color: #1F2933 !important;
        }
        [data-testid="stSidebar"] label, [data-testid="stSidebar"] p, [data-testid="stSidebar"] span,
        [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3,
        [data-testid="stSidebar"] .stMarkdown, [data-testid="stSidebar"] .stRadio label {
            color: #1F2933 !important;
        }
        [data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] span,
        [data-testid="stMarkdownContainer"] li, [data-testid="stMarkdownContainer"] label,
        .stMarkdown p, .stMarkdown span, .stMarkdown label, label, p, span {
            color: #1F2933 !important;
        }
        .stTextInput input, .stNumberInput input, .stDateInput input,
        .stSelectbox div[data-baseweb="select"], textarea, input {
            background: #FAFCFA !important;
            color: #1F2933 !important;
            border-color: #DDE5DF !important;
        }
        [data-testid="stMetricLabel"], [data-testid="stMetricValue"],
        [data-testid="stDataFrame"], [data-testid="stTable"] {
            color: #1F2933 !important;
        }
        .stTabs [data-baseweb="tab-list"], .stTabs [data-baseweb="tab"] {
            background: #EEF3EE !important;
            color: #1F2933 !important;
        }
        .stTabs [aria-selected="true"] {
            background: #FFFFFF !important;
            color: #1B5E20 !important;
        }
        @media (prefers-color-scheme: dark) {
            html, body, .stApp, [data-testid="stSidebar"], [data-testid="stAppViewContainer"] {
                color-scheme: light !important;
            }
        }
"""

CSS_MOBILE_RESPONSIVE = """
        html {
            -webkit-text-size-adjust: 100%;
            text-size-adjust: 100%;
        }
        .stApp {
            overflow-x: hidden;
        }
        @media (max-width: 768px) {
            [data-testid="stAppViewContainer"] .main .block-container {
                padding-left: 0.75rem !important;
                padding-right: 0.75rem !important;
                padding-top: 3.25rem !important;
                max-width: 100% !important;
            }
            [data-testid="stHorizontalBlock"] {
                flex-direction: column !important;
                flex-wrap: wrap !important;
                gap: 0.5rem !important;
                width: 100% !important;
            }
            [data-testid="stHorizontalBlock"] > [data-testid="column"],
            [data-testid="column"] {
                width: 100% !important;
                flex: 1 1 100% !important;
                min-width: 0 !important;
            }
            .stTabs [data-baseweb="tab-list"] {
                flex-wrap: nowrap !important;
                overflow-x: auto !important;
                -webkit-overflow-scrolling: touch;
                scrollbar-width: thin;
            }
            .stTabs [data-baseweb="tab"] {
                padding: 0.45rem 0.65rem !important;
                font-size: 0.72rem !important;
                white-space: nowrap !important;
                flex-shrink: 0 !important;
            }
            [data-testid="stDataFrame"],
            [data-testid="stTable"],
            [data-testid="stDataFrame"] > div,
            [data-testid="stDataFrame"] div[data-testid="glideDataEditor"],
            .dvn-scroller {
                overflow-x: auto !important;
                -webkit-overflow-scrolling: touch;
                max-width: 100% !important;
            }
            .modulo-titulo h1 {
                font-size: 1.35rem !important;
            }
            .modulo-titulo p {
                font-size: 0.85rem !important;
            }
            .logo-modulo {
                max-width: 160px !important;
            }
            .logo-sidebar {
                max-width: 120px !important;
            }
            .clima-widget-compact,
            .ind-widget-compact {
                max-width: 100% !important;
                margin-left: 0 !important;
                text-align: left !important;
            }
            .gantt-head,
            .gantt-row {
                grid-template-columns: 1fr !important;
            }
            .gantt-scale {
                margin-left: 0 !important;
            }
            [data-testid="stVerticalBlock"]:has(.gap-especie-marker) + [data-testid="stVerticalBlock"] [data-testid="stRadio"] > div {
                flex-direction: column !important;
            }
            [data-testid="stVerticalBlock"]:has(.gap-especie-marker) + [data-testid="stVerticalBlock"] [data-testid="stRadio"] label {
                min-width: unset !important;
                width: 100% !important;
                font-size: 1rem !important;
                padding: 0.65rem 1rem !important;
            }
            .stApp:has(.maq-bg-marker) .main [data-testid="stTabs"]:has([data-baseweb="tab"]:nth-child(2)[aria-selected="true"]) > div:first-child,
            .stApp:has(.maq-bg-marker) .main [data-testid="stTabs"]:has([data-baseweb="tab"]:nth-child(2)[aria-selected="true"]) [data-baseweb="tab-list"] {
                width: 100% !important;
                max-width: 100% !important;
                min-width: 0 !important;
            }
            .st-key-btn_logout {
                top: 3.15rem !important;
                right: 0.35rem !important;
            }
            [data-testid="stFormSubmitButton"] button,
            .stDownloadButton > button,
            .stButton > button {
                min-height: 2.75rem !important;
            }
            .pdf-toolbar {
                justify-content: stretch !important;
            }
            .sidebar-user {
                word-break: break-all;
            }
            /* Evita zoom automático al enfocar inputs en iOS Safari */
            input, select, textarea, [data-baseweb="input"] input {
                font-size: 16px !important;
            }
        }
        /* iPhone / iPad (clase inyectada por erp_cliente_web) */
        body.erp-ios [data-testid="stSidebar"] {
            padding-bottom: env(safe-area-inset-bottom, 0px);
        }
        body.erp-ios [data-testid="stAppViewContainer"] .main .block-container {
            padding-left: max(0.75rem, env(safe-area-inset-left)) !important;
            padding-right: max(0.75rem, env(safe-area-inset-right)) !important;
            padding-bottom: max(1rem, env(safe-area-inset-bottom)) !important;
        }
        body.erp-ios .st-key-btn_logout {
            top: max(3.15rem, calc(env(safe-area-inset-top, 0px) + 2.5rem)) !important;
            right: max(0.35rem, env(safe-area-inset-right, 0px)) !important;
        }
        body.erp-mobile [data-testid="stMetric"] {
            min-width: 0 !important;
        }
        body.erp-mobile [data-testid="stMetricValue"] {
            font-size: 1.15rem !important;
        }
        body.erp-mobile .stDownloadButton > button,
        body.erp-mobile [data-testid="stFormSubmitButton"] button,
        body.erp-mobile .stButton > button {
            min-height: 2.85rem !important;
            font-size: 0.95rem !important;
        }
        body.erp-mobile [data-testid="stAppViewContainer"]:has(.login-bg-marker) [data-testid="stHorizontalBlock"] {
            position: fixed !important;
            z-index: 20 !important;
            top: auto !important;
            bottom: max(1rem, env(safe-area-inset-bottom, 0px)) !important;
            left: 0.75rem !important;
            right: 0.75rem !important;
            width: auto !important;
        }
        body.erp-mobile [data-testid="stAppViewContainer"]:has(.login-bg-marker) .login-hero-fixed {
            top: 42% !important;
            width: min(92vw, 480px) !important;
        }
        @media (max-width: 480px) {
            [data-testid="stAppViewContainer"] .main .block-container {
                padding-left: 0.5rem !important;
                padding-right: 0.5rem !important;
            }
            .stTabs [data-baseweb="tab"] {
                font-size: 0.65rem !important;
                padding: 0.38rem 0.48rem !important;
            }
            .saldo-banner,
            .banner-econ {
                font-size: 0.92rem !important;
                padding: 0.7rem 0.85rem !important;
            }
            .brand-sidebar .brand-title {
                font-size: 0.92rem !important;
            }
        }
"""

CSS_SOLO_LECTURA_UI = """
        [data-testid="stAppViewContainer"] [data-testid="stFormSubmitButton"] button,
        [data-testid="stAppViewContainer"] [data-testid="stForm"] input,
        [data-testid="stAppViewContainer"] [data-testid="stForm"] textarea,
        [data-testid="stAppViewContainer"] [data-testid="stForm"] select,
        [data-testid="stAppViewContainer"] [data-testid="stForm"] [data-baseweb="select"],
        [data-testid="stAppViewContainer"] [data-testid="stForm"] [data-baseweb="input"],
        [data-testid="stAppViewContainer"] [data-testid="stForm"] [data-baseweb="textarea"],
        [data-testid="stAppViewContainer"] [data-testid="stForm"] [data-testid="stCheckbox"],
        [data-testid="stAppViewContainer"] [data-testid="stFileUploader"],
        [data-testid="stAppViewContainer"] [data-testid="stDataEditor"],
        [data-testid="stAppViewContainer"] [data-testid="stButton"] > button:not([data-baseweb="tab"]):not(.erp-consulta-btn),
        [data-testid="stAppViewContainer"] [data-testid="stDownloadButton"],
        [data-testid="stAppViewContainer"] [data-testid="stDownloadButton"] button {
            pointer-events: none !important;
            opacity: 0.55 !important;
            cursor: not-allowed !important;
            filter: grayscale(0.12);
        }
        [data-testid="stExpander"] summary,
        [data-testid="stExpander"] button,
        [class*="st-key-chip_ing_"] button,
        .st-key-btn_logout,
        .st-key-btn_logout button,
        [data-testid="stSidebar"] button,
        [data-testid="stSidebar"] input,
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] [data-baseweb="radio"],
        .stSidebarCollapsedControl,
        .stSidebarCollapsedControl button,
        [data-testid="stDateInput"] input,
        [data-testid="stSelectbox"] [data-baseweb="select"],
        [data-testid="stMultiSelect"] [data-baseweb="select"],
        [data-testid="stTextInput"] input,
        [data-testid="stNumberInput"] input,
        [data-testid="stRadio"] label,
        [data-testid="stSegmentedControl"] button {
            pointer-events: auto !important;
            opacity: 1 !important;
            cursor: pointer !important;
            filter: none !important;
        }
        div[data-testid="stHtml"] iframe {
            pointer-events: none !important;
        }
"""

def inyectar_css():
    icono_cierre = _uri_icono_cierre_sesion()
    css_comun = """<style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,600;0,9..40,700;0,9..40,800;1,9..40,400&display=swap');

        :root {
            --verde-oscuro: #1B5E20;
            --verde-medio: #2E7D32;
            --verde-claro: #E8F5E9;
            --azul-accion: #1565C0;
            --azul-oscuro: #0D47A1;
            --fondo: #F3F6F4;
            --tarjeta: #FFFFFF;
            --texto: #1F2933;
            --texto-suave: #5F6B7A;
            --borde: #DDE5DF;
            --sombra: 0 8px 24px rgba(27, 94, 32, 0.08);
            --radio: 14px;
            color-scheme: light;
        }
""" + CSS_FORZAR_TEMA_CLARO + """

        html, body, [class*="css"] {
            font-family: 'DM Sans', sans-serif !important;
            color: var(--texto);
        }

        header { visibility: visible !important; display: block !important; height: auto !important; }

        .stSidebarCollapsedControl {
            display: flex !important;
            visibility: visible !important;
            background-color: var(--verde-medio) !important;
            border-radius: 8px !important;
        }
        .stSidebarCollapsedControl button,
        .stSidebarCollapsedControl svg {
            background-color: var(--verde-medio) !important;
            color: white !important;
            fill: white !important;
            border-radius: 8px !important;
        }

        .stApp, [data-testid="stAppViewContainer"] > .main {
            background: linear-gradient(180deg, #F8FBF8 0%, var(--fondo) 220px, var(--fondo) 100%) !important;
        }

        h1, h2, h3, h4 {
            color: var(--verde-oscuro) !important;
            letter-spacing: -0.02em;
        }

        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #FFFFFF 0%, #F7FBF7 100%) !important;
            border-right: 1px solid var(--borde);
        }
        [data-testid="stSidebar"] h2 {
            font-size: 1.15rem !important;
            margin-bottom: 0 !important;
        }
        [data-testid="stSidebar"] .stRadio label {
            padding: 0.55rem 0.75rem !important;
            border-radius: 10px !important;
            transition: background 0.15s ease;
        }
        [data-testid="stSidebar"] .stRadio label:hover {
            background: var(--verde-claro) !important;
        }

        .brand-sidebar {
            background: transparent;
            color: var(--verde-oscuro);
            padding: 0 0 0.75rem;
            border-radius: 0;
            margin-bottom: 0.5rem;
            box-shadow: none;
            text-align: center;
        }
        .brand-logo-wrap {
            background: transparent;
            border-radius: 0;
            padding: 0 0 0.5rem;
            margin-bottom: 0.35rem;
            box-shadow: none;
            border: none;
        }
        .logo-empresa, .logo-sidebar, .logo-login, .logo-modulo {
            background: transparent !important;
        }
        .logo-sidebar {
            max-width: 100% !important;
            filter: drop-shadow(0 2px 8px rgba(0,0,0,0.18));
        }
        .logo-login { max-width: 280px !important; margin-bottom: 0.9rem !important; }
        .logo-modulo { max-width: 200px !important; margin-bottom: 0 !important; }
        .dash-top-stack {
            margin-top: -0.55rem;
            margin-bottom: 0.1rem;
        }
        .stApp:has(.dash-top-stack) [data-testid="stAppViewContainer"] .main .block-container {
            padding-top: 0 !important;
        }
        .stApp:has(.dash-top-stack) .main [data-testid="stVerticalBlock"] {
            gap: 0.2rem !important;
        }
        .dash-enc-simple {
            width: 100%;
            margin-bottom: 0.1rem;
        }
        .dash-us-widget-bottom {
            display: flex;
            justify-content: flex-end;
            width: 100%;
            margin-top: 0.35rem;
        }
        .dash-us-widget-bottom .us-widget-anchor {
            flex: 0 0 auto;
            max-width: min(270px, 100%);
            margin: 0;
        }
        .dash-encabezado-us {
            width: 100%;
            margin-top: 0.05rem;
            margin-bottom: 0.25rem;
        }
        .dash-enc-hr-fila {
            display: flex;
            align-items: flex-end;
            justify-content: space-between;
            gap: 0.75rem;
            margin-bottom: 0.55rem;
        }
        .dash-enc-hr-col {
            flex: 1;
            min-width: 0;
            padding-top: 0.08rem;
        }
        .brand-sidebar .brand-title {
            font-size: 1.05rem;
            font-weight: 800;
            line-height: 1.2;
            margin: 0;
            color: var(--verde-oscuro);
        }
        .brand-sidebar .brand-sub {
            font-size: 0.78rem;
            color: var(--texto-suave);
            margin-top: 0.35rem;
        }
        .clima-widget-compact {
            background: linear-gradient(135deg, #F8FBFF 0%, #EEF4FF 100%);
            border: 1px solid #C5D9F2;
            border-radius: 14px;
            padding: 0.75rem 0.9rem 0.7rem;
            text-align: right;
            max-width: 270px;
            margin-left: auto;
            margin-top: 0.1rem;
            box-shadow: 0 6px 16px rgba(21, 101, 192, 0.1);
        }
        .clima-widget-kicker {
            font-size: 0.78rem;
            font-weight: 700;
            color: #1565C0;
            letter-spacing: 0.01em;
            margin-bottom: 0.15rem;
        }
        .clima-widget-valor {
            font-size: 2rem;
            font-weight: 800;
            color: #0D47A1;
            line-height: 1;
        }
        .clima-widget-label {
            font-size: 0.76rem;
            color: #5F6B7A;
            margin-top: 0.12rem;
        }
        .clima-widget-meta {
            font-size: 0.72rem;
            color: #6B7B8C;
            margin-top: 0.35rem;
            line-height: 1.3;
        }
        .clima-us-spark {
            display: flex;
            align-items: flex-end;
            justify-content: flex-end;
            gap: 0.2rem;
            height: 2rem;
            margin-top: 0.3rem;
        }
        .us-widget-donut .clima-widget-valor,
        .us-widget-donut .clima-widget-label { display: none; }
        .dash-enc-hr-fila .us-widget-anchor {
            position: relative;
            z-index: 3;
            margin: 0;
            flex: 0 0 auto;
            max-width: min(270px, 38vw);
        }
        .clima-widget-compact.us-widget-donut {
            margin-top: 0;
            margin-bottom: 0;
            padding-top: 0.55rem;
            padding-bottom: 0.55rem;
        }
        .clima-widget-compact.us-widget-donut .clima-widget-kicker {
            margin-bottom: 0.45rem;
        }
        .us-donut-wrap {
            display: flex;
            justify-content: flex-end;
            margin: 0.1rem 0 0.3rem;
        }
        .clima-widget-compact.us-widget-donut .clima-widget-meta {
            margin-top: 0.28rem;
            margin-bottom: 0.15rem;
        }
        .us-donut {
            width: 118px;
            height: 118px;
            border-radius: 50%;
            position: relative;
            flex-shrink: 0;
        }
        .us-donut-hole {
            position: absolute;
            width: 74px;
            height: 74px;
            background: #fff;
            border-radius: 50%;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            box-shadow: inset 0 0 0 1px rgba(21, 101, 192, 0.08);
        }
        .us-donut-center {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            text-align: center;
            z-index: 2;
            line-height: 1.05;
        }
        .us-donut-num {
            font-size: 1.55rem;
            font-weight: 800;
            color: #0D47A1;
        }
        .us-donut-lbl {
            font-size: 0.58rem;
            font-weight: 600;
            color: #5F6B7A;
            text-transform: uppercase;
            letter-spacing: 0.02em;
        }
        .us-leyenda {
            margin-top: 0.2rem;
            text-align: right;
        }
        .us-leyenda-vacia {
            font-size: 0.68rem;
            color: #90A4AE;
            font-style: italic;
        }
        .us-ley-fila {
            display: flex;
            align-items: center;
            justify-content: flex-end;
            gap: 0.28rem;
            font-size: 0.62rem;
            line-height: 1.45;
            color: #37474F;
        }
        .us-ley-dot {
            width: 7px;
            height: 7px;
            border-radius: 50%;
            flex-shrink: 0;
        }
        .us-ley-nom {
            max-width: 5.5rem;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .us-ley-pct {
            font-weight: 800;
            color: #1565C0;
            min-width: 1.8rem;
            text-align: right;
        }
        .us-ley-otros { color: #78909C; }
        .maq-widget-petroleo {
            max-width: 300px;
        }
        .maq-widget-petroleo .clima-widget-kicker {
            margin-bottom: 0.35rem;
        }
        .maq-donut-duo {
            display: flex;
            justify-content: flex-end;
            gap: 0.55rem;
            margin: 0.15rem 0 0.25rem;
        }
        .maq-mini-donut {
            text-align: center;
            flex: 0 0 auto;
        }
        .maq-mini-ring {
            width: 92px;
            height: 92px;
            border-radius: 50%;
            position: relative;
            margin: 0 auto;
        }
        .maq-mini-hole {
            position: absolute;
            width: 58px;
            height: 58px;
            background: #fff;
            border-radius: 50%;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            box-shadow: inset 0 0 0 1px rgba(230, 81, 0, 0.1);
        }
        .maq-mini-center {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            text-align: center;
            z-index: 2;
            line-height: 1.05;
        }
        .maq-mini-num {
            font-size: 0.82rem;
            font-weight: 800;
            color: #E65100;
        }
        .maq-mini-lbl {
            font-size: 0.52rem;
            font-weight: 700;
            color: #6B7B8C;
            text-transform: uppercase;
        }
        .maq-mini-cap {
            font-size: 0.58rem;
            font-weight: 700;
            color: #5F6B7A;
            margin-top: 0.2rem;
            line-height: 1.15;
        }
        .maq-leyenda-pet {
            margin-top: 0.15rem;
            text-align: right;
        }
        .maq-ley-bloque {
            margin-bottom: 0.2rem;
        }
        .maq-ley-tit {
            font-size: 0.56rem;
            font-weight: 800;
            color: #6B7B8C;
            text-transform: uppercase;
            letter-spacing: 0.03em;
            margin-bottom: 0.08rem;
        }
        .maq-leyenda-vacia {
            font-size: 0.65rem;
            color: #90A4AE;
            font-style: italic;
            text-align: right;
        }
        .maq-ley-fila {
            display: flex;
            align-items: center;
            justify-content: flex-end;
            gap: 0.25rem;
            font-size: 0.58rem;
            line-height: 1.4;
            color: #37474F;
        }
        .maq-ley-dot {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            flex-shrink: 0;
        }
        .maq-ley-nom {
            max-width: 4.5rem;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .maq-ley-pct {
            font-weight: 800;
            color: #E65100;
            min-width: 1.6rem;
            text-align: right;
        }
        .clima-us-spark-col {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: flex-end;
            height: 100%;
            min-width: 0.85rem;
        }
        .clima-us-spark-bar {
            width: 0.65rem;
            background: linear-gradient(180deg, #64B5F6 0%, #1565C0 100%);
            border-radius: 2px 2px 0 0;
            min-height: 2px;
        }
        .clima-us-spark-n {
            font-size: 0.55rem;
            font-weight: 700;
            color: #1565C0;
            line-height: 1;
            margin-top: 1px;
        }
        .clima-widget-actualizado {
            font-size: 0.68rem;
            color: #7B8A99;
            margin-top: 0.22rem;
            font-weight: 600;
        }
        .clima-widget-off {
            font-size: 0.72rem;
            color: #888;
            text-align: right;
        }
        .clima-widget-alerta {
            background: linear-gradient(135deg, #FFF3E0 0%, #FFE0B2 100%);
            border-color: #FFB74D;
            box-shadow: 0 6px 16px rgba(230, 81, 0, 0.12);
        }
        .clima-widget-alerta .clima-widget-valor {
            color: #E65100;
        }
        .clima-widget-alerta .clima-widget-meta {
            color: #BF360C;
            font-weight: 700;
        }
        .ind-widget-compact {
            background: linear-gradient(145deg, #0D47A1 0%, #1565C0 55%, #1976D2 100%);
            color: #fff;
            border-radius: 14px;
            padding: 0.85rem 1rem;
            margin: 0 0 0.65rem auto;
            max-width: 19rem;
            box-shadow: 0 8px 20px rgba(13, 71, 161, 0.22);
            text-align: right;
        }
        .ind-widget-kicker {
            font-size: 0.72rem;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            opacity: 0.92;
            margin-bottom: 0.2rem;
        }
        .ind-widget-valor {
            font-size: 1.45rem;
            font-weight: 800;
            line-height: 1.15;
            margin-bottom: 0.15rem;
        }
        .ind-widget-meta {
            font-size: 0.78rem;
            opacity: 0.95;
            line-height: 1.35;
        }
        .ind-widget-actualizado {
            font-size: 0.68rem;
            opacity: 0.8;
            margin-top: 0.35rem;
        }
        .ind-widget-off {
            background: #ECEFF1;
            color: #546E7A;
            border: 1px dashed #90A4AE;
            box-shadow: none;
            font-size: 0.72rem;
            text-align: right;
        }
        .sidebar-user {
            color: var(--azul-oscuro) !important;
            font-weight: 700 !important;
            font-size: 0.95rem !important;
        }
        .status-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            background: var(--verde-claro);
            color: var(--verde-oscuro);
            border: 1px solid #A5D6A7;
            padding: 0.35rem 0.7rem;
            border-radius: 999px;
            font-size: 0.82rem;
            font-weight: 700;
            margin: 0.4rem 0 0.8rem;
        }

        .login-shell { max-width: 460px; margin: 2rem auto 1rem; }
        .login-hero {
            text-align: center;
            margin-bottom: 1.2rem;
        }
        .login-hero h1 {
            font-size: 2rem !important;
            margin-bottom: 0.35rem !important;
        }
        .login-hero p {
            color: var(--texto-suave);
            margin: 0;
            font-size: 0.95rem;
        }
        .prod-badge {
            display: inline-block;
            margin-top: 0.65rem;
            padding: 0.25rem 0.7rem;
            border-radius: 999px;
            background: var(--verde-claro);
            color: var(--verde-oscuro);
            font-size: 0.78rem;
            font-weight: 700;
            border: 1px solid #A5D6A7;
        }
        [data-testid="stForm"] {
            background: var(--tarjeta);
            border: 1px solid var(--borde);
            border-radius: calc(var(--radio) + 2px);
            padding: 1.4rem 1.5rem 1.2rem;
            box-shadow: var(--sombra);
        }
        [data-testid="stForm"] label {
            font-weight: 600 !important;
            color: var(--texto) !important;
        }
        [data-testid="stForm"] input {
            border-radius: 10px !important;
            border: 1px solid var(--borde) !important;
            background: #FAFCFA !important;
        }
        [data-testid="stFormSubmitButton"] button {
            width: 100%;
            background: linear-gradient(135deg, var(--verde-medio), var(--verde-oscuro)) !important;
            color: white !important;
            border: none !important;
            border-radius: 12px !important;
            padding: 0.7rem 1rem !important;
            font-weight: 800 !important;
            letter-spacing: 0.04em;
            box-shadow: 0 8px 18px rgba(46, 125, 50, 0.25);
            transition: transform 0.15s ease, box-shadow 0.15s ease;
        }
        [data-testid="stFormSubmitButton"] button:hover {
            transform: translateY(-1px);
            box-shadow: 0 10px 22px rgba(46, 125, 50, 0.32);
        }

        .stMetric, .metric-card {
            background: var(--tarjeta);
            padding: 1.1rem 1.2rem;
            border-radius: var(--radio);
            box-shadow: var(--sombra);
            border: 1px solid var(--borde);
            border-left: 5px solid var(--verde-medio);
        }
        [data-testid="stMetricValue"] {
            font-size: clamp(0.9rem, 1.8vw, 1.45rem) !important;
            font-weight: 800 !important;
            color: var(--verde-oscuro) !important;
            overflow: visible !important;
            text-overflow: unset !important;
            white-space: normal !important;
            word-break: break-word !important;
            line-height: 1.2 !important;
        }
        [data-testid="stMetricLabel"] {
            font-weight: 600 !important;
            color: var(--texto-suave) !important;
            overflow: visible !important;
            text-overflow: unset !important;
            white-space: normal !important;
            font-size: clamp(0.72rem, 1.1vw, 0.9rem) !important;
            line-height: 1.25 !important;
        }
        [data-testid="stMetric"] {
            min-width: 0 !important;
            overflow: visible !important;
        }
        [data-testid="column"] {
            min-width: 0 !important;
        }

        .dashboard-kpi-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(min(100%, 11.5rem), 1fr));
            gap: 0.75rem;
            margin-bottom: 1rem;
            width: 100%;
        }
        .dashboard-kpi-card {
            background: var(--tarjeta);
            padding: 0.95rem 1rem;
            border-radius: var(--radio);
            box-shadow: var(--sombra);
            border: 1px solid var(--borde);
            border-left: 5px solid var(--verde-medio);
            min-width: 0;
            overflow: visible;
        }
        .dashboard-kpi-label {
            font-size: clamp(0.7rem, 1.15vw, 0.88rem);
            font-weight: 600;
            color: var(--texto-suave);
            line-height: 1.25;
            margin-bottom: 0.35rem;
            word-wrap: break-word;
        }
        .dashboard-kpi-value {
            font-size: clamp(0.95rem, 2.1vw, 1.65rem);
            font-weight: 800;
            color: var(--verde-oscuro);
            line-height: 1.15;
            word-break: break-word;
            overflow-wrap: anywhere;
        }
        .dashboard-kpi-value.critico { color: #d32f2f; }
        .dashboard-kpi-value.alerta { color: #1976d2; }

        .dashboard-dual-panel {
            background: var(--tarjeta);
            border: 1px solid var(--borde);
            border-radius: var(--radio);
            box-shadow: var(--sombra);
            padding: 1rem 1.1rem 0.9rem;
            margin-bottom: 0.25rem;
            min-height: 100%;
        }
        .dashboard-dual-title {
            font-size: 1rem;
            font-weight: 800;
            color: var(--verde-oscuro);
            margin: 0 0 0.85rem;
            padding-bottom: 0.55rem;
            border-bottom: 2px solid var(--verde-claro);
            letter-spacing: -0.01em;
        }
        .dashboard-fila-monto {
            background: #FAFCFA;
            padding: 0.62rem 0.85rem;
            border-radius: 10px;
            margin-bottom: 0.42rem;
            border-left: 4px solid var(--verde-medio);
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 0.75rem;
            font-size: 0.88rem;
            line-height: 1.3;
        }
        .dashboard-fila-monto .etiqueta {
            font-weight: 600;
            color: var(--texto);
            min-width: 0;
            word-break: break-word;
        }
        .dashboard-fila-monto .monto {
            font-weight: 800;
            color: var(--verde-oscuro);
            white-space: nowrap;
            font-size: 0.92rem;
        }
        .dashboard-fila-monto.total {
            background: var(--verde-claro);
            border-left-color: var(--verde-oscuro);
            margin-top: 0.35rem;
        }
        .dashboard-fila-monto.total .etiqueta,
        .dashboard-fila-monto.total .monto {
            font-weight: 800;
            color: var(--verde-oscuro);
        }
        .dashboard-fila-monto.pago {
            border-left-color: var(--azul-accion);
            background: #F8FBFF;
        }
        .dashboard-fila-monto.pago .monto {
            color: var(--azul-oscuro);
        }
        .dashboard-fila-monto.pago-vacio .monto {
            color: var(--texto-suave);
            font-weight: 600;
        }
        .dashboard-cc-header,
        .dashboard-fila-monto.dashboard-fila-cc {
            display: grid;
            grid-template-columns: minmax(0, 1.4fr) minmax(4.2rem, 1fr) minmax(3.2rem, 0.7fr) minmax(4rem, 0.75fr);
            gap: 0.5rem;
            align-items: center;
            justify-content: unset;
        }
        .dashboard-cc-header {
            font-size: 0.76rem;
            font-weight: 700;
            color: var(--texto-suave);
            text-transform: uppercase;
            letter-spacing: 0.03em;
            padding: 0 0.85rem 0.25rem;
            margin-bottom: -0.15rem;
        }
        .dashboard-cc-header span:not(:first-child),
        .dashboard-fila-cc .monto,
        .dashboard-fila-cc .metrica {
            text-align: right;
        }
        .dashboard-fila-cc .metrica {
            font-weight: 700;
            white-space: nowrap;
            font-size: 0.86rem;
        }
        .dashboard-fila-cc .metrica.badge-costos {
            padding: 0.18rem 0.5rem;
            border-radius: 8px;
            display: inline-block;
            min-width: 3.2rem;
            text-align: center;
        }

        .lc-evento-banner {
            background: linear-gradient(135deg, #E8F5E9, #F1F8E9);
            border: 1px solid #A5D6A7;
            border-left: 5px solid var(--verde-medio);
            padding: 0.7rem 1rem;
            border-radius: 10px;
            font-size: 0.84rem;
            font-weight: 600;
            color: var(--verde-oscuro);
            margin: 1rem 0 0.4rem;
            line-height: 1.45;
            box-shadow: 0 4px 12px rgba(46, 125, 50, 0.08);
        }
        .lc-evento-card {
            border: 1px solid var(--borde);
            border-radius: 12px;
            padding: 0 0.5rem 0.75rem;
            margin-bottom: 0.5rem;
            background: var(--tarjeta);
            box-shadow: 0 4px 14px rgba(0, 0, 0, 0.04);
        }
        .lc-evento-spacer { height: 0.35rem; }

        .banner-econ {
            background: linear-gradient(135deg, var(--azul-oscuro), var(--azul-accion));
            color: white;
            padding: 0.85rem 1rem;
            border-radius: 12px;
            text-align: center;
            font-weight: 700;
            margin-bottom: 1.2rem;
            font-size: clamp(0.75rem, 1.4vw, 0.92rem);
            box-shadow: 0 6px 16px rgba(13, 71, 161, 0.18);
            line-height: 1.45;
            word-wrap: break-word;
        }
        @media (max-width: 1280px) {
            .clima-widget-compact {
                max-width: 100%;
                margin-left: 0;
                text-align: left;
            }
            .ind-widget-compact {
                max-width: 100%;
                margin-left: 0;
                text-align: left;
            }
            .dashboard-kpi-grid {
                grid-template-columns: repeat(auto-fit, minmax(min(100%, 9.5rem), 1fr));
            }
        }
        @media (max-width: 960px) {
            .dashboard-kpi-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }
        @media (max-width: 560px) {
            .dashboard-kpi-grid {
                grid-template-columns: 1fr;
            }
        }
        .saldo-banner {
            background: linear-gradient(135deg, #E8F5E9, #F1F8E9);
            color: var(--verde-oscuro);
            padding: 1rem 1.2rem;
            border-radius: var(--radio);
            border: 1px solid #A5D6A7;
            text-align: center;
            margin-bottom: 1.2rem;
            font-size: 1.25rem;
            font-weight: 800;
            box-shadow: var(--sombra);
        }
        .alert-roja {
            background: #FFEBEE;
            color: #B71C1C;
            padding: 0.8rem 1rem;
            border-radius: 12px;
            border: 1px solid #EF9A9A;
            margin-bottom: 0.8rem;
            font-weight: 700;
            text-align: center;
        }
        .alert-amarilla {
            background: #FFF8E1;
            color: #F57F17;
            padding: 0.8rem 1rem;
            border-radius: 12px;
            border: 1px solid #FFE082;
            margin-bottom: 0.8rem;
            font-weight: 700;
            text-align: center;
        }
        .alert-naranja {
            background: #FFF3E0;
            color: #E65100;
            padding: 0.8rem 1rem;
            border-radius: 12px;
            border: 1px solid #FFCC80;
            margin-bottom: 0.8rem;
            font-weight: 700;
            text-align: center;
        }
        .gantt-wrap {
            background: white;
            border: 1px solid var(--borde);
            border-radius: var(--radio);
            padding: 1rem 1rem 0.5rem;
            box-shadow: var(--sombra);
            margin-bottom: 1rem;
        }
        .gantt-head, .gantt-row {
            display: grid;
            grid-template-columns: 240px 1fr;
            gap: 0.75rem;
            align-items: center;
        }
        .gantt-head {
            font-size: 0.75rem;
            font-weight: 800;
            color: var(--texto-suave);
            text-transform: uppercase;
            letter-spacing: 0.04em;
            margin-bottom: 0.5rem;
        }
        .gantt-scale {
            position: relative;
            height: 28px;
            margin-left: 240px;
            border-bottom: 1px solid var(--borde);
            margin-bottom: 0.75rem;
        }
        .gantt-mes {
            position: absolute;
            top: 0;
            font-size: 0.68rem;
            color: var(--texto-suave);
            font-weight: 700;
            transform: translateX(-50%);
        }
        .gantt-today {
            position: absolute;
            top: 0;
            bottom: -8px;
            width: 2px;
            background: #C62828;
            z-index: 3;
        }
        .gantt-today::after {
            content: 'Hoy';
            position: absolute;
            top: -16px;
            left: -10px;
            font-size: 0.62rem;
            color: #C62828;
            font-weight: 800;
        }
        .gantt-row {
            padding: 0.45rem 0;
            border-top: 1px solid #EEF2EE;
        }
        .gantt-task-name {
            font-weight: 700;
            font-size: 0.86rem;
            color: var(--texto);
        }
        .gantt-task-sub {
            font-size: 0.72rem;
            color: var(--texto-suave);
            margin-top: 0.15rem;
        }
        .gantt-track {
            position: relative;
            height: 34px;
            background: #F3F6F4;
            border-radius: 8px;
        }
        .gantt-bar {
            position: absolute;
            top: 5px;
            height: 24px;
            border-radius: 6px;
            border: 2px solid #90A4AE;
            background: white;
            overflow: hidden;
            min-width: 36px;
        }
        .gantt-fill {
            height: 100%;
            opacity: 0.85;
        }
        .gantt-pct {
            position: absolute;
            inset: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.68rem;
            font-weight: 800;
            color: #1F2933;
            text-shadow: 0 0 4px white;
        }
        .gantt-empty {
            text-align: center;
            color: var(--texto-suave);
            padding: 2rem;
            background: white;
            border-radius: var(--radio);
            border: 1px dashed var(--borde);
        }
        .gantt-leyenda {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem 1rem;
            margin-bottom: 0.8rem;
            font-size: 0.78rem;
        }
        .gantt-leyenda span {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
        }
        .gantt-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            display: inline-block;
        }
        .gap-especie-panel {
            background: linear-gradient(135deg, #E0F2F1 0%, #E8F5E9 100%);
            border: 2px solid #00695C;
            border-radius: 16px;
            padding: 1rem 1.25rem 0.75rem;
            margin: 0.5rem 0 0.25rem;
            box-shadow: 0 6px 20px rgba(0, 105, 92, 0.12);
        }
        .gap-especie-titulo {
            font-size: 1.15rem;
            font-weight: 800;
            color: #004D40;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }
        .gap-especie-sub {
            font-size: 0.88rem;
            color: #00695C;
            margin-top: 0.25rem;
            font-weight: 600;
        }
        [data-testid="stVerticalBlock"]:has(.gap-especie-marker) + [data-testid="stVerticalBlock"] {
            background: #F8FBF9;
            border: 2px solid #80CBC4;
            border-radius: 14px;
            padding: 0.65rem 1rem 0.85rem;
            margin-bottom: 1rem;
        }
        [data-testid="stVerticalBlock"]:has(.gap-especie-marker) + [data-testid="stVerticalBlock"] [data-testid="stRadio"] > div {
            gap: 1rem;
            justify-content: center;
        }
        [data-testid="stVerticalBlock"]:has(.gap-especie-marker) + [data-testid="stVerticalBlock"] [data-testid="stRadio"] label {
            background: white !important;
            border: 2px solid #B2DFDB !important;
            border-radius: 12px !important;
            padding: 0.9rem 2.2rem !important;
            font-size: 1.35rem !important;
            font-weight: 800 !important;
            color: #004D40 !important;
            letter-spacing: 0.04em !important;
            box-shadow: 0 4px 12px rgba(0, 77, 64, 0.08) !important;
            transition: all 0.15s ease !important;
            min-width: 200px;
            justify-content: center !important;
        }
        [data-testid="stVerticalBlock"]:has(.gap-especie-marker) + [data-testid="stVerticalBlock"] [data-testid="stRadio"] label:hover {
            border-color: #00695C !important;
            background: #E0F2F1 !important;
            transform: translateY(-1px);
        }
        [data-testid="stVerticalBlock"]:has(.gap-especie-marker) + [data-testid="stVerticalBlock"] [data-testid="stRadio"] label[data-checked="true"],
        [data-testid="stVerticalBlock"]:has(.gap-especie-marker) + [data-testid="stVerticalBlock"] [data-testid="stRadio"] div[aria-checked="true"] label {
            background: linear-gradient(135deg, #00695C, #00897B) !important;
            border-color: #004D40 !important;
            color: white !important;
            box-shadow: 0 6px 18px rgba(0, 77, 64, 0.28) !important;
        }
        .modulo-titulo {
            text-align: center;
            margin: 0.2rem 0 1.2rem;
        }
        .modulo-titulo h1 {
            font-size: 2rem !important;
            margin-bottom: 0.2rem !important;
        }
        .modulo-titulo p {
            color: var(--texto-suave);
            margin: 0;
            font-size: 0.95rem;
        }

        .stTabs [data-baseweb="tab-list"] {
            gap: 0.35rem;
            background: #EEF3EE;
            padding: 0.35rem;
            border-radius: 12px;
        }
        .stTabs [data-baseweb="tab"] {
            border-radius: 10px !important;
            font-weight: 700 !important;
            padding: 0.55rem 0.9rem !important;
        }
        .stTabs [aria-selected="true"] {
            background: white !important;
            color: var(--verde-oscuro) !important;
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        }

        .stButton > button {
            border-radius: 10px !important;
            font-weight: 700 !important;
            transition: transform 0.15s ease, box-shadow 0.15s ease;
        }
        .stButton > button:hover {
            transform: translateY(-1px);
        }

        .stDownloadButton > button {
            background: linear-gradient(135deg, var(--azul-accion), var(--azul-oscuro)) !important;
            color: white !important;
            border: none !important;
            border-radius: 12px !important;
            padding: 0.62rem 1.1rem !important;
            font-weight: 800 !important;
            letter-spacing: 0.02em;
            box-shadow: 0 8px 18px rgba(21, 101, 192, 0.22);
            transition: transform 0.15s ease, box-shadow 0.15s ease;
        }
        .stDownloadButton > button:hover {
            transform: translateY(-1px);
            box-shadow: 0 10px 22px rgba(21, 101, 192, 0.3);
        }
        .pdf-toolbar {
            display: flex;
            justify-content: flex-end;
            margin: 0.8rem 0 1rem;
            padding-top: 0.4rem;
            border-top: 1px dashed var(--borde);
        }

        [data-testid="stDataFrame"] {
            border: 1px solid var(--borde);
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 4px 14px rgba(0,0,0,0.04);
        }

        .stTextInput input, .stNumberInput input, .stDateInput input, .stSelectbox div[data-baseweb="select"] {
            border-radius: 10px !important;
        }

        hr, [data-testid="stDivider"] {
            border-color: var(--borde) !important;
        }

        .modulo-titulo {
            animation: fadeSlideIn 0.4s ease-out;
        }
        .modulo-titulo::before {
            content: "";
            display: block;
            height: 5px;
            border-radius: 6px;
            margin: 0 0 1rem;
            background: linear-gradient(90deg, var(--modulo-accent, #1B5E20), var(--modulo-claro, #E8F5E9));
            animation: stripeGrow 0.45s ease-out;
        }
        @keyframes fadeSlideIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        @keyframes stripeGrow {
            from { opacity: 0; transform: scaleX(0.4); }
            to { opacity: 1; transform: scaleX(1); }
        }
        .modulo-badge {
            display: inline-block;
            margin-top: 0.45rem;
            padding: 0.2rem 0.65rem;
            border-radius: 999px;
            background: var(--modulo-claro, #E8F5E9);
            color: var(--modulo-accent, #1B5E20);
            font-size: 0.75rem;
            font-weight: 700;
            border: 1px solid color-mix(in srgb, var(--modulo-accent, #1B5E20) 25%, white);
        }

        .stMetric {
            border-left-color: var(--modulo-accent, var(--verde-medio)) !important;
            animation: fadeSlideIn 0.45s ease-out;
        }
        .stTabs [aria-selected="true"] {
            color: var(--modulo-accent, var(--verde-oscuro)) !important;
        }

        /* Botones semánticos por key de Streamlit */
        .st-key-comp_btn_save button,
        .st-key-t_p3 button,
        [class*="st-key-"] button[kind="primary"] {
            background: linear-gradient(135deg, #43A047, #2E7D32) !important;
            color: white !important;
            border: none !important;
        }
        .st-key-comp_btn_undo button,
        .st-key-mod_comp_3 button,
        .st-key-rh_p2 button {
            background: linear-gradient(135deg, #EF5350, #C62828) !important;
            color: white !important;
            border: none !important;
        }
        .st-key-b_m3 button,
        .st-key-em_4 button,
        .st-key-rh_p1 button {
            background: linear-gradient(135deg, #42A5F5, #1565C0) !important;
            color: white !important;
            border: none !important;
        }
        .st-key-t_p3 button {
            background: linear-gradient(135deg, #FFB300, #F57C00) !important;
            color: #3E2723 !important;
            font-weight: 800 !important;
        }
        .st-key-btn_logout {
            position: fixed !important;
            top: 3.65rem !important;
            right: 0.75rem !important;
            z-index: 1001 !important;
            width: auto !important;
            margin: 0 !important;
        }
        </style>"""
    css_logout_icono = f"""<style>
        .st-key-btn_logout [data-testid="stButton"] > button,
        .st-key-btn_logout button[kind="secondary"],
        .st-key-btn_logout button[data-testid="stBaseButton-secondary"] {{
            background: transparent !important;
            background-color: transparent !important;
            background-image: url("{icono_cierre}") !important;
            background-repeat: no-repeat !important;
            background-position: center !important;
            background-size: auto 2.85rem !important;
            border: none !important;
            border-radius: 0 !important;
            min-width: 2.35rem !important;
            min-height: 2.85rem !important;
            padding: 0.2rem !important;
            box-shadow: none !important;
            color: transparent !important;
            font-size: 0 !important;
            line-height: 0 !important;
        }}
        .st-key-btn_logout [data-testid="stButton"] > button:hover,
        .st-key-btn_logout button[kind="secondary"]:hover {{
            background-color: transparent !important;
            background-image: url("{icono_cierre}") !important;
            filter: brightness(1.08) drop-shadow(0 4px 12px rgba(198, 40, 40, 0.45));
            box-shadow: none !important;
            color: transparent !important;
        }}
        .st-key-btn_logout [data-testid="stButton"] > button p,
        .st-key-btn_logout [data-testid="stButton"] > button span,
        .st-key-btn_logout [data-testid="stButton"] > button div {{
            color: transparent !important;
            -webkit-text-fill-color: transparent !important;
            font-size: 0 !important;
            line-height: 0 !important;
            opacity: 0 !important;
        }}
        </style>"""

    css_extra = f"<style>{CSS_SOLO_LECTURA_UI}</style>" if es_solo_lectura() else ""
    st.markdown(
        css_comun + f"<style>{CSS_MOBILE_RESPONSIVE}</style>" + css_logout_icono + css_extra,
        unsafe_allow_html=True,
    )
    try:
        from erp_cliente_web import cliente_web
        cliente_web()
    except Exception:
        pass
    try:
        from erp_conexion import inyectar_watchdog_conexion_streamlit
        inyectar_watchdog_conexion_streamlit()
    except Exception:
        pass

def _aplicar_bloqueo_solo_lectura_js():
    components.html(
        """
        <script>
        (function () {
            const w = window.parent;
            const doc = w.document;
            doc.body.classList.add("erp-solo-lectura");

            const css = `
            body.erp-solo-lectura [data-testid="stAppViewContainer"] input:not([data-testid="stDateInput"] input),
            body.erp-solo-lectura [data-testid="stAppViewContainer"] textarea,
            body.erp-solo-lectura [data-testid="stAppViewContainer"] [data-baseweb="input"]:not([data-testid="stDateInput"] [data-baseweb="input"]),
            body.erp-solo-lectura [data-testid="stAppViewContainer"] [data-baseweb="textarea"],
            body.erp-solo-lectura [data-testid="stAppViewContainer"] [data-testid="stCheckbox"],
            body.erp-solo-lectura [data-testid="stAppViewContainer"] [data-testid="stFileUploader"],
            body.erp-solo-lectura [data-testid="stAppViewContainer"] [data-testid="stDataEditor"],
            body.erp-solo-lectura [data-testid="stAppViewContainer"] [data-testid="stFormSubmitButton"] button,
            body.erp-solo-lectura [data-testid="stAppViewContainer"] [data-testid="stButton"] > button:not([data-baseweb="tab"]):not(.erp-consulta-btn),
            body.erp-solo-lectura [data-testid="stAppViewContainer"] [data-testid="stDownloadButton"],
            body.erp-solo-lectura [data-testid="stAppViewContainer"] [data-testid="stDownloadButton"] button {
                pointer-events: none !important;
                opacity: 0.55 !important;
                cursor: not-allowed !important;
                filter: grayscale(0.12);
            }
            body.erp-solo-lectura [data-testid="stExpander"] summary,
            body.erp-solo-lectura [data-testid="stExpander"] button,
            body.erp-solo-lectura [class*="st-key-chip_ing_"] button {
                pointer-events: auto !important;
                opacity: 1 !important;
                cursor: pointer !important;
                filter: none !important;
            }
            body.erp-solo-lectura [data-testid="stForm"] input,
            body.erp-solo-lectura [data-testid="stForm"] textarea,
            body.erp-solo-lectura [data-testid="stForm"] select,
            body.erp-solo-lectura [data-testid="stForm"] [data-baseweb="select"],
            body.erp-solo-lectura [data-testid="stForm"] [data-baseweb="input"],
            body.erp-solo-lectura [data-testid="stForm"] [data-baseweb="textarea"],
            body.erp-solo-lectura [data-testid="stForm"] [data-testid="stCheckbox"] {
                pointer-events: none !important;
                opacity: 0.55 !important;
                cursor: not-allowed !important;
                filter: grayscale(0.12);
            }
            body.erp-solo-lectura .st-key-btn_logout,
            body.erp-solo-lectura .st-key-btn_logout button,
            body.erp-solo-lectura .st-key-btn_logout [data-testid="stButton"] > button,
            body.erp-solo-lectura [data-baseweb="tab"] {
                pointer-events: auto !important;
                opacity: 1 !important;
                cursor: pointer !important;
                filter: none !important;
            }
            body.erp-solo-lectura .stSidebarCollapsedControl,
            body.erp-solo-lectura .stSidebarCollapsedControl button,
            body.erp-solo-lectura [data-testid="stSidebar"],
            body.erp-solo-lectura [data-testid="stSidebar"] button,
            body.erp-solo-lectura [data-testid="stSidebar"] label,
            body.erp-solo-lectura [data-testid="stSidebar"] input,
            body.erp-solo-lectura [data-testid="stSidebar"] [data-baseweb="radio"] {
                pointer-events: auto !important;
                opacity: 1 !important;
                cursor: pointer !important;
                filter: none !important;
            }
            body.erp-solo-lectura div[data-testid="stHtml"] iframe {
                pointer-events: none !important;
            }
            body.erp-mobile.erp-solo-lectura .stSidebarCollapsedControl {
                z-index: 1000001 !important;
            }`;
            let styleEl = doc.getElementById("erp-solo-lectura-style");
            if (!styleEl) {
                styleEl = doc.createElement("style");
                styleEl.id = "erp-solo-lectura-style";
                doc.head.appendChild(styleEl);
            }
            styleEl.textContent = css;

            function enSidebar(el) {
                const sidebar = doc.querySelector('[data-testid="stSidebar"]');
                const collapsed = doc.querySelector(".stSidebarCollapsedControl");
                return (sidebar && sidebar.contains(el)) || (collapsed && collapsed.contains(el));
            }

            function esLogout(el) {
                return el.closest(".st-key-btn_logout");
            }

            function dentroDeFormulario(el) {
                return !!el.closest('[data-testid="stForm"]');
            }

            function esExpander(el) {
                return !!el.closest('[data-testid="stExpander"]');
            }

            function esChipConsulta(el) {
                return !!el.closest('[class*="st-key-chip_ing_"]');
            }

            function esFiltroConsulta(el) {
                if (dentroDeFormulario(el)) return false;
                if (el.closest('[data-testid="stDateInput"]')) return true;
                if (el.closest('[data-testid="stSelectbox"]')) return true;
                if (el.closest('[data-testid="stMultiSelect"]')) return true;
                if (el.closest('[data-testid="stTextInput"]')) return true;
                if (el.closest('[data-testid="stNumberInput"]')) return true;
                if (el.closest('[data-baseweb="select"]') && !dentroDeFormulario(el)) return true;
                if (el.tagName === "SELECT" && !dentroDeFormulario(el)) return true;
                if (el.closest('[data-testid="stRadio"]') && !dentroDeFormulario(el)) return true;
                if (el.closest('[data-testid="stSegmentedControl"]')) return true;
                return false;
            }

            function esControlSidebar(el) {
                return !!el.closest(".stSidebarCollapsedControl, [data-testid=\"stSidebarCollapsedControl\"]");
            }

            function permitido(el) {
                if (enSidebar(el)) return true;
                if (esControlSidebar(el)) return true;
                if (el.getAttribute("data-baseweb") === "tab") return true;
                if (esLogout(el)) return true;
                if (esExpander(el)) return true;
                if (esChipConsulta(el)) return true;
                if (esFiltroConsulta(el)) return true;
                return false;
            }

            function bloquear() {
                const main = doc.querySelector('[data-testid="stAppViewContainer"]');
                if (!main) return;
                main.querySelectorAll("input, textarea, select, button").forEach((el) => {
                    if (permitido(el)) {
                        if (el.tagName === "BUTTON") {
                            el.disabled = false;
                            el.removeAttribute("aria-disabled");
                            el.style.pointerEvents = "auto";
                            el.style.opacity = "1";
                            el.style.cursor = "pointer";
                            el.style.filter = "none";
                            if (esChipConsulta(el)) {
                                el.classList.add("erp-consulta-btn");
                            }
                        } else {
                            el.disabled = false;
                            el.readOnly = false;
                            el.removeAttribute("aria-disabled");
                            el.removeAttribute("tabindex");
                            el.style.pointerEvents = "auto";
                            el.style.opacity = "1";
                            el.style.cursor = "";
                            el.style.filter = "none";
                        }
                        return;
                    }
                    if (el.tagName === "BUTTON") {
                        el.disabled = true;
                        el.setAttribute("aria-disabled", "true");
                        el.style.pointerEvents = "none";
                        el.style.opacity = "0.55";
                        return;
                    }
                    el.readOnly = true;
                    el.disabled = true;
                    el.setAttribute("tabindex", "-1");
                    el.style.pointerEvents = "none";
                    el.style.opacity = "0.68";
                });
                main.querySelectorAll('[data-baseweb="select"], [data-baseweb="input"], [data-baseweb="textarea"]').forEach((el) => {
                    if (enSidebar(el) || esFiltroConsulta(el) || esExpander(el)) {
                        el.style.pointerEvents = "auto";
                        el.style.opacity = "1";
                        return;
                    }
                    el.style.pointerEvents = "none";
                    el.style.opacity = "0.68";
                });
                doc.querySelectorAll(".st-key-btn_logout button").forEach((el) => {
                    el.disabled = false;
                    el.removeAttribute("aria-disabled");
                    el.style.pointerEvents = "auto";
                    el.style.opacity = "1";
                    el.style.cursor = "pointer";
                });
                doc.querySelectorAll(
                    ".stSidebarCollapsedControl button, [data-testid=\"stSidebarCollapsedControl\"] button, "
                    + "[data-testid=\"stSidebar\"] button, [data-testid=\"stSidebar\"] label, "
                    + "[data-testid=\"stSidebar\"] input"
                ).forEach((el) => {
                    el.disabled = false;
                    el.removeAttribute("aria-disabled");
                    el.style.pointerEvents = "auto";
                    el.style.opacity = "1";
                    el.style.cursor = "pointer";
                    el.style.filter = "none";
                });
            }

            bloquear();
            if (!w.__erpRoObs) {
                w.__erpRoObs = new w.MutationObserver(bloquear);
                w.__erpRoObs.observe(doc.body, { childList: true, subtree: true });
            }
        })();
        </script>
        """,
        height=0,
        width=0,
    )


def _al_cambiar_menu_sidebar():
    """Marca cierre de sidebar en móvil (se aplica tras el rerun de Streamlit)."""
    st.session_state["_erp_cerrar_sidebar_movil"] = True


def _marcar_cierre_sidebar_si_cambio_menu(menu_choice):
    prev = st.session_state.get("_erp_menu_prev")
    if prev is not None and prev != menu_choice:
        st.session_state["_erp_cerrar_sidebar_movil"] = True
    st.session_state["_erp_menu_prev"] = menu_choice


def _colapsar_sidebar_movil_js(run_id):
    """Dispara cierre del sidebar (run_id único evita que Streamlit cachee el componente)."""
    components.html(
        f"""
        <script>
        (function () {{
            const w = window.parent;
            const fn = w.__erpColapsarSidebarMobil;
            if (typeof fn !== "function") return;
            [0, 100, 250, 500, 900, 1400].forEach((ms) => {{
                setTimeout(fn, ms);
            }});
        }})();
        </script>
        <!-- run:{run_id} -->
        """,
        height=0,
        width=0,
    )


def _inyectar_sidebar_movil_js():
    """iPhone/móvil: estilos + función global de cierre + listener persistente en el menú."""
    components.html(
        """
        <script>
        (function () {
            const w = window.parent;
            const doc = w.document;

            function esMovil() {
                return doc.body.classList.contains("erp-mobile")
                    || doc.body.classList.contains("erp-ios")
                    || w.matchMedia("(max-width: 768px)").matches;
            }

            const css = `
            body.erp-mobile .stSidebarCollapsedControl,
            body.erp-ios .stSidebarCollapsedControl,
            body.erp-mobile [data-testid="stSidebarCollapsedControl"],
            body.erp-ios [data-testid="stSidebarCollapsedControl"] {
                z-index: 1000001 !important;
            }`;
            let styleEl = doc.getElementById("erp-mobile-sidebar-style");
            if (!styleEl) {
                styleEl = doc.createElement("style");
                styleEl.id = "erp-mobile-sidebar-style";
                doc.head.appendChild(styleEl);
            }
            styleEl.textContent = css;

            function sidebarAbierta() {
                const sb = doc.querySelector('[data-testid="stSidebar"], section[data-testid="stSidebar"]');
                if (!sb) return false;
                if (sb.getAttribute("aria-expanded") === "true") return true;
                const rect = sb.getBoundingClientRect();
                return rect.width > 80 && w.matchMedia("(max-width: 768px)").matches;
            }

            w.__erpColapsarSidebarMobil = function () {
                if (!esMovil() || !sidebarAbierta()) return false;

                const sb = doc.querySelector('[data-testid="stSidebar"], section[data-testid="stSidebar"]');
                const intentos = [];

                const backdrop = doc.querySelector('[data-testid="stSidebarBackdrop"]');
                if (backdrop) intentos.push(backdrop);

                if (sb) {
                    [
                        '[data-testid="stSidebarCollapseButton"] button',
                        '[data-testid="stSidebarCollapseButton"]',
                        '[data-testid="stSidebarHeader"] button',
                        'button[kind="headerNoPadding"]',
                        '[data-testid="baseButton-header"]',
                    ].forEach((sel) => {
                        const el = sb.querySelector(sel);
                        if (el) intentos.push(el);
                    });
                    const headerBtn = sb.querySelector("button");
                    if (headerBtn) intentos.push(headerBtn);
                }

                const toggle = doc.querySelector(
                    '[data-testid="stSidebarCollapsedControl"] button, '
                    + '.stSidebarCollapsedControl button'
                );
                if (toggle) intentos.push(toggle);

                for (const el of intentos) {
                    try {
                        el.click();
                        if (!sidebarAbierta()) return true;
                    } catch (e) {}
                }

                try {
                    doc.dispatchEvent(new KeyboardEvent("keydown", {
                        key: "Escape", code: "Escape", bubbles: true,
                    }));
                } catch (e) {}
                return !sidebarAbierta();
            };

            function programarCierreSidebar() {
                if (!esMovil()) return;
                [80, 220, 450, 800].forEach((ms) => {
                    setTimeout(w.__erpColapsarSidebarMobil, ms);
                });
            }

            function esMenuSidebar(el) {
                return !!el.closest(
                    '[data-testid="stSidebar"] [data-testid="stRadio"] label, '
                    + '[data-testid="stSidebar"] [data-testid="stRadio"] input, '
                    + '[data-testid="stSidebar"] [data-testid="stRadio"] [role="radio"]'
                );
            }

            if (!w.__erpSidebarMobInit) {
                w.__erpSidebarMobInit = true;
                doc.addEventListener("change", (ev) => {
                    if (!esMovil()) return;
                    if (ev.target && ev.target.closest('[data-testid="stSidebar"] [data-testid="stRadio"]')) {
                        programarCierreSidebar();
                    }
                }, true);
                doc.addEventListener("click", (ev) => {
                    if (!esMovil()) return;
                    if (esMenuSidebar(ev.target)) {
                        programarCierreSidebar();
                    }
                }, true);
            }
        })();
        </script>
        """,
        height=0,
        width=0,
    )


def inyectar_modo_solo_lectura():
    if not es_solo_lectura():
        components.html(
            """
            <script>
            (function () {
                const doc = window.parent.document;
                doc.body.classList.remove("erp-solo-lectura");
                const st = doc.getElementById("erp-solo-lectura-style");
                if (st) st.remove();
                if (window.parent.__erpRoObs) {
                    window.parent.__erpRoObs.disconnect();
                    window.parent.__erpRoObs = null;
                }
            })();
            </script>
            """,
            height=0,
            width=0,
        )
        return
    st.info(
        "👁️ **Modo solo lectura** — puede consultar y filtrar en pantalla; "
        "no puede registrar, modificar ni exportar PDF."
    )

def aplicar_tema_modulo(modulo_key):
    tema = TEMAS_MODULO.get(modulo_key, TEMAS_MODULO["DASHBOARD"])
    st.markdown(
        f"""<style>
        :root {{
            --modulo-accent: {tema['color']};
            --modulo-claro: {tema['claro']};
        }}
        </style>""",
        unsafe_allow_html=True,
    )

def encabezado_modulo(modulo_key, titulo, subtitulo=None, con_logo=False):
    st.session_state["modulo_activo"] = modulo_key
    aplicar_tema_modulo(modulo_key)
    tema = TEMAS_MODULO.get(modulo_key, {})
    color = tema.get("color", "#1B5E20")
    claro = tema.get("claro", "#E8F5E9")
    if subtitulo is None:
        subtitulo = tema.get("sub", "")

    if con_logo:
        lg = logo_img_html(240, "logo-modulo")
        if lg:
            st.markdown(lg, unsafe_allow_html=True)

    st.markdown(
        f'<hr style="height:5px;border:none;border-radius:6px;margin:0 0 1rem;'
        f'background:linear-gradient(90deg,{color},{claro});">',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<p style="text-align:center;font-size:2rem;font-weight:800;color:{color};'
        f'margin:0.2rem 0 0.35rem;line-height:1.2;">{titulo}</p>',
        unsafe_allow_html=True,
    )
    if subtitulo:
        st.markdown(
            f'<p style="text-align:center;color:#5F6B7A;font-size:0.95rem;margin:0 0 0.5rem;">{subtitulo}</p>',
            unsafe_allow_html=True,
        )
    st.markdown(
        f'<p style="text-align:center;margin:0.2rem 0 1rem;">'
        f'<span class="modulo-badge">{modulo_key.upper()}</span></p>',
        unsafe_allow_html=True,
    )

def reset_liquidacion_mes():
    """Marca liquidación para limpiar al inicio del próximo run (antes de widgets)."""
    st.session_state["_reset_liquidacion_mes"] = True

def _aplicar_reset_liquidacion_mes():
    if not st.session_state.pop("_reset_liquidacion_mes", False):
        return
    st.session_state["rhm_liq"] = 0.0
    st.session_state["rhm_prev"] = 0.0
    st.session_state["rhm_l"] = False

def _mes_rrhh_norm(m):
    try:
        return f"{int(m):02d}"
    except (TypeError, ValueError):
        return str(m).strip().zfill(2)

def _periodo_rrhh_orden(mes, anio):
    return int(anio) * 100 + int(_mes_rrhh_norm(mes))

def _primera_cuota_date_default(ficha_act=None):
    h = hora_chile().date()
    if ficha_act and len(ficha_act) > 6 and ficha_act[5] and ficha_act[6]:
        try:
            return datetime(int(ficha_act[6]), int(_mes_rrhh_norm(ficha_act[5])), 1).date()
        except (TypeError, ValueError):
            pass
    return datetime(h.year, h.month, 1).date()

def _mes_anio_desde_fecha(fecha):
    return _mes_rrhh_norm(fecha.month), int(fecha.year)

def _prestamo_aplica_descuento_mes(info, mes, anio):
    pm, pa = info.get("primera_cuota_mes"), info.get("primera_cuota_anio")
    if not pm or not pa:
        return True
    return _periodo_rrhh_orden(mes, anio) >= _periodo_rrhh_orden(pm, pa)

def _total_descontado_prestamo(conn, trabajador_id):
    return float(
        conn.execute(
            "SELECT COALESCE(SUM(descuento_prestamo), 0) FROM remuneracion_mes WHERE trabajador_id=?",
            (trabajador_id,),
        ).fetchone()[0] or 0
    )

def _info_prestamo_worker(conn, trabajador_id):
    ficha = conn.execute(
        """SELECT monto_prestamo, cuotas_prestamo, primera_cuota_mes, primera_cuota_anio
           FROM remuneraciones_fichas WHERE trabajador_id=?""",
        (trabajador_id,),
    ).fetchone()
    if not ficha or not ficha[0]:
        return {
            "monto": 0.0, "cuotas": 0, "cuota_ref": 0.0, "descontado": 0.0, "saldo": 0.0,
            "primera_cuota_mes": None, "primera_cuota_anio": None,
        }
    monto, cuotas = float(ficha[0]), int(ficha[1] or 0)
    pm = _mes_rrhh_norm(ficha[2]) if ficha[2] else None
    pa = int(ficha[3]) if ficha[3] else None
    cuota_ref = (monto / cuotas) if cuotas > 0 else 0.0
    descontado = _total_descontado_prestamo(conn, trabajador_id)
    saldo = max(0.0, monto - descontado)
    return {
        "monto": monto, "cuotas": cuotas, "cuota_ref": cuota_ref,
        "descontado": descontado, "saldo": saldo,
        "primera_cuota_mes": pm, "primera_cuota_anio": pa,
    }

def _actualizar_cuotas_pagadas_desde_descuentos(conn, trabajador_id):
    if es_solo_lectura():
        return
    info = _info_prestamo_worker(conn, trabajador_id)
    if info["cuotas"] <= 0 or info["cuota_ref"] <= 0:
        return
    if info["saldo"] <= 0.01:
        cuotas_calc = info["cuotas"]
    else:
        cuotas_calc = min(info["cuotas"], int(round(info["descontado"] / info["cuota_ref"])))
    conn.execute(
        "UPDATE remuneraciones_fichas SET cuotas_pagadas=? WHERE trabajador_id=?",
        (cuotas_calc, trabajador_id),
    )

def _migrar_remuneracion_mes_inicial(conn):
    """Migra datos legacy de provision_liquido_mes a remuneracion_mes."""
    rows = conn.execute(
        "SELECT trabajador_id, mes, anio, liquido_provision FROM provision_liquido_mes"
    ).fetchall()
    for tid, mes, anio, liq in rows:
        mes_n = _mes_rrhh_norm(mes)
        conn.execute(
            """INSERT OR IGNORE INTO remuneracion_mes
               (trabajador_id, mes, anio, liquido_ganado, suple, descuento_prestamo, liquido_provision)
               VALUES (?, ?, ?, 0, 0, 0, ?)""",
            (tid, mes_n, int(anio), float(liq or 0)),
        )

def _migrar_descuento_prestamo_historico(conn):
    """Legacy: ya no aplica descuentos en pagos_rrhh; préstamos viven en remuneracion_mes."""
    pass

def _saldo_disponible_descuento_remuneracion(conn, trabajador_id, mes, anio):
    info = _info_prestamo_worker(conn, trabajador_id)
    mes_n = _mes_rrhh_norm(mes)
    row = conn.execute(
        """SELECT COALESCE(descuento_prestamo, 0) FROM remuneracion_mes
           WHERE trabajador_id=? AND mes=? AND anio=?""",
        (trabajador_id, mes_n, int(anio)),
    ).fetchone()
    desc_anterior = float(row[0] or 0) if row else 0.0
    return info["saldo"] + desc_anterior

def _descuento_cuota_sugerida(conn, trabajador_id, mes, anio, desc_guardado=None):
    """Cuota referencia si hay saldo; respeta descuento ya guardado en el mes."""
    if desc_guardado is not None and float(desc_guardado or 0) > 0:
        return float(desc_guardado)
    info = _info_prestamo_worker(conn, trabajador_id)
    if info["cuota_ref"] <= 0:
        return 0.0
    if not _prestamo_aplica_descuento_mes(info, mes, anio):
        return 0.0
    saldo_disp = _saldo_disponible_descuento_remuneracion(conn, trabajador_id, mes, anio)
    if saldo_disp <= 0:
        return 0.0
    return min(info["cuota_ref"], saldo_disp)


def _fila_totales_planilla_rrhh(df):
    tot = {"TRABAJADOR": "TOTAL"}
    for col in df.columns:
        if col == "TRABAJADOR":
            continue
        tot[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).sum()
    return pd.DataFrame([tot])


def _mostrar_totales_planilla_rrhh(df):
    df_tot = _fila_totales_planilla_rrhh(df)
    st.dataframe(
        df_tot.style.format({
            c: _fmt_styler_peso for c in df_tot.columns if c != "TRABAJADOR"
        }),
        use_container_width=True,
        hide_index=True,
    )


def _guardar_remuneracion_mes(conn, trabajador_id, mes, anio, liquido_ganado, suple, descuento_prestamo):
    if es_solo_lectura():
        return False, "Modo solo lectura: no puede modificar remuneraciones."
    mes_n = _mes_rrhh_norm(mes)
    ganado = float(liquido_ganado or 0)
    suple_v = float(suple or 0)
    desc = float(descuento_prestamo or 0)
    saldo_disp = _saldo_disponible_descuento_remuneracion(conn, trabajador_id, mes_n, anio)
    if desc > saldo_disp + 0.5:
        return False, (
            f"Descuento préstamo (${f_puntos(desc)}) supera saldo pendiente "
            f"(${f_puntos(saldo_disp)})."
        )
    neto = max(0.0, ganado - suple_v - desc)
    conn.execute(
        """INSERT INTO remuneracion_mes
           (trabajador_id, mes, anio, liquido_ganado, suple, descuento_prestamo, liquido_provision)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(trabajador_id, mes, anio) DO UPDATE SET
           liquido_ganado=excluded.liquido_ganado,
           suple=excluded.suple,
           descuento_prestamo=excluded.descuento_prestamo,
           liquido_provision=excluded.liquido_provision""",
        (trabajador_id, mes_n, int(anio), ganado, suple_v, desc, neto),
    )
    _actualizar_cuotas_pagadas_desde_descuentos(conn, trabajador_id)
    return True, neto

def _upsert_pago_rrhh(conn, trabajador_id, mes, anio, liquido, leyes, licencia):
    if es_solo_lectura():
        return False, "Modo solo lectura: no puede registrar liquidaciones."
    mes_n = _mes_rrhh_norm(mes)
    if licencia:
        liquido = leyes = 0.0
    liquido = float(liquido or 0)
    leyes = float(leyes or 0)
    tot = liquido + leyes
    existing = conn.execute(
        """SELECT id FROM pagos_rrhh
           WHERE trabajador_id=? AND printf('%02d', CAST(mes AS INTEGER))=? AND anio=?""",
        (trabajador_id, mes_n, int(anio)),
    ).fetchone()
    if existing:
        conn.execute(
            """UPDATE pagos_rrhh
               SET liquido=?, leyes_sociales=?, costo_empresa=?, fecha_registro=?
               WHERE id=?""",
            (liquido, leyes, tot, str(hoy), existing[0]),
        )
    else:
        conn.execute(
            """INSERT INTO pagos_rrhh
               (trabajador_id, mes, anio, liquido, leyes_sociales, costo_empresa, descuento_prestamo, tipo, fecha_registro)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (trabajador_id, mes_n, int(anio), liquido, leyes, tot, 0.0, "Sueldo", str(hoy)),
        )
    return True, None

def _imputar_costos_rrhh(conn, trabajador_id, mes, anio, total):
    if es_solo_lectura():
        return
    if total <= 0:
        return
    prorrateo_rrhh = cargar_prorrateo_cc(conn)
    mes_n = _mes_rrhh_norm(mes)
    try:
        conn.execute(
            "DELETE FROM costos_mano_obra WHERE trabajador_id=? AND mes=? AND anio=?",
            (trabajador_id, mes_n, int(anio)),
        )
    except Exception:
        pass
    for cc_interno, porcentaje in prorrateo_rrhh.items():
        parte_costo = total * float(porcentaje or 0)
        if parte_costo > 0:
            try:
                conn.execute(
                    """INSERT INTO costos_mano_obra (trabajador_id, centro_costo, monto, mes, anio, fecha_registro)
                       VALUES (?,?,?,?,?,?)""",
                    (trabajador_id, cc_interno, parte_costo, mes_n, int(anio), str(hoy)),
                )
            except Exception:
                pass

def _rrhh_sincronizar_mes_calendario():
    """Al cambiar mes/año calendario: líquido en cero; persisten solo cuotas de préstamo en ficha."""
    fecha = hora_chile()
    mes_cal = fecha.strftime("%m")
    anio_cal = int(fecha.year)
    clave = f"{mes_cal}-{anio_cal}"
    if st.session_state.get("rrhh_mes_calendario") == clave:
        return
    st.session_state["rrhh_mes_calendario"] = clave
    st.session_state["rhm_m"] = mes_cal
    st.session_state["rhm_a"] = anio_cal
    if "rh_prov_m" not in st.session_state:
        st.session_state["rh_prov_m"] = mes_cal
    if "rh_prov_a" not in st.session_state:
        st.session_state["rh_prov_a"] = anio_cal
    reset_liquidacion_mes()

def _siguiente_folio_contratista(conn, fecha):
    prefijo = f"CONTR-{str(fecha).replace('-', '')}-"
    n = conn.execute(
        "SELECT COUNT(*) FROM facturas WHERE nro_documento LIKE ? AND nro_documento NOT LIKE '%_P'",
        (prefijo + "%",),
    ).fetchone()[0]
    return f"{prefijo}{int(n) + 1:02d}"

def _registrar_servicio_contratista(
    conn, contratista_id, proveedor, nro_doc, fecha, fv, monto_bruto, concepto, selcc, razon_social, imputar_bruto=True,
):
    tipo_gv = "Gasto Operacional"
    tg = "Contratistas"
    imp = float(monto_bruto) if imputar_bruto else float(monto_bruto) / 1.19
    reparto, err_cc = _reparto_por_cc(conn, imp, selcc)
    if err_cc:
        return False, err_cc
    conn.execute(
        """INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, concepto, razon_social, tipo_gasto, contratista_id)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (nro_doc, proveedor, str(fecha), str(fv), monto_bruto, tipo_gv, concepto.strip(), razon_social, tg, contratista_id),
    )
    for c, parte in reparto:
        conn.execute(
            """INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, centro_costo, monto_imputado, concepto, razon_social, tipo_gasto, contratista_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (nro_doc + "_P", proveedor, str(fecha), str(fv), 0, tipo_gv, c.upper(), parte, concepto.strip(), razon_social, tg, contratista_id),
        )
    return True, None

def boton_pdf(etiqueta, blob, archivo, key):
    etiqueta = etiqueta if "📥" in etiqueta else f"📥 {etiqueta}"
    st.markdown(
        '<hr style="border:none;border-top:1px dashed #DDE5DF;margin:0.8rem 0 0.45rem;">',
        unsafe_allow_html=True,
    )
    _, col_pdf = st.columns([4, 1])
    with col_pdf:
        if es_solo_lectura():
            st.button(f"{etiqueta} — no disponible", disabled=True, key=f"{key}_ro")
        elif blob:
            boton_descarga_pdf(blob, archivo, key, etiqueta)
        else:
            st.button(f"{etiqueta} — sin datos", disabled=True, key=f"{key}_off")

def pdf_globalgap(df, seccion, especie, key, detalle=None, estilo_celda_fn=None):
    pref = "cerezos" if especie == "Cerezos" else "ciruelos"
    titulo = f"GLOBALGAP — {especie.upper()} — {seccion}"
    if detalle:
        titulo = f"{titulo} ({detalle})"
    slug = seccion.lower().replace(" ", "_").replace("/", "_")
    archivo = f"globalgap_{pref}_{slug}.pdf"
    if df is None or (hasattr(df, "empty") and df.empty):
        boton_pdf(f"PDF {seccion}", None, archivo, key=f"gap_{pref}_{key}")
        return
    df_pdf = df.copy()
    for col in ("id",):
        if col in df_pdf.columns:
            df_pdf = df_pdf.drop(columns=[col])
    boton_pdf(
        f"PDF {seccion}",
        generar_pdf_blob(df_pdf, titulo, incluir_precios=False, estilo_celda_fn=estilo_celda_fn),
        archivo,
        key=f"gap_{pref}_{key}",
    )

# =============================================================================
# 4. MÓDULOS DEL SISTEMA
# =============================================================================

def render_kpi_dashboard(deuda_total, meses_anteriores, vencidas_count, pendientes_count, petroleo_neto):
    st.markdown(
        f"""
        <div class="dashboard-kpi-grid">
            <div class="dashboard-kpi-card">
                <div class="dashboard-kpi-label">💰 DEUDA TOTAL</div>
                <div class="dashboard-kpi-value">${f_puntos(deuda_total)}</div>
            </div>
            <div class="dashboard-kpi-card">
                <div class="dashboard-kpi-label">🔥 MESES ANTERIORES</div>
                <div class="dashboard-kpi-value critico">${f_puntos(meses_anteriores)}</div>
            </div>
            <div class="dashboard-kpi-card">
                <div class="dashboard-kpi-label">⚠️ VENCIDAS</div>
                <div class="dashboard-kpi-value alerta">{vencidas_count} docs</div>
            </div>
            <div class="dashboard-kpi-card">
                <div class="dashboard-kpi-label">📄 PENDIENTES</div>
                <div class="dashboard-kpi-value">{pendientes_count}</div>
            </div>
            <div class="dashboard-kpi-card">
                <div class="dashboard-kpi-label">⛽ PETRÓLEO NETO</div>
                <div class="dashboard-kpi-value">{f_decimal(petroleo_neto)} L</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def _build_dashboard_gastos_cc_df(conn, dfr_base):
    temporada, _, _ = _temporada_vigente_costos()
    valor_dolar = obtener_valor_dolar()
    filas = []
    total_gasto = 0.0
    total_ppto = 0.0
    for _, row in dfr_base.iterrows():
        cc = str(row["Cuartel"])
        gasto = float(row["Total"] or 0)
        ppto = _obtener_ppto_temporada(conn, temporada, cc)
        kg = _obtener_kg_estimado_temporada(conn, temporada, cc)
        avance = (gasto / ppto * 100) if ppto > 0 else None
        usd_kg = _costo_usd_por_kg(gasto, kg, valor_dolar)
        filas.append({
            "Cuartel": cc,
            "Total Acumulado": gasto,
            "Avance %": avance,
            "USD/kg": usd_kg,
        })
        total_gasto += gasto
        if ppto > 0:
            total_ppto += ppto
    filas.append({
        "Cuartel": "TOTAL GENERAL",
        "Total Acumulado": total_gasto,
        "Avance %": (total_gasto / total_ppto * 100) if total_ppto > 0 else None,
        "USD/kg": None,
    })
    return pd.DataFrame(filas)

def _fmt_dashboard_avance_pct(valor):
    if valor is None:
        return "—"
    return f"{float(valor):.1f}%"

def _render_dashboard_cc_y_pagos(df_gastos_cc, df_facturas_pendientes):
    filas_cc = [
        '<div class="dashboard-cc-header">'
        '<span>Cuartel</span><span>Total</span><span>Avance</span><span>USD/kg</span>'
        '</div>'
    ]
    for _, row in df_gastos_cc.iterrows():
        cuartel = str(row["Cuartel"])
        monto = row["Total Acumulado"]
        avance_raw = row.get("Avance %")
        avance = _fmt_dashboard_avance_pct(avance_raw)
        usd_kg = _fmt_usd(row["USD/kg"]) if row.get("USD/kg") is not None else "—"
        estilo_avance = _badge_estilo_avance_costos(avance_raw)
        estilo_usd = _badge_estilo_avance_costos(avance_raw) if row.get("USD/kg") is not None else ""
        cls = "total" if cuartel.upper() == "TOTAL GENERAL" else ""
        filas_cc.append(
            f'<div class="dashboard-fila-monto dashboard-fila-cc {cls}">'
            f'<span class="etiqueta">{cuartel}</span>'
            f'<span class="monto">${f_puntos(monto)}</span>'
            f'<span class="metrica avance badge-costos" style="{estilo_avance}">{avance}</span>'
            f'<span class="metrica usd-kg badge-costos" style="{estilo_usd}">{usd_kg}</span></div>'
        )
    panel_cc = (
        '<div class="dashboard-dual-panel">'
        '<div class="dashboard-dual-title">📊 Gastos por cuartel</div>'
        + "".join(filas_cc)
        + "</div>"
    )

    filas_pago = []
    from dateutil.relativedelta import relativedelta

    base_mes = hoy.replace(day=1)
    n_meses = 6
    if not df_facturas_pendientes.empty:
        fv_max = pd.to_datetime(df_facturas_pendientes["fecha_vencimiento"], errors="coerce").max()
        if pd.notna(fv_max):
            ultimo = fv_max.to_pydatetime().replace(day=1)
            diff = (ultimo.year - base_mes.year) * 12 + (ultimo.month - base_mes.month) + 1
            n_meses = max(n_meses, diff)
    for i in range(n_meses):
        fp = base_mes + relativedelta(months=i)
        if df_facturas_pendientes.empty:
            totalm = 0
        else:
            fv = pd.to_datetime(df_facturas_pendientes["fecha_vencimiento"])
            totalm = df_facturas_pendientes[
                (fv.dt.month == fp.month) & (fv.dt.year == fp.year)
            ]["saldo"].sum()
        cls_p = "pago pago-vacio" if totalm <= 0 else "pago"
        filas_pago.append(
            f'<div class="dashboard-fila-monto {cls_p}">'
            f'<span class="etiqueta">{fp.strftime("%B %Y").upper()}</span>'
            f'<span class="monto">${f_puntos(totalm)}</span></div>'
        )
    panel_pagos = (
        '<div class="dashboard-dual-panel">'
        '<div class="dashboard-dual-title">📅 Proyección pagos</div>'
        + "".join(filas_pago)
        + "</div>"
    )

    c_izq, c_der = st.columns(2)
    with c_izq:
        st.markdown(panel_cc, unsafe_allow_html=True)
    with c_der:
        st.markdown(panel_pagos, unsafe_allow_html=True)

def modulo_dashboard():
    inyectar_fondo_dashboard()
    encabezado_dashboard_con_clima()
    conn = conectar_db()
    
    fecha_sistema = hora_chile()
    mes_act = fecha_sistema.strftime('%m')
    anio_act = fecha_sistema.year

    try:
        t_activos = pd.read_sql_query("SELECT id FROM personal WHERE estado='Activo'", conn)
        imputados = pd.read_sql_query(
            f"""SELECT DISTINCT trabajador_id FROM pagos_rrhh
                WHERE printf('%02d', CAST(mes AS INTEGER))='{mes_act}' AND anio={anio_act}""",
            conn,
        )
        faltan = len(t_activos) - len(imputados)
        if faltan > 0 and hora_chile().day >= 28:
            st.markdown(f'<div class="alert-roja">⚠️ RECORDATORIO: Faltan {faltan} trabajadores por imputar sueldos este mes.</div>', unsafe_allow_html=True)
    except:
        pass

    ind = obtener_indicadores()
    if ind.get("offline"):
        st.markdown(
            '<div class="banner-econ">📈 INDICADORES: sin conexión a fuente externa</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="banner-econ">📈 INDICADORES: UF: {ind["uf"]} | UTM: {ind["utm"]} | '
            f'DÓLAR: {ind["dolar"]} | EURO: {ind["euro"]}</div>',
            unsafe_allow_html=True,
        )
    
    df_f = _cargar_facturas_pendientes_saldo(conn)
    df_p_c = pd.read_sql_query("SELECT SUM(litros) as l FROM petroleo WHERE tipo='Carga' OR (tipo='Ajuste Manual' AND litros > 0)", conn)
    df_p_s = pd.read_sql_query("SELECT SUM(litros) as l FROM petroleo WHERE tipo='Salida' OR (tipo='Ajuste Manual' AND litros < 0)", conn)
    saldo_pet = (df_p_c['l'].fillna(0).iloc[0]) - abs(df_p_s['l'].fillna(0).iloc[0])
    
    pdia = hoy.replace(day=1)
    dcrit = df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < pdia]['saldo'].sum()
    vcount = len(df_f[pd.to_datetime(df_f['fecha_vencimiento']).dt.date < hoy])
    render_kpi_dashboard(
        df_f["saldo"].sum(),
        dcrit,
        vcount,
        len(df_f),
        saldo_pet,
    )

    st.divider()
    dfr_base, _ = _armar_dataframe_costos_dashboard(conn, CUARTELES_OFICIALES, cargar_prorrateo_cc(conn))
    if not dfr_base.empty:
        df_gastos = _build_dashboard_gastos_cc_df(conn, dfr_base)
        _render_dashboard_cc_y_pagos(df_gastos, df_f)

    _render_widget_usuarios_dashboard_al_final(conn)
    conn.close()

def modulo_petroleo():
    conn = conectar_db()
    temp_act = next(
        (t for t in TEMPORADAS_COSTOS if t[1] <= hoy <= t[2]),
        TEMPORADAS_COSTOS[0],
    )
    col_pet_t, col_pet_w = st.columns([5, 2], gap="small")
    with col_pet_t:
        encabezado_modulo("Petróleo", "⛽ GESTIÓN DE PETRÓLEO")
        try:
            df_p_c = pd.read_sql_query("SELECT SUM(litros) as l FROM petroleo WHERE tipo='Carga' OR (tipo='Ajuste Manual' AND litros > 0)", conn)
            df_p_s = pd.read_sql_query("SELECT SUM(litros) as l FROM petroleo WHERE tipo='Salida' OR (tipo='Ajuste Manual' AND litros < 0)", conn)
            tot_cargas = float(df_p_c["l"].fillna(0).iloc[0])
            tot_salidas = abs(float(df_p_s["l"].fillna(0).iloc[0]))
            saldo_actual = tot_cargas - tot_salidas
            st.markdown(f'<div class="saldo-banner">🛢️ SALDO ACTUAL EN TANQUE: {f_decimal(saldo_actual)} LITROS</div>', unsafe_allow_html=True)
            st.caption(
                f"Cargas al estanque: **{f_decimal(tot_cargas)} L** · "
                f"Despachos acumulados: **{f_decimal(tot_salidas)} L** · "
                f"La dona muestra solo despachos de la **temporada** ({temp_act[0]})."
            )
        except:
            st.markdown('<div class="saldo-banner">🛢️ SALDO ACTUAL EN TANQUE: 0 LITROS</div>', unsafe_allow_html=True)
            saldo_actual = 0
    with col_pet_w:
        render_widget_petroleo_maquinaria(
            conn, temp_act[0], str(temp_act[1]), str(temp_act[2]), ref_fecha=hoy
        )

    _pet_secc = ["📥 CARGA", "🚜 SALIDA", "📊 HISTORIAL", "📋 PLANILLA MAESTRA"]
    sec_pet = nav_seccion(_pet_secc, "pet_nav", "Sección")

    if sec_pet == _pet_secc[0]:
        with st.form("p_c", clear_on_submit=True):
            l = st.number_input("Litros Carga", 0.0, key="pet_c_l")
            mt = st.number_input("Total Bruto ($)", 0.0, key="pet_c_m")
            f = st.date_input("Fecha", hoy, key="pet_c_f")
            if st.form_submit_button("REGISTRAR CARGA"):
                if l > 0 and mt > 0:
                    conn.execute("INSERT INTO petroleo (tipo, litros, monto_total_compra, fecha) VALUES (?,?,?,?)", ("Carga", l, mt, str(f)))
                    _recalcular_imputacion_salidas_petroleo(conn)
                    conn.commit()
                    registrar_accion("PETROLEO", f"Carga {l}L")
                    st.success("✅ Carga de estanque guardada con éxito.")
                    st.rerun()
                    
    elif sec_pet == _pet_secc[1]:
        pmp_actual = _petroleo_pmp_neto(conn)
        st.markdown(
            f"<div style='background:#E3F2FD;border-left:5px solid #1565C0;padding:10px 14px;border-radius:6px;margin-bottom:12px;'>"
            f"<b>PMP neto estanque:</b> ${f_puntos(pmp_actual)}/L &nbsp;|&nbsp; "
            f"Imputación por cuartel = litros × PMP neto (bruto ÷ 1,19 − ${IMPUESTO_ESPECIFICO_LITRO}/L imp. específico)</div>",
            unsafe_allow_html=True,
        )
        with st.form("p_s", clear_on_submit=True):
            ls = st.number_input("Litros Salida", 0.0, key="pet_s_l")
            fs = st.date_input("Fecha", hoy, key="pet_s_f")
            v = render_select_maquinaria(
                conn,
                key="pet_s_v",
                label="Equipo / Vehículo",
                tipos=TIPOS_MAQUINARIA_PETROLEO,
            )
            r = st.text_input("Responsable Operación", key="pet_s_r")
            ccs = [cc for cc in CENTROS_COSTO if st.checkbox(cc, key=f"p_s_cc_{cc}")]
            if st.form_submit_button("DESPACHAR PETRÓLEO"):
                try:
                    pmp = _petroleo_pmp_neto(conn)
                except Exception:
                    pmp = 0
                if not v:
                    st.error("❌ Seleccione el equipo o vehículo desde la maestra de maquinaria.")
                elif not r.strip():
                    st.error("❌ Ingrese el responsable de la operación.")
                elif ccs and ls > 0:
                    reparto, err_cc = _reparto_por_cc(conn, ls, ccs)
                    if err_cc:
                        st.error(f"❌ {err_cc}")
                    else:
                        for c, litros_cc in reparto:
                            conn.execute(
                                "INSERT INTO petroleo (tipo, litros, vehiculo, responsable, centro_costo, fecha, valor_imputado) VALUES (?,?,?,?,?,?,?)",
                                ("Salida", litros_cc, v, r, c.upper(), str(fs), litros_cc * pmp),
                            )
                        conn.commit()
                        registrar_accion("PETROLEO", f"Salida {ls}L")
                        st.success(f"✅ Despacho registrado. PMP neto aplicado: ${f_puntos(pmp)}/L")
                        st.rerun()
                    
    elif sec_pet == _pet_secc[2]:
        try:
            f_min_q = conn.execute("SELECT MIN(fecha) FROM petroleo").fetchone()[0]
            f_min_p = pd.to_datetime(f_min_q).date() if f_min_q else hoy - timedelta(days=365)
        except:
            f_min_p = hoy - timedelta(days=365)
        
        c1, c2 = st.columns(2)
        fi_p = c1.date_input("Desde", f_min_p, key="p_f_1")
        ff_p = c2.date_input("Hasta", hoy, key="p_f_2")
        
        try:
            dfp = pd.read_sql_query(
                f"""SELECT id, fecha, tipo, litros, vehiculo, responsable, centro_costo,
                           monto_total_compra, valor_imputado
                    FROM petroleo WHERE fecha BETWEEN '{fi_p}' AND '{ff_p}'
                    ORDER BY fecha ASC, id ASC""",
                conn,
            )
            dfp = enriquecer_columna_maquinaria(conn, dfp, "vehiculo")
            st.markdown("##### Movimientos registrados")
            if dfp.empty:
                st.info("No hay movimientos en el período seleccionado.")
            else:
                eventos = _petroleo_eventos_historial(dfp)
                col_res, col_pdf = st.columns([2.8, 1.2])
                with col_res:
                    n_sal = sum(1 for k, _, _ in eventos if k == "salida")
                    n_car = sum(1 for k, _, _ in eventos if k == "carga")
                    st.markdown(
                        f"<div style='color:#37474F;font-size:0.92rem;padding-top:0.4rem;'>"
                        f"<b>{len(eventos)}</b> movimiento(s) · <b>{n_car}</b> entrada(s) · <b>{n_sal}</b> salida(s) · "
                        f"más reciente arriba (N° {len(eventos)})</div>",
                        unsafe_allow_html=True,
                    )
                with col_pdf:
                    blob_pet = generar_pdf_petroleo_historial(dfp, saldo_petroleo=saldo_actual)
                    if blob_pet:
                        boton_descarga_pdf(
                            blob_pet, "petroleo.pdf", "p_pdf", "PDF HISTORIAL PETRÓLEO",
                            use_container_width=True,
                        )
                st.markdown("<div style='margin-bottom:0.6rem;'></div>", unsafe_allow_html=True)
                render_historial_petroleo_agrupado(dfp, mostrar_resumen=False)
        except Exception as e:
            st.error(f"Error al cargar historial de petróleo: {e}")
        
        # --- INJERTO MAESTRO: AJUSTE DE REGISTROS DUPLICADOS ---
        if st.session_state.get('email') == 'osvaldolira@laconcepcion.cl':
            st.markdown("---")
            st.subheader("🔧 Panel de Ajuste Maestro (Administrador)")
            id_a_eliminar = st.number_input("Ingrese el ID del registro de petróleo duplicado:", min_value=1, step=1, key="id_del_petroleo")
            
            if st.button("🗑️ Eliminar Registro y Recalcular Estanque", type="primary"):
                try:
                    conn.execute("DELETE FROM petroleo WHERE id = ?", (id_a_eliminar,))
                    conn.commit()
                    st.success(f"¡Registro ID {id_a_eliminar} eliminado con éxito! El estanque se ha recalculado.")
                    st.rerun()
                except Exception as ex:
                    st.error(f"No se pudo eliminar el registro: {ex}")

    elif sec_pet == _pet_secc[3]:
        st.markdown("##### Planilla maestra del estanque")
        st.caption(
            "Imprima y deje en el estanque para **anotar salidas a mano**. "
            "Columnas: fecha, litros, huerto, maquinaria y quien retira."
        )
        f_plan_def, lts_plan_def = defaults_planilla_petroleo(conn, hoy)
        cp1, cp2 = st.columns(2)
        f_plan = cp1.date_input("Fecha de carga", f_plan_def, key="pet_plan_fecha")
        l_plan = cp2.number_input(
            "Carga (Lts)",
            min_value=0.0,
            value=float(lts_plan_def),
            step=1.0,
            key="pet_plan_litros",
        )
        blob_plan = generar_pdf_planilla_maestra_petroleo(
            f_plan, l_plan, logo_path=ruta_logo_pdf(), empresa=NOMBRE_ERP or "ERP Agrícola",
        )
        if blob_plan:
            boton_descarga_pdf(
                blob_plan,
                "planilla_maestra_petroleo.pdf",
                "pet_plan_pdf",
                "IMPRIMIR PLANILLA MAESTRA",
            )
            st.caption("Formato carta · una página con recuadros para completar en terreno.")
        else:
            st.error("No se pudo generar el PDF. Intente de nuevo o avise al administrador.")

    conn.close()

_SQL_ETIQUETA_TIPO_COMPRA = """
    CASE
        WHEN tipo IN ('Gasto Operacional', 'Gasto Vario') THEN 'Gasto Operacional'
        WHEN tipo IN ('Gasto Operacional Petróleo', 'Gasto Vario Petróleo') THEN 'Gasto Operacional Petróleo'
        WHEN TRIM(COALESCE(concepto, '')) LIKE '[%' THEN 'Insumos'
        ELSE COALESCE(NULLIF(TRIM(tipo), ''), 'Factura')
    END
"""

def _migrar_tipo_gasto_operacional(conn):
    if _conn_es_solo_lectura(conn) or _sesion_requiere_solo_lectura():
        return
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS schema_meta (clave TEXT PRIMARY KEY, valor TEXT)")
    if cur.execute("SELECT 1 FROM schema_meta WHERE clave='gasto_operacional_tipo_v1'").fetchone():
        return
    cur.execute("UPDATE facturas SET tipo='Gasto Operacional' WHERE tipo='Gasto Vario'")
    cur.execute(
        "UPDATE facturas SET tipo='Gasto Operacional Petróleo' WHERE tipo='Gasto Vario Petróleo'"
    )
    cur.execute("INSERT INTO schema_meta (clave, valor) VALUES ('gasto_operacional_tipo_v1', '1')")
    conn.commit()

def _limpiar_formulario_compras_ingreso(con_razon=False):
    """Reinicia el tab INGRESO tras guardar (Streamlit conserva el estado por key)."""
    st.session_state["comp_nro"] = ""
    st.session_state["comp_prov"] = ""
    st.session_state["comp_fe"] = hoy
    st.session_state["comp_fv"] = hoy
    if con_razon:
        st.session_state["comp_razon"] = RAZONES_SOCIALES_COMPRAS[0]
    for k in (
        "comp_nro_inp", "comp_prov_inp", "comp_fe_inp", "comp_fv_inp", "comp_razon_inp",
        "gv_concepto_det", "gv_tipo_gasto", "gv_5", "gv_6", "gv_razon",
        "gv_pet_concepto", "gv_pet_monto", "gv_litros",
        "comp_insumo_sel", "comp_prod_nuevo", "comp_fam_nuevo", "comp_um_nuevo",
        "comp_cant", "comp_neto", "comp_modo_prod",
    ):
        st.session_state.pop(k, None)
    for cc in CENTROS_COSTO:
        st.session_state.pop(f"gv_cc_{cc}", None)


def modulo_compras():
    encabezado_modulo("Compras", "📦 COMPRAS E HISTORIAL")
    conn = conectar_db()
    familias_prod = listar_familias_producto(conn)
    _comp_secc = ["INGRESO", "HISTORIAL", "CAJA CHICA"]
    sec_comp = nav_seccion(_comp_secc, "comp_nav", "Sección")
    if sec_comp == _comp_secc[0]:
        if es_solo_lectura():
            st.info("👁️ Modo solo lectura: consulte compras en **HISTORIAL** o **CAJA CHICA**.")
        if 'comp_nro' not in st.session_state: st.session_state['comp_nro'] = ""
        if 'comp_prov' not in st.session_state: st.session_state['comp_prov'] = ""
        if 'comp_fe' not in st.session_state: st.session_state['comp_fe'] = hoy
        if 'comp_fv' not in st.session_state: st.session_state['comp_fv'] = hoy
        if 'comp_razon' not in st.session_state: st.session_state['comp_razon'] = RAZONES_SOCIALES_COMPRAS[0]

        from erp_compras_ui import render_selector_modos_ingreso
        es_agro, es_petroleo = render_selector_modos_ingreso(st)

        sin_doc = False
        if not es_agro and not es_petroleo:
            sin_doc = st.checkbox(
                "¿Sin documento oficial? (folio interno)",
                key="gv_sin_doc",
            )

        c1, c2 = st.columns(2)
        if not es_agro and sin_doc:
            nro = c1.text_input(
                "N° Doc",
                value="AUTOGENERADO",
                disabled=True,
                key="comp_nro_inp",
            )
        else:
            nro = c1.text_input(
                "N° Factura / Doc",
                value=st.session_state['comp_nro'],
                key="comp_nro_inp",
            )
        prov = render_select_proveedor(
            conn,
            key="comp_prov_inp",
            label="Proveedor",
            valor_actual=st.session_state.get("comp_prov"),
        )
        idx_razon = RAZONES_SOCIALES_COMPRAS.index(st.session_state['comp_razon']) if st.session_state['comp_razon'] in RAZONES_SOCIALES_COMPRAS else 0
        razon = c1.selectbox("Razón social", RAZONES_SOCIALES_COMPRAS, index=idx_razon, key="comp_razon_inp")
        fe = c2.date_input("Emisión", value=st.session_state['comp_fe'], key="comp_fe_inp")
        fv = c2.date_input("Vence", value=st.session_state['comp_fv'], key="comp_fv_inp")

        st.session_state['comp_nro'] = nro
        st.session_state['comp_prov'] = prov or ""
        st.session_state['comp_fe'] = fe
        st.session_state['comp_fv'] = fv
        st.session_state['comp_razon'] = razon

        st.divider()

        if es_agro:
            st.info("💡 Si el insumo **no existe** en bodega, regístrelo aquí como producto nuevo. La compra creará el stock y el PMP según la factura.")
            modo_prod = st.radio("Tipo de ítem", ["Producto existente", "Producto nuevo"], horizontal=True, key="comp_modo_prod")
            dfi = pd.read_sql_query(
                "SELECT id, producto, familia, COALESCE(unidad_medida, 'kg') as unidad_medida FROM inventario ORDER BY producto",
                conn,
            )

            with st.form("add_item_car_form", clear_on_submit=True):
                if modo_prod == "Producto existente":
                    ps = st.selectbox(
                        "Insumo en bodega",
                        dfi['id'].astype(str) + " - " + dfi['producto'] + " (" + dfi['unidad_medida'] + ")",
                        key="comp_insumo_sel",
                    ) if not dfi.empty else None
                    prod_nombre, prod_familia, prod_um = None, None, None
                else:
                    ps = None
                    prod_nombre = st.text_input("Nombre producto nuevo", key="comp_prod_nuevo")
                    prod_familia = st.selectbox("Familia", familias_prod, key="comp_fam_nuevo")
                    prod_um = st.selectbox(
                        "Unidad de medida",
                        UNIDADES_MEDIDA_INSUMO,
                        index=UNIDADES_MEDIDA_INSUMO.index(DEFAULT_UNIDAD_INSUMO),
                        key="comp_um_nuevo",
                    )
                ct = st.number_input("Cantidad comprada", 0.0, key="comp_cant")
                pr = st.number_input("Neto unitario factura ($)", 0.0, key="comp_neto")
                btn_add = st.form_submit_button("➕ AGREGAR AL CARRO")

            if btn_add:
                if 'car' not in st.session_state:
                    st.session_state['car'] = []
                if ct > 0 and pr > 0:
                    if modo_prod == "Producto existente":
                        if ps:
                            iid = int(ps.split(" - ")[0])
                            um = dfi.loc[dfi['id'] == iid, 'unidad_medida'].iloc[0]
                            st.session_state['car'].append({
                                'id': iid, 'n': ps.split(" - ")[1].rsplit(" (", 1)[0],
                                'c': ct, 'p': pr, 't': ct * pr, 'nuevo': False, 'um': um,
                            })
                            st.rerun()
                        else:
                            st.error("❌ No hay productos en bodega. Use la opción Producto nuevo.")
                    elif prod_nombre and prod_nombre.strip():
                        st.session_state['car'].append({
                            'id': None, 'n': prod_nombre.strip(), 'familia': prod_familia,
                            'c': ct, 'p': pr, 't': ct * pr, 'nuevo': True, 'um': prod_um,
                        })
                        st.rerun()
                    else:
                        st.error("❌ Ingrese el nombre del producto nuevo.")

            if st.session_state.get('car'):
                st.markdown("#### 🛒 Productos en el Carro Actual:")
                car_view = pd.DataFrame(st.session_state['car']).rename(
                    columns={'n': 'Producto', 'c': 'Cantidad', 'um': 'UM', 'p': 'Neto unit. ($)', 't': 'Total neto ($)'}
                )
                st.table(car_view[['Producto', 'Cantidad', 'UM', 'Neto unit. ($)', 'Total neto ($)']])

                if st.button("🗑️ ELIMINAR ÚLTIMO ÍTEM DEL CARRO", key="comp_btn_undo"):
                    if len(st.session_state['car']) > 0:
                        st.session_state['car'].pop()
                        st.toast("🗑️ Último ítem removido del carro", icon="⚠️")
                        st.rerun()

                if st.button("💾 GUARDAR FACTURA COMPLETA", key="comp_btn_save"):
                    if nro.strip() == "" or not (prov or "").strip():
                        st.error("❌ No puedes guardar una factura con el Proveedor o Número en blanco.")
                    else:
                        desglose_lista = [f"{i['c']} {i.get('um', DEFAULT_UNIDAD_INSUMO)} x {i['n']}" for i in st.session_state['car']]
                        string_insumos = "[" + ", ".join(desglose_lista) + "]"

                        total_bruto = pd.DataFrame(st.session_state['car'])['t'].sum() * 1.19
                        conn.execute(
                            "INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, concepto, razon_social) VALUES (?,?,?,?,?,?,?)",
                            (nro, prov, str(fe), str(fv), total_bruto, string_insumos, razon),
                        )

                        for i in st.session_state['car']:
                            if i.get('nuevo') or i.get('id') is None:
                                cur_ins = conn.execute(
                                    "INSERT INTO inventario (producto, familia, stock, precio_medio, unidad_medida) VALUES (?,?,?,?,?)",
                                    (i['n'], i.get('familia', 'OTROS'), i['c'], i['p'], i.get('um', DEFAULT_UNIDAD_INSUMO)),
                                )
                                poblar_ingredientes_inventario(conn, cur_ins.lastrowid)
                            else:
                                cur = conn.execute("SELECT stock, precio_medio FROM inventario WHERE id=?", (i['id'],)).fetchone()
                                npmp = ((cur[0] * cur[1]) + (i['c'] * i['p'])) / (cur[0] + i['c']) if (cur[0] + i['c']) > 0 else i['p']
                                conn.execute(
                                    "UPDATE inventario SET stock = stock + ?, precio_medio = ? WHERE id = ?",
                                    (i['c'], npmp, i['id']),
                                )
                        conn.commit()

                        st.session_state['car'] = []
                        _limpiar_formulario_compras_ingreso(con_razon=True)

                        registrar_accion("COMPRA", nro)
                        st.success("✅ Factura de compra e insumos archivados con éxito.")
                        st.rerun()

        elif es_petroleo:
            st.info(
                "⛽ **Petróleo** — sin cuarteles ni tipo de gasto. "
                "Queda en Tesorería; registre la carga en **Petróleo → Carga**."
            )
            with st.form("gv_petroleo_form", clear_on_submit=True):
                concepto_det = st.text_input("Detalle / Concepto", key="gv_pet_concepto")
                mt = st.number_input(
                    "Total factura ($)",
                    0.0,
                    key="gv_pet_monto",
                    help="Valor total de la factura de combustible.",
                )
                if st.form_submit_button("💾 GUARDAR COMPRA PETRÓLEO"):
                    pg = prov.strip()
                    razon_gv = razon
                    fg1, fg2 = fe, fv
                    if sin_doc:
                        prefijo_dia = f"INT-{str(fg1).replace('-', '')}-"
                        cursor = conn.cursor()
                        cursor.execute(
                            "SELECT nro_documento FROM facturas WHERE nro_documento LIKE ? AND nro_documento NOT LIKE '%_P'",
                            (prefijo_dia + "%",),
                        )
                        existentes = cursor.fetchall()
                        ng_final = f"{prefijo_dia}{len(existentes) + 1:02d}"
                    else:
                        ng_final = nro.strip()
                    if pg == "":
                        st.error("❌ Error: El campo Proveedor es obligatorio.")
                    elif not sin_doc and ng_final == "":
                        st.error("❌ Error: El campo Número de Documento es obligatorio.")
                    elif mt <= 0:
                        st.error("❌ Error: El total de la factura debe ser superior a $0.")
                    else:
                        conn.execute(
                            "INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, concepto, razon_social, tipo_gasto) VALUES (?,?,?,?,?,?,?,?,?)",
                            (ng_final, pg, str(fg1), str(fg2), mt, "Gasto Operacional Petróleo", concepto_det.strip(), razon_gv, "Petróleo"),
                        )
                        conn.commit()
                        registrar_accion("GASTO PETROLEO", ng_final)
                        st.success(
                            f"✅ Compra de petróleo registrada ({ng_final}). "
                            "Queda en Tesorería; cargue el estanque en Petróleo → Carga."
                        )
                        _limpiar_formulario_compras_ingreso(con_razon=True)
                        st.rerun()

        else:
            with st.form("gv_form", clear_on_submit=True):
                concepto_det = st.text_input("Detalle / Concepto del Gasto", key="gv_concepto_det")
                tipo_gasto_gv = st.selectbox(
                    "Tipo de gasto (matriz CC)",
                    TIPOS_GASTO_ALTA,
                    key="gv_tipo_gasto",
                    help="Clasificación para la matriz de costos.",
                )
                st.caption("Centros de costo")
                selcc = []
                for cc in CENTROS_COSTO:
                    if st.checkbox(cc, key=f"gv_cc_{cc}"):
                        selcc.append(cc)
                mt = st.number_input("Bruto ($)", 0.0, key="gv_5")
                iva = st.radio("Imputar Bruto?", ["SI", "NO (NETO)"], key="gv_6")

                if st.form_submit_button("💾 GUARDAR GASTO OPERACIONAL"):
                    pg = prov.strip()
                    razon_gv = razon
                    fg1, fg2 = fe, fv
                    if sin_doc:
                        prefijo_dia = f"INT-{str(fg1).replace('-', '')}-"
                        cursor = conn.cursor()
                        cursor.execute(
                            "SELECT nro_documento FROM facturas WHERE nro_documento LIKE ? AND nro_documento NOT LIKE '%_P'",
                            (prefijo_dia + "%",),
                        )
                        existentes = cursor.fetchall()
                        ng_final = f"{prefijo_dia}{len(existentes) + 1:02d}"
                    else:
                        ng_final = nro.strip()
                    tipo_gv = "Gasto Operacional"
                    if pg == "":
                        st.error("❌ Error: El campo Proveedor es obligatorio.")
                    elif not sin_doc and ng_final == "":
                        st.error("❌ Error: El campo Número de Documento es obligatorio.")
                    elif mt <= 0:
                        st.error("❌ Error: El monto total bruto debe ser superior a $0.")
                    elif not selcc:
                        st.error("❌ Error: Debes seleccionar obligatoriamente al menos un Cuartel.")
                    else:
                        imp = mt if iva == "SI" else mt / 1.19
                        reparto, err_cc = _reparto_por_cc(conn, imp, selcc)
                        if err_cc:
                            st.error(f"❌ {err_cc}")
                        else:
                            tg_gv = st.session_state.get("gv_tipo_gasto", TIPOS_GASTO_ALTA[0])
                            conn.execute(
                                "INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, concepto, razon_social, tipo_gasto) VALUES (?,?,?,?,?,?,?,?,?)",
                                (ng_final, pg, str(fg1), str(fg2), mt, tipo_gv, concepto_det.strip(), razon_gv, tg_gv),
                            )
                            for c, parte in reparto:
                                conn.execute(
                                    "INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo, centro_costo, monto_imputado, concepto, razon_social, tipo_gasto) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                    (ng_final + "_P", pg, str(fg1), str(fg2), 0, tipo_gv, c.upper(), parte, concepto_det.strip(), razon_gv, tg_gv),
                                )
                            conn.commit()
                            registrar_accion("GASTO", ng_final)
                            st.success(f"✅ Gasto registrado con éxito bajo el folio: {ng_final}")
                            _limpiar_formulario_compras_ingreso(con_razon=True)
                            st.rerun()

    elif sec_comp == _comp_secc[1]:
        st.subheader("🔍 Panel de Filtros y Motores de Búsqueda Avanzada")
        c_f1, c_f2, c_f3 = st.columns([1.5, 1, 1])
        q_global = c_f1.text_input("Buscador Dinámico", key="hist_q_global")
        row_fc = conn.execute(
            "SELECT MAX(fecha_compra) FROM facturas WHERE monto_total > 0 AND nro_documento NOT LIKE '%_P'"
        ).fetchone()
        fmax_db = pd.to_datetime(row_fc[0]).date() if row_fc and row_fc[0] else hoy
        fi_hist = c_f2.date_input("Fecha Desde", _fecha_minima_facturas_compras(conn), key="hist_fi")
        ff_hist = c_f3.date_input("Fecha Hasta", max(hoy, fmax_db), key="hist_ff")
        
        query_hist = f"""SELECT id as ID, nro_documento as [N° DOCUMENTO], proveedor as PROVEEDOR,
                                IFNULL(razon_social, 'La Concepción') as [RAZÓN SOCIAL],
                                fecha_compra as [FECHA COMPRA],
                                {_SQL_ETIQUETA_TIPO_COMPRA} as [TIPO],
                                COALESCE(NULLIF(TRIM(tipo_gasto), ''), '{TIPO_GASTO_SIN_CLASIFICAR}') as [TIPO GASTO CC],
                                concepto as [DETALLE / CONCEPTO],
                                monto_total as [MONTO BRUTO]
                        FROM facturas
                        WHERE monto_total > 0 AND nro_documento NOT LIKE '%_P'
                          AND fecha_compra BETWEEN '{fi_hist}' AND '{ff_hist}'"""
                        
        if q_global.strip() != "":
            query_hist += f" AND (nro_documento LIKE '%{q_global}%' OR proveedor LIKE '%{q_global}%' OR concepto LIKE '%{q_global}%' OR IFNULL(razon_social,'') LIKE '%{q_global}%')"
            
        query_hist += " ORDER BY id DESC"
        
        dfh_filtrado = pd.read_sql_query(query_hist, conn)
        st.dataframe(dfh_filtrado.style.format({"MONTO BRUTO": _fmt_styler_peso}), use_container_width=True)
        
        if not dfh_filtrado.empty:
            boton_pdf(
                "PDF HISTORIAL COMPRAS",
                generar_pdf_blob(
                    dfh_filtrado.drop(columns=["ID"], errors="ignore"),
                    "HISTORIAL CONSOLIDADO DE COMPRAS",
                    campo_suma_forzado="MONTO BRUTO",
                ),
                "historial_compras.pdf",
                key="ch_pdf_dinamico",
            )
        _panel_corregir_compras_historial(conn, dfh_filtrado)

    elif sec_comp == _comp_secc[2]:
        from erp_caja_chica import render_modulo_caja_chica
        render_modulo_caja_chica(
            conn, registrar_accion, hora_chile, es_solo_lectura, f_peso,
            boton_pdf_fn=boton_pdf, generar_pdf_fn=generar_pdf_blob,
        )

    conn.close()

def modulo_tesoreria():
    encabezado_modulo("Tesoreria", "💸 TESORERÍA"); conn = conectar_db()
    
    def enviar_correo_pago_interno(proveedor, documentos, monto_total, metodo, usuario_operador, razon_social=""):
        from erp_correo_html import plantilla_correo_html

        try:
            if "gmail_smtp" not in st.secrets:
                return False
                
            conf = st.secrets["gmail_smtp"]
            emisor = conf["correo_emisor"]
            clave = conf["clave_application"] if "clave_application" in conf else conf["clave_aplicacion"]
            
            DESTINATARIOS = obtener_destinatarios_tesoreria(conn)
            if not DESTINATARIOS:
                return False
            filas_docs = "".join(
                f"<p>📄 <b>{d['nro_documento']}</b> — ${int(d['monto']):,}</p>"
                for d in documentos
            )
            n_docs = len(documentos)
            try:
                from erp_proveedores import razones_sociales_desde_docs
                pagador = razones_sociales_desde_docs(documentos, razon_social) or ""
            except Exception:
                pagador = (razon_social or "")
            marca_erp = (NOMBRE_ERP or "Agrícola La Concepción").strip()
            msg = MIMEMultipart()
            msg['From'] = smtp_from_header(emisor)
            msg['To'] = ", ".join(DESTINATARIOS)
            msg['Subject'] = f"🚨 [{marca_erp}] Pago Procesado: {proveedor} ({n_docs} doc.)"
            
            interior = f"""
                    <p>Se ha procesado un movimiento conforme en el módulo de <b>Tesorería</b>:</p>
                    <hr style='border: 0; border-top: 1px solid #eee;'>
                    <p><b>🏛️ Razón social que paga:</b> {pagador}</p>
                    <p><b>🏢 Proveedor:</b> {proveedor}</p>
                    <p><b>📄 Documento(s) pagado(s):</b> {n_docs}</p>
                    {filas_docs}
                    <p><b>💰 Monto total pagado:</b> <span style='font-weight: bold;'>${int(monto_total):,}</span></p>
                    <p><b>💳 Método Utilizado:</b> {metodo}</p>
                    <p><b>👤 Usuario Operador:</b> <span style='font-weight: bold;'>{usuario_operador}</span></p>
                    <p><b>📅 Fecha:</b> {str(hoy)}</p>
            """
            cuerpo_html = plantilla_correo_html(
                "tesoreria",
                "💸 Egreso registrado en Tesorería",
                interior,
                nombre_erp=marca_erp,
                pie="Respaldo automático de auditoría — Tesorería.",
            )
            _smtp_adjuntar_html(msg, cuerpo_html)
            
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(emisor, clave)
            server.sendmail(emisor, DESTINATARIOS, msg.as_string())
            server.quit()
            return True
        except Exception as e:
            try:
                conn_err = conectar_db()
                f_h = hora_chile().strftime('%Y-%m-%d %H:%M:%S')
                conn_err.execute("INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)", 
                                 (st.session_state.get('email', 'SISTEMA'), "FALLO_SMTP_TESO", str(e)[:150], f_h))
                conn_err.commit(); conn_err.close()
            except:
                pass
            return False

    teso_secciones = [
        "🔴 PENDIENTES",
        "🏢 DEUDA POR PROVEEDOR",
        "📜 HISTORIAL AUDITABLE",
    ]
    sec_teso = nav_seccion(teso_secciones, "teso_sec_nav", "Sección de Tesorería")

    if sec_teso == teso_secciones[0]:
        dfp = _cargar_facturas_pendientes_saldo(conn).sort_values("fecha_vencimiento")
        dfp_show = dfp.rename(columns={
            "nro_documento": "N° DOCUMENTO",
            "proveedor": "PROVEEDOR",
            "razon_social": "RAZÓN SOCIAL",
            "fecha_vencimiento": "VENCIMIENTO",
            "dias_vencido": "DÍAS VENC.",
            "monto_total": "MONTO DOC.",
            "monto_pagado": "ABONADO",
            "saldo": "SALDO",
        }).drop(columns=["id"])
        dfp_show = dfp_show[
            [
                "N° DOCUMENTO", "PROVEEDOR", "RAZÓN SOCIAL", "VENCIMIENTO", "DÍAS VENC.",
                "MONTO DOC.", "ABONADO", "SALDO",
            ]
        ]
        st.warning(f"### DEUDA PENDIENTE: ${f_puntos(dfp['saldo'].sum())}")
        
        def highlight_v(row):
            return ['background-color: #FFCDD2; color: #B71C1C; font-weight: bold' if pd.to_datetime(row['VENCIMIENTO']).date() < hoy else '' for _ in row]
            
        st.dataframe(
            dfp_show.style.apply(highlight_v, axis=1).format({
                "MONTO DOC.": _fmt_styler_peso,
                "ABONADO": _fmt_styler_peso,
                "SALDO": _fmt_styler_peso,
                "DÍAS VENC.": lambda v: "" if pd.isna(v) else str(int(v)),
            }),
            use_container_width=True,
        )
        boton_pdf("PDF PENDIENTES", generar_pdf_blob(dfp_show, "DEUDAS PENDIENTES", campo_suma_forzado="SALDO", estilo_celda_fn=_pdf_estilo_tesoreria_vencida, font_size_header=12, font_size_body=11, h_line_header=10, h_line_body=7), "pendientes.pdf", key="t_pdf_1")
        st.info("Para registrar pagos o abonos parciales, use la sección **🏢 Deuda por proveedor**.")
                
    elif sec_teso == teso_secciones[1]:
        from demo_web.services.tesoreria_cxp import saldo_cxp_neto, sql_imputado_costos_subquery, sql_solo_cxp_tesoreria
        from demo_web.services.lc_excluir_espino import sql_and_excluir_razon_social_espino

        excl = sql_and_excluir_razon_social_espino()
        imp_sql = sql_imputado_costos_subquery("f")
        prvs = pd.read_sql_query(
            f"""SELECT DISTINCT proveedor FROM facturas
               WHERE estado='Pendiente' AND monto_total > 0
               {sql_solo_cxp_tesoreria()}
               {excl}
               ORDER BY proveedor""",
            conn,
        )
        if not prvs.empty:
            psel = st.selectbox("Proveedor", prvs['proveedor'], key="t_prov_1")
            render_info_contacto_proveedor(conn, psel)
            dfpr = pd.read_sql_query(
                f"""SELECT f.id, f.nro_documento, f.fecha_vencimiento, f.monto_total,
                          COALESCE(f.monto_pagado, 0) AS monto_pagado,
                          COALESCE(NULLIF(TRIM(f.razon_social), ''), '') AS razon_social,
                          {imp_sql} AS imputado_costos
                   FROM facturas f
                   WHERE f.proveedor=? AND f.estado='Pendiente' AND f.monto_total > 0
                   {sql_solo_cxp_tesoreria('f')}
                   {excl}
                   ORDER BY f.fecha_vencimiento ASC""",
                conn,
                params=(psel,),
            )
            dfpr["saldo"] = dfpr.apply(
                lambda r: saldo_cxp_neto(r["monto_total"], r["monto_pagado"], r["imputado_costos"]),
                axis=1,
            )
            dfpr = dfpr[dfpr["saldo"] > 0.01].copy()
            total_deuda = dfpr["saldo"].sum()
            st.info(f"Deuda con {psel}: ${f_puntos(total_deuda)} — {len(dfpr)} documento(s) pendiente(s)")
            dfpr_show = dfpr.drop(columns=["id"]).rename(columns={
                "monto_total": "monto_doc",
                "monto_pagado": "abonado",
                "saldo": "saldo_pendiente",
            })
            st.dataframe(
                dfpr_show.style.format({
                    "monto_doc": _fmt_styler_peso,
                    "abonado": _fmt_styler_peso,
                    "saldo_pendiente": _fmt_styler_peso,
                }),
                use_container_width=True,
            )
            boton_pdf(
                f"PDF DEUDA {psel}",
                generar_pdf_blob(
                    dfpr_show,
                    f"DEUDA {psel}",
                    campo_suma_forzado="saldo_pendiente",
                    estilo_celda_fn=_pdf_estilo_tesoreria_vencida,
                ),
                f"deuda_{psel}.pdf",
                key="t_pdf_2",
            )
            if not dfpr.empty and not es_solo_lectura():
                st.markdown("##### Registrar pago total (puede seleccionar varios documentos)")
                with st.form("pago_proveedor_multi", clear_on_submit=False):
                    ids_pagar = []
                    for _, fila in dfpr.iterrows():
                        saldo_f = float(fila["saldo"])
                        abonado_txt = (
                            f" · abonado ${f_puntos(fila['monto_pagado'])}"
                            if float(fila["monto_pagado"]) > 0.01 else ""
                        )
                        etiqueta = (
                            f"{fila['nro_documento']} — saldo ${f_puntos(saldo_f)}{abonado_txt} — "
                            f"vence {pd.to_datetime(fila['fecha_vencimiento']).strftime('%d-%m-%Y')}"
                        )
                        if st.checkbox(etiqueta, key=f"t_pay_doc_{int(fila['id'])}"):
                            ids_pagar.append(int(fila["id"]))
                    metp = st.selectbox("Método de pago", METODOS_PAGO_TESORERIA, key="t_prov_met")
                    fpago = st.date_input("Fecha de pago", hoy, key="t_prov_fecha")
                    if st.form_submit_button("💰 PAGAR DOCUMENTOS SELECCIONADOS"):
                        if not ids_pagar:
                            st.error("Seleccione al menos un documento para pagar.")
                        else:
                            lineas = []
                            monto_total = 0.0
                            user_actual = st.session_state.get("email", "Usuario No Identificado")
                            errores = []
                            for doc_id in ids_pagar:
                                fila_p = dfpr[dfpr["id"] == doc_id].iloc[0]
                                saldo_p = float(fila_p["saldo"])
                                ok, res = _registrar_abono_factura(
                                    conn, doc_id, fpago, saldo_p, metp, user_actual,
                                )
                                if not ok:
                                    errores.append(f"{fila_p['nro_documento']}: {res}")
                                    continue
                                lineas.append({
                                    "nro_documento": fila_p["nro_documento"],
                                    "monto": saldo_p,
                                    "razon_social": str(fila_p.get("razon_social") or "").strip(),
                                })
                                monto_total += saldo_p
                            if lineas:
                                conn.commit()
                                with st.spinner("Despachando avisos..."):
                                    enviar_correo_pago_interno(
                                        proveedor=psel,
                                        documentos=lineas,
                                        monto_total=monto_total,
                                        metodo=metp,
                                        usuario_operador=user_actual,
                                    )
                                    mail_prov_ok, mail_prov = enviar_correo_pago_proveedor_si_corresponde(
                                        conn,
                                        psel,
                                        lineas,
                                        monto_total,
                                        metp,
                                        fpago,
                                        NOMBRE_ERP,
                                        _enviar_correo_html,
                                        registrar_accion=registrar_accion,
                                    )
                                    wa_ok, wa_dest, wa_err = enviar_whatsapp_pago_si_corresponde(
                                        conn,
                                        psel,
                                        lineas,
                                        monto_total,
                                        metp,
                                        fpago,
                                        NOMBRE_ERP,
                                        secrets_path=SECRETS_PATH,
                                        registrar_accion=registrar_accion,
                                    )
                                docs_txt = ", ".join(d["nro_documento"] for d in lineas)
                                registrar_accion("PAGO PROVEEDOR", f"{psel}: {docs_txt}")
                                msg = (
                                    f"✅ {len(lineas)} documento(s) de {psel} pagados "
                                    f"por ${f_puntos(monto_total)}."
                                    + mensaje_avisos_pago_proveedor(
                                        conn, psel, mail_prov_ok, mail_prov, wa_ok, wa_dest, wa_err
                                    )
                                )
                                st.success(msg)
                            if errores:
                                st.error(" ".join(errores))
                            if lineas:
                                st.rerun()

                st.markdown("##### Abonar pago parcial")
                with st.form("abono_factura_parcial", clear_on_submit=True):
                    opciones_abono = {}
                    for _, fila in dfpr.iterrows():
                        saldo_f = float(fila["saldo"])
                        lbl = (
                            f"{fila['nro_documento']} — saldo ${f_puntos(saldo_f)} — "
                            f"vence {pd.to_datetime(fila['fecha_vencimiento']).strftime('%d-%m-%Y')}"
                        )
                        opciones_abono[lbl] = (int(fila["id"]), saldo_f)
                    if not opciones_abono:
                        st.info("No hay documentos con saldo pendiente.")
                    else:
                        doc_sel = st.selectbox("Documento", list(opciones_abono.keys()), key="t_ab_doc")
                        doc_id_ab, saldo_max = opciones_abono[doc_sel]
                        fecha_ab = st.date_input("Fecha del abono", hoy, key="t_ab_fecha")
                        monto_ab = st.number_input(
                            "Monto abono ($)",
                            min_value=0.0,
                            max_value=float(saldo_max),
                            value=float(saldo_max),
                            step=1000.0,
                            key="t_ab_monto",
                        )
                        met_ab = st.selectbox("Método de pago", METODOS_PAGO_TESORERIA, key="t_ab_met")
                        if st.form_submit_button("💵 REGISTRAR ABONO"):
                            user_actual = st.session_state.get("email", "Usuario No Identificado")
                            ok, res = _registrar_abono_factura(
                                conn, doc_id_ab, fecha_ab, monto_ab, met_ab, user_actual,
                            )
                            if not ok:
                                st.error(res)
                            else:
                                conn.commit()
                                with st.spinner("Despachando avisos..."):
                                    _docs_ab = [{
                                            "nro_documento": res["nro_documento"],
                                            "monto": res["monto"],
                                            "razon_social": str(
                                                (dfpr.loc[dfpr["id"] == doc_id_ab, "razon_social"].iloc[0])
                                                if "razon_social" in dfpr.columns and not dfpr.loc[dfpr["id"] == doc_id_ab].empty
                                                else ""
                                            ),
                                        }]
                                    enviar_correo_pago_interno(
                                        proveedor=psel,
                                        documentos=_docs_ab,
                                        monto_total=res["monto"],
                                        metodo=met_ab,
                                        usuario_operador=user_actual,
                                    )
                                    mail_prov_ok, mail_prov = enviar_correo_pago_proveedor_si_corresponde(
                                        conn,
                                        psel,
                                        _docs_ab,
                                        res["monto"],
                                        met_ab,
                                        fecha_ab,
                                        NOMBRE_ERP,
                                        _enviar_correo_html,
                                        registrar_accion=registrar_accion,
                                    )
                                    wa_ok, wa_dest, wa_err = enviar_whatsapp_pago_si_corresponde(
                                        conn,
                                        psel,
                                        _docs_ab,
                                        res["monto"],
                                        met_ab,
                                        fecha_ab,
                                        NOMBRE_ERP,
                                        secrets_path=SECRETS_PATH,
                                        registrar_accion=registrar_accion,
                                    )
                                registrar_accion(
                                    "ABONO FACTURA",
                                    f"{psel} | {res['nro_documento']} | ${f_puntos(res['monto'])}",
                                )
                                msg = (
                                    f"✅ Abono de ${f_puntos(res['monto'])} registrado en "
                                    f"{res['nro_documento']}."
                                )
                                if res["estado"] == "Pagado":
                                    msg += " Documento saldado."
                                else:
                                    msg += f" Saldo restante: ${f_puntos(res['saldo_restante'])}."
                                msg += mensaje_avisos_pago_proveedor(
                                    conn, psel, mail_prov_ok, mail_prov, wa_ok, wa_dest, wa_err
                                )
                                st.success(msg)
                                st.rerun()
            elif not dfpr.empty and es_solo_lectura():
                st.info("Modo solo lectura: no puede registrar pagos ni abonos.")
            
    elif sec_teso == teso_secciones[2]:
        st.markdown("#### 🔍 Filtros de búsqueda")
        c1, c2, c3 = st.columns([2, 1, 1.5])
        bsq = c1.text_input("Buscar proveedor o documento", key="t_h1")
        met = c2.selectbox("Método de pago", ["TODOS"] + METODOS_PAGO_TESORERIA, key="t_h2")
        fi = c3.date_input("Desde", _fecha_minima_historial_tesoreria(conn), key="t_h3")
        ff = c3.date_input("Hasta", hoy, key="t_h4")

        dfh = _query_historial_abonos_tesoreria(conn, fi, ff, bsq, met)

        st.markdown("##### Pagos registrados")

        if dfh.empty:
            st.info("No hay pagos para los filtros seleccionados.")
        else:
            total_periodo = float(dfh["monto_total"].sum())
            n_grupos = dfh.groupby(["proveedor", "fecha_pago", "metodo_pago"], sort=False).ngroups
            col_res, col_pdf = st.columns([2.8, 1.2])
            with col_res:
                st.markdown(
                    f"<div style='color:#37474F;font-size:0.92rem;padding-top:0.4rem;line-height:1.5;'>"
                    f"<b>{n_grupos}</b> pago(s) · <b>{len(dfh)}</b> documento(s) · "
                    f"Total período: <b>${f_puntos(total_periodo)}</b> · "
                    f"más reciente arriba (N° {n_grupos})</div>",
                    unsafe_allow_html=True,
                )
            with col_pdf:
                blob_hist = generar_pdf_tesoreria_pagos(dfh)
                if blob_hist:
                    boton_descarga_pdf(
                        blob_hist, "pagos_tesoreria.pdf", "t_pdf_3", "PDF HISTORIAL DE PAGOS",
                        use_container_width=True,
                    )
                else:
                    st.button("📥 PDF — sin datos", disabled=True, key="t_pdf_3_off", use_container_width=True)
            st.markdown("<div style='margin-bottom:0.6rem;'></div>", unsafe_allow_html=True)
            render_historial_tesoreria_agrupado(dfh, mostrar_resumen=False)
        
    conn.close()

def _bodega_tab_pppl(conn):
    _render_auditoria_pppl_bodega(conn, key_prefix="bod_pppl")

def modulo_bodega():
    encabezado_modulo("Bodega", "🏠 BODEGA")
    conn = conectar_db()
    familias_prod = listar_familias_producto(conn)
    if es_certificacion():
        _bod_cert = ["🌿 PPPL", "📊 STOCK CONSULTA"]
        sec_bod = nav_seccion(_bod_cert, "bod_cert_nav", "Sección")
        if sec_bod == _bod_cert[0]:
            _bodega_tab_pppl(conn)
        elif sec_bod == _bod_cert[1]:
            dfs = pd.read_sql_query(
                "SELECT producto as PRODUCTO, familia as FAMILIA, stock as STOCK, COALESCE(unidad_medida, 'kg') as UM, "
                "COALESCE(ingrediente_activo,'') as [ING. ACTIVO], pppl_aprobado as PPPL, dias_carencia as PHI FROM inventario ORDER BY producto",
                conn,
            )
            dfs_show = dfs.copy()
            dfs_show["STOCK"] = dfs_show["STOCK"].apply(f_cantidad)
            st.dataframe(dfs_show, use_container_width=True)
        conn.close()
        return
    _bod_secc = [
        "📊 STOCK ACTUAL", "🔄 SALIDA", "🌿 PPPL", "📋 STOCK INICIAL",
        "🔍 CONSULTA CUARTEL", "⚠️ DESFASE LC",
    ]
    sec_bod = nav_seccion(_bod_secc, "bod_nav", "Sección")
    if sec_bod == _bod_secc[0]:
        dfs = pd.read_sql_query(
            """SELECT id, producto, familia, stock, COALESCE(unidad_medida, 'kg') as unidad_medida,
                      precio_medio, pppl_aprobado, dias_carencia, COALESCE(ingrediente_activo,'') as ingrediente_activo
               FROM inventario ORDER BY producto COLLATE NOCASE""",
            conn,
        )
        busq_stock = st.text_input(
            "Buscar producto, familia o ingrediente activo",
            key="b_stock_q",
            placeholder="Ej: urea, glifosato, fungicida…",
        )
        dfs_view = dfs.copy()
        if busq_stock.strip():
            q = busq_stock.strip().lower()
            dfs_view = dfs_view[
                dfs_view["producto"].astype(str).str.lower().str.contains(q, na=False)
                | dfs_view["familia"].astype(str).str.lower().str.contains(q, na=False)
                | dfs_view["ingrediente_activo"].astype(str).str.lower().str.contains(q, na=False)
            ]
        if dfs_view.empty:
            st.info("No hay productos que coincidan con la búsqueda.")
        else:
            dfs_show = dfs_view.rename(columns={"unidad_medida": "UM", "ingrediente_activo": "ING. ACTIVO"}).copy()
            dfs_show["stock"] = dfs_show["stock"].apply(f_cantidad)
            cols_orden = [
                "producto", "ING. ACTIVO", "familia", "stock", "UM",
                "precio_medio", "pppl_aprobado", "dias_carencia",
            ]
            cols_ok = [c for c in cols_orden if c in dfs_show.columns]
            extra = [c for c in dfs_show.columns if c not in cols_ok and c != "id"]
            dfs_show = dfs_show[cols_ok + extra]
            st.dataframe(
                dfs_show.style.format({"precio_medio": _fmt_styler_peso}),
                use_container_width=True,
            )
        dfs_op = dfs_view.drop(columns=['precio_medio', 'id'], errors='ignore').rename(columns={"unidad_medida": "UM"})
        boton_pdf("PDF STOCK OPERATIVO", generar_pdf_blob(dfs_op, "STOCK ACTUAL (SIN PRECIOS)", incluir_precios=False, estilo_celda_fn=_pdf_estilo_stock_pppl), "stock_operativo.pdf", key="b_pdf_1")
        if es_admin() and not dfs_view.empty:
            st.divider()
            st.markdown("##### ✏️ Corregir stock / nombre / familia / unidad / precio")
            opts_corr = dfs_view.apply(
                lambda r: f"{int(r['id'])} — {r['producto']} (stock: {f_cantidad(r['stock'])} {r['unidad_medida']})",
                axis=1,
            ).tolist()
            sel_corr = st.selectbox("Insumo a corregir", opts_corr, key="b_m_sel")
            idb = int(sel_corr.split(" — ")[0])
            row_corr = dfs_view[dfs_view['id'] == idb].iloc[0]
            fk = f"b_corr_{idb}"
            with st.form(f"bodega_corr_stock_form_{idb}", clear_on_submit=False):
                nprod = st.text_input("Nombre producto", value=str(row_corr['producto']), key=f"{fk}_nom")
                fam_actual = str(row_corr['familia'] or familias_prod[0])
                idx_fam = (
                    familias_prod.index(fam_actual)
                    if fam_actual in familias_prod
                    else 0
                )
                nfam = st.selectbox("Familia", familias_prod, index=idx_fam, key=f"{fk}_fam")
                um_actual = row_corr['unidad_medida']
                idx_um = (
                    UNIDADES_MEDIDA_INSUMO.index(um_actual)
                    if um_actual in UNIDADES_MEDIDA_INSUMO
                    else UNIDADES_MEDIDA_INSUMO.index(DEFAULT_UNIDAD_INSUMO)
                )
                c_st, c_um = st.columns(2)
                nst = c_st.number_input(
                    "Nuevo stock real",
                    min_value=0.0,
                    value=float(row_corr['stock']),
                    step=0.01,
                    format="%.2f",
                    key=f"{fk}_stock",
                )
                num_um = c_um.selectbox("Unidad de medida", UNIDADES_MEDIDA_INSUMO, index=idx_um, key=f"{fk}_um")
                npmp = st.number_input(
                    "Precio medio neto (PMP) ($)",
                    min_value=0.0,
                    value=float(row_corr["precio_medio"] or 0),
                    step=1.0,
                    format="%.0f",
                    key=f"{fk}_pmp",
                    help="Valor neto unitario de referencia. Se usa al imputar salidas de bodega a cuarteles.",
                )
                nia = st.text_input(
                    "Ingrediente activo",
                    value=str(row_corr.get("ingrediente_activo") or _ingrediente_pppl_producto(conn, row_corr["producto"])),
                    key=f"{fk}_ia",
                )
                clave_corr = st.text_input("Clave maestra", type="password", key=f"{fk}_clave")
                guardar_corr = st.form_submit_button("✏️ GUARDAR CORRECCIÓN")
            if guardar_corr:
                if clave_corr != CLAVE_MAESTRA:
                    st.error("❌ Clave maestra incorrecta.")
                elif not nprod.strip():
                    st.error("❌ El nombre del producto es obligatorio.")
                elif conn.execute(
                    "SELECT id FROM inventario WHERE UPPER(producto)=? AND id!=?",
                    (nprod.strip().upper(), idb),
                ).fetchone():
                    st.error("❌ Ya existe otro producto con ese nombre.")
                else:
                    conn.execute(
                        "UPDATE inventario SET producto=?, familia=?, stock=?, unidad_medida=?, precio_medio=?, ingrediente_activo=? WHERE id=?",
                        (nprod.strip(), nfam, nst, num_um, npmp, nia.strip(), idb),
                    )
                    if requiere_autorizacion_pppl(nfam) and nia.strip():
                        gap = conn.execute(
                            "SELECT id FROM gap_pppl WHERE UPPER(TRIM(producto))=?",
                            (nprod.strip().upper(),),
                        ).fetchone()
                        if gap:
                            conn.execute(
                                "UPDATE gap_pppl SET ingrediente_activo=?, vigente=1 WHERE id=?",
                                (nia.strip(), gap[0]),
                            )
                    conn.commit()
                    registrar_accion(
                        "BODEGA",
                        f"ID {idb} producto={nprod.strip()} familia={nfam} stock={nst} um={num_um} pmp={npmp}",
                    )
                    st.success("✅ Producto corregido.")
                    st.rerun()
    elif sec_bod == _bod_secc[1]:
        _mostrar_alertas_cruce_lc_bodega()
        _banner_independencia_lc_bodega("bodega")
        dfi = pd.read_sql_query(
            "SELECT id, producto, precio_medio, COALESCE(unidad_medida, 'kg') as unidad_medida FROM inventario WHERE stock > 0",
            conn,
        )
        if not dfi.empty:
            ps = st.selectbox(
                "Insumo",
                dfi['id'].astype(str) + " - " + dfi['producto'] + " (" + dfi['unidad_medida'] + ")",
                key="b_s1",
            )
            iid_preview = int(ps.split(" - ")[0])
            um_sel = dfi.loc[dfi['id'] == iid_preview, 'unidad_medida'].iloc[0]
            with st.form("salida_bodega_form", clear_on_submit=True):
                ct = st.number_input(f"Cantidad ({um_sel})", 0.0, step=0.01, format="%.2f", key="bod_s_c")
                ccs = [cc for cc in CENTROS_COSTO if st.checkbox(cc, key=f"b_s_cc_{cc}")]
                btn_bod_s = st.form_submit_button("REGISTRAR SALIDA BODEGA")
            if btn_bod_s:
                rechazar_escritura_solo_lectura()
                iid = int(ps.split(" - ")[0]); pmp = dfi[dfi['id']==iid]['precio_medio'].iloc[0]
                prod_nombre = dfi[dfi['id'] == iid]['producto'].iloc[0]
                if ct > 0 and ccs:
                    reparto, err_cc = _reparto_por_cc(conn, ct, ccs)
                    if err_cc:
                        st.error(f"❌ {err_cc}")
                    else:
                        for c, cant_cc in reparto:
                            conn.execute(
                                """INSERT INTO movimientos
                                   (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado, unidad_medida)
                                   VALUES (?,?,?,?,?,?,?)""",
                                (iid, "Salida", cant_cc, str(hoy), c.upper(), cant_cc * pmp, um_sel),
                            )
                        conn.execute("UPDATE inventario SET stock = stock - ? WHERE id = ?", (ct, iid))
                        conn.commit()
                        registrar_accion("BODEGA", ps)
                        if producto_pppl_aprobado(conn, prod_nombre):
                            st.session_state["bodega_alerta_lc"] = {
                                "producto": prod_nombre,
                                "cantidad": ct,
                                "um": um_sel,
                                "cuarteles": list(ccs),
                            }
                        else:
                            st.session_state["bodega_salida_ok"] = True
                        st.rerun()
    elif sec_bod == _bod_secc[2]:
        _bodega_tab_pppl(conn)
    elif sec_bod == _bod_secc[3]:
        st.warning("⚠️ Solo para **apertura de inventario existente** al iniciar el sistema. Las compras de productos nuevos deben ingresarse en **Compras → Insumos**.")
        with st.form("ni", clear_on_submit=True):
            np = st.text_input("Nombre comercial producto", key="bn_1")
            nf = st.selectbox("Familia", familias_prod, key="bn_2")
            nu = st.selectbox(
                "Unidad de medida",
                UNIDADES_MEDIDA_INSUMO,
                index=UNIDADES_MEDIDA_INSUMO.index(DEFAULT_UNIDAD_INSUMO),
                key="bn_um",
            )
            ns = st.number_input("Stock físico existente hoy", 0.0, step=0.01, format="%.2f", key="bn_3")
            npr = st.number_input("PMP estimado actual ($)", 0.0, key="bn_4", help="Valor referencial del stock ya existente en bodega.")
            if st.form_submit_button("REGISTRAR APERTURA DE STOCK"):
                if np.strip() != "":
                    existe = conn.execute("SELECT id FROM inventario WHERE UPPER(producto)=?", (np.strip().upper(),)).fetchone()
                    if existe:
                        st.error("❌ El producto ya existe. Use Compras → Insumos para nuevas compras.")
                    else:
                        cur = conn.execute(
                            "INSERT INTO inventario (producto, familia, stock, precio_medio, unidad_medida) VALUES (?,?,?,?,?)",
                            (np.strip(), nf, ns, npr, nu),
                        )
                        new_id = cur.lastrowid
                        poblar_ingredientes_inventario(conn, new_id)
                        conn.commit(); registrar_accion("BODEGA", f"Apertura stock {np}")
                        st.success("✅ Apertura de inventario registrada.")
                        st.rerun()
    elif sec_bod == _bod_secc[4]:
        ccq = st.selectbox("Consultar Cuartel", CENTROS_COSTO, key="b_q1")
        col_f1, col_f2 = st.columns(2)
        f_desde_b = col_f1.date_input("Desde", hoy - timedelta(days=90), key="b_fe_d")
        f_hasta_b = col_f2.date_input("Hasta", hoy, key="b_fe_h")
        
        dfcc_raw = pd.read_sql_query(
            f"""SELECT m.id as ID, m.producto_id as PRODUCTO_ID, m.fecha as FECHA, i.producto as PRODUCTO,
                      m.cantidad as CANTIDAD, {_sql_um_movimiento()} as UM,
                      m.valor_imputado as VALOR_IMPUTADO
               FROM movimientos m JOIN inventario i ON m.producto_id = i.id
               WHERE m.centro_costo = ? AND m.tipo = 'Salida'
                 AND m.fecha BETWEEN ? AND ?
               ORDER BY m.fecha ASC, m.id ASC""",
            conn,
            params=(ccq.upper(), str(f_desde_b), str(f_hasta_b)),
        )
        if not dfcc_raw.empty:
            dfcc_raw = dfcc_raw.assign(N=lambda d: range(1, len(d) + 1))
            dfcc_show = dfcc_raw.sort_values(["FECHA", "ID"], ascending=[False, False]).copy()
            dfcc_show["N"] = range(len(dfcc_show), 0, -1)
            dfcc_fmt = dfcc_show[["N", "FECHA", "PRODUCTO", "CANTIDAD", "UM", "VALOR_IMPUTADO"]].copy()
            dfcc_fmt["CANTIDAD"] = dfcc_fmt["CANTIDAD"].apply(f_cantidad)
            st.dataframe(
                dfcc_fmt.style.format({"VALOR_IMPUTADO": _fmt_styler_peso}),
                use_container_width=True,
            )
            dfcc_pdf = dfcc_raw[["FECHA", "PRODUCTO", "CANTIDAD", "UM", "VALOR_IMPUTADO"]].rename(
                columns={"FECHA": "FECHA", "PRODUCTO": "PRODUCTO", "CANTIDAD": "CANTIDAD", "UM": "UM", "VALOR_IMPUTADO": "VALOR_IMPUTADO"}
            )
        else:
            dfcc_show = dfcc_raw
            dfcc_pdf = dfcc_raw
            st.info("No hay salidas de bodega en el período seleccionado.")

        if not dfcc_raw.empty:
            boton_pdf(
                "PDF CONSULTA CUARTEL",
                generar_pdf_blob(
                    dfcc_pdf,
                    f"MOVIMIENTOS BODEGA - CUARTEL {ccq.upper()} ({f_desde_b} a {f_hasta_b})",
                    campo_suma_forzado="VALOR_IMPUTADO",
                ),
                f"bodega_cuartel_{ccq.lower()}.pdf",
                key="b_pdf_cc_btn",
            )
        _panel_corregir_movimientos_bodega_cuartel(conn, dfcc_raw, ccq.upper(), "bod_cc")
    elif sec_bod == _bod_secc[5]:
        _tab_desface_lc_bodega(conn, "bod_desf")
    conn.close()

def _render_temporada_gastos_sector(conn, temporada, fi, ff, tabla, titulo_pdf, etiqueta_modulo, etiqueta_boton, key_prefix):
    st.caption(f"Temporada **{temporada}** · {fi.strftime('%d-%m-%Y')} al {ff.strftime('%d-%m-%Y')}")
    fecha_def = hoy if fi <= hoy <= ff else (ff if hoy > ff else fi)
    _gast_secc = ["➕ REGISTRO", "📜 HISTORIAL"]
    sec_g = nav_seccion(_gast_secc, f"{key_prefix}_nav", "Sección")
    if sec_g == _gast_secc[0]:
        sin_doc = st.checkbox("¿Sin Documento Oficial? (Generar Folio Interno)", key=f"{key_prefix}_sin_doc")
        with st.form(f"{key_prefix}_form", clear_on_submit=True):
            f = st.date_input("Fecha", fecha_def, min_value=fi, max_value=ff, key=f"{key_prefix}_f")
            if sin_doc:
                d = st.text_input("Doc / Nro Factura o Boleta (Folio Interno Automático)", value="AUTOGENERADO", disabled=True, key=f"{key_prefix}_d")
            else:
                d = st.text_input("Doc / Nro Factura o Boleta", key=f"{key_prefix}_d")
            it = st.text_input("Detalle / Item de Gasto", key=f"{key_prefix}_i")
            mt = st.number_input("Monto total liquidado ($)", 0.0, key=f"{key_prefix}_m")
            if st.form_submit_button(etiqueta_boton):
                if it.strip() == "" or mt <= 0:
                    st.error("❌ Detalle e monto son obligatorios.")
                elif not (fi <= f <= ff):
                    st.error(f"❌ La fecha debe estar dentro de la temporada ({fi.strftime('%d-%m-%Y')} al {ff.strftime('%d-%m-%Y')}).")
                elif sin_doc:
                    d_final = _generar_folio_interno(conn, tabla, f)
                    conn.execute(f"INSERT INTO {tabla} (fecha, documento, item, monto) VALUES (?,?,?,?)", (str(f), d_final, it.strip(), mt))
                    conn.commit()
                    registrar_accion(etiqueta_modulo, f"{d_final} — {it}")
                    st.success(f"✅ Gasto guardado bajo folio interno: {d_final}")
                    st.rerun()
                elif not str(d or "").strip():
                    st.error("❌ El campo N° Documento es obligatorio.")
                else:
                    conn.execute(f"INSERT INTO {tabla} (fecha, documento, item, monto) VALUES (?,?,?,?)", (str(f), str(d).strip(), it.strip(), mt))
                    conn.commit()
                    registrar_accion(etiqueta_modulo, it)
                    st.success("✅ Gasto guardado y formulario limpio.")
                    st.rerun()
    elif sec_g == _gast_secc[1]:
        df_base = pd.read_sql_query(
            f"SELECT * FROM {tabla} WHERE fecha BETWEEN ? AND ? ORDER BY fecha ASC",
            conn,
            params=(str(fi), str(ff)),
        )
        total_temporada = df_base["monto"].sum() if not df_base.empty else 0
        st.markdown(
            f"<div style='background-color:#E8F5E9; padding:15px; border-radius:10px; border:2px solid #2E7D32; "
            f"color:#1B5E20; font-size:1.4rem; font-weight:bold; text-align:center; margin-bottom:15px;'>"
            f"💰 GASTO ACUMULADO {titulo_pdf} — TEMPORADA {temporada}: ${f_puntos(total_temporada)}</div>",
            unsafe_allow_html=True,
        )
        if df_base.empty:
            st.info("Sin registros en esta temporada.")
        else:
            c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
            buscar = c1.text_input("Buscar", placeholder="Detalle, documento...", key=f"{key_prefix}_bus")
            fi_f = c2.date_input("Desde", fi, min_value=fi, max_value=ff, key=f"{key_prefix}_fd")
            ff_f = c3.date_input("Hasta", min(hoy, ff), min_value=fi, max_value=ff, key=f"{key_prefix}_fh")
            orden = c4.selectbox("Orden", ["Fecha ↑", "Fecha ↓", "Monto ↑", "Monto ↓"], key=f"{key_prefix}_ord")
            df_show = df_base.copy()
            df_show["fecha"] = pd.to_datetime(df_show["fecha"])
            df_show = df_show[(df_show["fecha"].dt.date >= fi_f) & (df_show["fecha"].dt.date <= ff_f)]
            if buscar.strip():
                q = buscar.strip().upper()
                df_show = df_show[
                    df_show["item"].astype(str).str.upper().str.contains(q, na=False)
                    | df_show["documento"].astype(str).str.upper().str.contains(q, na=False)
                ]
            if orden == "Fecha ↓":
                df_show = df_show.sort_values("fecha", ascending=False)
            elif orden == "Monto ↓":
                df_show = df_show.sort_values("monto", ascending=False)
            elif orden == "Monto ↑":
                df_show = df_show.sort_values("monto", ascending=True)
            else:
                df_show = df_show.sort_values("fecha", ascending=True)
            df_show["fecha"] = df_show["fecha"].dt.strftime("%Y-%m-%d")
            total_fil = df_show["monto"].sum() if not df_show.empty else 0
            st.caption(f"{len(df_show)} movimiento(s) · Total filtrado: **${f_puntos(total_fil)}**")
            if df_show.empty:
                st.info("Sin registros para los filtros seleccionados.")
            else:
                st.dataframe(df_show.style.format({"monto": _fmt_styler_peso}), use_container_width=True)
                boton_pdf(
                    f"PDF {titulo_pdf}",
                    generar_pdf_blob(
                        df_show.drop(columns=["id"]),
                        f"{titulo_pdf} TEMPORADA {temporada} ({fi_f} a {ff_f})",
                        campo_suma_forzado="monto",
                    ),
                    f"{key_prefix}.pdf",
                    key=f"{key_prefix}_pdf",
                )
        _panel_corregir_gastos_historial(conn, df_base, tabla, etiqueta_modulo, key_prefix)

def modulo_espino():
    encabezado_modulo("Espino", "🏡 EL ESPINO")
    conn = conectar_db()
    nombre, fi, ff = nav_temporada(TEMPORADAS_ESPINO, "esp_nav", hoy=hoy)
    _render_temporada_gastos_sector(
        conn, nombre, fi, ff, "gastos_espino", "EL ESPINO", "EL ESPINO",
        "GUARDAR REGISTRO EL ESPINO", f"esp_{nombre}",
    )
    conn.close()

def _fmt_op_cert_libro(val):
    if val in (1, "1", True, "Sí", "Si", "Sí"):
        return "Sí"
    return "No"

FITOSANITARIO_PROGRAMAS = {
    "cerezos": {
        "titulo": "Programa Fitosanitario Cerezas",
        "temporada": "2026-2027",
        "version": "1.0",
        "emision": "Jun-26",
        "archivo": "programa_cerezos_2026-2027.pdf",
        "carpeta_paginas": "cerezos",
        "descarga": "programa_fitosanitario_cerezos_2026-2027.pdf",
        "emoji": "🍒",
        "notas": (
            "Pauta técnica Exportadora Subsole para protección de cerezos. "
            "Antes de aplicar, verifique PPPL Subsole, registro SAG, dosis de etiqueta y carencias "
            "(etiqueta + Asoex/LMR según mercado destino)."
        ),
    },
    "ciruelos": {
        "titulo": "Programa Fitosanitario Ciruelos",
        "temporada": "2026-2027",
        "version": "1.0",
        "emision": "Jun-26",
        "archivo": "programa_ciruelos_2026-2027.pdf",
        "carpeta_paginas": "ciruelos",
        "descarga": "programa_fitosanitario_ciruelos_2026-2027.pdf",
        "emoji": "🟣",
        "notas": (
            "Programa D'Agen / Exportadora Subsole para ciruelos. "
            "Productos fuera de este programa o del PPPL deben consultarse con el agrónomo "
            "de Subsole antes de aplicar."
        ),
    },
}

def _ruta_programa_fitosanitario(archivo):
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "fitosanitarios")
    candidatos = (
        os.path.join("/root/static/fitosanitarios", archivo),
        os.path.join(base, archivo),
    )
    for path in candidatos:
        if os.path.exists(path):
            return path
    return os.path.join(base, archivo)

@st.cache_data(show_spinner=False)
def _programa_fito_pdf_bytes(especie_key):
    meta = FITOSANITARIO_PROGRAMAS.get(especie_key, {})
    path = _ruta_programa_fitosanitario(meta.get("archivo", ""))
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read()

def _ruta_programa_paginas_dir(especie_key):
    meta = FITOSANITARIO_PROGRAMAS.get(especie_key, {})
    sub = meta.get("carpeta_paginas", especie_key)
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "fitosanitarios")
    candidatos = (
        os.path.join("/root/static/fitosanitarios", sub),
        os.path.join(base, sub),
    )
    for path in candidatos:
        if os.path.isdir(path):
            return path
    return candidatos[1]

def _generar_paginas_programa_desde_pdf(especie_key):
    """Convierte PDF a JPG por página (solo si falta la carpeta y hay PyMuPDF)."""
    try:
        import fitz
    except ImportError:
        return []
    meta = FITOSANITARIO_PROGRAMAS.get(especie_key, {})
    pdf_path = _ruta_programa_fitosanitario(meta.get("archivo", ""))
    out_dir = _ruta_programa_paginas_dir(especie_key)
    if not os.path.exists(pdf_path):
        return []
    os.makedirs(out_dir, exist_ok=True)
    doc = fitz.open(pdf_path)
    paths = []
    for i in range(len(doc)):
        pix = doc[i].get_pixmap(matrix=fitz.Matrix(1.55, 1.55), alpha=False)
        out = os.path.join(out_dir, f"pagina_{i + 1:02d}.jpg")
        pix.save(out, jpg_quality=82)
        paths.append(out)
    doc.close()
    return paths

@st.cache_data(show_spinner=False)
def _programa_fito_paginas_imagen(especie_key):
    dir_path = _ruta_programa_paginas_dir(especie_key)
    paginas = sorted(
        os.path.join(dir_path, f)
        for f in os.listdir(dir_path)
        if f.lower().startswith("pagina_") and f.lower().endswith(".jpg")
    ) if os.path.isdir(dir_path) else []
    if paginas:
        return tuple(paginas)
    generadas = _generar_paginas_programa_desde_pdf(especie_key)
    return tuple(generadas)

def render_programa_fitosanitario_paginas(especie_key):
    paginas = _programa_fito_paginas_imagen(especie_key)
    if not paginas:
        return False
    st.caption(f"**{len(paginas)}** página(s) — desplace hacia abajo para ver el documento completo.")
    for i, img_path in enumerate(paginas, 1):
        st.image(img_path, caption=f"Página {i} de {len(paginas)}", use_container_width=True)
    return True

def _panel_programa_fitosanitario(especie_key):
    meta = FITOSANITARIO_PROGRAMAS.get(especie_key)
    if not meta:
        st.error("Programa no configurado.")
        return
    st.markdown(
        f"""<div style="background:#E8F5E9;border:1px solid #A5D6A7;color:#1B5E20;
        padding:0.85rem 1rem;border-radius:12px;margin-bottom:0.85rem;">
        <strong>{meta['emoji']} {meta['titulo']}</strong> — Temporada <b>{meta['temporada']}</b>
        &nbsp;|&nbsp; Versión <b>{meta['version']}</b> &nbsp;|&nbsp; Emisión <b>{meta['emision']}</b><br>
        <span style="font-size:0.92rem;">Documento técnico Exportadora Subsole — consulta interna dentro del ERP.</span>
        </div>""",
        unsafe_allow_html=True,
    )
    st.caption(meta["notas"])
    pdf_bytes = _programa_fito_pdf_bytes(especie_key)
    if not pdf_bytes:
        st.warning(
            f"No se encontró el PDF `{meta['archivo']}`. "
            "Contacte al administrador para cargar el archivo en el servidor."
        )
        return
    c1, c2 = st.columns([3, 1])
    with c2:
        boton_descarga_pdf(
            pdf_bytes, meta["descarga"], f"lc_prog_pdf_{especie_key}", "Descargar PDF",
            use_container_width=True,
        )
    with c1:
        st.caption(
            "Consulta página a página (optimizado para celular). "
            "En iPhone use **Compartir PDF** para guardar en Archivos."
        )
    if not render_programa_fitosanitario_paginas(especie_key):
        st.warning(
            "No se pudieron generar las páginas para visualización. "
            "Use **Descargar PDF** o contacte al administrador."
        )

def render_historial_libro_campo_agrupado(df):
    if df is None or df.empty:
        st.info("No hay registros para los filtros seleccionados.")
        return
    col_app = next((c for c in df.columns if "APP" in str(c).upper()), df.columns[0])
    st.caption(f"**{df[col_app].nunique()}** evento(s) de aplicación · **{len(df)}** producto(s)")
    for n_app, grp in df.groupby(col_app, sort=False):
        grp = grp.reset_index(drop=True)
        base = grp.iloc[0]
        op_cert = _fmt_op_cert_libro(base.get("OP. CERT.", ""))
        st.markdown(
            f"""
            <div class="lc-evento-banner">
                <strong>N° {int(n_app):05d}</strong> &nbsp;|&nbsp;
                {base.get('FECHA', '')} &nbsp;|&nbsp;
                {base.get('CUARTEL', '')} &nbsp;|&nbsp;
                {base.get('ESPECIE', '')} &nbsp;|&nbsp;
                Agua: {f_decimal(base.get('VOL AGUA LT', 0))} L &nbsp;|&nbsp;
                {base.get('MAQUINARIA', '')} &nbsp;|&nbsp;
                {base.get('TRACTOR', '')} &nbsp;|&nbsp;
                {base.get('APLICADOR', '')} &nbsp;|&nbsp;
                Op.Cert: {op_cert}
            </div>
            """,
            unsafe_allow_html=True,
        )
        df_prod = grp[
            ["PRODUCTO", "LOTE", "ING ACTIVO", "DOSIS 100L", "UNIDAD", "TOTAL PROD", "FECHA VIABLE PHI"]
        ].copy()
        df_prod["DOSIS 100L"] = df_prod["DOSIS 100L"].apply(f_dosis_lc)
        df_prod["TOTAL PROD"] = df_prod["TOTAL PROD"].apply(f_cantidad)
        df_prod = df_prod.rename(columns={"FECHA VIABLE PHI": "PHI VIABLE"})
        with st.container(border=True):
            st.dataframe(df_prod, use_container_width=True, hide_index=True)


def _fmt_cantidad_desfase(v):
    """Muestra hasta 3 decimales útiles (0.125 no debe verse como 0,12)."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return v
    if abs(x - round(x)) < 1e-9:
        return f"{int(round(x))}"
    s = f"{x:.3f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")

def _normalizar_um_lc_bodega(um):
    """Normaliza etiquetas de UM (L/litro/Kg/etc.) al catálogo interno."""
    u = str(um or DEFAULT_UNIDAD_INSUMO).strip().lower().replace(".", "")
    aliases = {
        "kilo": "kg", "kilos": "kg", "kilogramo": "kg", "kilogramos": "kg",
        "gr": "gr", "g": "gr", "gramo": "gr", "gramos": "gr",
        "l": "lt", "lt": "lt", "litro": "lt", "litros": "lt",
        "ml": "ml", "mililitro": "ml", "mililitros": "ml",
        "cc": "ml",
    }
    return aliases.get(u, u or DEFAULT_UNIDAD_INSUMO)


def _tokens_producto_match(nombre):
    """Tokens significativos del nombre comercial (ignora dosis/formulaciones)."""
    raw = str(nombre or "").strip().upper()
    raw = re.sub(r"[^A-Z0-9ÁÉÍÓÚÑÜ\s]", " ", raw)
    stop = {
        "WG", "WP", "SC", "EC", "SL", "CS", "OD", "EW", "SE", "GR", "SG",
        "KG", "LT", "L", "ML", "GRS", "G", "X", "DE", "DEL", "LA", "EL",
        "PARA", "CON", "Y", "EN",
    }
    toks = []
    for t in raw.split():
        if t in stop:
            continue
        if re.fullmatch(r"\d+([.,]\d+)?", t):
            continue
        if len(t) < 3:
            continue
        toks.append(t)
    return toks


def _productos_equivalentes_lc_bodega(p_lc, p_bod):
    """True si es el mismo producto comercial con nombre distinto (alias/dosis)."""
    a = str(p_lc or "").strip().upper()
    b = str(p_bod or "").strip().upper()
    if not a or not b:
        return False
    if a == b:
        return True
    # Contención limpia (ej. BIOLIFE PSYCHRO ⊂ BIOLIFE PSYCHRO 250)
    if a in b or b in a:
        return True
    ta, tb = set(_tokens_producto_match(a)), set(_tokens_producto_match(b))
    if not ta or not tb:
        return False
    # Todos los tokens del más corto están en el más largo (NORDOX ⊂ COBRE NORDOX)
    short, long = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if short <= long:
        return True
    # Intersección fuerte: al menos 2 tokens o 1 token largo (>=6) compartido
    inter = ta & tb
    if len(inter) >= 2:
        return True
    if any(len(t) >= 6 for t in inter):
        return True
    return False


def _cantidades_equivalentes_lc_bodega(q_lc, q_mov, um_lc, um_mov, tol_rel=0.02, tol_abs=0.05):
    """Compara cantidades LC vs bodega en la misma UM (con conversión si difieren)."""
    q_lc = float(q_lc)
    q_mov = float(q_mov)
    um_lc = _normalizar_um_lc_bodega(um_lc or DEFAULT_UNIDAD_INSUMO)
    um_mov = _normalizar_um_lc_bodega(um_mov or DEFAULT_UNIDAD_INSUMO)
    if um_lc == um_mov:
        ref = max(abs(q_lc), abs(q_mov), tol_abs)
        return abs(q_lc - q_mov) <= max(tol_abs, ref * tol_rel)
    q_mov_en_lc = _convertir_um(q_mov, um_mov, um_lc)
    ref = max(abs(q_lc), abs(q_mov_en_lc), tol_abs)
    return abs(q_lc - q_mov_en_lc) <= max(tol_abs, ref * tol_rel)


def _lc_mov_coinciden(lc_row, mov_row, dias_ventana, tol_cant=0.05):
    if not _productos_equivalentes_lc_bodega(lc_row["producto"], mov_row["producto_u"]):
        return False
    if str(lc_row["sector"]).strip().upper() != str(mov_row["cuartel_u"]).strip().upper():
        return False
    um_lc = lc_row.get("unidad_gasto") or DEFAULT_UNIDAD_INSUMO
    um_mov = mov_row.get("um") or mov_row.get("um_inv") or DEFAULT_UNIDAD_INSUMO
    if not _cantidades_equivalentes_lc_bodega(
        lc_row["gasto_total"], mov_row["cantidad"], um_lc, um_mov, tol_rel=0.02, tol_abs=tol_cant,
    ):
        return False
    d_lc = pd.to_datetime(lc_row["fecha"]).date()
    d_mov = mov_row["fecha_d"] if isinstance(mov_row["fecha_d"], date) else pd.to_datetime(mov_row["fecha_d"]).date()
    return abs((d_lc - d_mov).days) <= dias_ventana

def _calcular_desfaces_lc_bodega(conn, f_desde, f_hasta, dias_ventana=14):
    ext_desde = str(f_desde - timedelta(days=dias_ventana))
    ext_hasta = str(f_hasta + timedelta(days=dias_ventana))
    df_lc = pd.read_sql_query(
        """SELECT id, fecha, n_aplicacion, sector, producto, gasto_total,
                  COALESCE(NULLIF(TRIM(unidad_gasto), ''), ?) as unidad_gasto
           FROM libro_campo WHERE date(fecha) BETWEEN ? AND ?""",
        conn,
        params=(DEFAULT_UNIDAD_INSUMO, ext_desde, ext_hasta),
    )
    df_mov = pd.read_sql_query(
        f"""SELECT m.id, m.fecha, m.cantidad, m.centro_costo, i.producto,
                  {_sql_um_movimiento()} as um
           FROM movimientos m JOIN inventario i ON i.id = m.producto_id
           WHERE m.tipo = 'Salida' AND date(m.fecha) BETWEEN ? AND ?""",
        conn,
        params=(ext_desde, ext_hasta),
    )
    # Bodega: solo PPPL (es el catálogo que se controla).
    # LC: se mantiene completo para poder empatar alias (ej. "Nordox 75 WG" ↔ "COBRE NORDOX");
    #     al reportar desfase LC solo se listan filas PPPL.
    if not df_mov.empty:
        df_mov = df_mov[df_mov["producto"].apply(lambda p: producto_pppl_aprobado(conn, p))].copy()
    df_lc_disp = df_lc[(pd.to_datetime(df_lc["fecha"]).dt.date >= f_desde) & (pd.to_datetime(df_lc["fecha"]).dt.date <= f_hasta)] if not df_lc.empty else df_lc.copy()
    df_mov_disp = df_mov[(pd.to_datetime(df_mov["fecha"]).dt.date >= f_desde) & (pd.to_datetime(df_mov["fecha"]).dt.date <= f_hasta)] if not df_mov.empty else df_mov.copy()
    if df_mov.empty:
        df_mov_agg = pd.DataFrame(columns=["fecha_d", "producto_u", "cuartel_u", "cantidad", "producto"])
    else:
        df_mov = df_mov.copy()
        df_mov["producto_u"] = df_mov["producto"].str.strip().str.upper()
        df_mov["cuartel_u"] = df_mov["centro_costo"].str.strip().str.upper()
        df_mov["fecha_d"] = pd.to_datetime(df_mov["fecha"]).dt.date
        df_mov_agg = df_mov.groupby(["fecha_d", "producto_u", "cuartel_u"], as_index=False).agg(
            cantidad=("cantidad", "sum"),
            producto=("producto", "first"),
            um=("um", "first"),
        )
    used_mov_keys = set()
    lc_sin_ids = []
    if not df_lc_disp.empty:
        for _, lc in df_lc_disp.iterrows():
            matched = False
            for idx, mov in df_mov_agg.iterrows():
                key = (mov["fecha_d"], mov["producto_u"], mov["cuartel_u"])
                if key in used_mov_keys:
                    continue
                if _lc_mov_coinciden(lc, mov, dias_ventana):
                    used_mov_keys.add(key)
                    matched = True
                    break
            if not matched:
                lc_sin_ids.append(lc["id"])
    df_lc_sin = df_lc_disp[df_lc_disp["id"].isin(lc_sin_ids)].copy() if lc_sin_ids else df_lc_disp.iloc[0:0].copy()
    if not df_lc_sin.empty:
        df_lc_sin = df_lc_sin[df_lc_sin["producto"].apply(lambda p: producto_pppl_aprobado(conn, p))].copy()
    bod_sin_rows = []
    if not df_mov_disp.empty and not df_mov_agg.empty:
        df_mov_disp = df_mov_disp.copy()
        df_mov_disp["producto_u"] = df_mov_disp["producto"].str.strip().str.upper()
        df_mov_disp["cuartel_u"] = df_mov_disp["centro_costo"].str.strip().str.upper()
        df_mov_disp["fecha_d"] = pd.to_datetime(df_mov_disp["fecha"]).dt.date
        for _, grp in df_mov_disp.groupby(["fecha_d", "producto_u", "cuartel_u"]):
            key = (grp["fecha_d"].iloc[0], grp["producto_u"].iloc[0], grp["cuartel_u"].iloc[0])
            if key in used_mov_keys:
                continue
            cant = grp["cantidad"].sum()
            mov_probe = {
                "producto_u": key[1],
                "cuartel_u": key[2],
                "cantidad": cant,
                "fecha_d": key[0],
                "um": grp["um"].iloc[0],
            }
            tiene_lc = False
            if not df_lc.empty:
                for _, lc in df_lc.iterrows():
                    if _lc_mov_coinciden(lc, mov_probe, dias_ventana):
                        tiene_lc = True
                        break
            if not tiene_lc:
                bod_sin_rows.append({
                    "fecha": str(key[0]),
                    "centro_costo": grp["centro_costo"].iloc[0],
                    "producto": grp["producto"].iloc[0],
                    "cantidad": cant,
                    "um": grp["um"].iloc[0],
                })
    df_bod_sin = pd.DataFrame(bod_sin_rows)
    if not df_lc_sin.empty:
        df_lc_sin = df_lc_sin.rename(columns={
            "fecha": "FECHA", "n_aplicacion": "N° APP", "sector": "CUARTEL",
            "producto": "PRODUCTO", "gasto_total": "CANTIDAD", "unidad_gasto": "UM",
        })[["FECHA", "N° APP", "CUARTEL", "PRODUCTO", "CANTIDAD", "UM"]]
        df_lc_sin["CANTIDAD"] = df_lc_sin["CANTIDAD"].apply(_fmt_cantidad_desfase)
    if not df_bod_sin.empty:
        df_bod_sin = df_bod_sin.rename(columns={
            "fecha": "FECHA", "centro_costo": "CUARTEL", "producto": "PRODUCTO",
            "cantidad": "CANTIDAD", "um": "UM",
        })[["FECHA", "CUARTEL", "PRODUCTO", "CANTIDAD", "UM"]]
        df_bod_sin["CANTIDAD"] = df_bod_sin["CANTIDAD"].apply(_fmt_cantidad_desfase)
    return df_lc_sin, df_bod_sin

def _tab_desface_lc_bodega(conn, key_prefix="desf"):
    st.markdown("### ⚠️ Cruce Libro de Campo ↔ Bodega")
    st.caption(
        "Detecta productos **PPPL** registrados en un módulo pero no reflejados en el otro. "
        "Criterio: mismo producto, cuartel, misma unidad de medida y cantidad equivalente (±2 %), "
        "fecha dentro de la ventana indicada."
    )
    c1, c2, c3 = st.columns(3)
    f_desde = c1.date_input("Desde", hoy - timedelta(days=90), key=f"{key_prefix}_fd")
    f_hasta = c2.date_input("Hasta", hoy, key=f"{key_prefix}_fh")
    dias_v = c3.number_input("Ventana días (±)", min_value=1, max_value=60, value=14, key=f"{key_prefix}_dv")
    df_lc_sin, df_bod_sin = _calcular_desfaces_lc_bodega(conn, f_desde, f_hasta, int(dias_v))
    n_lc, n_bod = len(df_lc_sin), len(df_bod_sin)
    if n_lc == 0 and n_bod == 0:
        st.success("✅ No hay desfaces PPPL en el período seleccionado.")
    else:
        if n_lc > 0:
            st.warning(f"**{n_lc}** registro(s) en Libro de Campo **sin salida de bodega** equivalente → corrija en **Bodega → Salida**.")
            st.dataframe(df_lc_sin, use_container_width=True, hide_index=True)
        if n_bod > 0:
            st.warning(f"**{n_bod}** salida(s) de bodega **sin aplicación en Libro de Campo** → corrija en **Libro de Campo → Ingreso aplicación**.")
            st.dataframe(df_bod_sin, use_container_width=True, hide_index=True)

def _banner_independencia_lc_bodega(desde):
    if desde == "libro_campo":
        texto = (
            "Libro de Campo y Bodega son <b>módulos independientes</b>. "
            "Registrar aquí solo archiva la aplicación fitosanitaria. "
            "Debe rebajar el stock en <b>Bodega → Salida</b> (producto, cantidad y cuartel)."
        )
    else:
        texto = (
            "Libro de Campo y Bodega son <b>módulos independientes</b>. "
            "Registrar aquí solo actualiza stock y costos del cuartel. "
            "Si corresponde a una aplicación fitosanitaria, anótela también en "
            "<b>Libro de Campo → Ingreso aplicación</b> (PHI, lote, aplicador)."
        )
    st.markdown(
        f"""<div style="background:#E3F2FD;border-left:5px solid #1565C0;padding:10px 14px;
        border-radius:8px;margin-bottom:10px;font-size:0.92rem;">
        <b>📦 Recuerde:</b> {texto}</div>""",
        unsafe_allow_html=True,
    )

def _mostrar_alertas_cruce_lc_bodega():
    lc = st.session_state.pop("lc_alerta_bodega", None)
    if lc:
        filas = "".join(
            f"<li><b>{html_lib.escape(p['producto'])}</b> — "
            f"{html_lib.escape(f_cantidad(p['gasto_total']))} {html_lib.escape(p.get('um_gasto', DEFAULT_UNIDAD_INSUMO))}</li>"
            for p in lc["productos"]
        )
        huerto = html_lib.escape(str(lc["huerto"]))
        n_app = int(lc["n_app"])
        st.markdown(
            f"""<div style="background:#FFF3E0;border-left:5px solid #E65100;padding:12px 16px;
            border-radius:8px;margin-bottom:12px;font-size:0.93rem;">
            <b>✅ Aplicación N° {n_app:05d} archivada en Libro de Campo.</b><br><br>
            <b>⚠️ Rebajar bodega pendiente</b> — El stock <u>no</u> se descontó automáticamente.<br>
            Vaya a <b>Bodega → Salida</b> e impute al cuartel <b>{huerto}</b>:
            <ul style="margin:8px 0 0;">{filas}</ul></div>""",
            unsafe_allow_html=True,
        )
    bod = st.session_state.pop("bodega_alerta_lc", None)
    if bod:
        cuarteles = ", ".join(html_lib.escape(c) for c in bod["cuarteles"])
        producto = html_lib.escape(str(bod["producto"]))
        cantidad = html_lib.escape(f_cantidad(bod["cantidad"]))
        um_bod = html_lib.escape(str(bod.get("um", DEFAULT_UNIDAD_INSUMO)))
        st.markdown(
            f"""<div style="background:#FFF3E0;border-left:5px solid #E65100;padding:12px 16px;
            border-radius:8px;margin-bottom:12px;font-size:0.93rem;">
            <b>✅ Salida de bodega registrada.</b><br><br>
            <b>⚠️ Libro de Campo pendiente</b> — La aplicación fitosanitaria <u>no</u> se anotó sola.<br>
            Vaya a <b>Libro de Campo → Ingreso aplicación</b> y registre:<br>
            <b>{producto}</b> — {cantidad} {um_bod} — cuartel(es): <b>{cuarteles}</b>
            </div>""",
            unsafe_allow_html=True,
        )
    if st.session_state.pop("bodega_salida_ok", False):
        st.success("✅ Salida de insumo registrada con éxito.")

def _siguiente_n_orden_libro(conn, sector):
    """Correlativo planilla GlobalGAP por cuartel (alineado con módulo GlobalGAP)."""
    res = conn.execute(
        "SELECT MAX(CAST(n_orden AS INTEGER)) FROM libro_campo "
        "WHERE UPPER(sector)=? AND n_orden GLOB '[0-9]*'",
        (str(sector or "").upper(),),
    ).fetchone()[0]
    return str(int(res) + 1 if res is not None else 1)


def _siguiente_n_aplicacion_libro(conn):
    # Histórico archivado usa n_aplicacion >= 10000; no cuenta para el correlativo.
    res = conn.execute(
        "SELECT MAX(CAST(n_aplicacion AS INTEGER)) FROM libro_campo "
        "WHERE n_aplicacion GLOB '[0-9]*' "
        "AND CAST(n_aplicacion AS INTEGER) < 10000"
    ).fetchone()[0]
    return int(res) + 1 if res is not None else 1


def _insertar_linea_libro_campo(conn, fe_app, n_app, huerto, especie, item, total_agua, aplicador, op_cert, maquinaria, tractor, n_orden=None):
    fv_viable = fe_app + timedelta(days=int(item["dias_car"]))
    um_gasto = item.get("um_gasto") or _um_producto_inventario(conn, item["producto"])
    ing = resolver_ingrediente_activo(conn, item["producto"]) or str(item.get("ingrediente") or "").strip()
    # n_orden = correlativo planilla GlobalGAP (por cuartel).
    orden = str(n_orden).strip() if n_orden is not None and str(n_orden).strip() != "" else _siguiente_n_orden_libro(conn, huerto)
    conn.execute(
        """INSERT INTO libro_campo
        (fecha, n_aplicacion, n_orden, sector, especie, producto, ingrediente, dosis, unidad_dosis,
         gasto_total, vol_total, tractor, maquina, aplicadores, fecha_viable, lote_producto,
         operador_certificado, unidad_gasto)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            str(fe_app), n_app, orden, huerto.upper(), especie.strip(), item["producto"].strip(),
            ing, item["dosis"], item["unidad_dosis"], item["gasto_total"],
            total_agua, tractor.strip(), maquinaria.strip(), aplicador.strip(), str(fv_viable),
            item["lote_producto"].strip(), 1 if op_cert else 0, um_gasto,
        ),
    )

def modulo_libro_campo():
    inyectar_fondo_libro_campo()
    encabezado_modulo("Libro de Campo", "📒 LIBRO DE CAMPO AGRICOLA")
    conn = conectar_db()
    if "lc_car" not in st.session_state:
        st.session_state["lc_car"] = []

    sub_tabs = [
        "📥 INGRESO APLICACIÓN",
        "📜 HISTORIAL AUDITABLE",
        "⚠️ DESFASE BODEGA",
        "🍒 PROGRAMA CEREZAS",
        "🟣 PROGRAMA CIRUELOS",
    ]
    if es_admin():
        sub_tabs.append("🛠️ MODIFICAR / ELIMINAR")

    sec_lc = nav_seccion(sub_tabs, "lc_nav", "Sección")

    if sec_lc == sub_tabs[0]:
        _mostrar_alertas_cruce_lc_bodega()
        _banner_independencia_lc_bodega("libro_campo")
        siguiente_correlativo = _siguiente_n_aplicacion_libro(conn)

        st.markdown(f"### 📋 Nueva Orden N° `{siguiente_correlativo:05d}`")
        st.caption("Un evento de aplicación puede incluir **varios productos** fitosanitarios con el mismo N° de orden.")

        st.markdown("#### Datos del evento")
        c1, c2, c3 = st.columns(3)
        fe_app = c1.date_input("Fecha de Aplicación", hoy, key="lca_1")
        huerto = c1.selectbox("Huerto / Cuartel Destino", CENTROS_COSTO, key="lca_2")
        especie = c1.text_input("Especie", value="Cerezos", key="lca_3")
        total_agua = c2.number_input("Total Agua Aplicada (LT)", min_value=0.0, format="%.1f", key="lca_8")
        aplicador = c2.text_input("Nombre de Aplicador(es)", key="lca_10")
        op_cert = c2.checkbox("Operador certificado fitosanitario", key="lca_10b")
        with c3:
            maquinaria = render_select_maquinaria(
                conn,
                key="lca_11",
                label="Maquinaria / Nebulizador",
                tipos=TIPOS_MAQUINARIA_APLICACION,
            )
            tractor = render_select_maquinaria(
                conn,
                key="lca_12",
                label="Tractor utilizado",
                tipos=TIPOS_MAQUINARIA_TRACTOR,
                permitir_vacio=True,
            )

        st.divider()
        st.markdown("#### Agregar producto al evento")
        df_inv_lc = pd.read_sql_query(
            "SELECT producto, stock FROM inventario WHERE stock > 0 ORDER BY producto",
            conn,
        )
        if df_inv_lc.empty:
            st.warning("No hay productos con stock en bodega. Registre compras o apertura de stock antes de anotar aplicaciones.")
            prod_nom = ""
        else:
            prod_nom = st.selectbox(
                "Producto (desde bodega)",
                df_inv_lc["producto"].tolist(),
                key="lca_4",
            )
            stock_disp = float(df_inv_lc.loc[df_inv_lc["producto"] == prod_nom, "stock"].iloc[0])
            um_prod_lc = _um_producto_inventario(conn, prod_nom) if prod_nom else DEFAULT_UNIDAD_INSUMO
            st.caption(f"Stock disponible en bodega: **{f_cantidad(stock_disp)} {um_prod_lc}**")
        ing_default = _ingrediente_pppl_producto(conn, prod_nom) if prod_nom else ""
        with st.form("lc_add_producto", clear_on_submit=True):
            p1, p2, p3 = st.columns(3)
            lote_prod = p1.text_input("Lote del producto (trazabilidad)", key="lca_4b")
            ingre_act = p1.text_input("Ingrediente Activo", value=ing_default, key="lca_5")
            dos_base = p2.number_input("Dosis Base (Por cada 100 LT de Agua)", min_value=0.0, step=0.001, format="%.3f", key="lca_6")
            e_un_dos = p2.selectbox(
                "Unidad de Medida Dosis",
                ["Gramos (g)", "Centímetros Cúbicos (cc)", "Kilogramos (kg)", "Litros (L)"],
                key="lca_7",
            )
            total_prod = p3.number_input("Total Producto Aplicado", min_value=0.0, step=0.01, format="%.2f", key="lca_9")
            dias_pppl = dias_carencia_producto(conn, prod_nom, 0) if prod_nom.strip() else 0
            dias_car = p3.number_input(
                "Período de Carencia / PHI (Días)",
                min_value=0,
                value=int(dias_pppl),
                key="lca_13",
                help="Se sugiere automáticamente si el producto está en PPPL GlobalGAP.",
            )
            if prod_nom and not producto_pppl_aprobado(conn, prod_nom):
                st.warning("Producto no está en PPPL GlobalGAP. Revise en Certificación → PPPL antes de aplicar.")
            if st.form_submit_button("➕ AGREGAR PRODUCTO AL EVENTO"):
                if not prod_nom:
                    st.error("❌ Seleccione un producto con stock en bodega.")
                elif prod_nom.strip() == "":
                    st.error("❌ Ingrese el nombre del producto.")
                elif not producto_pppl_aprobado(conn, prod_nom):
                    st.error("❌ Producto no autorizado en PPPL. Regístrelo en GlobalGAP → PPPL o marque en Bodega.")
                else:
                    st.session_state["lc_car"].append({
                        "producto": prod_nom.strip(),
                        "lote_producto": lote_prod.strip(),
                        "ingrediente": resolver_ingrediente_activo(conn, prod_nom) or ingre_act.strip(),
                        "dosis": dos_base,
                        "unidad_dosis": e_un_dos,
                        "gasto_total": total_prod,
                        "um_gasto": um_prod_lc,
                        "dias_car": int(dias_car),
                    })
                    st.rerun()

        if st.session_state["lc_car"]:
            st.markdown("#### Productos en este evento")
            df_car = pd.DataFrame(st.session_state["lc_car"])
            df_car = df_car.rename(columns={
                "producto": "PRODUCTO",
                "lote_producto": "LOTE",
                "ingrediente": "ING. ACTIVO",
                "dosis": "DOSIS/100L",
                "unidad_dosis": "UNIDAD DOSIS",
                "gasto_total": "TOTAL PROD.",
                "um_gasto": "UM TOTAL",
                "dias_car": "PHI (días)",
            })
            for col in ("DOSIS/100L", "TOTAL PROD."):
                fmt = f_dosis_lc if col == "DOSIS/100L" else f_cantidad
                df_car[col] = df_car[col].apply(fmt)
            st.dataframe(df_car, use_container_width=True)
            b1, b2 = st.columns(2)
            if b1.button("🗑️ QUITAR ÚLTIMO PRODUCTO", key="lc_pop_prod"):
                st.session_state["lc_car"].pop()
                st.rerun()
            if b2.button("💾 VALIDAR Y GUARDAR EVENTO COMPLETO", key="lc_save_event"):
                if not maquinaria:
                    st.error("❌ Seleccione la maquinaria / nebulizador desde la maestra.")
                elif aplicador.strip() == "":
                    st.error("❌ Ingrese el nombre del aplicador.")
                elif total_agua <= 0:
                    st.error("❌ Ingrese el volumen total de agua aplicada.")
                else:
                    n_orden_evt = _siguiente_n_orden_libro(conn, huerto)
                    for item in st.session_state["lc_car"]:
                        _insertar_linea_libro_campo(
                            conn, fe_app, siguiente_correlativo, huerto, especie, item,
                            total_agua, aplicador, op_cert, maquinaria, tractor or "",
                            n_orden=n_orden_evt,
                        )
                    conn.commit()
                    prods_txt = ", ".join(i["producto"] for i in st.session_state["lc_car"])
                    registrar_accion("LIBRO CAMPO", f"App N°{siguiente_correlativo} - {prods_txt}")
                    st.session_state["lc_alerta_bodega"] = {
                        "n_app": siguiente_correlativo,
                        "huerto": huerto,
                        "productos": list(st.session_state["lc_car"]),
                    }
                    st.session_state["lc_car"] = []
                    st.rerun()
        else:
            st.info("Agregue uno o más productos al evento antes de guardar.")

    elif sec_lc == sub_tabs[1]:
        st.markdown("#### 🔍 Motores de Búsqueda Avanzada:")
        cc1, cc2, cc3 = st.columns(3)
        fi_lc = cc1.date_input("Desde", hoy - timedelta(days=180), key="lc_fi")
        ff_lc = cc2.date_input("Hasta", hoy, key="lc_ff")
        q_cuartel = cc3.selectbox("Filtrar por Cuartel", ["TODOS"] + CENTROS_COSTO)

        c_p1, c_p2 = st.columns([2, 1])
        q_prod = c_p1.text_input("Buscar por Nombre de Producto")
        q_app = c_p2.text_input("N° Aplicación", placeholder="Ej: 12")

        filtros = [f"fecha BETWEEN '{fi_lc}' AND '{ff_lc}'"]
        if q_cuartel != "TODOS":
            filtros.append(f"sector = '{q_cuartel.upper()}'")
        if q_prod.strip():
            filtros.append(f"producto LIKE '%{q_prod.strip()}%'")
        if q_app.strip().isdigit():
            filtros.append(f"n_aplicacion = {int(q_app.strip())}")
        where_sql = " AND ".join(filtros)

        query_det = f"""SELECT n_aplicacion as [N° APP], fecha as FECHA, sector as CUARTEL, especie as ESPECIE,
                               producto as PRODUCTO, lote_producto as LOTE, ingrediente as [ING ACTIVO],
                               dosis as [DOSIS 100L], unidad_dosis as UNIDAD, vol_total as [VOL AGUA LT],
                               gasto_total as [TOTAL PROD], aplicadores as APLICADOR,
                               operador_certificado as [OP. CERT.], maquina as MAQUINARIA, tractor as TRACTOR,
                               fecha_viable as [FECHA VIABLE PHI]
                        FROM libro_campo WHERE {where_sql}
                        ORDER BY n_aplicacion DESC, id ASC"""
        dflc_f = pd.read_sql_query(query_det, conn)
        dflc_f = enriquecer_columna_maquinaria(conn, dflc_f, "MAQUINARIA")
        dflc_f = enriquecer_columna_maquinaria(conn, dflc_f, "TRACTOR")
        if not dflc_f.empty and "OP. CERT." in dflc_f.columns:
            dflc_f["OP. CERT."] = dflc_f["OP. CERT."].apply(_fmt_op_cert_libro)

        if not dflc_f.empty:
            boton_pdf(
                "PDF INFORME LIBRO DE CAMPO",
                generar_pdf_libro_campo(dflc_f),
                "libro_campo.pdf",
                key="lc_pdf_btn",
            )
        else:
            boton_pdf("PDF INFORME LIBRO DE CAMPO", None, "libro_campo.pdf", key="lc_pdf_btn")

        st.markdown("##### Registro por evento")
        render_historial_libro_campo_agrupado(dflc_f)

    elif len(sub_tabs) > 2 and sec_lc == sub_tabs[2]:
        _tab_desface_lc_bodega(conn, "lc_desf")

    elif len(sub_tabs) > 3 and sec_lc == sub_tabs[3]:
        _panel_programa_fitosanitario("cerezos")

    elif len(sub_tabs) > 4 and sec_lc == sub_tabs[4]:
        _panel_programa_fitosanitario("ciruelos")

    elif es_admin() and len(sub_tabs) > 5 and sec_lc == sub_tabs[5]:
            st.markdown("### 🛠️ Panel de Modificación / Borrado de Registros")
            df_mod_list = pd.read_sql_query(
                """SELECT n_aplicacion, fecha, sector,
                          GROUP_CONCAT(producto, ' + ') as productos,
                          COUNT(*) as n_prod
                   FROM libro_campo
                   GROUP BY n_aplicacion, fecha, sector
                   ORDER BY n_aplicacion DESC""",
                conn,
            )

            if not df_mod_list.empty:
                sel_app_str = st.selectbox(
                    "Seleccione evento de aplicación",
                    df_mod_list.apply(
                        lambda r: (
                            f"{int(r['n_aplicacion']):05d} | {r['fecha']} | {r['sector']} | "
                            f"{r['productos']} ({int(r['n_prod'])} prod.)"
                        ),
                        axis=1,
                    ).tolist(),
                )
                sel_id_app = int(sel_app_str.split(" | ")[0])

                df_lineas = pd.read_sql_query(
                    "SELECT * FROM libro_campo WHERE n_aplicacion = ? ORDER BY id",
                    conn,
                    params=(sel_id_app,),
                )
                sel_linea_str = st.selectbox(
                    "Línea de producto a editar",
                    df_lineas.apply(
                        lambda r: f"ID {int(r['id'])} | {r['producto']}",
                        axis=1,
                    ).tolist(),
                )
                sel_linea_id = int(sel_linea_str.split(" | ")[0].replace("ID ", ""))
                r_act = df_lineas[df_lineas["id"] == sel_linea_id].iloc[0]

                with st.form("form_edit_libro"):
                    st.markdown(f"#### Editando evento `{sel_id_app:05d}` — {r_act['producto']}")
                    ce1, ce2, ce3 = st.columns(3)

                    f_valida = r_act["fecha"] if r_act["fecha"] else "2026-05-19"
                    e_fecha = ce1.date_input("Modificar Fecha", datetime.strptime(str(f_valida), "%Y-%m-%d").date())
                    e_cuartel = ce1.selectbox(
                        "Modificar Cuartel",
                        CENTROS_COSTO,
                        index=CENTROS_COSTO.index(r_act["sector"]) if r_act["sector"] in CENTROS_COSTO else 0,
                    )
                    e_especie = ce1.text_input("Modificar Especie", r_act["especie"] if r_act["especie"] else "")

                    e_prod = ce2.text_input("Modificar Producto", r_act["producto"] if r_act["producto"] else "")
                    e_lote = ce2.text_input("Modificar Lote", r_act["lote_producto"] if r_act.get("lote_producto") else "")
                    e_ing = ce2.text_input("Modificar Ing. Activo", r_act["ingrediente"] if r_act["ingrediente"] else "")
                    e_dosis = ce2.number_input("Modificar Dosis Base", value=float(r_act["dosis"]) if r_act["dosis"] else 0.0, step=0.001, format="%.3f")

                    u_d_str = str(r_act["unidad_dosis"]) if r_act["unidad_dosis"] else ""
                    opts_u_edit = ["Gramos (g)", "Centímetros Cúbicos (cc)", "Kilogramos (kg)", "Litros (L)"]
                    idx_u_edit = opts_u_edit.index(u_d_str) if u_d_str in opts_u_edit else 0
                    e_un_dos = ce3.selectbox("Modificar Unidad Dosis", opts_u_edit, index=idx_u_edit)

                    e_agua = ce3.number_input("Modificar Vol Agua", value=float(r_act["vol_total"]) if r_act["vol_total"] else 0.0, format="%.1f")
                    e_total_pr = ce3.number_input("Modificar Total Producto", value=float(r_act["gasto_total"]) if r_act["gasto_total"] else 0.0, step=0.01, format="%.2f")

                    fv_actual = r_act["fecha_viable"] if r_act["fecha_viable"] else str(e_fecha)
                    e_fv = ce3.date_input("Modificar Fecha viable PHI", datetime.strptime(str(fv_actual), "%Y-%m-%d").date())

                    st.divider()
                    ce4, ce5, ce6 = st.columns(3)
                    e_apli = ce4.text_input("Modificar Aplicadores", r_act["aplicadores"] if r_act["aplicadores"] else "")
                    with ce5:
                        e_maq = render_select_maquinaria(
                            conn,
                            key="lc_edit_maq",
                            label="Modificar Maquinaria",
                            tipos=TIPOS_MAQUINARIA_APLICACION,
                            valor_actual=r_act["maquina"],
                        )
                    with ce6:
                        e_tract = render_select_maquinaria(
                            conn,
                            key="lc_edit_tract",
                            label="Modificar Tractor",
                            tipos=TIPOS_MAQUINARIA_TRACTOR,
                            valor_actual=r_act["tractor"],
                            permitir_vacio=True,
                        )

                    st.markdown("### 🔐 Autorización:")
                    clv_auth = st.text_input("Ingrese Clave Maestra", type="password", key="clv_lc_edit")

                    b_col1, b_col2, b_col3 = st.columns(3)
                    btn_upd = b_col1.form_submit_button("✏️ ACTUALIZAR LÍNEA")
                    btn_del_line = b_col2.form_submit_button("🗑️ ELIMINAR LÍNEA")
                    btn_del_evt = b_col3.form_submit_button("🗑️ ELIMINAR EVENTO COMPLETO")

                    if btn_upd:
                        if clv_auth == CLAVE_MAESTRA:
                            if not e_maq:
                                st.error("❌ Seleccione maquinaria desde la maestra.")
                            else:
                                conn.execute(
                                    """UPDATE libro_campo SET
                                       fecha=?, sector=?, especie=?, producto=?, lote_producto=?, ingrediente=?,
                                       dosis=?, unidad_dosis=?, vol_total=?, gasto_total=?, aplicadores=?,
                                       maquina=?, tractor=?, fecha_viable=?
                                       WHERE id=?""",
                                    (
                                        str(e_fecha), e_cuartel.upper(), e_especie.strip(), e_prod.strip(),
                                        e_lote.strip(), e_ing.strip(), e_dosis, e_un_dos, e_agua, e_total_pr,
                                        e_apli.strip(), e_maq, e_tract or "", str(e_fv), sel_linea_id,
                                    ),
                                )
                                conn.commit()
                                registrar_accion("UPDATE LIBRO", f"App N°{sel_id_app} línea {sel_linea_id}")
                                st.success("✅ Línea actualizada correctamente.")
                                st.cache_data.clear()
                                st.rerun()
                        else:
                            st.error("❌ Clave Maestra Incorrecta.")

                    if btn_del_line:
                        if clv_auth == CLAVE_MAESTRA:
                            conn.execute("DELETE FROM libro_campo WHERE id = ?", (sel_linea_id,))
                            conn.commit()
                            registrar_accion("DELETE LIBRO LINEA", f"App N°{sel_id_app} id {sel_linea_id}")
                            st.warning("🗑️ Línea de producto eliminada.")
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error("❌ Clave Maestra Incorrecta.")

                    if btn_del_evt:
                        if clv_auth == CLAVE_MAESTRA:
                            conn.execute("DELETE FROM libro_campo WHERE n_aplicacion = ?", (sel_id_app,))
                            conn.commit()
                            registrar_accion("DELETE LIBRO", f"App N°{sel_id_app} completo")
                            st.warning("🗑️ Evento completo eliminado.")
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error("❌ Clave Maestra Incorrecta.")
            else:
                st.info("No hay aplicaciones ingresadas.")

    conn.close()

def _fechas_consulta_contratistas_cc(conn, cc_u):
    return fechas_consulta_contratistas_cc(conn, cc_u)

def modulo_rrhh():
    encabezado_modulo("RRHH", "👥 RECURSOS HUMANOS")
    _rrhh_sincronizar_mes_calendario()
    conn = conectar_db()
    _rh_secc = [
        "📋 PERSONAL", "🤝 CONTRATISTAS", "💼 REMUNERACIONES",
        "💸 LIQUIDACIÓN MENSUAL", "📜 HISTORIAL PAGOS",
    ]
    sec_rh = nav_seccion(_rh_secc, "rrhh_nav", "Sección")

    if sec_rh == _rh_secc[0]:
        with st.form("rh_p", clear_on_submit=True):
            n = st.text_input("Nombre Completo Trabajador", key="rhp_n")
            r = st.text_input("RUT", key="rhp_r")
            c = st.text_input("Cargo", key="rhp_c")
            f_cont = st.date_input("Fecha Contrato", hoy, key="rhp_f")
            if st.form_submit_button("REGISTRAR NUEVO TRABAJADOR"):
                ok_rut, msg_rut, rut_fmt = validar_rut_campo(r, obligatorio=True)
                if n.strip() == "":
                    st.error("Ingrese el nombre del trabajador.")
                elif not ok_rut:
                    st.error(msg_rut)
                else:
                    conn.execute("INSERT INTO personal (nombre, rut, cargo, fecha_contrato) VALUES (?,?,?,?)", (n.strip(), rut_fmt, c.strip(), str(f_cont)))
                    conn.commit(); registrar_accion("RRHH", n)
                    st.success("✅ Trabajador registrado.")
                    st.rerun()
        df_p = pd.read_sql_query("SELECT * FROM personal", conn)
        st.dataframe(df_p, use_container_width=True)
        if st.session_state['email'] == 'osvaldolira@laconcepcion.cl' and not df_p.empty:
            st.divider(); id_p = st.selectbox("ID Personal a Gestionar", df_p['id'], key="rh_edit_id")
            isel = df_p[df_p['id']==id_p].iloc[0]
            un, ur, uc = st.text_input("Modificar Nombre", isel['nombre']), st.text_input("Modificar RUT", isel['rut']), st.text_input("Modificar Cargo", isel['cargo'])
            
            f_cont_ant = isel['fecha_contrato']
            if not f_cont_ant or str(f_cont_ant).strip() == "" or str(f_cont_ant).lower() == "none":
                fecha_objeto_segura = hoy
            else:
                try: fecha_objeto_segura = datetime.strptime(str(f_cont_ant), "%Y-%m-%d").date()
                except: fecha_objeto_segura = hoy
                
            ue_fecha_cont = st.date_input("Modificar Fecha Contrato", fecha_objeto_segura)
            
            col1, col2 = st.columns(2)
            if col1.button("✏️ MODIFICAR REGISTRO PERSONAL"):
                if st.text_input("Master", type="password", key="rh_p1") == CLAVE_MAESTRA:
                    ok_rut, msg_rut, rut_fmt = validar_rut_campo(ur, obligatorio=True)
                    if not ok_rut:
                        st.error(msg_rut)
                    else:
                        conn.execute("UPDATE personal SET nombre=?, rut=?, cargo=?, fecha_contrato=? WHERE id=?", (un, rut_fmt, uc, str(ue_fecha_cont), id_p))
                        conn.commit(); registrar_accion("UPDATE RRHH", un)
                        st.success("✏️ Ficha actualizada.")
                        st.rerun()
            if col2.button("🗑️ ELIMINAR TRABAJADOR"):
                if st.text_input("Master", type="password", key="rh_p2") == CLAVE_MAESTRA:
                    conn.execute("DELETE FROM personal WHERE id=?", (id_p,))
                    conn.commit(); registrar_accion("DELETE RRHH", isel['nombre'])
                    st.warning("🗑️ Trabajador borrado.")
                    st.rerun()

    elif sec_rh == _rh_secc[1]:
        st.caption(
            "Maestro de contratistas y registro de servicios. "
            "Los contratistas se gestionan aquí (no en maestra de proveedores). "
            "Cada servicio imputa al CC seleccionado y aparece en Costos como **Contratistas**."
        )
        _rh_ct_secc = [
            "📇 Maestro", "📝 Registrar servicio", "📊 Por centro de costo", "📒 Cuenta corriente",
        ]
        sec_rh_ct = nav_seccion(_rh_ct_secc, "rrhh_cont_nav", "Contratistas")

        if sec_rh_ct == _rh_ct_secc[0]:
            with st.form("rh_cont_alta", clear_on_submit=True):
                c1, c2 = st.columns(2)
                crut = c1.text_input("RUT", key="rh_ct_rut")
                crazon = c1.text_input("Razón social", key="rh_ct_al_razon")
                crubro = c2.text_input("Rubro (poda, riego, etc.)", key="rh_ct_rubro")
                ccontacto = c2.text_input("Contacto", key="rh_ct_contacto")
                cemail = c1.text_input("Mail de contacto", key="rh_ct_email")
                cmail_pago = c2.checkbox(
                    "Enviar mail de respaldo al pagar en Tesorería",
                    value=False,
                    key="rh_ct_mail_pago",
                )
                ccelular = c1.text_input("Celular WhatsApp (+569…)", key="rh_ct_celular")
                cwa_pago = c2.checkbox(
                    "Enviar WhatsApp al pagar en Tesorería",
                    value=False,
                    key="rh_ct_wa_pago",
                )
                cchab = st.selectbox(
                    "CC habitual (default al cargar servicio)",
                    ["—"] + CENTROS_COSTO,
                    key="rh_ct_cc",
                )
                cnotas = st.text_area("Notas", key="rh_ct_notas")
                if st.form_submit_button("REGISTRAR CONTRATISTA"):
                    ok_rut, msg_rut, rut_fmt = validar_rut_campo(crut, obligatorio=False)
                    if not crazon.strip():
                        st.error("❌ La razón social es obligatoria.")
                    elif not ok_rut:
                        st.error(msg_rut)
                    else:
                        cc_h = None if cchab == "—" else cchab
                        conn.execute(
                            """INSERT INTO contratistas
                               (rut, razon_social, rubro, contacto, cc_habitual, estado, notas,
                                email, mail_pago, celular, whatsapp_pago)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                            (
                                rut_fmt, crazon.strip(), crubro.strip(), ccontacto.strip(),
                                cc_h, "Activo", cnotas.strip(), cemail.strip(),
                                1 if cmail_pago else 0, ccelular.strip(), 1 if cwa_pago else 0,
                            ),
                        )
                        excluir_contratista_de_maestra_proveedores(conn, crazon.strip())
                        conn.commit()
                        registrar_accion("RRHH CONTRATISTA", crazon.strip())
                        st.success("✅ Contratista registrado.")
                        st.rerun()
            df_ct = pd.read_sql_query(
                """SELECT id, rut as RUT, razon_social as [RAZÓN SOCIAL], rubro as RUBRO, contacto as CONTACTO,
                          email as MAIL, celular as CELULAR,
                          CASE WHEN mail_pago=1 THEN 'Sí' ELSE 'No' END as [MAIL PAGO],
                          CASE WHEN whatsapp_pago=1 THEN 'Sí' ELSE 'No' END as [WA PAGO],
                          cc_habitual as [CC HABITUAL], estado as ESTADO
                   FROM contratistas ORDER BY razon_social""",
                conn,
            )
            st.dataframe(df_ct, use_container_width=True, hide_index=True)
            if es_admin() and not df_ct.empty:
                st.divider()
                id_ct = st.selectbox("Contratista a gestionar", df_ct["id"], key="rh_ct_edit_id")
                fila_ct = df_ct[df_ct["id"] == id_ct].iloc[0]
                row_db = conn.execute(
                    """SELECT id, rut, razon_social, rubro, contacto, cc_habitual, estado, notas,
                              COALESCE(email, ''), COALESCE(mail_pago, 0),
                              COALESCE(celular, ''), COALESCE(whatsapp_pago, 0)
                       FROM contratistas WHERE id=?""",
                    (id_ct,),
                ).fetchone()
                eu, er, eub, econt = st.columns(4)
                nur = eu.text_input("RUT", value=str(row_db[1] or ""), key="rh_ct_e_rut")
                nraz = er.text_input("Razón social", value=str(row_db[2] or ""), key="rh_ct_e_razon")
                nrub = eub.text_input("Rubro", value=str(row_db[3] or ""), key="rh_ct_e_rubro")
                ncont = econt.text_input("Contacto", value=str(row_db[4] or ""), key="rh_ct_e_cont")
                e1, e2 = st.columns(2)
                nemail = e1.text_input("Mail de contacto", value=str(row_db[8] or ""), key="rh_ct_e_email")
                nmail_pago = e2.checkbox(
                    "Enviar mail de respaldo al pagar en Tesorería",
                    value=bool(row_db[9]),
                    key="rh_ct_e_mail_pago",
                )
                w1, w2 = st.columns(2)
                ncelular = w1.text_input("Celular WhatsApp (+569…)", value=str(row_db[10] or ""), key="rh_ct_e_cel")
                nwa_pago = w2.checkbox(
                    "Enviar WhatsApp al pagar en Tesorería",
                    value=bool(row_db[11]),
                    key="rh_ct_e_wa_pago",
                )
                cc_opts = ["—"] + CENTROS_COSTO
                cc_val = str(row_db[5] or "—")
                ncc = st.selectbox(
                    "CC habitual",
                    cc_opts,
                    index=cc_opts.index(cc_val) if cc_val in cc_opts else 0,
                    key="rh_ct_e_cc",
                )
                nest = st.selectbox("Estado", ["Activo", "Inactivo"], index=0 if row_db[6] == "Activo" else 1, key="rh_ct_e_est")
                nnotas = st.text_area("Notas", value=str(row_db[7] or ""), key="rh_ct_e_notas")
                if st.button("✏️ ACTUALIZAR CONTRATISTA", key="rh_ct_upd"):
                    if st.text_input("Clave maestra", type="password", key="rh_ct_cl_up") == CLAVE_MAESTRA:
                        ok_rut, msg_rut, rut_fmt = validar_rut_campo(nur, obligatorio=False)
                        if not ok_rut:
                            st.error(msg_rut)
                        else:
                            conn.execute(
                                """UPDATE contratistas
                                   SET rut=?, razon_social=?, rubro=?, contacto=?, cc_habitual=?, estado=?, notas=?,
                                       email=?, mail_pago=?, celular=?, whatsapp_pago=?
                                   WHERE id=?""",
                                (
                                    rut_fmt, nraz.strip(), nrub.strip(), ncont.strip(),
                                    None if ncc == "—" else ncc, nest, nnotas.strip(),
                                    nemail.strip(), 1 if nmail_pago else 0,
                                    ncelular.strip(), 1 if nwa_pago else 0, id_ct,
                                ),
                            )
                            excluir_contratista_de_maestra_proveedores(conn, nraz.strip())
                            conn.commit()
                            st.success("✅ Contratista actualizado.")
                            st.rerun()

        elif sec_rh_ct == _rh_ct_secc[1]:
            df_act_ct = pd.read_sql_query(
                "SELECT id, razon_social, cc_habitual FROM contratistas WHERE estado='Activo' ORDER BY razon_social",
                conn,
            )
            if df_act_ct.empty:
                st.info("Registre contratistas activos en la pestaña Maestro.")
            else:
                opts_ct = df_act_ct["id"].astype(str) + " - " + df_act_ct["razon_social"]
                sel_ct = st.selectbox("Contratista", opts_ct, key="rh_ct_srv_sel")
                cid = int(sel_ct.split(" - ")[0])
                fila_srv = df_act_ct[df_act_ct["id"] == cid].iloc[0]
                cc_default = str(fila_srv.get("cc_habitual") or "")
                sin_doc_ct = st.checkbox("¿Sin documento oficial? (folio interno)", key="rh_ct_sin_doc")
                with st.form("rh_cont_srv", clear_on_submit=True):
                    c_a, c_b = st.columns(2)
                    if sin_doc_ct:
                        ndoc_ct = c_a.text_input("N° documento", value="AUTOGENERADO", disabled=True, key="rh_ct_ndoc")
                    else:
                        ndoc_ct = c_a.text_input("N° factura / boleta", key="rh_ct_ndoc")
                    f_srv = c_a.date_input("Fecha servicio", hoy, key="rh_ct_f")
                    fv_srv = c_b.date_input("Vencimiento", hoy, key="rh_ct_fv")
                    razon_ct = c_b.selectbox("Razón social", RAZONES_SOCIALES_COMPRAS, key="rh_ct_srv_razon")
                    concepto_ct = st.text_input("Servicio / concepto", key="rh_ct_concepto")
                    st.caption("Centros de costo (checkbox)")
                    selcc_ct = []
                    for cc in CENTROS_COSTO:
                        default_on = cc == cc_default
                        if st.checkbox(cc, value=default_on, key=f"rh_ct_cc_{cid}_{cc}"):
                            selcc_ct.append(cc)
                    mt_ct = st.number_input("Monto bruto ($)", min_value=0.0, key="rh_ct_monto")
                    iva_ct = st.radio("Imputar bruto?", ["SI", "NO (NETO)"], key="rh_ct_iva")
                    if st.form_submit_button("💾 REGISTRAR SERVICIO"):
                        if not concepto_ct.strip():
                            st.error("❌ Ingrese el concepto del servicio.")
                        elif mt_ct <= 0:
                            st.error("❌ El monto debe ser superior a $0.")
                        elif not selcc_ct:
                            st.error("❌ Seleccione al menos un centro de costo.")
                        else:
                            if sin_doc_ct:
                                ndoc_final = _siguiente_folio_contratista(conn, f_srv)
                            else:
                                ndoc_final = ndoc_ct.strip()
                            if not ndoc_final:
                                st.error("❌ N° documento obligatorio.")
                            else:
                                prov_ct = str(fila_srv["razon_social"])
                                ok, err = _registrar_servicio_contratista(
                                    conn, cid, prov_ct, ndoc_final, f_srv, fv_srv, mt_ct,
                                    concepto_ct, selcc_ct, razon_ct, imputar_bruto=(iva_ct == "SI"),
                                )
                                if not ok:
                                    st.error(f"❌ {err}")
                                else:
                                    conn.commit()
                                    registrar_accion("RRHH CONTRATISTA SERVICIO", f"{prov_ct} {ndoc_final}")
                                    st.success(f"✅ Servicio registrado ({ndoc_final}) — imputado a Costos / Contratistas.")
                                    st.rerun()

        elif sec_rh_ct == _rh_ct_secc[2]:
            cc_f = st.selectbox("Centro de costo", CENTROS_COSTO, key="rh_ct_v_cc")
            cc_u = cc_f.upper()
            ct_rows = listar_contratistas(conn, solo_activos=False)
            ct_opts = {"Todos": None}
            for cid, raz, _rut, _est in ct_rows:
                ct_opts[str(raz)] = int(cid)
            ct_sel = st.selectbox(
                "Contratista",
                list(ct_opts.keys()),
                key="rh_ct_v_contratista",
                help="Varios contratistas pueden imputar al mismo CC. Filtre uno o vea todos.",
            )
            ct_id_f = ct_opts.get(ct_sel)
            fi_def, ff_def = _fechas_consulta_contratistas_cc(conn, cc_u)
            if st.session_state.get("rh_ct_v_cc_prev") != cc_f:
                st.session_state["rh_ct_v_fi2"] = fi_def
                st.session_state["rh_ct_v_ff2"] = ff_def
                st.session_state["rh_ct_v_cc_prev"] = cc_f
            c_f1, c_f2 = st.columns(2)
            fi_ct = c_f1.date_input("Desde", value=fi_def, key="rh_ct_v_fi2")
            ff_ct = c_f2.date_input("Hasta", value=ff_def, key="rh_ct_v_ff2")
            df_srv_cc = query_imputaciones_contratistas_cc(
                conn, cc_u, fi_ct, ff_ct, contratista_id=ct_id_f,
            )
            if df_srv_cc.empty:
                st.info("Sin servicios de contratistas en este CC y período.")
            else:
                total_cc = df_srv_cc["MONTO"].sum()
                n_ct = df_srv_cc["CONTRATISTA"].nunique()
                st.caption(
                    f"**{cc_f}** · {len(df_srv_cc)} movimiento(s) · "
                    f"{n_ct} contratista(s) · Total imputado: **${f_puntos(total_cc)}**"
                )
                if n_ct > 1 and ct_id_f is None:
                    st.info(
                        "Hay más de un contratista en este CC. Use el filtro **Contratista** "
                        "o la pestaña **Cuenta corriente** para ver generado vs pagado por persona."
                    )
                st.dataframe(
                    df_srv_cc.style.format({"MONTO": _fmt_styler_peso}),
                    use_container_width=True,
                    hide_index=True,
                )
                titulo_pdf = (
                    f"CONTRATISTAS - {cc_f.upper()} "
                    f"({fi_ct.strftime('%d-%m-%Y')} al {ff_ct.strftime('%d-%m-%Y')})"
                )
                if ct_id_f:
                    titulo_pdf = f"{ct_sel.upper()} - {titulo_pdf}"
                boton_pdf(
                    "PDF CONTRATISTAS",
                    generar_pdf_blob(
                        df_srv_cc,
                        titulo_pdf,
                        campo_suma_forzado="MONTO",
                    ),
                    f"contratistas_{cc_f.lower()}_{fi_ct}_{ff_ct}.pdf",
                    key=f"rh_ct_pdf_{cc_f}_{ct_sel}",
                )

        elif sec_rh_ct == _rh_ct_secc[3]:
            st.caption(
                "Libro mayor por **contratista**: cada **trabajo** (DEBE) y cada **pago** (HABER) "
                "en filas separadas, con **saldo** acumulado al costado."
            )
            ct_rows_act = listar_contratistas(conn, solo_activos=True)
            if not ct_rows_act:
                st.info("Registre contratistas activos en la pestaña Maestro.")
            else:
                ct_map = {f"{r[1]}": int(r[0]) for r in ct_rows_act}
                ct_cta = st.selectbox(
                    "Contratista",
                    list(ct_map.keys()),
                    key="rh_ct_cta_sel",
                )
                cc_opts = ["Todos los CC"] + CENTROS_COSTO
                cc_cta = st.selectbox("Filtrar por CC (opcional)", cc_opts, key="rh_ct_cta_cc")
                cc_cta_u = None if cc_cta == "Todos los CC" else cc_cta.upper()
                cta1, cta2 = st.columns(2)
                fi_cta = cta1.date_input(
                    "Desde",
                    hoy - timedelta(days=365),
                    key="rh_ct_cta_fi",
                )
                ff_cta = cta2.date_input("Hasta", hoy, key="rh_ct_cta_ff")
                df_cta, razon_cta = query_cuenta_corriente_contratista(
                    conn, ct_map[ct_cta], fi_cta, ff_cta, cc_u=cc_cta_u,
                )
                if df_cta.empty:
                    st.info("Sin movimientos para este contratista y período.")
                else:
                    tot_gen = float(df_cta["DEBE"].sum())
                    tot_pag = float(df_cta["HABER"].sum())
                    saldo_final = float(df_cta["SALDO"].iloc[-1])
                    st.caption(
                        f"**{razon_cta}** · Trabajos **${f_puntos(tot_gen)}** · "
                        f"Pagos **${f_puntos(tot_pag)}** · Saldo **${f_puntos(saldo_final)}**"
                    )
                    st.dataframe(
                        df_cta.style.format({
                            "DEBE": _fmt_styler_peso,
                            "HABER": _fmt_styler_peso,
                            "SALDO": _fmt_styler_peso,
                        }),
                        use_container_width=True,
                        hide_index=True,
                    )
                    suf_cc = f"_{cc_cta.lower().replace(' ', '_')}" if cc_cta_u else ""
                    titulo_cta = (
                        f"CTA CTE {razon_cta.upper()} "
                        f"({fi_cta.strftime('%d-%m-%Y')} al {ff_cta.strftime('%d-%m-%Y')})"
                    )
                    titulo_cta += f" - CC {cc_cta_u}" if cc_cta_u else " - TODOS LOS CENTROS DE COSTOS"
                    boton_pdf(
                        "PDF CUENTA CORRIENTE",
                        generar_pdf_blob(
                            df_cta,
                            titulo_cta,
                            incluir_precios=False,
                            orden_asc=True,
                        ),
                        f"cta_cte_{ct_map[ct_cta]}{suf_cc}.pdf",
                        key=f"rh_cta_pdf_{ct_map[ct_cta]}",
                    )

    elif sec_rh == _rh_secc[2]:
        df_act = pd.read_sql_query("SELECT id, nombre FROM personal WHERE estado='Activo'", conn)
        if not df_act.empty:
            meses_rrhh = ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"]
            if "rh_prov_m" not in st.session_state:
                st.session_state["rh_prov_m"] = hora_chile().strftime("%m")
            if "rh_prov_a" not in st.session_state:
                st.session_state["rh_prov_a"] = int(hora_chile().year)
            st.subheader("💰 Planilla de provisión (fin de mes)")
            c_prov1, c_prov2 = st.columns(2)
            prov_m = c_prov1.selectbox("Mes planilla", meses_rrhh, key="rh_prov_m")
            prov_a = int(c_prov2.number_input("Año planilla", min_value=2020, max_value=2040, key="rh_prov_a"))
            st.caption(
                f"Mes **{prov_m}/{prov_a}**: registre lo ganado, suple y descuento de préstamo. "
                "**Líquido a provisionar = Líquido ganado − Suple − Descuento préstamo**. "
                "Si hay préstamo vigente, se **sugiere la cuota referencia** (editable). "
                "Independiente de Liquidación."
            )

            st.divider()
            st.subheader("Configuración de Remuneración Fija")
            st.caption(
                f"Al **guardar sueldo y suple** se actualiza también la planilla de **{prov_m}/{prov_a}** "
                "para el trabajador seleccionado."
            )
            ts = st.selectbox("Seleccionar Trabajador", df_act['id'].astype(str) + " - " + df_act['nombre'], key="rh_remu_1")
            tid = int(ts.split(" - ")[0])
            _actualizar_cuotas_pagadas_desde_descuentos(conn, tid)
            ficha_act = conn.execute(
                """SELECT sueldo_pactado, monto_prestamo, cuotas_prestamo, cuotas_pagadas, suple_fijo,
                          primera_cuota_mes, primera_cuota_anio
                   FROM remuneraciones_fichas WHERE trabajador_id=?""",
                (tid,),
            ).fetchone()
            info_prest = _info_prestamo_worker(conn, tid)

            with st.form("rh_remu_f", clear_on_submit=True):
                p_sueldo = st.number_input(
                    "Sueldo Líquido Pactado ($)", value=float(ficha_act[0]) if ficha_act else 0.0, key="rh_rf_1",
                )
                p_suple = st.number_input(
                    "Suple Fijo Mensual ($)", value=float(ficha_act[4]) if ficha_act else 0.0, key="rh_rf_4",
                )
                if st.form_submit_button("GUARDAR SUELDO Y SUPLE"):
                    m_prest = float(ficha_act[1]) if ficha_act else 0.0
                    c_prest = int(ficha_act[2]) if ficha_act else 0
                    c_pag = int(ficha_act[3]) if ficha_act else 0
                    pc_m = ficha_act[5] if ficha_act and len(ficha_act) > 5 else None
                    pc_a = ficha_act[6] if ficha_act and len(ficha_act) > 6 else None
                    conn.execute(
                        """INSERT OR REPLACE INTO remuneraciones_fichas
                           (trabajador_id, sueldo_pactado, monto_prestamo, cuotas_prestamo, cuotas_pagadas,
                            suple_fijo, primera_cuota_mes, primera_cuota_anio)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (tid, p_sueldo, m_prest, c_prest, c_pag, p_suple, pc_m, pc_a),
                    )
                    row_desc = conn.execute(
                        """SELECT COALESCE(descuento_prestamo, 0) FROM remuneracion_mes
                           WHERE trabajador_id=? AND mes=? AND anio=?""",
                        (tid, _mes_rrhh_norm(prov_m), prov_a),
                    ).fetchone()
                    desc_mes = float(row_desc[0] or 0) if row_desc else 0.0
                    desc_aplicar = _descuento_cuota_sugerida(conn, tid, prov_m, prov_a, desc_mes)
                    ok_rm, err_rm = _guardar_remuneracion_mes(
                        conn, tid, prov_m, prov_a, p_sueldo, p_suple, desc_aplicar,
                    )
                    if not ok_rm:
                        conn.commit()
                        st.error(err_rm)
                    else:
                        conn.commit()
                        registrar_accion("RRHH FICHA", f"{ts} planilla {prov_m}/{prov_a}")
                        st.success(f"✅ Sueldo/suple guardados y reflejados en planilla {prov_m}/{prov_a}.")
                        st.rerun()

            if info_prest["monto"] > 0:
                st.markdown("##### 💳 Estado del crédito (vigente)")
                cp, cd, cs, cr = st.columns(4)
                cp.metric("Préstamo original", f"${f_puntos(info_prest['monto'])}")
                cd.metric("Total descontado", f"${f_puntos(info_prest['descontado'])}")
                cs.metric("Saldo pendiente", f"${f_puntos(info_prest['saldo'])}")
                cr.metric("Cuota referencia", f"${f_puntos(info_prest['cuota_ref'])}")
                if info_prest.get("primera_cuota_mes") and info_prest.get("primera_cuota_anio"):
                    st.caption(
                        f"Primera cuota: **{info_prest['primera_cuota_mes']}/{info_prest['primera_cuota_anio']}**"
                    )
                if ficha_act:
                    rest = max(0, int(ficha_act[2] or 0) - int(ficha_act[3] or 0))
                    st.caption(f"Cuotas: {int(ficha_act[3] or 0)} pagadas de {int(ficha_act[2] or 0)} · Restantes: {rest}")
                if info_prest["saldo"] <= 0:
                    st.success("Préstamo saldado.")
            else:
                with st.form("rh_nuevo_prestamo", clear_on_submit=True):
                    st.markdown("##### ➕ Registrar nuevo préstamo")
                    np_monto = st.number_input("Monto préstamo total ($)", min_value=0.0, key="rh_np_m")
                    np_cuotas = st.number_input("Cuotas pactadas", min_value=0, step=1, key="rh_np_c")
                    np_primera = st.date_input(
                        "Primera cuota (mes/año)",
                        value=_primera_cuota_date_default(),
                        help="Mes en que se aplica el primer descuento en la planilla.",
                        key="rh_np_primera",
                    )
                    if np_cuotas > 0 and np_monto > 0:
                        st.caption(f"Cuota referencia: ${f_puntos(np_monto / np_cuotas)}")
                    if st.form_submit_button("REGISTRAR PRÉSTAMO"):
                        pc_m, pc_a = _mes_anio_desde_fecha(np_primera)
                        conn.execute(
                            """INSERT OR REPLACE INTO remuneraciones_fichas
                               (trabajador_id, sueldo_pactado, monto_prestamo, cuotas_prestamo, cuotas_pagadas,
                                suple_fijo, primera_cuota_mes, primera_cuota_anio)
                               VALUES (?,?,?,?,?,?,?,?)""",
                            (
                                tid,
                                float(ficha_act[0]) if ficha_act else 0.0,
                                np_monto,
                                int(np_cuotas),
                                0,
                                float(ficha_act[4]) if ficha_act else 0.0,
                                pc_m,
                                pc_a,
                            ),
                        )
                        conn.commit()
                        registrar_accion("RRHH PRESTAMO NUEVO", ts)
                        st.success("Préstamo registrado.")
                        st.rerun()

            with st.expander("✏️ Modificar términos del crédito (contrato)"):
                with st.form("rh_edit_prestamo"):
                    ep_monto = st.number_input(
                        "Monto préstamo total ($)",
                        min_value=0.0,
                        value=float(ficha_act[1]) if ficha_act else 0.0,
                        key="rh_ep_m",
                    )
                    ep_cuotas = st.number_input(
                        "Cuotas pactadas",
                        min_value=0,
                        value=int(ficha_act[2]) if ficha_act else 0,
                        key="rh_ep_c",
                    )
                    ep_primera = st.date_input(
                        "Primera cuota (mes/año)",
                        value=_primera_cuota_date_default(ficha_act),
                        help="Mes en que se aplica el primer descuento en la planilla.",
                        key="rh_ep_primera",
                    )
                    if st.form_submit_button("ACTUALIZAR CRÉDITO"):
                        c_pag = int(ficha_act[3]) if ficha_act else 0
                        if ep_cuotas < c_pag:
                            c_pag = ep_cuotas
                        ep_m, ep_a = _mes_anio_desde_fecha(ep_primera)
                        conn.execute(
                            """INSERT OR REPLACE INTO remuneraciones_fichas
                               (trabajador_id, sueldo_pactado, monto_prestamo, cuotas_prestamo, cuotas_pagadas,
                                suple_fijo, primera_cuota_mes, primera_cuota_anio)
                               VALUES (?,?,?,?,?,?,?,?)""",
                            (
                                tid,
                                float(ficha_act[0]) if ficha_act else 0.0,
                                ep_monto,
                                int(ep_cuotas),
                                c_pag,
                                float(ficha_act[4]) if ficha_act else 0.0,
                                ep_m,
                                ep_a,
                            ),
                        )
                        _actualizar_cuotas_pagadas_desde_descuentos(conn, tid)
                        conn.commit()
                        registrar_accion("RRHH PRESTAMO EDIT", ts)
                        st.success("Crédito actualizado.")
                        st.rerun()

            st.divider(); st.subheader("📒 Registro de Préstamos y Cuotas")
            q_prestamos = """SELECT p.nombre as TRABAJADOR,
                               f.monto_prestamo as PRESTAMO_TOTAL,
                               f.cuotas_prestamo as CUOTAS_PACTADAS,
                               COALESCE(f.cuotas_pagadas, 0) as CUOTAS_PAGADAS,
                               CASE WHEN f.primera_cuota_mes IS NOT NULL AND f.primera_cuota_anio IS NOT NULL
                                    THEN printf('%02d', CAST(f.primera_cuota_mes AS INTEGER)) || '/' || f.primera_cuota_anio
                                    ELSE 'Inmediato' END as PRIMERA_CUOTA,
                               COALESCE((
                                   SELECT SUM(descuento_prestamo) FROM remuneracion_mes WHERE trabajador_id = p.id
                               ), 0) as TOTAL_DESCONTADO,
                               MAX(0, f.monto_prestamo - COALESCE((
                                   SELECT SUM(descuento_prestamo) FROM remuneracion_mes WHERE trabajador_id = p.id
                               ), 0)) as SALDO_PENDIENTE,
                               CASE WHEN f.cuotas_prestamo > 0 THEN f.monto_prestamo / f.cuotas_prestamo ELSE 0 END as CUOTA_REFERENCIA
                               FROM personal p
                               JOIN remuneraciones_fichas f ON p.id = f.trabajador_id
                               WHERE p.estado='Activo' AND f.monto_prestamo > 0"""
            df_prest = pd.read_sql_query(q_prestamos, conn).fillna(0)
            if not df_prest.empty:
                st.caption(
                    "Saldo según descuentos registrados en la **planilla de Remuneraciones** de cada mes."
                )
                st.dataframe(df_prest.style.format({
                    c: _fmt_styler_peso for c in df_prest.columns
                    if c not in ("TRABAJADOR", "CUOTAS_PACTADAS", "CUOTAS_PAGADAS", "PRIMERA_CUOTA")
                }), use_container_width=True)
            else:
                st.info("No hay préstamos registrados.")

            st.divider(); st.subheader("📋 Detalle planilla del mes")
            q_prov = """SELECT p.id as trabajador_id, p.nombre as TRABAJADOR,
                        CASE WHEN r.trabajador_id IS NOT NULL
                             THEN COALESCE(r.liquido_ganado, 0)
                             ELSE COALESCE(f.sueldo_pactado, 0) END as LIQUIDO_GANADO,
                        CASE WHEN r.trabajador_id IS NOT NULL
                             THEN COALESCE(r.suple, 0)
                             ELSE COALESCE(f.suple_fijo, 0) END as SUPLE,
                        COALESCE(r.descuento_prestamo, 0) as DESCUENTO_PRESTAMO,
                        MAX(0, COALESCE(f.monto_prestamo, 0) - COALESCE((
                            SELECT SUM(descuento_prestamo) FROM remuneracion_mes WHERE trabajador_id = p.id
                        ), 0)) as SALDO_PRESTAMO,
                        CASE WHEN COALESCE(f.cuotas_prestamo, 0) > 0
                             THEN f.monto_prestamo / f.cuotas_prestamo ELSE 0 END as CUOTA_REFERENCIA
                        FROM personal p
                        LEFT JOIN remuneraciones_fichas f ON p.id = f.trabajador_id
                        LEFT JOIN remuneracion_mes r ON r.trabajador_id = p.id
                            AND r.mes = ? AND r.anio = ?
                        WHERE p.estado = 'Activo'
                        ORDER BY p.nombre"""
            df_prov = pd.read_sql_query(q_prov, conn, params=(prov_m, prov_a)).fillna(0)
            if not df_prov.empty:
                for idx, row in df_prov.iterrows():
                    tid_p = int(row["trabajador_id"])
                    desc_raw = float(row["DESCUENTO_PRESTAMO"] or 0)
                    df_prov.at[idx, "DESCUENTO_PRESTAMO"] = _descuento_cuota_sugerida(
                        conn, tid_p, prov_m, prov_a, desc_raw if desc_raw > 0 else None,
                    )
                df_edit = df_prov.drop(columns=["trabajador_id"]).copy()
                df_edit["LIQUIDO_A_PROVISIONAR"] = (
                    df_edit["LIQUIDO_GANADO"] - df_edit["SUPLE"] - df_edit["DESCUENTO_PRESTAMO"]
                ).clip(lower=0)
                if es_solo_lectura():
                    st.dataframe(
                        df_edit.style.format({
                            c: _fmt_styler_peso for c in df_edit.columns if c != "TRABAJADOR"
                        }),
                        use_container_width=True,
                    )
                    _mostrar_totales_planilla_rrhh(df_edit)
                    edited = df_edit
                else:
                    edited = st.data_editor(
                        df_edit,
                        column_config={
                            "TRABAJADOR": st.column_config.TextColumn("Trabajador", disabled=True),
                            "LIQUIDO_GANADO": st.column_config.NumberColumn(
                                "Líquido ganado ($)", min_value=0.0, format="$%d",
                            ),
                            "SUPLE": st.column_config.NumberColumn("Suple ($)", min_value=0.0, format="$%d"),
                            "DESCUENTO_PRESTAMO": st.column_config.NumberColumn(
                                "Descuento préstamo ($)", min_value=0.0, format="$%d",
                            ),
                            "SALDO_PRESTAMO": st.column_config.NumberColumn("Saldo préstamo", format="$%d", disabled=True),
                            "CUOTA_REFERENCIA": st.column_config.NumberColumn("Cuota referencia", format="$%d", disabled=True),
                            "LIQUIDO_A_PROVISIONAR": st.column_config.NumberColumn(
                                "Líquido a provisionar", format="$%d", disabled=True,
                            ),
                        },
                        hide_index=True,
                        use_container_width=True,
                        key=f"remu_editor_{prov_m}_{prov_a}",
                    )
                _mostrar_totales_planilla_rrhh(edited)
                total_provision = float(
                    (edited["LIQUIDO_GANADO"] - edited["SUPLE"] - edited["DESCUENTO_PRESTAMO"]).clip(lower=0).sum()
                )
                st.markdown(
                    f"<div style='background-color:#E3F2FD; border-left:6px solid #0D47A1; padding:15px; border-radius:8px; "
                    f"font-size:1.2rem; font-weight:bold; color:#0D47A1; margin-bottom:15px;'>"
                    f"💵 TOTAL LÍQUIDO A PROVISIONAR ({prov_m}/{prov_a}): ${f_puntos(total_provision)}</div>",
                    unsafe_allow_html=True,
                )
                if not es_solo_lectura() and st.button("💾 GUARDAR PLANILLA DEL MES", key=f"remu_save_{prov_m}_{prov_a}"):
                    errores = []
                    for idx, (_, row) in enumerate(edited.iterrows()):
                        tid_p = int(df_prov.iloc[idx]["trabajador_id"])
                        desc_save = float(row["DESCUENTO_PRESTAMO"] or 0)
                        if desc_save <= 0:
                            desc_save = _descuento_cuota_sugerida(conn, tid_p, prov_m, prov_a)
                        ok, res = _guardar_remuneracion_mes(
                            conn, tid_p, prov_m, prov_a,
                            row["LIQUIDO_GANADO"], row["SUPLE"], desc_save,
                        )
                        if not ok:
                            errores.append(f"{row['TRABAJADOR']}: {res}")
                    if errores:
                        for e in errores:
                            st.error(e)
                    else:
                        conn.commit()
                        registrar_accion("RRHH REMUNERACION MES", f"{prov_m}/{prov_a}")
                        st.success("Planilla de provisión guardada.")
                        st.rerun()
                edited["LIQUIDO_A_PROVISIONAR"] = (
                    edited["LIQUIDO_GANADO"] - edited["SUPLE"] - edited["DESCUENTO_PRESTAMO"]
                ).clip(lower=0)
                boton_pdf(
                    "PDF PROVISIÓN LÍQUIDOS",
                    generar_pdf_blob(
                        pd.concat([edited, _fila_totales_planilla_rrhh(edited)], ignore_index=True),
                        f"PROVISIÓN {prov_m}/{prov_a}",
                        incluir_precios=False,
                    ),
                    "provision_liquidos.pdf",
                    key="rh_pdf_prov_f",
                )
            else:
                st.info("No hay trabajadores activos.")
    
    elif sec_rh == _rh_secc[3]:
        _aplicar_reset_liquidacion_mes()
        if not df_act.empty:
            st.caption(
                "Registro del **pago real** (líquido + leyes sociales). "
                "Independiente de la planilla de Remuneraciones / provisión."
            )
            lista_t = (df_act['id'].astype(str) + " - " + df_act['nombre']).tolist()
            tm = st.selectbox("Trabajador", lista_t, key="rh_mov_1", on_change=reset_liquidacion_mes)

            tid_m = tnom_m = None
            if tm:
                tid_m = int(tm.split(" - ")[0])
                tnom_m = tm.split(" - ")[1]

            c1, rhm_col = st.columns(2)
            m = c1.selectbox(
                "Mes", ["01","02","03","04","05","06","07","08","09","10","11","12"],
                key="rhm_m", on_change=reset_liquidacion_mes,
            )
            a = c1.number_input("Año", min_value=2020, max_value=2040, key="rhm_a", on_change=reset_liquidacion_mes)

            row_liq = None
            if tm:
                row_liq = conn.execute(
                    """SELECT liquido, leyes_sociales
                       FROM pagos_rrhh
                       WHERE trabajador_id=? AND printf('%02d', CAST(mes AS INTEGER))=? AND anio=?""",
                    (tid_m, m, int(a)),
                ).fetchone()
                if row_liq:
                    st.warning(
                        f"⚠️ Ya existe liquidación para {tnom_m} en {m}/{int(a)}. "
                        f"Puede cargarla para editar o guardar de nuevo para actualizar."
                    )
                    if st.button("📂 Cargar registro guardado", key=f"rh_load_{tid_m}_{m}_{a}"):
                        st.session_state["rhm_liq"] = float(row_liq[0] or 0)
                        st.session_state["rhm_prev"] = float(row_liq[1] or 0)
                        st.rerun()

            with st.form("rh_mov_form", clear_on_submit=True):
                lic = rhm_col.checkbox("Licencia Médica", key="rhm_l")
                liq = rhm_col.number_input("Líquido pagado ($)", min_value=0.0, key="rhm_liq")
                ley = rhm_col.number_input("Leyes sociales ($)", min_value=0.0, key="rhm_prev")
                btn_label = "ACTUALIZAR LIQUIDACIÓN" if row_liq else "REGISTRAR LIQUIDACIÓN"
                if st.form_submit_button(btn_label):
                    if tm:
                        ok, err = _upsert_pago_rrhh(
                            conn, tid_m, m, int(a), liq, ley, lic,
                        )
                        if not ok:
                            st.error(err)
                        else:
                            tot = (0 if lic else float(liq or 0) + float(ley or 0))
                            _imputar_costos_rrhh(conn, tid_m, m, int(a), tot)
                            conn.commit()
                            registrar_accion("RRHH PAGO NETO", f"{tnom_m} {m}/{int(a)}")
                            st.success(f"✅ Liquidación de {tnom_m} guardada ({m}/{int(a)}).")
                            reset_liquidacion_mes()
                            st.rerun()
                        
    elif sec_rh == _rh_secc[4]:
        col_rh1, col_rh2 = st.columns(2)
        f_desde_rh = col_rh1.date_input("Desde", hoy - timedelta(days=120), key="rh_his_d")
        f_hasta_rh = col_rh2.date_input("Hasta", hoy, key="rh_his_h")
        
        df_h = pd.read_sql_query(f"""SELECT p.nombre as TRABAJADOR, h.mes as MES, h.anio as AÑO, 
                                    h.liquido as LIQUIDO_PAGADO, h.leyes_sociales as PREVIRED,
                                    (h.liquido + h.leyes_sociales) as TOTAL_PAGADO,
                                    h.fecha_registro as FECHA_REGISTRO
                                    FROM ({_subquery_pagos_rrhh_canonicos()}) h
                                    JOIN personal p ON h.trabajador_id = p.id 
                                    WHERE h.fecha_registro BETWEEN '{f_desde_rh}' AND '{f_hasta_rh}'
                                    ORDER BY h.anio DESC, CAST(h.mes AS INTEGER) DESC, p.nombre""", conn)
        
        total_historico_periodo = df_h['TOTAL_PAGADO'].sum()
        st.markdown(f"<div style='background-color:#E8F5E9; border-left:6px solid #2E7D32; padding:15px; border-radius:8px; font-size:1.2rem; font-weight:bold; color:#1B5E20; margin-bottom:15px;'>📊 EGRESO TOTAL PERÍODO: ${f_puntos(total_historico_periodo)}</div>", unsafe_allow_html=True)
        st.dataframe(df_h.style.format({
            "LIQUIDO_PAGADO": _fmt_styler_peso, "PREVIRED": _fmt_styler_peso, "TOTAL_PAGADO": _fmt_styler_peso,
        }), use_container_width=True)
        
        if not df_h.empty:
            boton_pdf("PDF HISTORIAL LIQUIDACIONES",
                      generar_pdf_blob(df_h, f"HISTORIAL GENERAL DE REMUNERACIONES", campo_suma_forzado="TOTAL_PAGADO"),
                      "historial_pagos_rrhh.pdf", key="rh_pdf_final_f")
    conn.close()
    
def _fecha_minima_costos_operativos(conn):
    fechas = []
    for sql in (
        "SELECT MIN(fecha) FROM movimientos WHERE ABS(COALESCE(valor_imputado, 0)) > 0.01",
        "SELECT MIN(fecha_compra) FROM facturas WHERE nro_documento LIKE '%_P' AND ABS(COALESCE(monto_imputado, 0)) > 0.01",
        "SELECT MIN(fecha) FROM petroleo WHERE tipo = 'Salida' AND ABS(COALESCE(valor_imputado, 0)) > 0.01",
        "SELECT MIN(fecha) FROM ajustes_costos WHERE ABS(COALESCE(monto, 0)) > 0.01",
    ):
        row = conn.execute(sql).fetchone()
        if row and row[0]:
            try:
                fechas.append(pd.to_datetime(row[0]).date())
            except Exception:
                pass
    return min(fechas) if fechas else None


def _rango_fechas_costos_consulta(conn, fi, ff, es_vigente):
    """Temporada vigente: incluye desde el movimiento más antiguo hasta hoy (evita ocultar gastos pre-temporada)."""
    ff_eff = max(ff, hoy)
    if not es_vigente:
        return fi, ff_eff
    fmin = _fecha_minima_costos_operativos(conn)
    if fmin and fmin < fi:
        return fmin, ff_eff
    return fi, ff_eff


def query_costos_consolidado(fi=None, ff=None):
    filtro_fecha = ""
    if fi and ff:
        fi_s, ff_s = str(fi), str(ff)
        filtro_fecha = f" AND fecha BETWEEN '{fi_s}' AND '{ff_s}' "
        filtro_fecha_f = f" AND fecha_compra BETWEEN '{fi_s}' AND '{ff_s}' "
        filtro_fecha_a = f" AND fecha BETWEEN '{fi_s}' AND '{ff_s}' "
    else:
        filtro_fecha = filtro_fecha_f = filtro_fecha_a = ""
    return f"""SELECT UPPER(TRIM(cc)) as Cuartel, 
                  SUM(CASE WHEN fuente = 'BODEGA' THEN val ELSE 0 END) as Insumos, 
                  SUM(CASE WHEN fuente = 'FACTURA' THEN val ELSE 0 END) as Gastos, 
                  SUM(CASE WHEN fuente = 'PETROLEO' THEN val ELSE 0 END) as Petroleo, 
                  0 as RRHH, 
                  SUM(CASE WHEN fuente = 'AJUSTE' THEN val ELSE 0 END) as Ajustes,
                  SUM(val) as Total 
           FROM (
               SELECT centro_costo as cc, valor_imputado as val, 'BODEGA' as fuente, fecha FROM movimientos WHERE 1=1 {filtro_fecha}
               UNION ALL 
               SELECT centro_costo as cc, monto_imputado as val, 'FACTURA' as fuente, fecha_compra as fecha FROM facturas WHERE nro_documento NOT LIKE '%_RRHH' AND nro_documento LIKE '%_P' {filtro_fecha_f}
               UNION ALL 
               SELECT centro_costo as cc, valor_imputado as val, 'PETROLEO' as fuente, fecha FROM petroleo WHERE tipo = 'Salida' {filtro_fecha}
               UNION ALL
               SELECT centro_costo as cc, monto as val, 'AJUSTE' as fuente, fecha FROM ajustes_costos WHERE 1=1 {filtro_fecha_a}
           ) WHERE cc != '' GROUP BY cc"""

def _mes_en_temporada_costos(anio, mes, fi, ff):
    try:
        anio_i, mes_i = int(anio), int(mes)
        ultimo_dia = calendar.monthrange(anio_i, mes_i)[1]
        inicio_mes = date(anio_i, mes_i, 1)
        fin_mes = date(anio_i, mes_i, ultimo_dia)
        return inicio_mes <= ff and fin_mes >= fi
    except (TypeError, ValueError):
        return False


def _ratio_leyes_sobre_liquido(conn):
    """Tasa leyes/liquido del último mes con pago real (fallback ~22 %)."""
    row = conn.execute(
        """SELECT SUM(leyes_sociales), SUM(liquido) FROM pagos_rrhh
           WHERE (anio, printf('%02d', CAST(mes AS INTEGER))) = (
               SELECT anio, printf('%02d', CAST(mes AS INTEGER)) FROM pagos_rrhh
               ORDER BY anio DESC, CAST(mes AS INTEGER) DESC LIMIT 1
           )"""
    ).fetchone()
    if row and row[1] and float(row[1]) > 0:
        return float(row[0]) / float(row[1])
    return 0.22

def _subquery_pagos_rrhh_canonicos():
    """Un pago por trabajador activo y mes: el de mayor monto (desempate id más reciente)."""
    return """
        SELECT p.*
        FROM pagos_rrhh p
        INNER JOIN personal per ON per.id = p.trabajador_id
        WHERE p.id = (
            SELECT p2.id FROM pagos_rrhh p2
            WHERE p2.trabajador_id = p.trabajador_id
              AND printf('%02d', CAST(p2.mes AS INTEGER)) = printf('%02d', CAST(p.mes AS INTEGER))
              AND p2.anio = p.anio
            ORDER BY (p2.liquido + p2.leyes_sociales) DESC, p2.id DESC
            LIMIT 1
        )
    """

def _total_rrhh_mes(conn, mes, anio):
    """Total imputado a costos desde Liquidación mensual (líquido + leyes)."""
    mes_n = _mes_rrhh_norm(mes)
    row = conn.execute(
        f"""SELECT COALESCE(SUM(liquido + leyes_sociales), 0)
            FROM ({_subquery_pagos_rrhh_canonicos()})
            WHERE printf('%02d', CAST(mes AS INTEGER))=? AND anio=?""",
        (mes_n, int(anio)),
    ).fetchone()
    return float(row[0] or 0)

def _totales_rrhh_por_mes(conn, fi=None, ff=None):
    """Dict (anio, mes) -> monto. Solo liquidaciones canónicas (personal activo en maestro)."""
    totales = {}
    for row in conn.execute(
        f"""SELECT printf('%02d', CAST(mes AS INTEGER)) as mes, anio,
                   SUM(liquido + leyes_sociales) as total
            FROM ({_subquery_pagos_rrhh_canonicos()})
            GROUP BY printf('%02d', CAST(mes AS INTEGER)), anio"""
    ).fetchall():
        if fi and ff and not _mes_en_temporada_costos(row[1], row[0], fi, ff):
            continue
        pago = float(row[2] or 0)
        if pago > 0:
            totales[(int(row[1]), _mes_rrhh_norm(row[0]))] = pago
    return totales

def _calcular_rrhh_temporada(conn, fi, ff):
    """Suma liquidaciones mensuales (líquido + leyes) dentro del rango de temporada."""
    try:
        return sum(_totales_rrhh_por_mes(conn, fi, ff).values())
    except Exception:
        return 0.0

def _calcular_rrhh_mes_dashboard(conn):
    try:
        _, fi, ff = _temporada_vigente_costos()
        monto = _calcular_rrhh_temporada(conn, fi, ff)
        return float(monto or 0)
    except Exception:
        return 0.0

def _armar_dataframe_costos_dashboard(conn, cuarteles, prorrateo_rrhh):
    """Totales por cuartel para dashboard (desde matriz Vista B, histórico completo)."""
    nombre, fi, ff = _temporada_vigente_costos()
    matriz = _armar_matriz_costos_vista_b(
        conn, None, None, cuarteles, prorrateo_rrhh, nombre, fi_rrhh=fi, ff_rrhh=ff,
    )
    tg = matriz[matriz["Rubro"] == "TOTAL GASTO"]
    if tg.empty:
        dfr = pd.DataFrame({"Cuartel": cuarteles, "Total": [0.0] * len(cuarteles)})
    else:
        dfr = pd.DataFrame({
            "Cuartel": list(cuarteles),
            "Total": [float(tg.iloc[0].get(c, 0) or 0) for c in cuarteles],
        })
    fila_t = pd.DataFrame([{"Cuartel": "TOTAL GENERAL", "Total": dfr["Total"].sum()}])
    return dfr, pd.concat([dfr, fila_t], ignore_index=True)

def _obtener_ppto_temporada(conn, temporada, centro_costo):
    row = conn.execute(
        "SELECT monto_ppto FROM costos_ppto_temporada WHERE temporada=? AND centro_costo=?",
        (temporada, centro_costo),
    ).fetchone()
    return float(row[0]) if row and row[0] is not None else 0.0

def _guardar_ppto_temporada(conn, temporada, centro_costo, monto):
    conn.execute(
        """INSERT INTO costos_ppto_temporada (temporada, centro_costo, monto_ppto)
           VALUES (?,?,?)
           ON CONFLICT(temporada, centro_costo) DO UPDATE SET monto_ppto=excluded.monto_ppto""",
        (temporada, centro_costo, float(monto)),
    )
    conn.commit()

def _migrar_costos_kg_estimado(conn):
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS costos_kg_estimado_temporada (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                temporada TEXT NOT NULL,
                centro_costo TEXT NOT NULL,
                kg_estimado REAL DEFAULT 0,
                UNIQUE(temporada, centro_costo)
            )"""
        )
        conn.commit()
    except Exception:
        pass

def _obtener_kg_estimado_temporada(conn, temporada, centro_costo):
    row = conn.execute(
        "SELECT kg_estimado FROM costos_kg_estimado_temporada WHERE temporada=? AND centro_costo=?",
        (temporada, centro_costo),
    ).fetchone()
    return float(row[0]) if row and row[0] is not None else 0.0

def _guardar_kg_estimado_temporada(conn, temporada, centro_costo, kg):
    conn.execute(
        """INSERT INTO costos_kg_estimado_temporada (temporada, centro_costo, kg_estimado)
           VALUES (?,?,?)
           ON CONFLICT(temporada, centro_costo) DO UPDATE SET kg_estimado=excluded.kg_estimado""",
        (temporada, centro_costo, float(kg)),
    )
    conn.commit()

def _costo_usd_por_kg(gasto_clp, kg_estimado, valor_dolar):
    if not kg_estimado or kg_estimado <= 0 or not valor_dolar or valor_dolar <= 0:
        return None
    return float(gasto_clp) / float(valor_dolar) / float(kg_estimado)

def _calc_metricas_produccion_cc(gasto_real, ppto, kg_est):
    valor_dolar = obtener_valor_dolar()
    ind = obtener_indicadores()
    costo_usd_kg = _costo_usd_por_kg(gasto_real, kg_est, valor_dolar)
    meta_usd_kg = _costo_usd_por_kg(ppto, kg_est, valor_dolar) if ppto > 0 else None
    avance = (float(gasto_real) / float(ppto) * 100) if ppto > 0 else 0.0
    return {
        "valor_dolar": valor_dolar,
        "ind": ind,
        "costo_usd_kg": costo_usd_kg,
        "meta_usd_kg": meta_usd_kg,
        "avance": avance,
    }


def _mostrar_widgets_produccion_cc(gasto_real, ppto, kg_est, meta):
    st.markdown("##### 🍒 Producción estimada y costo USD/kg")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Kg estimados a producir", f_cantidad(kg_est) if kg_est > 0 else "—")
    k2.metric(
        "Costo acumulado USD/kg",
        _fmt_usd(meta["costo_usd_kg"]) if meta["costo_usd_kg"] is not None else "—",
    )
    k3.metric(
        "Meta presupuesto USD/kg",
        _fmt_usd(meta["meta_usd_kg"]) if meta["meta_usd_kg"] is not None else "—",
    )
    with k4:
        if meta["ind"].get("offline") or not meta["valor_dolar"]:
            st.metric("Dólar referencia", "—")
        else:
            st.metric("Dólar referencia", meta["ind"]["dolar"])
    if kg_est <= 0:
        st.info(
            "Sin kg estimados para esta temporada. "
            "Configúrelos en **Administración → Ppto y producción**."
        )
    elif not meta["valor_dolar"]:
        st.warning("Sin cotización del dólar; no se puede calcular USD/kg (revise conexión del dashboard).")


def _mostrar_avance_y_resumen_cc(gasto_real, ppto, total_general, meta):
    """Métricas del cuartel en una fila: avance, participación, gasto, ppto y saldo."""
    st.markdown("##### 📊 Avance y resumen del cuartel")
    pct_total = (gasto_real / total_general * 100) if total_general > 0 else 0.0
    saldo = ppto - gasto_real if ppto > 0 else None

    if ppto <= 0:
        st.info("Sin presupuesto configurado. Cárguelo en **Administración → Ppto y producción**.")

    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        if ppto > 0:
            avance = meta["avance"]
            color_txt, _ = _color_avance_ppto(min(avance, 100.0) if avance <= 100 else 101)
            m1.markdown(
                f"<div><div style='font-size:14px;color:rgb(49,51,63);margin-bottom:4px;'>"
                f"Presupuesto utilizado</div>"
                f"<div style='font-size:36px;font-weight:600;color:{color_txt};'>{avance:.1f}%</div></div>",
                unsafe_allow_html=True,
            )
        else:
            m1.metric("Presupuesto utilizado", "—")
    m2.metric("Participación en temporada", f"{pct_total:.1f}%")
    m3.metric("Gasto acumulado", f"${f_puntos(gasto_real)}")
    m4.metric("Presupuesto", f"${f_puntos(ppto)}" if ppto > 0 else "—")
    if ppto > 0:
        color_saldo = "#C62828" if saldo < 0 else "#2E7D32"
        m5.markdown(
            f"<div><div style='font-size:14px;color:rgb(49,51,63);margin-bottom:4px;'>Saldo disponible</div>"
            f"<div style='font-size:36px;font-weight:600;color:{color_saldo};'>${f_puntos(saldo)}</div></div>",
            unsafe_allow_html=True,
        )
    else:
        m5.metric("Saldo disponible", "—")


def _rubro_valido_matriz(tg):
    return _rubro_matriz_desde_tipo_gasto(tg)


def _factores_monto_bruto_facturas(conn, fi=None, ff=None):
    """Escala imputaciones _P al monto bruto del documento padre (mismo criterio que Compras)."""
    filtro = ""
    params = []
    from demo_web.services.costos_compras_coherencia import (
        sql_filtro_imputacion_en_historial,
        sql_join_parent_imputacion,
    )

    if fi and ff:
        filtro = " AND f.fecha_compra BETWEEN ? AND ? "
        params = [str(fi), str(ff)]
    rows = conn.execute(
        f"""
        SELECT p.nro_documento, p.proveedor,
               MAX(f.monto_total) AS bruto,
               SUM(COALESCE(p.monto_imputado, 0)) AS imp
        FROM facturas p
        {sql_join_parent_imputacion('p', 'f')}
        WHERE 1=1
          {sql_filtro_imputacion_en_historial('p', 'f')}
          {filtro}
        GROUP BY p.nro_documento, p.proveedor
        """,
        params,
    ).fetchall()
    out = {}
    for nro_p, prov, bruto, imp in rows:
        imp_f = float(imp or 0)
        bruto_f = float(bruto or 0)
        out[(str(nro_p or ""), str(prov or ""))] = (bruto_f / imp_f) if imp_f > 0.01 and bruto_f > 0.01 else 1.0
    return out


def _monto_costos_factura_imputada(factores, nro_p, prov, monto_imputado):
    return float(monto_imputado or 0) * factores.get((str(nro_p or ""), str(prov or "")), 1.0)


def _monto_costos_factura_matriz(rubro, monto_bruto_escalado, neto_facturas_iva=True):
    """Costos imputa neto (÷ 1.19) en rubros con IVA; Compras historial usa bruto (monto_total)."""
    m = float(monto_bruto_escalado or 0)
    if neto_facturas_iva and rubro in RUBROS_COSTOS_NETO_IVA:
        return m / IVA_COSTOS_FACTOR
    return m


def _dataframe_facturas_detalle_cc(conn, cc_u, factores, fi_s=None, ff_s=None):
    base_sql = """
        SELECT fecha_compra as Fecha,
               COALESCE(NULLIF(TRIM(tipo_gasto), ''), ?) as Rubro,
               proveedor || ' — ' || nro_documento ||
               CASE WHEN concepto IS NOT NULL AND TRIM(concepto) != '' THEN ' | ' || concepto ELSE '' END as Detalle,
               nro_documento as nro_p,
               proveedor as prov,
               monto_imputado as Monto
        FROM facturas
        WHERE UPPER(TRIM(centro_costo)) = ?
          AND nro_documento NOT LIKE '%_RRHH' AND nro_documento LIKE '%_P'
          AND ABS(COALESCE(monto_imputado, 0)) > 0.01
    """
    if fi_s and ff_s:
        df = pd.read_sql_query(
            base_sql + " AND fecha_compra BETWEEN ? AND ?",
            conn,
            params=(TIPO_GASTO_SIN_CLASIFICAR, cc_u, fi_s, ff_s),
        )
    else:
        df = pd.read_sql_query(base_sql, conn, params=(TIPO_GASTO_SIN_CLASIFICAR, cc_u))
    if df.empty:
        return df
    df["Rubro"] = df["Rubro"].map(lambda tg: _rubro_matriz_desde_tipo_gasto(tg) or TIPO_GASTO_SIN_CLASIFICAR)
    df["Monto"] = df.apply(
        lambda r: _monto_costos_factura_matriz(
            r["Rubro"],
            _monto_costos_factura_imputada(factores, r["nro_p"], r["prov"], r["Monto"]),
        ),
        axis=1,
    )
    return df[["Fecha", "Rubro", "Detalle", "Monto"]]


def _armar_matriz_costos_vista_b(
    conn, fi, ff, cuarteles, prorrateo_rrhh, temporada, fi_rrhh=None, ff_rrhh=None,
    neto_facturas_iva=True,
):
    cols_cc = list(cuarteles)
    cols = cols_cc + ["TOTAL"]
    matriz = {rubro: {c: 0.0 for c in cols} for rubro in RUBROS_MATRIZ_COSTOS}
    cc_canon = {str(c).upper().strip(): c for c in cuarteles}

    def add(cc, rubro, monto):
        cc_key = cc_canon.get(str(cc or "").upper().strip())
        if not cc_key or not rubro:
            return
        m = float(monto or 0)
        if abs(m) < 0.01:
            return
        matriz[rubro][cc_key] += m
        matriz[rubro]["TOTAL"] += m

    from demo_web.services.costos_compras_coherencia import (
        sql_filtro_imputacion_en_historial,
        sql_join_parent_imputacion,
    )

    filtro_f = ""
    params_f = ()
    if fi and ff:
        filtro_f = " AND f.fecha_compra BETWEEN ? AND ? "
        params_f = (str(fi), str(ff))
    filtro_m = f" AND fecha BETWEEN ? AND ? " if fi and ff else ""
    params_m = (str(fi), str(ff)) if fi and ff else ()
    filtro_p = filtro_m.replace("fecha", "fecha") if fi and ff else ""
    filtro_a = filtro_m

    q_mov = f"""SELECT UPPER(TRIM(m.centro_costo)) as cc,
                       m.valor_imputado as m,
                       COALESCE(i.producto, '') as producto,
                       i.familia as familia
                FROM movimientos m
                LEFT JOIN inventario i ON m.producto_id = i.id
                WHERE ABS(COALESCE(m.valor_imputado,0))>0.01
                  AND TRIM(COALESCE(m.centro_costo,'')) != '' {filtro_m}"""
    for row in conn.execute(q_mov, params_m):
        rubro = _rubro_costo_desde_producto(conn, row[2], row[3])
        add(row[0], rubro, row[1])

    factores_bruto = _factores_monto_bruto_facturas(conn, fi, ff)
    q_fac = f"""SELECT p.nro_documento, p.proveedor,
                       UPPER(TRIM(p.centro_costo)) as cc,
                       COALESCE(NULLIF(TRIM(p.tipo_gasto), ''), ?) as tg,
                       p.monto_imputado as m
                FROM facturas p
                {sql_join_parent_imputacion('p', 'f')}
                WHERE 1=1
                  {sql_filtro_imputacion_en_historial('p', 'f')}
                  {filtro_f}"""
    for row in conn.execute(q_fac, (TIPO_GASTO_SIN_CLASIFICAR, *params_f)):
        rubro = _rubro_valido_matriz(row[3])
        if rubro:
            monto = _monto_costos_factura_imputada(factores_bruto, row[0], row[1], row[4])
            monto = _monto_costos_factura_matriz(rubro, monto, neto_facturas_iva=neto_facturas_iva)
            add(row[2], rubro, monto)

    q_pet = f"""SELECT UPPER(TRIM(centro_costo)) as cc, SUM(valor_imputado) as m
                FROM petroleo WHERE tipo='Salida'
                  AND ABS(COALESCE(valor_imputado,0))>0.01 {filtro_m}
                GROUP BY UPPER(TRIM(centro_costo))"""
    for row in conn.execute(q_pet, params_m):
        add(row[0], "Petróleo", row[1])

    q_aj = f"""SELECT UPPER(TRIM(centro_costo)) as cc, SUM(monto) as m
               FROM ajustes_costos WHERE ABS(COALESCE(monto,0))>0.01 {filtro_a}
               GROUP BY UPPER(TRIM(centro_costo))"""
    for row in conn.execute(q_aj, params_m):
        add(row[0], "Ajustes", row[1])

    monto_rrhh = _calcular_rrhh_temporada(conn, fi_rrhh or fi, ff_rrhh or ff)
    for cc in cuarteles:
        pct = prorrateo_rrhh.get(cc, 0)
        add(cc, "RRHH de la casa", monto_rrhh * pct)

    rows = []
    for rubro in RUBROS_MATRIZ_COSTOS:
        row = {"Rubro": rubro}
        for c in cols:
            row[c] = matriz[rubro].get(c, 0.0)
        rows.append(row)
    df = pd.DataFrame(rows)
    total_gasto = {c: float(df[c].sum()) for c in cols}
    ppto = {c: 0.0 for c in cols}
    for cc in cuarteles:
        ppto[cc] = _obtener_ppto_temporada(conn, temporada, cc)
    ppto["TOTAL"] = sum(ppto[c] for c in cuarteles)
    saldo = {c: ppto[c] - total_gasto[c] for c in cols}
    footer = pd.DataFrame([
        {"Rubro": "TOTAL GASTO", **total_gasto},
        {"Rubro": "PRESUPUESTO", **ppto},
        {"Rubro": "SALDO", **saldo},
    ])
    return pd.concat([df, footer], ignore_index=True)

def _total_gasto_cc_desde_matriz(matriz_df, cc):
    if matriz_df is None or matriz_df.empty:
        return 0.0
    tg = matriz_df[matriz_df["Rubro"] == "TOTAL GASTO"]
    if tg.empty or cc not in tg.columns:
        return 0.0
    return float(tg.iloc[0][cc] or 0)

def _total_gasto_general_matriz(matriz_df):
    return _total_gasto_cc_desde_matriz(matriz_df, "TOTAL")

def _rubros_cc_desde_matriz(matriz_df, cc):
    if matriz_df is None or matriz_df.empty:
        return pd.DataFrame(columns=["Rubro", "Monto"])
    body = matriz_df[~matriz_df["Rubro"].isin(RUBROS_MATRIZ_FILAS_CIERRE)].copy()
    if cc not in body.columns:
        return pd.DataFrame(columns=["Rubro", "Monto"])
    out = body[["Rubro", cc]].rename(columns={cc: "Monto"})
    out = out[out["Monto"].abs() > 0.5].sort_values("Monto", ascending=False)
    return out.reset_index(drop=True)

def _color_avance_ppto(pct):
    if pct <= 33:
        return "#2E7D32", "#E8F5E9"
    if pct <= 66:
        return "#F9A825", "#FFF8E1"
    if pct <= 100:
        return "#E65100", "#FFF3E0"
    return "#C62828", "#FFEBEE"

def _badge_estilo_avance_costos(pct):
    if pct is None:
        return ""
    color_txt, color_bg = _color_avance_ppto(float(pct))
    return f"color:{color_txt};background:{color_bg};"

def _metric_coloreado(label, valor, color):
    st.markdown(
        f"""<div>
        <div style="font-size:14px;color:rgb(49,51,63);margin-bottom:4px;font-weight:400;">{label}</div>
        <div style="font-size:36px;font-weight:600;color:{color};line-height:1.2;">{valor}</div>
        </div>""",
        unsafe_allow_html=True,
    )

def _lineas_rrhh_detalle_cc(conn, cc, fi, ff, prorrateo_rrhh):
    """Líneas de detalle RRHH para un CC.

    Preferimos las imputaciones reales en costos_mano_obra (por trabajador).
    La fecha mostrada es la de registro/subida de la liquidación (no el día 1 del mes).
    Si no hay filas, cae al prorrateo mensual del total de liquidaciones.
    """
    cc_u = str(cc or "").upper().strip()
    if not cc_u:
        return []

    pct = 0.0
    if isinstance(prorrateo_rrhh, dict):
        if cc in prorrateo_rrhh:
            pct = float(prorrateo_rrhh.get(cc) or 0)
        elif cc_u in prorrateo_rrhh:
            pct = float(prorrateo_rrhh.get(cc_u) or 0)
        else:
            for k, v in prorrateo_rrhh.items():
                if str(k).upper().strip() == cc_u:
                    pct = float(v or 0)
                    break

    def _fecha_linea(fecha_reg, anio, mes_str):
        fr = str(fecha_reg or "").strip()[:10]
        if fr and len(fr) >= 8 and fr[0:4].isdigit():
            return fr
        return f"{int(anio)}-{_mes_rrhh_norm(mes_str)}-01"

    lineas = []
    # 1) Imputaciones reales guardadas al liquidar
    try:
        rows = conn.execute(
            """
            SELECT c.anio,
                   printf('%02d', CAST(c.mes AS INTEGER)) AS mes,
                   COALESCE(NULLIF(TRIM(p.nombre), ''), 'Trabajador') AS trabajador,
                   SUM(c.monto) AS monto,
                   MAX(c.fecha_registro) AS fecha_reg,
                   MAX(pay.fecha_registro) AS fecha_pago
            FROM costos_mano_obra c
            LEFT JOIN personal p ON p.id = c.trabajador_id
            LEFT JOIN pagos_rrhh pay
                   ON pay.trabajador_id = c.trabajador_id
                  AND pay.anio = c.anio
                  AND printf('%02d', CAST(pay.mes AS INTEGER)) = printf('%02d', CAST(c.mes AS INTEGER))
            WHERE UPPER(TRIM(c.centro_costo)) = ?
              AND ABS(COALESCE(c.monto, 0)) > 0.01
            GROUP BY c.anio, printf('%02d', CAST(c.mes AS INTEGER)), COALESCE(NULLIF(TRIM(p.nombre), ''), 'Trabajador')
            ORDER BY COALESCE(MAX(pay.fecha_registro), MAX(c.fecha_registro)) DESC, trabajador
            """,
            (cc_u,),
        ).fetchall()
    except Exception:
        rows = []

    for row in rows:
        anio, mes_str, trabajador, monto = row[0], row[1], row[2], row[3]
        fecha_reg = row[4] if len(row) > 4 else None
        fecha_pago = row[5] if len(row) > 5 else None
        try:
            if fi and ff and not _mes_en_temporada_costos(anio, mes_str, fi, ff):
                continue
        except Exception:
            pass
        m = float(monto or 0)
        if abs(m) < 0.01:
            continue
        lineas.append(
            {
                "Fecha": _fecha_linea(fecha_pago or fecha_reg, anio, mes_str),
                "Fuente": "RRHH de la casa",
                "Detalle": f"RRHH · {trabajador} · {_mes_rrhh_norm(mes_str)}/{int(anio)}",
                "Monto": m,
            }
        )
    if lineas:
        return lineas

    # 2) Fallback: prorrateo del total de liquidaciones del mes
    if pct <= 0:
        return []
    totales = _totales_rrhh_por_mes(conn, fi, ff)
    for (anio, mes_str), total_mes in sorted(totales.items()):
        parte = float(total_mes) * pct
        if parte <= 0.01:
            continue
        fecha_pago = None
        try:
            fr = conn.execute(
                """
                SELECT MAX(fecha_registro)
                FROM pagos_rrhh
                WHERE anio=? AND printf('%02d', CAST(mes AS INTEGER))=?
                """,
                (int(anio), _mes_rrhh_norm(mes_str)),
            ).fetchone()
            fecha_pago = fr[0] if fr else None
        except Exception:
            fecha_pago = None
        lineas.append(
            {
                "Fecha": _fecha_linea(fecha_pago, anio, mes_str),
                "Fuente": "RRHH de la casa",
                "Detalle": f"Prorrateo RRHH {_mes_rrhh_norm(mes_str)}/{anio}",
                "Monto": parte,
            }
        )
    return lineas


def _lineas_rrhh_detalle_dashboard(conn, cc, prorrateo_rrhh):
    pct = prorrateo_rrhh.get(cc, 0)
    if pct <= 0:
        return []
    _, fi, ff = _temporada_vigente_costos()
    return _lineas_rrhh_detalle_cc(conn, cc, fi, ff, prorrateo_rrhh)

def _obtener_detalle_gastos_cc(conn, cc, prorrateo_rrhh, fi=None, ff=None, fi_rrhh=None, ff_rrhh=None):
    cc_u = cc.upper().strip()
    fi_rr = fi_rrhh if fi_rrhh is not None else fi
    ff_rr = ff_rrhh if ff_rrhh is not None else ff
    factores_bruto = _factores_monto_bruto_facturas(conn, fi, ff)
    partes = []
    if fi and ff:
        fi_s, ff_s = str(fi), str(ff)
        params_cc = (cc_u, fi_s, ff_s)
        partes.append(_dataframe_movimientos_detalle_cc(conn, cc_u, fi_s, ff_s))
        partes.append(_dataframe_facturas_detalle_cc(conn, cc_u, factores_bruto, fi_s, ff_s))
        partes.append(pd.read_sql_query(
            """SELECT fecha as Fecha, 'Petróleo' as Rubro,
                      TRIM(
                        CASE WHEN COALESCE(bitacora_codigo,'') != '' THEN bitacora_codigo || ' · ' ELSE '' END
                        || COALESCE(vehiculo, '') || ' — ' || COALESCE(responsable, '')
                      ) as Detalle,
                      valor_imputado as Monto
               FROM petroleo
               WHERE UPPER(TRIM(centro_costo)) = ? AND fecha BETWEEN ? AND ?
                 AND tipo = 'Salida' AND ABS(COALESCE(valor_imputado, 0)) > 0.01""",
            conn, params=params_cc,
        ))
        partes.append(pd.read_sql_query(
            """SELECT fecha as Fecha, 'Ajustes' as Rubro,
                      COALESCE(NULLIF(TRIM(motivo), ''), 'Ajuste manual') as Detalle,
                      monto as Monto
               FROM ajustes_costos
               WHERE UPPER(TRIM(centro_costo)) = ? AND fecha BETWEEN ? AND ?
                 AND ABS(COALESCE(monto, 0)) > 0.01""",
            conn, params=params_cc,
        ))
        df_rr = pd.DataFrame(_lineas_rrhh_detalle_cc(conn, cc, fi_rr, ff_rr, prorrateo_rrhh))
    else:
        params_cc = (cc_u,)
        partes.append(_dataframe_movimientos_detalle_cc(conn, cc_u))
        partes.append(_dataframe_facturas_detalle_cc(conn, cc_u, factores_bruto))
        partes.append(pd.read_sql_query(
            """SELECT fecha as Fecha, 'Petróleo' as Rubro,
                      TRIM(
                        CASE WHEN COALESCE(bitacora_codigo,'') != '' THEN bitacora_codigo || ' · ' ELSE '' END
                        || COALESCE(vehiculo, '') || ' — ' || COALESCE(responsable, '')
                      ) as Detalle,
                      valor_imputado as Monto
               FROM petroleo
               WHERE UPPER(TRIM(centro_costo)) = ? AND tipo = 'Salida'
                 AND ABS(COALESCE(valor_imputado, 0)) > 0.01""",
            conn, params=params_cc,
        ))
        partes.append(pd.read_sql_query(
            """SELECT fecha as Fecha, 'Ajustes' as Rubro,
                      COALESCE(NULLIF(TRIM(motivo), ''), 'Ajuste manual') as Detalle,
                      monto as Monto
               FROM ajustes_costos
               WHERE UPPER(TRIM(centro_costo)) = ? AND ABS(COALESCE(monto, 0)) > 0.01""",
            conn, params=params_cc,
        ))
        df_rr = pd.DataFrame(_lineas_rrhh_detalle_dashboard(conn, cc, prorrateo_rrhh))
    if not df_rr.empty:
        df_rr = df_rr.rename(columns={"Fuente": "Rubro"})
        if "Rubro" in df_rr.columns:
            df_rr["Rubro"] = df_rr["Rubro"].astype(str).replace(
                {"RRHH": "RRHH de la casa", "rrhh": "RRHH de la casa"}
            )
            df_rr.loc[
                df_rr["Rubro"].astype(str).str.upper().isin({"RRHH", "RRHH DE LA CASA"}),
                "Rubro",
            ] = "RRHH de la casa"
        partes.append(df_rr[["Fecha", "Rubro", "Detalle", "Monto"]])
    partes = [p for p in partes if p is not None and not getattr(p, "empty", True)]
    df = (
        pd.concat(partes, ignore_index=True)
        if partes
        else pd.DataFrame(columns=["Fecha", "Rubro", "Detalle", "Monto"])
    )
    if df.empty:
        return df
    return df.sort_values("Fecha", ascending=False).reset_index(drop=True)

def _mostrar_lista_detalle_gastos_cc(conn, cc, prorrateo_rrhh, key_prefix, fi=None, ff=None, fi_rrhh=None, ff_rrhh=None):
    df_det = _obtener_detalle_gastos_cc(conn, cc, prorrateo_rrhh, fi, ff, fi_rrhh, ff_rrhh)
    st.markdown("##### 📋 Detalle de gastos imputados")
    c1, c2, c3 = st.columns([2, 1, 1])
    buscar = c1.text_input("Buscar", placeholder="Detalle, proveedor, documento...", key=f"{key_prefix}_bus")
    rubros_filtro = ["Todas"] + [r for r in RUBROS_MATRIZ_COSTOS if r != "Ajustes" or es_admin()]
    rubro = c2.selectbox("Rubro", rubros_filtro, key=f"{key_prefix}_fue")
    orden = c3.selectbox("Orden", ["Fecha ↓", "Fecha ↑", "Monto ↓", "Monto ↑"], key=f"{key_prefix}_ord")
    df_show = df_det.copy()
    if buscar.strip():
        q = buscar.strip().upper()
        df_show = df_show[
            df_show["Detalle"].astype(str).str.upper().str.contains(q, na=False)
            | df_show["Rubro"].astype(str).str.upper().str.contains(q, na=False)
        ]
    if rubro != "Todas":
        df_show = df_show[df_show["Rubro"] == rubro]
    if orden == "Fecha ↑":
        df_show = df_show.sort_values("Fecha", ascending=True)
    elif orden == "Monto ↓":
        df_show = df_show.sort_values("Monto", ascending=False)
    elif orden == "Monto ↑":
        df_show = df_show.sort_values("Monto", ascending=True)
    else:
        df_show = df_show.sort_values("Fecha", ascending=False)
    if df_show.empty:
        st.info("Sin registros para los filtros seleccionados.")
    else:
        total_fil = df_show["Monto"].sum()
        st.caption(f"{len(df_show)} movimientos · Total filtrado: **${f_puntos(total_fil)}**")
        st.dataframe(
            df_show.style.format({"Monto": _fmt_styler_peso}),
            use_container_width=True,
            hide_index=True,
        )

def _estilo_fila_matriz_costos(row):
    """Colores de cierre: presupuesto (azul) y saldo (verde/rojo según signo)."""
    rubro = str(row.name or "")
    n = len(row)
    if rubro == "PRESUPUESTO":
        celda = "background-color: #E3F2FD; color: #0D47A1; font-weight: 600"
        return [celda] * n
    if rubro == "SALDO":
        estilos = []
        for val in row:
            try:
                m = float(val or 0)
            except (TypeError, ValueError):
                m = 0.0
            if m < -0.5:
                estilos.append("background-color: #FFEBEE; color: #C62828; font-weight: 600")
            elif m > 0.5:
                estilos.append("background-color: #E8F5E9; color: #2E7D32; font-weight: 600")
            else:
                estilos.append("background-color: #F5F5F5; color: #616161; font-weight: 600")
        return estilos
    if rubro == "TOTAL GASTO":
        celda = "background-color: #FFF8E1; color: #F57F17; font-weight: 600"
        return [celda] * n
    return [""] * n

def _fmt_pct_matriz_costos(v):
    try:
        if v is None or v == "":
            return ""
        return f"{float(v):.1f}%"
    except (TypeError, ValueError):
        return ""


def _inyectar_css_matriz_costos_resumen():
    st.markdown(
        """
        <style>
        .costos-matriz-resumen [data-testid="stDataFrame"] > div {
            overflow: visible !important;
            max-height: none !important;
        }
        .costos-matriz-resumen [data-testid="stDataFrame"] table {
            font-size: 0.78rem;
        }
        .costos-matriz-resumen [data-testid="stDataFrame"] th,
        .costos-matriz-resumen [data-testid="stDataFrame"] td {
            padding: 0.28rem 0.45rem !important;
            white-space: nowrap;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _preparar_matriz_costos_resumen(matriz_df):
    if matriz_df is None or matriz_df.empty:
        return matriz_df
    show = matriz_df.copy()
    if not es_admin():
        show = show[show["Rubro"] != "Ajustes"]
    footer_mask = show["Rubro"].isin(RUBROS_MATRIZ_FILAS_CIERRE)
    body = show[~footer_mask].copy()
    footer = show[footer_mask].copy()
    if "TOTAL" in body.columns:
        total_g = 0.0
        tg = footer[footer["Rubro"] == "TOTAL GASTO"]
        if not tg.empty:
            total_g = float(tg.iloc[0].get("TOTAL", 0) or 0)
        body["% Total"] = body["TOTAL"].apply(
            lambda v: (float(v or 0) / total_g * 100) if total_g > 0.01 else 0.0
        )
        body = body.sort_values("TOTAL", ascending=False)
        cols = [c for c in body.columns if c != "% Total"] + ["% Total"]
        body = body[cols]
    footer["% Total"] = ""
    return pd.concat([body, footer], ignore_index=True)


def _mostrar_matriz_costos_vista_b(matriz_df, key_pdf):
    if matriz_df is None or matriz_df.empty:
        st.info("Sin datos de costos.")
        return
    show = _preparar_matriz_costos_resumen(matriz_df)
    fmt_cols = [c for c in show.columns if c not in ("Rubro", "% Total")]
    fmt_map = {c: _fmt_styler_peso for c in fmt_cols}
    if "% Total" in show.columns:
        fmt_map["% Total"] = _fmt_pct_matriz_costos
    styled = (
        show.set_index("Rubro")
        .style.format(fmt_map)
        .apply(_estilo_fila_matriz_costos, axis=1)
    )
    _inyectar_css_matriz_costos_resumen()
    st.markdown('<div class="costos-matriz-resumen">', unsafe_allow_html=True)
    st.dataframe(
        styled,
        use_container_width=True,
        height=min(920, max(220, 30 * len(show) + 42)),
    )
    st.markdown("</div>", unsafe_allow_html=True)
    boton_pdf(
        "PDF COSTOS",
        generar_pdf_matriz_costos(show, "MATRIZ DE COSTOS POR RUBRO Y CENTRO DE COSTO"),
        "costos_matriz.pdf",
        key=key_pdf,
    )

def _mostrar_tabla_costos(dfr_f, key_pdf):
    hay_ajustes = abs(dfr_f["Ajustes"].sum()) > 0.5
    if es_admin() and hay_ajustes:
        cols_vis = list(dfr_f.columns)
    else:
        cols_vis = [c for c in dfr_f.columns if c != "Ajustes"]
    st.dataframe(
        dfr_f[cols_vis].style.format({c: _fmt_styler_peso for c in cols_vis if c != "Cuartel"}),
        use_container_width=True,
    )
    dfr_pdf = dfr_f.drop(columns=["Ajustes"], errors="ignore")
    boton_pdf(
        "PDF COSTOS",
        generar_pdf_blob(dfr_pdf, "INFORME COSTOS CONSOLIDADOS POR CUARTEL", incluir_precios=False),
        "costos.pdf",
        key=key_pdf,
    )

def _mostrar_detalle_cc_temporada(conn, temporada, fi, ff, cc, matriz_df, total_general, key_prefix, prorrateo_rrhh, fi_rrhh=None, ff_rrhh=None):
    gasto_real = _total_gasto_cc_desde_matriz(matriz_df, cc)
    ppto = _obtener_ppto_temporada(conn, temporada, cc)
    kg_est = _obtener_kg_estimado_temporada(conn, temporada, cc)
    meta = _calc_metricas_produccion_cc(gasto_real, ppto, kg_est)

    _mostrar_widgets_produccion_cc(gasto_real, ppto, kg_est, meta)

    if gasto_real <= 0.5:
        st.divider()
        _mostrar_avance_y_resumen_cc(gasto_real, ppto, total_general, meta)
        st.info(f"Sin movimientos imputados a **{cc}**.")
        return

    st.divider()
    df_cc = _rubros_cc_desde_matriz(matriz_df, cc)
    if not df_cc.empty:
        st.markdown("##### 📂 Desglose por rubro")
        st.dataframe(
            df_cc.style.format({"Monto": _fmt_styler_peso}),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Sin gastos imputados por rubro en este cuartel.")

    st.divider()
    _mostrar_avance_y_resumen_cc(gasto_real, ppto, total_general, meta)

    st.divider()
    _mostrar_lista_detalle_gastos_cc(
        conn, cc, prorrateo_rrhh, f"{key_prefix}_det", fi, ff, fi_rrhh, ff_rrhh,
    )

def _render_temporada_costos(conn, temporada, fi, ff, cuarteles, prorrateo_rrhh, key_prefix):
    es_vigente = fi <= hoy <= ff
    fi_cons, ff_cons = _rango_fechas_costos_consulta(conn, fi, ff, es_vigente)
    if es_vigente:
        matriz = _armar_matriz_costos_vista_b(
            conn, fi_cons, ff_cons, cuarteles, prorrateo_rrhh, temporada,
            fi_rrhh=fi, ff_rrhh=ff,
        )
        det_fi, det_ff = fi_cons, ff_cons
        ext_txt = ""
        if fi_cons < fi:
            ext_txt = (
                f" Incluye movimientos desde **{fi_cons.strftime('%d-%m-%Y')}** "
                f"(anteriores al inicio formal de temporada {fi.strftime('%d-%m-%Y')})."
            )
        caption = (
            "Matriz de costos — temporada vigente. Clasifique gastos históricos en "
            "**Compras → Historial → Corregir** (tipo de gasto). "
            f"Operativos hasta **{ff_cons.strftime('%d-%m-%Y')}**; RRHH desde liquidaciones."
            + ext_txt
        )
    else:
        matriz = _armar_matriz_costos_vista_b(
            conn, fi, ff, cuarteles, prorrateo_rrhh, temporada,
        )
        det_fi, det_ff = fi, ff
        caption = (
            f"Matriz de costos — temporada **{temporada}** ({fi.strftime('%d-%m-%Y')} al {ff.strftime('%d-%m-%Y')}). "
            "RRHH: suma de liquidaciones del período."
        )
    if matriz is None or matriz.empty:
        st.info("Sin datos de costos.")
        return
    total_general = _total_gasto_general_matriz(matriz)
    sub_labels = ["📊 Resumen"] + [cc for cc in cuarteles]
    sec_mat = nav_seccion(sub_labels, f"{key_prefix}_cc_nav", "Vista")
    if sec_mat == sub_labels[0]:
        _mostrar_matriz_costos_vista_b(matriz, f"{key_prefix}_pdf_res")
    else:
        i_cc = sub_labels.index(sec_mat) - 1
        cc = cuarteles[i_cc]
        _mostrar_detalle_cc_temporada(
            conn, temporada, det_fi, det_ff, cc, matriz, total_general,
            f"{key_prefix}_cc{i_cc}", prorrateo_rrhh,
            fi_rrhh=fi if es_vigente else None,
            ff_rrhh=ff if es_vigente else None,
        )

def panel_correccion_costos(conn):
    st.divider()
    st.subheader("🔧 Corrección de costos (Administrador)")
    st.caption("Elimine duplicados en la fuente o ajustes manuales de la etapa de prueba. Los totales se recalculan al instante.")

    _cost_corr = ["📋 Ajustes manuales", "🔍 Duplicados detectados", "🗑️ Eliminar imputación"]
    sec_corr = nav_seccion(_cost_corr, "cost_corr_nav", "Corrección")

    if sec_corr == _cost_corr[0]:
        df_aj = pd.read_sql_query(
            "SELECT id, centro_costo as Cuartel, monto as Monto, fecha as Fecha, motivo as Motivo FROM ajustes_costos ORDER BY id",
            conn,
        )
        if df_aj.empty:
            st.success("No hay ajustes manuales registrados.")
        else:
            st.dataframe(df_aj.style.format({"Monto": _fmt_styler_peso}), use_container_width=True)
            id_aj = st.number_input("ID de ajuste a eliminar", min_value=1, step=1, key="cost_del_aj_id")
            clv_aj_del = st.text_input("Clave Maestra", type="password", key="cost_del_aj_clv")
            if st.button("🗑️ Eliminar ajuste", key="cost_del_aj_btn"):
                if clv_aj_del == CLAVE_MAESTRA:
                    conn.execute("DELETE FROM ajustes_costos WHERE id=?", (id_aj,))
                    conn.commit()
                    registrar_accion("BORRADO AJUSTE COSTOS", f"ID {id_aj}")
                    st.success(f"Ajuste ID {id_aj} eliminado.")
                    st.rerun()
                else:
                    st.error("Clave incorrecta.")

    elif sec_corr == _cost_corr[1]:
        df_dup = pd.read_sql_query(
            """SELECT MIN(id) as id_ejemplo, nro_documento as Documento, proveedor as Proveedor,
                      centro_costo as Cuartel, COUNT(*) as Veces, SUM(monto_imputado) as Total_imputado
               FROM facturas WHERE nro_documento LIKE '%_P' AND IFNULL(centro_costo,'') != ''
               GROUP BY nro_documento, proveedor, centro_costo HAVING COUNT(*) > 1
               ORDER BY proveedor, centro_costo""",
            conn,
        )
        if df_dup.empty:
            st.success("No se detectan imputaciones duplicadas por cuartel.")
        else:
            st.warning("Estas imputaciones aparecen más de una vez en el mismo cuartel:")
            st.dataframe(df_dup.style.format({"Total_imputado": _fmt_styler_peso}), use_container_width=True)
            st.info("Use la sección **Eliminar imputación** con el ID exacto del registro sobrante.")

    elif sec_corr == _cost_corr[2]:
        df_imp = pd.read_sql_query(
            """SELECT id, nro_documento as Documento, proveedor as Proveedor, centro_costo as Cuartel,
                      monto_imputado as Monto, fecha_compra as Fecha, concepto as Detalle
               FROM facturas WHERE nro_documento LIKE '%_P' AND IFNULL(centro_costo,'') != ''
               ORDER BY id DESC LIMIT 80""",
            conn,
        )
        st.dataframe(df_imp.style.format({"Monto": _fmt_styler_peso}), use_container_width=True)
        id_imp = st.number_input("ID de imputación (_P) a eliminar", min_value=1, step=1, key="cost_del_imp_id")
        clv_imp = st.text_input("Clave Maestra", type="password", key="cost_del_imp_clv")
        if st.button("🗑️ Eliminar imputación de costo", type="primary", key="cost_del_imp_btn"):
            if clv_imp == CLAVE_MAESTRA:
                row = pd.read_sql_query(
                    "SELECT id, nro_documento, proveedor, centro_costo, monto_imputado FROM facturas WHERE id=?",
                    conn, params=(id_imp,),
                )
                if row.empty:
                    st.error("ID no encontrado.")
                elif not str(row.iloc[0]["nro_documento"]).endswith("_P"):
                    st.error("Solo se pueden eliminar imputaciones de costo (registros _P).")
                else:
                    conn.execute("DELETE FROM facturas WHERE id=?", (id_imp,))
                    conn.commit()
                    r = row.iloc[0]
                    registrar_accion("BORRADO IMPUTACION COSTO", f"ID {id_imp} | {r['proveedor']} | {r['centro_costo']} | ${r['monto_imputado']}")
                    st.success(f"Imputación ID {id_imp} eliminada. Los costos se actualizaron.")
                    st.rerun()
            else:
                st.error("Clave incorrecta.")

def modulo_costos():
    encabezado_modulo("Costos", "💰 COSTOS CONSOLIDADOS")
    conn = conectar_db()
    prorrateo_rrhh = cargar_prorrateo_cc(conn)
    nombre, fi, ff = nav_temporada(TEMPORADAS_COSTOS, "costos_temp_nav", hoy=hoy)
    _render_temporada_costos(
        conn, nombre, fi, ff, CUARTELES_OFICIALES, prorrateo_rrhh,
        f"costos_{nombre.replace('-', '_')}",
    )
    if st.session_state['email'] == 'osvaldolira@laconcepcion.cl':
        panel_correccion_costos(conn)
        st.divider(); st.subheader("➕ INGRESAR AJUSTE DE COSTOS")
        with st.form("form_ajuste_manual", clear_on_submit=True):
            cc_aj = st.selectbox("Centro de Costo", CENTROS_COSTO, key="aj_1")
            f_aj = st.date_input("Fecha Ajuste", hoy, key="aj_2")
            mot_aj = st.text_input("Motivo Ajuste", key="aj_3")
            monto_aj = st.number_input("Monto Ajuste ($)", value=0.0, key="aj_4")
            clv_aj = st.text_input("Clave Maestra", type="password", key="aj_5")
            if st.form_submit_button("GUARDAR AJUSTE"):
                if clv_aj == CLAVE_MAESTRA:
                    if monto_aj != 0 and mot_aj.strip() != "":
                        conn.execute("INSERT INTO ajustes_costos (centro_costo, monto, fecha, motivo) VALUES (?,?,?,?)", (cc_aj.upper(), monto_aj, str(f_aj), mot_aj.strip()))
                        conn.commit(); registrar_accion("AJUSTE COSTOS", f"Cuartel: {cc_aj} | Monto: {monto_aj}")
                        st.success("✅ Ajuste ingresado."); st.rerun()
    conn.close()


def _style_celda_flujo_proy(val):
    try:
        if float(val or 0) > 0.01:
            return "background-color: #FFF3E0; color: #E65100; font-weight: 600"
    except (TypeError, ValueError):
        pass
    return ""


def _style_celda_negativo_rojo(val):
    """Solo el número en rojo; no altera el fondo de la celda."""
    try:
        if float(val or 0) < -0.01:
            return "color: #C62828; font-weight: 600"
    except (TypeError, ValueError):
        pass
    return ""


def _style_col_flujo_proy(df_base, col_proy, col_valor, n_filas_datos=None):
    """Fondo naranjo si es proyección; texto rojo si el monto es negativo."""
    if n_filas_datos is None:
        n_filas_datos = len(df_base)

    def _aplicar(col):
        estilos = []
        for i, val in enumerate(col):
            if i >= n_filas_datos:
                try:
                    monto = float(val or 0)
                except (TypeError, ValueError):
                    monto = 0.0
                estilo = "font-weight: 700; background-color: #ECEFF1"
                if monto < -0.01:
                    estilo += "; color: #C62828"
                estilos.append(estilo)
                continue
            try:
                proy = float(df_base.iloc[i][col_proy] or 0)
                monto = float(df_base.iloc[i][col_valor] or 0)
            except (TypeError, ValueError, IndexError):
                proy, monto = 0.0, 0.0
            partes = []
            if proy > 0.01 and monto > 0.01:
                partes.append("background-color: #FFF3E0")
            if monto < -0.01:
                partes.append("color: #C62828")
                partes.append("font-weight: 600")
            elif proy > 0.01 and monto > 0.01:
                partes.append("color: #E65100")
                partes.append("font-weight: 600")
            estilos.append("; ".join(partes))
        return estilos

    return _aplicar


def _style_col_negativo_desde_base(df_base, col_base, n_filas_datos=None):
    if n_filas_datos is None:
        n_filas_datos = len(df_base)

    def _aplicar(col):
        estilos = []
        for i, val in enumerate(col):
            if i >= n_filas_datos:
                try:
                    monto = float(val or 0)
                except (TypeError, ValueError):
                    monto = 0.0
                estilo = "font-weight: 700; background-color: #ECEFF1"
                if monto < -0.01:
                    estilo += "; color: #C62828"
                estilos.append(estilo)
                continue
            try:
                monto = float(df_base.iloc[i][col_base] or 0)
            except (TypeError, ValueError, IndexError, KeyError):
                monto = 0.0
            estilos.append(_style_celda_negativo_rojo(monto))
        return estilos

    return _aplicar


def _style_proy_flujo_con_total(n_filas_datos):
    def _aplicar(col):
        return [
            _style_celda_flujo_proy(v) if i < n_filas_datos
            else "font-weight: 700; background-color: #ECEFF1"
            for i, v in enumerate(col)
        ]

    return _aplicar


def _style_fila_total_tabla(n_filas_datos):
    def _aplicar(col):
        return [
            "font-weight: 700; background-color: #ECEFF1" if i >= n_filas_datos else ""
            for i in range(len(col))
        ]

    return _aplicar


_FLUJO_COLOR_INGRESOS = "#2E7D32"
_FLUJO_COLOR_EGRESOS = "#C62828"
_FLUJO_COLOR_RESULTADOS = "#1565C0"

_COLS_FLUJO_ENC_INGRESOS = {"INGRESOS"}
_COLS_FLUJO_ENC_EGRESOS = {
    "RRHH SUELDOS", "TESO REAL", "TESO PROY", "EGRESOS REAL", "EGRESOS PROY", "EGRESOS TOTAL",
}
_COLS_FLUJO_ENC_RESULTADOS = {"RESULTADO MES", "EERR ACUM"}


def _metric_flujo(label, valor, tipo):
    """Widget resumen con banda de color: ingreso=verde, egreso=rojo, resultado=azul."""
    if tipo == "ingreso":
        bg, fg = _FLUJO_COLOR_INGRESOS, "#FFFFFF"
    elif tipo == "egreso":
        bg, fg = _FLUJO_COLOR_EGRESOS, "#FFFFFF"
    elif tipo == "resultado":
        bg, fg = _FLUJO_COLOR_RESULTADOS, "#FFFFFF"
    else:
        bg, fg = "#546E7A", "#FFFFFF"
    valor_txt = str(valor)
    valor_color = "#1F2933"
    if tipo == "resultado" and valor_txt.startswith("-") and valor_txt not in ("—", "-"):
        valor_color = _FLUJO_COLOR_EGRESOS
    st.markdown(
        f"""<div style="border:1px solid {bg};border-radius:8px;overflow:hidden;margin-bottom:4px;">
        <div style="background:{bg};color:{fg};font-size:12px;padding:6px 10px;font-weight:600;line-height:1.3;">{label}</div>
        <div style="font-size:28px;font-weight:600;padding:8px 10px 10px;color:{valor_color};line-height:1.2;">{valor_txt}</div>
        </div>""",
        unsafe_allow_html=True,
    )


def _inyectar_css_tabla_flujo():
    st.markdown(
        """
        <style>
        .flujo-tabla-principal { width: 100%; overflow-x: auto; margin: 0.25rem 0 0.75rem; }
        .flujo-tabla-principal table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
        .flujo-tabla-principal thead th {
            font-weight: 700 !important;
            text-align: center !important;
            white-space: nowrap;
            padding: 0.35rem 0.55rem !important;
        }
        .flujo-tabla-principal tbody td {
            padding: 0.35rem 0.55rem !important;
        }
        .flujo-tabla-principal thead th:first-child {
            background-color: #ECEFF1 !important;
            color: #1F2933 !important;
        }
        .flujo-tabla-principal thead th:not(:first-child) {
            color: #FFFFFF !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _aplicar_encabezados_flujo(styler):
    styles = [{
        "selector": "th.col_heading.level0.col0, thead th:nth-child(1)",
        "props": [
            ("background-color", "#ECEFF1"),
            ("color", "#1F2933"),
            ("font-weight", "700"),
            ("text-align", "center"),
        ],
    }]
    for i, col in enumerate(styler.columns):
        if col in _COLS_FLUJO_ENC_INGRESOS:
            bg, fg = _FLUJO_COLOR_INGRESOS, "#FFFFFF"
        elif col in _COLS_FLUJO_ENC_EGRESOS:
            bg, fg = _FLUJO_COLOR_EGRESOS, "#FFFFFF"
        elif col in _COLS_FLUJO_ENC_RESULTADOS:
            bg, fg = _FLUJO_COLOR_RESULTADOS, "#FFFFFF"
        else:
            continue
        props = [
            ("background-color", bg),
            ("color", fg),
            ("font-weight", "700"),
            ("text-align", "center"),
        ]
        styles.append({"selector": f"th.col_heading.level0.col{i}", "props": props})
        styles.append({"selector": f"thead th:nth-child({i + 1})", "props": props})
    return styler.set_table_styles(styles, overwrite=False)


def _styler_peso_con_negativos(df, cols):
    styler = df.style.format({c: _fmt_styler_peso for c in cols})
    for c in cols:
        styler = styler.map(_style_celda_negativo_rojo, subset=[c])
    return styler


def _render_flujo_temporada(conn, nombre, fi, ff, key_prefix):
    es_vigente = fi <= hoy <= ff
    vigente_txt = " · **temporada en curso**" if es_vigente else ""
    st.caption(
        f"Período **{fi.strftime('%d-%m-%Y')}** → **{ff.strftime('%d-%m-%Y')}**{vigente_txt}. "
        "Egresos alineados al **módulo Costos** (mismo ppto, gastado y saldo por CC)."
    )
    resumen_costos = _resumen_costos_para_flujo(conn, nombre, fi, ff)
    df_flujo, df_cc, df_eg_cc, meta = armar_flujo_financiero(
        conn, nombre, fi, ff, hoy, CUARTELES_OFICIALES, resumen_costos,
    )

    if df_flujo.empty:
        st.info("Sin meses proyectables en esta temporada desde la fecha actual.")
    else:
        tot_ing = df_flujo["INGRESOS"].sum()
        tot_eg_real = df_flujo["EGRESOS_REAL"].sum()
        tot_eg_proy = df_flujo["EGRESOS_PROY"].sum()
        eerr_final = df_flujo["EERR_ACUM"].iloc[-1]
        k1, k2, k3, k4, k5 = st.columns(5)
        with k1:
            _metric_flujo("Ingresos proyectados", f"${f_puntos(tot_ing)}", "ingreso")
        with k2:
            _metric_flujo("Gastado imputado (Costos)", f"${f_puntos(meta['total_gastado'])}", "egreso")
        with k3:
            _metric_flujo(
                "Cuentas por pagar",
                f"${f_puntos(meta.get('teso_cxp_bruto', meta.get('teso_cxp_total', tot_eg_real)))}",
                "egreso",
            )
        with k4:
            _metric_flujo("Egresos caja proy.", f"${f_puntos(tot_eg_proy)}", "egreso")
        with k5:
            _metric_flujo("EERR acumulado", f"${f_puntos(eerr_final)}", "resultado")
        st.caption(
            "**Gastado imputado** = acumulado del módulo Costos. "
            "**Egresos caja** = Tesorería + RRHH desde el mes en curso (o desde inicio de temporada si es futura)."
        )

        st.markdown(
            f"<span style='background:#E3F2FD;padding:2px 8px;border-radius:6px;margin-right:8px;'>■ Real</span>"
            f"<span style='background:#FFF3E0;color:#E65100;padding:2px 8px;border-radius:6px;'>■ Proyectado</span>",
            unsafe_allow_html=True,
        )
        st.caption(
            "**EGRESOS TOTAL** = TESO REAL + TESO PROY + RRHH. "
            "Fondo naranjo = monto **proyectado**."
        )

        df_show = df_flujo[
            ["MES", "INGRESOS", "RRHH", "TESO_REAL", "TESO_PROY", "EGRESOS_REAL", "EGRESOS_PROY", "EGRESOS_TOTAL", "RESULTADO_MES", "EERR_ACUM"]
        ].copy()
        n_meses = len(df_show)
        df_show = pd.concat(
            [df_show, pd.DataFrame([fila_total_flujo_mensual(df_flujo)])],
            ignore_index=True,
        )
        df_show = df_show.rename(
            columns={
                "RRHH": "RRHH SUELDOS",
                "TESO_REAL": "TESO REAL",
                "TESO_PROY": "TESO PROY",
                "EGRESOS_REAL": "EGRESOS REAL",
                "EGRESOS_PROY": "EGRESOS PROY",
                "EGRESOS_TOTAL": "EGRESOS TOTAL",
                "RESULTADO_MES": "RESULTADO MES",
                "EERR_ACUM": "EERR ACUM",
            }
        )
        if meta.get("meses_historial"):
            st.info(
                "Se muestran los meses ya corridos de la temporada (solo montos reales) y la "
                f"proyección desde **{meta.get('mes_inicio_proyeccion') or 'el mes en curso'}**. "
                f"Historial: {', '.join(meta.get('meses_historial') or [])}."
            )
        if meta.get("saldo_caja_inicial", 0) > 0.01 and meta.get("mes_caja_aplicada"):
            st.info(
                f"El ingreso de **{meta['mes_caja_aplicada']}** incluye flujo proyectado "
                f"(${f_puntos(meta['ingresos_flujo_mes_caja'])}) + saldo caja inicial "
                f"(${f_puntos(meta['saldo_caja_inicial'])}), cargado en Administración → Ingresos flujo."
            )
        fmt = {
            "INGRESOS": _fmt_styler_peso,
            "RRHH SUELDOS": _fmt_styler_peso,
            "TESO REAL": _fmt_styler_peso,
            "TESO PROY": _fmt_styler_peso,
            "EGRESOS REAL": _fmt_styler_peso,
            "EGRESOS PROY": _fmt_styler_peso,
            "EGRESOS TOTAL": _fmt_styler_peso,
            "RESULTADO MES": _fmt_styler_peso,
            "EERR ACUM": _fmt_styler_peso,
        }
        styler = df_show.style.format(fmt)
        styler = styler.apply(_style_col_flujo_proy(df_flujo, "RRHH_PROY", "RRHH", n_meses), subset=["RRHH SUELDOS"])
        styler = styler.apply(_style_proy_flujo_con_total(n_meses), subset=["TESO PROY"])
        styler = styler.apply(_style_proy_flujo_con_total(n_meses), subset=["EGRESOS PROY"])
        styler = styler.apply(_style_col_negativo_desde_base(df_flujo, "RESULTADO_MES", n_meses), subset=["RESULTADO MES"])
        styler = styler.apply(_style_col_negativo_desde_base(df_flujo, "EERR_ACUM", n_meses), subset=["EERR ACUM"])
        for col_tot in ("MES", "INGRESOS", "EGRESOS REAL", "EGRESOS TOTAL"):
            styler = styler.apply(_style_fila_total_tabla(n_meses), subset=[col_tot])
        styler = _aplicar_encabezados_flujo(styler)
        _inyectar_css_tabla_flujo()
        html_tabla = styler.hide(axis="index").to_html()
        st.markdown(f'<div class="flujo-tabla-principal">{html_tabla}</div>', unsafe_allow_html=True)

        with st.expander("Detalle egresos (Tesorería / RRHH)"):
            df_det = df_flujo[["MES", "TESO_REAL", "TESO_PROY", "RRHH_REAL", "RRHH_PROY"]].rename(
                columns={
                    "TESO_REAL": "Teso. real",
                    "TESO_PROY": "Teso. proy.",
                    "RRHH_REAL": "RRHH real",
                    "RRHH_PROY": "RRHH proy.",
                }
            )
            st.dataframe(
                df_det.style.format({
                    "Teso. real": _fmt_styler_peso,
                    "Teso. proy.": _fmt_styler_peso,
                    "RRHH real": _fmt_styler_peso,
                    "RRHH proy.": _fmt_styler_peso,
                })
                .map(_style_celda_flujo_proy, subset=["Teso. proy.", "RRHH proy."])
                .map(_style_celda_negativo_rojo, subset=["Teso. real", "RRHH real"]),
                use_container_width=True,
                hide_index=True,
                height=48 + len(df_det) * 38,
            )
            st.caption(
                f"Presupuesto temporada (Costos): **${f_puntos(meta['total_ppto'])}** · "
                f"Gastado imputado: **${f_puntos(meta['total_gastado'])}** · "
                f"**Saldo restante: ${f_puntos(meta['total_saldo_ppto'])}** · "
                f"Tesorería con vencimiento en el período: **${f_puntos(meta['teso_programada_flujo'])}** · "
                f"Saldo operacional a proyectar: **${f_puntos(meta['saldo_a_proyectar_teso_bruto'])}** "
                f"en **{meta['meses_sin_teso']}** mes(es). "
                f"RRHH base proy.: **${f_puntos(meta['rrhh_base_proy_bruto'])}**/mes. "
                f"Tope egresos futuros (real + proy.): **${f_puntos(meta['egresos_tope'])}** (saldo Costos). "
                + (
                    f"Tesorería proy. al **{meta['factor_teso']*100:.0f}%** del cálculo teórico."
                    if meta.get("factor_teso", 1.0) < 0.999
                    else ""
                )
                + (
                    f" RRHH proy. al **{meta['factor_rrhh']*100:.0f}%** del cálculo teórico."
                    if meta.get("factor_rrhh", 1.0) < 0.999
                    else ""
                )
            )

        boton_pdf(
            "PDF FLUJO FINANCIERO",
            generar_pdf_blob(
                df_flujo_para_pdf(df_flujo),
                f"FLUJO FINANCIERO — {nombre}",
                incluir_precios=False,
            ),
            f"flujo_financiero_{key_prefix}.pdf",
            key=f"flujo_pdf_{key_prefix}",
        )

    st.markdown("##### Presupuesto y proyección de egresos por CC")
    st.caption(
        "**GASTADO** y **SALDO** = mismos totales que **Costos** para esta temporada. "
        "**A proyectar** = saldo menos lo ya programado en Tesorería."
    )
    if not df_eg_cc.empty:
        cols_eg = [c for c in df_eg_cc.columns if c != "CENTRO_COSTO"]
        st.dataframe(
            _styler_peso_con_negativos(df_eg_cc, cols_eg),
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("##### Ingresos proyectados por centro de costo")
    st.caption("La columna **INGRESOS** del flujo es la suma de todos los CC por mes.")
    if not df_cc.empty:
        cc_cols = [c for c in df_cc.columns if c not in ("CENTRO_COSTO",)]
        st.dataframe(
            df_cc.style.format({c: _fmt_styler_peso for c in cc_cols if c != "CENTRO_COSTO"}),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info(
            f"Sin ingresos por CC cargados para **{nombre}**. "
            "Use Administración → Ingresos flujo financiero."
        )
    notas_rows = []
    notas_map = cargar_notas_ingresos_cc(conn, nombre)
    ing_map = cargar_ingresos_cc(conn, nombre)
    for (cc, anio, mes), nota in sorted(notas_map.items()):
        txt = str(nota or "").strip()
        if txt:
            notas_rows.append({
                "CENTRO_COSTO": cc,
                "MES": _mes_label(anio, mes),
                "INGRESO": ing_map.get((cc, anio, mes), 0.0),
                "NOTA": txt,
            })
    if notas_rows:
        with st.expander("Notas explicativas de ingresos"):
            st.dataframe(
                pd.DataFrame(notas_rows),
                use_container_width=True,
                hide_index=True,
            )


def modulo_flujo_financiero():
    encabezado_modulo("Flujo financiero", "📈 FLUJO FINANCIERO")
    conn = conectar_db()
    st.caption(
        "Proyección de ingresos y egresos por **temporada agrícola**. "
        "Las proyecciones naranjas no superan el **saldo presupuestario restante**."
    )
    tab_labels = [f"📅 {t[0]}" for t in TEMPORADAS_COSTOS]
    nombre, fi, ff = nav_temporada(TEMPORADAS_COSTOS, "flujo_temp_nav", hoy=hoy)
    _render_flujo_temporada(
        conn, nombre, fi, ff, nombre.replace("-", "_"),
    )
    conn.close()


def modulo_maquinaria():
    inyectar_fondo_maquinaria()
    st.markdown('<div class="maq-module-marker"></div>', unsafe_allow_html=True)
    inyectar_css_tabs_maquinaria()
    conn = conectar_db()
    encabezado_modulo("Maquinaria", "🚜 BITÁCORA DE MAQUINARIA")
    st.markdown('<div class="maq-tabs-principal"></div>', unsafe_allow_html=True)
    _maq_secc = ["Faenas", "Mantención", "Historial"]
    sec_maq = nav_seccion(_maq_secc, "maq_nav", "Sección")

    if sec_maq == _maq_secc[0]:
        render_tab_asignacion_faena_diaria(
            conn,
            registrar_accion,
            CENTROS_COSTO,
            hoy,
            boton_pdf_fn=boton_pdf,
            generar_pdf_fn=generar_pdf_blob,
            nombre_erp="ERP La Concepción",
        )

    elif sec_maq == _maq_secc[1]:
        with st.form("form_registro_maquinaria", clear_on_submit=True):
            col_m1, col_m2 = st.columns(2)
            with col_m1:
                cod_maquina = render_select_maquinaria(conn, key="maq_reg_id", label="Maquinaria")
            tipo_ev = col_m1.selectbox("Tipo de Evento", TIPOS_EVENTO_MAQ, key="maq_reg_tipo")
            f_evento = col_m1.date_input("Fecha", hoy, key="maq_reg_fecha")
            
            encargado = col_m2.text_input("Encargado / Proveedor", key="maq_reg_enc")
            responsable = col_m2.text_input("Responsable Interno", key="maq_reg_resp")
            etiqueta = col_m2.selectbox("Estado de Ingreso", ETIQUETAS_MAQ, key="maq_reg_etiq")
            
            detalle = st.text_area("Descripción Reparación", key="maq_reg_det")
            
            if st.form_submit_button("💾 GUARDAR EN BITÁCORA"):
                if not cod_maquina or detalle.strip() == "" or responsable.strip() == "":
                    st.error("❌ Seleccione maquinaria de la maestra y complete los campos obligatorios.")
                else:
                    id_maquina = cod_maquina
                    cursor = conn.cursor()
                    cursor.execute("SELECT MAX(id) FROM bitacora_maquinaria")
                    res_max = cursor.fetchone()[0]
                    prox_id = (int(res_max) + 1) if res_max else 1
                    cod_unico = f"MANT-{prox_id:05d}"
                    
                    conn.execute("""INSERT INTO bitacora_maquinaria 
                        (cod_registro, id_maquinaria, tipo_evento, detalle_mantenimiento, encargado_taller, responsable_interno, fecha_evento, etiqueta_ingreso) 
                        VALUES (?,?,?,?,?,?,?,?)""",
                        (cod_unico, id_maquina, tipo_ev, detalle.strip(), encargado.strip(), responsable.strip(), str(f_evento), etiqueta))
                    conn.commit()
                    registrar_accion("MAQUINARIA", f"Registro {cod_unico} - {id_maquina}")
                    st.success(f"✅ Evento guardado con éxito bajo el código: {cod_unico}")
                    st.rerun()
                    
    elif sec_maq == _maq_secc[2]:
        filtro_opts = opciones_filtro_maquinaria(conn)
        opts_maquinas = ["TODAS"] + [c for c, _ in filtro_opts]
        label_por_cod = {c: lbl for c, lbl in filtro_opts}
        
        cc_m1, cc_m2, cc_m3 = st.columns(3)
        filtro_maq = cc_m1.selectbox(
            "Filtrar Maquinaria",
            opts_maquinas,
            format_func=lambda c: "TODAS" if c == "TODAS" else label_por_cod.get(c, c),
            key="maq_fil_maq",
        )
        fi_maq = cc_m2.date_input("Desde", hoy - timedelta(days=180), key="maq_fil_fi")
        ff_maq = cc_m3.date_input("Hasta", hoy, key="maq_fil_ff")
        
        query_maq = f"""SELECT b.cod_registro as [N° ÚNICO], b.fecha_evento as FECHA,
            COALESCE(m.codigo || ' — ' || m.nombre, b.id_maquinaria) as MAQUINARIA,
            b.tipo_evento as [TIPO EVENTO], b.detalle_mantenimiento as DESCRIPCIÓN,
            b.encargado_taller as [ENCARGADO TALLER], b.responsable_interno as RESPONSABLE,
            b.etiqueta_ingreso as ETIQUETA
            FROM bitacora_maquinaria b
            LEFT JOIN maestra_maquinaria m ON UPPER(TRIM(m.codigo)) = UPPER(TRIM(b.id_maquinaria))
            WHERE b.fecha_evento BETWEEN '{fi_maq}' AND '{ff_maq}'"""
        
        if filtro_maq != "TODAS":
            query_maq += f" AND UPPER(TRIM(b.id_maquinaria)) = '{filtro_maq.upper()}'"
            
        query_maq += " ORDER BY b.id DESC"
        
        df_maq_f = pd.read_sql_query(query_maq, conn)
        codigos_rep = _codigos_maquinaria_en_reparacion(conn)
        df_styled = estilo_historial_maquinaria(df_maq_f, codigos_rep)
        st.dataframe(df_styled, use_container_width=True)
        render_panel_cerrar_casos_maquinaria(conn, registrar_accion)
        
        if not df_maq_f.empty:
            boton_pdf("PDF BITÁCORA MAQUINARIA",
                      generar_pdf_blob(df_maq_f, f"REPORTE DE MANTENCIONES ({fi_maq} a {ff_maq})", incluir_precios=False),
                      "bitacora_maquinaria.pdf", key="maq_pdf_btn")
            
    conn.close()

def panel_planificacion_gantt(conn, especie):
    inicio = inicio_gestion_gantt()
    cosecha_esp = fecha_cosecha_ciruelos_planificada() if especie == "Ciruelos" else fecha_cosecha_planificada(inicio.year)
    st.markdown(f"#### 📅 Planificación — Carta Gantt ({especie})")
    st.caption(
        f"Inicio gestión: **lunes {inicio.strftime('%d-%m-%Y')}** · "
        f"Cosecha {especie.lower()} planificada: **{cosecha_esp.strftime('%d-%m-%Y')}**"
    )
    umbrales = obtener_umbrales_gantt(conn)
    df_all = cargar_tareas_gantt(conn, especie=especie)
    alertas = df_all[df_all["indice_alerta"] >= 50].sort_values("indice_alerta", ascending=False) if not df_all.empty else df_all
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Actividades", len(df_all))
    c2.metric("En ritmo", len(df_all[df_all["nivel_alerta"].isin(["En ritmo", "Completada"])]) if not df_all.empty else 0)
    c3.metric("Con desfase", len(df_all[df_all["desfase_pct"] > 0]) if not df_all.empty else 0)
    c4.metric("Alertas activas", len(alertas))
    prom_av = round(df_all["avance_pct"].mean(), 1) if not df_all.empty else 0
    c5.metric("Avance promedio", f"{prom_av}%")

    if not alertas.empty:
        crit = len(alertas[alertas["nivel_alerta"].isin(["Crítico", "Vencida"])])
        if crit:
            st.markdown(f'<div class="alert-roja">🚨 {crit} actividad(es) con alerta crítica o vencida — desfase respecto al avance esperado.</div>', unsafe_allow_html=True)
        med = len(alertas[alertas["nivel_alerta"].isin(["Alto", "Medio"])])
        if med:
            st.markdown(f'<div class="alert-amarilla">⚠️ {med} actividad(es) con desfase medio o alto según umbrales configurados.</div>', unsafe_allow_html=True)

    _gantt_secc = ["📊 Carta Gantt", "🚨 Alertas", "➕ Gestión", "⚙️ Umbrales"]
    sec_gantt = nav_seccion(_gantt_secc, f"gantt_nav_{especie}", "Sección")

    if sec_gantt == _gantt_secc[0]:
        proys = pd.read_sql_query(
            f"SELECT id, nombre FROM gantt_proyectos WHERE estado='Activo' AND (COALESCE(especie,'Cerezos')='{especie}' OR COALESCE(especie,'Cerezos')='{GAP_ESPECIE_GENERAL}') ORDER BY nombre",
            conn,
        )
        opts = ["Todos los proyectos"] + proys["nombre"].tolist()
        filtro = st.selectbox("Proyecto", opts, key=f"gantt_filtro_proy_{especie}")
        pid = None
        if filtro != "Todos los proyectos" and not proys.empty:
            pid = int(proys.loc[proys["nombre"] == filtro, "id"].iloc[0])
        df_v = cargar_tareas_gantt(conn, pid, especie=especie)
        st.markdown(
            """<div class="gantt-leyenda">
            <span><i class="gantt-dot" style="background:#2E7D32"></i> En ritmo / Completada</span>
            <span><i class="gantt-dot" style="background:#1565C0"></i> Bajo (desfase &lt; umbral medio)</span>
            <span><i class="gantt-dot" style="background:#F9A825"></i> Medio (≥ """ + f'{umbrales["medio"]}' + """%)</span>
            <span><i class="gantt-dot" style="background:#E65100"></i> Alto (≥ """ + f'{umbrales["alto"]}' + """%)</span>
            <span><i class="gantt-dot" style="background:#B71C1C"></i> Crítico / Vencida (≥ """ + f'{umbrales["critico"]}' + """%)</span>
            </div>""",
            unsafe_allow_html=True,
        )
        mostrar_gantt(df_v)
        if not df_v.empty:
            st.caption("La línea roja marca la fecha de hoy. El color de cada barra se calcula comparando el % real vs. el % esperado según fechas planificadas.")
            df_tabla = df_v[[
                "proyecto", "actividad", "fecha_inicio", "fecha_fin", "avance_pct",
                "avance_esperado", "desfase_pct", "nivel_alerta", "responsable", "prioridad",
            ]].copy()
            df_tabla.columns = ["PROYECTO", "ACTIVIDAD", "INICIO", "FIN", "% REAL", "% ESPERADO", "DESFASE", "ALERTA", "RESPONSABLE", "PRIORIDAD"]
            st.dataframe(df_tabla, use_container_width=True)
            pdf_globalgap(df_tabla, "Carta Gantt", especie, "gantt", detalle=filtro, estilo_celda_fn=_pdf_estilo_gantt_alerta)
        else:
            pdf_globalgap(None, "Carta Gantt", especie, "gantt", detalle=filtro)

    elif sec_gantt == _gantt_secc[1]:
        st.markdown("#### Índice de alertas por % de avance")
        st.markdown(
            f"""| Nivel | Condición | Umbral desfase |
|-------|-----------|----------------|
| **Vencida** | Fecha fin superada y avance &lt; 100% | — |
| **Crítico** | Real muy por debajo del esperado | ≥ {umbrales['critico']}% |
| **Alto** | Desfase significativo | ≥ {umbrales['alto']}% |
| **Medio** | Desfase moderado | ≥ {umbrales['medio']}% |
| **Bajo** | Leve desfase | &gt; 0% y &lt; {umbrales['medio']}% |
| **En ritmo** | Avance real ≥ esperado | 0% |"""
        )
        if alertas.empty:
            st.success("No hay alertas activas en este momento.")
            pdf_globalgap(None, "Alertas Gantt", especie, "alertas")
        else:
            df_alertas = alertas[[
                "proyecto", "actividad", "fecha_inicio", "fecha_fin", "avance_pct",
                "avance_esperado", "desfase_pct", "nivel_alerta", "responsable",
            ]].copy()
            df_alertas.columns = ["PROYECTO", "ACTIVIDAD", "INICIO", "FIN", "% REAL", "% ESPERADO", "DESFASE", "ALERTA", "RESPONSABLE"]
            pdf_globalgap(df_alertas, "Alertas Gantt", especie, "alertas", estilo_celda_fn=_pdf_estilo_gantt_alerta)
            for _, row in alertas.iterrows():
                cls = "alert-roja" if row["nivel_alerta"] in ("Crítico", "Vencida") else ("alert-naranja" if row["nivel_alerta"] == "Alto" else "alert-amarilla")
                st.markdown(
                    f"""<div class="{cls}">
                    <b>{html_lib.escape(row['actividad'])}</b> ({html_lib.escape(row['proyecto'])})<br>
                    Avance real: <b>{row['avance_pct']:.0f}%</b> · Esperado hoy: <b>{row['avance_esperado']:.0f}%</b> ·
                    Desfase: <b>{row['desfase_pct']:.0f}%</b> · Nivel: <b>{html_lib.escape(row['nivel_alerta'])}</b><br>
                    <small>{row['fecha_inicio']} → {row['fecha_fin']} · {html_lib.escape(str(row['responsable'] or ''))}</small>
                    </div>""",
                    unsafe_allow_html=True,
                )

    elif sec_gantt == _gantt_secc[2]:
        _gest_secc = ["Nueva actividad", "Actualizar avance", "Proyectos"]
        sec_gest = nav_seccion(_gest_secc, f"gantt_gest_nav_{especie}", "Gestión")
        if sec_gest == _gest_secc[0]:
            with st.form("gantt_new_task", clear_on_submit=True):
                proy_opts = pd.read_sql_query(
                    f"SELECT id, nombre FROM gantt_proyectos WHERE COALESCE(especie,'Cerezos') IN ('{especie}', '{GAP_ESPECIE_GENERAL}') ORDER BY nombre",
                    conn,
                )
                if proy_opts.empty:
                    st.info("Cree un proyecto antes de registrar actividades.")
                else:
                    p_sel = st.selectbox("Proyecto", proy_opts["nombre"].tolist())
                    act = st.text_input("Actividad")
                    c_a, c_b = st.columns(2)
                    fi = c_a.date_input("Fecha inicio", hoy)
                    ff = c_b.date_input("Fecha fin", hoy + timedelta(days=30))
                    c_c, c_d, c_e = st.columns(3)
                    av = c_c.number_input("% avance inicial", 0.0, 100.0, 0.0, 5.0)
                    resp = c_d.text_input("Responsable")
                    pri = c_e.selectbox("Prioridad", GANTT_PRIORIDADES)
                    notas = st.text_area("Notas")
                    if st.form_submit_button("REGISTRAR ACTIVIDAD"):
                        if act.strip() and ff >= fi:
                            pid_new = int(proy_opts.loc[proy_opts["nombre"] == p_sel, "id"].iloc[0])
                            conn.execute(
                                "INSERT INTO gantt_tareas (proyecto_id, actividad, fecha_inicio, fecha_fin, avance_pct, responsable, prioridad, notas) VALUES (?,?,?,?,?,?,?,?)",
                                (pid_new, act.strip(), str(fi), str(ff), float(av), resp.strip(), pri, notas.strip()),
                            )
                            conn.commit()
                            registrar_accion("GANTT", act.strip())
                            st.success("Actividad registrada.")
                            st.rerun()
                        else:
                            st.error("Complete la actividad y revise las fechas.")
        elif sec_gest == _gest_secc[1]:
            df_up = cargar_tareas_gantt(conn, especie=especie)
            if df_up.empty:
                st.info("No hay actividades para actualizar.")
            else:
                labels = [f"{r['actividad']} ({r['proyecto']})" for _, r in df_up.iterrows()]
                sel_idx = st.selectbox("Actividad", range(len(labels)), format_func=lambda i: labels[i], key="gantt_up_sel")
                row = df_up.iloc[sel_idx]
                st.markdown(f"Avance esperado hoy: **{row['avance_esperado']:.0f}%** · Alerta actual: **{row['nivel_alerta']}**")
                with st.form("gantt_up_avance"):
                    nuevo_av = st.slider("% avance real", 0.0, 100.0, float(row["avance_pct"]), 5.0)
                    nuevo_est = st.selectbox("Estado", GANTT_ESTADOS, index=GANTT_ESTADOS.index(row["estado"]) if row["estado"] in GANTT_ESTADOS else 1)
                    if st.form_submit_button("GUARDAR AVANCE"):
                        conn.execute(
                            "UPDATE gantt_tareas SET avance_pct=?, estado=? WHERE id=?",
                            (float(nuevo_av), nuevo_est, int(row["id"])),
                        )
                        conn.commit()
                        registrar_accion("GANTT AVANCE", f"{row['actividad']} → {nuevo_av:.0f}%")
                        st.success("Avance actualizado.")
                        st.rerun()
        elif sec_gest == _gest_secc[2]:
            with st.form("gantt_new_proy", clear_on_submit=True):
                nom = st.text_input("Nombre del proyecto")
                desc = st.text_area("Descripción")
                c_p1, c_p2 = st.columns(2)
                fi_p = c_p1.date_input("Inicio proyecto", hoy)
                ff_p = c_p2.date_input("Fin proyecto", hoy + timedelta(days=90))
                cc = st.selectbox("Cuartel / centro de costo", cuarteles_gap_especie(especie))
                resp_p = st.text_input("Responsable general")
                if st.form_submit_button("CREAR PROYECTO"):
                    if nom.strip():
                        try:
                            conn.execute(
                                "INSERT INTO gantt_proyectos (nombre, descripcion, fecha_inicio, fecha_fin, centro_costo, responsable, especie) VALUES (?,?,?,?,?,?,?)",
                                (nom.strip(), desc.strip(), str(fi_p), str(ff_p), cc, resp_p.strip(), especie),
                            )
                            conn.commit()
                            registrar_accion("GANTT PROYECTO", nom.strip())
                            st.success("Proyecto creado.")
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error("Ya existe un proyecto con ese nombre.")
                    else:
                        st.error("Ingrese el nombre del proyecto.")

    elif sec_gantt == _gantt_secc[3]:
        st.markdown("#### Umbrales de alerta (desfase % esperado − % real)")
        with st.form("gantt_umbrales"):
            u_crit = st.number_input("Crítico (%)", 5.0, 80.0, float(umbrales["critico"]), 1.0)
            u_alto = st.number_input("Alto (%)", 3.0, 60.0, float(umbrales["alto"]), 1.0)
            u_med = st.number_input("Medio (%)", 1.0, 40.0, float(umbrales["medio"]), 1.0)
            if st.form_submit_button("GUARDAR UMBRALES"):
                if u_crit > u_alto > u_med:
                    for clave, val in [("critico", u_crit), ("alto", u_alto), ("medio", u_med)]:
                        conn.execute("INSERT OR REPLACE INTO gantt_config (clave, valor) VALUES (?,?)", (clave, float(val)))
                    conn.commit()
                    registrar_accion("GANTT UMBRALES", f"C:{u_crit} A:{u_alto} M:{u_med}")
                    st.success("Umbrales actualizados.")
                    st.rerun()
                else:
                    st.error("Los umbrales deben ser decrecientes: Crítico > Alto > Medio.")
        st.info("El avance esperado se calcula automáticamente según los días transcurridos entre fecha inicio y fin de cada actividad.")

def modulo_globalgap():
    encabezado_modulo("GlobalGAP", "🌿 CERTIFICACIÓN GLOBALGAP")
    conn = conectar_db()
    especie = seleccionar_especie_gap()
    cuarteles_esp = cuarteles_gap_especie(especie)
    st.markdown(
        f"""<div style="background:{TEMAS_MODULO['GlobalGAP']['claro']};border:1px solid #80CBC4;
        color:#004D40;padding:0.65rem 1rem;border-radius:10px;margin-bottom:1rem;font-size:0.9rem;">
        Trabajando con <b>{especie}</b> · Cuarteles: {', '.join(cuarteles_esp)}</div>""",
        unsafe_allow_html=True,
    )
    res = resumen_globalgap(conn, especie)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Cumplimiento checklist", f"{res['pct']}%")
    c2.metric("Ítems cumpliendo", f"{res['cumple']}/{res['total_chk']}")
    c3.metric("NC abiertas", res["nc_abiertas"])
    c4.metric("Productos PPPL", res["pppl"])
    c5.metric("Alertas", res["cap_venc"] + res["agua_venc"])
    if res["nc_abiertas"] > 0:
        st.markdown(f'<div class="alert-roja">Hay {res["nc_abiertas"]} no conformidad(es) abierta(s) pendientes de cierre.</div>', unsafe_allow_html=True)
    if res["cap_venc"] > 0:
        st.markdown(f'<div class="alert-amarilla">Hay {res["cap_venc"]} capacitación(es) vencida(s).</div>', unsafe_allow_html=True)
    if res["agua_venc"] > 0:
        st.markdown(f'<div class="alert-amarilla">Revise análisis de agua de riego (más de 12 meses).</div>', unsafe_allow_html=True)

    df_resumen_gap = pd.DataFrame([
        {"Indicador": "Cumplimiento checklist", "Valor": f"{res['pct']}%"},
        {"Indicador": "Ítems cumpliendo", "Valor": f"{res['cumple']}/{res['total_chk']}"},
        {"Indicador": "NC abiertas", "Valor": res["nc_abiertas"]},
        {"Indicador": "Productos PPPL", "Valor": res["pppl"]},
        {"Indicador": "Alertas capacitación / agua", "Valor": res["cap_venc"] + res["agua_venc"]},
        {"Indicador": "Cuarteles", "Valor": ", ".join(cuarteles_esp)},
        {"Indicador": "Fecha informe", "Valor": str(hoy)},
    ])
    pdf_globalgap(df_resumen_gap, "Resumen certificación", especie, "resumen")

    _gap_secc = [
        "📋 PPPL",
        "📁 Documentos",
        "✅ Autoevaluación",
        "⚠️ NC / AC",
        "🎓 Capacitaciones",
        "🍒 Cosecha / Lotes",
        "💧 Agua",
        "🔧 Calibración",
        "📅 Planificación",
    ]
    sec_gap = nav_seccion(_gap_secc, "gap_nav", "Sección GlobalGAP")

    if sec_gap == _gap_secc[0]:
        st.markdown("#### Lista de productos fitosanitarios autorizados (PPPL)")
        with st.form("gap_pppl_new", clear_on_submit=True):
            c_a, c_b, c_c = st.columns(3)
            p_nom = c_a.text_input("Producto comercial")
            p_ing = c_b.text_input("Ingrediente activo")
            p_dias = c_c.number_input("Días carencia (PHI)", 0, 365, 0)
            p_mer = st.selectbox("Mercado destino", ["General", "UE", "USA", "China", "Nacional"])
            p_not = st.text_input("Notas / Resolución SAG")
            p_esp = st.selectbox("Aplica a especie", [GAP_ESPECIE_GENERAL] + GAP_ESPECIES, index=GAP_ESPECIES.index(especie) + 1 if especie in GAP_ESPECIES else 0)
            if st.form_submit_button("AGREGAR A PPPL"):
                if p_nom.strip():
                    try:
                        conn.execute(
                            "INSERT INTO gap_pppl (producto, ingrediente_activo, dias_carencia, mercado, notas, especie) VALUES (?,?,?,?,?,?)",
                            (p_nom.strip(), p_ing.strip(), int(p_dias), p_mer, p_not.strip(), p_esp),
                        )
                        conn.commit()
                        registrar_accion("GLOBALGAP PPPL", p_nom.strip())
                        st.success("Producto agregado a PPPL.")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("El producto ya existe en PPPL.")
        df_pppl = pd.read_sql_query(
            "SELECT id, producto as PRODUCTO, ingrediente_activo as [ING. ACTIVO], dias_carencia as PHI, mercado as MERCADO, COALESCE(especie,'General') as ESPECIE, vigente as VIGENTE FROM gap_pppl WHERE COALESCE(especie,'General') IN (?, ?) ORDER BY producto",
            conn,
            params=(GAP_ESPECIE_GENERAL, especie),
        )
        st.dataframe(df_pppl, use_container_width=True)
        pdf_globalgap(df_pppl, "PPPL", especie, "pppl", estilo_celda_fn=_pdf_estilo_gap_vigente)
        st.caption("También puede auditar y sincronizar desde bodega en la sección siguiente.")
        st.divider()
        _render_auditoria_pppl_bodega(conn, key_prefix=f"gap_pppl_{especie[:3]}", especie=especie)

    elif sec_gap == _gap_secc[1]:
        with st.form("gap_doc_new", clear_on_submit=True):
            d_tipo = st.selectbox("Tipo", ["Manual BPA", "Mapa campo", "Política integrada", "Análisis agua", "Procedimiento", "Otro"])
            d_tit = st.text_input("Título")
            d_ver = st.text_input("Versión", value="1.0")
            d_vig = st.date_input("Vigente desde", hoy)
            d_resp = st.text_input("Responsable")
            d_not = st.text_area("Notas / ubicación física del documento")
            if st.form_submit_button("REGISTRAR DOCUMENTO"):
                if d_tit.strip():
                    conn.execute(
                        "INSERT INTO gap_documentos (tipo, titulo, version, fecha_vigencia, responsable, notas, fecha_registro, especie) VALUES (?,?,?,?,?,?,?,?)",
                        (d_tipo, d_tit.strip(), d_ver, str(d_vig), d_resp.strip(), d_not.strip(), str(hoy), especie),
                    )
                    conn.commit()
                    registrar_accion("GLOBALGAP DOC", d_tit.strip())
                    st.success("Documento registrado.")
                    st.rerun()
        df_doc = pd.read_sql_query(
            "SELECT tipo as TIPO, titulo as TITULO, version as VER, fecha_vigencia as VIGENTE, responsable as RESPONSABLE, notas as NOTAS FROM gap_documentos WHERE COALESCE(especie,'Cerezos')=? ORDER BY fecha_registro DESC",
            conn,
            params=(especie,),
        )
        st.dataframe(df_doc, use_container_width=True)
        pdf_globalgap(df_doc, "Documentos", especie, "documentos")

    elif sec_gap == _gap_secc[2]:
        filtro_cap = st.selectbox("Capítulo", ["TODOS"] + GAP_CAPITULOS)
        q_chk = f"""SELECT c.id, c.codigo, c.capitulo, c.descripcion, COALESCE(e.estado,'Pendiente') as estado, e.fecha_revision, e.responsable
                    FROM gap_checklist c
                    LEFT JOIN gap_evaluacion e ON c.id=e.checklist_id AND COALESCE(e.especie,'Cerezos')='{especie}'"""
        if filtro_cap != "TODOS":
            q_chk += f" WHERE c.capitulo='{filtro_cap}'"
        q_chk += " ORDER BY c.orden"
        df_chk = pd.read_sql_query(q_chk, conn)
        st.dataframe(df_chk, use_container_width=True)
        pdf_globalgap(df_chk, "Autoevaluación IFA", especie, "checklist", detalle=filtro_cap, estilo_celda_fn=_pdf_estilo_gap_checklist)
        with st.form("gap_eval_form"):
            sel = st.selectbox(
                "Ítem a evaluar",
                df_chk["codigo"].tolist() if not df_chk.empty else [],
            )
            estado = st.selectbox("Estado", ["Cumple", "No cumple", "N/A", "Pendiente"])
            evid = st.text_input("Evidencia / referencia")
            resp = st.text_input("Responsable revisión")
            if st.form_submit_button("GUARDAR EVALUACIÓN") and sel:
                chk_id = conn.execute("SELECT id FROM gap_checklist WHERE codigo=?", (sel,)).fetchone()[0]
                conn.execute("DELETE FROM gap_evaluacion WHERE checklist_id=? AND COALESCE(especie,'Cerezos')=?", (chk_id, especie))
                conn.execute(
                    "INSERT INTO gap_evaluacion (checklist_id, estado, evidencia, responsable, fecha_revision, usuario, especie) VALUES (?,?,?,?,?,?,?)",
                    (chk_id, estado, evid, resp, str(hoy), st.session_state.get("email", ""), especie),
                )
                conn.commit()
                st.success("Evaluación guardada.")
                st.rerun()

    elif sec_gap == _gap_secc[3]:
        with st.form("gap_nc_new", clear_on_submit=True):
            nc_cap = st.selectbox("Capítulo", GAP_CAPITULOS)
            nc_desc = st.text_area("Descripción hallazgo")
            nc_causa = st.text_input("Causa raíz")
            nc_ac = st.text_area("Acción correctiva")
            nc_plazo = st.date_input("Plazo cierre", hoy + timedelta(days=30))
            nc_cc = st.selectbox("Cuartel (opcional)", [""] + cuarteles_esp)
            if st.form_submit_button("ABRIR NC"):
                if nc_desc.strip():
                    n = conn.execute("SELECT COUNT(*) FROM gap_nc").fetchone()[0] + 1
                    cod = f"NC-{n:04d}"
                    conn.execute(
                        "INSERT INTO gap_nc (codigo, capitulo, descripcion, causa, accion_correctiva, plazo, cuartel, fecha_apertura, especie) VALUES (?,?,?,?,?,?,?,?,?)",
                        (cod, nc_cap, nc_desc.strip(), nc_causa.strip(), nc_ac.strip(), str(nc_plazo), nc_cc, str(hoy), especie),
                    )
                    conn.commit()
                    registrar_accion("GLOBALGAP NC", cod)
                    st.warning(f"No conformidad {cod} registrada.")
                    st.rerun()
        df_nc = pd.read_sql_query(
            f"SELECT codigo, capitulo, descripcion, accion_correctiva, plazo, estado, cuartel FROM gap_nc WHERE COALESCE(especie,'Cerezos')=? OR cuartel IN ({','.join('?' * len(cuarteles_esp))}) ORDER BY fecha_apertura DESC",
            conn,
            params=(especie, *cuarteles_esp),
        )
        st.dataframe(df_nc, use_container_width=True)
        pdf_globalgap(df_nc, "No conformidades", especie, "nc", estilo_celda_fn=_pdf_estilo_gap_nc)
        if not df_nc.empty:
            nc_cerrar = st.selectbox("Cerrar NC", df_nc[df_nc["estado"] == "Abierta"]["codigo"].tolist() if "Abierta" in df_nc["estado"].values else [])
            if nc_cerrar and st.button("MARCAR NC CERRADA"):
                conn.execute(
                    "UPDATE gap_nc SET estado='Cerrada', fecha_cierre=? WHERE codigo=?",
                    (str(hoy), nc_cerrar),
                )
                conn.commit()
                st.success(f"{nc_cerrar} cerrada.")
                st.rerun()

    elif sec_gap == _gap_secc[4]:
        pers = pd.read_sql_query("SELECT id, nombre FROM personal WHERE estado='Activo' ORDER BY nombre", conn)
        with st.form("gap_cap_new", clear_on_submit=True):
            tid = st.selectbox("Trabajador", pers["id"].tolist() if not pers.empty else []) if not pers.empty else None
            tema = st.selectbox("Tema", ["Fitosanitarios", "SST / Seguridad", "Higiene cosecha", "Primeros auxilios", "Otro"])
            horas = st.number_input("Horas", 0.5, 40.0, 2.0)
            inst = st.text_input("Instructor")
            f_cap = st.date_input("Fecha capacitación", hoy)
            vig = f_cap + timedelta(days=365)
            evid = st.text_input("Evidencia (lista asistencia, etc.)")
            if st.form_submit_button("REGISTRAR CAPACITACIÓN") and tid:
                conn.execute(
                    "INSERT INTO gap_capacitaciones (trabajador_id, tema, horas, instructor, fecha, vigencia_hasta, evidencia) VALUES (?,?,?,?,?,?,?)",
                    (int(tid), tema, horas, inst.strip(), str(f_cap), str(vig), evid.strip()),
                )
                conn.commit()
                registrar_accion("GLOBALGAP CAP", tema)
                st.success("Capacitación registrada.")
                st.rerun()
        df_cap = pd.read_sql_query(
            """SELECT p.nombre as TRABAJADOR, c.tema as TEMA, c.horas as HORAS, c.instructor as INSTRUCTOR,
                      c.fecha as FECHA, c.vigencia_hasta as VIGENCIA, c.evidencia as EVIDENCIA
               FROM gap_capacitaciones c JOIN personal p ON c.trabajador_id=p.id ORDER BY c.fecha DESC""",
            conn,
        )
        st.dataframe(df_cap, use_container_width=True)
        pdf_globalgap(df_cap, "Capacitaciones", especie, "capacitaciones", detalle="Campo", estilo_celda_fn=_pdf_estilo_cap_vencida)

    elif sec_gap == _gap_secc[5]:
        with st.form("gap_cos_new", clear_on_submit=True):
            n_lote = st.text_input("N° Lote cosecha", value=f"LOT-{especie[:3].upper()}-{hoy.strftime('%Y%m%d')}")
            cc = st.selectbox("Cuartel", cuarteles_esp)
            esp = especie
            var = st.text_input("Variedad")
            f_cos = st.date_input("Fecha cosecha", hoy)
            kg = st.number_input("Kg / bins estimados", 0.0)
            cuad = st.text_input("Cuadrilla")
            dest = st.text_input("Destino (packing, exportador)")
            apps = pd.read_sql_query(
                """SELECT n_aplicacion, fecha,
                          GROUP_CONCAT(producto, ' + ') as productos,
                          MAX(fecha_viable) as fecha_viable
                   FROM libro_campo WHERE sector=?
                   GROUP BY n_aplicacion, fecha
                   ORDER BY fecha DESC LIMIT 20""",
                conn,
                params=(cc.upper(),),
            )
            ult_app = st.selectbox(
                "Última aplicación fitosanitaria en cuartel",
                ["—"] + [
                    f"{int(r['n_aplicacion'])} | {r['fecha']} | {r['productos']}"
                    for _, r in apps.iterrows()
                ] if not apps.empty else ["—"],
            )
            fv = None
            ua_n = None
            if ult_app != "—":
                ua_n = int(ult_app.split(" | ")[0])
                fv_row = apps[apps["n_aplicacion"] == ua_n]
                if not fv_row.empty:
                    fv = fv_row.iloc[0]["fecha_viable"]
            if fv and f_cos < pd.to_datetime(fv).date():
                st.error(f"Cosecha antes de fecha viable ({fv}). GlobalGAP / PHI no cumplido.")
            if st.form_submit_button("REGISTRAR LOTE COSECHA"):
                if f_cos >= (pd.to_datetime(fv).date() if fv else f_cos):
                    conn.execute(
                        "INSERT INTO gap_cosecha (n_lote, cuartel, especie, variedad, fecha_cosecha, kg, cuadrilla, ultima_app_n, fecha_viable_cosecha, destino) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (n_lote.strip(), cc.upper(), esp.strip(), var.strip(), str(f_cos), kg, cuad.strip(), ua_n, str(fv) if fv else None, dest.strip()),
                    )
                    conn.commit()
                    registrar_accion("GLOBALGAP COSECHA", n_lote.strip())
                    st.success("Lote de cosecha registrado.")
                    st.rerun()
                else:
                    st.error("No se puede registrar: PHI no cumplido.")
        df_cos = pd.read_sql_query(
            "SELECT n_lote as LOTE, cuartel as CUARTEL, especie as ESPECIE, fecha_cosecha as FECHA, kg as KG, cuadrilla as CUADRILLA, ultima_app_n as [N° APP], fecha_viable_cosecha as [FECHA VIABLE], destino as DESTINO FROM gap_cosecha WHERE UPPER(especie)=? ORDER BY fecha_cosecha DESC",
            conn,
            params=(especie.upper(),),
        )
        st.dataframe(df_cos, use_container_width=True)
        pdf_globalgap(df_cos, "Cosecha y lotes", especie, "cosecha")

    elif sec_gap == _gap_secc[6]:
        with st.form("gap_agua_new", clear_on_submit=True):
            punto = st.text_input("Punto muestreo (pozo, canal, etc.)")
            lab = st.text_input("Laboratorio")
            f_m = st.date_input("Fecha muestra", hoy)
            ecoli = st.text_input("E. coli")
            colif = st.text_input("Coliformes")
            ph = st.number_input("pH", 0.0, 14.0, 7.0)
            ce = st.number_input("Conductividad (dS/m)", 0.0, 10.0, 0.5)
            conf = st.checkbox("Resultado conforme", value=True)
            acc = st.text_input("Acción si no conforme")
            if st.form_submit_button("REGISTRAR ANÁLISIS"):
                if punto.strip():
                    conn.execute(
                        "INSERT INTO gap_agua (punto_muestreo, laboratorio, fecha_muestra, e_coli, coliformes, ph, ce, conforme, accion) VALUES (?,?,?,?,?,?,?,?,?)",
                        (punto.strip(), lab.strip(), str(f_m), ecoli, colif, ph, ce, 1 if conf else 0, acc.strip()),
                    )
                    conn.commit()
                    registrar_accion("GLOBALGAP AGUA", punto.strip())
                    st.success("Análisis de agua registrado.")
                    st.rerun()
        df_agua = pd.read_sql_query(
            "SELECT punto_muestreo as PUNTO, laboratorio as LAB, fecha_muestra as FECHA, e_coli as [E.COLI], coliformes as COLIFORMES, ph as PH, ce as CE, conforme as CONFORME FROM gap_agua ORDER BY fecha_muestra DESC",
            conn,
        )
        st.dataframe(df_agua, use_container_width=True)
        pdf_globalgap(df_agua, "Análisis de agua", especie, "agua", detalle="Campo", estilo_celda_fn=_pdf_estilo_gap_agua)

    elif sec_gap == _gap_secc[7]:
        with st.form("gap_cal_new", clear_on_submit=True):
            eq = st.text_input("Equipo / Nebulizador ID")
            f_cal = st.date_input("Fecha calibración", hoy)
            pres = st.number_input("Presión (bar)", 0.0, 50.0, 15.0)
            lha = st.number_input("L/ha medido", 0.0, 5000.0, 800.0)
            desv = st.number_input("Desviación %", 0.0, 100.0, 5.0)
            tec = st.text_input("Técnico")
            prox = st.date_input("Próxima calibración", hoy + timedelta(days=180))
            notas = st.text_area("Notas")
            if st.form_submit_button("REGISTRAR CALIBRACIÓN"):
                if eq.strip():
                    conn.execute(
                        "INSERT INTO gap_calibracion (equipo, fecha, presion, l_ha_medido, desviacion_pct, tecnico, proxima_fecha, notas) VALUES (?,?,?,?,?,?,?,?)",
                        (eq.strip().upper(), str(f_cal), pres, lha, desv, tec.strip(), str(prox), notas.strip()),
                    )
                    conn.commit()
                    registrar_accion("GLOBALGAP CAL", eq.strip())
                    st.success("Calibración registrada.")
                    st.rerun()
        df_cal = pd.read_sql_query(
            "SELECT equipo as EQUIPO, fecha as FECHA, presion as PRESION, l_ha_medido as [L/HA], desviacion_pct as [% DESV], tecnico as TECNICO, proxima_fecha as [PROX. FECHA] FROM gap_calibracion ORDER BY fecha DESC",
            conn,
        )
        st.dataframe(df_cal, use_container_width=True)
        pdf_globalgap(df_cal, "Calibración equipos", especie, "calibracion", detalle="Campo")
        st.caption("También puede registrar calibración como evento en **Maquinaria → Calibración Nebulizador**.")

    elif sec_gap == _gap_secc[8]:
        panel_planificacion_gantt(conn, especie)

    conn.close()

def render_manual_viewer(html_body, height=680):
    doc = f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
    <style>
      body {{ font-family: 'DM Sans', 'Segoe UI', sans-serif; margin:0; padding:20px 24px;
             color:#1F2933; line-height:1.55; user-select:none; -webkit-user-select:none; }}
      h2 {{ color:#1B5E20; border-bottom:2px solid #E8F5E9; padding-bottom:6px; font-size:1.25rem; }}
      h3 {{ color:#2E7D32; font-size:1.05rem; }}
      table {{ width:100%; border-collapse:collapse; margin:12px 0; font-size:14px; }}
      th, td {{ border:1px solid #DDE5DF; padding:8px; text-align:left; }}
      th {{ background:#F3F6F4; }}
      ul {{ padding-left:1.2rem; }}
      hr {{ border:none; border-top:1px solid #DDE5DF; margin:20px 0; }}
      .footer {{ margin-top:24px; font-size:12px; color:#777; text-align:center; }}
    </style></head>
    <body oncontextmenu="return false" ondragstart="return false">{html_body}</body></html>"""
    components.html(
        f"<iframe srcdoc=\"{html_lib.escape(doc)}\" "
        f"style='width:100%;height:{height}px;border:1px solid #DDE5DF;border-radius:14px;background:white;' "
        f"sandbox='' title='Manual ERP La Concepción'></iframe>",
        height=height + 12,
    )

def modulo_manual():
    encabezado_modulo("Manual", "📖 MANUAL DE USUARIO")
    if es_certificacion():
        st.markdown(
            """<div style="background:#E0F2F1;border:1px solid #80CBC4;color:#004D40;
            padding:0.75rem 1rem;border-radius:10px;margin-bottom:1rem;font-weight:600;font-size:0.92rem;">
            Manual Certificación GlobalGAP — solo módulos asignados a su perfil. Solo visualización.</div>""",
            unsafe_allow_html=True,
        )
        guia = manual_contenido.GUIA_RAPIDA_CERT_HTML
        completo = manual_contenido.MANUAL_COMPLETO_CERT_HTML
    elif es_solo_lectura() or st.session_state.get("rol") == "lector":
        st.markdown(
            """<div style="background:#ECEFF1;border:1px solid #B0BEC5;color:#37474F;
            padding:0.75rem 1rem;border-radius:10px;margin-bottom:1rem;font-weight:600;font-size:0.92rem;">
            Manual Lector / Solo lectura — consulta sin registrar ni exportar PDF.</div>""",
            unsafe_allow_html=True,
        )
        guia = manual_contenido.GUIA_RAPIDA_LECTOR_HTML
        completo = manual_contenido.MANUAL_COMPLETO_LECTOR_HTML
    else:
        st.markdown(
            """<div style="background:#E8F5E9;border:1px solid #A5D6A7;color:#1B5E20;
            padding:0.75rem 1rem;border-radius:10px;margin-bottom:1rem;font-weight:600;font-size:0.92rem;">
            Documento de consulta — solo visualización dentro del sistema. No disponible para descarga.</div>""",
            unsafe_allow_html=True,
        )
        guia = manual_contenido.GUIA_RAPIDA_HTML
        completo = manual_contenido.MANUAL_COMPLETO_HTML
    _man_secc = ["Guía rápida (1 página)", "Manual completo"]
    sec_man = nav_seccion(_man_secc, "manual_nav", "Documento")
    if sec_man == _man_secc[0]:
        render_manual_viewer(guia, height=520)
    elif sec_man == _man_secc[1]:
        render_manual_viewer(completo, height=720)

def modulo_seguridad():
    if not es_admin():
        st.error("Solo administradores pueden acceder a Administración.")
        st.stop()
    encabezado_modulo("Administración", "⚙️ ADMINISTRACIÓN")
    conn = conectar_db()
    adm_secciones = [
        "📜 BITÁCORA",
        "👤 USUARIOS Y PERFILES",
        "🔐 MÓDULOS OPERADOR",
        "🏷️ FAMILIAS PRODUCTO",
        "🚜 MAESTRA MAQUINARIA",
        "🏢 MAESTRA PROVEEDORES",
        "💵 ENCARGADOS COMPRAS",
        "📊 PRORRATEO CC",
        "🍒 PPTO Y PRODUCCIÓN",
        "💰 INGRESOS FLUJO",
        "💾 RESPALDO DATOS",
    ]
    sec = nav_seccion(adm_secciones, "adm_sec_nav", "Sección de administración")
    if sec == adm_secciones[0]:
        c1, c2 = st.columns(2)
        fi, ff = c1.date_input("Desde", hoy-timedelta(days=7), key="s_d"), c2.date_input("Hasta", hoy, key="s_h")
        dfb = pd.read_sql_query(f"SELECT usuario, accion, detalle, fecha_hora FROM bitacora WHERE DATE(fecha_hora) BETWEEN '{fi}' AND '{ff}' ORDER BY id DESC", conn)
        st.dataframe(dfb, use_container_width=True)
        boton_pdf("PDF BITACORA", generar_pdf_blob(dfb, f"ADMINISTRACIÓN ({fi} a {ff})", incluir_precios=False), "administracion.pdf", key="s_pdf_f")
    elif sec == adm_secciones[1]:
        st.markdown("#### Usuarios del sistema")
        emails = _form_mail_tesoreria_usuarios(conn)
        st.caption(
            "Perfil **certificacion**: solo GlobalGAP, Libro de Campo y Bodega (PPPL). "
            "Perfil **lector**: consulta con menú acotado (asigne módulos en la pestaña correspondiente). "
            "La casilla **Solo lectura** aplica a cualquier perfil excepto administrador. "
            "Al crear un usuario se genera una clave automática enviada solo al correo del colaborador (sin copia al administrador)."
        )
        with st.form("seg_nuevo_usuario", clear_on_submit=True):
            nu = st.text_input("Email nuevo usuario")
            nr = st.selectbox("Perfil", ["operador", "lector", "certificacion", "admin"], key="seg_nuevo_rol")
            mail_teso_nuevo = st.checkbox("Mail respaldo Tesorería", key="seg_nuevo_mail_teso")
            solo_lect_nuevo = st.checkbox(
                "Solo lectura",
                value=st.session_state.get("seg_nuevo_rol", "operador") in ("lector",),
                disabled=st.session_state.get("seg_nuevo_rol", "operador") == "admin",
                key="seg_nuevo_solo_lect",
            )
            if st.form_submit_button("CREAR USUARIO"):
                if nu.strip():
                    try:
                        from erp_correo_html import generar_clave_invitacion

                        email_nuevo = nu.strip().lower()
                        clave_auto = generar_clave_invitacion()
                        admin_inv = st.session_state.get("email", "")
                        sl = 0
                        if nr != "admin" and (nr == "lector" or solo_lect_nuevo):
                            sl = 1
                        conn.execute(
                            "INSERT INTO usuarios (email, password, rol, mail_tesoreria, solo_lectura) VALUES (?,?,?,?,?)",
                            (email_nuevo, hash_password(clave_auto), nr, 1 if mail_teso_nuevo else 0, sl),
                        )
                        conn.commit()
                        registrar_accion("USUARIO NUEVO", f"{email_nuevo} ({nr})")
                        mail_ok = enviar_correo_invitacion_concepcion(
                            email_nuevo, clave_auto, nr, admin_inv,
                        )
                        msg = f"Usuario {email_nuevo} creado con perfil {nr} (acceso permanente)."
                        if mail_ok:
                            msg += " Invitación enviada por correo (clave automática, solo al colaborador)."
                        else:
                            msg += " Usuario creado; no se pudo enviar el correo (revise SMTP en secrets)."
                        st.success(msg)
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Ese email ya existe. Use otro o cambie el rol manualmente en la base.")
        if not emails:
            emails = []
        if emails:
            with st.form("seg_cambiar_rol"):
                ue = st.selectbox("Usuario existente", emails, key="seg_rol_user")
                nuevo_rol = st.selectbox("Nuevo perfil", ["operador", "lector", "certificacion", "admin"], key="seg_rol_chg")
                if st.form_submit_button("ACTUALIZAR PERFIL") and ue:
                    if nuevo_rol == "lector":
                        conn.execute(
                            "UPDATE usuarios SET rol=?, solo_lectura=1 WHERE email=?",
                            (nuevo_rol, ue),
                        )
                    elif nuevo_rol == "admin":
                        conn.execute(
                            "UPDATE usuarios SET rol=?, solo_lectura=0 WHERE email=?",
                            (nuevo_rol, ue),
                        )
                    else:
                        conn.execute("UPDATE usuarios SET rol=? WHERE email=?", (nuevo_rol, ue))
                    conn.commit()
                    registrar_accion("USUARIO ROL", f"{ue} → {nuevo_rol}")
                    st.success("Perfil actualizado.")
                    st.rerun()
            with st.form("seg_cambiar_clave", clear_on_submit=True):
                st.markdown("##### Cambiar contraseña")
                ue_pw = st.selectbox("Usuario", emails, key="seg_pw_user")
                nueva_clave = st.text_input("Nueva contraseña", type="password", key="seg_pw_new")
                nueva_clave2 = st.text_input("Confirmar contraseña", type="password", key="seg_pw_conf")
                if st.form_submit_button("ACTUALIZAR CONTRASEÑA") and ue_pw:
                    if not nueva_clave.strip():
                        st.error("Ingrese la nueva contraseña.")
                    elif nueva_clave != nueva_clave2:
                        st.error("Las contraseñas no coinciden.")
                    elif len(nueva_clave.strip()) < 4:
                        st.error("La contraseña debe tener al menos 4 caracteres.")
                    else:
                        conn.execute(
                            "UPDATE usuarios SET password=? WHERE email=?",
                            (hash_password(nueva_clave.strip()), ue_pw),
                        )
                        conn.commit()
                        registrar_accion("USUARIO CLAVE", ue_pw)
                        st.success(f"Contraseña actualizada para {ue_pw}.")
                        st.rerun()
            with st.form("seg_reenviar_invitacion", clear_on_submit=True):
                st.markdown("##### Reenviar invitación por correo")
                st.caption(
                    "Genera una clave nueva automáticamente, la guarda en el sistema y la envía solo por correo "
                    "(usted no la verá en pantalla)."
                )
                ue_re = st.selectbox("Usuario", emails, key="seg_reinv_user")
                if st.form_submit_button("REENVIAR INVITACIÓN") and ue_re:
                    admin_re = st.session_state.get("email", "")
                    mail_ok = reenviar_correo_invitacion_concepcion(ue_re, admin_re)
                    if mail_ok:
                        st.success(f"Invitación reenviada a **{ue_re}** (clave nueva solo en el correo).")
                    else:
                        st.error(f"No se pudo reenviar a **{ue_re}**. Revise bitácora → FALLO_SMTP.")
                    st.rerun()
            st.divider()
            st.markdown("##### Eliminar usuario")
            st.warning("Esta acción es permanente. No puede eliminar su propio usuario ni el último administrador.")
            with st.form("seg_eliminar_usuario"):
                ue_del = st.selectbox("Usuario a eliminar", emails, key="seg_del_user")
                confirm_del = st.checkbox("Confirmo eliminar este usuario de forma permanente", key="seg_del_confirm")
                if st.form_submit_button("ELIMINAR USUARIO"):
                    email_actual = st.session_state.get("email", "")
                    if not ue_del:
                        st.error("Seleccione un usuario.")
                    elif ue_del == email_actual:
                        st.error("No puede eliminar su propio usuario mientras está conectado.")
                    elif not confirm_del:
                        st.error("Debe marcar la casilla de confirmación.")
                    else:
                        rol_row = conn.execute("SELECT rol FROM usuarios WHERE email=?", (ue_del,)).fetchone()
                        n_admins = conn.execute("SELECT COUNT(*) FROM usuarios WHERE rol='admin'").fetchone()[0]
                        if rol_row and rol_row[0] == "admin" and n_admins <= 1:
                            st.error("No puede eliminar el único administrador del sistema.")
                        else:
                            conn.execute("DELETE FROM usuarios WHERE email=?", (ue_del,))
                            conn.commit()
                            registrar_accion("USUARIO ELIMINADO", ue_del)
                            st.success(f"Usuario {ue_del} eliminado.")
                            st.rerun()
    elif sec == adm_secciones[2]:
        st.markdown("#### Módulos visibles por operador / lector")
        st.caption(
            "Solo aplica a usuarios con perfil **operador** o **lector**. Si no asigna módulos (o deja todos marcados), "
            "verán el menú completo. El módulo **Manual** siempre queda disponible."
        )
        ops = pd.read_sql_query(
            "SELECT email, COALESCE(modulos, '') AS modulos FROM usuarios WHERE rol IN ('operador', 'lector') ORDER BY email",
            conn,
        )
        if ops.empty:
            st.info("No hay usuarios con perfil operador o lector. Cree uno en la pestaña Usuarios y perfiles.")
        else:
            ue_mod = st.selectbox("Operador", ops["email"].tolist(), key="seg_mod_user")
            mod_act = parse_modulos_usuario(
                ops.loc[ops["email"] == ue_mod, "modulos"].iloc[0]
            )
            mod_user_slug = _sync_checkboxes_modulos_operador(ue_mod, mod_act, MENU_COMPLETO)
            todos_los_modulos = [key for _, key in MENU_COMPLETO]
            with st.form("seg_modulos_operador"):
                st.markdown(f"**Módulos para** `{ue_mod}`")
                cols_mod = st.columns(3)
                seleccionados = []
                for i, (lbl, key) in enumerate(MENU_COMPLETO):
                    with cols_mod[i % 3]:
                        if st.checkbox(
                            lbl,
                            key=f"seg_chk_mod_{mod_user_slug}_{key}",
                        ):
                            seleccionados.append(key)
                if st.form_submit_button("GUARDAR MÓDULOS"):
                    if set(seleccionados) >= set(todos_los_modulos):
                        mod_txt = ""
                    else:
                        mod_txt = ",".join(seleccionados)
                    conn.execute("UPDATE usuarios SET modulos=? WHERE email=?", (mod_txt, ue_mod))
                    conn.commit()
                    registrar_accion("USUARIO MODULOS", f"{ue_mod}: {mod_txt or 'todos'}")
                    _invalidar_sync_modulos_operador()
                    st.success("Módulos actualizados. El operador verá el menú al volver a entrar o al recargar.")
                    st.rerun()
    elif sec == adm_secciones[3]:
        _admin_tab_familias_producto(conn)
    elif sec == adm_secciones[4]:
        render_admin_tab_maestra_maquinaria(conn, registrar_accion)
    elif sec == adm_secciones[5]:
        render_admin_tab_maestra_proveedores(conn, registrar_accion)
    elif sec == adm_secciones[6]:
        from erp_caja_chica import render_admin_encargados_compras
        render_admin_encargados_compras(conn, registrar_accion, hora_chile, es_solo_lectura)
    elif sec == adm_secciones[7]:
        st.markdown("#### Prorrateo de centros de costo (campo)")
        st.caption(
            "Porcentajes para **Cerezos Corte 1, Corte 2, Ciruelos, Nogales Aparición y Nogales Cruz del Sur**. "
            "Deben sumar **100 %**. Se aplican a gastos operacionales, salida petróleo, salida bodega, liquidación RRHH y costos. "
            "**El Espino** y **Otros** quedan fuera de este reparto (imputación directa 100 % al cuartel marcado). "
            "Los movimientos ya registrados no se recalculan."
        )
        if not (es_admin() or st.session_state.get("email") == "osvaldolira@laconcepcion.cl"):
            st.warning("Solo administradores pueden editar el prorrateo.")
        else:
            actual = cargar_prorrateo_cc_pct(conn)
            nuevos = {}
            cols_pr = st.columns(2)
            for i, cc in enumerate(CUARTELES_PRORRATEO):
                with cols_pr[i % 2]:
                    nuevos[cc] = st.number_input(
                        cc.title(),
                        min_value=0.0,
                        max_value=100.0,
                        value=float(actual.get(cc, PRORRATEO_CC_DEFAULT.get(cc, 0))),
                        step=0.01,
                        format="%.2f",
                        key=f"prorrateo_{cc}",
                    )
            suma = sum(nuevos.values())
            color_suma = "#2E7D32" if abs(suma - 100.0) < 0.05 else "#C62828"
            st.markdown(
                f"<div style='font-size:1.1rem;font-weight:600;color:{color_suma};'>Suma actual: {suma:.2f} %</div>",
                unsafe_allow_html=True,
            )
            with st.form("seg_prorrateo_cc"):
                clv_pr = st.text_input("Clave maestra para guardar", type="password", key="seg_pr_clv")
                if st.form_submit_button("💾 GUARDAR PRORRATEO"):
                    if clv_pr != CLAVE_MAESTRA:
                        st.error("Clave maestra incorrecta.")
                    elif abs(suma - 100.0) >= 0.05:
                        st.error(f"Los porcentajes deben sumar 100 % (suma actual: {suma:.2f} %).")
                    else:
                        for cc, pct in nuevos.items():
                            conn.execute(
                                "INSERT INTO prorrateo_cc (centro_costo, porcentaje) VALUES (?, ?) "
                                "ON CONFLICT(centro_costo) DO UPDATE SET porcentaje=excluded.porcentaje",
                                (cc, float(pct)),
                            )
                        conn.commit()
                        registrar_accion("PRORRATEO CC", ", ".join(f"{k}={v:.2f}%" for k, v in nuevos.items()))
                        st.success("Prorrateo actualizado. Aplica solo a movimientos nuevos.")
                        st.rerun()
    elif sec == adm_secciones[8]:
        _admin_tab_metas_costos(conn)
    elif sec == adm_secciones[9]:
        _admin_tab_ingresos_flujo(conn)
    elif sec == adm_secciones[10]:
        from erp_respaldo import render_admin_respaldo_datos
        render_admin_respaldo_datos(
            conn, NOMBRE_ERP, os.path.abspath(NOMBRE_DB), SECRETS_PATH,
        )
    conn.close()

def modulo_soporte():
    from erp_soporte import render_modulo_soporte
    conn = conectar_db()
    conf = _conf_smtp_prod()
    admin_mail = conf.get("receptor_admin", "osvaldolira@laconcepcion.cl") if conf else "osvaldolira@laconcepcion.cl"
    render_modulo_soporte(
        conn,
        NOMBRE_ERP,
        _enviar_correo_html,
        admin_mail,
        es_admin,
        registrar_accion,
        hora_chile,
        f_puntos,
        encabezado_modulo,
        solo_lectura=es_solo_lectura(),
    )
    conn.close()


def login_page():
    if "login_panel_abierto" not in st.session_state:
        st.session_state.login_panel_abierto = False
    inyectar_css()
    inyectar_css_login_pantalla()
    hero = """
        <h1>ERP AGRICOLA LA CONCEPCIÓN</h1>
        <p>Gestión integral para operaciones agrícolas</p>
        <span class="prod-badge">PRODUCCIÓN</span>
    """
    st.markdown(_login_fondo_html(hero, logo_img_html(380, "logo-login")), unsafe_allow_html=True)
    _, col_acc = st.columns([8, 1.5])
    with col_acc:
        btn_txt = "Cerrar" if st.session_state.login_panel_abierto else "Acceso"
        if st.button(btn_txt, key="login_toggle", type="primary", use_container_width=False):
            st.session_state.login_panel_abierto = not st.session_state.login_panel_abierto
            st.rerun()
        if st.session_state.login_panel_abierto:
            reiniciar_lectura_recordado(NOMBRE_DB)
            limpiar_login_usuario_corrupto()
            rec_email, rec_recordado = preparar_usuario_recordado(NOMBRE_DB)
            if _email_valido(rec_email):
                st.session_state["login_usuario"] = rec_email
            if rec_recordado:
                st.session_state["login_recordar"] = True
            with st.form("login"):
                e = st.text_input("Usuario", key="login_usuario")
                p = st.text_input("Clave", type="password", key="login_clave")
                recordar = st.checkbox("Recordar usuario", key="login_recordar")
                if st.form_submit_button("ACCEDER"):
                    email_login = str(st.session_state.get("login_usuario", e) or "").strip().lower()
                    clave_login = str(st.session_state.get("login_clave", p) or "").strip()
                    if not email_login or not clave_login:
                        st.error("Ingrese usuario y clave.")
                    else:
                        conn = conectar_db(); cursor = conn.cursor()
                        cursor.execute(
                            "SELECT email, COALESCE(rol,'operador'), COALESCE(solo_lectura,0) FROM usuarios WHERE lower(email)=lower(?) AND password=?",
                            (email_login, hash_password(clave_login)),
                        )
                        row_login = cursor.fetchone()
                        if row_login:
                            guardar_usuario_recordado(NOMBRE_DB, email_login, recordar)
                            if email_login != "osvaldolira@laconcepcion.cl":
                                with st.spinner("Despachando alerta de seguridad..."):
                                    enviar_correo_alerta(email_login, exitoso=True)
                                    import time
                                    time.sleep(1.5)
                            st.session_state['logged_in'] = True
                            st.session_state['email'] = row_login[0]
                            rol_login = row_login[1] if row_login[1] in ROLES_USUARIO else 'operador'
                            st.session_state['rol'] = rol_login
                            st.session_state['solo_lectura'] = bool(row_login[2]) or rol_login == 'lector'
                            st.session_state.login_panel_abierto = False
                            st.rerun()
                        else:
                            enviar_correo_alerta(email_login, exitoso=False)
                            st.error("Acceso Denegado")
            aplicar_usuario_recordado_en_formulario(NOMBRE_DB)

@st.cache_resource(show_spinner=False)
def _bootstrap_db():
    inicializar_db()
    return True


def _streamlit_runtime_active():
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx() is not None
    except Exception:
        return False


def run_streamlit_concepcion():
    _bootstrap_db()
    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False
    if not st.session_state["logged_in"]:
        login_page()
        return
    anclaje_sesion_definitivo()
    if "init" not in st.session_state:
        st.session_state["init"] = True
    sincronizar_perfil_sesion()
    inyectar_css()
    inyectar_modo_solo_lectura()
    if es_solo_lectura():
        _aplicar_bloqueo_solo_lectura_js()
    _inyectar_sidebar_movil_js()
    with st.sidebar:
        st.markdown(
            f"""
            <div class="brand-sidebar">
                <div class="brand-logo-wrap">{logo_img_html(170, "logo-sidebar")}</div>
                <p class="brand-title">ERP LA CONCEPCIÓN</p>
                <p class="brand-sub">Agrícola La Concepción</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        rol = st.session_state.get("rol", "operador")
        rol_txt = texto_perfil_sidebar(rol)
        st.markdown(f"👤 <span class='sidebar-user'>{st.session_state['email']}</span>", unsafe_allow_html=True)
        st.markdown(f"<span class='status-pill'>Perfil: {rol_txt}</span>", unsafe_allow_html=True)
        st.divider()
        m_opts = construir_menu_usuario(st.session_state.get("email", ""), rol)
        _conn_menu = conectar_db()
        try:
            from erp_soporte import aplicar_badge_menu_soporte
            from demo_web.services.sidebar_badges import aplicar_badges_labels_menu

            m_opts = aplicar_badge_menu_soporte(m_opts, _conn_menu, es_admin, es_solo_lectura())
            m_opts = aplicar_badges_labels_menu(m_opts, _conn_menu)
        except Exception:
            pass
        finally:
            _conn_menu.close()
        menu_choice = st.radio(
            "MENÚ", list(m_opts.keys()), key="menu_radio", on_change=_al_cambiar_menu_sidebar,
        )
        menu = m_opts[menu_choice]
        _marcar_cierre_sidebar_si_cambio_menu(menu_choice)

    if st.session_state.pop("_erp_cerrar_sidebar_movil", False):
        n = int(st.session_state.get("_erp_sidebar_collapse_n", 0)) + 1
        st.session_state["_erp_sidebar_collapse_n"] = n
        _colapsar_sidebar_movil_js(n)

    if st.button("\u200b", key="btn_logout", help="Cerrar sesión"):
        st.session_state.clear()
        st.rerun()

    if not puede_acceder_modulo(menu):
        st.error("No tiene permiso para acceder a este módulo.")
        st.stop()

    if menu == "DASHBOARD":
        modulo_dashboard()
    elif menu == "Petróleo":
        modulo_petroleo()
    elif menu == "Compras":
        modulo_compras()
    elif menu == "Tesoreria":
        modulo_tesoreria()
    elif menu == "Flujo financiero":
        modulo_flujo_financiero()
    elif menu == "RRHH":
        modulo_rrhh()
    elif menu == "Bodega":
        modulo_bodega()
    elif menu == "Espino":
        modulo_espino()
    elif menu == "Libro de Campo":
        modulo_libro_campo()
    elif menu == "GlobalGAP":
        modulo_globalgap()
    elif menu == "Maquinaria":
        modulo_maquinaria()
    elif menu == "Costos":
        modulo_costos()
    elif menu == "Soporte":
        modulo_soporte()
    elif menu == "Manual":
        modulo_manual()
    elif menu == "Administracion":
        modulo_seguridad()


if _streamlit_runtime_active():
    run_streamlit_concepcion()
