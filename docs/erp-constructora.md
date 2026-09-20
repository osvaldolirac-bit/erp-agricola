# ERP Constructora

Producto separado de Comercial (Río Maipo).

- Path VPS: `/root/constructora`
- URL: `https://erpmaster.cl/constructora/`
- Servicio: `erp-constructora` → `:8509`
- Tenant: `constructora-demo`
- Inicio (`/`): hero con edificio en construcción (`bg_home_constructora.png`); menú **Inicio**
- Login: mismo fondo de obra; título Acceso · Constructora
- Rutas (nginx quita `/constructora`): `/obras/`, `/obra`, `/precios/`, `/apu/`, `/hub/`
- Consola Master: producto `constructora`
