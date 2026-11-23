"""Creado con Claude.

Escuela mínima para pruebas del verificador, los conflictos y el modelo.

Primaria (nivel 1): lunes y martes, horas de 50 min desde las 8:00, receso de 9:40 a 10:00.
Franjas por día: 0 = 8:00–8:50, 1 = 8:50–9:40, 2 = 10:00–10:50, 3 = 10:50–11:40.
Grupos 1°A (1) y 1°B (2). Asignaturas: Matemáticas (1), Inglés (2), Ed. Física (3, cancha).
Profesores: Ana (1: Mate e Inglés), Beto (2: Mate), Caro (3: Ed. Física e Inglés).
Clases: Mate 1°A (10, 2 h), Mate 1°B (11, 2 h), Inglés 1°A (12, 1 h), Ed. Física 1°A (13, 1 h),
Ed. Física 1°B (14, 1 h).
"""

from timetabling.dominio.borrador import Colocacion
from timetabling.dominio.modelos import (
    Asignatura,
    Clase,
    Configuracion,
    DatosEscuela,
    Destinatario,
    Espacio,
    Grado,
    Grupo,
    Nivel,
    PlanEstudios,
    Profesor,
    Receso,
    ReglasAsignatura,
)

MATE, INGLES, FISICA = 1, 2, 3
ANA, BETO, CARO = 1, 2, 3
MATE_A, MATE_B, INGLES_A, FISICA_A, FISICA_B = 10, 11, 12, 13, 14


def escuela_minima() -> DatosEscuela:
    return DatosEscuela(
        configuracion=Configuracion(nombre_escuela="Mínima", hilos=2),
        niveles=[
            Nivel(
                id=1,
                nombre="Primaria",
                duracion_min=50,
                inicio_jornada=480,
                fin_jornada=720,
                dias=["L", "M"],
                recesos=[Receso(inicio=580, fin=600)],
            )
        ],
        grados=[Grado(id=1, nivel_id=1, nombre="1°")],
        grupos=[Grupo(id=1, grado_id=1, seccion="A"), Grupo(id=2, grado_id=1, seccion="B")],
        asignaturas=[
            Asignatura(id=MATE, nombre="Matemáticas"),
            Asignatura(id=INGLES, nombre="Inglés"),
            Asignatura(
                id=FISICA,
                nombre="Ed. Física",
                espacio_requerido="cancha",
                reglas_por_defecto=ReglasAsignatura(max_horas_dia=1),
            ),
        ],
        plan=[
            PlanEstudios(grado_id=1, asignatura_id=MATE, horas_semanales=2),
            PlanEstudios(grado_id=1, asignatura_id=INGLES, horas_semanales=1),
            PlanEstudios(grado_id=1, asignatura_id=FISICA, horas_semanales=1),
        ],
        profesores=[
            Profesor(id=ANA, nombre="Ana", asignaturas=[MATE, INGLES], grados=[1]),
            Profesor(id=BETO, nombre="Beto", asignaturas=[MATE], grados=[1]),
            Profesor(id=CARO, nombre="Caro", asignaturas=[FISICA, INGLES], grados=[1]),
        ],
        espacios=[Espacio(id=1, nombre="Cancha", tipo="cancha", cantidad=1)],
        clases=[
            Clase(id=MATE_A, asignatura_id=MATE, destinatarios=[Destinatario(grupo_id=1)],
                  horas_semanales=2),
            Clase(id=MATE_B, asignatura_id=MATE, destinatarios=[Destinatario(grupo_id=2)],
                  horas_semanales=2),
            Clase(id=INGLES_A, asignatura_id=INGLES, destinatarios=[Destinatario(grupo_id=1)],
                  horas_semanales=1),
            Clase(id=FISICA_A, asignatura_id=FISICA, destinatarios=[Destinatario(grupo_id=1)],
                  horas_semanales=1),
            Clase(id=FISICA_B, asignatura_id=FISICA, destinatarios=[Destinatario(grupo_id=2)],
                  horas_semanales=1),
        ],
    )  # fmt: skip


def f(dia: str, indice: int) -> str:
    """Id de franja de la Primaria."""
    return f"1:{dia}:{indice}"


def horario_valido() -> list[Colocacion]:
    """Un horario completo que cumple todas las restricciones de `escuela_minima()`."""
    return [
        Colocacion(MATE_A, f("L", 0), (ANA,)),
        Colocacion(MATE_A, f("L", 1), (ANA,)),
        Colocacion(MATE_B, f("L", 0), (BETO,)),
        Colocacion(MATE_B, f("M", 0), (BETO,)),
        Colocacion(INGLES_A, f("M", 0), (CARO,)),
        Colocacion(FISICA_A, f("L", 2), (CARO,)),
        Colocacion(FISICA_B, f("M", 2), (CARO,)),
    ]
