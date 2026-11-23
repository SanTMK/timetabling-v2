"""Creado con Claude.

Diagnóstico de infactibilidad (§11.3). Solo se ejecuta si el resultado es INFACTIBLE.

1. **Por familias:** el modelo sin objetivo, con cada familia bajo un literal de suposición y
   un solo hilo; `sufficient_assumptions_for_infeasibility` da un núcleo que se reduce con un
   filtro de eliminación.
2. **Refinamiento:** dentro de las familias del núcleo, cada familia se sustituye por literales
   por entidad y se repite.
3. Presupuesto: 10 s por intento y 60 s en total (30 s desde la interfaz).

El resultado se traduce a mensajes que nombran entidades concretas, con enlaces a ellas.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from timetabling.dominio.clases import texto_destinatarios
from timetabling.dominio.modelos import DatosEscuela, por_id
from timetabling.nucleo.franjas import Calendario
from timetabling.nucleo.modelo import ConstructorModelo, ModeloHorario, ModoSuposiciones


@dataclass(frozen=True)
class Elemento:
    """Una restricción del núcleo: familia y entidad («*» si no se refinó)."""

    familia: str
    entidad: str

    @property
    def tipo(self) -> str:
        return self.entidad.split(":", 1)[0] if ":" in self.entidad else ""

    @property
    def ident(self) -> str:
        return self.entidad.split(":", 1)[1] if ":" in self.entidad else ""


@dataclass(frozen=True)
class Enlace:
    """Referencia navegable a una entidad («profesor», «grupo», «clase», «asignatura»,
    «division» o «espacio»)."""

    entidad: str
    id: int | str
    texto: str


@dataclass
class Diagnostico:
    factible: bool = False
    """El modelo relajado resultó factible (no había infactibilidad que explicar)."""
    estructural: bool = False
    """La infactibilidad no depende de ninguna familia: es estructural."""
    familias: list[str] = field(default_factory=list)
    elementos: list[Elemento] = field(default_factory=list)
    minimo: bool = True
    """El núcleo quedó reducido (no se agotó el presupuesto)."""
    mensaje: str = ""
    detalles: list[str] = field(default_factory=list)
    enlaces: list[Enlace] = field(default_factory=list)
    tiempo_s: float = 0.0

    @property
    def tiene_nucleo(self) -> bool:
        return bool(self.elementos)


class _Presupuesto:
    def __init__(self, total_s: float, por_intento_s: float) -> None:
        self.fin = time.monotonic() + total_s
        self.por_intento_s = por_intento_s

    @property
    def restante(self) -> float:
        return self.fin - time.monotonic()

    def siguiente(self) -> float | None:
        restante = self.restante
        if restante <= 0.05:
            return None
        return min(self.por_intento_s, restante)


Clave = tuple[str, str]

LIMITE_NUCLEO_S = 3.0
"""Tiempo máximo para extraer un núcleo con suposiciones antes de usar el filtro completo."""


def _resolver(
    horario: ModeloHorario, supuestas: list[Clave], segundos: float
) -> tuple[int, list[Clave]]:
    """Resuelve con las suposiciones dadas y un solo hilo. Devuelve el estado y, si es
    infactible, el subconjunto suficiente de suposiciones."""
    modelo = horario.modelo
    modelo.clear_assumptions()
    modelo.add_assumptions([horario.suposiciones[k] for k in supuestas])
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    solver.parameters.max_time_in_seconds = max(0.05, segundos)
    estado = solver.solve(modelo)
    nucleo: list[Clave] = []
    if estado == cp_model.INFEASIBLE:
        por_indice = {horario.suposiciones[k].index: k for k in supuestas}
        nucleo = [
            por_indice[i]
            for i in solver.sufficient_assumptions_for_infeasibility()
            if i in por_indice
        ]
    return estado, nucleo


Prueba = Callable[[list[Clave], float], int]


def _probador(
    datos: DatosEscuela, calendario: Calendario, refinar: list[str], hilos: int
) -> Prueba:
    """Construye el modelo con solo las restricciones dadas (sin literales) y lo resuelve."""
    modo: ModoSuposiciones = "entidad" if refinar else "familia"

    def probar(activas: list[Clave], segundos: float) -> int:
        horario = ConstructorModelo(
            datos, calendario, modo=modo, refinar=refinar, activas=activas
        ).construir()
        solver = cp_model.CpSolver()
        solver.parameters.num_workers = hilos
        solver.parameters.max_time_in_seconds = max(0.05, segundos)
        return solver.solve(horario.modelo)

    return probar


def _reducir(
    probar: Prueba, nucleo: list[Clave], presupuesto: _Presupuesto
) -> tuple[list[Clave], bool]:
    """Filtro de eliminación: quita cada elemento si sin él sigue siendo infactible."""
    actual = list(nucleo)
    i = 0
    while i < len(actual):
        segundos = presupuesto.siguiente()
        if segundos is None:
            return actual, False
        prueba = actual[:i] + actual[i + 1 :]
        if probar(prueba, segundos) == cp_model.INFEASIBLE:
            actual = prueba
        else:
            i += 1  # necesaria (o no se supo a tiempo: se conserva)
    return actual, True


def diagnosticar(
    datos: DatosEscuela,
    total_s: float = 60.0,
    por_intento_s: float = 10.0,
    calendario: Calendario | None = None,
    hilos: int | None = None,
) -> Diagnostico:
    """La extracción de cada núcleo usa suposiciones y un solo hilo (§11.3). El filtro de
    eliminación reconstruye el modelo con solo las restricciones probadas y sin literales (las
    restricciones condicionadas debilitan la relajación lineal y la prueba de infactibilidad
    puede tardar mucho); ahí se usan `hilos` (por defecto, los de la configuración)."""
    hilos = max(1, hilos or datos.configuracion.hilos)
    inicio = time.monotonic()
    calendario = calendario or Calendario.de(datos)
    presupuesto = _Presupuesto(total_s, por_intento_s)
    resultado = Diagnostico()

    def terminar() -> Diagnostico:
        resultado.tiempo_s = time.monotonic() - inicio
        _redactar(datos, resultado)
        return resultado

    # 1. Por familias.
    horario = ConstructorModelo(datos, calendario, modo="familia").construir()
    claves = sorted(horario.suposiciones)
    segundos = presupuesto.siguiente() or 0.05
    estado, nucleo = _resolver(horario, claves, segundos)
    if estado in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        resultado.factible = True
        return terminar()
    if estado != cp_model.INFEASIBLE:
        resultado.minimo = False
        resultado.mensaje = "No se pudo completar el diagnóstico en el tiempo disponible."
        resultado.tiempo_s = time.monotonic() - inicio
        return resultado
    if not nucleo:
        resultado.estructural = True
        return terminar()
    nucleo, minimo = _reducir(_probador(datos, calendario, [], hilos), nucleo, presupuesto)
    resultado.minimo = minimo
    resultado.familias = sorted({f for f, _ in nucleo})
    if not nucleo:
        resultado.estructural = True
        return terminar()
    resultado.elementos = [Elemento(f, "*") for f in resultado.familias]

    # 2. Refinamiento por entidad dentro de las familias del núcleo. Si el núcleo por
    # suposiciones no sale pronto, se parte de todas las entidades de esas familias.
    refinado = ConstructorModelo(
        datos, calendario, modo="entidad", refinar=resultado.familias
    ).construir()
    claves = sorted(k for k in refinado.suposiciones if k[0] in resultado.familias)
    segundos = presupuesto.siguiente()
    if segundos is not None:
        estado, nucleo_entidades = _resolver(refinado, claves, min(segundos, LIMITE_NUCLEO_S))
        if estado != cp_model.INFEASIBLE or not nucleo_entidades:
            nucleo_entidades = claves
        probar = _probador(datos, calendario, resultado.familias, hilos)
        nucleo_entidades, minimo = _reducir(probar, nucleo_entidades, presupuesto)
        resultado.minimo = resultado.minimo and minimo
        if nucleo_entidades:
            resultado.elementos = [Elemento(f, e) for f, e in nucleo_entidades]
    return terminar()


# ---------------------------------------------------------------------------
# Redacción
# ---------------------------------------------------------------------------

_POR_FAMILIA: dict[str, str] = {
    "disponibilidad": "la disponibilidad de los profesores",
    "prohibidas": "las franjas prohibidas de las asignaturas",
    "curricular": "las horas semanales de las clases",
    "grupo": "que cada grupo tenga una sola clase a la vez",
    "profesor": "que cada profesor esté en un solo lugar a la vez",
    "carga": "los límites de carga de los profesores",
    "continuidad": "que cada clase la imparta un solo profesor",
    "espacio": "la capacidad de los espacios especiales",
    "diaria": "el máximo de horas diarias por asignatura",
    "bloque": "los bloques dobles obligatorios",
    "sin_huecos": "la prohibición de huecos de los alumnos",
    "fija": "las asignaciones fijas",
    "division": "la simultaneidad de las divisiones",
}


def _unir(partes: list[str]) -> str:
    if len(partes) <= 1:
        return "".join(partes)
    return ", ".join(partes[:-1]) + " y " + partes[-1]


def _describir(datos: DatosEscuela, elemento: Elemento) -> tuple[str, Enlace | None]:
    if elemento.entidad == "*":
        return _POR_FAMILIA.get(elemento.familia, elemento.familia), None
    tipo, ident = elemento.tipo, elemento.ident
    profesores = por_id(datos.profesores)
    clases = por_id(datos.clases)
    asignaturas = por_id(datos.asignaturas)
    divisiones = por_id(datos.divisiones)
    if tipo == "profesor" and int(ident) in profesores:
        nombre = profesores[int(ident)].nombre
        textos = {
            "disponibilidad": f"la disponibilidad de {nombre}",
            "carga": f"los límites de carga de {nombre} (máximos y tiempo continuo)",
            "profesor": f"que {nombre} no puede estar en dos lugares a la vez",
        }
        return textos.get(elemento.familia, f"{elemento.familia} de {nombre}"), Enlace(
            "profesor", int(ident), nombre
        )
    if tipo == "clase" and int(ident) in clases:
        clase = clases[int(ident)]
        asignatura = asignaturas[clase.asignatura_id].nombre
        grupos = texto_destinatarios(datos, clase)
        textos = {
            "curricular": f"las {clase.horas_semanales} horas de {asignatura} de {grupos}",
            "continuidad": f"que {asignatura} de {grupos} la imparta un solo profesor",
            "bloque": f"el bloque doble obligatorio de {asignatura} de {grupos}",
            "fija": f"las asignaciones fijas de {asignatura} de {grupos}",
        }
        return textos.get(elemento.familia, f"{elemento.familia} de {asignatura} de {grupos}"), (
            Enlace("clase", int(ident), f"{asignatura} · {grupos}")
        )
    if tipo == "grupo":
        nombre = datos.nombre_grupo(int(ident))
        textos = {
            "grupo": f"que {nombre} tenga una sola clase a la vez",
            "diaria": f"el máximo de horas diarias por asignatura de {nombre}",
            "sin_huecos": f"la prohibición de huecos de {nombre}",
        }
        return textos.get(elemento.familia, f"{elemento.familia} de {nombre}"), Enlace(
            "grupo", int(ident), nombre
        )
    if tipo == "asignatura" and int(ident) in asignaturas:
        nombre = asignaturas[int(ident)].nombre
        return f"las franjas prohibidas de {nombre}", Enlace("asignatura", int(ident), nombre)
    if tipo == "division" and int(ident) in divisiones:
        division = divisiones[int(ident)]
        grupo = datos.nombre_grupo(division.grupo_id)
        return (
            f"la simultaneidad de «{division.nombre}» de {grupo}",
            Enlace("division", int(ident), f"{division.nombre} ({grupo})"),
        )
    if tipo == "espacio":
        return (
            f"la capacidad de los espacios de tipo «{ident}»",
            Enlace("espacio", ident, ident),
        )
    return f"{elemento.familia} ({elemento.entidad})", None


def _redactar(datos: DatosEscuela, resultado: Diagnostico) -> None:
    if resultado.factible:
        resultado.mensaje = "No se encontró ningún conflicto: el problema tiene solución."
        return
    if resultado.estructural or not resultado.elementos:
        resultado.mensaje = (
            "El conflicto es estructural: no depende de una restricción concreta. Revise los "
            "errores de validación, las habilitaciones de los profesores y que cada clase tenga "
            "franjas posibles."
        )
        return
    descripciones: list[str] = []
    for elemento in sorted(resultado.elementos, key=lambda e: (e.familia, e.entidad)):
        texto, enlace = _describir(datos, elemento)
        if texto not in descripciones:
            descripciones.append(texto)
        if enlace is not None and enlace not in resultado.enlaces:
            resultado.enlaces.append(enlace)
    resultado.detalles = descripciones
    resultado.mensaje = "El conflicto involucra " + _unir(descripciones) + "."
    if not resultado.minimo:
        resultado.mensaje += " (El diagnóstico no terminó de reducir el conflicto a tiempo.)"
