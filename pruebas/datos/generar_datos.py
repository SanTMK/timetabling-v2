"""Creado con Claude.

Genera los archivos de ejemplo de la importación (§15) con datos inventados:

- `cuadro_grupos.xlsx`: cuadro de horarios por grado (una hoja por grado, un bloque por grupo);
- `cuadro_maestros.xlsx`: cuadro de maestros (un bloque por maestro);
- `proyecto_v6.horario`: proyecto de la versión anterior con el **esquema v6 real** (versión 6).

Los tres salen del mismo horario semanal, así que son coherentes entre sí. Uso:

    uv run python -m pruebas.datos.generar_datos
"""

import json
import sqlite3
from pathlib import Path

import openpyxl
from openpyxl.styles import PatternFill

CARPETA = Path(__file__).parent
DIAS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
DIAS = ["L", "M", "X", "J", "V"]

# ---------------------------------------------------------------------------
# La escuela inventada
# ---------------------------------------------------------------------------

# Primaria: 45 min de 8:00 a 11:20, recreo 9:30–9:50, hora cívica el lunes a primera hora.
PRIMARIA = [(480, 525), (525, 570), (590, 635), (635, 680)]
RECESO_PRIMARIA = (570, 590)
# Preescolar: 40 min de 8:00 a 10:55, recreo 9:20–9:40, la última hora dura 35 min.
PREESCOLAR = [(480, 520), (520, 560), (580, 620), (620, 655)]
RECESO_PREESCOLAR = (560, 580)

# Texto del cuadro → (asignatura del proyecto v6, profesor que la da por grupo).
MATE, ESP, CIEN, EF, ARTE, JUEGO = (
    "Matemáticas",
    "Español",
    "Ciencias",
    "Ed. Física",
    "Arte",
    "Juego",
)
TEXTO = {MATE: "Math", ESP: "Español", CIEN: "Science", EF: "Gym", ARTE: "Art", JUEGO: "Play"}
PROFESOR = {
    ("1A", MATE): "Ana Pérez", ("1B", MATE): "Ana Pérez", ("2A", MATE): "Ana Pérez",
    ("1A", ESP): "Bruno Díaz", ("1B", ESP): "Bruno Díaz", ("2A", ESP): "Bruno Díaz",
    ("1A", CIEN): "Carla Ruiz", ("1B", CIEN): "Carla Ruiz", ("2A", CIEN): "Carla Ruiz",
    ("2A", ARTE): "Carla Ruiz", ("1A", ARTE): "Fabián León", ("1B", ARTE): "Fabián León",
    ("1A", EF): "Diego Soto", ("1B", EF): "Diego Soto", ("2A", EF): "Diego Soto",
    ("KA", EF): "Diego Soto", ("KA", JUEGO): "Elena Mora", ("KA", ESP): "Elena Mora",
}  # fmt: skip

# Horario semanal por grupo: [día][hora]. None = libre (tutoría en el cuadro). Las dos horas
# de una asignatura en un día van juntas (D10) y ningún maestro está en dos grupos a la vez.
M, E, C, F, A, J = MATE, ESP, CIEN, EF, ARTE, JUEGO
HORARIO: dict[str, list[list[str | None]]] = {
    "1A": [[None, M, E, C], [M, M, E, F], [E, C, A, A], [M, M, E, F], [M, E, C, None]],
    "1B": [[None, E, C, M], [E, F, M, M], [C, E, M, M], [E, E, A, A], [C, M, F, None]],
    "2A": [[None, C, M, E], [F, E, C, A], [M, M, E, E], [C, F, M, M], [E, A, M, None]],
    "KA": [[F, E, J, J], [J, J, E, None], [F, E, J, J], [J, J, E, None], [F, E, J, J]],
}


def horario() -> dict[str, list[list[str | None]]]:
    """Grupo → [día][hora] → asignatura (None = libre o tutoría)."""
    return {g: [list(dia) for dia in tabla] for g, tabla in HORARIO.items()}


def hhmm12(minutos: int) -> str:
    h, m = divmod(minutos, 60)
    return f"{h if h <= 12 else h - 12}:{m:02d}"


