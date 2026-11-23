# Timetabling escolar v2 — Especificación para reconstrucción desde cero

> Creado con Claude. Este documento es autocontenido: describe el sistema completo que hay que
> construir. Se basa en la versión anterior (esquema v6, noviembre 2026) y corrige los problemas
> detectados en su revisión crítica. La trazabilidad está en el Apéndice A.

---

## 0. Instrucciones para Claude Code

**Objetivo:** construir desde un repositorio vacío una aplicación de escritorio, sin conexión,
que genere y permita **editar a mano** el horario semanal de una escuela con preescolar,
primaria y secundaria.

**Reglas de trabajo:**

1. Trabaja **por fases** (§21), en orden. No empieces una fase sin que la anterior cumpla sus
   criterios de aceptación: pruebas en verde y `ruff` limpio.
2. Haz un commit por fase, o varios commits pequeños dentro de una fase, con mensajes en español.
3. Registra en `DECISIONES.md` cada decisión de detalle que esta especificación no cubra: fecha,
   contexto, decisión y alternativa descartada. Si una decisión cambia el alcance o contradice
   este documento, **pregunta antes**.
4. Cada archivo `.py` empieza con un docstring de módulo cuya primera línea es
   `Creado con Claude.`. El `README.md` también lo indica al principio. Hay una prueba que lo
   verifica (§20).
5. Los identificadores del dominio, los docstrings, los mensajes y la interfaz van en español.
   Los nombres técnicos genéricos (`id`, `json`) se permiten.
6. Escribe código con tipos en todas partes. Usa `ruff` con línea de 100 y reglas `E F I UP B`.
7. No agregues dependencias fuera de §3 sin registrarlo en `DECISIONES.md`.
8. Al terminar cada fase, actualiza el `README.md` con lo que ya funciona y cómo probarlo.

---

## 1. Propósito y alcance

La aplicación sirve para:
- capturar los datos de la escuela;
- **generar** el horario con un solver;
- **crearlo o ajustarlo a mano** con validación en vivo;
- reajustar un horario en uso con cambios mínimos;
- gestionar ausencias y suplencias por fecha;
- exportar a Excel y PDF.

**Fuera de alcance:**
- asignación de aulas concretas (solo se controla la capacidad por tipo de espacio especial);
- horarios de exámenes;
- semanas alternas A/B;
- red, sincronización o multiusuario.

El diseño no debe impedir agregar más adelante las semanas A/B ni las aulas concretas.

## 2. Requisitos no funcionales

| Requisito | Detalle |
|---|---|
| Sin conexión | Ninguna llamada de red, servidor (ni `localhost`) ni telemetría. Se verifica **en ejecución** (§20). |
| Proyecto = archivo | Cada escuela es un archivo SQLite `.horario`. Se hacen respaldos automáticos (§6.4). |
| Interfaz | Escritorio con PySide6. Nunca se congela; el solver corre en un hilo aparte. |
| Rendimiento | Ejemplo mediano (30 grupos, ~42 profesores): primera solución factible en menos de 60 s y resultado final en menos de 5 min en una laptop de 4 núcleos. Se mide en una prueba de rendimiento (§20). |
| Robustez de datos | Ninguna operación pierde horarios guardados sin confirmación y sin respaldo previo. |
| Idioma | Español en todo (ver §0). |
| Plataformas | Windows 10/11 x64 es la **plataforma principal**. Le siguen macOS arm64 e Intel. Ejecutable sin requerir Python instalado. |
| Lenguaje | Python ≥ 3.13, gestionado con `uv` y `.python-version`. |

## 3. Stack

| Paquete | Uso |
|---|---|
| `PySide6` ≥ 6.12 | Interfaz; también `QPdfWriter` para exportar a PDF y `QUndoStack` para deshacer |
| `sqlite3` (stdlib) | Persistencia |
| `ortools` ≥ 9.15 | Solver CP-SAT |
| `pydantic` v2 | Modelos del dominio (`validate_assignment=True`, `extra="forbid"`, `frozen` donde aplique) |
| `XlsxWriter` ≥ 3.3 | Exportación a Excel |
| `openpyxl` | Importación de Excel (dependencia de ejecución: la importación ahora está en la interfaz) |
| `typer` | Línea de comandos |
| `pytest`, `pytest-qt`, `hypothesis`, `ruff`, `pyinstaller` (dev) | Pruebas, estilo, empaquetado |

## 4. Arquitectura

Regla de dependencias: **el núcleo no conoce la base de datos, la interfaz ni Excel**.

```
gui, cli  →  servicios  →  persistencia, nucleo, importacion, exportacion  →  dominio
```

`servicios/` coordina los casos de uso (generar, reajustar, editar un borrador, importar,
registrar una suplencia). Ni la interfaz ni la línea de comandos tocan el repositorio
directamente para operaciones compuestas.

```
src/timetabling/
├── dominio/
│   ├── modelos.py          # entidades pydantic y DatosEscuela
│   ├── tiempo.py           # minutos, conversión HH:MM, días
│   ├── clases.py           # generación de Clases a partir del plan; destinatarios
│   ├── borrador.py         # horario editable (colocar, quitar, intercambiar, pendientes)
│   ├── cuadricula.py       # disposición común de horarios (GUI, Excel, PDF)
│   ├── colores.py
│   ├── estadisticas.py
│   └── comparacion.py
├── persistencia/
│   ├── esquema.sql
│   ├── migraciones.py      # empieza en v1; la v2 de la app no comparte versiones con la anterior
│   ├── respaldos.py
│   └── repositorio.py
├── nucleo/
│   ├── franjas.py          # franjas, rejilla temporal, traslapes, cliques, disponibilidad
│   ├── conflictos.py       # comprobaciones incrementales por clase y franja (editor y verificador)
│   ├── validacion.py
│   ├── modelo.py           # restricciones duras
│   ├── objetivo.py         # restricciones blandas
│   ├── resolver.py
│   ├── diagnostico.py
│   ├── verificador.py
│   ├── reparacion.py       # «colocar y reacomodar lo mínimo», «sugerir lugar»
│   └── suplencias.py
├── servicios/
├── importacion/
│   ├── horarios_excel.py
│   ├── maestros_excel.py
│   └── proyecto_v6.py      # importa un .horario de la versión anterior
├── exportacion/
│   ├── estilos.py
│   ├── excel.py
│   └── pdf.py
├── gui/
│   ├── app.py
│   ├── trabajador.py
│   ├── pantallas/
│   └── widgets/
├── recursos/
├── ejemplo.py
└── cli.py
```

## 5. Modelo del dominio

Las horas se manejan en **minutos desde medianoche** (`int`). Los días válidos son
`L M X J V S D` (por defecto `L–V`). La carga docente se mide en **minutos**.

### 5.1 Entidades de configuración y estructura

