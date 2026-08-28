GUIA_RAPIDA_HTML = """
<h2>Guía rápida — ERP Agrícola</h2>
<p><b>Acceso (producción y demo):</b> <a href="https://erpmaster.cl/agricola/" target="_blank" rel="noopener">https://erpmaster.cl/agricola/</a> — elija el ERP (La Concepción o DEMO) en la pantalla de acceso.</p>
<p>En la pantalla de acceso puede marcar <b>Recordar usuario</b> para precargar su correo la próxima vez (la clave siempre debe ingresarse).</p>
<table>
<tr><th>Quiero...</th><th>Ir a...</th></tr>
<tr><td>Ver resumen general</td><td>Dashboard</td></tr>
<tr><td>Comprar insumo / agroquímico (bodega)</td><td>Compras → INGRESO → casilla Agroquímicos</td></tr>
<tr><td>Registrar gasto operacional a cuarteles</td><td>Compras → INGRESO → Gastos operacionales (tipo de gasto + cuarteles)</td></tr>
<tr><td>Registrar factura de petróleo</td><td>Compras → INGRESO → casilla Compra de petróleo</td></tr>
<tr><td>Imprimir planilla física del estanque</td><td>Petróleo → Planilla maestra</td></tr>
<tr><td>Registrar salida de petróleo en terreno (link)</td><td>Petróleo → Salida Link (enlace personal WhatsApp) · Admin autoriza</td></tr>
<tr><td>Autorizar salidas pendientes del link</td><td>Petróleo → Salida Link (contador en el menú)</td></tr>
<tr><td>Registrar riego y fertilización</td><td>Riego → Registro manual o Link riego (admin autoriza)</td></tr>
<tr><td>Ver balance NPK aplicado (kg/ha)</td><td>Riego → Historial</td></tr>
<tr><td>Despachar insumo a cuartel</td><td>Bodega → Salida</td></tr>
<tr><td>Pagar proveedor</td><td>Tesorería → Deuda por proveedor</td></tr>
<tr><td>Registrar sueldos del mes</td><td>RRHH → Liquidación mensual</td></tr>
<tr><td>Registrar servicio de contratista</td><td>RRHH → Contratistas → Registrar servicio</td></tr>
<tr><td>Ver deuda / pagos de un contratista</td><td>RRHH → Contratistas → Cuenta corriente</td></tr>
<tr><td>Autorizar personal para Salida Link</td><td>RRHH → Personal (casilla autorizado petróleo)</td></tr>
<tr><td>Registrar aplicación fitosanitaria</td><td>Libro de Campo</td></tr>
<tr><td>Gestionar certificación GlobalGAP</td><td>GlobalGAP</td></tr>
<tr><td>Ver costos por rubro y cuartel</td><td>Costos → Temporada → Resumen</td></tr>
<tr><td>Detalle de un cuartel</td><td>Costos → Temporada → subpestaña del cuartel</td></tr>
<tr><td>Ver planes y cupos de usuarios (demo)</td><td>Planes</td></tr>
<tr><td>Cargar presupuesto o kg estimados</td><td>Administración → Ppto y producción (administrador)</td></tr>
<tr><td>Gestionar usuarios y permisos</td><td>Administración → Usuarios y perfiles (solo administrador)</td></tr>
<tr><td>Reportar un problema del sistema</td><td>Soporte → Nuevo ticket</td></tr>
<tr><td>Consultar este manual</td><td>Manual</td></tr>
</table>
<h3>Reglas clave</h3>
<ul>
<li>Producto <b>nuevo con factura</b> → Compras → INGRESO → Agroquímicos, nunca Bodega stock inicial.</li>
<li><b>Compra de petróleo</b> → casilla dedicada en Compras → INGRESO (carga el estanque al guardar; no hay pestaña Carga aparte).</li>
<li><b>Salida Link</b> registra en terreno y queda <b>pendiente</b> hasta autorización; al autorizar se imputa al estanque y a <b>Costos</b> (revise allí el detalle por cuartel).</li>
<li><b>Riego Link</b> mismo esquema: pendiente → autorizar → historial e imputación a CC (con fertilizante opcional desde bodega).</li>
<li>Los <b>gastos operacionales</b> deben tener <b>tipo de gasto</b> para clasificarse en la matriz de Costos.</li>
<li>Tras guardar un gasto en Compras, el formulario se limpia para ingresar otro.</li>
<li><b>Libro de Campo</b> solo acepta productos autorizados en PPPL GlobalGAP.</li>
<li>Los botones <b>PDF</b> exportan reportes del módulo; este manual es <b>solo lectura</b>.</li>
<li>Perfil <b>lector</b> o casilla <b>Solo lectura</b>: puede consultar módulos asignados, pero no guardar ni exportar PDF.</li>
</ul>
"""