def rango12(inicio: int, fin: int) -> str:
    return f"{hhmm12(inicio)}-{hhmm12(fin)}"


def filas_horas(grupo: str) -> list[tuple[int, int, int | None]]:
    """(inicio, fin, índice de hora) de las filas del cuadro, con la del recreo (índice None)."""
    horas, receso = (
        (PREESCOLAR, RECESO_PREESCOLAR) if grupo == "KA" else (PRIMARIA, RECESO_PRIMARIA)
    )
    filas: list[tuple[int, int, int | None]] = [(i, f, k) for k, (i, f) in enumerate(horas)]
    filas.insert(2, (*receso, None))
    return filas


CELESTE = PatternFill("solid", fgColor="FF66FFFF")


# ---------------------------------------------------------------------------
# Cuadro de horarios por grado
# ---------------------------------------------------------------------------


def cuadro_grupos(ruta: Path) -> None:
    datos = horario()
    libro = openpyxl.Workbook()
    libro.remove(libro.active)  # type: ignore[arg-type]
    for hoja_nombre, grupos in (("1st", ["1A", "1B"]), ("2nd", ["2A"]), ("kinder", ["KA"])):
        hoja = libro.create_sheet(hoja_nombre)
        hoja.cell(1, 1, f"Horario {hoja_nombre} — Colegio de Prueba")
        for b, grupo in enumerate(grupos):
            col = 2 + b * 7  # columna de horas; los días van a su derecha
            hoja.cell(2, col + 3, "Kinder" if grupo == "KA" else grupo)
            for k, dia in enumerate(DIAS_EN):
                hoja.cell(3, col + 1 + k, dia)
            for r, (inicio, fin, indice) in enumerate(filas_horas(grupo)):
                fila = 4 + r
                hoja.cell(fila, col, rango12(inicio, fin))
                for d in range(5):
                    celda = hoja.cell(fila, col + 1 + d)
                    if indice is None:
                        celda.value = "Snack" if grupo == "KA" else "Recess"
                        continue
                    if grupo != "KA" and (d, indice) == (0, 0):
                        celda.fill = CELESTE  # hora cívica: celda vacía pintada de celeste
                        continue
                    asignatura = datos[grupo][d][indice]
                    if asignatura is None:
                        celda.value = "Tutoría" if grupo != "KA" else None
                    else:
                        # Variantes de escritura que el mapeo debe unificar.
                        texto = TEXTO[asignatura]
                        if asignatura == MATE and d == 4:
                            texto = "MATH "
                        if asignatura == CIEN and grupo == "1B" and d == 2:
                            texto = "Sceince"
                        celda.value = texto
        fin = 4 + len(filas_horas(grupos[0])) + 1
        hoja.cell(fin, 2, "Horarios de Examen")
        hoja.cell(fin + 1, 3, "Math")  # se ignora
    libro.save(ruta)


# ---------------------------------------------------------------------------
# Cuadro de maestros
# ---------------------------------------------------------------------------

ESCRITO = {  # cómo aparece cada maestro en el cuadro
    "Ana Pérez": "MS. ANA PEREZ",
    "Bruno Díaz": "Mr.Bruno Díaz",
    "Carla Ruiz": "Ms. Carla Ruiz",
    "Diego Soto": "MR. DIEGO SOTO",
    "Elena Mora": "Miss Elena Mora",
    "Fabián León": "Mr. Fabián León",
}


