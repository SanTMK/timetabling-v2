"""Creado con Claude.

Reajuste del horario vigente (§13.2): resuelve con el vigente como **base** (pista + B9), así se
conserva lo más posible. La base nunca vuelve infactible el problema: solo pesa en el objetivo.
Si el vigente está desactualizado, cada clase guardada se mapea a la franja actual de mayor
traslape; las que no se pueden mapear se cuentan como «sin correspondencia».
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from timetabling.dominio.comparacion import Comparacion, comparar
from timetabling.dominio.modelos import DatosEscuela, Solucion
from timetabling.nucleo.resolver import OpcionesResolucion, Progreso, Resolutor
from timetabling.nucleo.validacion import hay_errores, validar
from timetabling.persistencia.migraciones import ErrorProyecto
from timetabling.persistencia.repositorio import Repositorio
from timetabling.servicios.generacion import (
    ErrorValidacion,
    ResultadoGeneracion,
    generar_en_memoria,
    opciones_de,
)
from timetabling.servicios.soluciones import Mapeo, mapear_solucion


class ErrorReajuste(ErrorProyecto):
    """No hay horario vigente que reajustar."""


@dataclass
class ResultadoReajuste:
    generacion: ResultadoGeneracion
    mapeo: Mapeo
    comparacion: Comparacion | None = None


def preparar_reajuste(
    datos: DatosEscuela, vigente: Solucion, opciones: OpcionesResolucion
) -> tuple[OpcionesResolucion, Mapeo]:
    """Opciones con el vigente (mapeado a las franjas actuales) como base."""
    mapeo = mapear_solucion(vigente, datos)
    opciones.base = mapeo.colocaciones
    return opciones, mapeo


def completar_solucion_de_reajuste(solucion: Solucion, vigente: Solucion, mapeo: Mapeo) -> Solucion:
    """Nombre, nota y `base_id` de la solución reajustada (§13.5)."""
    nota = f"Reajuste a partir de «{vigente.nombre}» (id {vigente.id})."
    if mapeo.por_traslape:
        nota += " El vigente estaba desactualizado: se mapeó por traslape."
    if mapeo.sin_correspondencia:
        nota += f" {len(mapeo.sin_correspondencia)} clases sin correspondencia."
    return solucion.model_copy(
        update={
            "nombre": f"Reajuste de «{vigente.nombre}»",
            "nota": nota,
            "base_id": vigente.id,
        }
    )


def reajustar_en_memoria(
    datos: DatosEscuela,
    vigente: Solucion,
    opciones: OpcionesResolucion,
    al_progresar: Callable[[Progreso], None] | None = None,
    resolutor: Resolutor | None = None,
) -> ResultadoReajuste:
    opciones, mapeo = preparar_reajuste(datos, vigente, opciones)
    generacion = generar_en_memoria(datos, opciones, al_progresar, resolutor)
    comparacion = None
    if generacion.solucion is not None:
        generacion.solucion = completar_solucion_de_reajuste(generacion.solucion, vigente, mapeo)
        comparacion = comparar(vigente, generacion.solucion)
    return ResultadoReajuste(generacion, mapeo, comparacion)


def reajustar(
    ruta: Path | str,
    tiempo_limite_s: float | None = None,
    hilos: int | None = None,
    al_progresar: Callable[[Progreso], None] | None = None,
) -> ResultadoReajuste:
    """Reajusta el vigente del proyecto y guarda el resultado (no lo marca vigente)."""
    with Repositorio.abrir(ruta) as repo:
        datos = repo.cargar_datos()
        ident = repo.solucion_vigente_id()
        if ident is None:
            raise ErrorReajuste("No hay un horario vigente que reajustar: marque uno primero.")
        vigente = repo.cargar_solucion(ident)
    problemas = validar(datos)
    if hay_errores(problemas):
        raise ErrorValidacion(problemas)
    resultado = reajustar_en_memoria(
        datos.model_copy(deep=True), vigente, opciones_de(datos, tiempo_limite_s, hilos),
        al_progresar,
    )  # fmt: skip
    if resultado.generacion.solucion is not None:
        with Repositorio.abrir(ruta, respaldo_diario=False) as repo:
            resultado.generacion.solucion = repo.guardar_solucion(resultado.generacion.solucion)
    return resultado