| Entidad | Campos (valor por defecto) | Reglas |
|---|---|---|
| `Configuracion` | `nombre_escuela` («Mi escuela»), `margen_traslado_min` (0, 0–120), `descanso_minimo_min` (10, 0–60; ver D8), `tiempo_limite_s` (300), `hilos` (`min(8, núcleos)`), `criterios` (§9), `respaldos_a_conservar` (10) | Nombre no vacío |
| `Nivel` | `nombre`, `duracion_min` (5–240), `inicio_jornada`, `fin_jornada`, `dias`, `recesos`, `eventos`, `duraciones_especiales` ({índice → minutos}), `huecos_alumnos` (`permitidos`/`penalizar`/`prohibidos`; por defecto `penalizar`), `preferir_titular` (no) | Inicio < fin; al menos un día. **Ningún comportamiento depende del nombre del nivel.** |
| `Receso` | `nombre`, `inicio`, `fin` | Inicio < fin |
| `Evento` | `nombre` («Hora cívica»), `dia`, `inicio`, `fin` | Actividad de todo el nivel (D14) |
| `Grado` | `nivel_id`, `nombre` | Único por nivel |
| `Grupo` | `grado_id`, `seccion`, `estudiantes` (0, informativo), `titular_id` (opcional), `bloqueos` | Nombre visible = grado + sección (`7°A`) |
| `BloqueoGrupo` | `dia`, `inicio`, `fin`, `nombre` | Franjas en que ese grupo no tiene clase (sale temprano, natación) |
| `Division` | `grupo_id`, `nombre` («Inglés por nivel»), `partes` (≥2 nombres), `simultanea` (sí) | Subgrupos de un grupo. Las partes de una división pueden tener clase al mismo tiempo. |
| `Asignatura` | `nombre`, `color`, `espacio_requerido` (tipo o nada), `reglas_por_defecto` | Nombre único |
| `ReglasAsignatura` | `max_horas_dia` (2), `bloque_doble` (`no`/`preferido`/`obligatorio`), `franjas_prohibidas`, `franjas_preferidas` | Se pueden **sobrescribir por nivel** (`ReglasAsignaturaNivel`: `asignatura_id`, `nivel_id` y los mismos campos opcionales) |
| `RangoFranjas` | `dias` (todos si vacío), `desde_indice`, `hasta_indice` **o** `desde`, `hasta` (HH:MM) | Ejemplo: «Ed. Física no en la 1.ª hora», «Matemáticas antes de las 11:00» |
| `PlanEstudios` | `grado_id`, `asignatura_id`, `horas_semanales` (en horas-clase del nivel) | Guardar 0 elimina la fila |
| `Profesor` | `nombre`, `activo` (sí), `asignaturas`, `grados`, `disponibilidad`, `disponible_toda_la_jornada` (sí), `eventos`, `suplencia_asignaturas`, `suplencia_grados`, `carga_max_semanal_min` (2400), `carga_max_diaria_min` (480), `carga_min_semanal_min` (0), `max_dias` (opcional), `max_minutos_continuos` (200) | Nombre único entre activos. **No se borra si aparece en un horario guardado**: se desactiva (§6.3). |
| `Disponibilidad` | `dia`, `inicio`, `fin`, `tipo` (`disponible`/`preferible_no`/`no_disponible`) | Con `disponible_toda_la_jornada`, el profesor puede dar clase en toda la jornada de sus niveles salvo en los rangos `no_disponible`. Sin esa marca, solo puede en los rangos `disponible`. |
| `Espacio` | `nombre`, `tipo`, `cantidad` (1) | Capacidad de un tipo = Σ cantidades |
| `AliasImportacion` | `texto`, `asignatura_id` | Tabla editable para la importación (§15) |

### 5.2 Clases: la unidad que se programa

Una `Clase` es lo que se coloca en el horario. Este concepto sustituye al antiguo
«grupo × asignatura» con un solo profesor, y permite **clases conjuntas** (varios grupos con
uno o más profesores) y **clases divididas** (un grupo partido en subgrupos).

| Campo | Descripción |
|---|---|
| `asignatura_id` | |
| `destinatarios` | Lista de pares `(grupo_id, parte)`. `parte = None` significa el grupo completo. Debe haber al menos uno y **todos los grupos deben ser del mismo nivel**. |
| `profesores` | Lista de ids. Vacía significa que **el generador elige uno** entre los habilitados. Con uno o más, todos imparten juntos. |
| `horas_semanales` | En franjas del nivel |
| `espacio_requerido` | Hereda el de la asignatura; se puede sobrescribir |
| `origen` | `plan` (creada al sincronizar con el plan) o `manual` |

**Sincronizar con el plan** (`dominio/clases.py`): por cada grupo y fila del plan, si ninguna
clase cubre ese par `(grupo, asignatura)`, se crea una clase de grupo completo con las horas
del plan. Las clases editadas a mano no se tocan. Se informan las diferencias:
- grupos con horas de más o de menos respecto al plan;
- clases huérfanas (su asignatura ya no está en el plan).

**Cobertura del plan:** para cada `(grupo, asignatura)` del plan se cuentan las horas recibidas.
- Si el grupo tiene clases de esa asignatura sobre partes de una división, **cada parte** debe
  recibir las horas del plan.
- Si no, el grupo completo debe recibirlas.

### 5.3 Fijas y soluciones

| Entidad | Campos | Reglas |
|---|---|---|
| `AsignacionFija` | `clase_id`, `profesor_id` (opcional, solo si la clase no tiene profesores fijos), `dia`, `indice_franja` | |
| `Solucion` | `nombre`, `fecha`, `estado`, `origen` (`generado`/`manual`/`editado`/`importado`), `tiempo_s`, `penalizaciones`, `nota`, `vigente`, `base_id` (de qué solución partió), `huella_niveles`, `franjas` (instantánea), `asignaciones`, `violaciones` | Solo una vigente a la vez. Solo los estados `BORRADOR` se pueden editar. |
| `FranjaGuardada` | `nivel_id`, `dia`, `indice`, `inicio`, `fin` | Copia de las franjas al momento de guardar |
| `Asignacion` | `clase_id` (nullable), `franja` (ref. a `FranjaGuardada`), `profesor_id` (nullable), **y copias desnormalizadas**: `asignatura_nombre`, `grupos_texto`, `profesor_nombre`, `color` | El horario guardado sigue siendo legible aunque se edite o se elimine la entidad original |

**Estados:** `OPTIMO`, `FACTIBLE`, `INFACTIBLE`, `SIN_SOLUCION_EN_TIEMPO`, `CANCELADO`,
`BORRADOR` (incompleto o editable), `INVALIDA` (el verificador encontró violaciones; se guarda
con la lista para depurar).

**Huella de niveles:** hash estable de la configuración temporal de todos los niveles (duración,
jornada, días, recesos, eventos, duraciones especiales). Si la huella actual no coincide con la
de una solución, esa solución se marca **«desactualizada»**:
- se sigue viendo con sus propias franjas guardadas;
- se puede usar como base de un reajuste, mapeando por traslape (§13);
- no se puede editar directamente (se ofrece «Editar una copia ajustada»).

## 6. Persistencia

