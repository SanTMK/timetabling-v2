"""Creado con Claude.

Escuelas de ejemplo (§18): «pequeño» (5 grupos y 12 profesores) y «mediano» (30 grupos y 42
profesores, con clase conjunta, división, franjas prohibidas, bloqueo de grupo y profesor
multinivel con disponibilidad parcial).
"""

from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from timetabling.dominio.clases import sincronizar_con_plan
from timetabling.dominio.modelos import (
    Asignatura,
    BloqueoGrupo,
    Clase,
    Configuracion,
    DatosEscuela,
    Destinatario,
    Disponibilidad,
    Division,
    Espacio,
    Evento,
    Grado,
    Grupo,
    Nivel,
    PlanEstudios,
    Profesor,
    RangoFranjas,
    Receso,
    ReglasAsignatura,
)
from timetabling.dominio.tiempo import DIAS_POR_DEFECTO, a_minutos
from timetabling.persistencia import respaldos
from timetabling.persistencia.repositorio import Repositorio

Tamano = Literal["pequeno", "mediano"]

_COLORES: dict[str, str] = {
    "Español": "#E57373",
    "Matemáticas": "#64B5F6",
    "Ciencias": "#81C784",
    "Ciencias Sociales": "#FFB74D",
    "Historia": "#FFB74D",
    "Formación Cívica": "#BA68C8",
    "Inglés": "#4DB6AC",
    "Ed. Física": "#AED581",
    "Artes": "#F06292",
    "Música": "#9575CD",
    "Tecnología": "#90A4AE",
    "Lenguaje": "#E57373",
    "Pensamiento Matemático": "#64B5F6",
    "Exploración del Mundo": "#81C784",
}


class _Constructor:
    """Arma un `DatosEscuela` asignando ids consecutivos."""

    def __init__(self, nombre_escuela: str, margen: int) -> None:
        self.datos = DatosEscuela(
            configuracion=Configuracion(nombre_escuela=nombre_escuela, margen_traslado_min=margen)
        )
        self._siguiente: dict[str, int] = {}

    def _id(self, tipo: str) -> int:
        self._siguiente[tipo] = self._siguiente.get(tipo, 0) + 1
        return self._siguiente[tipo]

    def nivel(self, **campos: object) -> Nivel:
        nivel = Nivel(id=self._id("nivel"), **campos)  # type: ignore[arg-type]
        self.datos.niveles.append(nivel)
        return nivel

    def grado(self, nivel: Nivel, nombre: str) -> Grado:
        assert nivel.id is not None
        grado = Grado(id=self._id("grado"), nivel_id=nivel.id, nombre=nombre)
        self.datos.grados.append(grado)
        return grado

    def grupo(self, grado: Grado, seccion: str, estudiantes: int = 25) -> Grupo:
        assert grado.id is not None
        grupo = Grupo(
            id=self._id("grupo"), grado_id=grado.id, seccion=seccion, estudiantes=estudiantes
        )
        self.datos.grupos.append(grupo)
        return grupo

    def asignatura(
        self,
        nombre: str,
        *,
        espacio: str | None = None,
        reglas: ReglasAsignatura | None = None,
    ) -> Asignatura:
        asignatura = Asignatura(
            id=self._id("asignatura"),
            nombre=nombre,
            color=_COLORES.get(nombre, "#9E9E9E"),
            espacio_requerido=espacio,
            reglas_por_defecto=reglas or ReglasAsignatura(),
        )
        self.datos.asignaturas.append(asignatura)
        return asignatura

    def plan(self, grados: Iterable[Grado], horas: list[tuple[Asignatura, int]]) -> None:
        for grado in grados:
            for asignatura, h in horas:
                assert grado.id is not None and asignatura.id is not None
                self.datos.plan.append(
                    PlanEstudios(grado_id=grado.id, asignatura_id=asignatura.id, horas_semanales=h)
                )

    def profesor(
        self,
        nombre: str,
        asignaturas: Iterable[Asignatura],
        grados: Iterable[Grado],
        **campos: object,
    ) -> Profesor:
        profesor = Profesor(
            id=self._id("profesor"),
            nombre=nombre,
            asignaturas=[a.id for a in asignaturas if a.id is not None],
            grados=[g.id for g in grados if g.id is not None],
            **campos,  # type: ignore[arg-type]
        )
        self.datos.profesores.append(profesor)
        return profesor

    def espacio(self, nombre: str, tipo: str, cantidad: int = 1) -> None:
        self.datos.espacios.append(
            Espacio(id=self._id("espacio"), nombre=nombre, tipo=tipo, cantidad=cantidad)
        )

    def division(self, grupo: Grupo, nombre: str, partes: list[str]) -> Division:
        assert grupo.id is not None
        division = Division(
            id=self._id("division"), grupo_id=grupo.id, nombre=nombre, partes=partes
        )
        self.datos.divisiones.append(division)
        return division

    def sincronizar(self) -> None:
        """Crea las clases del plan que falten y les asigna id."""
        for clase in sincronizar_con_plan(self.datos).nuevas:
            clase.id = self._id("clase")
            self.datos.clases.append(clase)

    def clase(self, clase: Clase) -> Clase:
        clase.id = self._id("clase")
        self.datos.clases.append(clase)
        return clase

    def clases_de(self, asignatura: Asignatura, grupo: Grupo) -> list[Clase]:
        return [
            c
            for c in self.datos.clases
            if c.asignatura_id == asignatura.id
            and any(d.grupo_id == grupo.id for d in c.destinatarios)
        ]

    def fijar_profesor(self, asignatura: Asignatura, grupo: Grupo, profesor: Profesor) -> None:
        assert profesor.id is not None
        for clase in self.clases_de(asignatura, grupo):
            clase.profesores = [profesor.id]


