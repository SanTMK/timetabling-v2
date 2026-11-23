"""Creado con Claude.

Casos de uso sobre un proyecto: cargar sus datos y validarlos.
"""

from pathlib import Path

from timetabling.dominio.modelos import DatosEscuela
from timetabling.nucleo.validacion import Problema, validar
from timetabling.persistencia.repositorio import Repositorio


def cargar_datos(ruta: Path | str) -> DatosEscuela:
    with Repositorio.abrir(ruta) as repo:
        return repo.cargar_datos()


def validar_proyecto(ruta: Path | str) -> list[Problema]:
    """Valida los datos del proyecto (§10). Los errores van primero."""
    problemas = validar(cargar_datos(ruta))
    return sorted(problemas, key=lambda p: not p.es_error)
