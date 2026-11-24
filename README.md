# Timetabling escolar v2

> Creado con Claude.

Aplicación de escritorio, sin conexión, para generar y **editar a mano** el horario semanal de
una escuela con preescolar, primaria y secundaria. La especificación completa está en
[`ESPECIFICACION_V2.md`](ESPECIFICACION_V2.md) y las decisiones de detalle en
[`DECISIONES.md`](DECISIONES.md).

## Estado

| Fase | Estado |
|---|---|
| F0 Esqueleto | ✔ `uv`, `pyproject`, `ruff`, `pytest`, red bloqueada en pruebas, prueba de cabeceras, CI |
| F1 Dominio y persistencia | ✔ Entidades (§5), archivo SQLite con migraciones, borrados, respaldos y bloqueo (§6), ejemplos |
| F2 Tiempo y validación | ✔ Franjas, recesos, eventos, bloqueos, traslapes, cliques, rejilla Δ, disponibilidad (§7); validación global (§10) |
| F3 Modelo duro y verificador | ✔ Modelo CP-SAT con D1–D16, etapa de factibilidad, conflictos incrementales, verificador independiente; el mediano resuelve en ~1,5 s |
| F4 Objetivo | ✔ Criterios B1–B10 con prioridades y perfiles, etapa de optimización, `timetabling generar` |
| F5 Diagnóstico | ✔ Núcleo de infactibilidad por familias y por entidad, con mensajes concretos |
| F6 GUI de captura | ✔ Ventana principal, Inicio, Configuración, Niveles, Grados y grupos, Asignaturas, Plan, Clases, Profesores, Espacios, Validación |
| F7 Generar y Resultados | ✔ Generar en segundo plano, Resultados con vistas por grupo, profesor y espacio, vigente, exportación a Excel |
| F8 Editor manual | ✔ Borradores, panel «Por colocar», colores de validez, arrastrar, intercambiar, reacomodar, deshacer, bloquear, completar, sugerir |
| F9 Reajuste y comparación | ✔ Reajustar el vigente con cambios mínimos, mapeo por traslape, comparación por asignación mínima, hoja Cambios |
| F10 Suplencias | ✔ Ausencias (completas o parciales), clases afectadas del vigente, candidatos en orden, «sin cubrir», conteo mensual y reporte del día en Excel |
| F11 Importación | ✔ Asistentes para el cuadro de horarios, el cuadro de maestros (con horarios como borrador) y proyectos v6; alias y mapeo editables; todo en una transacción con respaldo |
| F12 | Pendiente |

Lo que ya funciona:
- `timetabling` (sin argumentos) abre la interfaz gráfica: se crea o abre un proyecto y se
  capturan todos los datos de la escuela, con validación, aviso de cambios sin guardar (•),
  errores junto a cada campo, respaldos y proyectos recientes.
- `timetabling --version` muestra la versión.
- `timetabling ejemplo P.horario [--tamano pequeno|mediano] [--sobrescribir]` crea un proyecto
  de ejemplo.
- `timetabling validar P.horario` lista errores y advertencias con su acción sugerida
  (código de salida 1 si hay errores).
- `timetabling generar P.horario [--tiempo-limite N] [--hilos N]` valida, genera el horario
  (primero una solución factible y luego la optimiza según las prioridades de §9), lo comprueba
  con el verificador independiente y lo guarda en el proyecto con sus penalizaciones. Si no
  hay solución posible, explica el conflicto («El conflicto involucra los límites de carga de
  Ana y las 2 horas de Matemáticas de 1°A…»).
- En la interfaz, «Generar» resuelve sin congelar la ventana (con fase, mejor penalización y
  Cancelar) y «Resultados» muestra cada horario por grupo, profesor y espacio, sus
  penalizaciones y la carga docente; desde ahí se marca el vigente y se exporta a Excel.
- El «Editor» permite armar o ajustar un horario a mano: arrastrar clases del panel
  «Por colocar» a la rejilla, ver en verde/amarillo/rojo (✓/~/✗) dónde puede ir cada una y
  por qué, intercambiar, «colocar y reacomodar lo mínimo», bloquear (📌) las que importan,
  deshacer, «Completar el resto» con el generador y validar el borrador como definitivo.
- «Reajustar vigente» (en Generar) o `timetabling reajustar P.horario [--tiempo-limite N]`
  resuelve conservando lo más posible del horario vigente; Resultados muestra cuántas clases y
  profesores cambian, la pestaña «Cambios» y «Resaltar cambios» (↻). Un horario hecho con otra
  configuración de niveles se ajusta por traslape.
- `timetabling exportar P.horario --solucion ID --salida horario.xlsx` y
  `timetabling generar P.horario --exportar horario.xlsx` escriben el libro de Excel.
- Al abrir un proyecto se crea un respaldo diario en `.respaldos/`, un archivo de bloqueo
  `P.horario.lock` y, si la carpeta está sincronizada (OneDrive, Dropbox…), un aviso.
- La suite de pruebas bloquea la red en ejecución y verifica las cabeceras «Creado con Claude.».