def ejemplo_pequeno() -> DatosEscuela:
    """Una primaria de 5 grupos (1°A–5°A) y 12 profesores."""
    c = _Constructor("Escuela de ejemplo (pequeña)", margen=0)
    primaria = c.nivel(
        nombre="Primaria",
        duracion_min=50,
        inicio_jornada=a_minutos("07:30"),
        fin_jornada=a_minutos("14:00"),
        recesos=[Receso(nombre="Recreo", inicio=a_minutos("10:00"), fin=a_minutos("10:30"))],
    )
    grados = [c.grado(primaria, f"{n}°") for n in range(1, 6)]
    for grado in grados:
        c.grupo(grado, "A")

    espanol = c.asignatura("Español")
    mate = c.asignatura("Matemáticas")
    ciencias = c.asignatura("Ciencias")
    ingles = c.asignatura("Inglés")
    fisica = c.asignatura(
        "Ed. Física",
        reglas=ReglasAsignatura(
            max_horas_dia=1, franjas_prohibidas=[RangoFranjas(desde_indice=0, hasta_indice=0)]
        ),
    )
    artes = c.asignatura("Artes")
    civica = c.asignatura("Formación Cívica", reglas=ReglasAsignatura(max_horas_dia=1))
    c.plan(
        grados,
        [(espanol, 6), (mate, 6), (ciencias, 4), (ingles, 4), (fisica, 2), (artes, 2), (civica, 1)],
    )

    c.profesor("Ana López", [espanol], grados)
    c.profesor("Bruno Díaz", [espanol], grados)
    c.profesor("Carla Méndez", [mate], grados)
    c.profesor("Diego Ruiz", [mate], grados)
    c.profesor("Elena Torres", [ciencias], grados)
    c.profesor("Fernando Gil", [ciencias, civica], grados)
    c.profesor("Gabriela Sosa", [ingles], grados)
    c.profesor("Héctor Vega", [ingles], grados)
    c.profesor("Irene Castro", [fisica], grados)
    c.profesor("Jorge Peña", [artes], grados)
    c.profesor("Karla Ríos", [espanol, mate, civica], grados)
    c.profesor("Luis Navarro", [artes, fisica], grados)
    c.sincronizar()
    return c.datos