MANUAL_COMPLETO_HTML = """
<h2>1. Acceso, perfiles y permisos</h2>
<p>Menú lateral con los módulos según su <b>perfil</b> y, si corresponde, los módulos asignados por el administrador. Cada sección tiene color propio, botones PDF y formularios con colores semánticos (verde guardar, rojo eliminar, azul editar).</p>
<p><b>URL única del rubro:</b> <a href="https://erpmaster.cl/agricola/" target="_blank" rel="noopener">erpmaster.cl/agricola/</a>. Las rutas antiguas <code>/laconcepcion</code> y <code>/demo</code> redirigen aquí.</p>
<p>En la pantalla de acceso, el botón <b>Acceso</b> abre el formulario de usuario y clave. La casilla <b>Recordar usuario</b> guarda solo el correo en el equipo; la clave debe digitarse en cada ingreso.</p>

<h3>1.1 Producción — La Concepción</h3>
<table>
<tr><th>Perfil</th><th>Qué puede hacer</th></tr>
<tr><td><b>Administrador</b></td><td>Acceso total: todos los módulos, Administración, corrección/eliminación de datos, ajustes en Costos, gestión de usuarios. Autoriza Salida Link (petróleo y riego).</td></tr>
<tr><td><b>Operador</b></td><td>Módulos operativos asignados en Administración → Módulos operador. Registra compras, bodega, RRHH, etc., según lo habilitado.</td></tr>
<tr><td><b>Certificación GlobalGAP</b></td><td>Solo GlobalGAP, Libro de Campo, Bodega (PPPL y consulta), Soporte y Manual. Manual dedicado a su perfil.</td></tr>
<tr><td><b>Lector</b></td><td>Consulta con menú acotado (módulos asignados). <b>Sin</b> guardar cambios ni exportar PDF. Manual dedicado a su perfil.</td></tr>
<tr><td><b>Solo lectura</b> (casilla)</td><td>Puede aplicarse a operador u otros perfiles (excepto administrador): misma restricción que lector en formularios y PDF.</td></tr>
</table>
<p>El administrador crea usuarios en <b>Administración → Usuarios y perfiles</b> (o en la <b>Consola Master</b> de plataforma para tenants LC/DEMO), define perfil, casilla solo lectura y correos de alerta (tesorería, petróleo, riego). Los perfiles <b>operador</b> y <b>lector</b> requieren asignación de módulos en <b>Módulos operador</b>.</p>

<h3>1.2 Cupos de usuarios (planes)</h3>
<ul>
<li><b>Por módulo · Pack Campo · Pack Patio · Pack Oficina:</b> 1 Administrador + 1 asiento (Operador o Lector). Usuario adicional: $3.900/mes.</li>
<li><b>Pack Agrícola</b> (completo): 1 Administrador + 3 asientos. Usuario adicional: $1.990/mes.</li>
<li>El Administrador configura el acceso y módulos de cada asiento.</li>
<li>En DEMO, el detalle de packs y precios está en el menú <b>Planes</b>.</li>
</ul>

<h3>1.3 Entorno demo — ERP Master</h3>
<p>La demo replica la operación con datos ficticios. Los perfiles están <b>separados por capas</b> para simular la entrega a un cliente real:</p>
<table>
<tr><th>Perfil demo</th><th>Alcance</th></tr>
<tr><td><b>Super administrador</b> (plataforma ERP Master)</td><td>Todo el menú + Administración completa: Bitácora, Usuarios, Respaldo, Plataforma demo y maestras. Solo cuentas de plataforma.</td></tr>
<tr><td><b>Administrador de campo</b></td><td>Menú operativo + Administración parcial: Módulos operador, Familias, Maestras (maquinaria/proveedores), Ppto y producción. <b>No</b> ve Bitácora, Usuarios ni Respaldo (se habilitan en la inducción del cliente real).</td></tr>
<tr><td><b>Operación</b></td><td>Módulos asignados; usuarios de prueba con vigencia limitada (30 días).</td></tr>
<tr><td><b>Certificación GlobalGAP</b></td><td>Igual que en producción: GlobalGAP, Libro de Campo, Bodega (PPPL), Soporte y Manual.</td></tr>
</table>
<p>En demo <b>no existe</b> perfil lector ni modo solo lectura: la exportación PDF está habilitada para facilitar la prueba del sistema.</p>
<hr>

<h2>2. Módulos operativos</h2>
<h3>Dashboard</h3>
<p>Vista general: indicadores UF/UTM/dólar, deuda pendiente, facturas vencidas, saldo petróleo, gastos por cuartel y proyección de pagos.</p>

<h3>Petróleo</h3>
<ul>
<li><b>Saldo en tanque</b> — banner superior; cargas y despachos acumulados en el resumen.</li>
<li><b>Widget resumen</b> (parte superior derecha): tres donas en columnas —
  (1) litros despachados por <b>maquinaria</b> en la <b>temporada</b>,
  (2) litros por maquinaria en el <b>mes en curso</b>,
  (3) <b>gasto neto por centro de costo</b> en la temporada (PMP imputado). Cada columna muestra leyenda y total.</li>
<li><b>Compra / carga al estanque:</b> solo vía <b>Compras → INGRESO → Compra de petróleo</b> (litros + monto). No use gasto operacional con cuarteles para combustible.</li>
<li><b>Salida manual:</b> excepciones en el ERP (preferir Salida Link).</li>
<li><b>Salida Link:</b> formulario móvil con enlace personal (WhatsApp). Registra litros, cuartel del link y maquinaria. Queda <b>pendiente</b>.</li>
<li><b>Autorización (admin):</b> Petróleo → Salida Link → AUTORIZAR o RECHAZAR. Al autorizar: salida real en historial, descuento de estanque (PMP) e imputación a Costos (un cuartel o prorrateo si el link es Administración). En la bitácora se ve el detalle <b>Imputado a:</b> por CC; no hay enlace — consulte <b>Costos</b> directamente.</li>
<li><b>Contador en el menú:</b> pendientes por autorizar en el ítem Petróleo.</li>
<li><b>Historial</b> — movimientos del estanque y PDF.</li>
<li><b>Planilla maestra</b> — PDF para anotar salidas físicas; luego Salida Link o Salida manual.</li>
</ul>
<p><b>Personal autorizado al link:</b> RRHH → Personal → casilla salida petróleo. Enlaces personales en Petróleo → Salida Link (admin).</p>

<h3>Riego</h3>
<ul>
<li><b>Historial</b> — registros autorizados (manual + link). Tabla superior <b>NPK aplicado (kg/ha por CC)</b>: acumula N, P₂O₅ y K₂O del fertirriego dividido por la <b>superficie (ha)</b> del <b>Prorrateo CC</b> (Consola Master). Interpreta cada fertilizante por nombre de bodega (sin renombrar productos).</li>
<li><b>Registro manual</b> — fecha, huerto (CC), horas, m³ (auto según huerto: tecnificado o por surco), regador, fertilización opcional desde bodega (familia FERTILIZANTE).</li>
<li><b>Link riego</b> — enlaces personales para regadores; pendiente hasta que admin autorice (descuenta bodega si lleva fertilizante).</li>
<li><b>Modos de riego:</b> <b>Tecnificado</b> (m³/h·ha × ha prorrateo × horas) o <b>Por surco</b> (40 m³/h·ha × ha × horas) según huerto.</li>
<li><b>Fertilización:</b> al guardar, el sistema identifica el análisis NPK del producto y lo deja registrado en la línea del riego. Productos no reconocidos aparecen avisados en Historial para ampliar el catálogo del módulo.</li>
<li><b>Metas NPK/ha</b> — previstas para una versión futura (hoy solo muestra lo aplicado).</li>
</ul>
<p><b>Regadores autorizados:</b> RRHH → Personal (casilla registro riego) o extras en el módulo. Parámetros m³/h·ha y superficie: Consola Master → Prorrateo CC.</p>

<h3>Compras</h3>
<p>Dos pestañas: <b>INGRESO</b> e <b>HISTORIAL</b>.</p>
<h4>INGRESO — tres modos (casillas mutuamente excluyentes)</h4>
<ul>
<li><b>Agroquímicos (ingreso a bodega):</b> carro de productos existentes o nuevos → stock y PMP. El costo a cuarteles se imputa al sacar de bodega.</li>
<li><b>Compra de petróleo:</b> factura de combustible sin cuarteles ni tipo de gasto (demo: incluye litros y carga el estanque al guardar).</li>
<li><b>Gastos operacionales</b> (sin casillas anteriores): imputación a uno o más cuarteles, con <b>tipo de gasto</b> para la matriz de Costos, monto bruto e indicador IVA (Imputar bruto SI/NO).</li>
</ul>
<p>Campos comunes: proveedor, N° documento (o folio interno autogenerado), razón social, fechas. Tras guardar exitosamente, el formulario se reinicia para ingresar otro movimiento.</p>
<h4>HISTORIAL</h4>
<p>Búsqueda por texto y rango de fechas. Columna <b>TIPO GASTO CC</b> muestra la clasificación para Costos. El administrador puede <b>Corregir / eliminar</b> facturas desde el panel al final del historial.</p>

<h3>Tesorería</h3>
<p>Deudas pendientes, deuda por proveedor, historial de pagos. Marcar pagado con método (transferencia, efectivo, cheque). PDF de pendientes con tipografía legible.</p>
<p>Al registrar un pago, el sistema envía un correo de respaldo al equipo de tesorería indicando el <b>sistema ERP</b> de origen (producción o demo), proveedor, documentos y monto.</p>

<h3>Bodega</h3>
<ul>
<li><b>Stock actual</b> — inventario y corrección (solo administrador)</li>
<li><b>Salida</b> — despacho a cuarteles (imputa costo como Agroquímicos en matriz CC)</li>
<li><b>PPPL</b> — marcar productos autorizados GlobalGAP y días de carencia (PHI)</li>
<li><b>Stock inicial</b> — solo apertura de inventario preexistente</li>
<li><b>Consulta cuartel</b> — movimientos por centro de costo</li>
</ul>
<p>Perfil certificación: solo ve <b>PPPL</b> y <b>Stock consulta</b>.</p>

<h3>RRHH</h3>
<ul>
<li><b>Personal</b> — alta y edición de trabajadores; casilla <b>autorizado salida petróleo</b> para Salida Link</li>
<li><b>Contratistas</b> — maestro, registro de servicios, consulta por centro de costo y <b>Cuenta corriente</b> (trabajos vs pagos con saldo acumulado)</li>
<li><b>Remuneraciones</b> — sueldos, préstamos, cuotas, provisión</li>
<li><b>Liquidación mensual</b> — registro por mes (alimenta RRHH de la casa en Costos)</li>
<li><b>Historial pagos</b></li>
</ul>

<h3>El Espino</h3>
<p>Registro y seguimiento de gastos del módulo El Espino. Historial filtrable por fechas y exportación PDF.</p>

<h3>Libro de Campo</h3>
<p>Registro fitosanitario obligatorio para certificación y operación diaria.</p>
<ul>
<li>Cuartel, especie, producto, ingrediente activo, dosis, volumen de agua</li>
<li><b>Lote del producto</b> — trazabilidad GlobalGAP</li>
<li><b>Operador certificado</b> — checkbox de cumplimiento</li>
<li><b>PHI / fecha viable</b> — calculada según días de carencia del PPPL</li>
<li>El sistema <b>bloquea</b> productos que no estén en PPPL</li>
</ul>

<h3>Maquinaria</h3>
<p>Bitácora de mantenciones con código único (MANT-00001). Incluye evento <b>Calibración Nebulizador</b> para auditoría GlobalGAP. El menú muestra a la derecha el contador de casos abiertos.</p>

<h3>Costos</h3>
<p>Consolidado por cuartel y <b>rubro de costo</b>, organizado por <b>temporada agrícola</b> (1 de mayo al 30 de abril).</p>
<h4>Pestañas de temporada</h4>
<ul>
<li><b>2026-2027</b>, <b>2027-2028</b> y <b>2028-2029</b></li>
<li>Filtra movimientos de bodega, facturas imputadas, petróleo, ajustes y RRHH del periodo</li>
</ul>
<h4>Subpestaña Resumen</h4>
<p>Matriz de rubros × cuarteles con filas de cierre: rubros ordenados por gasto, columna % Total, TOTAL GASTO, PRESUPUESTO y SALDO por cuartel. Botón PDF de la matriz.</p>
<h4>Subpestaña por cuartel</h4>
<p>Producción estimada, costo USD/kg, desglose por rubro, avance vs presupuesto y detalle de imputados con filtros.</p>
<p>El RRHH se prorratea entre cuarteles según porcentajes en <b>Administración → Prorrateo CC</b> (producción). En demo los porcentajes vienen preconfigurados en el entorno de prueba.</p>
<p><b>Administrador:</b> panel de corrección de duplicados, ajustes manuales y eliminación de imputaciones erróneas.</p>

<h3>Soporte</h3>
<p>Módulo para reportar problemas del sistema. Nuevo ticket, seguimiento de estado y correo automático al administrador. El menú muestra contador de tickets abiertos (administrador).</p>

<h3>Administración</h3>
<h4>Producción — administrador</h4>
<ul>
<li><b>Bitácora</b> — registro de acciones de usuarios</li>
<li><b>Usuarios y perfiles</b> — altas, claves, roles (admin, operador, certificación, lector) y casilla solo lectura</li>
<li><b>Módulos operador</b> — qué menú ve cada operador o lector</li>
<li><b>Familias producto</b>, <b>Maestra maquinaria</b>, <b>Maestra proveedores</b></li>
<li><b>Prorrateo CC</b> — % de RRHH de la casa por cuartel y <b>superficie (ha)</b> por CC (usada en Riego para m³ y balance NPK/ha)</li>
<li><b>Ppto y producción</b> — presupuesto ($) y kg estimados por cuartel y temporada</li>
<li><b>Respaldo datos</b> — envío programado de copia de la base de datos por correo</li>
</ul>
<h4>Demo — separación de poderes</h4>
<ul>
<li><b>Super administrador:</b> todo lo anterior en el entorno demo + pestaña <b>Plataforma demo</b> (re-seed, mantenimiento, usuarios permanentes).</li>
<li><b>Administrador de campo:</b> maestras, presupuesto y módulos operador únicamente. Bitácora, usuarios y respaldo quedan reservados a la plataforma / inducción del cliente.</li>
<li>Usuarios invitados en demo tienen <b>30 días</b> de vigencia; el super administrador gestiona cuentas permanentes.</li>
</ul>
<hr>

<h2>3. Certificación GlobalGAP</h2>
<p>Módulo central para preparar y mantener la certificación IFA (cerezas, ciruelas y demás frutales del campo).</p>
<h3>Dashboard GlobalGAP</h3>
<p>Muestra % cumplimiento del checklist, ítems cumpliendo, NC abiertas, productos PPPL y alertas (capacitaciones vencidas, análisis de agua).</p>
<h3>PPPL, Documentos, Autoevaluación, NC/AC, Capacitaciones, Cosecha/Lotes, Agua, Calibración</h3>
<p>Ver manual de perfil Certificación para el detalle operativo de cada pestaña.</p>
<hr>

<h2>4. Conceptos clave</h2>
<table>
<tr><th>Concepto</th><th>Significado</th></tr>
<tr><td>Cuartel</td><td>Sector del campo (centro de costo)</td></tr>
<tr><td>Temporada agrícola</td><td>Periodo de costos del 1 de mayo al 30 de abril (ej. 2026-2027)</td></tr>
<tr><td>Tipo de gasto</td><td>Clasificación en Compras que define el rubro en la matriz de Costos</td></tr>
<tr><td>PPPL / PHI</td><td>Lista fitosanitaria autorizada / plazo de carencia hasta cosecha</td></tr>
<tr><td>Cuenta corriente contratista</td><td>Libro mayor de trabajos (debe) y pagos (haber) con saldo</td></tr>
<tr><td>Planilla maestra petróleo</td><td>Formato impreso para anotar salidas físicas del estanque</td></tr>
<tr><td>Salida Link</td><td>Registro móvil de retiro de combustible; requiere autorización del administrador; imputación visible en Costos</td></tr>
<tr><td>Balance NPK riego</td><td>kg de N, P₂O₅ y K₂O aplicados por fertirriego, expresados por hectárea (prorrateo CC)</td></tr>
<tr><td>Consola Master</td><td>Panel web de plataforma (8507) para usuarios, módulos, prorrateo y respaldos por tenant LC/DEMO</td></tr>
<tr><td>Asiento</td><td>Usuario Operador o Lector incluido en el plan (además del Administrador)</td></tr>
</table>
<hr>

<h2>5. Flujos recomendados</h2>
<p><b>Certificación — inicio de temporada:</b> GlobalGAP → PPPL → Documentos → Autoevaluación</p>
<p><b>Aplicación fitosanitaria:</b> Verificar PPPL → Libro de Campo → registrar con lote y operador certificado</p>
<p><b>Compra insumo:</b> Compras → INGRESO → Agroquímicos → autorizar en PPPL si es fitosanitario</p>
<p><b>Compra petróleo:</b> Compras → casilla petróleo (carga estanque) → salidas Salida Link o Salida manual → Admin autoriza link → revisar Costos</p>
<p><b>Salida Link en terreno:</b> Enlace personal → litros, cuartel link, maquinaria → Admin autoriza en Petróleo → Salida Link → ver imputación en bitácora y detalle en Costos</p>
<p><b>Riego con fertilizante:</b> Bodega con productos FERTILIZANTE → Riego manual o Link → autorizar si es link → Historial (m³ + NPK kg/ha por CC)</p>
<p><b>Contratista:</b> RRHH → Registrar servicio → pagos en Tesorería / RRHH → revisar Cuenta corriente</p>
<p><b>Fin de mes:</b> RRHH → Liquidación mensual</p>
<p><b>Problema del sistema:</b> Soporte → Nuevo ticket</p>
<hr>

<h2>6. Soporte rápido</h2>
<table>
<tr><th>Problema</th><th>Qué hacer</th></tr>
<tr><td>Página no carga</td><td>Refrescar F5 (Cmd+Shift+R en Mac)</td></tr>
<tr><td>Producto rechazado en Libro de Campo</td><td>Agregar a GlobalGAP → PPPL o Bodega → PPPL</td></tr>
<tr><td>No puedo exportar PDF</td><td>Revise si tiene perfil lector o solo lectura; solicite cambio al administrador</td></tr>
<tr><td>No veo Administración / Usuarios</td><td>En demo solo super administrador; en producción solo perfil administrador</td></tr>
<tr><td>Salida Link no imputa al estanque</td><td>Debe estar <b>Autorizada</b> por un administrador en Petróleo → Salida Link</td></tr>
<tr><td>NPK en cero en Riego</td><td>Producto sin mapeo: avisar para catálogo del módulo; micronutrientes no aportan N/P/K</td></tr>
<tr><td>m³ riego incorrecto</td><td>Revise superficie (ha) en Consola Master → Prorrateo CC</td></tr>
<tr><td>No aparece mi enlace de petróleo</td><td>RRHH → Personal: marcar autorizado salida petróleo</td></tr>
<tr><td>Costos sin presupuesto</td><td>Administración → Ppto y producción</td></tr>
<tr><td>Error o falla del ERP</td><td>Soporte → Nuevo ticket</td></tr>
</table>
<p class="footer"><i>ERP Agrícola — Manual de usuario v1.6</i></p>
"""

