# Decisiones de detalle

> Creado con Claude.

Registro de decisiones que la especificación (`ESPECIFICACION_V2.md`) no cubre (§0, regla 3).
Formato: fecha · contexto · decisión · alternativa descartada.

## F0 Esqueleto

### 2026-11-23 · Versión de Python fijada
- **Contexto:** §2 pide Python ≥ 3.13 con `.python-version`.
- **Decisión:** `.python-version = 3.13` y `requires-python = ">=3.13"`. 3.13 tiene ruedas
  publicadas de PySide6, OR-Tools y PyInstaller en los tres sistemas.
- **Descartada:** 3.14, por el riesgo de que alguna dependencia binaria aún no publique ruedas.

### 2026-11-23 · Backend de construcción
- **Contexto:** el `pyproject` necesita un backend para instalar el paquete y el script
  `timetabling`.
- **Decisión:** `hatchling` (solo en tiempo de construcción; no es dependencia de ejecución).
- **Descartada:** `setuptools`, más verboso para el diseño `src/`.

### 2026-11-23 · Todas las dependencias declaradas desde F0
- **Contexto:** las dependencias de §3 se usan a partir de F1–F12.
- **Decisión:** declararlas todas desde F0 para que `uv.lock` y el CI validen desde el principio
  que se instalan en Windows, macOS y Linux.
- **Descartada:** agregarlas fase por fase (detectaría tarde un problema de instalación).

### 2026-11-23 · Forma del bloqueo de red
- **Contexto:** §20 pide bloquear `socket.socket` y `socket.create_connection` durante toda la
  suite.
- **Decisión:** un fixture `autouse` de alcance de sesión en `pruebas/conftest.py` sustituye
  ambos por una función que lanza `RedBloqueadaError` (subclase de `RuntimeError`).
  `pruebas/test_esqueleto.py` comprueba que el bloqueo funciona.
- **Descartada:** el plugin `pytest-socket` (dependencia extra fuera de §3).

### 2026-11-23 · Sin verificador de tipos estático
- **Contexto:** §0 pide código con tipos en todas partes, pero §3 no incluye `mypy` ni `pyright`.
- **Decisión:** anotar todo el código sin agregar un verificador al CI, para no salir de §3.
- **Descartada:** agregar `mypy` al grupo dev (se puede proponer más adelante).

### 2026-11-23 · Pruebas lentas en el CI sin pruebas todavía
- **Contexto:** en F0 no existen pruebas `lento` ni `rendimiento`; pytest devuelve el código 5
  («ninguna prueba recolectada»).
- **Decisión:** el trabajo de Windows trata el código 5 como éxito.
- **Descartada:** omitir el trabajo hasta F4 (el flujo de CI quedaría incompleto).

### 2026-11-23 · Comando sin subcomando
- **Contexto:** §18 dice que `timetabling` sin argumentos abre la interfaz, que llega en F6.
- **Decisión:** hasta F6 imprime un aviso y termina con código 0.
- **Descartada:** mostrar la ayuda (cambiaría el comportamiento esperado más adelante).

## F1 Dominio y persistencia

### 2026-11-23 · Destinatario parcial = división + nombre de la parte
- **Contexto:** §5.2 describe los destinatarios como pares `(grupo_id, parte)`, pero D2 necesita
  saber a qué división pertenece cada parte.
- **Decisión:** `Destinatario(grupo_id, division_id, parte)`; `division_id` y `parte` son ambos
  nulos (grupo completo) o ambos presentes. La parte se identifica por su nombre.
- **Descartada:** identificar la parte por posición (frágil si se reordenan las partes).

### 2026-11-23 · Eventos del profesor
- **Contexto:** §5.1 lista `Profesor.eventos` sin definir su forma; §7.6 habla de «un evento al
  que asiste».
- **Decisión:** `EventoProfesor(nombre, dia, inicio, fin)`: compromisos propios del profesor
  (juntas, cursos) en los que no puede dar clase.
- **Descartada:** referencias a eventos de nivel (los eventos de nivel ya excluyen las franjas
  de todo el nivel).

### 2026-11-23 · Reglas por nivel anidadas en la asignatura
- **Contexto:** §5.1 define `ReglasAsignaturaNivel` con `asignatura_id` y `nivel_id`.
- **Decisión:** en el modelo se guardan dentro de `Asignatura.reglas_por_nivel` (sin
  `asignatura_id`, que es implícito); en la base son la tabla `reglas_asignatura_nivel`. Un campo
  `None` hereda la regla por defecto; una lista vacía de franjas sobrescribe con «ninguna».
- **Descartada:** lista aparte en `DatosEscuela` (la pantalla de Asignaturas las edita juntas).

### 2026-11-23 · Espacio de una clase: herencia explícita
- **Contexto:** `Clase.espacio_requerido` hereda el de la asignatura o lo sobrescribe, incluso
  con «ninguno».
- **Decisión:** `Clase.sobrescribe_espacio: bool` más `espacio_requerido`; `espacio_efectivo()`
  resuelve la herencia.
