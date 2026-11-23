"""Creado con Claude.

Resolución (§11.1). Etapa 1: factibilidad sin objetivo (`stop_after_first_solution`). La etapa
2 (optimización con el objetivo y la primera solución como pista) se agrega en F4. El tiempo de
construcción se descuenta del límite (mínimo 1 s de búsqueda). `cancelar()` detiene la búsqueda
desde otro hilo y conserva la mejor solución.
"""

import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from timetabling.dominio.borrador import Colocacion
from timetabling.dominio.modelos import DatosEscuela, EstadoSolucion
from timetabling.nucleo.franjas import Calendario
from timetabling.nucleo.modelo import ConstructorModelo, ModeloHorario


@dataclass(frozen=True)
class Progreso:
    fase: str
    soluciones: int
    mejor_objetivo: float | None
    cota: float | None
    tiempo_s: float


@dataclass
class OpcionesResolucion:
    tiempo_limite_s: float = 300.0
    hilos: int = 8
    semilla: int = 0
    base: list[Colocacion] | None = None
    """Horario de partida: se usa como pista (y, desde F4, para B9)."""
    vecindario: set[int] | None = None
    """Clases libres; las demás se fijan como en `base` (reparación, §12.4)."""
    fijar: list[Colocacion] = field(default_factory=list)
    """Colocaciones obligatorias además de las asignaciones fijas de los datos."""


@dataclass
class ResultadoResolucion:
    estado: EstadoSolucion
    colocaciones: list[Colocacion]
    tiempo_s: float
    tiempo_primera_s: float | None = None
    penalizaciones: dict[str, float] = field(default_factory=dict)
    penalizaciones_son_cota: bool = False
    mensaje: str = ""

    @property
    def tiene_solucion(self) -> bool:
        return bool(self.colocaciones)


class _Escucha(cp_model.CpSolverSolutionCallback):
    def __init__(self, resolutor: "Resolutor", fase: str) -> None:
        super().__init__()
        self.resolutor = resolutor
        self.fase = fase
        self.soluciones = 0

    def on_solution_callback(self) -> None:
        self.soluciones += 1
        self.resolutor._informar(self.fase, self.soluciones, None, None)
        if self.resolutor.cancelado:
            self.stop_search()


class Resolutor:
    def __init__(
        self,
        datos: DatosEscuela,
        opciones: OpcionesResolucion | None = None,
        al_progresar: Callable[[Progreso], None] | None = None,
    ) -> None:
        self.datos = datos
        self.opciones = opciones or OpcionesResolucion(
            tiempo_limite_s=datos.configuracion.tiempo_limite_s, hilos=datos.configuracion.hilos
        )
        self.al_progresar = al_progresar
        self.cancelado = False
        self._solver: cp_model.CpSolver | None = None
        self._candado = threading.Lock()
        self._inicio = 0.0

    def cancelar(self) -> None:
        """Detiene la búsqueda en curso (seguro desde otro hilo)."""
        self.cancelado = True
        with self._candado:
            if self._solver is not None:
                self._solver.stop_search()

    def _informar(
        self, fase: str, soluciones: int, mejor: float | None, cota: float | None
    ) -> None:
        if self.al_progresar:
            self.al_progresar(
                Progreso(fase, soluciones, mejor, cota, time.monotonic() - self._inicio)
            )

    def _fijaciones(self) -> list[Colocacion]:
        fijar = list(self.opciones.fijar)
        if self.opciones.base is not None and self.opciones.vecindario is not None:
            fijar += [c for c in self.opciones.base if c.clase_id not in self.opciones.vecindario]
        return fijar

    def construir(self, calendario: Calendario | None = None) -> ModeloHorario:
        constructor = ConstructorModelo(self.datos, calendario, fijar=self._fijaciones())
        horario = constructor.construir()
        self._pistas(horario, self.opciones.base or [])
        return horario

    @staticmethod
    def _pistas(horario: ModeloHorario, base: Iterable[Colocacion]) -> None:
        elegidas = {(c.clase_id, c.franja_id) for c in base}
        if not elegidas:
            return
        for (clase_id, franja_id), z in horario.z.items():
            horario.modelo.add_hint(z, (clase_id, franja_id) in elegidas)

    def resolver(self) -> ResultadoResolucion:
        self._inicio = time.monotonic()
        self._informar("construyendo", 0, None, None)
        horario = self.construir()
        construccion = time.monotonic() - self._inicio
        restante = max(1.0, self.opciones.tiempo_limite_s - construccion)

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = restante
        solver.parameters.num_workers = max(1, self.opciones.hilos)
        solver.parameters.random_seed = self.opciones.semilla
        solver.parameters.stop_after_first_solution = True
        with self._candado:
            self._solver = solver
        if self.cancelado:
            return ResultadoResolucion(EstadoSolucion.CANCELADO, [], self._transcurrido())
        escucha = _Escucha(self, "factibilidad")
        estado = solver.solve(horario.modelo, escucha)
        with self._candado:
            self._solver = None
        tiempo = self._transcurrido()

        if estado in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            colocaciones = horario.colocaciones(solver)
            return ResultadoResolucion(
                EstadoSolucion.CANCELADO if self.cancelado else EstadoSolucion.FACTIBLE,
                colocaciones,
                tiempo,
                tiempo_primera_s=tiempo,
            )
        if estado == cp_model.INFEASIBLE:
            return ResultadoResolucion(
                EstadoSolucion.INFACTIBLE, [], tiempo, mensaje="El problema no tiene solución."
            )
        if estado == cp_model.MODEL_INVALID:
            raise RuntimeError(f"Modelo inválido: {horario.modelo.validate()}")
        return ResultadoResolucion(
            EstadoSolucion.CANCELADO if self.cancelado else EstadoSolucion.SIN_SOLUCION_EN_TIEMPO,
            [],
            tiempo,
            mensaje="No se encontró una solución en el tiempo disponible.",
        )

    def _transcurrido(self) -> float:
        return time.monotonic() - self._inicio


def resolver(
    datos: DatosEscuela, opciones: OpcionesResolucion | None = None
) -> ResultadoResolucion:
    return Resolutor(datos, opciones).resolver()