### 6.1 Archivo
- SQLite con `PRAGMA foreign_keys = ON` y `journal_mode = DELETE` (nunca WAL; el archivo debe
  ser un único fichero portátil).
- Cada operación compuesta se ejecuta en **una transacción**.
- Al abrir, si la ruta está dentro de una carpeta sincronizada (OneDrive, Dropbox, Google
  Drive, iCloud Drive o una unidad de red), se muestra un aviso **no bloqueante** con
  recomendaciones. La detección se hace por nombres de ruta y tipo de unidad, sin red.
- Al abrir se crea un archivo de bloqueo `.horario.lock` con el PID y el equipo. Si ya existe y
  sigue vigente, se avisa que el proyecto podría estar abierto en otro lugar.

### 6.2 Esquema y migraciones
- `esquema.sql` describe siempre la versión actual; `MIGRACIONES[n]` lleva de `n-1` a `n`.
- Abrir un proyecto más nuevo que el programa produce `ErrorVersionEsquema` con un mensaje
  claro.
- Los archivos de la versión anterior de la app (esquema v6) **no se abren**: se importan con
  `proyecto_v6.py` (§15.3). Se detectan por su tabla `esquema_version` y se ofrece importarlos.

### 6.3 Borrados
- Se borra en cascada lo estructural: recesos, eventos, bloqueos, divisiones, disponibilidad,
  relaciones y filas del plan.
- Las referencias desde las soluciones (`asignaciones.clase_id`, `profesor_id`) usan
  `SET NULL`. Las copias desnormalizadas mantienen legible el horario.
- **Un profesor que aparece en alguna solución no se elimina**: la interfaz ofrece
  desactivarlo. Un profesor inactivo no entra al generador, no aparece como candidato y se
  muestra atenuado.
- `Repositorio.afectados_por_eliminar()` cuenta lo afectado. La interfaz lo muestra antes de
  confirmar.

### 6.4 Respaldos
- Se crea un respaldo automático en `<carpeta del proyecto>/.respaldos/<nombre>-AAAAMMDD-HHMMSS.horario`
  (usando la API de respaldo de `sqlite3`):
  - al abrir el proyecto, como máximo uno por día;
  - antes de cualquier operación destructiva: reemplazar datos, importar, eliminar soluciones,
    eliminar en cascada más de N elementos.
- Se conservan los últimos `respaldos_a_conservar`.
- Menú **Archivo → Restaurar respaldo…**.

## 7. Tiempo: franjas, rejilla, traslapes y disponibilidad (`nucleo/franjas.py`)

1. **Generación de franjas:** por nivel y día, franjas consecutivas desde `inicio_jornada`. La
   franja `i` dura `duraciones_especiales[i]` o `duracion_min`. Si chocaría con un receso,
   empieza al terminar este (`receso_antes = True`). Se detiene cuando la franja no cabe antes de
   `fin_jornada`. Id: `"nivel:día:índice"`.
2. **Franjas útiles:** se descartan las que toca un evento del nivel, conservando los índices.
   Para cada grupo se descartan además las que toca un `BloqueoGrupo`.
3. **Adyacencia:** dos franjas son adyacentes si son consecutivas, del mismo nivel y día, sin
   receso ni hueco de tiempo entre ellas.
4. **Traslape:** `[a,b)` y `[c,d)` del mismo día se traslapan si `a < d + m` y `c < b + m`,
   con `m = margen_traslado_min` solo entre niveles distintos. Se calculan los **cliques
   maximales** (Bron–Kerbosch con pivote, incluidas las franjas aisladas).
5. **Rejilla temporal:** paso `Δ = mcd` de todos los límites de franjas, recesos y márgenes, con
   mínimo 5 min. Cada franja cubre un conjunto de «ticks». Se usa para D8 y B1 sobre la línea
   de tiempo **real** del profesor, cruzando niveles.
6. **Validez para un profesor:** la franja cabe completa en su disponibilidad efectiva de ese día
   (rangos contiguos fusionados), no se cruza con `no_disponible` ni con un evento al que asiste.
   Es `preferible_no` si toca un rango de ese tipo.
7. **Redondeos:** si el editor de disponibilidad (cuadrícula de 5 min) recorta un rango de modo
   que una franja deja de ser válida, se avisa en el editor.

## 8. Restricciones duras (`nucleo/modelo.py`)

**Variables:** `x[c,p,s]` booleana solo si:
- `p` puede impartir la clase `c`: está en `c.profesores` o, si la lista está vacía, está
  habilitado para la asignatura y para el grado de **cada** destinatario;
- `s` es una franja útil para **todos** los grupos destinatarios;
- `s` es válida para `p`;
- `s` no cae en una franja prohibida de la asignatura en ese nivel.

**Auxiliares:**
- `y[c,p]`: `p` está a cargo de `c`;
- `z[c,s]`: la clase ocurre en `s`;
- `o[p,s]`: el profesor da clase en `s`;
- `ocupado[p,t]`: el profesor está ocupado en el tick `t`, igual a `Σ` de `o[p,s]` sobre las
  franjas que cubren `t`.

| # | Restricción | Formulación |
|---|---|---|
| D1 | Horas de cada clase | `Σ_s z[c,s] = horas_semanales` |
| D2 | Grupo en una sola clase | Por grupo y franja: `Σ z ≤ 1` sobre las clases que ocupan al grupo completo o a partes de **distintas** divisiones. Las partes de una misma división pueden coincidir. |
| D3 | Profesor en un solo lugar | Por profesor y clique: `Σ x ≤ 1` |
| D4 | Competencia | Por poda de variables |
| D5 | Disponibilidad | Por poda de variables |
| D6 | Continuidad docente | Clase sin profesores fijos: `Σ_p y = 1` y `x[c,p,s] ≤ y[c,p]`. Con profesores fijos: todos están en cada franja de la clase (`x[c,p,s] = z[c,s]`). |
| D7 | Carga | Minutos semanales entre `carga_min_semanal_min` y `carga_max_semanal_min`; minutos diarios ≤ máximo (solo si puede excederse); días con clase ≤ `max_dias` |
| D8 | Tiempo continuo máximo | Por profesor, día y tick `t`: `Σ ocupado[p, t … t+M+P) ≤ M/Δ`, con `M = max_minutos_continuos` y `P = descanso_minimo_min`. **Cruza niveles**; los recesos y huecos cuentan como descanso. |
| D9 | Espacios especiales | Por tipo y clique: clases que lo requieren ≤ capacidad |
| D10 | Máximo diario por asignatura | Por destinatario, asignatura y día: `Σ ≤ max_horas_dia` (de las reglas efectivas del nivel). Con máximo 2, prohibidos los pares no adyacentes. |
| D11 | Bloque doble obligatorio | Variables de par `b` sobre franjas adyacentes y sueltas `u`: `z[s] = Σ b + u[s]`, `Σ u ≤ horas % 2` |
| D12 | Sin huecos para alumnos | Si `huecos_alumnos = prohibidos`: por grupo y día, `ocupada[k] ≥ ocupada[k+1]` sobre las franjas útiles del grupo |
| D13 | Asignaciones fijas | `z[c,s] = 1` y, si la fija trae profesor, `x[c,p,s] = 1` |
| D14 | Eventos y bloqueos | Por construcción |
| D15 | Franjas prohibidas por asignatura | Por poda |
| D16 | Divisiones simultáneas | Si `division.simultanea`, las clases de las partes de esa división **para la misma asignatura** ocurren en las mismas franjas: `z[c1,s] = z[c2,s]`. La validación exige que tengan las mismas horas. |

