# ERP Constructora

Producto separado de Comercial (Río Maipo).

- Path VPS: `/root/constructora`
- URL: `https://erpmaster.cl/constructora/`
- Servicio: `erp-constructora` → `:8509`
- Tenant: `constructora-demo` (DEMO Constructora)
- Consola Master (`/consola/`):
  - Producto `constructora` (kind=`comercial` para reutilizar handlers de admin)
  - Selector de cliente con optgroup **Constructora**
  - Respaldo etiqueta rubro **Constructora** (código owner: `constructora-demo`)
  - Archivos UI: `erp_master/erp_master/templates/super_consola.html`, `home.html`, `static/master.css`
- Comercial: sin módulo Constructora
- Menú Obras: Obras / Precios (PMP) / APU