GUIA_RAPIDA_CERT_HTML = """
<h2>Guía rápida — Perfil Certificación GlobalGAP</h2>
<p><b>Acceso:</b> <a href="https://erpmaster.cl/agricola/" target="_blank" rel="noopener">https://erpmaster.cl/agricola/</a></p>
<p>Su perfil tiene acceso solo a los módulos de certificación y soporte. El menú lateral muestra únicamente esas opciones.</p>
<table>
<tr><th>Quiero...</th><th>Ir a...</th></tr>
<tr><td>Gestionar certificación GlobalGAP</td><td>GlobalGAP</td></tr>
<tr><td>Autorizar producto fitosanitario (PPPL)</td><td>GlobalGAP → PPPL o Bodega → PPPL</td></tr>
<tr><td>Registrar aplicación fitosanitaria</td><td>Libro de Campo</td></tr>
<tr><td>Consultar stock de insumos</td><td>Bodega → Stock consulta</td></tr>
<tr><td>Registrar cosecha con trazabilidad</td><td>GlobalGAP → Cosecha / Lotes</td></tr>
<tr><td>Cerrar una no conformidad</td><td>GlobalGAP → NC / AC</td></tr>
<tr><td>Registrar capacitación de trabajador</td><td>GlobalGAP → Capacitaciones</td></tr>
<tr><td>Reportar un problema del sistema</td><td>Soporte → Nuevo ticket</td></tr>
<tr><td>Consultar este manual</td><td>Manual</td></tr>
</table>
<h3>Reglas clave</h3>
<ul>
<li><b>Libro de Campo</b> solo acepta productos autorizados en PPPL.</li>
<li>Antes de cosechar, verificar <b>PHI</b> (fecha viable) en Libro de Campo o GlobalGAP → Cosecha.</li>
<li>Mantener sincronizado PPPL entre <b>GlobalGAP</b> y <b>Bodega</b>.</li>
<li>No tiene acceso a Compras, Tesorería, Costos ni Administración.</li>
<li>Este manual es <b>solo lectura</b> y describe únicamente sus módulos asignados.</li>
</ul>
"""