def cuadro_maestros(ruta: Path) -> None:
    datos = horario()
    libro = openpyxl.Workbook()
    hoja = libro.active
    assert hoja is not None
    hoja.title = "Maestros"
    fila = 1
    for maestro, escrito in ESCRITO.items():
        kinder = maestro == "Elena Mora"
        filas = filas_horas("KA" if kinder else "1A")
        hoja.cell(fila, 4, escrito)
        for k, dia in enumerate(DIAS_EN):
            hoja.cell(fila + 1, 3 + k, dia)
        for r, (inicio, fin, indice) in enumerate(filas):
            f = fila + 2 + r
            hoja.cell(f, 2, rango12(inicio, fin))
            for d in range(5):
                if indice is None:
                    hoja.cell(f, 3 + d, "Lunch" if d == 0 else None)
                    continue
                for grupo, tabla in datos.items():
                    if (grupo == "KA") != kinder and maestro != "Diego Soto":
                        continue
                    asignatura = tabla[d][indice]
                    if asignatura is None or PROFESOR.get((grupo, asignatura)) != maestro:
                        continue
                    if maestro == "Diego Soto" and grupo == "KA":
                        continue  # va en su propio bloque de preescolar (otra hora)
                    texto = f"{TEXTO[asignatura].upper()} {grupo}"
                    if maestro == "Bruno Díaz" and grupo == "2A":
                        texto = f"2A ({rango12(inicio, fin)})"  # solo el grupo
                    hoja.cell(f, 3 + d, texto)
        fila += 2 + len(filas) + 2
    # Diego también da Ed. Física en preescolar: un bloque con las horas de ese nivel.
    hoja.cell(fila, 4, "MR. DIEGO SOTO (Kinder)")
    for k, dia in enumerate(DIAS_EN):
        hoja.cell(fila + 1, 3 + k, dia)
    for r, (inicio, fin, indice) in enumerate(filas_horas("KA")):
        f = fila + 2 + r
        hoja.cell(f, 2, rango12(inicio, fin))
        for d in range(5):
            if indice is not None and datos["KA"][d][indice] == EF:
                hoja.cell(f, 3 + d, "GYM KA")
    fila += 2 + len(filas_horas("KA")) + 2
    hoja.cell(fila, 4, "Biblioteca")  # no es un maestro
    for k, dia in enumerate(DIAS_EN):
        hoja.cell(fila + 1, 3 + k, dia)
    hoja.cell(fila + 2, 2, "8:00-8:45")
    hoja.cell(fila + 2, 3, "Lectura 1A")
    libro.save(ruta)


# ---------------------------------------------------------------------------
# Proyecto v6
# ---------------------------------------------------------------------------

