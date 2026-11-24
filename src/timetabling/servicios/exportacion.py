"""Creado con Claude.

Caso de uso «Exportar»: abre el proyecto, carga la solución y la escribe en Excel o PDF (según
la extensión de la salida; el PDF lleva una página por grupo y por profesor).
"""

from pathlib import Path

from timetabling.exportacion.excel import exportar_excel
from timetabling.persistencia.migraciones import ErrorProyecto
from timetabling.persistencia.repositorio import Repositorio


class ErrorExportacion(ErrorProyecto):
    """No se pudo exportar (formato no disponible o solución inexistente)."""


def exportar(proyecto: Path | str, solucion_id: int, salida: Path | str) -> Path:
    salida = Path(salida)
    sufijo = salida.suffix.lower()
    if sufijo not in (".xlsx", ".pdf"):
        raise ErrorExportacion("La salida debe terminar en .xlsx (o .pdf).")
    with Repositorio.abrir(proyecto, respaldo_diario=False) as repo:
        try:
            solucion = repo.cargar_solucion(solucion_id)
        except KeyError as error:
            raise ErrorExportacion(f"No existe la solución {solucion_id}.") from error
        datos = repo.cargar_datos()
    if sufijo == ".pdf":
        from timetabling.exportacion.pdf import exportar_pdf

        return exportar_pdf(datos, solucion, salida)[0]
    return exportar_excel(datos, solucion, salida)