- **Descartada:** un valor centinela dentro de `espacio_requerido`.

### 2026-11-23 · Una asignación por profesor
- **Contexto:** una clase puede tener varios profesores fijos (D6).
- **Decisión:** `Asignacion` guarda una fila por `(clase, franja, profesor)`. Se agrega
  `bloqueada` (📌 del editor, §12.5). `Asignacion.franja` es la posición en `Solucion.franjas`.
  Se agregan `Solucion.penalizaciones_son_cota` (§11.1) y `Violacion(restriccion, mensaje,
  clase_id)`.
- **Descartada:** una fila por franja con una lista de profesores (complica `SET NULL`).

### 2026-11-23 · Versión del esquema en `metadatos`
- **Contexto:** §6.2 detecta los archivos v6 por su tabla `esquema_version`.
- **Decisión:** la v2 guarda `aplicacion` y `version_esquema` en una tabla `metadatos`, sin
  tabla `esquema_version`. La configuración es una fila JSON en `configuracion`.
- **Descartada:** `PRAGMA user_version` (menos explícito al inspeccionar el archivo).

### 2026-11-23 · Unicidad
- **Decisión:** únicos el nombre de nivel, asignatura, espacio y alias; grado por nivel; sección
  por grado; nombre de profesor entre activos (índice parcial). Solo una solución vigente
  (índice parcial).

### 2026-11-23 · Clases sin destinatarios tras un borrado
- **Contexto:** borrar un grupo o una división borra en cascada sus destinatarios.
- **Decisión:** en la misma transacción se borran las clases que quedan sin destinatarios. Una
  clase conjunta conserva sus otros grupos.

### 2026-11-23 · Profesores referenciados por suplencias
- **Decisión:** un profesor que aparece en una suplencia (ausente o suplente) tampoco se puede
  eliminar (FK `RESTRICT`); como en §6.3, se ofrece desactivarlo.

### 2026-11-23 · `reemplazar_datos` empareja por id
- **Contexto:** en la v6 `reemplazar_datos()` borraba todas las soluciones.
- **Decisión:** se conservan las soluciones; las entidades se emparejan por id (las que faltan se
  borran; los profesores en uso que faltan se desactivan). Todas las entidades deben traer id.
  Siempre hay respaldo previo si el archivo tenía datos.

### 2026-11-23 · Cuándo un borrado en cascada respalda
- **Decisión:** `N = 20` filas afectadas (`UMBRAL_RESPALDO_CASCADA`). Borrar una solución
  siempre respalda. `afectados_por_eliminar()` simula el borrado dentro de un punto de guardado
  y lo revierte, así cuenta exactamente lo que haría la cascada.

### 2026-11-23 · Archivo de bloqueo y carpetas sincronizadas
- **Decisión:** el módulo `persistencia/archivo.py` (no listado en §4) contiene la detección y el
  bloqueo. Un bloqueo de otro equipo siempre se considera vigente; uno de este equipo, solo si su
  proceso sigue vivo (en Windows se consulta con `OpenProcess`, porque `os.kill(pid, 0)`
  terminaría el proceso). Si el bloqueo es ajeno y vigente, no se sobrescribe ni se borra al
  cerrar.
- **Detección:** por nombres de ruta (OneDrive, Dropbox, Google Drive/Mi unidad, iCloud/Mobile
  Documents, CloudStorage), rutas UNC y, en Windows, `GetDriveTypeW == DRIVE_REMOTE`.

### 2026-11-23 · Nombres de respaldo en el mismo segundo
- **Decisión:** si ya hay respaldos en el mismo segundo se agrega `-1`, `-2`…, siempre mayor que
  el más alto existente, para que la poda no reutilice un nombre y el orden se mantenga.

### 2026-11-23 · Ejemplos
- **Decisión:** `--tamano` vale `pequeno` por defecto. `--sobrescribir` respalda el archivo
  existente en `.respaldos/` antes de reemplazarlo.
  - Pequeño: primaria de 5 grupos (1°A–5°A) y 12 profesores por asignatura.
  - Mediano: preescolar K1–K3 × A/B (45 min, con titular), primaria 1°–6° × A/B (50 min, con
    titular y hora cívica), secundaria 7°–9° × A–D (50 min). Clase conjunta: Ed. Física de
    9°C+9°D. División: Inglés por nivel en 8°A y 8°B. Bloqueo: 6°B los viernes de 13:00 a 13:50.
    Profesora multinivel con disponibilidad parcial: Sara Kim (inglés de preescolar y 1°–3°,
    de 08:00 a 12:30). Espacios: cancha (2) y taller (1).

## F2 Tiempo y validación

### 2026-11-23 · Interpretación de D2 con divisiones
- **Contexto:** D2 dice que «las partes de una misma división pueden coincidir».
- **Decisión:** pueden coincidir partes **distintas** de una división **simultánea**. La misma
  parte no puede estar en dos clases a la vez, y las partes de una división no simultánea no se
  empalman. Para las horas del grupo (§10) se cuenta: grupo completo + por cada división
  simultánea el máximo de sus partes (o la suma si no es simultánea).
  `validacion.chocan_destinatarios()` implementa la regla.
