"""Creado con Claude.

Exportación a Excel (§16.1) con XlsxWriter: Resumen, una hoja por grupo, por profesor con
clases y por tipo de espacio y nivel, CargaDocente, Cambios (opcional) y Leyenda. Color por
asignatura con texto en contraste, recesos en gris combinados, impresión carta horizontal
ajustada a una página.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import xlsxwriter
from xlsxwriter.workbook import Workbook
from xlsxwriter.worksheet import Worksheet

from timetabling.dominio.colores import GRIS_RECESO, color_texto
from timetabling.dominio.cuadricula import Cuadricula, Disposicion
from timetabling.dominio.estadisticas import carga_docente
from timetabling.dominio.modelos import NOMBRES_CRITERIOS, DatosEscuela, Solucion
from timetabling.dominio.tiempo import NOMBRES_DIAS
from timetabling.exportacion.estilos import nombre_hoja

NOMBRES_RESUMEN: dict[str, str] = {**NOMBRES_CRITERIOS, "total": "Penalización total"}


@dataclass(frozen=True)
class FilaCambio:
    """Una diferencia respecto al vigente (la llena el reajuste, §13)."""

    clase: str
    antes: str
    despues: str
    tipo: str


class _Libro:
    def __init__(self, ruta: Path, escuela: str) -> None:
        self.libro: Workbook = xlsxwriter.Workbook(str(ruta))
        self.escuela = escuela
        self.usados: set[str] = set()
        self._formatos: dict[tuple[Any, ...], Any] = {}
        self.fecha = datetime.now().strftime("%d/%m/%Y %H:%M")

    def formato(self, **propiedades: Any) -> Any:
        clave = tuple(sorted(propiedades.items()))
        if clave not in self._formatos:
            base = {"font_size": 9, "border": 1, "valign": "vcenter", "text_wrap": True}
            self._formatos[clave] = self.libro.add_format(base | propiedades)
        return self._formatos[clave]

    def hoja(self, titulo: str) -> Worksheet:
        hoja = self.libro.add_worksheet(nombre_hoja(titulo, self.usados))
        hoja.set_landscape()
        hoja.set_paper(1)  # carta
        hoja.fit_to_pages(1, 1)
        hoja.set_margins(left=0.25, right=0.25, top=0.25, bottom=0.25)
        escuela = self.escuela.replace("&", "&&")
        hoja.set_header(f"&L&B{escuela}&R&A", {"margin": 0.1})
        hoja.set_footer(f"&L{self.fecha}&RPágina &P de &N", {"margin": 0.1})
        return hoja

    def cerrar(self) -> None:
        self.libro.close()


def _escribir_cuadricula(libro: _Libro, hoja: Worksheet, cuadricula: Cuadricula) -> None:
    titulo = libro.formato(bold=True, font_size=12, border=0, text_wrap=False)
    encabezado = libro.formato(bold=True, align="center", bg_color="#EEEEEE")
    hora = libro.formato(bold=True, align="center", font_size=8)
    vacio = libro.formato()
    hoja.write(0, 0, cuadricula.titulo, titulo)
    if cuadricula.subtitulo:
        hoja.write(0, 1, cuadricula.subtitulo, libro.formato(border=0, italic=True))
    hoja.write(1, 0, "Hora", encabezado)
    for j, dia in enumerate(cuadricula.dias):
        hoja.write(1, j + 1, NOMBRES_DIAS[dia], encabezado)
    hoja.set_column(0, 0, 12)
    hoja.set_column(1, len(cuadricula.dias), 22)
    fina = len(cuadricula.filas) > 30  # rejilla Δ de un profesor multinivel
    for i, fila in enumerate(cuadricula.filas):
        etiqueta = (
            fila.etiqueta if not fina else (fila.etiqueta_inicio if fila.inicio % 30 == 0 else "")
        )
        hoja.write(i + 2, 0, etiqueta, hora)
        hoja.set_row(i + 2, 12 if fina else 36)
        for j in range(len(cuadricula.dias)):
            hoja.write_blank(i + 2, j + 1, None, vacio)
    for celda in cuadricula.celdas:
        fila = celda.fila + 2
        columna = celda.columna + 1
        if celda.tipo == "receso":
            formato = libro.formato(align="center", bg_color=GRIS_RECESO, italic=True)
        else:
            formato = libro.formato(
                align="center",
                bg_color=celda.color,
                font_color=color_texto(celda.color),
                bold=celda.cambiada,
            )
        if celda.filas > 1 or celda.columnas > 1:
            hoja.merge_range(fila, columna, fila + celda.filas - 1, columna + celda.columnas - 1,
                             celda.texto, formato)  # fmt: skip
        else:
            hoja.write(fila, columna, celda.texto, formato)


def _resumen(libro: _Libro, solucion: Solucion) -> None:
    hoja = libro.hoja("Resumen")
    negrita = libro.formato(bold=True, border=0, text_wrap=False)
    normal = libro.formato(border=0, text_wrap=False)
    filas: list[tuple[str, Any]] = [
        ("Escuela", libro.escuela),
        ("Horario", solucion.nombre),
        ("Fecha", solucion.fecha.strftime("%d/%m/%Y %H:%M")),
        ("Estado", solucion.estado.value),
        ("Origen", solucion.origen),
        ("Tiempo (s)", round(solucion.tiempo_s, 1)),
    ]
    cota = " (cota superior)" if solucion.penalizaciones_son_cota else ""
    for criterio, nombre in NOMBRES_RESUMEN.items():
        if criterio in solucion.penalizaciones:
            filas.append((f"{criterio} {nombre}{cota}" if criterio != "total" else nombre + cota,
                          round(solucion.penalizaciones[criterio], 2)))  # fmt: skip
    if solucion.nota:
        filas.append(("Nota", solucion.nota))
    for i, (clave, valor) in enumerate(filas):
        hoja.write(i, 0, clave, negrita)
        hoja.write(i, 1, valor, normal)
    hoja.set_column(0, 0, 44)
    hoja.set_column(1, 1, 40)


def _carga(libro: _Libro, solucion: Solucion, datos: DatosEscuela) -> None:
    hoja = libro.hoja("CargaDocente")
    encabezado = libro.formato(bold=True, align="center", bg_color="#EEEEEE")
    normal = libro.formato()
    porcentaje = libro.formato(num_format="0.0")
    titulos = ["Profesor", "Minutos asignados", "Mínimo", "Máximo", "% del máximo",
               "Días con clase", "Minutos de hueco"]  # fmt: skip
    for j, titulo in enumerate(titulos):
        hoja.write(0, j, titulo, encabezado)
    for i, c in enumerate(carga_docente(solucion, datos), start=1):
        valores = [c.nombre, c.minutos, c.minimo, c.maximo]
        for j, valor in enumerate(valores):
            hoja.write(i, j, valor, normal)
        hoja.write(i, 4, round(c.porcentaje, 1), porcentaje)
        hoja.write(i, 5, c.dias, normal)
        hoja.write(i, 6, c.minutos_hueco, normal)
    hoja.set_column(0, 0, 26)
    hoja.set_column(1, 6, 14)


def _cambios(libro: _Libro, cambios: Sequence[FilaCambio]) -> None:
    hoja = libro.hoja("Cambios")
    encabezado = libro.formato(bold=True, align="center", bg_color="#EEEEEE")
    normal = libro.formato()
    for j, titulo in enumerate(["Clase", "Antes", "Después", "Cambio"]):
        hoja.write(0, j, titulo, encabezado)
    for i, cambio in enumerate(cambios, start=1):
        for j, valor in enumerate([cambio.clase, cambio.antes, cambio.despues, cambio.tipo]):
            hoja.write(i, j, valor, normal)
    hoja.set_column(0, 3, 30)


def _leyenda(libro: _Libro, solucion: Solucion) -> None:
    hoja = libro.hoja("Leyenda")
    encabezado = libro.formato(bold=True, align="center", bg_color="#EEEEEE")
    hoja.write(0, 0, "Asignatura", encabezado)
    hoja.write(0, 1, "Color", encabezado)
    colores = sorted({(a.asignatura_nombre, a.color) for a in solucion.asignaciones})
    for i, (asignatura, color) in enumerate(colores, start=1):
        hoja.write(i, 0, asignatura, libro.formato())
        hoja.write(i, 1, color, libro.formato(bg_color=color, font_color=color_texto(color)))
    hoja.write(len(colores) + 2, 0, "Marcas: 📌 bloqueada · ↻ cambiada · ⚠ conflicto",
               libro.formato(border=0, text_wrap=False))  # fmt: skip
    hoja.set_column(0, 1, 26)


def exportar_excel(
    datos: DatosEscuela,
    solucion: Solucion,
    ruta: Path | str,
    cambios: Sequence[FilaCambio] | None = None,
    disposicion: Disposicion | None = None,
) -> Path:
    """Escribe el libro de Excel del horario y devuelve la ruta."""
    ruta = Path(ruta)
    disposicion = disposicion or Disposicion(solucion, datos)
    libro = _Libro(ruta, datos.configuracion.nombre_escuela)
    try:
        _resumen(libro, solucion)
        for grupo in disposicion.grupos():
            _escribir_cuadricula(libro, libro.hoja(grupo), disposicion.por_grupo(grupo))
        for profesor in disposicion.profesores():
            _escribir_cuadricula(libro, libro.hoja(profesor), disposicion.por_profesor(profesor))
        for tipo, nivel_id in disposicion.espacios():
            titulo = f"{tipo} - {disposicion.nombre_nivel(nivel_id)}"
            _escribir_cuadricula(libro, libro.hoja(titulo), disposicion.por_espacio(tipo, nivel_id))
        _carga(libro, solucion, datos)
        if cambios is not None:
            _cambios(libro, cambios)
        _leyenda(libro, solucion)
    finally:
        libro.cerrar()
    return ruta
