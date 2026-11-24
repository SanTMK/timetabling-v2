"""Creado con Claude.

Campos de formulario: hora (HH:MM), selector de días, lista marcable y tabla de filas
editables (recesos, eventos, bloqueos, divisiones…). Todos emiten `cambiado`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from PySide6.QtCore import Qt, QTime, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from timetabling.dominio.tiempo import DIAS, NOMBRES_DIAS, Dia


class HoraEdit(QTimeEdit):
    """Hora HH:MM con valor en minutos desde medianoche."""

    def __init__(self, minutos: int = 480, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDisplayFormat("HH:mm")
        self.poner(minutos)

    def minutos(self) -> int:
        t = self.time()
        return t.hour() * 60 + t.minute()

    def poner(self, minutos: int) -> None:
        minutos = min(max(minutos, 0), 24 * 60 - 1)
        self.setTime(QTime(minutos // 60, minutos % 60))


class DiasSelector(QWidget):
    cambiado = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        capa = QHBoxLayout(self)
        capa.setContentsMargins(0, 0, 0, 0)
        self.casillas: dict[Dia, QCheckBox] = {}
        for dia in DIAS:
            casilla = QCheckBox(dia)
            casilla.setToolTip(NOMBRES_DIAS[dia])
            casilla.setAccessibleName(NOMBRES_DIAS[dia])
            casilla.toggled.connect(self.cambiado)
            capa.addWidget(casilla)
            self.casillas[dia] = casilla
        capa.addStretch()

    def dias(self) -> list[Dia]:
        return [d for d, c in self.casillas.items() if c.isChecked()]

    def poner(self, dias: Sequence[Dia]) -> None:
        for dia, casilla in self.casillas.items():
            casilla.blockSignals(True)
            casilla.setChecked(dia in dias)
            casilla.blockSignals(False)
        self.cambiado.emit()


class ListaMarcable(QListWidget):
    """Lista de opciones `(id, texto)` con casillas."""

    cambiado = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.itemChanged.connect(lambda _item: self.cambiado.emit())
        self.setMaximumHeight(140)

    def poner(self, opciones: Sequence[tuple[int, str]], marcados: Sequence[int]) -> None:
        self.blockSignals(True)
        self.clear()
        for ident, texto in opciones:
            item = QListWidgetItem(texto)
            item.setData(Qt.ItemDataRole.UserRole, ident)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if ident in marcados else Qt.CheckState.Unchecked
            )
            self.addItem(item)
        self.blockSignals(False)

    def marcados(self) -> list[int]:
        return [
            int(self.item(i).data(Qt.ItemDataRole.UserRole))
            for i in range(self.count())
            if self.item(i).checkState() == Qt.CheckState.Checked
        ]

    def marcar(self, idents: Sequence[int]) -> None:
        """Marca exactamente esos ids (útil en pruebas y atajos)."""
        for i in range(self.count()):
            item = self.item(i)
            ident = int(item.data(Qt.ItemDataRole.UserRole))
            item.setCheckState(
                Qt.CheckState.Checked if ident in idents else Qt.CheckState.Unchecked
            )


TipoColumna = Literal["texto", "dia", "hora", "entero", "booleano", "opcion"]


@dataclass(frozen=True)
class Columna:
    clave: str
    titulo: str
    tipo: TipoColumna
    defecto: Any = None
    minimo: int = 0
    maximo: int = 9999
    opciones: tuple[tuple[Any, str], ...] = ()


class TablaFilas(QWidget):
    """Tabla de filas editables con botones «Agregar» y «Quitar»."""

    cambiado = Signal()

    def __init__(self, columnas: Sequence[Columna], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.columnas = list(columnas)
        capa = QVBoxLayout(self)
        capa.setContentsMargins(0, 0, 0, 0)
        self.tabla = QTableWidget(0, len(self.columnas))
        self.tabla.setHorizontalHeaderLabels([c.titulo for c in self.columnas])
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla.setMinimumHeight(90)
        self.tabla.setMaximumHeight(180)
        capa.addWidget(self.tabla)
        botones = QHBoxLayout()
        self.boton_agregar = QPushButton("Agregar")
        self.boton_quitar = QPushButton("Quitar")
        self.boton_agregar.clicked.connect(lambda: self.agregar())
        self.boton_quitar.clicked.connect(self.quitar_seleccionada)
        botones.addWidget(self.boton_agregar)
        botones.addWidget(self.boton_quitar)
        botones.addStretch()
        capa.addLayout(botones)

    def _editor(self, columna: Columna, valor: Any) -> QWidget:
        if columna.tipo == "texto":
            editor = QLineEdit("" if valor is None else str(valor))
            editor.textChanged.connect(self.cambiado)
            return editor
        if columna.tipo in ("dia", "opcion"):
            editor = QComboBox()
            opciones = (
                [(d, NOMBRES_DIAS[d]) for d in DIAS] if columna.tipo == "dia" else columna.opciones
            )
            for clave, texto in opciones:
                editor.addItem(texto, clave)
            indice = editor.findData(valor)
            editor.setCurrentIndex(max(indice, 0))
            editor.currentIndexChanged.connect(self.cambiado)
            return editor
        if columna.tipo == "hora":
            editor = HoraEdit(480 if valor is None else int(valor))
            editor.timeChanged.connect(self.cambiado)
            return editor
        if columna.tipo == "entero":
            editor = QSpinBox()
            editor.setRange(columna.minimo, columna.maximo)
            editor.setValue(int(valor if valor is not None else columna.minimo))
            editor.valueChanged.connect(self.cambiado)
            return editor
        editor = QCheckBox()
        editor.setChecked(bool(valor))
        editor.toggled.connect(self.cambiado)
        return editor

    def agregar(self, valores: dict[str, Any] | None = None) -> None:
        valores = valores or {}
        fila = self.tabla.rowCount()
        self.tabla.insertRow(fila)
        for j, columna in enumerate(self.columnas):
            self.tabla.setCellWidget(
                fila, j, self._editor(columna, valores.get(columna.clave, columna.defecto))
            )
        self.cambiado.emit()

    def quitar_seleccionada(self) -> None:
        fila = self.tabla.currentRow()
        if fila < 0:
            fila = self.tabla.rowCount() - 1
        if fila >= 0:
            self.tabla.removeRow(fila)
            self.cambiado.emit()

    def _valor(self, columna: Columna, editor: QWidget) -> Any:
        if isinstance(editor, QLineEdit):
            return editor.text()
        if isinstance(editor, QComboBox):
            return editor.currentData()
        if isinstance(editor, HoraEdit):
            return editor.minutos()
        if isinstance(editor, QSpinBox):
            return editor.value()
        if isinstance(editor, QCheckBox):
            return editor.isChecked()
        return None

    def filas(self) -> list[dict[str, Any]]:
        return [
            {
                c.clave: self._valor(c, self.tabla.cellWidget(i, j))
                for j, c in enumerate(self.columnas)
            }
            for i in range(self.tabla.rowCount())
        ]

    def poner(self, filas: Sequence[dict[str, Any]]) -> None:
        self.blockSignals(True)
        self.tabla.setRowCount(0)
        for fila in filas:
            self.agregar(fila)
        self.blockSignals(False)
