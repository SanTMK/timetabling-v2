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
