"""Creado con Claude.

Caso de uso «Generar horario» (§11.1, §11.2): valida, resuelve, verifica y guarda la solución.
La resolución recibe una copia de los datos, así que puede correr en otro hilo.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from timetabling.dominio.modelos import DatosEscuela, EstadoSolucion, Solucion
from timetabling.nucleo.diagnostico import Diagnostico, diagnosticar
from timetabling.nucleo.objetivo import pesos, total_ponderado
from timetabling.nucleo.resolver import (
    OpcionesResolucion,
    Progreso,
    Resolutor,
    ResultadoResolucion,
)
from timetabling.nucleo.validacion import Problema, hay_errores, validar
from timetabling.nucleo.verificador import verificar
from timetabling.persistencia.migraciones import ErrorProyecto
from timetabling.persistencia.repositorio import Repositorio
from timetabling.servicios.soluciones import a_solucion


class ErrorValidacion(ErrorProyecto):
    """Los datos tienen errores de validación (§10): no se resuelve."""

    def __init__(self, problemas: list[Problema]) -> None:
        self.problemas = problemas
        errores = [p for p in problemas if p.es_error]
        super().__init__(f"Hay {len(errores)} errores de validación; corríjalos antes de generar.")


@dataclass
class ResultadoGeneracion:
    resolucion: ResultadoResolucion
    solucion: Solucion | None = None
    """La solución guardada (si hubo horario)."""
    advertencias: list[Problema] = field(default_factory=list)
    diagnostico: Diagnostico | None = None
    """Solo si el resultado es INFACTIBLE (§11.3)."""


def nombre_por_defecto(resultado: ResultadoResolucion) -> str:
    return f"Generado ({resultado.estado.value.lower().replace('_', ' ')})"


def resolver_y_armar(
    datos: DatosEscuela,
    opciones: OpcionesResolucion,
    al_progresar: Callable[[Progreso], None] | None = None,
    resolutor: Resolutor | None = None,
) -> tuple[ResultadoResolucion, Solucion | None]:
    """Resuelve, verifica y arma la `Solucion` (sin guardarla)."""
    resolutor = resolutor or Resolutor(datos, opciones, al_progresar)
    resultado = resolutor.resolver()
    if not resultado.colocaciones:
        return resultado, None
    verificacion = verificar(datos, resultado.colocaciones, calendario=resolutor.calendario)
    estado = resultado.estado if verificacion.valida else EstadoSolucion.INVALIDA
    penalizaciones = dict(resultado.penalizaciones)
    penalizaciones["total"] = total_ponderado(
        penalizaciones, pesos(datos.configuracion.criterios, con_base=opciones.base is not None)
    )
    solucion = a_solucion(
        datos,
        resultado.colocaciones,
        nombre=nombre_por_defecto(resultado),
        estado=estado,
        origen="generado",
        calendario=resolutor.calendario,
        tiempo_s=resultado.tiempo_s,
        penalizaciones=penalizaciones,
        penalizaciones_son_cota=resultado.penalizaciones_son_cota,
        violaciones=verificacion.violaciones,
    )
    return resultado, solucion


def generar_en_memoria(
    datos: DatosEscuela,
    opciones: OpcionesResolucion,
    al_progresar: Callable[[Progreso], None] | None = None,
    resolutor: Resolutor | None = None,
    diagnostico_s: float = 60.0,
) -> ResultadoGeneracion:
    """Resuelve, verifica, arma la `Solucion` (sin guardarla) y, si es infactible, diagnostica.
    No toca archivos: la interfaz lo ejecuta en otro hilo con una copia de los datos."""
    resultado, solucion = resolver_y_armar(datos, opciones, al_progresar, resolutor)
    diagnostico = None
    if resultado.estado is EstadoSolucion.INFACTIBLE and diagnostico_s > 0:
        if al_progresar:
            al_progresar(Progreso("diagnostico", 0, None, None, resultado.tiempo_s))
        diagnostico = diagnosticar(datos, total_s=diagnostico_s)
    return ResultadoGeneracion(resultado, solucion, [], diagnostico)


def opciones_de(datos: DatosEscuela, tiempo_limite_s: float | None = None,
                hilos: int | None = None) -> OpcionesResolucion:  # fmt: skip
    configuracion = datos.configuracion
    return OpcionesResolucion(
        tiempo_limite_s=tiempo_limite_s or configuracion.tiempo_limite_s,
        hilos=hilos or configuracion.hilos,
    )


def generar(
    ruta: Path | str,
    tiempo_limite_s: float | None = None,
    hilos: int | None = None,
    al_progresar: Callable[[Progreso], None] | None = None,
    diagnostico_s: float = 60.0,
) -> ResultadoGeneracion:
    """Genera un horario para el proyecto y lo guarda. Lanza `ErrorValidacion` si hay errores.
    Si el problema es infactible, adjunta el diagnóstico (con `diagnostico_s` de presupuesto)."""
    with Repositorio.abrir(ruta) as repo:
        datos = repo.cargar_datos()
    problemas = validar(datos)
    if hay_errores(problemas):
        raise ErrorValidacion(problemas)
    resultado = generar_en_memoria(
        datos.model_copy(deep=True), opciones_de(datos, tiempo_limite_s, hilos), al_progresar,
        diagnostico_s=diagnostico_s,
    )  # fmt: skip
    if resultado.solucion is not None:
        with Repositorio.abrir(ruta, respaldo_diario=False) as repo:
            resultado.solucion = repo.guardar_solucion(resultado.solucion)
    resultado.advertencias = [p for p in problemas if not p.es_error]
    return resultado