- **Descartada:** dejar que dos clases de la misma parte coincidan (los alumnos estarían en dos
  lugares).

### 2026-11-23 · Rangos de franjas por hora
- **Decisión:** una franja **prohibida** por horas basta con que toque el rango; una franja
  **preferida** por horas debe quedar completa dentro del rango («Matemáticas antes de las
  11:00»). Por índices se usa `desde ≤ índice ≤ hasta` (inclusive, desde 0).
- **Descartada:** el mismo criterio para ambos (sería demasiado laxo o demasiado estricto).

### 2026-11-23 · Rejilla Δ
- **Decisión:** Δ = mcd de los límites de todas las franjas generadas, los recesos, el margen de
  traslado y el descanso mínimo; si sale menor que 5 se usa 5, y una franja cubre todo tick que
  toque. `max_minutos_continuos` no entra en el mcd (D8 lo redondea hacia abajo en ticks).

### 2026-11-23 · Disponibilidad «preferible no» sin toda la jornada
- **Decisión:** sin `disponible_toda_la_jornada`, los rangos `preferible_no` también permiten
  dar clase (con penalización B4); se fusionan con los `disponible`.

### 2026-11-23 · Minutos de una clase para cargas y capacidad
- **Decisión:** en la validación, los minutos de una clase son `horas × duracion_min` del nivel
  (sin duraciones especiales, que dependen de dónde caiga la clase). La capacidad de un profesor
  en un nivel es `min(carga máxima, minutos de franjas útiles válidas para él)`; un profesor
  habilitado en varias asignaturas cuenta completo en cada una (condición necesaria, §22).

### 2026-11-23 · Revisión adicional de destinatarios
- **Decisión:** además de §10, es error que una clase use una división de otro grupo o una parte
  que no existe en la división.

### 2026-11-23 · Capa de servicios y código de salida de `validar`
- **Decisión:** `servicios/proyecto.py` carga y valida; la CLI solo presenta. `timetabling
  validar` termina con 0 sin errores, 1 con errores y 2 si el archivo no se pudo abrir.

## F3 Modelo duro y verificador

### 2026-11-23 · `Colocacion` y `Borrador` mínimos desde F3
- **Contexto:** `conflictos.motivos(datos, borrador, …)` necesita un horario editable, que §12 y
  F8 completan.
- **Decisión:** `dominio/borrador.py` define ya `Colocacion(clase_id, franja_id, profesores,
  bloqueada)` y un `Borrador` con lo básico; F8 agrega intercambio, deshacer y lo demás. El
  resolutor, el verificador y los conflictos trabajan con colocaciones; la conversión a
  `Solucion` (franjas guardadas y copias desnormalizadas) se hace en servicios (F4/F7).

### 2026-11-23 · `Conflictos` como índice incremental
- **Decisión:** `nucleo/conflictos.py` expone la clase `Conflictos` (índices por grupo, profesor,
  asignatura y tipo de espacio, con `agregar`/`quitar`) y `motivos()` como atajo. El verificador
  agrega las colocaciones una por una y revisa cada una contra las anteriores, así cada
  violación se informa una sola vez. Medido en el mediano: 0,04 ms por celda.
- Sin profesor indicado, `motivos()` usa el que ya imparte la clase; si no hay, el único
  candidato; si hay varios, el candidato libre con menos motivos, o informa «Ningún profesor
  posible está libre» con los primeros motivos de cada uno.

### 2026-11-23 · D8 exacto en minutos
- **Decisión:** `max_minutos_continuos` de los profesores activos entra al mcd de Δ. El modelo
  y el verificador revisan las mismas ventanas de `M + P` minutos: las que empiezan al inicio de
  una franja y las que terminan al final de una (el máximo siempre se alcanza en una de ellas).
  El modelo usa una variable entera `o[p,s]` por profesor y franja para no repetir sumas.
- **Familia:** D8 se registra en la familia `carga` (con D7); `continuidad` es D6.

### 2026-11-23 · Un solo candidato = profesor fijo
- **Decisión:** si una clase sin profesores fijos tiene un único candidato posible, el modelo lo
  trata como fijo (sin variables `y` ni `x` propias). Las franjas de una clase se podan a las
  que son válidas para al menos un candidato (o para todos los fijos).

### 2026-11-23 · Estado de una solución de la etapa 1
- **Decisión:** en F3 (sin objetivo) una solución encontrada se informa como `FACTIBLE`; F4
  distinguirá `OPTIMO` al terminar la etapa 2. Cancelar antes o durante la búsqueda devuelve
  `CANCELADO` (con la mejor solución si la había).

### 2026-11-23 · Segunda propiedad de `test_propiedades`
- **Contexto:** §20 pide además que un INFACTIBLE produzca un núcleo de diagnóstico, pero el
  diagnóstico es F5.
- **Decisión:** en F3 la prueba cubre «el verificador acepta lo que resuelve el modelo» (60
  escuelas aleatorias por corrida; una corrida de 600 no encontró contraejemplos). La propiedad
  del diagnóstico se agrega en F5.

