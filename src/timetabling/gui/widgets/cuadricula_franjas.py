"""Creado con Claude.

Editor de franjas prohibidas y preferidas sobre la cuadrícula de un nivel (§17, Asignaturas).
Cada celda (día × hora) alterna entre normal, prohibida (🚫) y preferida (★) con un clic o con
la barra espaciadora. El resultado son rangos por índice, uno por tramo consecutivo de cada día.
Si la cuadrícula no se toca, se conservan los rangos originales (también los definidos por
horas).
"""

from collections.abc import Sequence
from typing import Literal

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QKeyEvent
from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem, QWidget

from timetabling.dominio.modelos import RangoFranjas
from timetabling.dominio.tiempo import NOMBRES_DIAS, Dia, texto_rango
from timetabling.nucleo.franjas import Franja, en_rango

Estado = Literal["", "prohibida", "preferida"]
SIGUIENTE: dict[Estado, Estado] = {"": "prohibida", "prohibida": "preferida", "preferida": ""}
SIMBOLO: dict[Estado, str] = {"": "", "prohibida": "🚫", "preferida": "★"}
DESCRIPCION: dict[Estado, str] = {"": "Normal", "prohibida": "Prohibida", "preferida": "Preferida"}
COLOR: dict[Estado, str] = {"": "#FFFFFF", "prohibida": "#BDBDBD", "preferida": "#C8E6C9"}


class CuadriculaFranjas(QTableWidget):
    cambiado = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.dias: list[Dia] = []
        self.horas = 0
        self.estados: dict[tuple[Dia, int], Estado] = {}
        self.modificada = False
        self._originales: tuple[list[RangoFranjas], list[RangoFranjas]] = ([], [])
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.horizontalHeader().setMinimumSectionSize(36)
        self.setMinimumWidth(320)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setMinimumHeight(180)
        self.setAccessibleName("Cuadrícula de franjas prohibidas y preferidas")
        self.cellClicked.connect(self.alternar)

    def configurar(self, franjas_por_dia: dict[Dia, list[Franja]], etiquetas: bool = True) -> None:
        self.dias = list(franjas_por_dia)
        self.horas = max((len(v) for v in franjas_por_dia.values()), default=0)
        self._franjas = franjas_por_dia
        self.setColumnCount(len(self.dias))
        self.setRowCount(self.horas)
        self.setHorizontalHeaderLabels(list(self.dias))
        for j, dia in enumerate(self.dias):
            self.horizontalHeaderItem(j).setToolTip(NOMBRES_DIAS[dia])
        primeras = next(iter(franjas_por_dia.values()), [])
        self.setVerticalHeaderLabels(
            [
                f"{i + 1}. {texto_rango(primeras[i].inicio, primeras[i].fin)}"
                if etiquetas and i < len(primeras)
                else f"{i + 1}"
                for i in range(self.horas)
            ]
        )

    def poner(self, prohibidas: Sequence[RangoFranjas], preferidas: Sequence[RangoFranjas]) -> None:
        self._originales = (list(prohibidas), list(preferidas))
        self.modificada = False
        self.estados = {}
        for dia, franjas in self._franjas.items():
            for franja in franjas:
                estado: Estado = ""
                if any(en_rango(r, franja, completa=False) for r in prohibidas):
                    estado = "prohibida"
                elif preferidas and any(en_rango(r, franja, completa=True) for r in preferidas):
                    estado = "preferida"
                self.estados[(dia, franja.indice)] = estado
        self._pintar()

    def _pintar(self) -> None:
        for j, dia in enumerate(self.dias):
            indices = {f.indice for f in self._franjas.get(dia, [])}
            for i in range(self.horas):
                item = QTableWidgetItem()
                if i in indices:
                    estado = self.estados.get((dia, i), "")
                    item.setText(SIMBOLO[estado])
                    item.setToolTip(f"{NOMBRES_DIAS[dia]}, hora {i + 1}: {DESCRIPCION[estado]}")
                    item.setBackground(QBrush(QColor(COLOR[estado])))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                else:
                    item.setFlags(Qt.ItemFlag.NoItemFlags)
                self.setItem(i, j, item)

    def alternar(self, fila: int, columna: int) -> None:
        if not 0 <= columna < len(self.dias):
            return
        clave = (self.dias[columna], fila)
        if clave not in self.estados:
            return
        self.estados[clave] = SIGUIENTE[self.estados[clave]]
        self.modificada = True
        self._pintar()
        self.setCurrentCell(fila, columna)
        self.cambiado.emit()

    def keyPressEvent(self, evento: QKeyEvent) -> None:  # noqa: N802 - API de Qt
        if evento.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.alternar(self.currentRow(), self.currentColumn())
            return
        super().keyPressEvent(evento)

    def poner_estado(self, dia: Dia, indice: int, estado: Estado) -> None:
        self.estados[(dia, indice)] = estado
        self.modificada = True
        self._pintar()
        self.cambiado.emit()

    def rangos(self) -> tuple[list[RangoFranjas], list[RangoFranjas]]:
        """`(prohibidas, preferidas)` como rangos por índice (o los originales si no hubo
        cambios)."""
        if not self.modificada:
            return self._originales
        resultado: dict[Estado, list[RangoFranjas]] = {"prohibida": [], "preferida": []}
        for dia in self.dias:
            for estado in ("prohibida", "preferida"):
                indices = sorted(
                    i for (d, i), e in self.estados.items() if d == dia and e == estado
                )
                inicio = None
                for k, indice in enumerate(indices):
                    if inicio is None:
                        inicio = indice
                    fin_tramo = k + 1 == len(indices) or indices[k + 1] != indice + 1
                    if fin_tramo:
                        resultado[estado].append(
                            RangoFranjas(dias=(dia,), desde_indice=inicio, hasta_indice=indice)
                        )
                        inicio = None
        return resultado["prohibida"], resultado["preferida"]