Cada restricción se registra con una **clave de familia** (`curricular`, `grupo`, `profesor`,
`carga`, `continuidad`, `espacio`, `diaria`, `bloque`, `sin_huecos`, `fija`, `division`) y una
**clave de entidad** (`profesor:12`, `grupo:7`, `clase:40`, `espacio:laboratorio`) para el
diagnóstico (§11.3).

## 9. Restricciones blandas y prioridades (`nucleo/objetivo.py`)

### 9.1 Criterios

| # | Criterio | Unidad normalizada |
|---|---|---|
| B1 | Huecos de profesores | Minutos libres entre su primera y su última clase del día, **sobre la línea de tiempo real y cruzando niveles**; no cuentan los ticks dentro de recesos de los niveles en que da clase ese día. Unidad = 50 min. |
| B2 | Mala distribución semanal | Por clase y día, `max(0, horas_del_día − ⌈horas_semanales / días_lectivos⌉)`. Unidad = 1 franja. |
| B3 | Fuera de las franjas preferidas de la asignatura | 1 por franja. Sustituye al antiguo «exigente en la tarde». |
| B4 | Franja `preferible_no` del profesor | 1 por franja |
| B5 | Días con clase por profesor | 1 por día |
| B6 | Desequilibrio de carga | Máx − mín de minutos entre profesores de la misma asignatura y nivel. Unidad = 50 min. |
| B7 | Grupo sin su titular | En niveles con `preferir_titular`: franjas del grupo no impartidas por su titular |
| B8 | Bloque doble preferido | `Σ u − horas % 2` |
| B9 | Cambios respecto a la base | Solo al reajustar o reparar. Por clase base: cambiar solo el profesor = 1; moverla de hora = 2. |
| B10 | Huecos de alumnos | Solo si `huecos_alumnos = penalizar`. Franjas libres entre la primera y la última clase del grupo. |

### 9.2 Prioridades (en lugar de pesos sueltos)

Cada criterio tiene una prioridad: `desactivado`, `baja`, `media`, `alta` o `muy alta`. Sus
multiplicadores son 0, 1, 4, 16 y 64; el peso efectivo es `multiplicador × unidad normalizada`.
Los criterios desactivados no se construyen. B9 siempre usa un multiplicador fijo de 64.

Valores predefinidos («perfiles»), que se eligen en Configuración:

| Perfil | B1 | B2 | B3 | B4 | B5 | B6 | B7 | B8 | B10 |
|---|---|---|---|---|---|---|---|---|---|
| Equilibrado (por defecto) | alta | alta | media | media | baja | baja | media | media | alta |
| Priorizar profesores | muy alta | media | baja | alta | media | media | baja | baja | media |
| Priorizar alumnos | media | muy alta | alta | baja | baja | baja | alta | alta | muy alta |

Hay un modo **Avanzado** (oculto por defecto) que permite escribir pesos numéricos.

## 10. Validación global (`nucleo/validacion.py`)

Cada `Problema` lleva entidad, id, elemento, severidad, mensaje y una **acción sugerida** (texto).
Con al menos un error no se resuelve. Los mensajes nombran entidades concretas.

| Revisión | Severidad |
|---|---|
| Cobertura del plan por las clases (§5.2): horas de más, de menos, clases huérfanas | Error |
| Clase conjunta con grupos de distinto nivel | Error |
| Clase sin profesor posible (ningún habilitado o los fijos no habilitados) | Error |
| Horas de cada grupo y parte ≤ sus franjas útiles | Error |
| Capacidad docente por asignatura y nivel (minutos requeridos contra minutos disponibles de los habilitados) | Error |
| **Por profesor:** minutos de sus clases con profesor fijo ≤ su carga máxima, y horas ≤ franjas en que está disponible en cada nivel | Error |
| Carga mínima imposible de alcanzar con sus habilitaciones | Error |
| Demanda de espacios ≤ franjas × capacidad, por nivel | Error |
| Asignaciones fijas coherentes (franja existente y útil, profesor posible y disponible, sin choques entre fijas, no más fijas que horas) | Error |
| `max_horas_dia × días ≥ horas_semanales` (con las reglas efectivas) | Error |
| Bloque doble obligatorio con `max_horas_dia < 2` | Error |
| Partes de una división simultánea con horas distintas | Error |
| Franjas prohibidas de una asignatura que dejan menos franjas que horas | Error |
| Rango de disponibilidad que no cubre ninguna franja; evento o bloqueo que no toca ninguna franja; duración especial de una hora que no existe | Advertencia |
| Incompletos: grado sin grupos o sin plan, nivel sin franjas, profesor sin asignaturas o grados | Advertencia |

## 11. Resolución, verificación, conflictos y diagnóstico

### 11.1 `resolver.py`
- Construye el modelo descontando su tiempo del límite (mínimo 1 s de búsqueda).
- **Etapa 1:** factibilidad sin objetivo (`stop_after_first_solution`).
- **Etapa 2:** optimización con el objetivo, usando la primera solución como pista.
- Informa `Progreso(fase, soluciones, mejor_objetivo, cota, tiempo_s)`.
- `cancelar()` conserva la mejor solución encontrada.
- Acepta `base` (reajuste: pista + B9) y `vecindario` (conjunto de clases libres; el resto se
  fija), que usa la reparación (§12.4).
- Si la etapa 2 no termina, las penalizaciones se informan marcadas como «cota superior».

### 11.2 `conflictos.py` y `verificador.py`
- `conflictos.py` expone comprobaciones **incrementales**:
  `motivos(datos, borrador, clase, franja, profesor=None) -> list[Motivo]`. Cada `Motivo` trae
  severidad (`dura` o `blanda`), restricción (D·/B·) y un texto con las entidades concretas
  («López ya da 8°B de 9:00 a 9:50»).
- Debe responder en **menos de 2 ms** por celda en el ejemplo mediano. Para eso se precalculan
  índices de ocupación por profesor, grupo y tipo de espacio en la línea de tiempo.
- `verificador.py` comprueba referencias y D1–D16 sobre una lista completa de asignaciones,
  usando `conflictos.py` y **sin compartir código con `modelo.py`**:
  - D5 se revisa minuto a minuto;
  - D9 se revisa con la ocupación física real.
- Se ejecuta siempre al terminar de resolver y al guardar un borrador. Con violaciones, la
  solución se guarda como `INVALIDA` junto con la lista.
- En modo **parcial** (borradores), las horas faltantes (D1) se informan como «pendientes» y
  no como violación.

