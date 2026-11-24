"""Creado con Claude.

Reparación local (§12.4).

**Colocar y reacomodar lo mínimo:** fija la clase en la celda pedida; el vecindario son las
clases que comparten grupo, profesor o tipo de espacio con ella ese día; si no hay solución en
3 s, el vecindario se amplía a toda la semana de esos grupos y profesores; el resto queda fijo y
se minimiza B9 (cambios) más el objetivo normal. Devuelve una propuesta (antes → después) que el
usuario acepta o descarta.

**Sugerir lugar:** evalúa las celdas válidas para una clase con la penalización marginal y
devuelve las mejores.
"""

import time
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from timetabling.dominio.borrador import Colocacion
from timetabling.dominio.clases import grupos_de_clase
from timetabling.dominio.modelos import DatosEscuela, EstadoSolucion, por_id
from timetabling.dominio.tiempo import NOMBRES_DIAS, texto_rango
from timetabling.nucleo.conflictos import Conflictos
from timetabling.nucleo.franjas import Calendario
from timetabling.nucleo.objetivo import evaluar, pesos, total_ponderado
from timetabling.nucleo.resolver import OpcionesResolucion, Resolutor

LIMITE_DIA_S = 3.0
"""Plazo total para el intento con el vecindario del día (§12.4), preparación incluida."""
MARGEN_S = 0.5
"""Tiempo que se reserva para lo que sigue a la búsqueda (extraer, evaluar, comparar)."""
LIMITE_SEMANA_S = 5.0


@dataclass(frozen=True)
class CambioPropuesto:
    clase_id: int
    texto: str
    antes: tuple[str, ...]
    despues: tuple[str, ...]

    @property
    def linea(self) -> str:
        return f"{self.texto}: {', '.join(self.antes) or '—'} → {', '.join(self.despues) or '—'}"


@dataclass
class Propuesta:
    encontrada: bool
    colocaciones: list[Colocacion] = field(default_factory=list)
    cambios: list[CambioPropuesto] = field(default_factory=list)
    ampliada: bool = False
    """Hubo que ampliar el vecindario a toda la semana."""
    tiempo_s: float = 0.0
    mensaje: str = ""

    @property
    def cambiadas(self) -> set[tuple[int, str]]:
        """(clase, franja) nuevas respecto a antes (para marcarlas con ↻)."""
        return {(c.clase_id, c.franja_id) for c in self.colocaciones} - self._antes

    _antes: set[tuple[int, str]] = field(default_factory=set, repr=False)


def _texto_franja(calendario: Calendario, franja_id: str) -> str:
    f = calendario.franjas.get(franja_id)
    if f is None:
        return franja_id
    return f"{NOMBRES_DIAS[f.dia][:2]} {texto_rango(f.inicio, f.fin)}"


def _vecindario_del_dia(
    datos: DatosEscuela,
    calendario: Calendario,
    conflictos: Conflictos,
    base: list[Colocacion],
    nueva: Colocacion,
) -> set[int]:
    """Clases que comparten grupo, profesor o tipo de espacio con la nueva, ese día."""
    info = conflictos.info[nueva.clase_id]
    dia = calendario.franjas[nueva.franja_id].dia
    grupos = set(grupos_de_clase(info.clase))
    profesores = set(nueva.profesores) | set(info.clase.profesores)
    vecinas = {nueva.clase_id}
    for c in base:
        if calendario.franjas[c.franja_id].dia != dia:
            continue
        otra = conflictos.info.get(c.clase_id)
        if otra is None:
            continue
        if (
            grupos & set(grupos_de_clase(otra.clase))
            or profesores & set(c.profesores)
            or (info.tipo_espacio is not None and otra.tipo_espacio == info.tipo_espacio)
        ):
            vecinas.add(c.clase_id)
    return vecinas


def _vecindario_semana(
    conflictos: Conflictos, base: list[Colocacion], nueva: Colocacion
) -> set[int]:
    """Todas las clases de esos grupos y profesores, en toda la semana."""
    info = conflictos.info[nueva.clase_id]
    grupos = set(grupos_de_clase(info.clase))
    profesores = set(nueva.profesores) | set(info.clase.profesores)
    profesores |= {p for c in base if c.clase_id == nueva.clase_id for p in c.profesores}
    vecinas = {nueva.clase_id}
    for clase_id, otra in conflictos.info.items():
        if grupos & set(grupos_de_clase(otra.clase)) or profesores & set(otra.clase.profesores):
            vecinas.add(clase_id)
    for c in base:
        if profesores & set(c.profesores):
            vecinas.add(c.clase_id)
    return vecinas


