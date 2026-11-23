-- Creado con Claude.
-- Esquema actual del proyecto .horario (§6.2). Versión en metadatos.version_esquema.
-- Las horas son minutos desde medianoche; los días, letras L M X J V S D.

CREATE TABLE metadatos (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);

-- Una sola fila; los criterios se guardan como JSON.
CREATE TABLE configuracion (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    datos TEXT NOT NULL
);

CREATE TABLE niveles (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE,
    duracion_min INTEGER NOT NULL,
    inicio_jornada INTEGER NOT NULL,
    fin_jornada INTEGER NOT NULL,
    dias TEXT NOT NULL,
    huecos_alumnos TEXT NOT NULL,
    preferir_titular INTEGER NOT NULL
);

CREATE TABLE recesos (
    nivel_id INTEGER NOT NULL REFERENCES niveles(id) ON DELETE CASCADE,
    orden INTEGER NOT NULL,
    nombre TEXT NOT NULL,
    inicio INTEGER NOT NULL,
    fin INTEGER NOT NULL
);

CREATE TABLE eventos_nivel (
    nivel_id INTEGER NOT NULL REFERENCES niveles(id) ON DELETE CASCADE,
    orden INTEGER NOT NULL,
    nombre TEXT NOT NULL,
    dia TEXT NOT NULL,
    inicio INTEGER NOT NULL,
    fin INTEGER NOT NULL
);

CREATE TABLE duraciones_especiales (
    nivel_id INTEGER NOT NULL REFERENCES niveles(id) ON DELETE CASCADE,
    indice INTEGER NOT NULL,
    minutos INTEGER NOT NULL,
    PRIMARY KEY (nivel_id, indice)
);