MANUAL_COMPLETO_CERT_HTML = """
<h2>1. Su perfil de acceso</h2>
<p>Como encargada de <b>Certificación GlobalGAP</b>, el sistema le muestra estos módulos:</p>
<ul>
<li><b>GlobalGAP</b> — gestión integral de la certificación</li>
<li><b>Libro de Campo</b> — registro fitosanitario</li>
<li><b>Bodega</b> — PPPL y consulta de stock (sin salidas ni stock inicial)</li>
<li><b>Soporte</b> — reportar problemas del sistema al administrador</li>
<li><b>Manual</b> — esta guía</li>
</ul>
<p>No tiene acceso a módulos financieros (Compras, Tesorería, Costos), RRHH operativo ni Administración. Si necesita otro módulo, solicítelo al administrador del sistema.</p>
<p>En la pantalla de acceso puede marcar <b>Recordar usuario</b> para precargar su correo (la clave siempre debe ingresarse).</p>
<hr>
<h2>2. GlobalGAP</h2>
<p>Módulo central para preparar y mantener la certificación IFA (cerezas, ciruelas y frutales del campo).</p>
<h3>Dashboard GlobalGAP</h3>
<p>% cumplimiento del checklist, ítems cumpliendo, NC abiertas, productos PPPL y alertas (capacitaciones vencidas, análisis de agua).</p>
<h3>PPPL</h3>
<p>Lista oficial de productos fitosanitarios autorizados: producto, ingrediente activo, días carencia (PHI), mercado destino, notas SAG.</p>
<p>Debe estar sincronizado con <b>Bodega → PPPL</b> para que Libro de Campo valide correctamente.</p>
<h3>Documentos, Autoevaluación, NC/AC, Capacitaciones, Cosecha/Lotes, Agua, Calibración</h3>
<p>Registros trazables para auditoría externa. Cosecha bloquea lotes si no se cumple PHI.</p>
<hr>
<h2>3. Libro de Campo</h2>
<p>Registro fitosanitario con cuartel, producto, lote, operador certificado y fecha viable PHI. El sistema bloquea productos fuera de PPPL.</p>
<hr>
<h2>4. Bodega (su versión)</h2>
<ul>
<li><b>PPPL</b> — autorizar productos y días de carencia</li>
<li><b>Stock consulta</b> — ver inventario y estado PPPL</li>
</ul>
<p>Sin acceso a salidas, stock inicial ni corrección de inventario (solo administrador u operación).</p>
<hr>
<h2>5. Soporte y conceptos</h2>
<p>Soporte → Nuevo ticket para reportar errores. Conceptos: PPPL, PHI, NC/AC, capítulos AFB/CB/FV.</p>
<hr>
<h2>6. Flujos y soporte rápido</h2>
<p><b>Inicio temporada:</b> PPPL → Documentos → Autoevaluación · <b>Pre-cosecha:</b> validar PHI · <b>Auditoría:</b> cerrar NC y exportar evidencias.</p>
<table>
<tr><th>Problema</th><th>Qué hacer</th></tr>
<tr><td>Producto rechazado en Libro de Campo</td><td>Agregar a PPPL (GlobalGAP o Bodega)</td></tr>
<tr><td>No puedo cosechar un lote</td><td>Revisar fecha viable PHI</td></tr>
<tr><td>Necesito otro módulo</td><td>Solicitar al administrador</td></tr>
</table>
<p class="footer"><i>ERP Agrícola — Manual Certificación GlobalGAP v1.3</i></p>
"""