def _diferencias(
    datos: DatosEscuela,
    calendario: Calendario,
    antes: list[Colocacion],
    despues: list[Colocacion],
    conflictos: Conflictos,
) -> list[CambioPropuesto]:
    profesores = por_id(datos.profesores)
    por_clase_antes: dict[int, Counter[tuple[str, tuple[int, ...]]]] = defaultdict(Counter)
    por_clase_despues: dict[int, Counter[tuple[str, tuple[int, ...]]]] = defaultdict(Counter)
    for c in antes:
        por_clase_antes[c.clase_id][(c.franja_id, c.profesores)] += 1
    for c in despues:
        por_clase_despues[c.clase_id][(c.franja_id, c.profesores)] += 1

    def describir(clave: tuple[str, tuple[int, ...]]) -> str:
        nombres = ", ".join(profesores[p].nombre for p in clave[1] if p in profesores)
        return f"{_texto_franja(calendario, clave[0])}" + (f" ({nombres})" if nombres else "")

    cambios = []
    for clase_id in sorted(set(por_clase_antes) | set(por_clase_despues)):
        a, d = por_clase_antes[clase_id], por_clase_despues[clase_id]
        if a == d:
            continue
        quitadas = tuple(describir(k) for k in sorted((a - d).elements()))
        puestas = tuple(describir(k) for k in sorted((d - a).elements()))
        info = conflictos.info.get(clase_id)
        cambios.append(
            CambioPropuesto(clase_id, info.texto if info else str(clase_id), quitadas, puestas)
        )
    return cambios


def colocar_y_reacomodar(
    datos: DatosEscuela,
    colocaciones: Iterable[Colocacion],
    nueva: Colocacion,
    quitar: Colocacion | None = None,
    hilos: int | None = None,
    calendario: Calendario | None = None,
    limite_dia_s: float = LIMITE_DIA_S,
    limite_semana_s: float = LIMITE_SEMANA_S,
) -> Propuesta:
    """Coloca `nueva` (moviendo `quitar` si se da) y reacomoda lo mínimo alrededor."""
    inicio = time.monotonic()
    calendario = calendario or Calendario.de(datos)
    antes = list(colocaciones)
    base = list(antes)
    if quitar is not None:
        base.remove(quitar)
    conflictos = Conflictos(datos, calendario)
    if nueva.clase_id not in conflictos.info or nueva.franja_id not in calendario.franjas:
        return Propuesta(False, mensaje="La clase o la franja no existen.")
    horas = Counter(c.clase_id for c in base)
    horas[nueva.clase_id] += 1
    bloqueadas = [c for c in base if c.bloqueada and c.clase_id != nueva.clase_id]
    fijar = [nueva, *bloqueadas]
    hilos = hilos or datos.configuracion.hilos
    bloqueo = {(c.clase_id, c.franja_id): c.bloqueada for c in base}

    for ampliada, vecindario, limite in (
        (False, _vecindario_del_dia(datos, calendario, conflictos, base, nueva), limite_dia_s),
        (True, _vecindario_semana(conflictos, base, nueva), limite_semana_s),
    ):
        transcurrido = time.monotonic() - inicio
        if not ampliada:
            limite = max(1.0, limite - transcurrido - MARGEN_S)
        opciones = OpcionesResolucion(
            tiempo_limite_s=limite,
            hilos=hilos,
            base=base,
            vecindario=vecindario,
            fijar=fijar,
            horas=dict(horas),
        )
        resultado = Resolutor(datos, opciones, calendario=calendario).resolver()
        if resultado.estado in (EstadoSolucion.OPTIMO, EstadoSolucion.FACTIBLE):
            despues = sorted(
                Colocacion(
                    c.clase_id,
                    c.franja_id,
                    c.profesores,
                    nueva.bloqueada
                    if (c.clase_id, c.franja_id) == (nueva.clase_id, nueva.franja_id)
                    else bloqueo.get((c.clase_id, c.franja_id), False),
                )
                for c in resultado.colocaciones
            )
            propuesta = Propuesta(
                True,
                despues,
                _diferencias(datos, calendario, antes, despues, conflictos),
                ampliada,
                time.monotonic() - inicio,
            )
            propuesta._antes = {(c.clase_id, c.franja_id) for c in antes}
            return propuesta
    return Propuesta(
        False,
        tiempo_s=time.monotonic() - inicio,
        mensaje="No se encontró un reacomodo que respete todas las restricciones.",
    )


@dataclass(frozen=True)
class Sugerencia:
    franja_id: str
    profesores: tuple[int, ...]
    penalizacion: float
    """Penalización marginal (aumento de la suma ponderada al colocarla ahí)."""


def sugerir_lugares(
    datos: DatosEscuela,
    colocaciones: Iterable[Colocacion],
    clase_id: int,
    cuantos: int = 3,
    conflictos: Conflictos | None = None,
) -> list[Sugerencia]:
    """Las `cuantos` celdas válidas (🟩/🟨) con menor penalización marginal."""
    lista = list(colocaciones)
    conflictos = conflictos or Conflictos(datos).cargar(lista)
    info = conflictos.info.get(clase_id)
    if info is None or info.nivel_id is None:
        return []
    calendario = conflictos.calendario
    tabla = pesos(datos.configuracion.criterios)
    actual = total_ponderado(evaluar(datos, lista, calendario), tabla)
    opciones: list[Sugerencia] = []
    for franja in calendario.utiles_nivel.get(info.nivel_id, []):
        if franja.id not in info.utiles:
            continue
        estado, _ = conflictos.estado(clase_id, franja)
        if estado == "invalida":
            continue
        profesores = conflictos.profesores_de(clase_id, franja)
        nueva = Colocacion(clase_id, franja.id, profesores)
        total = total_ponderado(evaluar(datos, [*lista, nueva], calendario), tabla)
        opciones.append(Sugerencia(franja.id, profesores, total - actual))
    opciones.sort(key=lambda s: (s.penalizacion, s.franja_id))
    return opciones[:cuantos]
