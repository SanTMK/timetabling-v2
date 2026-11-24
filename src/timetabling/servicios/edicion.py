"""Creado con Claude.

Edición de borradores (§12). `EdicionBorrador` mantiene el borrador abierto, sus índices de
conflictos y la persistencia: cada operación se guarda al instante en una transacción. También
ofrece «Completar el resto», la reparación local, sugerir lugar y «Validar y guardar como
definitivo».
"""

from collections.abc import Callable
from dataclasses import dataclass

from timetabling.dominio.borrador import Borrador, Colocacion, Operacion
from timetabling.dominio.modelos import EstadoSolucion, OrigenSolucion, Solucion
from timetabling.nucleo.conflictos import Conflictos
from timetabling.nucleo.objetivo import evaluar, pesos, total_ponderado
from timetabling.nucleo.reparacion import (
    Propuesta,
    Sugerencia,
    colocar_y_reacomodar,
    sugerir_lugares,
)
from timetabling.nucleo.resolver import (
    OpcionesResolucion,
    Progreso,
    Resolutor,
    ResultadoResolucion,
)
from timetabling.nucleo.verificador import ResultadoVerificacion, verificar
from timetabling.persistencia.migraciones import ErrorProyecto
from timetabling.servicios.sesion import SesionProyecto
from timetabling.servicios.soluciones import a_colocaciones, a_solucion


class ErrorEdicion(ErrorProyecto):
    """La solución no se puede editar (no es borrador o está desactualizada)."""


@dataclass(frozen=True)
class EstadoBorrador:
    pendientes: int
    conflictos: int
    penalizacion: float
    violaciones: list[str]


class EdicionBorrador:
    def __init__(self, sesion: SesionProyecto, solucion_id: int) -> None:
        self.sesion = sesion
        solucion = sesion.cargar_solucion(solucion_id)
        if solucion.estado is not EstadoSolucion.BORRADOR:
            raise ErrorEdicion("Solo se pueden editar los borradores; edite una copia.")
        if sesion.desactualizada(solucion):
            raise ErrorEdicion(
                "El borrador se hizo con otra configuración de niveles; edite una copia ajustada "
                "(disponible con el reajuste)."
            )
        self.solucion = solucion
        self.datos = sesion.datos
        self.calendario = sesion.calendario
        self.borrador = Borrador.de(a_colocaciones(solucion))
        self.conflictos = Conflictos(self.datos, self.calendario).cargar(self.borrador.colocaciones)
        self._base: set[tuple[int, str]] | None = None

    # ------------------------------------------------------------------ edición

    def aplicar(self, operacion: Operacion) -> None:
        """Aplica la operación, actualiza los índices y guarda al instante."""
        self.borrador.aplicar(operacion)
        for c in operacion.quitar:
            self.conflictos.quitar(c)
        for c in operacion.poner:
            self.conflictos.agregar(c)
        self.guardar()

    def guardar(self) -> None:
        solucion = a_solucion(
            self.datos,
            self.borrador.colocaciones,
            nombre=self.solucion.nombre,
            estado=EstadoSolucion.BORRADOR,
            origen=self.solucion.origen,
            calendario=self.calendario,
            nota=self.solucion.nota,
            base_id=self.solucion.base_id,
        ).model_copy(update={"id": self.solucion.id})
        self.solucion = self.sesion.repo.guardar_solucion(solucion)

    def renombrar(self, nombre: str) -> None:
        self.solucion = self.solucion.model_copy(update={"nombre": nombre})
        self.guardar()

    # ------------------------------------------------------------------ consultas

    def estado(self) -> EstadoBorrador:
        """Pendientes, conflictos duros y penalización total en vivo (sin solver)."""
        verificacion = verificar(
            self.datos, self.borrador.colocaciones, parcial=True, calendario=self.calendario
        )
        valores = evaluar(self.datos, self.borrador.colocaciones, self.calendario)
        total = total_ponderado(valores, pesos(self.datos.configuracion.criterios))
        return EstadoBorrador(
            pendientes=sum(self.borrador.pendientes(self.datos).values()),
            conflictos=len(verificacion.violaciones),
            penalizacion=total,
            violaciones=[v.mensaje for v in verificacion.violaciones],
        )

    def verificacion(self) -> ResultadoVerificacion:
        return verificar(
            self.datos, self.borrador.colocaciones, parcial=True, calendario=self.calendario
        )

    def cambiadas(self) -> set[tuple[int, str]]:
        """(clase, franja) distintas de la solución de la que partió el borrador (↻)."""
        if self.solucion.base_id is None:
            return set()
        if self._base is None:
            try:
                base = self.sesion.cargar_solucion(self.solucion.base_id)
            except KeyError:
                self._base = set()
            else:
                self._base = (
                    set()
                    if self.sesion.desactualizada(base)
                    else {(c.clase_id, c.franja_id) for c in a_colocaciones(base)}
                )
        if not self._base:
            return set()
        return {(c.clase_id, c.franja_id) for c in self.borrador.colocaciones} - self._base

    # ------------------------------------------------------------------ asistencia

    def reacomodar(self, nueva: Colocacion, quitar: Colocacion | None = None) -> Propuesta:
        return colocar_y_reacomodar(
            self.datos, self.borrador.colocaciones, nueva, quitar, calendario=self.calendario
        )

    def sugerir(self, clase_id: int, cuantos: int = 3) -> list[Sugerencia]:
        return sugerir_lugares(
            self.datos, self.borrador.colocaciones, clase_id, cuantos, self.conflictos
        )

    def resolutor_completar(
        self,
        tiempo_limite_s: float | None = None,
        al_progresar: Callable[[Progreso], None] | None = None,
    ) -> Resolutor:
        """«Completar el resto» (§12.3): las bloqueadas entran fijas y las demás como base
        (pista + B9). El resolutor trabaja sobre una copia: puede correr en otro hilo."""
        opciones = OpcionesResolucion(
            tiempo_limite_s=tiempo_limite_s or self.datos.configuracion.tiempo_limite_s,
            hilos=self.datos.configuracion.hilos,
            base=[c for c in self.borrador.colocaciones if not c.bloqueada],
            fijar=self.borrador.bloqueadas(),
        )
        return Resolutor(self.datos.model_copy(deep=True), opciones, al_progresar)

    def guardar_completado(self, resultado: ResultadoResolucion) -> Solucion | None:
        """Guarda el resultado de completar como un **nuevo** borrador (el original no se toca).
        Debe llamarse en el hilo que abrió el proyecto."""
        if not resultado.colocaciones:
            return None
        fijas = {(c.clase_id, c.franja_id) for c in self.borrador.bloqueadas()}
        colocaciones = [
            Colocacion(c.clase_id, c.franja_id, c.profesores, (c.clase_id, c.franja_id) in fijas)
            for c in resultado.colocaciones
        ]
        nuevo = a_solucion(
            self.datos,
            colocaciones,
            nombre=f"{self.solucion.nombre} (completado)",
            estado=EstadoSolucion.BORRADOR,
            origen="editado",
            calendario=self.calendario,
            base_id=self.solucion.id,
            nota=f"Completado a partir de «{self.solucion.nombre}».",
        )
        return self.sesion.guardar_solucion(nuevo)

    def completar(self, tiempo_limite_s: float | None = None) -> Solucion | None:
        """Completa y guarda en el mismo hilo (línea de comandos y pruebas)."""
        return self.guardar_completado(self.resolutor_completar(tiempo_limite_s).resolver())

    def validar_definitivo(self) -> ResultadoVerificacion:
        """«Validar y guardar como definitivo» (§12.1): si pasa el verificador completo, el
        estado cambia a FACTIBLE y se guardan las penalizaciones."""
        verificacion = verificar(self.datos, self.borrador.colocaciones, calendario=self.calendario)
        if verificacion.valida:
            valores = evaluar(self.datos, self.borrador.colocaciones, self.calendario)
            tabla = pesos(self.datos.configuracion.criterios)
            valores["total"] = total_ponderado(valores, tabla)
            definitivo = a_solucion(
                self.datos,
                self.borrador.colocaciones,
                nombre=self.solucion.nombre,
                estado=EstadoSolucion.FACTIBLE,
                origen=self.solucion.origen,
                calendario=self.calendario,
                penalizaciones=valores,
                nota=self.solucion.nota,
                base_id=self.solucion.base_id,
            ).model_copy(update={"id": self.solucion.id})
            self.solucion = self.sesion.guardar_solucion(definitivo)
        return verificacion


