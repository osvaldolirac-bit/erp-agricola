# Contrato de obra (Constructora)

Flujo por obra (`/obras/<id>?sec=...`):

1. **Cotización de obra** — partidas del requerimiento.
2. **APU** — valoriza partidas con precios editables (foto). El PMP de bodega es solo referencia.
3. **Aprobar** — congela APU/partidas y fija el presupuesto de cotización.
4. **Gantt** — avance físico % por partida (tras aprobar).
5. **EEPP** — avance en CLP = % × total congelado de la partida; se emite desde el Gantt.

Las cotizaciones globales siguen para presupuestos simples. El APU no se sincroniza desde bodega.
