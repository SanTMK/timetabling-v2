"""Creado con Claude.

Vista de horario (§17): la misma disposición que Excel y PDF (`dominio/cuadricula.py`). Color
por asignatura con texto en contraste, recesos en gris, 📌 bloqueadas, ↻ en negrita para las
cambiadas y ⚠ en conflictos.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from timetabling.dominio.colores import GRIS_RECESO, color_texto
from timetabling.dominio.cuadricula import Cuadricula
from timetabling.dominio.tiempo import NOMBRES_DIAS


class VistaHorario(QTableWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setWordWrap(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.setAccessibleName("Horario")
        self.verticalHeader().setMinimumSectionSize(6)
        self.cuadricula: Cuadricula | None = None

    def mostrar(self, cuadricula: Cuadricula | None) -> None:
        self.clearSpans()
        self.clear()
        self.cuadricula = cuadricula
        if cuadricula is None:
            self.setRowCount(0)
            self.setColumnCount(0)
            return
        self.setRowCount(len(cuadricula.filas))
        self.setColumnCount(len(cuadricula.dias))
        self.setHorizontalHeaderLabels([NOMBRES_DIAS[d] for d in cuadricula.dias])
        fina = len(cuadricula.filas) > 30
        self.setVerticalHeaderLabels(
            [
                f.etiqueta if not fina else (f.etiqueta_inicio if f.inicio % 30 == 0 else "")
                for f in cuadricula.filas
            ]
        )
        alto = 8 if fina else 46
        fuente = QFont(self.font())
        if fina:
            fuente.setPointSizeF(max(6.0, fuente.pointSizeF() * 0.7))
        self.verticalHeader().setFont(fuente)
        for i, fila in enumerate(cuadricula.filas):
            self.setRowHeight(i, 22 if fila.receso else alto)
        for celda in cuadricula.celdas:
            item = QTableWidgetItem(celda.texto)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setToolTip(celda.texto)
            fondo = GRIS_RECESO if celda.tipo == "receso" else celda.color
            item.setBackground(QBrush(QColor(fondo)))
            item.setForeground(QBrush(QColor(color_texto(fondo))))
            if celda.cambiada:
                fuente = QFont(item.font())
                fuente.setBold(True)
                item.setFont(fuente)
            self.setItem(celda.fila, celda.columna, item)
            if celda.filas > 1 or celda.columnas > 1:
                self.setSpan(celda.fila, celda.columna, celda.filas, celda.columnas)

    def texto(self, fila: int, columna: int) -> str:
        item = self.item(fila, columna)
        return item.text() if item else ""
