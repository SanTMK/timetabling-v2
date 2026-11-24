"""Creado con Claude.

Resolución (§11.1). Etapa 1: factibilidad sin objetivo (`stop_after_first_solution`). Etapa 2:
optimización con el objetivo (§9) y la primera solución como pista. El tiempo de construcción
se descuenta del límite (mínimo 1 s de búsqueda por etapa). `cancelar()` detiene la búsqueda
desde otro hilo y conserva la mejor solución. Si la etapa 2 no termina, las penalizaciones son
cotas superiores.
"""

import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from timetabling.dominio.borrador import Colocacion
from timetabling.dominio.modelos import Criterios, DatosEscuela, EstadoSolucion
from timetabling.nucleo.franjas import Calendario
from timetabling.nucleo.modelo import ConstructorModelo, ModeloHorario
from timetabling.nucleo.objetivo import ESCALA_UNIDAD, ConstructorObjetivo, Objetivo, evaluar


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
    optimizar: bool = True
    """Con `False` solo se ejecuta la etapa de factibilidad."""
    criterios: Criterios | None = None
    """Prioridades a usar; por defecto, las de la configuración del proyecto."""
    horas: dict[int, int] | None = None
    """Horas a colocar por clase cuando no son las semanales (reparación de un borrador)."""


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
    def __init__(self, resolutor: "Resolutor", fase: str, con_objetivo: bool) -> None:
        super().__init__()
        self.resolutor = resolutor
        self.fase = fase
        self.con_objetivo = con_objetivo
        self.soluciones = 0

    def on_solution_callback(self) -> None:
        self.soluciones += 1
        mejor = cota = None
        if self.con_objetivo:
            mejor = self.objective_value / ESCALA_UNIDAD
            cota = self.best_objective_bound / ESCALA_UNIDAD
        self.resolutor._informar(self.fase, self.soluciones, mejor, cota)
        if self.resolutor.cancelado:
            self.stop_search()


class Resolutor:
    def __init__(
        self,
        datos: DatosEscuela,
        opciones: OpcionesResolucion | None = None,
        al_progresar: Callable[[Progreso], None] | None = None,
        calendario: Calendario | None = None,
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
        self.calendario = calendario or Calendario.de(datos)

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

    def construir(self) -> tuple[ModeloHorario, Objetivo | None]:
        constructor = ConstructorModelo(
            self.datos, self.calendario, fijar=self._fijaciones(), horas=self.opciones.horas
        )
        horario = constructor.construir()
        objetivo = None
        if self.opciones.optimizar:
            criterios = self.opciones.criterios or self.datos.configuracion.criterios
            objetivo = ConstructorObjetivo(constructor, criterios, self.opciones.base).construir()
        self._pistas(horario, self.opciones.base or [])
        return horario, objetivo

    @staticmethod
    def _pistas(horario: ModeloHorario, base: Iterable[Colocacion]) -> None:
        """Pista completa desde la base: dónde ocurre cada clase (z) y quién la da (x, y). Una
        pista solo de z deja libre al profesor y la primera solución se aleja de la base."""
        base = list(base)
        if not base:
            return
        elegidas = {(c.clase_id, c.franja_id) for c in base}
        con_profesor = {(c.clase_id, p, c.franja_id) for c in base for p in c.profesores}
        a_cargo = {(c.clase_id, p) for c in base for p in c.profesores}
        vistas: set[int] = set()
        for (clase_id, franja_id), z in horario.z.items():
            vistas.add(z.index)
            horario.modelo.add_hint(z, (clase_id, franja_id) in elegidas)
        for clave, x in horario.x.items():
            if x.index not in vistas:  # en las clases con profesor fijo, x es la misma z
                vistas.add(x.index)
                horario.modelo.add_hint(x, clave in con_profesor)
        for clave, y in horario.y.items():
            horario.modelo.add_hint(y, clave in a_cargo)

    def _solver_nuevo(self, segundos: float, primera: bool) -> cp_model.CpSolver:
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(1.0, segundos)
        solver.parameters.num_workers = max(1, self.opciones.hilos)
        solver.parameters.random_seed = self.opciones.semilla
        solver.parameters.stop_after_first_solution = primera
        with self._candado:
            self._solver = solver
        return solver

    def _soltar_solver(self) -> None:
        with self._candado:
            self._solver = None

    def resolver(self) -> ResultadoResolucion:
        self._inicio = time.monotonic()
        self._informar("construyendo", 0, None, None)
        horario, objetivo = self.construir()
        limite = self.opciones.tiempo_limite_s

        # Etapa 1: factibilidad sin objetivo.
        solver = self._solver_nuevo(limite - self._transcurrido(), primera=True)
        if self.cancelado:
            self._soltar_solver()
            return ResultadoResolucion(EstadoSolucion.CANCELADO, [], self._transcurrido())
        estado = solver.solve(horario.modelo, _Escucha(self, "factibilidad", False))
        self._soltar_solver()
        tiempo_primera = self._transcurrido()

        if estado == cp_model.INFEASIBLE:
            return ResultadoResolucion(
                EstadoSolucion.INFACTIBLE,
                [],
                tiempo_primera,
                mensaje="El problema no tiene solución.",
            )
        if estado == cp_model.MODEL_INVALID:
            raise RuntimeError(f"Modelo inválido: {horario.modelo.validate()}")
        if estado not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return ResultadoResolucion(
                EstadoSolucion.CANCELADO
                if self.cancelado
                else EstadoSolucion.SIN_SOLUCION_EN_TIEMPO,
                [],
                tiempo_primera,
                mensaje="No se encontró una solución en el tiempo disponible.",
            )

        colocaciones = horario.colocaciones(solver)
        optimo = objetivo is None or objetivo.vacio
        if not optimo and not self.cancelado and objetivo is not None:
            # Etapa 2: optimización con la primera solución como pista.
            modelo = horario.modelo
            modelo.clear_hints()
            # En las clases con profesores fijos, x y z son la misma variable: una pista por
            # variable (las repetidas invalidan el modelo).
            unicas = {
                v.index: v for v in [*horario.z.values(), *horario.x.values(), *horario.y.values()]
            }
            for var in unicas.values():
                modelo.add_hint(var, solver.boolean_value(var))
            modelo.minimize(objetivo.expresion)
            solver = self._solver_nuevo(limite - self._transcurrido(), primera=False)
            if not self.cancelado:
                estado = solver.solve(modelo, _Escucha(self, "optimizacion", True))
                if estado == cp_model.MODEL_INVALID:
                    self._soltar_solver()
                    raise RuntimeError(f"Modelo inválido: {modelo.validate()}")
                if estado in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                    colocaciones = horario.colocaciones(solver)
                    optimo = estado == cp_model.OPTIMAL
            self._soltar_solver()

        if self.cancelado:
            estado_final = EstadoSolucion.CANCELADO
        else:
            estado_final = EstadoSolucion.OPTIMO if optimo else EstadoSolucion.FACTIBLE
        valores = evaluar(self.datos, colocaciones, self.calendario, self.opciones.base)
        return ResultadoResolucion(
            estado_final,
            colocaciones,
            self._transcurrido(),
            tiempo_primera_s=tiempo_primera,
            penalizaciones=valores,
            penalizaciones_son_cota=not optimo,
        )

    def _transcurrido(self) -> float:
        return time.monotonic() - self._inicio


def resolver(
    datos: DatosEscuela, opciones: OpcionesResolucion | None = None
) -> ResultadoResolucion:
    return Resolutor(datos, opciones).resolver()
