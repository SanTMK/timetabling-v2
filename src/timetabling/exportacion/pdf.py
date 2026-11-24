"""Creado con Claude.

Exportación a PDF (§16.2) con `QPdfWriter`, usando la misma disposición que la interfaz y
Excel (`dominio/cuadricula.py`): una página por grupo o por profesor (se elige qué incluir) y el
reporte «Suplencias del día». Carta horizontal, márgenes de 0,25", encabezado con la escuela y
el título, pie con la fecha y «Página n de N».

Qt necesita una aplicación para dibujar texto: si no hay ninguna (línea de comandos), se crea
una `QApplication` (y no solo una `QGuiApplication`, para que después se puedan crear widgets
en el mismo proceso); en Linux sin pantalla, con la plataforma «offscreen».
"""

import os
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import QMarginsF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QPen,
)
from PySide6.QtWidgets import QApplication

from timetabling.dominio.colores import GRIS_RECESO, color_texto
from timetabling.dominio.cuadricula import Celda, Cuadricula, Disposicion
from timetabling.dominio.modelos import Ausencia, DatosEscuela, Solucion
from timetabling.dominio.tiempo import NOMBRES_DIAS, texto_rango
from timetabling.exportacion.excel import FilaSuplencia, texto_fecha

RESOLUCION = 144  # puntos por pulgada del dibujo (suficiente para texto nítido)
_app: QApplication | None = None


def asegurar_aplicacion() -> None:
    """Crea una `QApplication` si no hay ninguna (exportar desde la línea de comandos)."""
    global _app
    if QGuiApplication.instance() is not None:
        return
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    _app = QApplication([])


@dataclass
class _Pagina:
    titulo: str
    cuadricula: Cuadricula | None = None


class _Documento:
    """Un PDF carta horizontal con encabezado y pie en cada página."""

    def __init__(self, ruta: Path, escuela: str, total: int) -> None:
        asegurar_aplicacion()
        self.escritor = QPdfWriter(str(ruta))
        self.escritor.setResolution(RESOLUCION)
        self.escritor.setCreator("timetabling")
        self.escritor.setTitle(escuela)
        self.escritor.setPageLayout(QPageLayout(
            QPageSize(QPageSize.PageSizeId.Letter), QPageLayout.Orientation.Landscape,
            QMarginsF(6.35, 6.35, 6.35, 6.35), QPageLayout.Unit.Millimeter,
        ))  # fmt: skip
        self.pintor = QPainter()
        if not self.pintor.begin(self.escritor):
            raise OSError(f"No se pudo escribir «{ruta}».")
        self.escuela = escuela
        self.total = total
        self.numero = 0
        self.fecha = datetime.now().strftime("%d/%m/%Y %H:%M")

    def pagina(self, titulo: str) -> QRectF:
        """Empieza una página y devuelve el rectángulo libre entre encabezado y pie."""
        if self.numero:
            self.escritor.newPage()
        self.numero += 1
        p = self.pintor
        ancho = self.escritor.width()
        alto = self.escritor.height()
        p.setPen(QColor("#555555"))
        p.setFont(_fuente(8))
        linea = QFontMetricsF(p.font()).height()
        p.drawText(QRectF(0, 0, ancho, linea), Qt.AlignmentFlag.AlignLeft, self.escuela)
        p.drawText(QRectF(0, 0, ancho, linea), Qt.AlignmentFlag.AlignRight, titulo)
        p.drawText(QRectF(0, alto - linea, ancho, linea), Qt.AlignmentFlag.AlignLeft, self.fecha)
        p.drawText(QRectF(0, alto - linea, ancho, linea), Qt.AlignmentFlag.AlignRight,
                   f"Página {self.numero} de {self.total}")  # fmt: skip
        return QRectF(0, linea * 1.6, ancho, alto - linea * 3.2)

    def cerrar(self) -> None:
        self.pintor.end()


def _fuente(puntos: float, negrita: bool = False, cursiva: bool = False) -> QFont:
    fuente = QFont()
    fuente.setPointSizeF(puntos)
    fuente.setBold(negrita)
    fuente.setItalic(cursiva)
    return fuente