CREATE TABLE grados (
    id INTEGER PRIMARY KEY,
    nivel_id INTEGER NOT NULL REFERENCES niveles(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    UNIQUE (nivel_id, nombre)
);

CREATE TABLE grupos (
    id INTEGER PRIMARY KEY,
    grado_id INTEGER NOT NULL REFERENCES grados(id) ON DELETE CASCADE,
    seccion TEXT NOT NULL,
    estudiantes INTEGER NOT NULL,
    titular_id INTEGER REFERENCES profesores(id) ON DELETE SET NULL,
    UNIQUE (grado_id, seccion)
);

CREATE TABLE bloqueos_grupo (
    grupo_id INTEGER NOT NULL REFERENCES grupos(id) ON DELETE CASCADE,
    orden INTEGER NOT NULL,
    nombre TEXT NOT NULL,
    dia TEXT NOT NULL,
    inicio INTEGER NOT NULL,
    fin INTEGER NOT NULL
);

CREATE TABLE divisiones (
    id INTEGER PRIMARY KEY,
    grupo_id INTEGER NOT NULL REFERENCES grupos(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    partes TEXT NOT NULL,
    simultanea INTEGER NOT NULL
);

CREATE TABLE asignaturas (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE,
    color TEXT NOT NULL,
    espacio_requerido TEXT,
    max_horas_dia INTEGER NOT NULL,
    bloque_doble TEXT NOT NULL
);

-- Sobrescritura de reglas por nivel; NULL = hereda.
CREATE TABLE reglas_asignatura_nivel (
    asignatura_id INTEGER NOT NULL REFERENCES asignaturas(id) ON DELETE CASCADE,
    nivel_id INTEGER NOT NULL REFERENCES niveles(id) ON DELETE CASCADE,
    max_horas_dia INTEGER,
    bloque_doble TEXT,
    define_prohibidas INTEGER NOT NULL,
    define_preferidas INTEGER NOT NULL,
    PRIMARY KEY (asignatura_id, nivel_id)
);

-- nivel_id NULL = reglas por defecto de la asignatura.
CREATE TABLE rangos_franjas (
    asignatura_id INTEGER NOT NULL REFERENCES asignaturas(id) ON DELETE CASCADE,
    nivel_id INTEGER REFERENCES niveles(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL CHECK (tipo IN ('prohibida', 'preferida')),
    orden INTEGER NOT NULL,
    dias TEXT NOT NULL,
    desde_indice INTEGER,
    hasta_indice INTEGER,
    desde INTEGER,
    hasta INTEGER
);

CREATE TABLE plan (
    grado_id INTEGER NOT NULL REFERENCES grados(id) ON DELETE CASCADE,
    asignatura_id INTEGER NOT NULL REFERENCES asignaturas(id) ON DELETE CASCADE,
    horas_semanales INTEGER NOT NULL CHECK (horas_semanales > 0),
    PRIMARY KEY (grado_id, asignatura_id)
);

CREATE TABLE profesores (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    activo INTEGER NOT NULL,
    disponible_toda_la_jornada INTEGER NOT NULL,
    carga_max_semanal_min INTEGER NOT NULL,
    carga_max_diaria_min INTEGER NOT NULL,
    carga_min_semanal_min INTEGER NOT NULL,
    max_dias INTEGER,
    max_minutos_continuos INTEGER NOT NULL
);
CREATE UNIQUE INDEX profesores_nombre_activo ON profesores(nombre) WHERE activo = 1;

-- tipo: 'imparte' (habilitación) o 'suplencia' («puede suplir»).
CREATE TABLE profesor_asignaturas (
    profesor_id INTEGER NOT NULL REFERENCES profesores(id) ON DELETE CASCADE,
    asignatura_id INTEGER NOT NULL REFERENCES asignaturas(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL CHECK (tipo IN ('imparte', 'suplencia')),
    orden INTEGER NOT NULL,
    PRIMARY KEY (profesor_id, asignatura_id, tipo)
);

CREATE TABLE profesor_grados (
    profesor_id INTEGER NOT NULL REFERENCES profesores(id) ON DELETE CASCADE,
    grado_id INTEGER NOT NULL REFERENCES grados(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL CHECK (tipo IN ('imparte', 'suplencia')),
    orden INTEGER NOT NULL,
    PRIMARY KEY (profesor_id, grado_id, tipo)
);

CREATE TABLE disponibilidad (
    profesor_id INTEGER NOT NULL REFERENCES profesores(id) ON DELETE CASCADE,
    orden INTEGER NOT NULL,
    dia TEXT NOT NULL,
    inicio INTEGER NOT NULL,
    fin INTEGER NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('disponible', 'preferible_no', 'no_disponible'))
);

CREATE TABLE eventos_profesor (
    profesor_id INTEGER NOT NULL REFERENCES profesores(id) ON DELETE CASCADE,
    orden INTEGER NOT NULL,
    nombre TEXT NOT NULL,
    dia TEXT NOT NULL,
    inicio INTEGER NOT NULL,
    fin INTEGER NOT NULL
);

CREATE TABLE espacios (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE,
    tipo TEXT NOT NULL,
    cantidad INTEGER NOT NULL CHECK (cantidad >= 1)
);

CREATE TABLE alias_importacion (
    id INTEGER PRIMARY KEY,
    texto TEXT NOT NULL UNIQUE,
    asignatura_id INTEGER NOT NULL REFERENCES asignaturas(id) ON DELETE CASCADE
);

CREATE TABLE clases (
    id INTEGER PRIMARY KEY,
    asignatura_id INTEGER NOT NULL REFERENCES asignaturas(id) ON DELETE CASCADE,
    horas_semanales INTEGER NOT NULL CHECK (horas_semanales >= 1),
    sobrescribe_espacio INTEGER NOT NULL,
    espacio_requerido TEXT,
    origen TEXT NOT NULL CHECK (origen IN ('plan', 'manual'))
);

CREATE TABLE clase_destinatarios (
    clase_id INTEGER NOT NULL REFERENCES clases(id) ON DELETE CASCADE,
    orden INTEGER NOT NULL,
    grupo_id INTEGER NOT NULL REFERENCES grupos(id) ON DELETE CASCADE,
    division_id INTEGER REFERENCES divisiones(id) ON DELETE CASCADE,
    parte TEXT
);

CREATE TABLE clase_profesores (
    clase_id INTEGER NOT NULL REFERENCES clases(id) ON DELETE CASCADE,
    orden INTEGER NOT NULL,
    profesor_id INTEGER NOT NULL REFERENCES profesores(id) ON DELETE CASCADE,
    PRIMARY KEY (clase_id, profesor_id)
);

CREATE TABLE asignaciones_fijas (
    id INTEGER PRIMARY KEY,
    clase_id INTEGER NOT NULL REFERENCES clases(id) ON DELETE CASCADE,
    profesor_id INTEGER REFERENCES profesores(id) ON DELETE SET NULL,
    dia TEXT NOT NULL,
    indice_franja INTEGER NOT NULL
);

CREATE TABLE soluciones (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    fecha TEXT NOT NULL,
    estado TEXT NOT NULL,
    origen TEXT NOT NULL,
    tiempo_s REAL NOT NULL,
    penalizaciones TEXT NOT NULL,
    penalizaciones_son_cota INTEGER NOT NULL,
    nota TEXT NOT NULL,
    vigente INTEGER NOT NULL,
    base_id INTEGER REFERENCES soluciones(id) ON DELETE SET NULL,
    huella_niveles TEXT NOT NULL,
    violaciones TEXT NOT NULL
);
CREATE UNIQUE INDEX soluciones_una_vigente ON soluciones(vigente) WHERE vigente = 1;

CREATE TABLE franjas_guardadas (
    id INTEGER PRIMARY KEY,
    solucion_id INTEGER NOT NULL REFERENCES soluciones(id) ON DELETE CASCADE,
    orden INTEGER NOT NULL,
    nivel_id INTEGER REFERENCES niveles(id) ON DELETE SET NULL,
    dia TEXT NOT NULL,
    indice INTEGER NOT NULL,
    inicio INTEGER NOT NULL,
    fin INTEGER NOT NULL
);

CREATE TABLE asignaciones (
    id INTEGER PRIMARY KEY,
    solucion_id INTEGER NOT NULL REFERENCES soluciones(id) ON DELETE CASCADE,
    franja_id INTEGER NOT NULL REFERENCES franjas_guardadas(id) ON DELETE CASCADE,
    clase_id INTEGER REFERENCES clases(id) ON DELETE SET NULL,
    profesor_id INTEGER REFERENCES profesores(id) ON DELETE SET NULL,
    asignatura_nombre TEXT NOT NULL,
    grupos_texto TEXT NOT NULL,
    profesor_nombre TEXT NOT NULL,
    color TEXT NOT NULL,
    bloqueada INTEGER NOT NULL
);
CREATE INDEX asignaciones_solucion ON asignaciones(solucion_id);
CREATE INDEX asignaciones_profesor ON asignaciones(profesor_id);

CREATE TABLE ausencias (
    id INTEGER PRIMARY KEY,
    profesor_id INTEGER NOT NULL REFERENCES profesores(id) ON DELETE CASCADE,
    fecha_inicio TEXT NOT NULL,
    fecha_fin TEXT NOT NULL,
    desde INTEGER,
    hasta INTEGER,
    motivo TEXT NOT NULL
);

CREATE TABLE suplencias (
    id INTEGER PRIMARY KEY,
    fecha TEXT NOT NULL,
    solucion_id INTEGER REFERENCES soluciones(id) ON DELETE SET NULL,
    asignacion_id INTEGER REFERENCES asignaciones(id) ON DELETE SET NULL,
    profesor_ausente_id INTEGER NOT NULL REFERENCES profesores(id) ON DELETE RESTRICT,
    suplente_id INTEGER REFERENCES profesores(id) ON DELETE RESTRICT,
    nota TEXT NOT NULL
);