## Requisitos de desarrollo

- [`uv`](https://docs.astral.sh/uv/) (instala Python 3.13 automáticamente según `.python-version`).

## Cómo probar

```bash
uv sync
```

```bash
uv run timetabling --version
```

```bash
uv run timetabling ejemplo mediano.horario --tamano mediano
```

```bash
uv run timetabling validar mediano.horario
```

```bash
uv run timetabling generar mediano.horario --tiempo-limite 60
```

```bash
uv run pytest -m "not lento and not rendimiento"
```

```bash
uv run pytest
```

```bash
uv run ruff check src pruebas
```

## Prueba manual de la interfaz

1. `uv run timetabling ejemplo mediano.horario --tamano mediano`
2. `uv run timetabling` → Archivo → Abrir… → `mediano.horario`.
3. Inicio muestra la lista de verificación en verde; recorra las pantallas de la barra lateral.
4. En Niveles cambie la duración de la hora: la vista previa de franjas se actualiza. Intente
   cambiar de pantalla sin guardar y elija Guardar, Descartar o Cancelar.
5. En Profesores, elija «Sara Kim» y arrastre sobre la cuadrícula de disponibilidad.
6. En Validación, haga doble clic en un problema para ir al elemento.
7. En Configuración ponga un tiempo límite de 30 s; en Generar pulse «Generar horario» y
   observe la fase y la penalización; luego «Ver en Resultados», elija «8°A» y «Dora Montes»
   (profesora de tres niveles), marque el horario como vigente y expórtelo a Excel.

### Prueba manual de la importación (F11)

1. Archivo → Importar proyecto anterior…: elija `pruebas/datos/proyecto_v6.horario`, revise
   el resumen y pulse «Aplicar»: se abre el proyecto nuevo con su horario vigente.
2. Cree un proyecto con los niveles Primaria (45 min, 8:00–11:20, recreo 9:30–9:50) y
   Preescolar (40 min, 8:00–10:55, recreo 9:20–9:40) y los grados 1°, 2° y Kinder.
3. Archivo → Importar cuadro de horarios (Excel)…: `pruebas/datos/cuadro_grupos.xlsx`; en el
   mapeo cambie «Math» por «Matemáticas» y aplique. Revise Plan, Clases y Niveles (hora cívica).
4. Archivo → Importar cuadro de maestros (Excel)…: `pruebas/datos/cuadro_maestros.xlsx` con
   «Importar también los horarios como borrador»; abra el borrador en el Editor.

Desde la línea de comandos:

```bash
uv run timetabling importar-v6 pruebas/datos/proyecto_v6.horario nuevo.horario
```

### Prueba manual de las suplencias (F10)

1. Con un horario vigente, abra Suplencias y elija un lunes en el calendario.
2. En «Registrar ausencia» elija un profesor con clases ese día, escriba un motivo y pulse
   «Registrar ausencia»: aparece la lista de clases afectadas y el día queda en negritas.
3. Elija una clase: el primer candidato ya está seleccionado; pulse «Asignar». Marque otra
   como «Sin cubrir». Revise «Conteo del mes».
4. Pulse «Exportar el día a Excel…» y abra el archivo: una hoja carta horizontal.
5. En el Editor, clic derecho sobre una clase → «Buscar suplente…».

### Prueba manual del reajuste (F9)

1. Con un horario vigente, en Profesores quite a «Sara Kim» la disponibilidad del lunes.
2. En Generar pulse «Reajustar vigente»: al terminar dice cuántas clases y profesores cambian.
3. En Resultados abra la pestaña «Cambios» y active «Resaltar cambios»; elija el grupo «K1A».

### Prueba manual del editor (F8)

1. En Resultados, con el horario generado, pulse «Editar una copia»: se abre el Editor.
2. Elija el grupo «8°A» y haga clic en una clase: las celdas se pintan ✓ (verde), ~ (amarillo)
   o ✗ (rojo); pase el ratón sobre una roja para ver el motivo.
3. Pulse Supr: la clase vuelve al panel «Por colocar» (Pendientes: 1). Pulse «Sugerir lugar»:
   tres celdas llevan ★. Arrastre la tarjeta a una de ellas.
4. Arrastre una clase sobre otra del mismo grupo: se ofrece «Intercambiar» o «Colocar y
   reacomodar lo mínimo» con la lista de cambios antes de aplicarlos.
5. Ctrl+Z / Ctrl+Y deshacen y rehacen; Ctrl+L bloquea (📌); Alt+flechas mueve.
6. Quite varias clases, bloquee alguna y pulse «Completar el resto»: se abre un borrador nuevo
   con ↻ en lo que cambió. «Validar y guardar como definitivo» lo deja como FACTIBLE.

## Integración continua

`.github/workflows/ci.yml` ejecuta `ruff` y las pruebas rápidas en Windows, macOS y Linux
(`QT_QPA_PLATFORM=offscreen` en Linux) en cada push, y las pruebas lentas y de rendimiento en
Windows.