def ejemplo_mediano() -> DatosEscuela:
    """30 grupos (6 de preescolar, 12 de primaria y 12 de secundaria) y 42 profesores."""
    c = _Constructor("Colegio de ejemplo (mediano)", margen=10)
    dias = list(DIAS_POR_DEFECTO)

    # Niveles: duraciones y recesos distintos.
    preescolar = c.nivel(
        nombre="Preescolar",
        duracion_min=45,
        inicio_jornada=a_minutos("08:00"),
        fin_jornada=a_minutos("12:30"),
        recesos=[Receso(nombre="Recreo", inicio=a_minutos("10:15"), fin=a_minutos("10:45"))],
        preferir_titular=True,
    )
    primaria = c.nivel(
        nombre="Primaria",
        duracion_min=50,
        inicio_jornada=a_minutos("07:30"),
        fin_jornada=a_minutos("14:00"),
        recesos=[Receso(nombre="Recreo", inicio=a_minutos("10:00"), fin=a_minutos("10:30"))],
        eventos=[
            Evento(nombre="Hora cívica", dia="L", inicio=a_minutos("07:30"), fin=a_minutos("08:20"))
        ],
    )
    secundaria = c.nivel(
        nombre="Secundaria",
        duracion_min=50,
        inicio_jornada=a_minutos("07:00"),
        fin_jornada=a_minutos("14:00"),
        recesos=[Receso(nombre="Receso", inicio=a_minutos("10:20"), fin=a_minutos("10:40"))],
    )

    grados_pre = [c.grado(preescolar, n) for n in ("K1", "K2", "K3")]
    grados_pri = [c.grado(primaria, f"{n}°") for n in range(1, 7)]
    grados_sec = [c.grado(secundaria, f"{n}°") for n in range(7, 10)]
    grupos_pre = [c.grupo(g, s, 18) for g in grados_pre for s in "AB"]
    grupos_pri = [c.grupo(g, s, 28) for g in grados_pri for s in "AB"]
    grupos_sec = [c.grupo(g, s, 30) for g in grados_sec for s in "ABCD"]

    # Bloqueo de grupo: 6°B sale temprano los viernes (natación).
    seis_b = grupos_pri[-1]
    seis_b.bloqueos = [
        BloqueoGrupo(dia="V", inicio=a_minutos("13:00"), fin=a_minutos("13:50"), nombre="Natación")
    ]

    # Asignaturas.
    lenguaje = c.asignatura("Lenguaje")
    pensamiento = c.asignatura("Pensamiento Matemático")
    exploracion = c.asignatura("Exploración del Mundo")
    musica = c.asignatura("Música", reglas=ReglasAsignatura(max_horas_dia=1))
    espanol = c.asignatura("Español")
    mate = c.asignatura("Matemáticas")
    ciencias = c.asignatura("Ciencias")
    sociales = c.asignatura("Ciencias Sociales")
    historia = c.asignatura("Historia")
    civica = c.asignatura("Formación Cívica", reglas=ReglasAsignatura(max_horas_dia=1))
    ingles = c.asignatura("Inglés")
    fisica = c.asignatura(
        "Ed. Física",
        espacio="cancha",
        reglas=ReglasAsignatura(
            max_horas_dia=1, franjas_prohibidas=[RangoFranjas(desde_indice=0, hasta_indice=0)]
        ),
    )
    artes = c.asignatura("Artes", reglas=ReglasAsignatura(max_horas_dia=1))
    tecnologia = c.asignatura(
        "Tecnología", espacio="taller", reglas=ReglasAsignatura(bloque_doble="preferido")
    )
    c.espacio("Cancha techada", "cancha")
    c.espacio("Patio", "cancha")
    c.espacio("Taller de tecnología", "taller")

    # Plan de estudios.
    c.plan(
        grados_pre,
        [(lenguaje, 5), (pensamiento, 5), (exploracion, 4), (ingles, 4), (fisica, 2), (musica, 2)],
    )
    c.plan(
        grados_pri,
        [
            (espanol, 7),
            (mate, 6),
            (ciencias, 4),
            (sociales, 3),
            (civica, 1),
            (ingles, 5),
            (fisica, 2),
            (artes, 2),
        ],
    )
    c.plan(
        grados_sec,
        [
            (espanol, 5),
            (mate, 5),
            (ciencias, 6),
            (historia, 3),
            (civica, 1),
            (ingles, 4),
            (fisica, 2),
            (artes, 2),
            (tecnologia, 2),
        ],
    )
    todos_grados = grados_pre + grados_pri + grados_sec

    # Profesores: 6 titulares de preescolar.
    nombres_pre = ["Alicia Mora", "Beatriz Luna", "Cecilia Paz", "Daniela Rey", "Eva Solís",
                   "Fabiola Cruz"]  # fmt: skip
    titulares_pre: list[Profesor] = []
    for nombre, grupo in zip(nombres_pre, grupos_pre, strict=True):
        grado = next(g for g in grados_pre if g.id == grupo.grado_id)
        titulares_pre.append(c.profesor(nombre, [lenguaje, pensamiento, exploracion], [grado]))

    # 12 titulares de primaria.
    nombres_pri = ["Gerardo Ortiz", "Hilda Campos", "Iván Medina", "Julia Reyes",
                   "Kevin Salas", "Laura Fuentes", "Mario Ibarra", "Nora Aguilar",
                   "Óscar Rangel", "Paula Herrera", "Quique Bravo", "Rosa Valdez"]  # fmt: skip
    titulares_pri: list[Profesor] = []
    for nombre, grupo in zip(nombres_pri, grupos_pri, strict=True):
        grado = next(g for g in grados_pri if g.id == grupo.grado_id)
        titulares_pri.append(
            c.profesor(nombre, [espanol, mate, ciencias, sociales, civica], [grado])
        )

    # 6 de inglés (dos multinivel preescolar–primaria; una con disponibilidad parcial).
    pri_bajos = grados_pri[:3]
    c.profesor(
        "Sara Kim",
        [ingles],
        grados_pre + pri_bajos,
        disponible_toda_la_jornada=False,
        disponibilidad=[
            Disponibilidad(dia=d, inicio=a_minutos("08:00"), fin=a_minutos("12:30")) for d in dias
        ],
    )
    c.profesor("Tomás Wilson", [ingles], grados_pre + grados_pri)
    c.profesor("Úrsula Grant", [ingles], grados_pri)
    c.profesor("Víctor Hale", [ingles], grados_pri + grados_sec)
    c.profesor("Wendy Park", [ingles], grados_sec)
    c.profesor("Xavier Bell", [ingles], grados_sec)

    # 3 de Ed. Física y 3 de artes/música (todos los niveles).
    for nombre in ("Yolanda Ochoa", "Zacarías León", "Adrián Prieto"):
        c.profesor(nombre, [fisica], todos_grados)
    c.profesor("Berta Quiroga", [musica, artes], grados_pre + grados_pri)
    c.profesor("César Lozano", [artes], grados_pri + grados_sec)
    c.profesor("Dora Montes", [artes, musica], todos_grados)

    # 12 de secundaria.
    for nombre in ("Emilio Vargas", "Flor Benítez", "Gonzalo Rivas"):
        c.profesor(nombre, [espanol], grados_sec)
    for nombre in ("Hugo Carrillo", "Inés Barrera", "Joel Sandoval"):
        c.profesor(nombre, [mate], grados_sec)
    for nombre in ("Karen Nieto", "Leonel Ponce", "Marta Cabrera"):
        c.profesor(nombre, [ciencias], grados_sec)
    for nombre in ("Nicolás Ávila", "Olga Serrano"):
        c.profesor(nombre, [historia, civica], grados_sec)
    c.profesor("Pablo Esquivel", [tecnologia], grados_sec)

    # Titulares de grupo (preescolar prefiere al titular).
    for grupo, profesor in zip(grupos_pre, titulares_pre, strict=True):
        grupo.titular_id = profesor.id
    for grupo, profesor in zip(grupos_pri, titulares_pri, strict=True):
        grupo.titular_id = profesor.id

    # Clase conjunta: Ed. Física de 9°C y 9°D juntos.
    nueve_c, nueve_d = grupos_sec[-2], grupos_sec[-1]
    assert fisica.id is not None and nueve_c.id is not None and nueve_d.id is not None
    c.clase(
        Clase(
            asignatura_id=fisica.id,
            destinatarios=[Destinatario(grupo_id=nueve_c.id), Destinatario(grupo_id=nueve_d.id)],
            horas_semanales=2,
        )
    )

    # División: Inglés por nivel en 8°A y 8°B (Básico / Avanzado, simultáneas).
    assert ingles.id is not None
    for grupo in grupos_sec[4:6]:
        division = c.division(grupo, "Inglés por nivel", ["Básico", "Avanzado"])
        assert grupo.id is not None and division.id is not None
        for parte in division.partes:
            c.clase(
                Clase(
                    asignatura_id=ingles.id,
                    destinatarios=[
                        Destinatario(grupo_id=grupo.id, division_id=division.id, parte=parte)
                    ],
                    horas_semanales=4,
                )
            )

    c.sincronizar()

    # Los titulares imparten los campos formativos (preescolar) y las materias base (primaria).
    for grupo, profesor in zip(grupos_pre, titulares_pre, strict=True):
        for asignatura in (lenguaje, pensamiento, exploracion):
            c.fijar_profesor(asignatura, grupo, profesor)
    for grupo, profesor in zip(grupos_pri, titulares_pri, strict=True):
        for asignatura in (espanol, mate, ciencias, sociales, civica):
            c.fijar_profesor(asignatura, grupo, profesor)

    return c.datos


def datos_ejemplo(tamano: Tamano) -> DatosEscuela:
    return ejemplo_pequeno() if tamano == "pequeno" else ejemplo_mediano()


def crear_ejemplo(ruta: Path | str, tamano: Tamano = "pequeno", sobrescribir: bool = False) -> Path:
    """Crea el archivo de proyecto de ejemplo. Si existe y se pide sobrescribir, primero se
    respalda."""
    ruta = Path(ruta)
    if ruta.exists():
        if not sobrescribir:
            raise FileExistsError(f"Ya existe «{ruta}». Use --sobrescribir para reemplazarlo.")
        respaldos.respaldar_archivo(ruta, Configuracion().respaldos_a_conservar)
        ruta.unlink()
    datos = datos_ejemplo(tamano)
    with Repositorio.crear(ruta, datos.configuracion) as repo:
        repo.reemplazar_datos(datos)
    return ruta