### 11.3 `diagnostico.py`
Solo se ejecuta si el resultado es `INFACTIBLE`.

1. **Por familias:** reconstruye el modelo sin objetivo, con cada familia bajo un literal de
   suposición y `num_workers = 1`; obtiene `sufficient_assumptions_for_infeasibility` y lo
   reduce con un filtro de eliminación.
2. **Refinamiento:** dentro de las familias del núcleo, sustituye la familia por literales
   **por entidad** y repite.
3. Presupuesto: 10 s por intento, 60 s en total (30 s desde la interfaz).

El resultado se traduce a mensajes del tipo «El conflicto involucra la disponibilidad de López,
la carga máxima de López y las 6 horas de Matemáticas de 7°A», con enlaces a esas entidades.
Si el núcleo queda vacío, se informa un conflicto estructural.

### 11.4 `suplencias.py`
Dada una clase y una franja (y opcionalmente una fecha), lista los profesores que pueden
cubrirla:
- habilitados (titulares o marcados como suplentes para esa asignatura **y** grado) y activos;
- disponibles en la franja, sin evento que la toque;
- sin otra clase **ni otra suplencia ese día** que se les cruce (con margen de traslado).

Orden: primero quienes la imparten normalmente, luego sin «preferible no», luego con menos
clases y suplencias ese día, luego con menos suplencias en el mes, luego por nombre.

## 12. Editor manual de horarios (función central)

El editor es la herramienta principal del día a día: el usuario coloca lo que le importa, el
sistema valida en vivo y el generador completa o repara.

### 12.1 Borradores
- Un borrador es una `Solucion` con estado `BORRADOR` y origen `manual` o `editado`.
- Se crea desde:
  1. un horario vacío;
  2. **una copia** de cualquier solución (las soluciones generadas no se editan directamente);
  3. el horario actual de la escuela importado de Excel (§15.2).
- Cada operación se guarda al instante en una transacción y se registra en un `QUndoStack`
  (Ctrl+Z / Ctrl+Y) durante la sesión de edición.
- «Validar y guardar como definitivo» ejecuta el verificador completo. Si pasa, el estado
  cambia a `FACTIBLE` y se puede marcar como vigente.

### 12.2 Pantalla

| Elemento | Comportamiento |
|---|---|
| **Panel «Por colocar»** | Tarjetas derivadas de `borrador.pendientes()`: «Matemáticas · 7°A · López · faltan 3 de 5». Las clases con bloque doble obligatorio aparecen como tarjeta de 2 franjas. Filtros por grupo, profesor y asignatura; búsqueda por texto. |
| **Vistas** | Por grupo, por profesor, por espacio y **vista maestra** (filas = grupos o profesores, columnas = todas las franjas de la semana). La selección se sincroniza entre vistas. |
| **Al tomar una tarjeta o una clase** | Cada celda destino se pinta: 🟩 válida · 🟨 válida con penalización · 🟥 inválida. El tooltip lista los `Motivo` de §11.2. |
| **Soltar en una celda libre** | Coloca la clase. Si la clase no tiene profesor, aparece la lista de candidatos (orden de §11.4) para elegir. |
| **Soltar en una celda ocupada** | Si ambas quedan válidas, se ofrece **Intercambiar**. Si no, se ofrece **Colocar y reacomodar lo mínimo** (§12.4). |
| **Modo estricto / flexible** | Estricto (por defecto): no permite soltar en rojo. Flexible: lo permite y la clase queda marcada ⚠ con su motivo en la lista de conflictos. |
| **Acciones sobre una clase** | Mover (arrastrar o flechas), Supr (devolver al panel), 📌 Bloquear/Desbloquear, doble clic = cambiar profesor, menú contextual con «Buscar suplente…» y «¿Por qué no puede ir en…?». |
| **Barra de estado** | Pendientes, conflictos duros, penalización total en vivo (calculada sin solver), barra de carga del profesor o grupo seleccionado. |
| **Lista de conflictos** | Panel desplegable; clic = navegar a la clase. |

### 12.3 Completar automáticamente
«Completar el resto» lanza el resolutor:
- las clases **bloqueadas** del borrador entran como `AsignacionFija`;
- las no bloqueadas entran como `base` (pista + B9), para que se respeten mientras no estorben.

El resultado se abre como un **nuevo borrador** con los cambios marcados con ↻. El original no
se toca.

### 12.4 Reparación local (`nucleo/reparacion.py`)
- **Colocar y reacomodar lo mínimo:**
  1. fija la clase en la celda pedida;
  2. el vecindario es todas las clases que comparten grupo, profesor o espacio con ella ese día;
  3. si no hay solución en 3 s, el vecindario se amplía a toda la semana de esos grupos y
     profesores;
  4. el resto queda fijo;
  5. se minimiza B9 más el objetivo normal.

  Se muestra una **vista previa** (lista «antes → después» y ↻ en la cuadrícula) que el usuario
  acepta o descarta. Objetivo de tiempo: menos de 3 s en el ejemplo mediano.
- **Sugerir lugar:** para una tarjeta, evalúa las celdas verdes con la penalización marginal y
  resalta las 3 mejores.

### 12.5 Relación con «Clases fijas»
No existe una pantalla aparte de clases fijas: **fijar es bloquear en el editor**. Las clases
bloqueadas del borrador de trabajo (o del vigente) se convierten en `AsignacionFija` al
generar. La pantalla Generar muestra cuántas fijas hay y de dónde vienen.

## 13. Horario vigente, reajuste y comparación

1. Solo puede haber una solución vigente. Se marca en Resultados o en el editor (solo si es
   válida).
2. **Reajustar horario vigente:** resuelve con la vigente como `base`. Nunca vuelve infactible
   el problema por culpa de la base. Si la base está desactualizada (huella distinta), cada
   clase guardada se mapea a la franja actual de **mayor traslape en minutos** del mismo día y
   nivel; las que no se puedan mapear se cuentan como «sin correspondencia».
3. Emparejamiento entre clases guardadas y actuales: por `clase_id` si existe; si no, por
   asignatura + destinatarios.
4. **Comparación** (`dominio/comparacion.py`): por cada clase, empareja las ocurrencias de los
   dos horarios resolviendo un **problema de asignación de costo mínimo** (costo 0 = igual,
   1 = solo cambia el profesor, 2 = cambia la hora, 3 = cambian ambas). Lo no emparejado se
   reporta como clase agregada o quitada.
5. Resultados muestra el conteo de clases y profesores afectados, ↻ en las vistas, y la
   pestaña y hoja Excel «Cambios». La nota de cada reajuste guarda de qué horario partió
   (`base_id`).

## 14. Ausencias y suplencias

| Entidad | Campos |
|---|---|
| `Ausencia` | `profesor_id`, `fecha_inicio`, `fecha_fin`, `desde` / `hasta` (opcionales, para ausencias parciales), `motivo` |
| `Suplencia` | `fecha`, `solucion_id` (la vigente en ese momento), `asignacion_id`, `profesor_ausente_id`, `suplente_id` (nulo = «sin cubrir»), `nota` |