### 2026-11-23 · `test_resolucion` desde F3
- **Decisión:** se crea en F3 para medir el criterio «el mediano encuentra una solución factible
  en menos de 60 s» (marca `lento`; hoy tarda ~1,5 s). F4 lo amplía con la optimización.

## F4 Objetivo

### 2026-11-23 · Escala entera del objetivo
- **Decisión:** el objetivo de CP-SAT es entero: cada unidad con peso 1 vale 5000; los criterios
  por minuto (B1, B6) valen 100 por minuto (una unidad = 50 min). Así los pesos avanzados admiten
  dos decimales. `Progreso.mejor_objetivo` y la penalización total se informan en unidades.

### 2026-11-23 · Penalizaciones informadas = evaluación sin solver
- **Contexto:** si la etapa 2 no termina, algunas variables auxiliares del modelo pueden no estar
  ajustadas (por ejemplo, las de «antes de la primera clase» de B1).
- **Decisión:** las penalizaciones que se guardan se calculan con `objetivo.evaluar()`, que no
  usa el solver (la misma función servirá para el editor). En el óptimo, el modelo y la
  evaluación coinciden criterio por criterio; una prueba lo comprueba con los tres perfiles.
  La solución guarda además `total`, la suma ponderada.

### 2026-11-23 · Definiciones de detalle de los criterios
- **B1:** la línea de tiempo del profesor se parte en segmentos entre los límites de sus franjas
  y de los recesos; un segmento libre entre la primera y la última clase cuenta, salvo que caiga
  dentro del receso de un nivel en el que da clase ese día.
- **B2:** `días lectivos` = días con franjas útiles comunes a los grupos de la clase.
- **B6:** por asignatura y nivel con al menos dos profesores posibles, máximo − mínimo de los
  minutos que cada uno imparte **de esa asignatura en ese nivel** (incluye a quienes quedan en 0).
  Se descartó usar la carga total del profesor, que mezclaría asignaturas.
- **B7:** se cuenta por grupo destinatario: una clase conjunta sin el titular de uno de sus
  grupos cuenta 1 por cada grupo afectado.
- **B9:** `2 − z − x` por ocurrencia de la base (moverla, 2; cambiar solo el profesor, 1). Si la
  franja de la base ya no es posible, cuesta 2 fijo y no restringe nada.
- **B10:** franjas útiles libres del grupo entre su primera y su última clase del día.

### 2026-11-23 · Estados al optimizar
- **Decisión:** `OPTIMO` si la etapa 2 demuestra el óptimo (o si no hay criterios activos);
  `FACTIBLE` con `penalizaciones_son_cota = True` si se acabó el tiempo; `CANCELADO` conserva la
  mejor solución encontrada. Las pistas de la etapa 2 son una por variable (en las clases con
  profesores fijos, `x` y `z` son la misma variable y repetirla invalida el modelo).

### 2026-11-23 · Comando `generar` desde F4
- **Decisión:** `timetabling generar` (§18) ya valida, resuelve, verifica y guarda la solución
  (`servicios/generacion.py`). Si el verificador encuentra violaciones, se guarda como
  `INVALIDA` con la lista. Si no hay horario (INFACTIBLE, sin solución en tiempo), no se guarda
  nada y el comando termina con código 1. La opción `--exportar` llega con la exportación (F7).
- **Conversión:** `servicios/soluciones.py` arma la `Solucion` con la instantánea de **todas** las
  franjas generadas de todos los niveles y una asignación por profesor.

### 2026-11-23 · Prueba de rendimiento
- **Decisión:** `test_rendimiento` resuelve el mediano con 4 hilos y límite de 280 s; exige
  primera solución < 60 s y total < 300 s, y escribe `rendimiento.json` (artefacto del CI).

## F5 Diagnóstico

### 2026-11-23 · Disponibilidad y franjas prohibidas como familias del diagnóstico
- **Contexto:** en el modelo normal, D5 (disponibilidad) y D15 (franjas prohibidas) se aplican
  podando variables, así que no pueden aparecer en un núcleo; pero §11.3 pone como ejemplo «la
  disponibilidad de López».
- **Decisión:** en el modelo de diagnóstico no se poda: D5 y D15 se agregan como restricciones
  de las familias `disponibilidad` (entidad `profesor:p`) y `prohibidas` (entidad
  `asignatura:a`). El modelo normal sigue podando.

### 2026-11-23 · Filtro de eliminación sin literales
- **Contexto:** con suposiciones, CP-SAT trata las restricciones como condicionadas y su
  relajación lineal es débil: demostrar que un subconjunto es infactible podía tardar 8 s aun
  en el ejemplo pequeño.
- **Decisión:** cada núcleo se **extrae** como pide §11.3 (suposiciones, un hilo,
  `sufficient_assumptions_for_infeasibility`), pero el filtro de eliminación reconstruye el
  modelo con solo las restricciones del subconjunto, sin literales (`ConstructorModelo(...,
  activas=...)`), y lo resuelve con los hilos de la configuración. En el refinamiento por
  entidad, si el núcleo con suposiciones no sale en 3 s, el filtro parte de todas las entidades
  de las familias del núcleo. Resultado en el ejemplo pequeño: de 28 s a 7,7 s, con el mismo
  núcleo mínimo.
