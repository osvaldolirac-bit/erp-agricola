# ERP Constructora

Producto separado de Comercial (Río Maipo).

- Path VPS: `/root/constructora`
- URL: `https://erpmaster.cl/constructora/`
- Servicio: `erp-constructora` → `:8509`
- Tenant: `constructora-demo` (DEMO Constructora)
- Nginx: `location /constructora/` → `proxy_pass ...8509/` (quita el prefijo) + `X-Forwarded-Prefix /constructora`
- Rutas Flask (sin prefijo interno; el prefijo lo pone SCRIPT_NAME):
  - `/obras/`, `/obra` (alias), `/precios/`, `/apu/`, `/hub/`, `/cotizaciones-obra/`
  - Público: `/constructora/obras/`, etc.
- Consola Master: producto `constructora` (kind=`comercial` para handlers de admin)
- Comercial: sin módulo Constructora
- Menú Obras: Obras / Precios (PMP) / APU