ESQUEMA_V6 = """
CREATE TABLE esquema_version (version INTEGER NOT NULL);
CREATE TABLE configuracion (id INTEGER PRIMARY KEY CHECK (id = 1), nombre_escuela TEXT NOT NULL,
    margen_traslado_min INTEGER NOT NULL, tiempo_limite_s INTEGER NOT NULL,
    hilos INTEGER NOT NULL, pesos TEXT NOT NULL);
CREATE TABLE niveles (id INTEGER PRIMARY KEY, nombre TEXT NOT NULL UNIQUE,
    duracion_min INTEGER NOT NULL, inicio_jornada INTEGER NOT NULL, fin_jornada INTEGER NOT NULL,
    dias TEXT NOT NULL, sin_huecos_alumnos INTEGER NOT NULL DEFAULT 0,
    duraciones_especiales TEXT NOT NULL DEFAULT '{}');
CREATE TABLE recesos (id INTEGER PRIMARY KEY,
    nivel_id INTEGER NOT NULL REFERENCES niveles(id) ON DELETE CASCADE, nombre TEXT NOT NULL,
    inicio INTEGER NOT NULL, fin INTEGER NOT NULL);
CREATE TABLE grados (id INTEGER PRIMARY KEY,
    nivel_id INTEGER NOT NULL REFERENCES niveles(id) ON DELETE CASCADE, nombre TEXT NOT NULL,
    UNIQUE (nivel_id, nombre));
CREATE TABLE profesores (id INTEGER PRIMARY KEY, nombre TEXT NOT NULL UNIQUE,
    carga_max_semanal_min INTEGER NOT NULL, carga_max_diaria_min INTEGER NOT NULL,
    max_consecutivas INTEGER NOT NULL);
CREATE TABLE grupos (id INTEGER PRIMARY KEY,
    grado_id INTEGER NOT NULL REFERENCES grados(id) ON DELETE CASCADE, seccion TEXT NOT NULL,
    estudiantes INTEGER NOT NULL DEFAULT 0,
    titular_id INTEGER REFERENCES profesores(id) ON DELETE SET NULL, UNIQUE (grado_id, seccion));
CREATE TABLE asignaturas (id INTEGER PRIMARY KEY, nombre TEXT NOT NULL UNIQUE,
    espacio_requerido TEXT, max_horas_dia INTEGER NOT NULL,
    bloque_doble TEXT NOT NULL CHECK (bloque_doble IN ('no', 'preferido', 'obligatorio')),
    exigente INTEGER NOT NULL DEFAULT 0, color TEXT NOT NULL);
CREATE TABLE plan_estudios (grado_id INTEGER NOT NULL REFERENCES grados(id) ON DELETE CASCADE,
    asignatura_id INTEGER NOT NULL REFERENCES asignaturas(id) ON DELETE CASCADE,
    horas_semanales INTEGER NOT NULL, PRIMARY KEY (grado_id, asignatura_id));
CREATE TABLE profesor_asignatura (profesor_id INTEGER NOT NULL REFERENCES profesores(id)
    ON DELETE CASCADE, asignatura_id INTEGER NOT NULL REFERENCES asignaturas(id)
    ON DELETE CASCADE, PRIMARY KEY (profesor_id, asignatura_id));
CREATE TABLE profesor_grado (profesor_id INTEGER NOT NULL REFERENCES profesores(id)
    ON DELETE CASCADE, grado_id INTEGER NOT NULL REFERENCES grados(id) ON DELETE CASCADE,
    PRIMARY KEY (profesor_id, grado_id));
CREATE TABLE disponibilidad (id INTEGER PRIMARY KEY,
    profesor_id INTEGER NOT NULL REFERENCES profesores(id) ON DELETE CASCADE,
    dia TEXT NOT NULL, inicio INTEGER NOT NULL, fin INTEGER NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('disponible', 'preferible_no')));
CREATE TABLE espacios (id INTEGER PRIMARY KEY, nombre TEXT NOT NULL UNIQUE, tipo TEXT NOT NULL,
    cantidad INTEGER NOT NULL);
CREATE TABLE asignaciones_fijas (id INTEGER PRIMARY KEY,
    grupo_id INTEGER NOT NULL REFERENCES grupos(id) ON DELETE CASCADE,
    asignatura_id INTEGER NOT NULL REFERENCES asignaturas(id) ON DELETE CASCADE,
    profesor_id INTEGER REFERENCES profesores(id) ON DELETE SET NULL, dia TEXT NOT NULL,
    indice_franja INTEGER NOT NULL);
CREATE TABLE soluciones (id INTEGER PRIMARY KEY, fecha TEXT NOT NULL, estado TEXT NOT NULL,
    tiempo_s REAL NOT NULL, penalizaciones TEXT NOT NULL, nota TEXT NOT NULL DEFAULT '',
    vigente INTEGER NOT NULL DEFAULT 0);
CREATE TABLE asignaciones (id INTEGER PRIMARY KEY,
    solucion_id INTEGER NOT NULL REFERENCES soluciones(id) ON DELETE CASCADE,
    grupo_id INTEGER NOT NULL REFERENCES grupos(id) ON DELETE CASCADE,
    asignatura_id INTEGER NOT NULL REFERENCES asignaturas(id) ON DELETE CASCADE,
    profesor_id INTEGER NOT NULL REFERENCES profesores(id) ON DELETE CASCADE,
    nivel_id INTEGER NOT NULL REFERENCES niveles(id) ON DELETE CASCADE, dia TEXT NOT NULL,
    indice INTEGER NOT NULL);
CREATE TABLE docentes_asignados (grupo_id INTEGER NOT NULL REFERENCES grupos(id)
    ON DELETE CASCADE, asignatura_id INTEGER NOT NULL REFERENCES asignaturas(id)
    ON DELETE CASCADE, profesor_id INTEGER NOT NULL REFERENCES profesores(id) ON DELETE CASCADE,
    PRIMARY KEY (grupo_id, asignatura_id));
CREATE TABLE eventos (id INTEGER PRIMARY KEY,
    nivel_id INTEGER NOT NULL REFERENCES niveles(id) ON DELETE CASCADE, nombre TEXT NOT NULL,
    dia TEXT NOT NULL, inicio INTEGER NOT NULL, fin INTEGER NOT NULL);
CREATE TABLE profesor_evento (profesor_id INTEGER NOT NULL REFERENCES profesores(id)
    ON DELETE CASCADE, evento_id INTEGER NOT NULL REFERENCES eventos(id) ON DELETE CASCADE,
    PRIMARY KEY (profesor_id, evento_id));
CREATE TABLE profesor_suplencia_asignatura (profesor_id INTEGER NOT NULL
    REFERENCES profesores(id) ON DELETE CASCADE, asignatura_id INTEGER NOT NULL
    REFERENCES asignaturas(id) ON DELETE CASCADE, PRIMARY KEY (profesor_id, asignatura_id));
CREATE TABLE profesor_suplencia_grado (profesor_id INTEGER NOT NULL REFERENCES profesores(id)
    ON DELETE CASCADE, grado_id INTEGER NOT NULL REFERENCES grados(id) ON DELETE CASCADE,
    PRIMARY KEY (profesor_id, grado_id));
"""