- **Descartada:** usar varios hilos con suposiciones (no ayudaba: el cuello de botella es la
  relajación débil, y con varios hilos CP-SAT no da el subconjunto suficiente).

### 2026-11-23 · Corte para `max_dias`
- **Decisión:** con `max_dias`, además de `Σ días ≤ max_dias` se agrega por día
  `minutos ≤ tope_diario × día_con_clase` (familia `carga`). Es redundante pero refuerza la
  relajación lineal, en el modelo normal y en el diagnóstico.

### 2026-11-23 · Mensajes y enlaces
- **Decisión:** cada elemento del núcleo se traduce a una frase con la entidad concreta («los
  límites de carga de Ana», «las 2 horas de Matemáticas de 1°A», «la capacidad de los espacios
  de tipo «cancha»») y a un `Enlace(entidad, id, texto)` para que la interfaz navegue. Si el
  núcleo queda vacío, se informa un conflicto estructural. Si se agota el presupuesto, el
  mensaje lo dice (`minimo = False`).
- **Integración:** `generar` diagnostica solo si el resultado es INFACTIBLE (60 s por defecto;
  la interfaz usará 30 s) y la línea de comandos imprime el mensaje y los enlaces.

## F6 GUI de captura

### 2026-11-23 · `SesionProyecto` entre la interfaz y el repositorio
- **Decisión:** `servicios/sesion.py` (sin Qt) mantiene el proyecto abierto, cachea los datos,
  avisa a los observadores cuando cambian y hace las operaciones compuestas en una transacción:
  sincronizar clases, guardar un grupo con sus divisiones, juntar y dividir clases, guardar
  varias celdas del plan. También calcula la lista de verificación de Inicio.

### 2026-11-23 · Diálogos intercambiables
- **Decisión:** todos los diálogos (guardar/descartar/cancelar, confirmar, elegir, rutas) pasan
  por `gui/dialogos.py`; las pruebas usan `DialogosFalsos` con respuestas programadas. Las
  pruebas corren con `QT_QPA_PLATFORM=offscreen` y preferencias en una carpeta temporal
  (`TIMETABLING_CONFIG`).

### 2026-11-23 · Reglas de asignatura en la interfaz
- **Decisión:** la pestaña «Por defecto» usa una cuadrícula genérica de índices (vale para
  todos los niveles); cada nivel tiene su pestaña con la casilla «Usar reglas propias en este
  nivel», que sobrescribe las cuatro reglas a la vez (el modelo permite sobrescribir campo por
  campo; la interfaz lo simplifica). La cuadrícula guarda un rango por índice por tramo
  consecutivo de cada día; si no se toca, conserva los rangos originales (también por horas).

### 2026-11-23 · Acciones inmediatas en Clases
- **Decisión:** en Clases cada acción (sincronizar, nueva clase, juntar, dividir, asignar
  profesor, cambiar horas, eliminar) se guarda al instante; no hay botón Guardar. «Juntar
  grupos» une clases de la misma asignatura en grupos del mismo nivel y conserva horas y
  profesores de la clase elegida. «Dividir» crea una clase por parte con las mismas horas.

### 2026-11-23 · Divisiones en Grados y grupos
- **Decisión:** las divisiones se editan como filas del grupo («Partes» separadas por coma);
  quitar una fila elimina la división (y en cascada las clases que la usaban).

### 2026-11-23 · «Importar proyecto anterior…»
- **Decisión:** el menú existe pero queda desactivado hasta F11. Abrir un archivo v6 avisa que
  debe importarse.

## F7 Generar y Resultados

### 2026-11-24 · Disposición desde la solución guardada
- **Decisión:** `dominio/cuadricula.py` arma las cuadrículas desde la `Solucion` guardada (sus
  franjas y copias desnormalizadas). Los grupos de cada clase salen de los datos actuales si la
  clase existe; si se borró, del texto guardado («7°A, 7°B», «8°A (Básico)»). Así una solución
  desactualizada o con entidades borradas sigue legible.
- Las filas de los recesos se deducen de los huecos entre franjas consecutivas guardadas.
- Varias clases en la misma celda (partes de una división) van una por línea:
  «Inglés (Básico) · Wendy Park».
- Profesor multinivel: filas de Δ minutos (mcd de los límites de sus niveles, mínimo 5) con
  celdas combinadas según la duración real; en Excel y en la interfaz se rotula cada media hora.

### 2026-11-24 · Carga docente
- **Decisión:** minutos de hueco = minutos entre la primera y la última clase del día que no son
  clase ni receso de un nivel en el que el profesor da clase ese día (como B1).

### 2026-11-24 · Hojas de Excel
- **Decisión:** las hojas de grupo y profesor se nombran con el nombre visible; las de espacio,
  «tipo - Nivel». La hoja `Cambios` solo aparece si se pasan cambios (los calcula el reajuste,
  F9). El encabezado usa `&A` (nombre de la hoja) y el pie la fecha de exportación.