def nuevo_borrador(
    sesion: SesionProyecto,
    nombre: str = "Borrador",
    copia_de: int | None = None,
    origen: OrigenSolucion | None = None,
) -> Solucion:
    """Un borrador vacío o la copia de una solución (las generadas no se editan, §12.1)."""
    colocaciones: list[Colocacion] = []
    base_id = None
    if copia_de is not None:
        original = sesion.cargar_solucion(copia_de)
        if sesion.desactualizada(original):
            raise ErrorEdicion(
                "Esa solución se hizo con otra configuración de niveles; su copia ajustada llega "
                "con el reajuste."
            )
        colocaciones = a_colocaciones(original)
        base_id = original.id
        nombre = nombre if nombre != "Borrador" else f"Copia de {original.nombre}"
    solucion = a_solucion(
        sesion.datos,
        colocaciones,
        nombre=nombre,
        estado=EstadoSolucion.BORRADOR,
        origen=origen or ("editado" if copia_de is not None else "manual"),
        calendario=sesion.calendario,
        base_id=base_id,
    )
    return sesion.guardar_solucion(solucion)


def bloqueadas_para_generar(sesion: SesionProyecto) -> tuple[list[Colocacion], str]:
    """Clases bloqueadas que entran como fijas al generar (§12.5): las del borrador de trabajo
    más reciente o, si no hay, las del vigente."""
    borradores = [
        s for s in sesion.soluciones()
        if s.estado is EstadoSolucion.BORRADOR and not sesion.desactualizada(s)
    ]  # fmt: skip
    candidatas = sorted(borradores, key=lambda s: (s.fecha, s.id), reverse=True)
    vigente = sesion.vigente()
    if vigente is not None and not sesion.desactualizada(vigente):
        candidatas.append(vigente)
    for resumen in candidatas:
        bloqueadas = [c for c in a_colocaciones(sesion.cargar_solucion(resumen.id)) if c.bloqueada]
        if bloqueadas:
            return bloqueadas, resumen.nombre
    return [], ""