GUIA_RAPIDA_LECTOR_HTML = """
<h2>Guía rápida — Perfil Lector / Solo lectura</h2>
<p><b>Acceso:</b> <a href="https://erpmaster.cl/agricola/" target="_blank" rel="noopener">https://erpmaster.cl/agricola/</a></p>
<p>Su perfil permite <b>consultar</b> los módulos que el administrador le asignó. No puede guardar cambios, eliminar registros ni descargar PDF.</p>
<table>
<tr><th>Puede...</th><th>No puede...</th></tr>
<tr><td>Ver dashboards, tablas e historiales de sus módulos</td><td>Registrar compras, salidas, pagos o sueldos</td></tr>
<tr><td>Navegar filtros y fechas dentro del módulo</td><td>Corregir stock, facturas o datos maestros</td></tr>
<tr><td>Abrir Soporte → Nuevo ticket</td><td>Exportar PDF (botón deshabilitado)</td></tr>
<tr><td>Leer este manual</td><td>Acceder a Administración</td></tr>
</table>
<h3>Módulos típicos asignados</h3>
<p>El administrador define su menú en <b>Administración → Módulos operador</b>. Si no ve un módulo que necesita, solicítelo al administrador (no es un error del sistema).</p>
<h3>Reglas clave</h3>
<ul>
<li>Los formularios aparecen bloqueados o deshabilitados: es el comportamiento esperado.</li>
<li>Si necesita registrar operaciones, pida perfil <b>Operador</b> o que le quiten la casilla <b>Solo lectura</b>.</li>
<li>Para reportar fallas del ERP use <b>Soporte → Nuevo ticket</b>.</li>
</ul>
"""