- **Nota:** XlsxWriter no escribe `fitToWidth`/`fitToHeight` cuando valen 1 (es el valor por
  defecto de OOXML); el ajuste a una página queda activado con `fitToPage`.

### 2026-11-24 · Exportar a PDF y botones de fases siguientes
- **Decisión:** «Exportar a PDF», «Editar una copia», «Resaltar cambios» y «Reajustar vigente»
  aparecen desactivados con una nota de la fase en que llegan (F12, F8, F9). La línea de
  comandos responde con un error claro si se pide `.pdf`.

### 2026-11-24 · Generación en segundo plano
- **Decisión:** `gui/trabajador.py` resuelve en un `QThread` con una copia de los datos
  (`servicios.generacion.generar_en_memoria`) y la solución se guarda en el hilo de la
  interfaz. `terminado` detiene el hilo con conexión directa: al cerrar la ventana, el hilo de
  la interfaz espera al trabajador y una conexión en cola se bloquearía hasta el tiempo límite.
  El diagnóstico desde la interfaz usa 30 s (§11.3).
- Mientras se resuelve, las pantallas de captura quedan desactivadas (se puede navegar);
  Validación, Generar, Resultados e Inicio siguen activas, y no se puede abrir otro proyecto.
- Las asignaciones fijas solo vienen de los datos hasta F8 (luego también de las clases
  bloqueadas del editor).

## F8 Editor manual

### 2026-11-24 · Operaciones reversibles del borrador
- **Decisión:** toda edición es una `Operacion` (colocaciones que se quitan y que se ponen) con
  `inversa()`; el `QUndoStack` solo envuelve operaciones. Mover, intercambiar, bloquear,
  cambiar profesor y aceptar una reparación son operaciones de este tipo. Cambiar el profesor
  cambia **todas** las ocurrencias de la clase (continuidad, D6).
- Cada operación se guarda al instante reescribiendo la solución borrador en una transacción
  (las asignaciones de un borrador no tienen suplencias que conservar).

### 2026-11-24 · Horas por clase en el modelo
- **Contexto:** la reparación trabaja sobre borradores incompletos; con D1 = horas semanales,
  las clases fijas a medio colocar volverían infactible el modelo.
- **Decisión:** `ConstructorModelo(horas=…)` / `OpcionesResolucion.horas` permiten fijar cuántas
  horas debe tener cada clase; la reparación conserva las que ya tiene cada clase (+1 para la
  que se coloca).

### 2026-11-24 · Vecindario de la reparación
- **Decisión:** el vecindario del día son las clases con alguna colocación ese día que
  comparten grupo, profesor o tipo de espacio con la clase movida; esas clases quedan libres
  en toda la semana. El intento con ese vecindario tiene un plazo total de 3 s (§12.4): la
  búsqueda recibe lo que queda tras preparar el modelo, menos 0,5 s de margen; si no hay
  solución, se
  amplía a todas las clases de esos grupos y profesores (5 s). Las bloqueadas no se mueven
  nunca.
- **Dominios reducidos:** las clases con todas sus horas fijadas (las de fuera del vecindario)
  solo reciben variables para esas franjas y profesores. El modelo de la reparación pasa de
  decenas de miles de variables a unos pocos cientos: en el mediano, de ~1,3 s a ~0,5 s (el
  runner de Windows llegaba a 3,7 s con el modelo completo).

### 2026-11-24 · Interacción en la rejilla
- **Decisión:** clic en una clase la toma; clic en otra celda la suelta ahí; también se
  arrastra. Alt+flechas mueve la clase seleccionada; Supr la devuelve al panel; Ctrl+L
  bloquea; Ctrl+Z / Ctrl+Y deshacen y rehacen; doble clic cambia el profesor. Al soltar en una
  celda inválida ocupada por una sola clase, si el intercambio deja ambas válidas se ofrece
  «Intercambiar»; si no, «Colocar y reacomodar lo mínimo» (con vista previa). En modo
  flexible se ofrece colocarla con conflictos (queda marcada con ⚠).
- Al soltar una tarjeta de una clase sin profesor se elige entre los candidatos válidos en el
  orden de §11.4 (sin «preferible no», menos clases ese día, nombre).
- Las vistas por profesor y espacio y la vista maestra muestran un nivel a la vez (las celdas
  son franjas de ese nivel). «Buscar suplente…» queda desactivado hasta F10.

### 2026-11-24 · «Completar el resto» y fijas al generar
- **Decisión:** el cálculo corre en otro hilo con una copia de los datos; el nuevo borrador se
  guarda en el hilo de la interfaz (SQLite no admite usar la conexión desde otro hilo). Las
  señales de las tareas en segundo plano se conectan a métodos de la pantalla (un `QObject`),
  no a lambdas: en PySide, una lambda sin receptor se ejecutaría en el hilo del trabajador.