ASIGNATURAS_V6 = [  # id, nombre, espacio, max/día, bloque doble, exigente, color
    (1, MATE, None, 2, "no", 1, "#E57373"),
    (2, ESP, None, 2, "no", 0, "#64B5F6"),
    (3, CIEN, "laboratorio", 1, "no", 0, "#81C784"),
    (4, EF, "cancha", 1, "no", 0, "#FFB74D"),
    (5, ARTE, None, 2, "preferido", 0, "#BA68C8"),
    (6, JUEGO, None, 2, "no", 0, "#4DB6AC"),
]
PROFESORES_V6 = ["Ana Pérez", "Bruno Díaz", "Carla Ruiz", "Diego Soto", "Elena Mora", "Fabián León"]
GRUPOS_V6 = {"1A": (1, 1, "A"), "1B": (2, 1, "B"), "2A": (3, 2, "A"), "KA": (4, 3, "A")}
NIVEL_DE_GRUPO = {"1A": 1, "1B": 1, "2A": 1, "KA": 2}


def proyecto_v6(ruta: Path) -> None:
    if ruta.exists():
        ruta.unlink()
    con = sqlite3.connect(ruta)
    con.executescript(ESQUEMA_V6)
    con.execute("INSERT INTO esquema_version VALUES (6)")
    pesos = {
        "huecos_profesor": 10, "distribucion_semanal": 8, "exigente_tarde": 3,
        "preferible_no": 6, "dias_profesor": 2, "desequilibrio_carga": 1,
        "titular_preescolar": 5, "bloque_doble_preferido": 4, "cambios_vigente": 20,
    }  # fmt: skip
    con.execute("INSERT INTO configuracion VALUES (1, 'Colegio de Prueba', 5, 120, 4, ?)",
                (json.dumps(pesos),))  # fmt: skip
    con.execute("INSERT INTO niveles VALUES (1, 'Primaria', 45, 480, 680, 'L,M,X,J,V', 0, '{}')")
    con.execute(
        "INSERT INTO niveles VALUES (2, 'Preescolar', 40, 480, 655, 'L,M,X,J,V', 1, '{\"3\": 35}')"
    )
    con.execute("INSERT INTO recesos VALUES (1, 1, 'Recreo', 570, 590)")
    con.execute("INSERT INTO recesos VALUES (2, 2, 'Recreo', 560, 580)")
    con.execute("INSERT INTO eventos VALUES (1, 1, 'Hora cívica', 'L', 480, 525)")
    con.executemany("INSERT INTO grados VALUES (?, ?, ?)",
                    [(1, 1, "1°"), (2, 1, "2°"), (3, 2, "Kinder")])  # fmt: skip
    for i, nombre in enumerate(PROFESORES_V6, start=1):
        con.execute("INSERT INTO profesores VALUES (?, ?, 1500, 300, 3)", (i, nombre))
    pid = {n: i for i, n in enumerate(PROFESORES_V6, start=1)}
    for grupo, (gid, grado, seccion) in GRUPOS_V6.items():
        titular = pid["Elena Mora"] if grupo == "KA" else None
        con.execute("INSERT INTO grupos VALUES (?, ?, ?, ?, ?)", (gid, grado, seccion, 25, titular))
    con.executemany("INSERT INTO asignaturas VALUES (?, ?, ?, ?, ?, ?, ?)", ASIGNATURAS_V6)
    aid = {a[1]: a[0] for a in ASIGNATURAS_V6}
    plan_primaria = {MATE: 6, ESP: 5, CIEN: 3, EF: 2, ARTE: 2}
    for grado in (1, 2):
        for asignatura, horas in plan_primaria.items():
            con.execute(
                "INSERT INTO plan_estudios VALUES (?, ?, ?)", (grado, aid[asignatura], horas)
            )
    for asignatura, horas in {JUEGO: 10, ESP: 5, EF: 3}.items():
        con.execute("INSERT INTO plan_estudios VALUES (3, ?, ?)", (aid[asignatura], horas))
    # Habilitaciones a partir de quién da qué.
    grado_de = {g: v[1] for g, v in GRUPOS_V6.items()}
    habil: set[tuple[int, int]] = set()
    grados: set[tuple[int, int]] = set()
    for (grupo, asignatura), profesor in PROFESOR.items():
        habil.add((pid[profesor], aid[asignatura]))
        grados.add((pid[profesor], grado_de[grupo]))
        gid = GRUPOS_V6[grupo][0]
        con.execute("INSERT INTO docentes_asignados VALUES (?, ?, ?)",
                    (gid, aid[asignatura], pid[profesor]))  # fmt: skip
    con.executemany("INSERT INTO profesor_asignatura VALUES (?, ?)", sorted(habil))
    con.executemany("INSERT INTO profesor_grado VALUES (?, ?)", sorted(grados))
    # Disponibilidad: todos de 7:00 a 16:00 salvo Ana (sin rangos guardados); Fabián prefiere
    # no dar clase el viernes.
    for nombre, i in pid.items():
        if nombre == "Ana Pérez":
            continue
        for dia in DIAS:
            tipo = "preferible_no" if nombre == "Fabián León" and dia == "V" else "disponible"
            con.execute("INSERT INTO disponibilidad (profesor_id, dia, inicio, fin, tipo) "
                        "VALUES (?, ?, 420, 960, ?)", (i, dia, tipo))  # fmt: skip
    con.execute("INSERT INTO profesor_evento VALUES (?, 1)", (pid["Bruno Díaz"],))
    con.execute("INSERT INTO profesor_suplencia_asignatura VALUES (?, ?)",
                (pid["Fabián León"], aid[ARTE]))  # fmt: skip
    con.execute("INSERT INTO profesor_suplencia_grado VALUES (?, 2)", (pid["Fabián León"],))
    con.executemany("INSERT INTO espacios VALUES (?, ?, ?, ?)",
                    [(1, "Cancha", "cancha", 1), (2, "Laboratorio", "laboratorio", 1)])  # fmt: skip
    con.execute("INSERT INTO asignaciones_fijas VALUES (1, 1, ?, ?, 'L', 1)",
                (aid[MATE], pid["Ana Pérez"]))  # fmt: skip
    con.execute("INSERT INTO soluciones VALUES (1, '2026-08-20T10:30:00', 'FACTIBLE', 42.5, "
                "'{\"huecos_profesor\": 12}', 'Horario del ciclo', 1)")  # fmt: skip
    for grupo, tabla in horario().items():
        for d, fila in enumerate(tabla):
            for s, asignatura in enumerate(fila):
                if asignatura is None:
                    continue
                con.execute(
                    "INSERT INTO asignaciones (solucion_id, grupo_id, asignatura_id, profesor_id,"
                    " nivel_id, dia, indice) VALUES (1, ?, ?, ?, ?, ?, ?)",
                    (GRUPOS_V6[grupo][0], aid[asignatura], pid[PROFESOR[(grupo, asignatura)]],
                     NIVEL_DE_GRUPO[grupo], DIAS[d], s),
                )  # fmt: skip
    con.commit()
    con.close()


def main() -> None:
    cuadro_grupos(CARPETA / "cuadro_grupos.xlsx")
    cuadro_maestros(CARPETA / "cuadro_maestros.xlsx")
    proyecto_v6(CARPETA / "proyecto_v6.horario")
    print("Listo:", ", ".join(p.name for p in sorted(CARPETA.glob("*.*")) if p.suffix != ".py"))


if __name__ == "__main__":
    main()