**Pantalla Suplencias:**
- calendario y selector de fecha;
- al registrar una ausencia se listan las clases afectadas del vigente en esas fechas;
- por cada clase: candidatos (§11.4), asignación con un clic o marcar «sin cubrir».

Reportes:
- **Suplencias del día** (Excel y PDF, una página imprimible);
- conteo mensual de suplencias por profesor (cubiertas y realizadas).

Las suplencias no modifican el horario vigente.

## 15. Importación (desde la interfaz y la línea de comandos)

Toda importación funciona como un **asistente**:
1. elegir el archivo;
2. vista previa con lo detectado;
3. mapeo editable;
4. resumen de lo que se creará o cambiará;
5. aplicar **en una transacción**, con respaldo previo.

### 15.1 Cuadro de horarios por grado (`horarios_excel.py`)
- **Formato:** una hoja por grado; cada grupo es un bloque de columnas de días con la columna de
  horas a la izquierda y el nombre del grupo encima; se ignora lo que sigue a «Horarios de
  Examen».
- El asistente permite mapear **hojas → grados** (detecta por defecto `kinder`, `Prepa`,
  `1st`…`11th`, pero no depende de esos nombres) y **textos → asignaturas** usando
  `AliasImportacion` (editable y guardada en el proyecto).
- Las celdas de recreo (Lunch, Snack, Playground, Recess, Receso, Recreo) y tutorías son
  configurables.
- Cuenta las sesiones semanales por asignatura y toma por grado el valor más frecuente,
  avisando si los grupos difieren.
- Crea asignaturas, grupos, filas del plan y los eventos detectados. Requiere que existan los
  niveles y los grados (si faltan, el asistente ofrece crearlos).

### 15.2 Cuadro de maestros (`maestros_excel.py`)
- **Formato:** un bloque por maestro (nombre encima de la fila de días); cada celda indica
  asignatura y grupo («ESPAÑOL 3A», «Math PPA»). Si solo trae el grupo, se usa la asignatura
  más frecuente del maestro.
- Normaliza los títulos (Ms., Mr., Prof., Mtra.).
- Crea o actualiza profesores (asignaturas, grados; disponibilidad = toda la jornada) y fija el
  profesor de las clases correspondientes.
- **Nuevo:** opción «Importar también los horarios como borrador». Cada celda se mapea a la
  franja de mayor traslape de su nivel; las que no se puedan mapear se listan. El borrador
  resultante puede revisarse en el editor y marcarse como vigente.

### 15.3 Proyecto de la versión anterior (`proyecto_v6.py`)
Lee un `.horario` con esquema v6 y crea un proyecto nuevo:
- configuración → criterios: los pesos se convierten al perfil más cercano y se guardan también
  como pesos avanzados;
- niveles, recesos y eventos;
- grados y grupos;
- asignaturas: reglas globales; `exigente` se convierte en una franja preferida «primera mitad
  de la jornada»;
- plan;
- profesores: `docentes_asignados` pasa a `Clase.profesores`;
- espacios;
- asignaciones fijas: se convierten en clases bloqueadas de un borrador;
- soluciones: se importan con franjas reconstruidas y copias desnormalizadas; la vigente se
  conserva;
- un nivel llamado «Preescolar» activa `preferir_titular`.

Al terminar se muestra un informe de lo importado y de lo que no se pudo importar.

## 16. Exportación

### 16.1 Excel (`excel.py`)

| Hoja | Contenido |
|---|---|
| `Resumen` | Escuela, fecha, estado, origen, tiempo, cada penalización (marcada si es cota) |
| Una por grupo | Filas = franjas del nivel (con hora y recesos), columnas = días; asignatura y profesor; las partes de una división se muestran en la misma celda |
| Una por profesor con clases | Un nivel: cuadrícula del nivel. Varios: filas en la rejilla Δ con celdas combinadas según la duración real |
| Una por tipo de espacio y nivel | Grupos que usan el tipo en cada franja |
| `CargaDocente` | Minutos asignados, mínimo y máximo, %, días con clase, minutos de hueco |
| `Cambios` | Diferencias respecto al vigente (opcional) |
| `Leyenda` | Asignatura y color |

**Estilo:**
- color por asignatura con texto en contraste;
- recesos en gris combinados;
- encabezados en negrita, bordes finos, texto centrado y ajustado.

**Impresión:**
- horizontal, carta, ajuste 1×1, márgenes de 0,25";
- encabezado con la escuela y la hoja; pie con la fecha y «Página &P de &N».