MANUAL_COMPLETO_LECTOR_HTML = """
<h2>1. Su perfil de acceso</h2>
<p>Usted ingresa con perfil <b>Lector</b> o con la casilla <b>Solo lectura</b> activada. En ambos casos el sistema aplica las mismas restricciones:</p>
<ul>
<li>Menú acotado a los módulos asignados por el administrador</li>
<li>Consulta de datos, tablas, filtros e historiales</li>
<li><b>Sin</b> permiso para crear, editar ni eliminar registros</li>
<li><b>Sin</b> exportación PDF (botones muestran “no disponible”)</li>
<li><b>Sin</b> acceso a Administración</li>
</ul>
<p>También tiene acceso a <b>Soporte</b> (nuevo ticket) y <b>Manual</b> (esta guía).</p>
<hr>
<h2>2. Diferencia con otros perfiles</h2>
<table>
<tr><th>Perfil</th><th>Consulta</th><th>Registra</th><th>PDF</th><th>Administración</th></tr>
<tr><td>Lector / Solo lectura</td><td>Sí (módulos asignados)</td><td>No</td><td>No</td><td>No</td></tr>
<tr><td>Operador</td><td>Sí</td><td>Sí (módulos asignados)</td><td>Sí</td><td>No</td></tr>
<tr><td>Certificación</td><td>Sí (módulos cert.)</td><td>Sí (fitosanitario)</td><td>Sí</td><td>No</td></tr>
<tr><td>Administrador</td><td>Sí (todo)</td><td>Sí</td><td>Sí</td><td>Sí</td></tr>
</table>
<hr>
<h2>3. Uso de los módulos en modo consulta</h2>
<p>En cada módulo asignado puede revisar la información vigente. Ejemplos:</p>
<ul>
<li><b>Dashboard</b> — indicadores y gráficos del periodo</li>
<li><b>Compras → Historial</b> — facturas ingresadas (sin corregir)</li>
<li><b>Tesorería</b> — deudas y pagos (sin marcar pagado)</li>
<li><b>Costos</b> — matriz y detalle por cuartel (sin ajustes manuales)</li>
<li><b>Bodega → Stock consulta</b> — inventario actual</li>
<li><b>Petróleo</b> — consultar historial; no autoriza Salida Link</li>
</ul>
<p>Si un botón o campo aparece gris o bloqueado, no es un fallo: es la restricción de su perfil.</p>
<hr>
<h2>4. Soporte</h2>
<p>Para errores del sistema o solicitar más permisos: <b>Soporte → Nuevo ticket</b> describiendo módulo y necesidad. Para cambio de perfil, contacte al administrador del campo.</p>
<p class="footer"><i>ERP Agrícola — Manual Lector v1.1</i></p>
"""