- **Borrador de trabajo (§12.5):** al generar, las clases bloqueadas del borrador más reciente
  que tenga bloqueadas (o, si no hay, del vigente) entran como fijas; Generar indica cuántas y
  de qué borrador vienen.

### 2026-11-24 · Copias de soluciones desactualizadas
- **Decisión:** una solución desactualizada (huella de niveles distinta) no se copia todavía:
  la «copia ajustada» necesita el mapeo por traslape del reajuste (F9).

### 2026-11-24 · Ancho mínimo de la ventana
- **Decisión:** la ventana debe caber en una laptop de 1024 px de ancho (en macOS las fuentes la
  ensanchan hasta ~860 px); una prueba lo vigila. Las filas de botones largas se reparten en
  dos.

## F9 Reajuste y comparación

### 2026-11-24 · Comparación en tiempo real con asignación mínima propia
- **Decisión:** `dominio/comparacion.py` compara dos soluciones guardadas. Las clases se
  identifican por `clase_id` o, si se borró, por asignatura + grupos (texto guardado); las
  ocurrencias se comparan por día, inicio y fin (así funciona con soluciones desactualizadas) y
  por el conjunto de profesores. El emparejamiento usa un método húngaro propio (el dominio no
  depende de OR-Tools); se verificó contra fuerza bruta en matrices rectangulares aleatorias.
- «Clases afectadas» cuenta las clases con algún cambio; «profesores afectados», los que
  aparecen antes o después en una ocurrencia que cambió.

### 2026-11-24 · Mapeo de una solución guardada
- **Decisión:** `servicios.soluciones.mapear_solucion` lleva una solución a las clases y
  franjas actuales: misma franja si la huella coincide; si no, la de mayor traslape del mismo
  día y nivel (en empate, la de menor índice). Dos ocurrencias que caerían en la misma franja de
  la misma clase: la segunda queda «sin correspondencia». Los profesores que ya no existen se
  quitan de la colocación. Se usa en el reajuste y en las copias ajustadas del editor (§5.3:
  una solución desactualizada se edita como «Copia ajustada de …»).

### 2026-11-24 · Pista completa desde la base
- **Contexto:** reajustar un vigente sin cambios en los datos producía cientos de cambios: la
  pista solo fijaba dónde ocurría cada clase y no quién la daba, y la primera solución se
  alejaba de la base sin que la optimización alcanzara a volver.
- **Decisión:** la pista de la base incluye también `x` (profesor en cada franja) e `y`
  (profesor a cargo). Ahora un reajuste sin cambios da 0 cambios.

### 2026-11-24 · Con qué se compara una solución
- **Decisión:** con la solución de la que partió (`base_id`: reajustes, copias, completados) o,
  si no tiene, con el vigente (si es otra). Resultados muestra el resumen, la pestaña Cambios y
  «Resaltar cambios» (↻ en negrita); la hoja `Cambios` de Excel aparece cuando hay con qué
  comparar. El reajuste no se marca vigente solo: el usuario lo revisa y lo marca.

### 2026-11-24 · Suplencias: qué ocupa a un candidato
- **Decisión:** el candidato no debe tener, ese día, clase del vigente ni otra suplencia que se
  le cruce; el margen de traslado se aplica solo entre niveles distintos (igual que D9). Si el
  candidato tiene una ausencia que toca esa fecha y hora, no aparece; y las clases de un
  profesor ausente en esa fecha no lo ocupan. Se trabaja con las horas guardadas de la
  solución (día, inicio, fin), así sirve aunque el vigente esté desactualizado.
- «Titular» = habilitado para la asignatura y **todos** los grados de la clase; «suplente» =
  marcado en `suplencia_asignaturas` y `suplencia_grados` para ellos. Los inactivos no cuentan.
- Orden (§11.4): titular, sin «preferible no», menos clases y suplencias ese día, menos
  suplencias en el mes (del suplente, por fecha de la suplencia), nombre.

### 2026-11-24 · Suplencias: registro y conteo
- **Decisión:** una suplencia se identifica por (fecha, asignación del vigente); asignar de
  nuevo la misma clase reemplaza el registro. «Sin cubrir» es una suplencia con
  `suplente_id` nulo; «Quitar» la borra y la clase vuelve a «Pendiente». Las clases afectadas
  se calculan cada vez desde las ausencias y el vigente (no se guardan).
- Eliminar una ausencia borra las suplencias de sus clases que ya no tengan otra ausencia que
  las justifique.
- Conteo mensual: por profesor, **suplencias realizadas** (como suplente), **sus clases
  cubiertas** por otros y **sus clases sin cubrir**. Las pendientes no cuentan.
- La asignación «con un clic» (§14): el mejor candidato queda preseleccionado y basta pulsar
  «Asignar» (o doble clic en otro candidato).
- «Buscar suplente…» del editor lista, sin fecha, quién podría cubrir la clase en esa franja
  según el borrador actual; las suplencias con fecha se registran en la pantalla Suplencias.
- El reporte del día en **PDF** llega con F12 (`pdf.py`, §16.2); en F10 se exporta a Excel
  (una hoja carta horizontal ajustada a una página).