**Nombres de hoja:** se sanean (`[]:*?/\` → `_`), se recortan a 31 caracteres y los duplicados
llevan « (2)».

### 16.2 PDF (`pdf.py`)
- Con `QPdfWriter`, usando la misma disposición de `dominio/cuadricula.py`.
- Una página por grupo o por profesor (se elige qué incluir) y el reporte de suplencias del día.
- Carta horizontal.

## 17. Interfaz gráfica

Ventana principal (1280×800, recordando tamaño y posición) con barra lateral.

**Menú Archivo:** Nuevo proyecto, Abrir, Importar proyecto anterior…, Guardar como, Restaurar
respaldo…, Proyectos recientes, Salir.

**Edición de formularios:**
- botón **Guardar** e indicador de cambios sin guardar (•);
- al cambiar de pantalla o cerrar con cambios pendientes: «Guardar / Descartar / Cancelar»;
- los errores de pydantic se traducen al español y se muestran junto al campo.

| Pantalla | Contenido |
|---|---|
| **Inicio** | Lista de verificación del proyecto («✔ Niveles · ✔ Plan · ✖ 3 profesores sin disponibilidad») con enlaces; vigente actual; accesos rápidos |
| **Configuración** | Nombre, margen de traslado, descanso mínimo, tiempo límite, hilos, perfil y prioridades de criterios (§9), modo avanzado |
| **Niveles** | Datos del nivel, recesos, eventos, duraciones especiales, huecos de alumnos, preferir titular; **vista previa de franjas** en vivo |
| **Grados y grupos** | Árbol nivel → grado → grupos; titular, bloqueos y **divisiones** del grupo |
| **Asignaturas** | Color, espacio, reglas por defecto y **pestañas por nivel** para sobrescribir; editor de franjas prohibidas y preferidas sobre la cuadrícula del nivel |
| **Plan de estudios** | Matriz grados × asignaturas; total por grado en rojo si no cabe |
| **Clases** | Por grupo: lista de clases (asignatura, destinatarios, profesores, horas, origen). Botones **Sincronizar con el plan**, **Juntar grupos** (clase conjunta), **Dividir** (usar una división), **Asignar profesor** (con la matriz grupos × asignaturas como vista alternativa). Sustituye a «Profesores por grupo». |
| **Profesores** | Activo, datos generales, habilitaciones, eventos, «Puede suplir», cargas, **editor de disponibilidad** |
| **Espacios** | Espacios especiales |
| **Validación** | Problemas con su acción sugerida; doble clic navega al elemento |
| **Generar** | Generar horario · Reajustar vigente · Cancelar; fase, mejor penalización, soluciones, tiempo; diagnóstico con enlaces si es infactible |
| **Editor** | §12 |
| **Resultados** | Selector de solución (★ vigente, estado, origen, ⚠ desactualizada); Marcar vigente, Eliminar, Editar una copia, Resaltar cambios; pestañas por grupo, profesor y espacio, Penalizaciones, Cambios, Carga docente; Exportar a Excel o PDF |
| **Suplencias** | §14 |

**Editor de disponibilidad:**
- cuadrícula de días × intervalos de 5 min entre la hora más temprana y la más tardía de los
  niveles del profesor;
- se arrastra para marcar disponible (verde), preferible no (naranja) o no disponible (gris);
- bandas tenues con las franjas de referencia de cada nivel;
- «Copiar día a toda la semana» y «Limpiar»;
- aviso si un rango deja una franja parcialmente cubierta.

**Vista de horario:** misma disposición que Excel y PDF; color por asignatura; recesos en gris;
escala Δ para profesores multinivel; 📌 en clases bloqueadas, ↻ en negrita en clases
cambiadas, ⚠ en conflictos.

**Concurrencia:**
- `trabajador.py` resuelve en un `QThread` con una **copia** de los datos; la solución se guarda
  en el hilo de la interfaz;
- mientras se resuelve, las pantallas de captura quedan en solo lectura (se puede navegar);
- cerrar la ventana cancela, espera y guarda la mejor solución como `CANCELADO`.

**Accesibilidad:**
- todo se puede hacer con teclado;
- los colores de validez llevan además un ícono, para quien no distingue colores;
- la letra respeta la escala del sistema.

## 18. Línea de comandos

```
timetabling                                         # abre la interfaz
timetabling ejemplo   P.horario [--tamano pequeno|mediano] [--sobrescribir]
timetabling validar   P.horario
timetabling generar   P.horario [--tiempo-limite N] [--hilos N] [--exportar salida.xlsx|.pdf]
timetabling reajustar P.horario [--tiempo-limite N]
timetabling exportar  P.horario --solucion ID --salida salida.xlsx|.pdf
timetabling importar-excel     P.horario cuadro_grupos.xlsx [--mapeo mapeo.json]
timetabling importar-maestros  P.horario cuadro_maestros.xlsx [--con-horarios]
timetabling importar-v6        anterior.horario nuevo.horario
timetabling --version
```

**Ejemplos incluidos:**
- **pequeño:** 5 grupos y 12 profesores;
- **mediano:** 30 grupos (6 de preescolar, 12 de primaria y 12 de secundaria) y 42 profesores;
  preescolar de 45 min, primaria y secundaria de 50 min, recesos distintos, margen de traslado
  de 10 min. El mediano incluye además:
  - una clase conjunta (Ed. Física de 2 grupos);
  - una división (Inglés por nivel en 2 grupos de secundaria);
  - franjas prohibidas (Ed. Física no en la 1.ª hora);
  - un bloqueo de grupo;
  - un profesor multinivel con disponibilidad parcial.

## 19. Empaquetado y publicación

- `empaquetado/construir.py`:
  - genera el ícono (dibujado con Qt → `.icns` / `.ico`);
  - ejecuta PyInstaller en modo **onedir**, sin consola, con `collect_all("ortools")`, e incluye
    `esquema.sql` y los recursos;
  - deja un `.zip` en `dist/`.
- El mismo ejecutable acepta los subcomandos de la CLI (en Windows, adjuntando la consola del
  padre si existe).
- **CI (GitHub Actions):**
  - en cada push: `ruff` y pruebas rápidas en `windows-latest`, `macos-latest` y
    `ubuntu-latest` (esta última con `QT_QPA_PLATFORM=offscreen`);
  - pruebas lentas y de rendimiento en `windows-latest`.
- **Release** al subir una etiqueta `v*`:
  - construye en `windows-latest`, `macos-latest` (arm64) y `macos-13` (Intel);
  - **prueba de humo del ejecutable empaquetado:** `timetabling --version`, luego
    `timetabling ejemplo t.horario --tamano pequeno` y `timetabling generar t.horario
    --tiempo-limite 30`;
  - publica los `.zip`.
- Sin firma de código. El README explica «clic derecho → Abrir» en macOS y «Más información →
  Ejecutar de todas formas» en Windows. La firma queda como mejora futura documentada.

## 20. Pruebas (`pruebas/`)

| Archivo | Cubre |
|---|---|
| `conftest.py` | **Bloquea `socket.socket` y `socket.create_connection` durante toda la suite**; cualquier intento de red falla la prueba |
| `test_cabeceras.py` | Todo `.py` de `src/` y `pruebas/` empieza con «Creado con Claude.»; el README también |
| `test_franjas.py` | Generación, recesos, duraciones especiales, eventos, bloqueos, rejilla Δ, traslapes entre niveles, cliques, disponibilidad con los tres tipos |
| `test_clases.py` | Sincronización con el plan, cobertura, divisiones, clases conjuntas |
| `test_persistencia.py` | Ida y vuelta de todas las entidades, cascadas, `SET NULL`, desactivar profesor en uso, huella de niveles, respaldos, bloqueo de archivo |
| `test_validacion.py` | Cada revisión de §10 con su mensaje |
| `test_conflictos.py` | Cada motivo de §11.2; tiempo por celda en el ejemplo mediano |
| `test_verificador.py` | Soluciones hechas a mano que violan cada restricción D1–D16; modo parcial |
| `test_propiedades.py` | **Hypothesis:** escuelas pequeñas aleatorias → si el resolutor devuelve una solución, el verificador nunca la rechaza; si devuelve INFACTIBLE, el diagnóstico produce un núcleo no vacío o un conflicto estructural |
| `test_resolucion.py` | Ejemplos pequeño y mediano de punta a punta (marca `lento`) |
| `test_rendimiento.py` | Mediano: tiempo hasta la primera solución y tiempo total, contra los umbrales de §2; guarda los tiempos en un JSON como artefacto de CI (marca `rendimiento`) |
| `test_objetivo.py` | Cada criterio B1–B10 en casos mínimos donde se sabe el valor óptimo; B1 y D8 cruzando niveles |
| `test_diagnostico.py` | Caso infactible conocido: el mensaje nombra al profesor y al grupo correctos |
| `test_borrador.py` | Colocar, quitar, intercambiar, pendientes, deshacer y rehacer |
| `test_reparacion.py` | «Colocar y reacomodar»: resultado válido, B9 mínimo, menos de 3 s en el mediano |
| `test_reajuste.py` | Vigente, B9, base desactualizada con mapeo por traslape, comparación por asignación mínima |
| `test_suplencias.py` | Candidatos, orden, ausencias parciales, choque con otra suplencia |
| `test_importacion.py` | Ambos cuadros (con archivos de ejemplo en `pruebas/datos/`), mapeos y alias, horarios como borrador, importación v6 (con un `.horario` v6 real guardado en `pruebas/datos/`) |
| `test_exportacion.py` | Hojas, celdas combinadas, impresión (openpyxl); PDF con el número de páginas esperado |
| `test_gui_*.py` | pytest-qt: flujo completo; cambios sin guardar; editor (arrastrar, colores, intercambio, deshacer, bloquear); generar y cancelar |

```bash
uv run pytest -m "not lento and not rendimiento"
uv run pytest
uv run ruff check src pruebas
```

## 21. Fases de construcción y criterios de aceptación

| Fase | Contenido | Hecho cuando… |
|---|---|---|
| **F0 Esqueleto** | `uv`, `pyproject`, `ruff`, `pytest`, `conftest` sin red, `test_cabeceras`, CI en los 3 sistemas, README inicial, `DECISIONES.md` | CI en verde en Windows, macOS y Linux con una prueba trivial |
| **F1 Dominio y persistencia** | §5, §6 completos, `ejemplo.py` (pequeño y mediano) | `test_persistencia`, `test_clases` en verde; `timetabling ejemplo` crea ambos archivos |
| **F2 Tiempo y validación** | §7, §10 | `test_franjas`, `test_validacion` en verde; `timetabling validar` sobre el mediano sin errores |
| **F3 Modelo duro y verificador** | §8, §11.1 sin objetivo, §11.2 | `test_verificador`, `test_conflictos`, `test_propiedades` en verde; el mediano encuentra una solución factible en menos de 60 s |
| **F4 Objetivo** | §9 | `test_objetivo`, `test_resolucion`, `test_rendimiento` en verde |
| **F5 Diagnóstico** | §11.3 | `test_diagnostico` en verde |
| **F6 GUI de captura** | §17: Inicio, Configuración, Niveles, Grados y grupos, Asignaturas, Plan, Clases, Profesores, Espacios, Validación | Se puede capturar el ejemplo pequeño desde cero solo con la interfaz (prueba pytest-qt) |
| **F7 Generar y Resultados** | Generar, Resultados, exportación Excel, vigente | Flujo «abrir mediano → generar → marcar vigente → exportar» en una prueba pytest-qt |
| **F8 Editor manual** | §12 completo (borradores, panel, colores, intercambio, deshacer, bloquear, completar, reparación, sugerir) | `test_borrador`, `test_reparacion`, `test_gui_editor` en verde; prueba manual descrita en el README |
| **F9 Reajuste y comparación** | §13 | `test_reajuste` en verde |
| **F10 Suplencias** | §11.4, §14 | `test_suplencias` en verde; reporte del día exportado |
| **F11 Importación** | §15 con asistentes en la interfaz | `test_importacion` en verde |
| **F12 PDF y distribución** | §16.2, §19 | Release de prueba (`v0.9.0-rc1`) con los 3 `.zip` y la prueba de humo en verde |

## 22. Supuestos y limitaciones aceptadas

**Supuestos (confirmar con el usuario si hay dudas):**
- Las clases conjuntas solo unen grupos del mismo nivel.
- La disponibilidad por defecto de un profesor nuevo es «toda la jornada».
- Las suplencias no alteran el horario vigente ni la carga docente semanal.

**Limitaciones aceptadas:**
- D9 en el modelo usa cliques con margen de traslado (algo más estricto que la ocupación física
  que comprueba el verificador).
- La validación de capacidad docente es condición necesaria, no suficiente; el diagnóstico cubre
  el resto.
- Si la optimización no termina, las penalizaciones son cotas superiores (se indica en la
  interfaz y en Excel).
- La importación desde Excel depende de cuadros con una estructura parecida a la descrita;
  el mapeo es editable, pero no se aceptan formatos arbitrarios.

---

## Apéndice A. Qué cambia respecto a la versión anterior y por qué

| Problema de la v6 | Solución en v2 | Sección |
|---|---|---|
| Las soluciones guardaban solo índices de franja; editar un nivel cambiaba su significado sin aviso | Instantánea de franjas, huella de niveles, estado «desactualizada», mapeo por traslape | §5.3, §13 |
| Eliminar un profesor borraba sus clases del vigente | Profesores activos/inactivos, copias desnormalizadas, `SET NULL` | §5.3, §6.3 |
| `reemplazar_datos()` borraba todas las soluciones | Respaldo previo obligatorio; las soluciones son instantáneas autocontenidas | §6.4 |
| Si el verificador encontraba violaciones, la solución se perdía | Estado `INVALIDA` con la lista de violaciones | §11.2 |
| Windows sin prueba manual | Windows como plataforma principal; CI y prueba de humo del ejecutable | §2, §19 |
| Riesgo con carpetas sincronizadas | Aviso, `journal_mode=DELETE`, archivo de bloqueo, respaldos | §6.1 |
| Un solo profesor por grupo y asignatura | `Clase` con varios destinatarios y profesores; divisiones | §5.2, D2, D6, D16 |
| Reglas de asignatura globales | Reglas sobrescribibles por nivel | §5.1 |
| Sin franjas prohibidas o preferidas por asignatura | `franjas_prohibidas` (D15) y `franjas_preferidas` (B3) | §5.1, §8, §9 |
| Sin disponibilidad por grupo | `BloqueoGrupo` | §5.1, §7 |
| Preescolar detectado por nombre; B7 específico | `Nivel.preferir_titular` | §5.1, §9 |
| D8 y B1 no cruzaban niveles | Rejilla temporal Δ sobre la línea de tiempo real | §7, §8, §9 |
| Pesos incomparables y difíciles de ajustar | Unidades normalizadas, prioridades y perfiles | §9 |
| B2 ignoraba asignaturas con más horas que días | Penaliza el exceso sobre ⌈h/días⌉ | §9 |
| Diagnóstico por familias poco útil | Refinamiento por entidad con mensajes concretos | §11.3 |
| Comparación emparejaba «en orden» | Asignación de costo mínimo | §13 |
| Suplencias sin fecha ni registro | Ausencias y suplencias persistidas, reportes | §14 |
| Importación solo por CLI, formato rígido; horarios del cuadro descartados | Asistentes en la interfaz, mapeo y alias editables, importar horarios como borrador | §15 |
| No se podía editar un horario a mano | Editor manual con validación en vivo, completar y reparación local | §12 |
| Sin deshacer; cambios sin guardar se podían perder | `QUndoStack` en el editor; aviso de cambios pendientes | §12, §17 |
| Disponibilidad vacía = profesor inutilizable | `disponible_toda_la_jornada` por defecto | §5.1 |
| Redondeo de disponibilidad silencioso | Cuadrícula de 5 min y aviso | §7, §17 |
| Prueba «sin red» solo estática | Bloqueo de sockets en ejecución | §20 |
| Sin prueba de rendimiento ni pruebas aleatorias | `test_rendimiento`, `test_propiedades` (Hypothesis) | §20 |
| `hilos = 8` fijo | `min(8, núcleos)` | §5.1 |
| `Grupo.estudiantes` sin uso | Se mantiene, documentado como informativo | §5.1 |