def _texto_ajustado(p: QPainter, rect: QRectF, texto: str, puntos: float,
                    negrita: bool = False, cursiva: bool = False) -> None:  # fmt: skip
    """Texto centrado que se achica hasta caber en el rectángulo (mínimo 4,5 pt)."""
    margen = rect.adjusted(3, 2, -3, -2)
    banderas = int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap)
    tam = puntos
    while tam > 4.5:
        fuente = _fuente(tam, negrita, cursiva)
        necesario = QFontMetricsF(fuente).boundingRect(margen, banderas, texto)
        if necesario.height() <= margen.height() and necesario.width() <= margen.width():
            break
        tam -= 0.5
    p.setFont(_fuente(tam, negrita, cursiva))
    p.drawText(margen, banderas, texto)


def _dibujar_cuadricula(p: QPainter, area: QRectF, cuadricula: Cuadricula) -> None:
    p.setPen(QColor("#000000"))
    p.setFont(_fuente(13, negrita=True))
    alto_titulo = QFontMetricsF(p.font()).height() * 1.4
    p.drawText(QRectF(area.left(), area.top(), area.width(), alto_titulo),
               int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
               cuadricula.titulo)  # fmt: skip
    if cuadricula.subtitulo:
        p.setFont(_fuente(9, cursiva=True))
        p.drawText(QRectF(area.left(), area.top(), area.width(), alto_titulo),
                   int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                   cuadricula.subtitulo)  # fmt: skip
    tabla = area.adjusted(0, alto_titulo, 0, 0)
    fina = len(cuadricula.filas) > 30  # rejilla Δ de un profesor multinivel
    ancho_hora = tabla.width() * (0.08 if not fina else 0.06)
    ancho_dia = (tabla.width() - ancho_hora) / max(1, len(cuadricula.dias))
    alto_encabezado = 22.0
    pesos = [0.45 if f.receso and not fina else 1.0 for f in cuadricula.filas]
    unidad = (tabla.height() - alto_encabezado) / max(1.0, sum(pesos))
    tops = [tabla.top() + alto_encabezado]
    for peso in pesos:
        tops.append(tops[-1] + peso * unidad)

    def x(columna: int) -> float:
        return tabla.left() + ancho_hora + columna * ancho_dia

    borde = QPen(QColor("#808080"))
    borde.setWidthF(0.8)
    p.setPen(borde)
    # Encabezado y columna de horas.
    p.fillRect(QRectF(tabla.left(), tabla.top(), tabla.width(), alto_encabezado),
               QColor("#EEEEEE"))  # fmt: skip
    p.drawRect(QRectF(tabla.left(), tabla.top(), ancho_hora, alto_encabezado))
    p.setPen(QColor("#000000"))
    _texto_ajustado(p, QRectF(tabla.left(), tabla.top(), ancho_hora, alto_encabezado), "Hora",
                    9, negrita=True)  # fmt: skip
    for j, dia in enumerate(cuadricula.dias):
        rect = QRectF(x(j), tabla.top(), ancho_dia, alto_encabezado)
        p.setPen(borde)
        p.drawRect(rect)
        p.setPen(QColor("#000000"))
        _texto_ajustado(p, rect, NOMBRES_DIAS[dia], 9, negrita=True)
    for i, fila in enumerate(cuadricula.filas):
        rect = QRectF(tabla.left(), tops[i], ancho_hora, tops[i + 1] - tops[i])
        p.setPen(borde if not fina else QPen(QColor("#DDDDDD")))
        p.drawRect(rect)
        etiqueta = fila.etiqueta
        if fina:
            etiqueta = fila.etiqueta_inicio if fila.inicio % 30 == 0 else ""
        p.setPen(QColor("#000000"))
        if etiqueta:
            _texto_ajustado(p, rect, etiqueta, 8, negrita=True)
        for j in range(len(cuadricula.dias)):
            p.setPen(borde if not fina else QPen(QColor("#DDDDDD")))
            p.drawRect(QRectF(x(j), tops[i], ancho_dia, tops[i + 1] - tops[i]))
    for celda in cuadricula.celdas:
        _dibujar_celda(p, celda, QRectF(
            x(celda.columna), tops[celda.fila], ancho_dia * celda.columnas,
            tops[celda.fila + celda.filas] - tops[celda.fila],
        ), borde)  # fmt: skip


def _dibujar_celda(p: QPainter, celda: Celda, rect: QRectF, borde: QPen) -> None:
    fondo = GRIS_RECESO if celda.tipo == "receso" else celda.color
    p.fillRect(rect, QColor(fondo))
    p.setPen(borde)
    p.drawRect(rect)
    p.setPen(QColor(color_texto(fondo)))
    texto = celda.texto.replace("📌", "[F]").replace("↻", "*").replace("⚠", "!")
    _texto_ajustado(p, rect, texto, 9, negrita=celda.cambiada, cursiva=celda.tipo == "receso")