### 2026-11-24 · Importación: datos de prueba sintéticos
- **Decisión (consultada):** `pruebas/datos/` guarda un `.horario` con el **esquema v6 real**
  (versión 6, todas sus tablas) pero con una escuela inventada, y dos cuadros de Excel con el
  mismo horario. No se publica el proyecto real de la escuela (el repositorio es público). Los
  tres archivos los genera `pruebas/datos/generar_datos.py` desde un único horario semanal.

### 2026-11-24 · Importación: arquitectura
- **Decisión:** `importacion/` lee los archivos y calcula el resultado como datos puros (una
  copia de `DatosEscuela` con ids nuevos, el resumen y los avisos); usa `nucleo.franjas` para
  conocer las franjas. `servicios/importacion.py` lo aplica: respaldo y, en **una**
  transacción, `reemplazar_datos` (que gana el parámetro `respaldo`) y los borradores o
  soluciones. Si algo falla, no queda nada a medias.
- La importación de un cuadro **sincroniza las clases** con el plan importado (crea las de
  grupo completo que falten), porque el cuadro de maestros fija profesores sobre ellas.

### 2026-11-24 · Cuadro de horarios (§15.1)
- Hojas → grados por nombre («1st», «1°», «primero», «kinder»); el asistente permite elegir un
  grado existente, **crear uno nuevo** en un nivel u omitir la hoja.
- Días en inglés o español. Sección: última letra de la etiqueta si la hoja tiene varios
  grupos; si no, A, B, C… por orden.
- Textos → asignaturas: alias guardado, asignatura del mismo nombre (sin acentos ni
  mayúsculas), variante conocida o el propio texto. Lo que se mapea a otro nombre se guarda
  como `AliasImportacion` (sin distinguir mayúsculas). «(ignorar)» descarta la celda.
- Recesos y tutorías: listas de palabras editables en el mapeo; no cuentan.
- Plan por grado: el valor más frecuente entre sus grupos (el mayor si empatan), con aviso.
  El plan de los grados importados se **reemplaza** (el resumen dice qué cambia o se quita).
- Hora cívica: celdas vacías celestes → evento del nivel, si no se cruza con uno existente.
- `--mapeo` de la línea de comandos usa el mismo JSON que `--guardar-mapeo` escribe.

### 2026-11-24 · Cuadro de maestros (§15.2)
- Títulos normalizados (Ms., Mr., Mrs., Miss, Prof., Profa., Mtro., Mtra.) y conservados en el
  nombre; al comparar con los profesores existentes se ignoran (y los acentos). Un profesor
  inactivo que aparece en el cuadro se reactiva.
- Grupos en las celdas: número de grado (o «PP» prepa, «K» kínder) + sección A–H.
- Cada (grupo, asignatura) queda con el maestro que más sesiones da (aviso si hay varios); las
  clases de ese grupo reciben ese profesor fijo. Los profesores nuevos quedan disponibles toda
  la jornada.
- «Importar también los horarios como borrador»: la hora sale de la columna de horas del
  bloque (o del texto de la celda); cada celda va a la franja de mayor traslape del nivel del
  grupo (en empate, la de menor índice). El borrador es `BORRADOR`, origen `importado`.
- Los bloques cuyo nombre contiene «biblioteca» o «library» se proponen como «(omitir)».

### 2026-11-24 · Proyecto v6 (§15.3)
- Pesos → perfil más cercano por el **ángulo** entre el vector de pesos v6 (B1–B8) y los
  multiplicadores de cada perfil; los pesos v6 se guardan como pesos avanzados (sin activar el
  modo avanzado). B10 no existía: recibe el multiplicador del perfil escalado a los pesos v6.
- `sin_huecos_alumnos` → huecos de alumnos «prohibidos» (si no, «penalizar»).
- `exigente` → franja preferida desde el inicio hasta la mitad de la jornada (redondeada a
  5 min) en cada nivel donde se da la asignatura.
- `max_consecutivas` → `max_minutos_continuos` = clases × la duración más larga de los niveles
  del profesor. Un profesor v6 **sin rangos** de disponibilidad se importa disponible toda la
  jornada (en la v6 no podía dar clase) y se avisa.
- Eventos a los que asistía un profesor → eventos propios del profesor (nombre + nivel).
- Las soluciones se reconstruyen con las franjas actuales y se verifican con las reglas v2:
  la que no las cumple se importa como `INVALIDA` y, si era la vigente, no se marca (se
  avisa). Las penalizaciones se recalculan con los criterios v2.
- También se leen las versiones 1–5 del esquema anterior (sin eventos, suplencias ni
  docentes asignados).
- Abrir un archivo v6 ofrece importarlo; el proyecto nuevo se abre al terminar.

### 2026-11-24 · Asistentes en la interfaz
- **Archivo → Importar proyecto anterior…, Importar cuadro de horarios (Excel)…, Importar
  cuadro de maestros (Excel)…** (estos dos, con un proyecto abierto). El resumen previo se
  calcula sin tocar el archivo; «Aplicar» guarda.