def _elegidos(todos: list[str], pedidos: Iterable[str] | None) -> list[str]:
    if pedidos is None:
        return todos
    pedidos = set(pedidos)
    return [t for t in todos if t in pedidos]


def exportar_pdf(
    datos: DatosEscuela,
    solucion: Solucion,
    ruta: Path | str,
    grupos: Iterable[str] | None = None,
    profesores: Iterable[str] | None = None,
    disposicion: Disposicion | None = None,
) -> tuple[Path, int]:
    """Una página por grupo y por profesor. `grupos` y `profesores` eligen cuáles (`None` =
    todos, vacío = ninguno). Devuelve la ruta y el número de páginas."""
    ruta = Path(ruta)
    disposicion = disposicion or Disposicion(solucion, datos)
    paginas = [
        *[_Pagina(f"Grupo {g}", disposicion.por_grupo(g))
          for g in _elegidos(disposicion.grupos(), grupos)],
        *[_Pagina(f"Profesor {p}", disposicion.por_profesor(p))
          for p in _elegidos(disposicion.profesores(), profesores)],
    ]  # fmt: skip
    if not paginas:
        raise ValueError("Elija al menos un grupo o un profesor para el PDF.")
    documento = _Documento(ruta, datos.configuracion.nombre_escuela, len(paginas))
    try:
        for pagina in paginas:
            area = documento.pagina(f"{solucion.nombre} · {pagina.titulo}")
            assert pagina.cuadricula is not None
            _dibujar_cuadricula(documento.pintor, area, pagina.cuadricula)
    finally:
        documento.cerrar()
    return ruta, len(paginas)


def exportar_suplencias_del_dia_pdf(
    escuela: str,
    fecha: date,
    filas: Sequence[FilaSuplencia],
    ausencias: Sequence[tuple[str, Ausencia]],
    ruta: Path | str,
) -> Path:
    """El reporte «Suplencias del día» en una página (§14)."""
    ruta = Path(ruta)
    documento = _Documento(ruta, escuela, 1)
    p = documento.pintor
    try:
        area = documento.pagina("Suplencias del día")
        p.setPen(QColor("#000000"))
        p.setFont(_fuente(13, negrita=True))
        linea = QFontMetricsF(p.font()).height() * 1.4
        p.drawText(QRectF(area.left(), area.top(), area.width(), linea),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   f"Suplencias del {texto_fecha(fecha)}")  # fmt: skip
        y = area.top() + linea
        p.setFont(_fuente(9))
        alto_texto = QFontMetricsF(p.font()).height() * 1.3
        for nombre, a in ausencias:
            horas = "todo el día"
            if a.desde is not None and a.hasta is not None:
                horas = texto_rango(a.desde, a.hasta)
            motivo = f" — {a.motivo}" if a.motivo else ""
            p.drawText(QRectF(area.left(), y, area.width(), alto_texto),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       f"Ausente: {nombre} ({horas}){motivo}")  # fmt: skip
            y += alto_texto
        y += alto_texto * 0.5
        columnas = ["Horario", "Asignatura", "Grupos", "Ausente", "Suplente", "Estado", "Nota"]
        anchos = [0.10, 0.17, 0.13, 0.15, 0.15, 0.10, 0.20]
        filas_texto = [[f.horas, f.asignatura, f.grupos, f.ausente, f.suplente or "—", f.estado,
                        f.nota] for f in filas]  # fmt: skip
        if not filas_texto:
            filas_texto = [["", "No hay clases afectadas en esta fecha.", "", "", "", "", ""]]
        alto = min(28.0, (area.bottom() - y) / (len(filas_texto) + 1))
        borde = QPen(QColor("#808080"))
        for i, valores in enumerate([columnas, *filas_texto]):
            izquierda = area.left()
            for j, valor in enumerate(valores):
                rect = QRectF(izquierda, y, area.width() * anchos[j], alto)
                if i == 0:
                    p.fillRect(rect, QColor("#EEEEEE"))
                p.setPen(borde)
                p.drawRect(rect)
                pendiente = i > 0 and j == 5 and valor not in ("Cubierta", "")
                p.setPen(QColor("#B71C1C" if pendiente else "#000000"))
                _texto_ajustado(p, rect, valor, 9, negrita=i == 0 or pendiente)
                izquierda += area.width() * anchos[j]
            y += alto
    finally:
        documento.cerrar()
    return ruta
